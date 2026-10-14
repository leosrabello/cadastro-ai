"""Document and registration analysis.

process_document() is safe to call more than once for the same document: it claims the
document atomically (only one worker can move it from queued/failed to processing), keeps
every human-confirmed field and every reviewer resolution, and replaces only machine output.
"""

import hashlib
import io
import re
import logging
import time
import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.models import (
    DocStatus,
    Document,
    ExtractedField,
    Finding,
    FindingStatus,
    ProcessingJob,
    RegStatus,
    Registration,
    utcnow,
)
from app.pipeline import ai as ai_mod
from app.pipeline import classify, completeness, consistency, extract, forensics, injection, ocr, priority, rendering, validity
from app.pipeline.ai.base import AiRequest
from app.pipeline.findings import FindingDraft, evidence, sync
from app.pipeline.normalize import digits, format_cnpj, format_cpf, format_money, parse_date, parse_money, valid_cnpj, valid_cpf
from app.settings_store import get_setting
from app.storage import StorageCorrupted, StorageUnavailable, get_store

log = logging.getLogger(__name__)

COMMON_FIELDS = ["nome", "cpf", "cnpj", "data_emissao", "validade"]
CERTAINTY_SEVERITY_CAP = {"low": "low", "medium": "medium", "high": "high"}
KIND_TITLES = {
    "inconsistency": "Inconsistência apontada pela IA",
    "possible_alteration": "Possível alteração apontada pela IA",
    "missing_element": "Elemento esperado ausente (IA)",
    "illegible": "Trecho ilegível (IA)",
    "other": "Observação da IA",
}
SEV = ["info", "low", "medium", "high", "critical"]


class TransientError(Exception):
    pass


class PermanentError(Exception):
    pass


def today() -> date:
    return date.today()


def claim(db: Session, document_id: uuid.UUID) -> bool:
    res = db.execute(
        update(Document)
        .where(Document.id == document_id, Document.status.in_((DocStatus.QUEUED, DocStatus.FAILED)))
        .values(status=DocStatus.PROCESSING, processing_attempts=Document.processing_attempts + 1, processing_error=None)
    )
    db.commit()
    return res.rowcount == 1


def _job(db: Session, document_id: uuid.UUID) -> ProcessingJob | None:
    return db.execute(
        select(ProcessingJob).where(ProcessingJob.document_id == document_id).order_by(ProcessingJob.created_at.desc()).limit(1)
    ).scalar_one_or_none()


def process_document(db: Session, document_id: uuid.UUID) -> dict:
    """Run the full pipeline. Returns metrics, or {'skipped': True} if another worker owns the document."""
    if not claim(db, document_id):
        return {"skipped": True}
    started = time.monotonic()
    job = _job(db, document_id)
    if job:
        job.status, job.started_at, job.attempts = "running", utcnow(), job.attempts + 1
        db.commit()
    try:
        metrics = _run(db, document_id)
    except Exception:
        db.rollback()
        raise
    metrics["total_ms"] = int((time.monotonic() - started) * 1000)
    if job:
        job.status, job.finished_at, job.duration_ms, job.metrics, job.error = "done", utcnow(), metrics["total_ms"], metrics, None
    db.commit()
    doc = db.get(Document, document_id)
    if doc and doc.registration_id:
        try:
            analyze_registration(db, doc.registration_id)
            db.commit()
        except Exception:  # the document itself is processed; the registration view refreshes on its next change
            log.exception("registration analysis failed after processing %s", document_id)
            db.rollback()
    return metrics


def release_for_retry(db: Session, document_id: uuid.UUID, reason: str) -> None:
    db.execute(update(Document).where(Document.id == document_id).values(status=DocStatus.QUEUED, processing_error=reason))
    job = _job(db, document_id)
    if job:
        job.status, job.error = "queued", reason
    db.commit()


