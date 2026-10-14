"""Portfolio of client folders (Normal and One7), their commercials and the contracts awaiting signature.

The registration (document analysis) side links to a portfolio client through Registration.client_id;
both carry the same modality.
"""

import re
import unicodedata
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Commercial, Modality, PortfolioClient, SignatureContract, SignatureTracking, utcnow
from app.settings_store import get_setting

CONTRACT_KINDS = ("SEC", "FIDC")
FOLLOWUP_KINDS = ("documentacao", "assinatura")
ONE7_RESULTS = {"em_analise": "Em análise", "aprovado": "Aprovado", "negado": "Negado", "falta_documento": "Falta documento"}
ONE7_ANALYSIS_TYPES = {"tombamento": "Tombamento", "analise_completa": "Análise completa"}


def clean_name(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def name_key(text: str) -> str:
    """Identity for names typed by people: accents, case, punctuation and spacing do not matter."""
    folded = unicodedata.normalize("NFKD", clean_name(text)).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", " ", folded).strip()


class Catalog:
    """Statuses per modality, from the client_statuses setting."""

    def __init__(self, raw: dict):
        self.raw = raw
        self.by_modality = {m: {s["key"]: s for s in raw.get(m, [])} for m in Modality.ALL}

    @classmethod
    def load(cls, db: Session) -> "Catalog":
        return cls(get_setting(db, "client_statuses"))

    def has(self, modality: str, key: str) -> bool:
        return key in self.by_modality.get(modality, {})

    def label(self, modality: str, key: str) -> str:
        return self.by_modality.get(modality, {}).get(key, {}).get("label", key)

    def outcome(self, modality: str, key: str) -> str | None:
        return self.by_modality.get(modality, {}).get(key, {}).get("outcome")

    def opens_signature(self, modality: str, key: str) -> bool:
        return bool(self.by_modality.get(modality, {}).get(key, {}).get("opens_signature"))

    def ordered(self, modality: str) -> list[dict]:
        return list(self.raw.get(modality, []))


def client_outcome(c: PortfolioClient, cat: Catalog) -> str | None:
    """approved / denied / None. One7 folders also close on the One7 committee result."""
    out = cat.outcome(c.modality, c.status)
    if out:
        return out
    if c.modality == Modality.ONE7:
        result = (c.extra or {}).get("resultado_comite")
        if result == "aprovado":
            return "approved"
        if result == "negado":
            return "denied"
    return None


def commercial_index(db: Session) -> dict[str, Commercial]:
    """Every name key that identifies a commercial, its own and those merged into it."""
    index: dict[str, Commercial] = {}
    for com in db.execute(select(Commercial)).scalars():
        index[com.name_key] = com
        for alias in com.aliases or []:
            index.setdefault(alias, com)
    return index


def get_or_create_commercial(db: Session, name: str | None) -> Commercial | None:
    name = clean_name(name or "")
    if not name:
        return None
    key = name_key(name)
    found = commercial_index(db).get(key)
    if found:
        return found
    com = Commercial(name=name, name_key=key)
    db.add(com)
    db.flush()
    return com


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def iso_date(d: date | None) -> str | None:
    return d.isoformat() if d else None


def change_status(db: Session, c: PortfolioClient, new_status: str, cat: Catalog, at: datetime | None = None) -> bool:
    """Moves a client to a new status, keeps the status history and opens the signature tracking
    when the status calls for it. Returns False when nothing changed."""
    if c.status == new_status:
        return False
    c.status = new_status
    c.status_history = [*(c.status_history or []), {"status": new_status, "at": (at or utcnow()).isoformat()}]
    if cat.opens_signature(c.modality, new_status):
        ensure_signature_tracking(db, c)
    return True


def ensure_signature_tracking(db: Session, c: PortfolioClient) -> SignatureTracking:
    existing = db.execute(select(SignatureTracking).where(SignatureTracking.client_id == c.id)).scalars().first()
    if existing:
        return existing
    t = SignatureTracking(client_id=c.id, modality=c.modality, company_name=c.name, commercial_id=c.commercial_id, auto_created=True)
    t.contracts = [SignatureContract(kind=k) for k in CONTRACT_KINDS]
    db.add(t)
    db.flush()
    return t


def commercial_brief(com: Commercial | None) -> dict | None:
    return {"id": str(com.id), "name": com.name} if com else None


def days_between(a: date | None, b: date | None) -> int | None:
    if a is None or b is None:
        return None
    return (b - a).days
