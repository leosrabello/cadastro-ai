"""Review queue, dashboard, metrics, audit history, metadata and health."""

from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.orm import Session

from app import audit
from app.api.serializers import FIELD_LABELS, iso, registration_row
from app.config import get_settings
from app.db import get_db
from app.deps import ANY_ROLE, AUDIT_READERS, SUPERVISORS, Principal
from app.models import (
    AuditEvent,
    Decision,
    DocStatus,
    Document,
    Finding,
    FindingStatus,
    IngestRecord,
    ProcessingJob,
    RegStatus,
    Registration,
    Role,
    WatcherStatus,
    utcnow,
)
from app.ratelimit import _client as redis_client
from app.settings_store import get_setting
from app.storage import get_store

router = APIRouter(prefix="/api", tags=["operations"])

QUEUE_STATUSES = (RegStatus.AWAITING_REVIEW, RegStatus.PROCESSING_FAILED)


@router.get("/queue")
def review_queue(
    scope: Literal["all", "escalated", "ready", "failed"] = "all",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    p: Principal = Depends(ANY_ROLE),
    db: Session = Depends(get_db),
):
    stmt = select(Registration).where(Registration.status.in_(QUEUE_STATUSES))
    if scope == "ready":
        stmt = stmt.where(Registration.ready_for_decision.is_(True))
    elif scope == "failed":
        stmt = stmt.where(Registration.status == RegStatus.PROCESSING_FAILED)
    elif scope == "escalated":
        esc = select(Finding.registration_id).where(Finding.status == FindingStatus.ESCALATED)
        stmt = stmt.where(Registration.id.in_(esc))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(Registration.priority_score.desc(), Registration.created_at.asc()).offset((page - 1) * page_size).limit(page_size)
    ).scalars().all()
    return {
        "items": [registration_row(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "rules": get_setting(db, "priority_rules"),
    }


@router.get("/dashboard")
def dashboard(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    def count_regs(*conds):
        return db.execute(select(func.count(Registration.id)).where(*conds)).scalar_one()

    now = utcnow()
    week = now - timedelta(days=7)
    start_today = datetime.combine(date.today(), time.min, tzinfo=timezone.utc)
    docs_in_flight = db.execute(select(func.count(Document.id)).where(Document.status.in_((DocStatus.QUEUED, DocStatus.PROCESSING)))).scalar_one()
    docs_failed = db.execute(select(func.count(Document.id)).where(Document.status == DocStatus.FAILED)).scalar_one()
    inbox = db.execute(select(func.count(Document.id)).where(Document.registration_id.is_(None), Document.status != DocStatus.PURGED)).scalar_one()
    escalated = db.execute(
        select(func.count(func.distinct(Finding.registration_id))).where(Finding.status == FindingStatus.ESCALATED)
    ).scalar_one()
    missing_docs = db.execute(
        select(func.count(Registration.id)).where(
            Registration.status.notin_(RegStatus.FINAL),
            text("EXISTS (SELECT 1 FROM jsonb_array_elements(registrations.checklist->'documents') i WHERE i->>'state' IN ('missing','unclassified'))"),
        )
    ).scalar_one()
    recent = db.execute(
        select(Registration).where(Registration.status.in_(RegStatus.FINAL), Registration.decided_at >= week).order_by(Registration.decided_at.desc()).limit(8)
    ).scalars().all()
    top = db.execute(
        select(Registration).where(Registration.status.in_(QUEUE_STATUSES)).order_by(Registration.priority_score.desc(), Registration.created_at).limit(6)
    ).scalars().all()
    jobs_24h = db.execute(select(ProcessingJob.duration_ms).where(ProcessingJob.finished_at >= now - timedelta(hours=24), ProcessingJob.status == "done")).scalars().all()
    watcher = db.get(WatcherStatus, 1)
    decided_today = db.execute(select(func.count(Decision.id)).where(Decision.decided_at >= start_today, Decision.action.in_(("approve", "reject", "request_documents")))).scalar_one()
    processing_cfg = get_setting(db, "processing")
    s = get_settings()
    return {
        "counts": {
            "awaiting_processing": count_regs(Registration.status.in_((RegStatus.AWAITING_PROCESSING, RegStatus.PROCESSING))),
            "documents_in_flight": docs_in_flight,
            "awaiting_review": count_regs(Registration.status == RegStatus.AWAITING_REVIEW),
            "ready_for_decision": count_regs(Registration.status == RegStatus.AWAITING_REVIEW, Registration.ready_for_decision.is_(True)),
            "escalated": escalated,
            "missing_documents": missing_docs,
            "pending_documents": count_regs(Registration.status == RegStatus.PENDING_DOCUMENTS),
            "processing_failed": count_regs(Registration.status == RegStatus.PROCESSING_FAILED),
            "documents_failed": docs_failed,
            "inbox": inbox,
            "decided_today": decided_today,
        },
        "next_up": [registration_row(r) for r in top],
        "recently_completed": [registration_row(r) for r in recent],
        "processing": {
            "jobs_24h": len(jobs_24h),
            "avg_seconds_24h": round(sum(j or 0 for j in jobs_24h) / len(jobs_24h) / 1000, 1) if jobs_24h else None,
        },
        "watcher": {
            "folder": watcher.folder if watcher else None,
            "reachable": watcher.reachable if watcher else False,
            "last_scan_at": iso(watcher.last_scan_at) if watcher else None,
            "last_error": watcher.last_error if watcher else None,
            "pending_files": watcher.pending_files if watcher else 0,
            "enabled": get_setting(db, "watcher").get("enabled", False),
        },
        "ai": {"configured": s.ai_configured, "enabled": bool(processing_cfg.get("ai_enabled")), "model": s.ai_model if s.ai_configured else None},
        "ocr": {"provider": s.ocr_provider},
    }


@router.get("/metrics")
def metrics(days: int = Query(30, ge=1, le=365), p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    since = utcnow() - timedelta(days=days)
    jobs = db.execute(select(ProcessingJob).where(ProcessingJob.finished_at >= since, ProcessingJob.status == "done")).scalars().all()
    durations = sorted(j.duration_ms or 0 for j in jobs)
    ai_cost = sum(float((j.metrics or {}).get("ai_cost_usd") or 0) for j in jobs)
    pages = sum(int((j.metrics or {}).get("pages") or 0) for j in jobs)
    decided = db.execute(select(Registration).where(Registration.decided_at >= since, Registration.status.in_(RegStatus.FINAL))).scalars().all()
    approved_clean = 0
    for r in decided:
        touched = db.execute(select(func.count(Finding.id)).where(Finding.registration_id == r.id, Finding.status.in_((FindingStatus.ACCEPTED, FindingStatus.OVERRIDDEN, FindingStatus.ESCALATED)))).scalar_one()
        approved_clean += 1 if touched == 0 else 0
    corrected = db.execute(text("SELECT count(*) FROM extracted_fields f JOIN documents d ON d.id=f.document_id WHERE f.status='corrected' AND d.processed_at >= :s"), {"s": since}).scalar_one()
    confirmed = db.execute(text("SELECT count(*) FROM extracted_fields f JOIN documents d ON d.id=f.document_id WHERE f.status='confirmed' AND d.processed_at >= :s"), {"s": since}).scalar_one()
    by_code = db.execute(
        select(Finding.code, Finding.status, func.count()).where(Finding.created_at >= since).group_by(Finding.code, Finding.status)
    ).all()
    codes: dict[str, dict] = {}
    for code, status, n in by_code:
        codes.setdefault(code, {})[status] = n
    return {
        "period_days": days,
        "documents_processed": len(jobs),
        "pages_processed": pages,
        "processing_seconds": {
            "avg": round(sum(durations) / len(durations) / 1000, 2) if durations else None,
            "p95": round(durations[int(len(durations) * 0.95) - 1] / 1000, 2) if durations else None,
        },
        "ai_cost_usd": round(ai_cost, 4),
        "ai_cost_per_document_usd": round(ai_cost / len(jobs), 5) if jobs else None,
        "registrations_decided": len(decided),
        "decided_without_manual_findings": approved_clean,
        "fields_reviewed": {"confirmed": confirmed, "corrected": corrected,
                            "correction_rate": round(corrected / (corrected + confirmed), 3) if (corrected + confirmed) else None},
        "findings_by_code": codes,
        "note": "Taxas de acerto de campos e de indícios exigem um conjunto rotulado; veja backend/scripts/evaluate.py.",
    }


@router.get("/audit")
def audit_history(
    q: str | None = Query(None, max_length=100),
    action: str | None = None,
    registration_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    p: Principal = Depends(AUDIT_READERS),
    db: Session = Depends(get_db),
):
    stmt = select(AuditEvent, Registration.code).outerjoin(Registration, Registration.id == AuditEvent.registration_id)
    conds = []
    if q:
        like = f"%{q}%"
        conds.append(or_(AuditEvent.actor_label.ilike(like), AuditEvent.action.ilike(like), Registration.code.ilike(like), AuditEvent.entity_id.ilike(like)))
    if action:
        conds.append(AuditEvent.action.like(f"{action}%"))
    if registration_id:
        conds.append(AuditEvent.registration_id == registration_id)
    if date_from:
        conds.append(AuditEvent.at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc))
    if date_to:
        conds.append(AuditEvent.at < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc))
    if conds:
        stmt = stmt.where(and_(*conds))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {
        "items": [
            {"id": e.id, "at": iso(e.at), "actor": e.actor_label, "action": e.action, "entity_type": e.entity_type,
             "entity_id": e.entity_id, "registration_id": str(e.registration_id) if e.registration_id else None,
             "registration_code": code, "details": e.details, "ip": e.ip, "hash": e.hash}
            for e, code in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/audit/verify")
def audit_verify(p: Principal = Depends(AUDIT_READERS), db: Session = Depends(get_db)):
    return audit.verify_chain(db)


@router.get("/meta")
def meta(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    doc_types = get_setting(db, "document_types")
    profiles = get_setting(db, "requirement_profiles")
    approval = get_setting(db, "approval")
    role = p.role
    return {
        "user": {"id": str(p.user.id), "name": p.user.name, "email": p.user.email, "role": role},
        "document_types": {k: {"label": v.get("label", k), "fields": v.get("fields", [])} for k, v in doc_types.items()},
        "profiles": {k: {"label": v.get("label", k), "tax_id_kind": v.get("tax_id_kind", "cpf")} for k, v in profiles.items()},
        "field_labels": FIELD_LABELS,
        "statuses": list(RegStatus.ALL),
        "roles": list(Role.ALL),
        "permissions": {
            "operate": role in (Role.ANALYST, Role.SUPERVISOR, Role.ADMIN),
            "approve": role in approval.get("approve_roles", []),
            "reject": role in approval.get("reject_roles", []),
            "override": role in approval.get("override_roles", []),
            "audit": role in (Role.SUPERVISOR, Role.ADMIN, Role.AUDITOR),
            "admin": role == Role.ADMIN,
        },
        "limits": {"max_upload_mb": get_settings().max_upload_mb, "accepted": [".pdf", ".jpg", ".jpeg", ".png"]},
    }


@router.get("/ingest-records")
def ingest_records(page: int = Query(1, ge=1), p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    rows = db.execute(select(IngestRecord).order_by(IngestRecord.created_at.desc()).offset((page - 1) * 50).limit(50)).scalars().all()
    return {"items": [{"id": str(r.id), "source_ref": r.source_ref, "status": r.status, "detail": r.detail, "created_at": iso(r.created_at),
                       "document_id": str(r.document_id) if r.document_id else None} for r in rows]}


@router.get("/health")
def health(db: Session = Depends(get_db)):
    checks = {"database": False, "queue": False, "storage": False}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        pass
    try:
        checks["queue"] = bool(redis_client().ping())
    except Exception:
        pass
    checks["storage"] = get_store().healthy()
    return {"ok": all(checks.values()), "checks": checks, "version": get_settings().pipeline_version}