def mark_failed(db: Session, document_id: uuid.UUID, reason: str) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        return
    doc.status, doc.processing_error = DocStatus.FAILED, reason[:2000]
    job = _job(db, document_id)
    if job:
        job.status, job.error, job.finished_at = "failed", reason[:2000], utcnow()
    sync(db, registration_id=None, document_id=doc.id, sources={"system"}, document_scope=True, drafts=[FindingDraft(
        code="PROCESSING_FAILED", category="processing", severity="high", source="system", document_id=doc.id,
        title="Falha no processamento",
        explanation=f"O documento foi guardado sem alterações, mas a análise automática não terminou: {reason[:300]}",
        recommended_action="Tente processar de novo. Se a falha persistir, revise o documento manualmente.",
        rule_id="pipeline.failed",
    )])
    for f in db.execute(select(Finding).where(Finding.document_id == doc.id, Finding.code == "PROCESSING_FAILED")).scalars():
        f.registration_id = doc.registration_id
    audit.record(db, "document.processing_failed", actor_label="pipeline", entity_type="document", entity_id=doc.id,
                 registration_id=doc.registration_id, details={"reason": reason[:500], "attempts": doc.processing_attempts})
    db.commit()
    if doc.registration_id:
        analyze_registration(db, doc.registration_id)
        db.commit()


