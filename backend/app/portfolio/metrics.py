"""Portfolio indicators. The rules follow the team's previous dashboard (aba Relatórios):

- situação: concluído (status Apto a Operar), negado (Negada), atrasado (parado no mesmo status há
  sla_days dias ou mais), em andamento (o resto);
- tempo total: da data de entrada até a primeira vez em Apto a Operar, ou até hoje se em andamento;
- tempo de assinatura: da emissão do contrato até a assinatura. Contracts in Assinaturas are the source;
  the client's own emission/conclusion dates are used only when it has no contracts there.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.models import Modality, PortfolioClient, SignatureContract, SignatureTracking
from app.portfolio import Catalog, client_outcome, days_between, parse_iso_datetime

SITUATIONS = {"andamento": "Em andamento", "concluido": "Concluído", "negado": "Negado", "atrasado": "Atrasado"}


def mean(values: list[int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


@dataclass
class ClientFacts:
    client: PortfolioClient
    status_label: str
    outcome: str | None
    situation: str
    status_since: datetime | None
    days_in_status: int | None
    approved_at: datetime | None
    total_days: int | None
    total_days_open: bool
    signature_issued: date | None
    signature_completed: date | None
    signature_days: int | None
    signature_open: bool
    contracts: list[SignatureContract] = field(default_factory=list)


def _status_since(c: PortfolioClient) -> datetime | None:
    hist = c.status_history or []
    if hist:
        return parse_iso_datetime(hist[-1].get("at"))
    return c.created_at


def _first_entry(c: PortfolioClient, cat: Catalog, outcome: str) -> datetime | None:
    for h in c.status_history or []:
        if cat.outcome(c.modality, h.get("status", "")) == outcome:
            return parse_iso_datetime(h.get("at"))
    return None


def client_facts(c: PortfolioClient, cat: Catalog, contracts: list[SignatureContract], sla_days: int, today: date, now: datetime) -> ClientFacts:
    outcome = client_outcome(c, cat)
    since = _status_since(c)
    days_in_status = max(0, round((now - since).total_seconds() / 86400)) if since else None
    if outcome == "approved":
        situation = "concluido"
    elif outcome == "denied":
        situation = "negado"
    elif days_in_status is not None and days_in_status >= sla_days:
        situation = "atrasado"
    else:
        situation = "andamento"

    approved_at = _first_entry(c, cat, "approved")
    if approved_at is None and outcome == "approved" and c.modality == Modality.ONE7 and c.committee_date:
        approved_at = datetime.combine(c.committee_date, datetime.min.time(), tzinfo=timezone.utc)
    total_days, total_open = None, False
    if c.entry_date:
        if approved_at:
            total_days = days_between(c.entry_date, approved_at.date())
        elif outcome is None:
            total_days, total_open = days_between(c.entry_date, today), True

    issued_dates = [k.issued_date for k in contracts if k.issued_date]
    if issued_dates:
        issued = min(issued_dates)
        pending = [k for k in contracts if k.issued_date and not k.signed_date]
        completed = None if pending else max(k.signed_date for k in contracts if k.signed_date)
    else:
        issued, completed = c.contract_issued_date, c.signature_completed_date
    sig_days, sig_open = None, False
    if issued and completed:
        sig_days = days_between(issued, completed)
    elif issued:
        sig_days, sig_open = days_between(issued, today), True

    return ClientFacts(
        client=c, status_label=cat.label(c.modality, c.status), outcome=outcome, situation=situation,
        status_since=since, days_in_status=days_in_status, approved_at=approved_at,
        total_days=total_days, total_days_open=total_open,
        signature_issued=issued, signature_completed=completed, signature_days=sig_days, signature_open=sig_open,
        contracts=contracts,
    )


def contract_days(k: SignatureContract, today: date) -> tuple[int | None, str]:
    """(days, state). state: sem_emissao | aguardando | assinado."""
    if k.issued_date and k.signed_date:
        return days_between(k.issued_date, k.signed_date), "assinado"
    if k.issued_date:
        return days_between(k.issued_date, today), "aguardando"
    return None, "sem_emissao"


def signature_kpis(trackings: list[SignatureTracking], today: date) -> dict:
    """The cards of the Assinaturas area: average signing time overall and per contract, contracts in
    process and signed, follow-ups. Averages count only contracts with both dates."""
    done: dict[str, list[int]] = {"SEC": [], "FIDC": []}
    waiting: list[int] = []
    not_issued = 0
    for t in trackings:
        for k in t.contracts:
            days, state = contract_days(k, today)
            if state == "assinado":
                done[k.kind].append(days)
            elif state == "aguardando":
                waiting.append(days)
            else:
                not_issued += 1
    all_done = done["SEC"] + done["FIDC"]
    return {
        "avg_signature_days": mean(all_done),
        "avg_signature_days_sec": mean(done["SEC"]),
        "avg_signature_days_fidc": mean(done["FIDC"]),
        "signed_basis": len(all_done),
        "in_process": len(waiting),
        "avg_open_days": mean(waiting),
        "oldest_open_days": max(waiting) if waiting else None,
        "signed": len(all_done),
        "not_issued": not_issued,
        "followups": sum(len(t.followups or []) for t in trackings),
        "companies": len(trackings),
    }


def summarize(facts: list[ClientFacts], cat: Catalog, modalities: list[str], trackings: list[SignatureTracking], sla_days: int, today: date) -> dict:
    total = len(facts)
    approved = [f for f in facts if f.outcome == "approved"]
    denied = [f for f in facts if f.outcome == "denied"]
    decided = len(approved) + len(denied)

    by_com: dict[str, dict] = {}
    for f in facts:
        com = f.client.commercial
        key = str(com.id) if com else ""
        row = by_com.setdefault(key, {"id": str(com.id) if com else None, "name": com.name if com else "Sem comercial",
                                      "total": 0, "approved": 0, "denied": 0, "in_progress": 0, "overdue": 0,
                                      "risk_exit": 0, "limit_expired": 0, "_to_approved": []})
        row["total"] += 1
        row["approved"] += f.outcome == "approved"
        row["denied"] += f.outcome == "denied"
        row["in_progress"] += f.outcome is None
        row["overdue"] += f.situation == "atrasado"
        row["risk_exit"] += f.client.risk_exit
        row["limit_expired"] += f.client.limit_expired
        if f.outcome == "approved" and f.total_days is not None:
            row["_to_approved"].append(f.total_days)
    commercials = []
    for row in by_com.values():
        dec = row["approved"] + row["denied"]
        row["approval_rate"] = round(row["approved"] / dec, 3) if dec else None
        row["avg_days_to_approved"] = mean(row.pop("_to_approved"))
        row["share"] = round(row["total"] / total, 3) if total else 0
        commercials.append(row)
    commercials.sort(key=lambda r: (-r["total"], r["name"]))
    named = [r for r in commercials if r["id"]]
    top = named[0] if named else None

    statuses = []
    for m in modalities:
        counts = Counter(f.client.status for f in facts if f.client.modality == m)
        for s in cat.ordered(m):
            statuses.append({"modality": m, "key": s["key"], "label": s["label"], "outcome": s.get("outcome"), "count": counts.get(s["key"], 0)})
        for key, n in counts.items():  # statuses no longer in the catalog still count
            if not cat.has(m, key):
                statuses.append({"modality": m, "key": key, "label": key, "outcome": None, "count": n})

    months = Counter(f.client.entry_date.strftime("%Y-%m") for f in facts if f.client.entry_date)
    by_month = [{"month": k, "count": months[k]} for k in sorted(months)[-12:]]

    open_facts = sorted((f for f in facts if f.outcome is None), key=lambda f: -(f.days_in_status or 0))
    to_approved = [f.total_days for f in approved if f.total_days is not None]
    sig_client = [f.signature_days for f in facts if f.signature_days is not None and not f.signature_open]
    ref = lambda f: {"id": str(f.client.id), "name": f.client.name, "modality": f.client.modality, "status_label": f.status_label,  # noqa: E731
                     "days_in_status": f.days_in_status, "commercial": f.client.commercial.name if f.client.commercial else None}

    return {
        "kpis": {
            "total_clients": total,
            "approved": len(approved),
            "denied": len(denied),
            "in_progress": total - decided,
            "overdue": sum(1 for f in facts if f.situation == "atrasado"),
            "approval_rate": round(len(approved) / decided, 3) if decided else None,
            "avg_days_to_approved": mean(to_approved),
            "avg_days_to_approved_basis": len(to_approved),
            "avg_signature_days_clients": mean(sig_client),
            "avg_signature_days_clients_basis": len(sig_client),
            "risk_exit": sum(1 for f in facts if f.client.risk_exit),
            "limit_expired": sum(1 for f in facts if f.client.limit_expired),
            "commercials": len(named),
            "top_commercial": {"name": top["name"], "total": top["total"]} if top else None,
        },
        "signatures": signature_kpis(trackings, today),
        "by_status": statuses,
        "by_commercial": commercials,
        "by_month": by_month,
        "by_situation": {k: sum(1 for f in facts if f.situation == k) for k in SITUATIONS},
        "stalled": [ref(f) for f in open_facts[:5]],
        "over_sla": [ref(f) for f in open_facts if (f.days_in_status or 0) >= sla_days],
        "risk_exit": [ref(f) for f in facts if f.client.risk_exit],
        "limit_expired": [ref(f) for f in facts if f.client.limit_expired],
        "sla_days": sla_days,
    }


def fact_row(f: ClientFacts) -> dict:
    c = f.client
    return {
        "id": str(c.id),
        "name": c.name,
        "modality": c.modality,
        "commercial": c.commercial.name if c.commercial else None,
        "status": c.status,
        "status_label": f.status_label,
        "situation": f.situation,
        "entry_date": c.entry_date.isoformat() if c.entry_date else None,
        "pre_committee_date": c.pre_committee_date.isoformat() if c.pre_committee_date else None,
        "committee_date": c.committee_date.isoformat() if c.committee_date else None,
        "signature_issued": f.signature_issued.isoformat() if f.signature_issued else None,
        "signature_completed": f.signature_completed.isoformat() if f.signature_completed else None,
        "approved_at": f.approved_at.date().isoformat() if f.approved_at else None,
        "total_days": f.total_days,
        "total_days_open": f.total_days_open,
        "signature_days": f.signature_days,
        "signature_open": f.signature_open,
        "days_in_status": f.days_in_status,
        "risk_exit": c.risk_exit,
        "limit_expired": c.limit_expired,
        "notes": c.notes,
    }


def group_contracts(trackings: list[SignatureTracking]) -> dict:
    out: dict = defaultdict(list)
    for t in trackings:
        if t.client_id:
            out[t.client_id].extend(t.contracts)
    return out
