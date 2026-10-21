import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import audit, ratelimit
from app.api.registrations import get_registration
from app.api.serializers import FIELD_LABELS, document_brief, field_out, finding_out, iso, registration_row
from app.config import get_settings
from app.db import get_db
from app.deps import ANY_ROLE, OPERATORS, SUPERVISORS, Principal
from app.errors import ApiError
from app.ingestion.service import DuplicateDocument, RegistrationClosed, ingest, job_key
from app.ingestion.validation import RejectedFile
from app.models import (
    DocStatus,
    Document,
    ExtractedField,
    Finding,
    FindingStatus,
    IngestRecord,
    ProcessingJob,
    RegStatus,
    Registration,
    utcnow,
)
from app.pipeline.normalize import digits, format_cnpj, format_cpf, format_money, parse_date, parse_money, valid_cnpj, valid_cpf
from app.pipeline.orchestrator import analyze_registration
from app.pipeline.rendering import render_page_png
from app.settings_store import get_setting
from app.storage import StorageCorrupted, StorageUnavailable, get_store
from app.worker import enqueue

router = APIRouter(prefix="/api", tags=["documents"])


class FieldEdit(BaseModel):
    action: Literal["confirm", "correct"]
    value: str | None = Field(None, max_length=400)
    reason: str | None = Field(None, max_length=1000)


class ClassificationIn(BaseModel):
    doc_type: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(None, max_length=500)


class AssociateIn(BaseModel):
    registration_id: uuid.UUID


class ResolveIn(BaseModel):
    action: Literal["accept", "escalate", "override", "reopen"]
    note: str | None = Field(None, max_length=2000)


def get_document(db: Session, did: uuid.UUID) -> Document:
    doc = db.get(Document, did)
    if doc is None:
        raise ApiError(404, "not_found", "Documento não encontrado.")
    return doc


def _read_original(doc: Document) -> bytes:
    if doc.status == DocStatus.PURGED or not doc.storage_key:
        raise ApiError(410, "purged", "O arquivo foi expurgado pela política de retenção.")
    try:
        return get_store().get(doc.storage_key)
    except StorageUnavailable:
        raise ApiError(503, "storage_unavailable", "O repositório de documentos está indisponível. Tente em instantes.")
    except StorageCorrupted:
        raise ApiError(500, "storage_corrupted", "O arquivo armazenado está ilegível. Avise o administrador.")


def _read_for_viewing(doc: Document) -> tuple[bytes, str]:
    """The bytes the pipeline and the page viewer use: the PDF made from a Word/Excel original, or the original."""
    if doc.rendition_key and doc.status != DocStatus.PURGED:
        try:
            return get_store().get(doc.rendition_key), "application/pdf"
        except StorageUnavailable:
            raise ApiError(503, "storage_unavailable", "O repositório de documentos está indisponível. Tente em instantes.")
    return _read_original(doc), doc.mime_type