def _run(db: Session, document_id: uuid.UUID) -> dict:
    s = get_settings()
    doc = db.get(Document, document_id)
    assert doc is not None
    doc_types = get_setting(db, "document_types")
    processing = get_setting(db, "processing")
    metrics: dict = {"pipeline_version": s.pipeline_version}

    try:
        data = get_store().get(doc.storage_key or "")
    except StorageUnavailable as exc:
        raise TransientError(f"armazenamento indisponível: {exc}") from exc
    except StorageCorrupted as exc:
        raise PermanentError(f"arquivo armazenado ilegível: {exc}") from exc
    if forensics_sha(data) != doc.sha256:
        raise PermanentError("o arquivo armazenado não confere com o hash registrado na entrada")

    try:
        rendered = rendering.render(data, doc.mime_type, dpi=s.render_dpi, max_pages=s.max_pages)
    except Exception as exc:
        raise PermanentError(f"não foi possível abrir o documento: {exc}") from exc
    metrics["pages"] = len(rendered.pages)

    provider = ocr.get_provider()
    metrics["ocr_provider"] = provider.name
    t0 = time.monotonic()
    pages = []
    integrity: list[FindingDraft] = []
    for page in rendered.pages:
        try:
            ocr_page = provider.recognize(page.image, page.index)
        except ocr.OcrUnavailable as exc:
            raise TransientError(f"OCR indisponível: {exc}") from exc
        except ocr.OcrFailed as exc:
            raise PermanentError(f"OCR falhou: {exc}") from exc
        if page.text_layer is not None:
            pages.append(ocr.merge_image_text(page.text_layer, ocr_page, page.image_boxes))
            if processing.get("compare_text_layer", True):
                integrity += forensics.text_layer_findings(page.text_layer, ocr_page, doc.id)
        else:
            pages.append(ocr_page)
    metrics["ocr_ms"] = int((time.monotonic() - t0) * 1000)
    ocr_conf = [p.mean_conf for p in pages if p.source != "pdf_text"]
    metrics["ocr_mean_conf"] = round(sum(ocr_conf) / len(ocr_conf), 3) if ocr_conf else None

    full_text = "\n".join(p.text for p in pages)
    doc.ocr_provider = "pdf_text" if all(p.source == "pdf_text" for p in pages) else provider.name
    doc.ocr_text = full_text
    doc.ocr_pages = [p.to_json() for p in pages]
    doc.file_metadata = rendered.metadata
    doc.phash = forensics.phash(rendered.pages[0].image)

    cls = classify.classify(full_text, doc_types)
    doc_type, type_conf, type_source = cls.doc_type, cls.confidence, "rules"
    if doc.doc_type_source == "human" and doc.doc_type:
        doc_type, type_conf, type_source = doc.doc_type, 1.0, "human"
    wanted = doc_types.get(doc_type, {}).get("fields", COMMON_FIELDS) if doc_type else COMMON_FIELDS
    fields = extract.extract(doc_type, wanted, pages)

    drafts: list[FindingDraft] = list(integrity)
    drafts += forensics.metadata_findings(rendered.metadata, doc.id)
    ela = forensics.ela_finding(data, doc.mime_type, doc.id)
    if ela:
        drafts.append(ela)

    hits = injection.scan(full_text)
    if hits:
        drafts.append(FindingDraft(
            code="EMBEDDED_INSTRUCTIONS", category="integrity", severity="high", source="rule", document_id=doc.id,
            title="Texto com instruções para sistemas automatizados",
            explanation="O documento contém frases dirigidas a um sistema ou analista (por exemplo, pedindo aprovação ou para ignorar regras). Documentos legítimos não trazem esse tipo de texto. O conteúdo foi tratado apenas como dado.",
            recommended_action="Escale para o supervisor e peça o documento por outro canal.",
            evidence=[evidence("Trecho", h, document_id=doc.id) for h in hits[:5]],
            rule_id="integrity.injection",
        ))

    # AI-assisted analysis: optional, bounded, validated, never decisive
    ai_summary = None
    ai_provider = ai_mod.get_provider() if processing.get("ai_enabled") else None
    if ai_provider is None:
        doc.ai_status, doc.ai_error = "skipped", ("IA desativada nas configurações" if not processing.get("ai_enabled") else "Nenhum provedor de IA configurado")
    else:
        images = []
        if processing.get("ai_send_images") and s.ai_allow_images:
            for page in rendered.pages[:3]:
                img = page.image.copy()
                img.thumbnail((1568, 1568))
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                images.append(buf.getvalue())
        req = AiRequest(
            doc_type_hint=doc_type,
            doc_types={k: v.get("label", k) for k, v in doc_types.items()},
            wanted_fields=wanted,
            pages_text=[p.text for p in pages],
            rule_fields={k: v.raw or v.value or "" for k, v in fields.items()},
            reference_date=today().isoformat(),
            images=images,
        )
        try:
            result = ai_provider.analyze(req)
            doc.ai_status, doc.ai_error = "done", None
            ai_summary = result.analysis.summary
            metrics.update(ai_model=result.model, ai_input_tokens=result.input_tokens, ai_output_tokens=result.output_tokens, ai_cost_usd=result.cost_usd)
            doc_type, type_conf, type_source, fields, ai_drafts = _merge_ai(doc, result.analysis, doc_type, type_conf, type_source, fields, doc_types, pages)
            drafts += ai_drafts
        except ai_mod.AiUnavailable as exc:
            doc.ai_status, doc.ai_error = "failed", str(exc)
        except ai_mod.AiFailed as exc:
            doc.ai_status, doc.ai_error = "failed", str(exc)
        if doc.ai_status == "failed":
            drafts.append(FindingDraft(
                code="AI_UNAVAILABLE", category="processing", severity="info", source="system", document_id=doc.id,
                title="Análise por IA não concluída",
                explanation=f"As verificações por regras foram feitas normalmente. A análise complementar por IA não terminou: {doc.ai_error}",
                recommended_action="Revise manualmente ou peça nova análise mais tarde.",
                rule_id="ai.unavailable",
            ))

    doc.doc_type, doc.doc_type_confidence, doc.doc_type_source = doc_type, type_conf, type_source
    doc.classification = {"scores": cls.scores, "matched": cls.matched, "rules_type": cls.doc_type, "rules_confidence": cls.confidence,
                          "ai_summary": ai_summary}
    doc.issuer = (fields.get("orgao_expedidor").value if fields.get("orgao_expedidor") else None) or (
        fields.get("emissor").value if fields.get("emissor") else None) or doc.issuer

    if doc_type is None:
        drafts.append(FindingDraft(
            code="DOC_TYPE_UNKNOWN", category="quality", severity="medium", document_id=doc.id,
            title="Tipo de documento não identificado",
            explanation="O texto lido não corresponde com segurança a nenhum tipo configurado.",
            recommended_action="Classifique o documento manualmente na revisão.",
            evidence=[evidence("Pontuação por tipo", ", ".join(f"{k}: {v}" for k, v in cls.scores.items() if v) or "nenhuma palavra-chave")],
            rule_id="classify.unknown",
        ))
    elif type_source == "rules" and type_conf < 0.35:
        drafts.append(FindingDraft(
            code="DOC_TYPE_UNCERTAIN", category="quality", severity="low", document_id=doc.id,
            title="Classificação incerta",
            explanation=f"Classificado como {doc_types[doc_type]['label']} com poucas evidências ({', '.join(cls.matched) or 'nenhuma'}).",
            recommended_action="Confirme o tipo do documento.",
            rule_id="classify.uncertain",
        ))

    mean_conf = metrics.get("ocr_mean_conf")
    if (mean_conf is not None and mean_conf < processing.get("min_ocr_confidence", 0.6)) or len(full_text.strip()) < 40:
        drafts.append(FindingDraft(
            code="LOW_LEGIBILITY", category="quality", severity="medium", document_id=doc.id,
            title="Leitura com baixa qualidade",
            explanation=f"A confiança média do OCR foi {mean_conf if mean_conf is not None else 0:.0%} e foram lidos {len(full_text.strip())} caracteres. Campos podem estar errados ou ausentes.",
            recommended_action="Confira os campos no original ou peça uma cópia mais nítida.",
            confidence=mean_conf, confidence_basis="Confiança média informada pelo OCR.",
            rule_id="quality.ocr",
        ))

    for fv in fields.values():
        if fv.valid is False and fv.name in ("cpf", "cnpj"):
            drafts.append(FindingDraft(
                code="ID_CHECK_DIGITS", category="quality", severity="high", field_name=fv.name, document_id=doc.id,
                title=f"{fv.name.upper()} com dígitos verificadores inválidos",
                explanation=f"O número lido ({fv.raw}) não passa na verificação de dígitos. Pode ser erro de leitura ou número adulterado.",
                recommended_action="Confira o número no original e corrija o campo.",
                evidence=[evidence("Lido", fv.raw, document_id=doc.id, field=fv.name, page=fv.page, bbox=fv.bbox)],
                rule_id=f"check_digits.{fv.name}",
            ))

    _store_fields(db, doc, fields)
    db.flush()
    effective = {f.name: f for f in doc.fields}
    if doc_type:
        vr = validity.evaluate(doc_type, doc_types[doc_type], _as_values(effective), doc.id, today())
        doc.validity = vr.to_json()
        drafts += vr.findings
    else:
        doc.validity = {"state": "unknown", "summary": "Tipo não identificado; validade não avaliada.", "rule": None, "reference_date": today().isoformat()}

    db.flush()
    drafts += forensics.duplicate_findings(db, doc, int(processing.get("duplicate_phash_distance", 6)))
    sync(db, registration_id=None, document_id=doc.id, sources={"rule", "forensics", "ai", "system"}, drafts=drafts, document_scope=True)
    for f in db.execute(select(Finding).where(Finding.document_id == doc.id)).scalars():
        f.registration_id = doc.registration_id

    if doc.registration_id is None:
        _suggest_registration(db, doc, processing)

    doc.status, doc.processed_at, doc.processing_error = DocStatus.PROCESSED, utcnow(), None
    audit.record(db, "document.processed", actor_label="pipeline", entity_type="document", entity_id=doc.id,
                 registration_id=doc.registration_id,
                 details={"doc_type": doc_type, "type_source": type_source, "validity": (doc.validity or {}).get("state"),
                          "findings": len(drafts), "ai_status": doc.ai_status, "ocr": doc.ocr_provider})
    return metrics


