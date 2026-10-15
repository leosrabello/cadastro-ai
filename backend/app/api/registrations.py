import hashlib
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import audit
from app.api.serializers import decision_out, document_brief, finding_out, iso, registration_row, user_brief
from app.db import get_db
from app.deps import ANY_ROLE, OPERATORS, SUPERVISORS, ADMINS, Principal
from app.errors import ApiError
from app.models import (
    AuditEvent,
    Counter,
    Decision,
    DocStatus,
    Document,
    Finding,
    FindingStatus,
    Modality,
    PortfolioClient,
    RegStatus,
    Registration,
    utcnow,
)
from app.pipeline.normalize import digits, valid_cnpj, valid_cpf
from app.pipeline.orchestrator import analyze_registration
from app.retention import purge_registration
from app.settings_store import get_setting

router = APIRouter(prefix="/api/registrations", tags=["registrations"])

CHECK_STATE_LABELS = {
    "missing": "falta",
    "unclassified": "recebido sem tipo identificado",
    "processing": "em análise",
    "failed": "falha na análise",
    "expired": "vencido",
    "too_old": "emitido há tempo demais",
    "invalid": "situação inválida",
    "needs_review": "precisa de conferência",
}


class RegistrationIn(BaseModel):
    kind: str = Field(min_length=1, max_length=32)
    modality: Literal["normal", "one7"]  # required: no default, the analyst chooses
    client_id: uuid.UUID | None = None
    subject_name: str = Field(min_length=3, max_length=300)
    tax_id: str | None = Field(None, max_length=32)
    reference_fields: dict[str, str] = Field(default_factory=dict)

    @field_validator("reference_fields")
    @classmethod
    def _small(cls, v: dict) -> dict:
        if len(v) > 20 or any(len(k) > 60 or len(str(x)) > 300 for k, x in v.items()):
            raise ValueError("campos de referência longos demais")
        return v


class RegistrationPatch(BaseModel):
    subject_name: str | None = Field(None, min_length=3, max_length=300)
    modality: Literal["normal", "one7"] | None = None
    client_id: uuid.UUID | None = None
    clear_client: bool = False
    tax_id: str | None = Field(None, max_length=32)
    reference_fields: dict[str, str] | None = None


class DecisionIn(BaseModel):
    action: Literal["approve", "request_documents", "reject", "escalate", "reopen"]
    reason: str | None = Field(None, max_length=2000)
    requested_items: list[str] = Field(default_factory=list, max_length=20)
    override: bool = False


class HoldIn(BaseModel):
    hold: bool
    reason: str = Field(min_length=10, max_length=1000)


class PurgeIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


def _validate_tax_id(kind_profile: dict, tax_id: str | None) -> str | None:
    if not tax_id:
        return None
    d = digits(tax_id)
    kind = kind_profile.get("tax_id_kind", "cpf")
    if kind == "cpf" and not valid_cpf(d):
        raise ApiError(422, "invalid_tax_id", "CPF inválido: confira os dígitos.")
    if kind == "cnpj" and not valid_cnpj(d):
        raise ApiError(422, "invalid_tax_id", "CNPJ inválido: confira os dígitos.")
    return d


def next_code(db: Session) -> str:
    year = utcnow().year
    row = db.execute(select(Counter).where(Counter.name == "registration", Counter.year == year).with_for_update()).scalar_one_or_none()
    if row is None:
        row = Counter(name="registration", year=year, value=0)
        db.add(row)
        db.flush()
    row.value += 1
    return f"CAD-{year}-{row.value:06d}"


def _portfolio_client(db: Session, client_id: uuid.UUID | None, modality: str) -> PortfolioClient | None:
    if client_id is None:
        return None
    client = db.get(PortfolioClient, client_id)
    if client is None:
        raise ApiError(422, "invalid_client", "Cliente da carteira não encontrado.")
    if client.modality != modality:
        raise ApiError(422, "modality_mismatch", f"O cliente escolhido é da carteira {Modality.LABELS[client.modality]}; a modalidade do cadastro precisa ser a mesma.")
    return client


def get_registration(db: Session, rid: uuid.UUID) -> Registration:
    reg = db.get(Registration, rid)
    if reg is None:
        raise ApiError(404, "not_found", "Cadastro não encontrado.")
    return reg