@router.post("/registrations/{rid}/documents", status_code=201)
async def upload(rid: uuid.UUID, files: list[UploadFile] = File(...), p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    ratelimit.hit(f"upload:{p.user.id}", limit=120, window_seconds=60)
    limit = get_settings().max_upload_mb * 1024 * 1024
    results, queued = [], []
    for upload_file in files[:20]:
        name = upload_file.filename or "documento"
        data = await upload_file.read(limit + 1)
        try:
            if len(data) > limit:
                raise RejectedFile("too_large", f"O arquivo passa do limite de {get_settings().max_upload_mb} MB.")
            result = ingest(db, data=data, filename=name, source="upload", registration=reg, actor=p.user, ip=p.ip)
            db.commit()
            queued.append(result.document.id)
            results.append({"filename": name, "ok": True, "document": document_brief(result.document)})
        except RejectedFile as exc:
            db.rollback()
            audit.record(db, "document.rejected", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id,
                         details={"filename": name, "code": exc.code, "message": exc.message}, ip=p.ip)
            db.commit()
            results.append({"filename": name, "ok": False, "error": {"code": exc.code, "message": exc.message}})
        except DuplicateDocument as exc:
            db.rollback()
            results.append({"filename": name, "ok": False, "error": {"code": "duplicate", "message": f"Este arquivo já foi enviado neste cadastro ({exc.existing.original_filename}).", "document_id": str(exc.existing.id)}})
        except RegistrationClosed:
            db.rollback()
            results.append({"filename": name, "ok": False, "error": {"code": "registration_closed", "message": "Cadastro reprovado. Reabra-o para anexar documentos."}})
        except StorageUnavailable:
            db.rollback()
            results.append({"filename": name, "ok": False, "error": {"code": "storage_unavailable", "message": "Repositório indisponível. Tente reenviar em instantes."}})
    for doc_id in queued:
        enqueue(doc_id)
    if not queued and len(files) == 1 and not results[0]["ok"]:
        err = results[0]["error"]
        raise ApiError(409 if err["code"] in ("duplicate", "registration_closed") else 422, err["code"], err["message"], details=results)
    return {"results": results}


@router.get("/documents/{did}")
def document_detail(did: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    doc = db.execute(select(Document).options(selectinload(Document.fields)).where(Document.id == did)).scalar_one_or_none()
    if doc is None:
        raise ApiError(404, "not_found", "Documento não encontrado.")
    findings = db.execute(
        select(Finding).options(selectinload(Finding.resolved_by))
        .where(Finding.document_id == doc.id, Finding.status != FindingStatus.SUPERSEDED)
    ).scalars().all()
    reg = db.get(Registration, doc.registration_id) if doc.registration_id else None
    siblings = []
    if reg:
        siblings = [
            {"id": str(d.id), "original_filename": d.original_filename, "doc_type": d.doc_type, "status": d.status}
            for d in db.execute(select(Document).where(Document.registration_id == reg.id).order_by(Document.received_at)).scalars()
        ]
    job = db.execute(select(ProcessingJob).where(ProcessingJob.document_id == doc.id).order_by(ProcessingJob.created_at.desc()).limit(1)).scalar_one_or_none()
    doc_types = get_setting(db, "document_types")
    wanted = doc_types.get(doc.doc_type, {}).get("fields", []) if doc.doc_type else []
    present = {f.name for f in doc.fields}
    return {
        **document_brief(doc),
        "fields": [field_out(f) for f in doc.fields],
        "missing_fields": [{"name": n, "label": FIELD_LABELS.get(n, n)} for n in wanted if n not in present],
        "findings": [finding_out(f) for f in findings],
        "classification": doc.classification,
        "file_metadata": doc.file_metadata,
        "ocr_provider": doc.ocr_provider,
        "registration": registration_row(reg) if reg else None,
        "siblings": siblings,
        "job": {"status": job.status, "attempts": job.attempts, "duration_ms": job.duration_ms, "error": job.error,
                "metrics": job.metrics, "finished_at": iso(job.finished_at)} if job else None,
    }


@router.get("/documents/{did}/text")
def document_text(did: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    return {"pages": doc.ocr_pages or [], "text": doc.ocr_text or ""}


@router.get("/documents/{did}/file")
def document_file(did: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    data = _read_original(doc)
    audit.record(db, "document.downloaded", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=doc.registration_id, ip=p.ip)
    db.commit()
    return Response(content=data, media_type=doc.mime_type, headers={
        "Content-Disposition": "attachment; filename=\"documento\"",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "no-store",
    })


@router.get("/documents/{did}/pages/{page}")
def document_page(did: uuid.UUID, page: int, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    if page < 0 or page >= (doc.page_count or 1):
        raise ApiError(404, "not_found", "Página inexistente.")
    data, mime = _read_for_viewing(doc)
    png = render_page_png(data, mime, page, dpi=200)  # sharp enough to read small print at 300% zoom
    if page == 0:
        audit.record(db, "document.viewed", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=doc.registration_id, ip=p.ip)
        db.commit()
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


class DocumentDeleteIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/documents/{did}/delete")
def delete_document(did: uuid.UUID, body: DocumentDeleteIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    """A file sent by mistake (wrong person, wrong version, duplicate). The stored file and everything read
    from it go; the audit keeps the type, the hash and the reason, not the file name (it often carries a CPF)."""
    from sqlalchemy import delete as sql_delete, update

    doc = get_document(db, did)
    reg = db.get(Registration, doc.registration_id) if doc.registration_id else None
    if reg is not None and reg.legal_hold:
        raise ApiError(409, "legal_hold", "Cadastro sob retenção legal; os documentos não podem ser excluídos.")
    if reg is not None and reg.status == RegStatus.APPROVED:
        raise ApiError(409, "approved", "Cadastro aprovado: os documentos ficam guardados pelo prazo legal.")
    if doc.status in (DocStatus.QUEUED, DocStatus.PROCESSING):
        raise ApiError(409, "processing", "O documento ainda está sendo analisado. Aguarde terminar para excluir.")
    store = get_store()
    try:
        for key in (doc.storage_key, doc.rendition_key):
            if key:
                store.delete(key)
    except StorageUnavailable:
        raise ApiError(503, "storage_unavailable", "O repositório de documentos não respondeu; nada foi excluído. Tente de novo.")
    db.execute(update(Document).where(Document.duplicate_of_id == doc.id).values(duplicate_of_id=None))
    db.execute(update(IngestRecord).where(IngestRecord.document_id == doc.id).values(document_id=None))
    db.execute(sql_delete(ExtractedField).where(ExtractedField.document_id == doc.id))
    db.execute(sql_delete(Finding).where(Finding.document_id == doc.id))
    db.execute(sql_delete(ProcessingJob).where(ProcessingJob.document_id == doc.id))
    audit.record(db, "document.deleted", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=doc.registration_id,
                 details={"doc_type": doc.doc_type, "sha256": doc.sha256, "reason": body.reason.strip()}, ip=p.ip)
    db.delete(doc)
    db.flush()
    if reg is not None:
        analyze_registration(db, reg.id)
    db.commit()
    return {"deleted": True}


@router.post("/documents/{did}/reprocess")
def reprocess(did: uuid.UUID, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    if doc.status == DocStatus.PURGED:
        raise ApiError(410, "purged", "Documento expurgado.")
    if doc.status == DocStatus.PROCESSING:
        raise ApiError(409, "in_progress", "O documento já está em processamento.")
    round_ = db.execute(select(ProcessingJob).where(ProcessingJob.document_id == doc.id)).scalars().all()
    db.add(ProcessingJob(document_id=doc.id, idempotency_key=job_key(doc.id, doc.sha256, len(round_) + 1), requested_by_id=p.user.id))
    doc.status = DocStatus.QUEUED
    if doc.registration_id:
        reg = db.get(Registration, doc.registration_id)
        if reg and reg.status not in RegStatus.FINAL:
            reg.status = RegStatus.PROCESSING
    audit.record(db, "document.reprocess_requested", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=doc.registration_id, ip=p.ip)
    db.commit()
    enqueue(doc.id)
    return document_brief(doc)


def _normalize_field(name: str, value: str) -> tuple[str, bool, str | None]:
    v = value.strip()
    if name in ("data_nascimento", "data_expedicao", "data_emissao", "validade", "data_registro"):
        d = parse_date(v)
        if d is None:
            raise ApiError(422, "invalid_value", "Data inválida. Use DD/MM/AAAA.")
        return d.isoformat(), True, None
    if name == "cpf":
        if not valid_cpf(v):
            raise ApiError(422, "invalid_value", "CPF inválido: confira os dígitos.")
        return format_cpf(digits(v)), True, None
    if name == "cnpj":
        if not valid_cnpj(v):
            raise ApiError(422, "invalid_value", "CNPJ inválido: confira os dígitos.")
        return format_cnpj(digits(v)), True, None
    if name in ("nome", "razao_social"):
        return " ".join(v.split()).upper(), True, None
    if name == "exercicio":
        if not re.fullmatch(r"20\d{2}", v):
            raise ApiError(422, "invalid_value", "Informe o ano com quatro dígitos.")
        return v, True, None
    if name in MONEY_FIELDS:
        amount = parse_money(v)
        if amount is None:
            raise ApiError(422, "invalid_value", "Valor inválido. Use o formato 1.234.567,89.")
        return format_money(amount), True, None
    return v, True, None


MONEY_FIELDS = {"receita_liquida", "lucro_liquido", "patrimonio_liquido", "ativo_total", "faturamento_total",
                "endividamento_total", "patrimonio_declarado", "dividas_onus", "lucros_dividendos"}


@router.patch("/documents/{did}/fields/{name}")
def edit_field(did: uuid.UUID, name: str, body: FieldEdit, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    if name not in FIELD_LABELS:
        raise ApiError(404, "not_found", "Campo desconhecido.")
    reg = db.get(Registration, doc.registration_id) if doc.registration_id else None
    if reg and reg.status in RegStatus.CLOSED:
        raise ApiError(409, "registration_closed", "Cadastro já decidido.")
    field = next((f for f in doc.fields if f.name == name), None)
    before = field.value if field else None
    if body.action == "confirm":
        if field is None or not field.value:
            raise ApiError(422, "nothing_to_confirm", "Não há valor para confirmar; informe a correção.")
        field.status = "confirmed"
    else:
        if not body.value:
            raise ApiError(422, "value_required", "Informe o valor correto.")
        if not body.reason or len(body.reason.strip()) < 5:
            raise ApiError(422, "reason_required", "Explique a correção em poucas palavras.")
        value, valid, note = _normalize_field(name, body.value)
        if field is None:
            field = ExtractedField(name=name, source="human")
            doc.fields.append(field)
        field.previous_value = field.value
        field.value, field.valid, field.validation_note, field.status, field.source = value, valid, note, "corrected", "human"
        field.confidence = 1.0
    field.reviewed_by_id, field.reviewed_at = p.user.id, utcnow()
    db.flush()
    _rerun_rules(db, doc)
    audit.record(db, "field.confirmed" if body.action == "confirm" else "field.corrected", actor=p.user, entity_type="document",
                 entity_id=doc.id, registration_id=doc.registration_id,
                 details={"field": name, "before": before, "after": field.value, "reason": body.reason}, ip=p.ip)
    db.commit()
    return field_out(field)


def _rerun_rules(db: Session, doc: Document) -> None:
    """Re-evaluate validity and registration-level checks after a human change, without new OCR."""
    from app.pipeline import validity
    from app.pipeline.orchestrator import _as_values, today

    doc_types = get_setting(db, "document_types")
    if doc.doc_type and doc.doc_type in doc_types:
        vr = validity.evaluate(doc.doc_type, doc_types[doc.doc_type], _as_values({f.name: f for f in doc.fields}), doc.id, today())
        doc.validity = vr.to_json()
        keep = db.execute(
            select(Finding).where(Finding.document_id == doc.id, Finding.category == "validity", Finding.status.in_(FindingStatus.OPEN_STATES))
        ).scalars().all()
        produced = {d.fingerprint(None) for d in vr.findings}
        for f in keep:
            if f.fingerprint not in produced and f.code in ("DOC_EXPIRED", "DOC_TOO_OLD", "EXPIRY_MISSING", "ISSUE_DATE_MISSING", "DATE_CONTRADICTION", "DATE_UNREADABLE", "REQUIRED_VALUE_MISSING", "REQUIRED_VALUE_MISMATCH", "SIGNATURE_NOT_FOUND", "REVENUE_OUTDATED"):
                f.status = FindingStatus.SUPERSEDED
        if vr.findings:
            existing = {f.fingerprint for f in db.execute(select(Finding).where(Finding.document_id == doc.id)).scalars()}
            for d in vr.findings:
                if d.fingerprint(None) not in existing:
                    db.add(Finding(fingerprint=d.fingerprint(None), registration_id=doc.registration_id, document_id=doc.id, code=d.code,
                                       category=d.category, severity=d.severity, title=d.title, explanation=d.explanation, evidence=d.evidence,
                                       field_name=d.field_name, recommended_action=d.recommended_action, source=d.source, rule_id=d.rule_id))
    for f in db.execute(select(Finding).where(Finding.document_id == doc.id, Finding.field_name.is_not(None),
                                              Finding.code.in_(("ID_CHECK_DIGITS", "AI_RULE_DISAGREEMENT")),
                                              Finding.status.in_(FindingStatus.OPEN_STATES))).scalars():
        fld = next((x for x in doc.fields if x.name == f.field_name), None)
        if fld is not None and fld.status in ("confirmed", "corrected"):
            f.status = FindingStatus.SUPERSEDED
    db.flush()
    if doc.registration_id:
        analyze_registration(db, doc.registration_id)


@router.patch("/documents/{did}/classification")
def classify_document(did: uuid.UUID, body: ClassificationIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    if body.doc_type not in get_setting(db, "document_types"):
        raise ApiError(422, "invalid_type", "Tipo de documento desconhecido.")
    before = doc.doc_type
    doc.doc_type, doc.doc_type_source, doc.doc_type_confidence = body.doc_type, "human", 1.0
    db.add(ProcessingJob(document_id=doc.id, idempotency_key=job_key(doc.id, doc.sha256, int(utcnow().timestamp())), requested_by_id=p.user.id))
    doc.status = DocStatus.QUEUED
    audit.record(db, "document.classified", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=doc.registration_id,
                 details={"before": before, "after": body.doc_type, "reason": body.reason}, ip=p.ip)
    db.commit()
    enqueue(doc.id)
    return document_brief(doc)


@router.post("/documents/{did}/associate")
def associate(did: uuid.UUID, body: AssociateIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    doc = get_document(db, did)
    if doc.registration_id is not None:
        raise ApiError(409, "already_associated", "O documento já pertence a um cadastro.")
    reg = get_registration(db, body.registration_id)
    if reg.status in RegStatus.CLOSED:
        raise ApiError(409, "registration_closed", "Cadastro já decidido.")
    dup = db.execute(select(Document).where(Document.registration_id == reg.id, Document.sha256 == doc.sha256)).scalar_one_or_none()
    if dup:
        raise ApiError(409, "duplicate", "Este cadastro já tem um arquivo idêntico.")
    doc.registration_id, doc.suggested_registration_id = reg.id, None
    for f in db.execute(select(Finding).where(Finding.document_id == doc.id)).scalars():
        f.registration_id = reg.id
    db.flush()
    analyze_registration(db, reg.id)
    audit.record(db, "document.associated", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=reg.id,
                 details={"registration": reg.code, "rule": "manual"}, ip=p.ip)
    db.commit()
    return document_brief(doc)


@router.get("/inbox")
def inbox(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    docs = db.execute(select(Document).where(Document.registration_id.is_(None), Document.status != DocStatus.PURGED).order_by(Document.received_at.desc()).limit(200)).scalars().all()
    suggested = {d.suggested_registration_id for d in docs if d.suggested_registration_id}
    regs = {r.id: r for r in db.execute(select(Registration).where(Registration.id.in_(suggested))).scalars()} if suggested else {}
    records = db.execute(select(IngestRecord).where(IngestRecord.status.in_(("rejected", "failed", "duplicate"))).order_by(IngestRecord.created_at.desc()).limit(50)).scalars().all()
    ingest_detail = {r.document_id: r.detail for r in db.execute(select(IngestRecord).where(IngestRecord.document_id.in_([d.id for d in docs]))).scalars()} if docs else {}
    return {
        "documents": [
            {**document_brief(d), "ingest_note": ingest_detail.get(d.id),
             "suggested_registration": registration_row(regs[d.suggested_registration_id]) if d.suggested_registration_id in regs else None,
             "fields": [field_out(f) for f in d.fields if f.name in ("nome", "cpf", "cnpj", "razao_social")]}
            for d in docs
        ],
        "ingest_problems": [
            {"id": str(r.id), "source": r.source, "source_ref": r.source_ref, "status": r.status, "detail": r.detail,
             "size_bytes": r.size_bytes, "created_at": iso(r.created_at)}
            for r in records
        ],
    }


@router.post("/findings/{fid}/resolve")
def resolve_finding(fid: uuid.UUID, body: ResolveIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    f = db.get(Finding, fid)
    if f is None:
        raise ApiError(404, "not_found", "Ponto não encontrado.")
    reg = db.get(Registration, f.registration_id) if f.registration_id else None
    if reg and reg.status in RegStatus.CLOSED:
        raise ApiError(409, "registration_closed", "Cadastro já decidido.")
    note = (body.note or "").strip()
    policy = get_setting(db, "approval")
    if body.action == "override":
        if p.role not in policy.get("override_roles", ["supervisor", "admin"]):
            raise ApiError(403, "forbidden", "Somente supervisores sobrepõem o resultado de uma regra.")
        if len(note) < 20:
            raise ApiError(422, "reason_required", "Sobrepor uma regra exige justificativa (mínimo 20 caracteres).")
        new = FindingStatus.OVERRIDDEN
    elif body.action == "accept":
        if f.severity in ("high", "critical") and p.role not in ("supervisor", "admin"):
            raise ApiError(403, "forbidden", "Pontos de severidade alta são aceitos somente por supervisores. Escale-o.")
        if len(note) < 10:
            raise ApiError(422, "reason_required", "Explique por que o ponto não é um problema (mínimo 10 caracteres).")
        new = FindingStatus.ACCEPTED
    elif body.action == "escalate":
        if len(note) < 10:
            raise ApiError(422, "reason_required", "Explique o motivo do escalonamento (mínimo 10 caracteres).")
        new = FindingStatus.ESCALATED
    else:
        if p.role not in ("supervisor", "admin"):
            raise ApiError(403, "forbidden", "Somente supervisores reabrem pontos.")
        new = FindingStatus.OPEN
    before = f.status
    f.status, f.resolution_note = new, note or None
    f.resolved_by_id, f.resolved_at = (p.user.id, utcnow()) if new != FindingStatus.OPEN else (None, None)
    db.flush()
    if f.registration_id:
        analyze_registration(db, f.registration_id)
    audit.record(db, f"finding.{body.action}", actor=p.user, entity_type="finding", entity_id=f.id, registration_id=f.registration_id,
                 details={"code": f.code, "title": f.title, "from": before, "to": new, "note": note}, ip=p.ip)
    db.commit()
    db.refresh(f)
    return finding_out(f)


__all__ = ["router", "SUPERVISORS"]