def forensics_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _V:
    """Adapter so stored fields can feed the validity rules like fresh FieldValues."""

    def __init__(self, f: ExtractedField):
        self.name, self.value, self.raw, self.page, self.bbox = f.name, f.value, f.raw_value, f.page, f.bbox


def _as_values(fields: dict) -> dict:
    return {k: _V(v) for k, v in fields.items()}


def _store_fields(db: Session, doc: Document, fields: dict) -> None:
    existing = {f.name: f for f in doc.fields}
    for name, f in existing.items():
        if f.status in ("corrected", "confirmed"):
            continue
        if name not in fields:
            doc.fields.remove(f)
    for name, fv in fields.items():
        cur = existing.get(name)
        if cur is not None and cur.status in ("corrected", "confirmed"):
            continue
        if cur is None:
            cur = ExtractedField(name=name)
            doc.fields.append(cur)
        cur.value, cur.raw_value, cur.confidence, cur.source = fv.value, fv.raw, fv.confidence, fv.source
        cur.page, cur.bbox, cur.valid, cur.validation_note = fv.page, fv.bbox, fv.valid, fv.note
        cur.status = "extracted"


def _normalize_ai_value(name: str, value: str) -> tuple[str | None, bool | None]:
    v = value.strip()
    if not v:
        return None, None
    if name in ("data_nascimento", "data_expedicao", "data_emissao", "validade", "data_registro"):
        d = parse_date(v)
        return (d.isoformat() if d else None), d is not None
    if name == "cpf":
        d = digits(v)
        return format_cpf(d), valid_cpf(d)
    if name == "cnpj":
        d = digits(v)
        return format_cnpj(d), valid_cnpj(d)
    if name == "nome":
        return v.upper(), True
    if name == "exercicio":
        m = re.search(r"20\d{2}", v)
        return (m.group(0), True) if m else (None, None)
    if name in MONEY_FIELDS:
        amount = parse_money(v)
        return (format_money(amount), True) if amount is not None else (None, None)
    return v, True