@router.get("")
def list_registrations(
    q: str | None = Query(None, max_length=100),
    status: str | None = None,
    kind: str | None = None,
    modality: Literal["normal", "one7"] | None = None,
    ready: bool | None = None,
    sort: Literal["priority", "created", "updated", "name", "code"] = "priority",
    direction: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    p: Principal = Depends(ANY_ROLE),
    db: Session = Depends(get_db),
):
    doc_count = select(func.count(Document.id)).where(Document.registration_id == Registration.id).correlate(Registration).scalar_subquery()
    stmt = select(Registration, doc_count.label("docs"))
    if q:
        like = f"%{q.strip()}%"
        conds = [Registration.code.ilike(like), Registration.subject_name.ilike(like)]
        if digits(q):
            conds.append(Registration.tax_id.like(f"%{digits(q)}%"))
        stmt = stmt.where(or_(*conds))
    if status:
        stmt = stmt.where(Registration.status.in_([s for s in status.split(",") if s in RegStatus.ALL]))
    if kind:
        stmt = stmt.where(Registration.kind == kind)
    if modality:
        stmt = stmt.where(Registration.modality == modality)
    if ready is not None:
        stmt = stmt.where(Registration.ready_for_decision.is_(ready))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    col = {
        "priority": Registration.priority_score,
        "created": Registration.created_at,
        "updated": Registration.updated_at,
        "name": Registration.subject_name,
        "code": Registration.code,
    }[sort]
    order = col.desc() if direction == "desc" else col.asc()
    stmt = stmt.order_by(order, Registration.created_at.asc()).offset((page - 1) * page_size).limit(page_size)
    rows = db.execute(stmt).all()
    return {"items": [registration_row(r, docs) for r, docs in rows], "total": total, "page": page, "page_size": page_size}


