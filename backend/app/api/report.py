"""The analysis report of a registration: everything the documents show, put together for the
credit committee, plus the analyst's own opinion. Rendered as an image by the desktop client."""

import io
import json
import uuid
from datetime import date

import fitz
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.api.registrations import get_registration
from app.api.serializers import iso
from app.db import get_db
from app.deps import ANY_ROLE, Principal
from app.errors import ApiError
from app.models import Decision, DocStatus, Document, Finding, FindingStatus, Modality, utcnow
from app.pipeline.normalize import digits, format_cnpj, format_cpf, parse_money
from app.settings_store import get_setting
from app.storage import get_store

router = APIRouter(prefix="/api", tags=["report"])

ANALYST_FIELDS = ["parecer", "recomendacao", "limite_total", "taxa", "comercial", "regiao"]
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _f(doc: Document, name: str) -> str | None:
    return next((f.value for f in doc.fields if f.name == name and f.value), None)


def _money(v: str | None) -> float | None:
    return parse_money(v) if v else None


def _latest(docs: list[Document], doc_type: str) -> Document | None:
    cands = [d for d in docs if d.doc_type == doc_type]
    return max(cands, key=lambda d: (_f(d, "exercicio") or "", d.received_at)) if cands else None


def _commercial_name(reg) -> str | None:
    if reg.commercial:
        return reg.commercial.name
    return reg.client.commercial.name if reg.client and reg.client.commercial else None