MONEY_FIELDS = {"receita_liquida", "lucro_liquido", "patrimonio_liquido", "ativo_total", "faturamento_total",
                "endividamento_total", "patrimonio_declarado", "dividas_onus", "lucros_dividendos"}


def _merge_ai(doc, analysis, doc_type, type_conf, type_source, fields, doc_types, pages):
    drafts: list[FindingDraft] = []
    ai_type = analysis.document_type if analysis.document_type in doc_types else None
    if type_source != "human" and ai_type and ai_type != doc_type:
        if doc_type is None or type_conf < 0.5:
            if doc_type is not None:
                drafts.append(FindingDraft(
                    code="DOC_TYPE_SET_BY_AI", category="quality", severity="low", source="ai", document_id=doc.id,
                    title="Tipo definido pela IA",
                    explanation=f"As regras sugeriram {doc_type}; a IA indicou {ai_type}. Foi adotada a indicação da IA porque a evidência das regras era fraca.",
                    recommended_action="Confirme o tipo do documento.",
                    rule_id="ai.type",
                ))
            doc_type, type_conf, type_source = ai_type, 0.6, "ai"
            wanted = doc_types[doc_type].get("fields", COMMON_FIELDS)
            fields = extract.extract(doc_type, wanted, pages)
        else:
            drafts.append(FindingDraft(
                code="DOC_TYPE_DISAGREEMENT", category="quality", severity="low", source="ai", document_id=doc.id,
                title="Regras e IA classificaram de forma diferente",
                explanation=f"As regras classificaram como {doc_type}; a IA indicou {ai_type}. Foi mantida a classificação por regras.",
                recommended_action="Confirme o tipo do documento.",
                rule_id="ai.type",
            ))

    allowed = set(doc_types.get(doc_type, {}).get("fields", COMMON_FIELDS)) if doc_type else set(COMMON_FIELDS)
    for af in analysis.fields:
        if af.name not in allowed:
            continue
        norm, ok = _normalize_ai_value(af.name, af.value)
        if norm is None:
            continue
        current = fields.get(af.name)
        if current is None or not current.value:
            fields[af.name] = extract.FieldValue(
                name=af.name, value=norm, raw=af.value, confidence=0.5, page=af.page, bbox=None, valid=ok,
                note="Lido pela IA; as regras não encontraram este campo. Confirme no original.", source="ai",
            )
        elif _cmp(current.value) != _cmp(norm):
            drafts.append(FindingDraft(
                code="AI_RULE_DISAGREEMENT", category="quality", severity="medium", source="ai", field_name=af.name, document_id=doc.id,
                title=f"Leituras diferentes: {af.name.replace('_', ' ')}",
                explanation=f"O OCR com regras leu '{current.raw}'; a IA leu '{af.value}'. Uma das leituras está errada, ou o campo está ambíguo no documento.",
                recommended_action="Confira no original e confirme ou corrija o campo.",
                evidence=[
                    evidence("Regras (OCR)", current.raw, document_id=doc.id, field=af.name, page=current.page, bbox=current.bbox),
                    evidence("IA", af.value, document_id=doc.id, field=af.name, page=af.page, note=af.evidence_text[:200]),
                ],
                rule_id="ai.field_disagreement",
            ))

    for i, ob in enumerate(analysis.observations):
        sev = ob.severity if SEV.index(ob.severity) <= SEV.index(CERTAINTY_SEVERITY_CAP[ob.certainty]) else CERTAINTY_SEVERITY_CAP[ob.certainty]
        drafts.append(FindingDraft(
            code=f"AI_{ob.kind.upper()}", category="ai", severity=sev, source="ai", document_id=doc.id,
            field_name=ob.field or None, key=f"{ob.kind}:{ob.field}:{i}",
            title=KIND_TITLES[ob.kind],
            explanation=ob.explanation,
            recommended_action=ob.recommended_action or "Confira no original.",
            evidence=[evidence("Trecho citado pela IA", ob.evidence_text, document_id=doc.id, field=ob.field or None, page=ob.page)] if ob.evidence_text else [],
            confidence=None, confidence_basis=f"Grau de clareza segundo a IA: {ob.certainty}. Não é uma probabilidade calibrada.",
            certainty=ob.certainty, rule_id="ai.observation",
        ))
    if analysis.embedded_instructions_detected:
        drafts.append(FindingDraft(
            code="AI_EMBEDDED_INSTRUCTIONS", category="integrity", severity="high", source="ai", document_id=doc.id,
            title="A IA encontrou instruções embutidas no documento",
            explanation="A IA identificou texto no documento dirigido a um sistema automatizado. Ele foi ignorado como instrução e tratado como indício.",
            recommended_action="Escale para o supervisor.",
            rule_id="ai.injection",
        ))
    return doc_type, type_conf, type_source, fields, drafts


