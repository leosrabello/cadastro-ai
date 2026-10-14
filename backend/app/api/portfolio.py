"""Portfolio clients (Normal and One7), commercials, data import, indicators, and signature tracking."""

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import audit
from app.api.serializers import iso
from app.db import get_db
from app.deps import ANY_ROLE, OPERATORS, SUPERVISORS, Principal
from app.errors import ApiError
from app.models import Commercial, DataImport, Modality, PortfolioClient, Registration, SignatureContract, SignatureTracking, utcnow
from app.portfolio import (
    CONTRACT_KINDS,
    FOLLOWUP_KINDS,
    ONE7_ANALYSIS_TYPES,
    ONE7_RESULTS,
    Catalog,
    change_status,
    clean_name,
    commercial_brief,
    ensure_signature_tracking,
    get_or_create_commercial,
    iso_date,
    name_key,
)
from app.portfolio import importer, metrics
from app.settings_store import get_setting

router = APIRouter(prefix="/api", tags=["portfolio"])

ModalityParam = Literal["normal", "one7"]
ScopeParam = Literal["normal", "one7", "all"]


def scope_modalities(scope: str) -> list[str]:
    return list(Modality.ALL) if scope == "all" else [scope]


# ---------------------------------------------------------------- catalog and commercials

@router.get("/portfolio/catalog")
def catalog(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    coms = db.execute(select(Commercial).order_by(Commercial.name)).scalars().all()
    return {
        "modalities": [{"key": k, "label": v} for k, v in Modality.LABELS.items()],
        "statuses": get_setting(db, "client_statuses"),
        "sla_days": get_setting(db, "portfolio")["sla_days"],
        "commercials": [{"id": str(c.id), "name": c.name, "is_active": c.is_active} for c in coms],
        "one7_results": ONE7_RESULTS,
        "one7_analysis_types": ONE7_ANALYSIS_TYPES,
        "situations": metrics.SITUATIONS,
    }


class CommercialIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class CommercialPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=120)
    is_active: bool | None = None


@router.get("/portfolio/commercials")
def list_commercials(p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(PortfolioClient.commercial_id, func.count()).group_by(PortfolioClient.commercial_id)).all())
    by_mod = {}
    for cid, mod, n in db.execute(select(PortfolioClient.commercial_id, PortfolioClient.modality, func.count()).group_by(PortfolioClient.commercial_id, PortfolioClient.modality)).all():
        by_mod.setdefault(cid, {})[mod] = n
    coms = db.execute(select(Commercial).order_by(Commercial.name)).scalars().all()
    return {"items": [{"id": str(c.id), "name": c.name, "is_active": c.is_active, "clients": counts.get(c.id, 0),
                       "by_modality": by_mod.get(c.id, {}), "created_at": iso(c.created_at)} for c in coms],
            "without_commercial": counts.get(None, 0)}