@router.get("/registrations/{rid}/report")
def report(rid: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    reg = get_registration(db, rid)
    docs = db.execute(select(Document).where(Document.registration_id == reg.id, Document.status == DocStatus.PROCESSED)).scalars().all()
    profiles = get_setting(db, "requirement_profiles")
    types = get_setting(db, "document_types")

    # company
    tax_label, tax_fmt = (("CNPJ", format_cnpj(reg.tax_id)) if reg.tax_id and len(reg.tax_id) == 14
                          else ("CPF", format_cpf(reg.tax_id)) if reg.tax_id and len(reg.tax_id) == 11 else (None, None))
    company = {"razao_social": reg.subject_name, "cnpj": tax_fmt, "tax_id_label": tax_label,
               "endereco": None, "situacao_cadastral": None, "data_registro": None}
    contract = _latest(docs, "contrato_social")
    for t in ("cartao_cnpj", "certidao_simplificada", "contrato_social", "estatuto_social"):
        d = _latest(docs, t)
        if d:
            company["endereco"] = company["endereco"] or _f(d, "endereco")
            company["situacao_cadastral"] = company["situacao_cadastral"] or _f(d, "situacao_cadastral")
            company["data_registro"] = company["data_registro"] or _f(d, "data_registro")

    # partners: names from the corporate documents, enriched by their IRPF and ID documents
    names: list[str] = []
    for t in ("contrato_social", "certidao_simplificada", "estatuto_social"):
        d = _latest(docs, t)
        if d and _f(d, "socios"):
            names += [n.strip() for n in _f(d, "socios").split(";") if n.strip() and n.strip() not in names]
    people: dict[str, dict] = {n: {"nome": n, "cpf": None, "irpf": []} for n in names}
    for d in docs:
        nome = _f(d, "nome")
        if d.doc_type not in ("irpf", "rg", "cin", "cnh") or not nome:
            continue
        person = people.setdefault(nome, {"nome": nome, "cpf": None, "irpf": [], "fora_do_quadro": bool(names)})
        cpf = _f(d, "cpf")
        if cpf and len(digits(cpf)) == 11:
            person["cpf"] = format_cpf(digits(cpf))
        if d.doc_type == "irpf":
            person["irpf"].append({"exercicio": _f(d, "exercicio"), "bens": _money(_f(d, "patrimonio_declarado")),
                                   "dividas": _money(_f(d, "dividas_onus")), "dividendos": _money(_f(d, "lucros_dividendos"))})
    for person in people.values():
        person["irpf"].sort(key=lambda x: x["exercicio"] or "")

    # revenue: merge every revenue statement's monthly table
    revenue: dict[str, dict[str, float]] = {}
    for d in docs:
        if d.doc_type == "faturamento" and _f(d, "faturamento_mensal"):
            try:
                for y, months in json.loads(_f(d, "faturamento_mensal"))["years"].items():
                    revenue.setdefault(y, {}).update(months)
            except (ValueError, KeyError):
                continue
    years = sorted(revenue)
    cur = years[-1] if years else None
    prev = years[-2] if len(years) > 1 else None
    rev_summary = None
    if cur:
        months_cur = sorted(int(m) for m in revenue[cur])
        avg_cur = sum(revenue[cur].values()) / len(months_cur)
        same_prev = [revenue[prev][str(m)] for m in months_cur if prev and str(m) in revenue[prev]]
        avg_prev_same = sum(same_prev) / len(same_prev) if same_prev else None
        rev_summary = {
            "year": cur, "previous_year": prev, "months": months_cur,
            "total": round(sum(revenue[cur].values()), 2),
            "average": round(avg_cur, 2),
            "previous_total": round(sum(revenue[prev].values()), 2) if prev else None,
            "previous_average_same_months": round(avg_prev_same, 2) if avg_prev_same else None,
            "growth_same_months": round(avg_cur / avg_prev_same - 1, 4) if avg_prev_same else None,
        }

    # debt
    debt = None
    d_debt = _latest(docs, "endividamento")
    if d_debt:
        total = _money(_f(d_debt, "endividamento_total"))
        try:
            items = json.loads(_f(d_debt, "endividamento_itens") or "[]")
        except ValueError:
            items = []
        debt = {"total": total, "date": _f(d_debt, "data_emissao"), "items": sorted(items, key=lambda i: -(i.get("tomado") or 0))[:8],
                "times_average_revenue": round(total / rev_summary["average"], 2) if total and rev_summary and rev_summary["average"] else None}

    # customers
    customers = None
    d_abc = _latest(docs, "curva_abc")
    if d_abc and _f(d_abc, "concentracao_clientes"):
        try:
            rows = json.loads(_f(d_abc, "concentracao_clientes"))
            customers = {"top": rows[:5], "top3_share": round(sum(r["percentual"] for r in rows[:3]), 2)}
        except ValueError:
            customers = None

    # statements
    statements = []
    for d in docs:
        if d.doc_type == "balanco_dre":
            statements.append({"exercicio": _f(d, "exercicio"), "receita_liquida": _money(_f(d, "receita_liquida")),
                               "lucro_liquido": _money(_f(d, "lucro_liquido")), "patrimonio_liquido": _money(_f(d, "patrimonio_liquido")),
                               "ativo_total": _money(_f(d, "ativo_total"))})
    statements.sort(key=lambda s: s["exercicio"] or "")

    findings = db.execute(select(Finding).where(Finding.registration_id == reg.id, Finding.status.in_(FindingStatus.OPEN_STATES))).scalars().all()
    by_sev: dict[str, int] = {}
    for f in findings:
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    # one line per distinct point, rule-based before AI-assisted, most severe first
    source_rank = {"rule": 0, "forensics": 0, "human": 0, "system": 1, "ai": 2}
    grouped: dict[str, dict] = {}
    for f in sorted(findings, key=lambda f: (SEV_ORDER.get(f.severity, 9), source_rank.get(f.source, 3), f.created_at)):
        key = f.explanation[:120] if f.source == "ai" else f.title
        g = grouped.setdefault(key, {"title": f.title, "severity": f.severity, "explanation": f.explanation,
                                         "recommended_action": f.recommended_action, "source": f.source, "count": 0})
        g["count"] += 1
    top = list(grouped.values())
    decision = db.execute(select(Decision).where(Decision.registration_id == reg.id).order_by(Decision.decided_at.desc()).limit(1)).scalar_one_or_none()

    visit = _latest(docs, "relatorio_visita")
    thumbs = [str(d.id) for d in sorted(docs, key=lambda d: d.received_at) if d.doc_type not in ("relatorio_visita",)][:5]
    refs = reg.reference_fields or {}

    audit.record(db, "registration.report_generated", actor=p.user, entity_type="registration", entity_id=reg.id, registration_id=reg.id, ip=p.ip)
    db.commit()
    return {
        "generated_at": iso(utcnow()),
        "generated_by": p.user.name,
        "reference_date": date.today().isoformat(),
        "registration": {"id": str(reg.id), "code": reg.code, "kind": reg.kind, "kind_label": profiles.get(reg.kind, {}).get("label", reg.kind),
                         "modality": reg.modality, "modality_label": Modality.LABELS.get(reg.modality, reg.modality),
                         "status": reg.status, "created_at": iso(reg.created_at), "ready_for_decision": reg.ready_for_decision},
        "company": company,
        "partners": list(people.values()),
        "governance": {k: _f(contract, k) for k in ("administradores", "responsaveis_assinatura", "forma_assinatura", "consolidado")} if contract else None,
        "revenue": {"series": revenue, "summary": rev_summary},
        "debt": debt,
        "customers": customers,
        "statements": statements,
        "checklist": reg.checklist or {},
        "findings": {"by_severity": by_sev, "top": top[:6]},
        "documents": [{"id": str(d.id), "type": types.get(d.doc_type, {}).get("label", d.doc_type or "Não identificado"),
                       "validity": (d.validity or {}).get("state"), "ai_summary": (d.classification or {}).get("ai_summary")} for d in docs],
        # the commercial comes from the linked portfolio client unless the analyst typed one
        "analysis": {k: refs.get(k) or (_commercial_name(reg) if k == "comercial" else None) for k in ANALYST_FIELDS},
        "decision": {"action": decision.action, "reason": decision.reason, "by": decision.decided_by.name if decision.decided_by else None,
                     "at": iso(decision.decided_at)} if decision else None,
        "images": {"visit_document_id": str(visit.id) if visit else None, "page_document_ids": thumbs},
    }


@router.get("/documents/{did}/photo")
def document_photo(did: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    """The largest photograph embedded in a PDF (the visit report's picture of the company)."""
    doc = db.get(Document, did)
    if doc is None or doc.mime_type != "application/pdf" or not doc.storage_key:
        raise ApiError(404, "not_found", "Sem fotografia neste documento.")
    data = get_store().get(doc.storage_key)
    best = None
    with fitz.open(stream=data, filetype="pdf") as pdf:
        for page in pdf:
            for img in page.get_images(full=True):
                info = pdf.extract_image(img[0])
                if info and info.get("width", 0) * info.get("height", 0) > (best[0] if best else 40_000):
                    best = (info["width"] * info["height"], info["image"])
    if best is None:
        raise ApiError(404, "not_found", "Sem fotografia neste documento.")
    with Image.open(io.BytesIO(best[1])) as im:
        out = io.BytesIO()
        im.convert("RGB").save(out, "JPEG", quality=85)
    audit.record(db, "document.viewed", actor=p.user, entity_type="document", entity_id=doc.id, registration_id=doc.registration_id,
                 details={"part": "photo"}, ip=p.ip)
    db.commit()
    return Response(out.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})