def _cmp(v: str | None) -> str:
    return "".join(ch for ch in (v or "").upper() if ch.isalnum())


def _suggest_registration(db: Session, doc: Document, processing: dict) -> None:
    ids = {digits(f.value) for f in doc.fields if f.name in ("cpf", "cnpj") and f.value and f.valid}
    if not ids:
        return
    matches = db.execute(select(Registration).where(Registration.tax_id.in_(ids), Registration.status.notin_(RegStatus.CLOSED))).scalars().all()
    if len(matches) != 1:
        return
    reg = matches[0]
    if processing.get("auto_assign_by_extracted_id"):
        doc.registration_id = reg.id
        audit.record(db, "document.associated", actor_label="pipeline", entity_type="document", entity_id=doc.id,
                     registration_id=reg.id, details={"rule": "extracted_tax_id", "registration": reg.code})
    else:
        doc.suggested_registration_id = reg.id


def analyze_registration(db: Session, registration_id: uuid.UUID) -> None:
    reg = db.get(Registration, registration_id)
    if reg is None:
        return
    doc_types = get_setting(db, "document_types")
    profiles = get_setting(db, "requirement_profiles")
    profile = profiles.get(reg.kind, {})
    docs = db.execute(select(Document).where(Document.registration_id == reg.id, Document.status != DocStatus.PURGED)).scalars().all()
    processed = [d for d in docs if d.status == DocStatus.PROCESSED]

    cons = consistency.analyze(reg, processed, get_setting(db, "consistency_rules"), profile)
    doc_level_open = db.execute(
        select(Finding).where(
            Finding.registration_id == reg.id,
            Finding.status.in_(FindingStatus.OPEN_STATES),
            Finding.category.notin_(("consistency", "completeness")),
        )
    ).scalars().all()
    pseudo = doc_level_open + [SimpleNamespace(severity=d.severity, status=FindingStatus.OPEN) for d in cons]
    labels = {k: v.get("label", k) for k, v in doc_types.items()}
    checklist, comp, ready = completeness.build(profile, list(docs), pseudo, labels, reg.reference_fields or {}, today(),
                                                approved=reg.status == RegStatus.APPROVED)
    sync(db, registration_id=reg.id, document_id=None, sources={"rule"}, drafts=cons + comp, document_scope=False)

    all_findings = db.execute(select(Finding).where(Finding.registration_id == reg.id)).scalars().all()
    reg.priority_score, reg.priority_reasons = priority.compute(reg, list(docs), all_findings, checklist, get_setting(db, "priority_rules"))
    reg.checklist, reg.ready_for_decision, reg.last_analysis_at = checklist, ready, utcnow()

    old = reg.status
    if reg.status not in RegStatus.FINAL:
        if not docs:
            new = RegStatus.AWAITING_PROCESSING
        elif any(d.status in (DocStatus.QUEUED, DocStatus.PROCESSING) for d in docs):
            new = RegStatus.PROCESSING
        elif any(d.status == DocStatus.FAILED for d in docs):
            new = RegStatus.PROCESSING_FAILED
        elif reg.status == RegStatus.PENDING_DOCUMENTS and not any(reg.decided_at and d.received_at > reg.decided_at for d in docs):
            new = RegStatus.PENDING_DOCUMENTS
        else:
            new = RegStatus.AWAITING_REVIEW
        if new != old:
            reg.status = new
            audit.record(db, "registration.status_changed", actor_label="pipeline", entity_type="registration", entity_id=reg.id,
                         registration_id=reg.id, details={"from": old, "to": new})
    db.flush()
