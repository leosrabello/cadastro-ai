"""Findings carry a stable fingerprint so re-running an analysis never discards a reviewer's
resolution: a finding that is produced again keeps its status; one that is no longer
produced is marked superseded (if still open), never deleted."""

import hashlib
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Finding, FindingStatus

SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@dataclass
class FindingDraft:
    code: str
    category: str
    severity: str
    title: str
    explanation: str
    recommended_action: str
    source: str = "rule"
    rule_id: str | None = None
    field_name: str | None = None
    evidence: list[dict] = field(default_factory=list)
    confidence: float | None = None
    confidence_basis: str | None = None
    document_id: uuid.UUID | None = None
    key: str = ""  # extra discriminator for the fingerprint (e.g. the other document's id)

    def fingerprint(self, registration_id: uuid.UUID | None) -> str:
        raw = f"{registration_id}|{self.document_id}|{self.code}|{self.field_name}|{self.key}"
        return hashlib.sha256(raw.encode()).hexdigest()


def evidence(label: str, value, *, document_id=None, field=None, page=None, bbox=None, note=None) -> dict:
    return {
        "label": label,
        "value": None if value is None else str(value),
        "document_id": str(document_id) if document_id else None,
        "field": field,
        "page": page,
        "bbox": bbox,
        "note": note,
    }


def sync(
    db: Session,
    *,
    registration_id: uuid.UUID | None,
    document_id: uuid.UUID | None,
    sources: set[str],
    drafts: list[FindingDraft],
    document_scope: bool,
) -> list[Finding]:
    """Upsert `drafts` and supersede open findings in the same scope that were not produced again.

    document_scope=True: the scope is findings attached to `document_id`.
    document_scope=False: the scope is registration-level findings (document_id IS NULL or
    cross-document ones flagged by the registration analysis) for `registration_id`.
    """
    q = select(Finding).where(Finding.source.in_(sources))
    if document_scope:
        q = q.where(Finding.document_id == document_id, Finding.category != "consistency", Finding.category != "completeness")
    else:
        q = q.where(Finding.registration_id == registration_id, Finding.category.in_(("consistency", "completeness", "integrity_cross")))
    existing = {f.fingerprint: f for f in db.execute(q).scalars()}

    seen: set[str] = set()
    result = []
    for d in drafts:
        fp = d.fingerprint(registration_id if not document_scope else None)
        if fp in seen:
            continue
        seen.add(fp)
        f = existing.get(fp)
        if f is None:
            f = Finding(fingerprint=fp, status=FindingStatus.OPEN)
            db.add(f)
        elif f.status == FindingStatus.SUPERSEDED:
            f.status = FindingStatus.OPEN
        f.registration_id = registration_id
        f.document_id = d.document_id
        f.code = d.code
        f.category = d.category
        f.severity = d.severity
        f.title = d.title
        f.explanation = d.explanation
        f.evidence = d.evidence
        f.field_name = d.field_name
        f.confidence = d.confidence
        f.confidence_basis = d.confidence_basis
        f.recommended_action = d.recommended_action
        f.source = d.source
        f.rule_id = d.rule_id
        result.append(f)

    for fp, f in existing.items():
        if fp not in seen and f.status in FindingStatus.OPEN_STATES:
            f.status = FindingStatus.SUPERSEDED
    db.flush()
    return result