@router.post("", status_code=201)
def create_registration(body: RegistrationIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    profiles = get_setting(db, "requirement_profiles")
    if body.kind not in profiles:
        raise ApiError(422, "invalid_kind", "Tipo de cadastro desconhecido.")
    tax_id = _validate_tax_id(profiles[body.kind], body.tax_id)
    client = _portfolio_client(db, body.client_id, body.modality)
    reg = Registration(
        code=next_code(db),
        kind=body.kind,
        modality=body.modality,
        client=client,
        subject_name=" ".join(body.subject_name.split()).upper(),
        tax_id=tax_id,
        reference_fields=body.reference_fields,
        status=RegStatus.AWAITING_PROCESSING,
        created_by_id=p.user.id,
    )
    db.add(reg)
    db.flush()
    analyze_registration(db, reg.id)
    audit.record(db, "registration.created", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id,
                 details={"code": reg.code, "kind": reg.kind, "modality": reg.modality}, ip=p.ip)
    db.commit()
    return registration_row(reg, 0)


@router.get("/{rid}")
def registration_detail(rid: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    docs = db.execute(select(Document).where(Document.registration_id == reg.id).order_by(Document.received_at)).scalars().all()
    findings = db.execute(
        select(Finding).options(selectinload(Finding.resolved_by))
        .where(Finding.registration_id == reg.id, Finding.status != FindingStatus.SUPERSEDED)
        .order_by(Finding.created_at)
    ).scalars().all()
    decisions = db.execute(
        select(Decision).options(selectinload(Decision.decided_by)).where(Decision.registration_id == reg.id).order_by(Decision.decided_at.desc())
    ).scalars().all()
    events = db.execute(
        select(AuditEvent).where(AuditEvent.registration_id == reg.id).order_by(AuditEvent.id.desc()).limit(200)
    ).scalars().all()
    audit.record(db, "registration.viewed", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id, ip=p.ip)
    db.commit()
    return {
        **registration_row(reg, len(docs)),
        "reference_fields": reg.reference_fields or {},
        "checklist": reg.checklist or {},
        "decision_reason": reg.decision_reason,
        "decided_by": user_brief(reg.decided_by),
        "created_by": user_brief(reg.created_by),
        "legal_hold": reg.legal_hold,
        "anonymized_at": iso(reg.anonymized_at),
        "last_analysis_at": iso(reg.last_analysis_at),
        "documents": [document_brief(d) for d in docs],
        "findings": [finding_out(f) for f in findings],
        "decisions": [decision_out(d) for d in decisions],
        "history": [
            {"id": e.id, "at": iso(e.at), "actor": e.actor_label, "action": e.action, "entity_type": e.entity_type,
             "entity_id": e.entity_id, "details": e.details}
            for e in events if e.action != "registration.viewed"
        ],
    }


@router.patch("/{rid}")
def update_registration(rid: uuid.UUID, body: RegistrationPatch, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    if reg.status in RegStatus.CLOSED:
        raise ApiError(409, "registration_closed", "Cadastro reprovado. Reabra-o antes de editar.")
    before = {"subject_name": reg.subject_name, "tax_id": reg.tax_id, "reference_fields": reg.reference_fields,
              "modality": reg.modality, "client_id": str(reg.client_id) if reg.client_id else None}
    if body.modality is not None:
        reg.modality = body.modality
    if body.clear_client:
        reg.client = None
    elif body.client_id is not None:
        reg.client = _portfolio_client(db, body.client_id, reg.modality)
    elif reg.client_id and body.modality is not None:
        _portfolio_client(db, reg.client_id, reg.modality)
    if body.subject_name is not None:
        reg.subject_name = " ".join(body.subject_name.split()).upper()
    if body.tax_id is not None:
        reg.tax_id = _validate_tax_id(get_setting(db, "requirement_profiles").get(reg.kind, {}), body.tax_id)
    if body.reference_fields is not None:
        reg.reference_fields = body.reference_fields
    analyze_registration(db, reg.id)
    audit.record(db, "registration.updated", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id,
                 details={"before": before, "after": {"subject_name": reg.subject_name, "tax_id": reg.tax_id, "reference_fields": reg.reference_fields,
                                                      "modality": reg.modality, "client_id": str(reg.client_id) if reg.client_id else None}}, ip=p.ip)
    db.commit()
    return registration_row(reg)


@router.post("/{rid}/reanalyze")
def reanalyze(rid: uuid.UUID, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    analyze_registration(db, reg.id)
    audit.record(db, "registration.reanalyzed", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id, ip=p.ip)
    db.commit()
    return registration_row(reg)


@router.post("/{rid}/decisions", status_code=201)
def decide(rid: uuid.UUID, body: DecisionIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    reg = db.execute(select(Registration).where(Registration.id == rid).with_for_update()).scalar_one_or_none()
    if reg is None:
        raise ApiError(404, "not_found", "Cadastro não encontrado.")
    policy = get_setting(db, "approval")
    reason = (body.reason or "").strip()
    overrides: list[dict] = []

    if body.action == "reopen":
        if p.role not in ("supervisor", "admin"):
            raise ApiError(403, "forbidden", "Somente supervisores reabrem cadastros.")
        if len(reason) < 10:
            raise ApiError(422, "reason_required", "Explique o motivo da reabertura (mínimo 10 caracteres).")
        if reg.status not in (*RegStatus.FINAL, RegStatus.PENDING_DOCUMENTS):
            raise ApiError(409, "invalid_state", "Somente cadastros decididos podem ser reabertos.")
        if reg.anonymized_at:
            raise ApiError(409, "purged", "Os documentos e dados deste cadastro foram apagados após a reprovação. Abra um cadastro novo.")
        new_status = RegStatus.AWAITING_REVIEW
    elif reg.status in RegStatus.FINAL:
        raise ApiError(409, "registration_closed", "Cadastro já decidido.")
    elif body.action == "approve":
        if p.role not in policy.get("approve_roles", ["supervisor", "admin"]):
            raise ApiError(403, "forbidden", "Seu perfil não pode aprovar cadastros.")
        analyze_registration(db, reg.id)
        checklist = reg.checklist or {}
        if checklist.get("processing"):
            raise ApiError(409, "still_processing", "Há documentos em processamento. Aguarde a análise terminar.")
        blockers = []
        for item in checklist.get("documents", []):
            if item.get("blocking", True) and item.get("required", True) and item["state"] != "ok":
                blockers.append(f"{item['label']}: {CHECK_STATE_LABELS.get(item['state'], item['state'])}")
        for item in checklist.get("fields", []):
            if item["state"] != "ok":
                blockers.append(f"{item['label']}: não lido")
        for item in checklist.get("info", []):
            if item.get("blocking") and item["state"] != "ok":
                blockers.append(f"{item['label']}: não informado")
        open_findings = db.execute(
            select(Finding).where(Finding.registration_id == reg.id, Finding.status.in_(FindingStatus.OPEN_STATES))
        ).scalars().all()
        relevant = open_findings if not policy.get("allow_approve_with_open_findings") else [f for f in open_findings if f.severity in ("high", "critical")]
        blockers += [f"Ponto em aberto: {f.title}" for f in relevant if f.severity != "info"]
        if blockers:
            if not body.override:
                raise ApiError(409, "not_ready", "O cadastro tem pendências.", details=blockers)
            if p.role not in policy.get("override_roles", ["supervisor", "admin"]):
                raise ApiError(403, "forbidden", "Seu perfil não pode aprovar com pendências.")
            if len(reason) < 20:
                raise ApiError(422, "reason_required", "Aprovar com pendências exige justificativa (mínimo 20 caracteres).")
            overrides = [{"item": b} for b in blockers]
            now = utcnow()
            for f in relevant:
                f.status, f.resolved_by_id, f.resolved_at, f.resolution_note = FindingStatus.OVERRIDDEN, p.user.id, now, reason
        new_status = RegStatus.APPROVED
    elif body.action == "reject":
        if p.role not in policy.get("reject_roles", ["supervisor", "admin"]):
            raise ApiError(403, "forbidden", "Seu perfil não pode reprovar cadastros.")
        if len(reason) < 10:
            raise ApiError(422, "reason_required", "Explique o motivo da reprovação (mínimo 10 caracteres).")
        new_status = RegStatus.REJECTED
    elif body.action == "request_documents":
        items = [i.strip() for i in body.requested_items if i.strip()]
        if not items:
            raise ApiError(422, "items_required", "Indique quais documentos solicitar.")
        body.requested_items = items
        new_status = RegStatus.PENDING_DOCUMENTS
    else:  # escalate
        if len(reason) < 10:
            raise ApiError(422, "reason_required", "Explique o motivo do escalonamento (mínimo 10 caracteres).")
        db.add(Finding(
            registration_id=reg.id, fingerprint=hashlib.sha256(f"esc:{uuid.uuid4()}".encode()).hexdigest(),
            code="MANUAL_ESCALATION", category="review", severity="high", source="human", status=FindingStatus.ESCALATED,
            title=f"Escalado por {p.user.name}", explanation=reason, evidence=[], recommended_action="Supervisor: avaliar e registrar a decisão.",
        ))
        new_status = reg.status

    old = reg.status
    decision = Decision(registration_id=reg.id, action=body.action, reason=reason or None, requested_items=body.requested_items,
                        overrides=overrides, decided_by_id=p.user.id)
    db.add(decision)
    reg.status = new_status
    if body.action in ("approve", "reject", "request_documents"):
        reg.decided_by_id, reg.decided_at, reg.decision_reason = p.user.id, utcnow(), reason or None
    if body.action == "reopen":
        reg.decided_by_id, reg.decided_at, reg.decision_reason = None, None, None
    db.flush()
    analyze_registration(db, reg.id)
    audit.record(db, f"registration.{body.action}", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id,
                 details={"from": old, "to": reg.status, "reason": reason, "requested_items": body.requested_items, "overrides": overrides}, ip=p.ip)
    if body.action == "reject" and get_setting(db, "retention").get("rejected_days") == 0 and not reg.legal_hold:
        # LGPD necessity: a rejected prospect's documents have no further use; the decision and the audit trail stay
        purge_registration(db, reg, "reprovado: documentos apagados na decisão", actor=p.user)
    db.commit()
    return decision_out(decision)


@router.post("/{rid}/legal-hold")
def legal_hold(rid: uuid.UUID, body: HoldIn, p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    reg.legal_hold = body.hold
    audit.record(db, "registration.legal_hold", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id,
                 details={"hold": body.hold, "reason": body.reason}, ip=p.ip)
    db.commit()
    return {"legal_hold": reg.legal_hold}


@router.get("/{rid}/export")
def export_subject_data(rid: uuid.UUID, p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    """LGPD art. 18 access request: everything held about the data subject in this registration."""
    reg = get_registration(db, rid)
    docs = db.execute(select(Document).where(Document.registration_id == reg.id)).scalars().all()
    audit.record(db, "registration.exported", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id, ip=p.ip)
    db.commit()
    return {
        "registration": {"code": reg.code, "kind": reg.kind, "subject_name": reg.subject_name, "tax_id": reg.tax_id,
                         "reference_fields": reg.reference_fields, "status": reg.status, "created_at": iso(reg.created_at),
                         "decided_at": iso(reg.decided_at), "decision_reason": reg.decision_reason},
        "documents": [
            {"filename": d.original_filename, "received_at": iso(d.received_at), "doc_type": d.doc_type, "status": d.status,
             "fields": {f.name: f.value for f in d.fields}}
            for d in docs
        ],
        "processors": ["Armazenamento interno", "OCR: " + (docs[0].ocr_provider if docs and docs[0].ocr_provider else "tesseract (servidor próprio)")],
    }


@router.post("/{rid}/purge")
def purge(rid: uuid.UUID, body: PurgeIn, p: Principal = Depends(ADMINS), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    if reg.legal_hold:
        raise ApiError(409, "legal_hold", "Cadastro sob retenção legal; remova a retenção antes de expurgar.")
    if reg.status == RegStatus.APPROVED:
        raise ApiError(409, "retention_required", "Cadastros aprovados seguem o prazo legal de guarda e não podem ser expurgados por aqui.")
    count = purge_registration(db, reg, body.reason, actor=p.user)
    db.commit()
    return {"purged_documents": count}


__all__ = ["router", "get_registration", "DocStatus"]
