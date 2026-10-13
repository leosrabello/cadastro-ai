from app.models import Decision, Document, ExtractedField, Finding, Registration, User

FIELD_LABELS = {
    "nome": "Nome",
    "cpf": "CPF",
    "cnpj": "CNPJ",
    "rg_numero": "Número do RG",
    "cnh_registro": "Registro da CNH",
    "data_nascimento": "Data de nascimento",
    "data_expedicao": "Data de expedição",
    "data_emissao": "Data de emissão",
    "validade": "Validade",
    "orgao_expedidor": "Órgão expedidor",
    "endereco": "Endereço",
    "cep": "CEP",
    "razao_social": "Razão social",
    "situacao_cadastral": "Situação cadastral",
    "socios": "Sócios",
    "data_registro": "Data de registro",
    "emissor": "Emissor",
    "exercicio": "Exercício",
    "receita_liquida": "Receita líquida",
    "lucro_liquido": "Lucro (prejuízo) líquido",
    "patrimonio_liquido": "Patrimônio líquido",
    "ativo_total": "Ativo total",
    "faturamento_mensal": "Faturamento mensal",
    "faturamento_total": "Faturamento do ano",
    "periodo_fim": "Último mês informado",
    "endividamento_total": "Endividamento total",
    "endividamento_itens": "Endividamento por instituição",
    "concentracao_clientes": "Concentração de clientes",
    "crc_contador": "Contador (CRC)",
    "assinatura_representante": "Assinatura do representante",
    "patrimonio_declarado": "Bens e direitos declarados",
    "dividas_onus": "Dívidas e ônus",
    "lucros_dividendos": "Lucros e dividendos recebidos",
    "regime_bens": "Regime de bens",
}


def iso(dt):
    return dt.isoformat() if dt else None


def user_brief(u: User | None) -> dict | None:
    return {"id": str(u.id), "name": u.name, "email": u.email} if u else None


def user_full(u: User) -> dict:
    return {
        "id": str(u.id),
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "created_at": iso(u.created_at),
        "last_login_at": iso(u.last_login_at),
    }


def registration_row(r: Registration, doc_count: int | None = None, open_findings: int | None = None) -> dict:
    checklist = r.checklist or {}
    missing = [i["label"] for i in checklist.get("documents", []) if i.get("state") in ("missing", "unclassified")]
    return {
        "id": str(r.id),
        "code": r.code,
        "kind": r.kind,
        "subject_name": r.subject_name,
        "tax_id": r.tax_id,
        "status": r.status,
        "priority_score": r.priority_score,
        "priority_reasons": r.priority_reasons or [],
        "ready_for_decision": r.ready_for_decision,
        "missing": missing,
        "open_findings": open_findings if open_findings is not None else checklist.get("open_findings", 0),
        "blocking_findings": checklist.get("blocking_findings", 0),
        "document_count": doc_count,
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
        "decided_at": iso(r.decided_at),
    }


def field_out(f: ExtractedField) -> dict:
    return {
        "id": str(f.id),
        "name": f.name,
        "label": FIELD_LABELS.get(f.name, f.name),
        "value": f.value,
        "raw_value": f.raw_value,
        "confidence": f.confidence,
        "source": f.source,
        "page": f.page,
        "bbox": f.bbox,
        "valid": f.valid,
        "validation_note": f.validation_note,
        "status": f.status,
        "previous_value": f.previous_value,
        "reviewed_at": iso(f.reviewed_at),
    }


def finding_out(f: Finding) -> dict:
    return {
        "id": str(f.id),
        "registration_id": str(f.registration_id) if f.registration_id else None,
        "document_id": str(f.document_id) if f.document_id else None,
        "code": f.code,
        "category": f.category,
        "severity": f.severity,
        "title": f.title,
        "explanation": f.explanation,
        "evidence": f.evidence or [],
        "field_name": f.field_name,
        "confidence": f.confidence,
        "confidence_basis": f.confidence_basis,
        "recommended_action": f.recommended_action,
        "source": f.source,
        "rule_id": f.rule_id,
        "status": f.status,
        "resolved_by": user_brief(f.resolved_by),
        "resolved_at": iso(f.resolved_at),
        "resolution_note": f.resolution_note,
        "created_at": iso(f.created_at),
    }


def document_brief(d: Document) -> dict:
    return {
        "id": str(d.id),
        "registration_id": str(d.registration_id) if d.registration_id else None,
        "original_filename": d.original_filename,
        "mime_type": d.mime_type,
        "size_bytes": d.size_bytes,
        "sha256": d.sha256,
        "source": d.source,
        "source_ref": d.source_ref,
        "received_at": iso(d.received_at),
        "page_count": d.page_count,
        "doc_type": d.doc_type,
        "doc_type_confidence": d.doc_type_confidence,
        "doc_type_source": d.doc_type_source,
        "issuer": d.issuer,
        "status": d.status,
        "processing_error": d.processing_error,
        "processing_attempts": d.processing_attempts,
        "processed_at": iso(d.processed_at),
        "ai_status": d.ai_status,
        "ai_error": d.ai_error,
        "validity": d.validity,
        "suggested_registration_id": str(d.suggested_registration_id) if d.suggested_registration_id else None,
        "purged_at": iso(d.purged_at),
    }


def decision_out(d: Decision) -> dict:
    return {
        "id": str(d.id),
        "action": d.action,
        "reason": d.reason,
        "requested_items": d.requested_items or [],
        "overrides": d.overrides or [],
        "decided_by": user_brief(d.decided_by),
        "decided_at": iso(d.decided_at),
    }