@router.post("/portfolio/commercials", status_code=201)
def create_commercial(body: CommercialIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    name = clean_name(body.name)
    if db.execute(select(Commercial).where(Commercial.name_key == name_key(name))).scalar_one_or_none():
        raise ApiError(409, "duplicate", "Já existe um comercial com esse nome.")
    com = get_or_create_commercial(db, name)
    audit.record(db, "commercial.created", actor=p.user, entity_type="commercial", entity_id=com.id, details={"name": com.name}, ip=p.ip)
    db.commit()
    return {"id": str(com.id), "name": com.name, "is_active": com.is_active}


@router.patch("/portfolio/commercials/{cid}")
def update_commercial(cid: uuid.UUID, body: CommercialPatch, p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    com = db.get(Commercial, cid)
    if com is None:
        raise ApiError(404, "not_found", "Comercial não encontrado.")
    before = {"name": com.name, "is_active": com.is_active}
    if body.name is not None:
        name = clean_name(body.name)
        other = db.execute(select(Commercial).where(Commercial.name_key == name_key(name), Commercial.id != com.id)).scalar_one_or_none()
        if other:
            raise ApiError(409, "duplicate", "Já existe um comercial com esse nome.")
        com.name, com.name_key = name, name_key(name)
    if body.is_active is not None:
        com.is_active = body.is_active
    com.updated_at = utcnow()
    audit.record(db, "commercial.updated", actor=p.user, entity_type="commercial", entity_id=com.id,
                 details={"before": before, "after": {"name": com.name, "is_active": com.is_active}}, ip=p.ip)
    db.commit()
    return {"id": str(com.id), "name": com.name, "is_active": com.is_active}


# ---------------------------------------------------------------- clients

class Followup(BaseModel):
    date: date
    note: str = Field("", max_length=2000)
    kind: Literal["documentacao", "assinatura"] = "documentacao"


class ClientIn(BaseModel):
    modality: ModalityParam
    name: str = Field(min_length=2, max_length=300)
    commercial_id: uuid.UUID | None = None
    status: str = Field(min_length=2, max_length=64)
    entry_date: date | None = None  # required for Normal; One7 folders may not be registered at ONE7 yet
    pre_committee_date: date | None = None
    committee_date: date | None = None
    notes: str = Field("", max_length=10_000)
    risk_exit: bool = False
    limit_expired: bool = False
    extra: dict = Field(default_factory=dict)


class ClientPatch(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=300)
    commercial_id: uuid.UUID | None = None
    clear_commercial: bool = False
    status: str | None = Field(None, min_length=2, max_length=64)
    entry_date: date | None = None
    pre_committee_date: date | None = None
    committee_date: date | None = None
    contract_issued_date: date | None = None
    signature_completed_date: date | None = None
    clear_dates: list[Literal["pre_committee_date", "committee_date", "contract_issued_date", "signature_completed_date"]] = Field(default_factory=list)
    notes: str | None = Field(None, max_length=10_000)
    risk_exit: bool | None = None
    limit_expired: bool | None = None
    milestones: dict[str, dict[str, bool]] | None = None
    extra: dict | None = None
    followups: list[Followup] | None = Field(None, max_length=200)


def _clean_extra(modality: str, extra: dict) -> dict:
    if modality != Modality.ONE7:
        return {}
    result = extra.get("resultado_comite") or "em_analise"
    if result not in ONE7_RESULTS:
        raise ApiError(422, "invalid_extra", "Resultado do comitê One7 inválido.")
    analysis = extra.get("tipo_analise") or None
    if analysis and analysis not in ONE7_ANALYSIS_TYPES:
        raise ApiError(422, "invalid_extra", "Tipo de análise inválido.")
    sent = extra.get("data_envio_comite") or None
    if sent:
        try:
            sent = date.fromisoformat(str(sent)).isoformat()
        except ValueError:
            raise ApiError(422, "invalid_extra", "Data de envio ao comitê inválida.")
    return {"resultado_comite": result, "tipo_analise": analysis, "data_envio_comite": sent, "em_triagem": bool(analysis) and bool(extra.get("em_triagem"))}


def _milestone_template(modality: str) -> dict:
    if modality == Modality.ONE7:
        return {"formalizacao": {"analiseComite": False, "aprovacaoSistema": False}, "cadastro": {"cadastroFormalizacao": False}}
    return {"formalizacao": {"cadastro": False, "homologado": False}, "contratos": {"emissao": False, "processo": False, "assinado": False}}


def _check_dates(c: PortfolioClient) -> None:
    if c.contract_issued_date and c.signature_completed_date and c.signature_completed_date < c.contract_issued_date:
        raise ApiError(422, "invalid_dates", "A conclusão da assinatura não pode ser anterior à emissão do contrato.")
    for label, d in (("pré-comitê", c.pre_committee_date), ("comitê", c.committee_date)):
        if d and c.entry_date and d < c.entry_date:
            raise ApiError(422, "invalid_dates", f"A data do {label} não pode ser anterior à entrada da pasta.")


def _commercial(db: Session, cid: uuid.UUID | None) -> Commercial | None:
    if cid is None:
        return None
    com = db.get(Commercial, cid)
    if com is None:
        raise ApiError(422, "invalid_commercial", "Comercial não encontrado.")
    return com


def client_out(c: PortfolioClient, cat: Catalog, facts: metrics.ClientFacts | None = None, registrations: list | None = None, trackings: list | None = None) -> dict:
    out = {
        "id": str(c.id),
        "external_id": c.external_id,
        "modality": c.modality,
        "name": c.name,
        "commercial": commercial_brief(c.commercial),
        "status": c.status,
        "status_label": cat.label(c.modality, c.status),
        "entry_date": iso_date(c.entry_date),
        "pre_committee_date": iso_date(c.pre_committee_date),
        "committee_date": iso_date(c.committee_date),
        "contract_issued_date": iso_date(c.contract_issued_date),
        "signature_completed_date": iso_date(c.signature_completed_date),
        "notes": c.notes,
        "risk_exit": c.risk_exit,
        "limit_expired": c.limit_expired,
        "milestones": {**_milestone_template(c.modality), **(c.milestones or {})},
        "extra": c.extra or {},
        "followups": c.followups or [],
        "status_history": [{**h, "label": cat.label(c.modality, h.get("status", ""))} for h in (c.status_history or [])],
        "source": c.source,
        "created_at": iso(c.created_at),
        "updated_at": iso(c.updated_at),
        "imported_at": iso(c.imported_at),
    }
    if facts:
        out.update(situation=facts.situation, days_in_status=facts.days_in_status, total_days=facts.total_days, total_days_open=facts.total_days_open,
                   signature_days=facts.signature_days, signature_open=facts.signature_open)
    if registrations is not None:
        out["registrations"] = [{"id": str(r.id), "code": r.code, "status": r.status} for r in registrations]
    if trackings is not None:
        out["signature_trackings"] = [str(t.id) for t in trackings]
    if c.legacy_history:
        out["legacy_history"] = c.legacy_history
    return out


def _load_clients(db: Session, modalities: list[str]) -> list[PortfolioClient]:
    return db.execute(select(PortfolioClient).options(selectinload(PortfolioClient.commercial))
                      .where(PortfolioClient.modality.in_(modalities))).scalars().all()


def _load_trackings(db: Session, modalities: list[str] | None = None) -> list[SignatureTracking]:
    stmt = select(SignatureTracking).options(selectinload(SignatureTracking.contracts), selectinload(SignatureTracking.commercial), selectinload(SignatureTracking.client))
    if modalities:
        stmt = stmt.where(SignatureTracking.modality.in_(modalities))
    return db.execute(stmt).scalars().all()


def _facts(db: Session, clients: list[PortfolioClient], trackings: list[SignatureTracking], cat: Catalog) -> list[metrics.ClientFacts]:
    sla = get_setting(db, "portfolio")["sla_days"]
    contracts = metrics.group_contracts(trackings)
    today, now = date.today(), utcnow()
    return [metrics.client_facts(c, cat, contracts.get(c.id, []), sla, today, now) for c in clients]


@router.get("/portfolio/clients")
def list_clients(
    modality: ScopeParam = "normal",
    q: str | None = Query(None, max_length=100),
    status: str | None = None,
    commercial_id: str | None = None,
    situation: str | None = None,
    sort: Literal["entry", "name", "days"] = "entry",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    p: Principal = Depends(ANY_ROLE),
    db: Session = Depends(get_db),
):
    cat = Catalog.load(db)
    mods = scope_modalities(modality)
    facts = _facts(db, _load_clients(db, mods), _load_trackings(db, mods), cat)
    facts = filter_facts(facts, q=q, status=status, commercial_id=commercial_id, situation=situation)
    key = {"entry": lambda f: (f.client.entry_date or date.min, f.client.name), "name": lambda f: name_key(f.client.name),
           "days": lambda f: f.days_in_status or 0}[sort]
    facts.sort(key=key, reverse=sort != "name")
    total = len(facts)
    page_items = facts[(page - 1) * page_size: page * page_size]
    return {"items": [client_out(f.client, cat, f) for f in page_items], "total": total, "page": page, "page_size": page_size}


def filter_facts(facts, *, q=None, status=None, commercial_id=None, situation=None, entry_from=None, entry_to=None, committee_from=None, committee_to=None):
    statuses = set(status.split(",")) if status else None
    situations = set(situation.split(",")) if situation else None
    coms = set(commercial_id.split(",")) if commercial_id else None
    qk = name_key(q) if q else ""
    out = []
    for f in facts:
        c = f.client
        if qk and qk not in c.name_key:
            continue
        if statuses is not None and c.status not in statuses:
            continue
        if situations is not None and f.situation not in situations:
            continue
        if coms is not None and (str(c.commercial_id) if c.commercial_id else "none") not in coms:
            continue
        if entry_from and (not c.entry_date or c.entry_date < entry_from):
            continue
        if entry_to and (not c.entry_date or c.entry_date > entry_to):
            continue
        if committee_from and (not c.committee_date or c.committee_date < committee_from):
            continue
        if committee_to and (not c.committee_date or c.committee_date > committee_to):
            continue
        out.append(f)
    return out


@router.post("/portfolio/clients", status_code=201)
def create_client(body: ClientIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    cat = Catalog.load(db)
    if not cat.has(body.modality, body.status):
        raise ApiError(422, "invalid_status", "Status inválido para a modalidade.")
    if body.modality == Modality.NORMAL and body.entry_date is None:
        raise ApiError(422, "entry_date_required", "Informe a data de entrada da pasta.")
    now = utcnow()
    name = clean_name(body.name).upper()
    c = PortfolioClient(
        modality=body.modality, name=name, name_key=name_key(name), status=body.status, entry_date=body.entry_date,
        pre_committee_date=body.pre_committee_date, committee_date=body.committee_date, notes=body.notes.strip(),
        risk_exit=body.risk_exit if body.modality == Modality.NORMAL else False,
        limit_expired=body.limit_expired if body.modality == Modality.NORMAL else False,
        milestones=_milestone_template(body.modality), extra=_clean_extra(body.modality, body.extra),
        followups=[], status_history=[{"status": body.status, "at": now.isoformat()}], legacy_history=[],
        source="manual", created_at=now, updated_at=now,
    )
    c.commercial = _commercial(db, body.commercial_id)
    _check_dates(c)
    db.add(c)
    db.flush()
    if cat.opens_signature(c.modality, c.status):
        ensure_signature_tracking(db, c)
    audit.record(db, "client.created", actor=p.user, entity_type="client", entity_id=c.id, details={"name": c.name, "modality": c.modality, "status": c.status}, ip=p.ip)
    db.commit()
    return client_out(c, cat)


def get_client(db: Session, cid: uuid.UUID) -> PortfolioClient:
    c = db.get(PortfolioClient, cid)
    if c is None:
        raise ApiError(404, "not_found", "Cliente não encontrado.")
    return c


@router.get("/portfolio/clients/{cid}")
def client_detail(cid: uuid.UUID, p: Principal = Depends(ANY_ROLE), db: Session = Depends(get_db)):
    cat = Catalog.load(db)
    c = get_client(db, cid)
    trackings = db.execute(select(SignatureTracking).options(selectinload(SignatureTracking.contracts)).where(SignatureTracking.client_id == c.id)).scalars().all()
    regs = db.execute(select(Registration).where(Registration.client_id == c.id).order_by(Registration.created_at)).scalars().all()
    f = _facts(db, [c], trackings, cat)[0]
    return client_out(c, cat, f, regs, trackings)


@router.patch("/portfolio/clients/{cid}")
def update_client(cid: uuid.UUID, body: ClientPatch, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    cat = Catalog.load(db)
    c = get_client(db, cid)
    before = client_out(c, cat)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        c.name = clean_name(body.name).upper()
        c.name_key = name_key(c.name)
    if body.clear_commercial:
        c.commercial = None
    elif body.commercial_id is not None:
        c.commercial = _commercial(db, body.commercial_id)
    for attr in ("entry_date", "pre_committee_date", "committee_date", "contract_issued_date", "signature_completed_date"):
        if data.get(attr) is not None:
            setattr(c, attr, data[attr])
    for attr in body.clear_dates:
        setattr(c, attr, None)
    if body.notes is not None:
        c.notes = body.notes.strip()
    if c.modality == Modality.NORMAL:
        if body.risk_exit is not None:
            c.risk_exit = body.risk_exit
        if body.limit_expired is not None:
            c.limit_expired = body.limit_expired
    if body.milestones is not None:
        template = _milestone_template(c.modality)
        c.milestones = {g: {k: bool(body.milestones.get(g, {}).get(k, v)) for k, v in items.items()} for g, items in template.items()}
    if body.extra is not None:
        c.extra = _clean_extra(c.modality, {**(c.extra or {}), **body.extra})
    if body.followups is not None:
        c.followups = [{"date": f.date.isoformat(), "note": f.note.strip(), "kind": f.kind if f.kind in FOLLOWUP_KINDS else "documentacao"}
                       for f in sorted(body.followups, key=lambda f: f.date)]
    if body.status is not None:
        if not cat.has(c.modality, body.status):
            raise ApiError(422, "invalid_status", "Status inválido para a modalidade.")
        change_status(db, c, body.status, cat)
    _check_dates(c)
    c.updated_at = utcnow()
    after = client_out(c, cat)
    changed = {k: {"before": before[k], "after": after[k]} for k in after if k not in ("updated_at", "status_history") and before.get(k) != after[k]}
    audit.record(db, "client.updated", actor=p.user, entity_type="client", entity_id=c.id, details={"changes": changed}, ip=p.ip)
    db.commit()
    return client_detail(cid, p, db)


# ---------------------------------------------------------------- indicators

@router.get("/portfolio/summary")
def summary(
    modality: ScopeParam = "normal",
    q: str | None = Query(None, max_length=100),
    status: str | None = None,
    commercial_id: str | None = None,
    situation: str | None = None,
    entry_from: date | None = None,
    entry_to: date | None = None,
    committee_from: date | None = None,
    committee_to: date | None = None,
    rows: bool = False,
    p: Principal = Depends(ANY_ROLE),
    db: Session = Depends(get_db),
):
    cat = Catalog.load(db)
    mods = scope_modalities(modality)
    trackings = _load_trackings(db, mods)
    all_facts = _facts(db, _load_clients(db, mods), trackings, cat)
    filters = dict(q=q, status=status, commercial_id=commercial_id, situation=situation, entry_from=entry_from, entry_to=entry_to,
                   committee_from=committee_from, committee_to=committee_to)
    facts = filter_facts(all_facts, **filters)
    filtered = any(v for v in filters.values())
    # signature cards follow the same scope: the filtered clients' contracts, or every company of the modality
    if filtered:
        ids = {f.client.id for f in facts}
        scoped = [t for t in trackings if t.client_id in ids]
    else:
        scoped = trackings
    sla = get_setting(db, "portfolio")["sla_days"]
    out = metrics.summarize(facts, cat, mods, scoped, sla, date.today())
    out.update(
        modality=modality,
        modality_label="Consolidado (Normal e One7)" if modality == "all" else Modality.LABELS[modality],
        filtered=filtered,
        generated_at=iso(utcnow()),
        generated_by=p.user.name,
        population=len(all_facts),
    )
    if rows:
        out["rows"] = [metrics.fact_row(f) for f in sorted(facts, key=lambda f: (f.client.entry_date or date.min), reverse=True)]
    return out


# ---------------------------------------------------------------- import

@router.post("/portfolio/import/preview")
async def import_preview(file: UploadFile = File(...), p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    data = await file.read(importer.MAX_BYTES + 1)
    try:
        plan = importer.build_plan(db, data, file.filename or "importacao.json")
    except importer.ImportFileError as exc:
        raise ApiError(422, "invalid_file", str(exc))
    db.rollback()
    return plan.out()


@router.post("/portfolio/import")
async def import_apply(file: UploadFile = File(...), sha256: str = Form(..., min_length=64, max_length=64), p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    data = await file.read(importer.MAX_BYTES + 1)
    try:
        plan = importer.build_plan(db, data, file.filename or "importacao.json")
    except importer.ImportFileError as exc:
        raise ApiError(422, "invalid_file", str(exc))
    if plan.sha256 != sha256:
        raise ApiError(409, "file_changed", "O arquivo mudou desde a prévia. Gere a prévia de novo antes de importar.")
    try:
        result = importer.apply(db, plan, p.user.id)
        audit.record(db, "portfolio.imported", actor=p.user, entity_type="import", entity_id=plan.sha256[:16], details=result, ip=p.ip)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {**result, "issues": [i.out() for i in plan.issues]}


@router.get("/portfolio/imports")
def import_history(p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    rows = db.execute(select(DataImport).options(selectinload(DataImport.imported_by)).order_by(DataImport.imported_at.desc()).limit(50)).scalars().all()
    return {"items": [{"id": str(r.id), "filename": r.filename, "sha256": r.sha256, "imported_at": iso(r.imported_at),
                       "imported_by": r.imported_by.name if r.imported_by else None, "summary": r.summary} for r in rows]}


# ---------------------------------------------------------------- signatures (conferência de assinaturas no portal)

class ContractIn(BaseModel):
    process_number: str | None = Field(None, max_length=80)
    created_date: date | None = None
    issued_date: date | None = None
    signed_date: date | None = None
    clear: list[Literal["created_date", "issued_date", "signed_date"]] = Field(default_factory=list)


class TrackingIn(BaseModel):
    company_name: str | None = Field(None, min_length=2, max_length=300)
    client_id: uuid.UUID | None = None
    commercial_id: uuid.UUID | None = None
    modality: ModalityParam = "normal"


class TrackingPatch(BaseModel):
    company_name: str | None = Field(None, min_length=2, max_length=300)
    commercial_id: uuid.UUID | None = None
    clear_commercial: bool = False
    contracts: dict[Literal["SEC", "FIDC"], ContractIn] | None = None
    followups: list[Followup] | None = Field(None, max_length=200)


def tracking_out(t: SignatureTracking, today: date, cat: Catalog) -> dict:
    contracts = []
    for kind in CONTRACT_KINDS:
        k = next((x for x in t.contracts if x.kind == kind), None)
        if k is None:
            continue
        days, state = metrics.contract_days(k, today)
        contracts.append({"kind": kind, "process_number": k.process_number, "created_date": iso_date(k.created_date),
                          "issued_date": iso_date(k.issued_date), "signed_date": iso_date(k.signed_date), "days": days, "state": state})
    states = {k["state"] for k in contracts}
    if states == {"assinado"}:
        overall = "assinado"
    elif "aguardando" in states:
        overall = "aguardando"
    elif "assinado" in states:
        overall = "parcial"
    else:
        overall = "sem_emissao"
    pending = [k for k in contracts if k["state"] == "aguardando"]
    signed = [k["signed_date"] for k in contracts if k["signed_date"]]
    return {
        "id": str(t.id),
        "external_id": t.external_id,
        "company_name": t.company_name,
        "modality": t.modality,
        "commercial": commercial_brief(t.commercial),
        "client": {"id": str(t.client.id), "name": t.client.name, "status": t.client.status,
                   "status_label": cat.label(t.client.modality, t.client.status)} if t.client else None,
        "auto_created": t.auto_created,
        "contracts": contracts,
        "state": overall,
        "waiting_days": max((k["days"] for k in pending), default=None),
        "oldest_pending_issue": min((k["issued_date"] for k in pending), default=None),
        "last_signed": max(signed, default=None),
        "followups": t.followups or [],
        "created_at": iso(t.created_at),
        "updated_at": iso(t.updated_at),
    }


def _sort_key(row: dict):
    # pending first with the oldest emission on top (the previous dashboard's order), then most recently signed, then newest
    if row["oldest_pending_issue"]:
        return (0, date.fromisoformat(row["oldest_pending_issue"]).toordinal())
    if row["last_signed"]:
        return (1, -date.fromisoformat(row["last_signed"]).toordinal())
    return (2, -date.fromisoformat(row["created_at"][:10]).toordinal())


@router.get("/signatures")
def list_signatures(
    modality: ScopeParam = "all",
    q: str | None = Query(None, max_length=100),
    state: str | None = None,
    commercial_id: str | None = None,
    p: Principal = Depends(ANY_ROLE),
    db: Session = Depends(get_db),
):
    cat = Catalog.load(db)
    today = date.today()
    trackings = _load_trackings(db, scope_modalities(modality))
    sla = get_setting(db, "portfolio")["sla_days"]
    qk = name_key(q) if q else ""
    coms = set(commercial_id.split(",")) if commercial_id else None
    states = set(state.split(",")) if state else None
    rows = []
    kept = []
    for t in trackings:
        if qk and qk not in name_key(t.company_name) and not (t.commercial and qk in t.commercial.name_key):
            continue
        if coms is not None and (str(t.commercial_id) if t.commercial_id else "none") not in coms:
            continue
        row = tracking_out(t, today, cat)
        if states is not None and row["state"] not in states:
            continue
        rows.append(row)
        kept.append(t)
    rows.sort(key=_sort_key)
    return {"items": rows, "kpis": metrics.signature_kpis(kept, today), "kpis_all": metrics.signature_kpis(trackings, today), "sla_days": sla}


def get_tracking(db: Session, tid: uuid.UUID) -> SignatureTracking:
    t = db.get(SignatureTracking, tid)
    if t is None:
        raise ApiError(404, "not_found", "Registro de assinatura não encontrado.")
    return t


@router.post("/signatures", status_code=201)
def create_signature(body: TrackingIn, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    cat = Catalog.load(db)
    if body.client_id:
        c = get_client(db, body.client_id)
        if db.execute(select(SignatureTracking).where(SignatureTracking.client_id == c.id)).scalars().first():
            raise ApiError(409, "duplicate", "Este cliente já tem contratos em acompanhamento.")
        t = SignatureTracking(client_id=c.id, modality=c.modality, company_name=c.name, commercial_id=c.commercial_id)
    else:
        if not body.company_name:
            raise ApiError(422, "company_required", "Informe a empresa ou escolha um cliente da carteira.")
        t = SignatureTracking(modality=body.modality, company_name=clean_name(body.company_name).upper())
        t.commercial = _commercial(db, body.commercial_id)
    now = utcnow()
    t.created_at = t.updated_at = now
    t.contracts = [SignatureContract(kind=k) for k in CONTRACT_KINDS]
    db.add(t)
    db.flush()
    audit.record(db, "signature.created", actor=p.user, entity_type="signature", entity_id=t.id, details={"company": t.company_name}, ip=p.ip)
    db.commit()
    db.refresh(t)
    return tracking_out(t, date.today(), cat)


@router.patch("/signatures/{tid}")
def update_signature(tid: uuid.UUID, body: TrackingPatch, p: Principal = Depends(OPERATORS), db: Session = Depends(get_db)):
    cat = Catalog.load(db)
    t = get_tracking(db, tid)
    before = tracking_out(t, date.today(), cat)
    if body.company_name is not None and not t.client_id:
        t.company_name = clean_name(body.company_name).upper()
    if body.clear_commercial:
        t.commercial = None
    elif body.commercial_id is not None:
        t.commercial = _commercial(db, body.commercial_id)
    if body.contracts:
        by_kind = {k.kind: k for k in t.contracts}
        for kind, change in body.contracts.items():
            k = by_kind.get(kind)
            if k is None:
                k = SignatureContract(kind=kind)
                t.contracts.append(k)
            data = change.model_dump(exclude_unset=True)
            if "process_number" in data:
                k.process_number = (change.process_number or "").strip()
            for attr in ("created_date", "issued_date", "signed_date"):
                if data.get(attr) is not None:
                    setattr(k, attr, data[attr])
            for attr in change.clear:
                setattr(k, attr, None)
            if k.signed_date and not k.issued_date:
                raise ApiError(422, "invalid_dates", f"Contrato {kind}: informe a emissão antes da assinatura.")
            if k.signed_date and k.issued_date and k.signed_date < k.issued_date:
                raise ApiError(422, "invalid_dates", f"Contrato {kind}: a assinatura não pode ser anterior à emissão.")
            if k.signed_date and k.signed_date > date.today():
                raise ApiError(422, "invalid_dates", f"Contrato {kind}: a assinatura não pode estar no futuro.")
    if body.followups is not None:
        t.followups = [{"date": f.date.isoformat(), "note": f.note.strip(), "kind": "assinatura"} for f in sorted(body.followups, key=lambda f: f.date)]
    t.updated_at = utcnow()
    db.flush()
    after = tracking_out(t, date.today(), cat)
    audit.record(db, "signature.updated", actor=p.user, entity_type="signature", entity_id=t.id,
                 details={"company": t.company_name, "before": {"contracts": before["contracts"], "followups": len(before["followups"])},
                          "after": {"contracts": after["contracts"], "followups": len(after["followups"])}}, ip=p.ip)
    db.commit()
    return after


@router.delete("/signatures/{tid}", status_code=204)
def delete_signature(tid: uuid.UUID, p: Principal = Depends(SUPERVISORS), db: Session = Depends(get_db)):
    t = get_tracking(db, tid)
    snapshot = tracking_out(t, date.today(), Catalog.load(db))
    db.delete(t)
    audit.record(db, "signature.deleted", actor=p.user, entity_type="signature", entity_id=tid, details=snapshot, ip=p.ip)
    db.commit()

