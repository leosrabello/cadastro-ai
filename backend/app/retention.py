"""Retention: purge original files and personal data of registrations past their retention
period. Approved registrations are never purged automatically (the end of the customer
relationship is known only to the core system). Registrations under legal hold are skipped.
Metadata needed to prove what happened (hashes, decisions, audit trail) is kept."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.models import DocStatus, Document, RegStatus, Registration, utcnow
from app.settings_store import get_setting
from app.storage import StorageUnavailable, get_store


def purge_registration(db: Session, reg: Registration, reason: str, actor=None) -> int:
    store = get_store()
    purged = 0
    for doc in db.execute(select(Document).where(Document.registration_id == reg.id, Document.status != DocStatus.PURGED)).scalars():
        if doc.storage_key:
            try:
                store.delete(doc.storage_key)
            except StorageUnavailable:
                continue
        doc.storage_key = None
        doc.ocr_text = None
        doc.ocr_pages = None
        doc.phash = None
        for f in list(doc.fields):
            doc.fields.remove(f)
        doc.status = DocStatus.PURGED
        doc.purged_at = utcnow()
        purged += 1
    reg.subject_name = "[expurgado]"
    reg.tax_id = None
    reg.reference_fields = {}
    reg.anonymized_at = utcnow()
    audit.record(db, "registration.purged", actor=actor, actor_label=None if actor else "retention", entity_type="registration",
                 entity_id=reg.id, registration_id=reg.id, details={"reason": reason, "documents": purged})
    return purged


def run(db: Session) -> dict:
    policy = get_setting(db, "retention")
    now = utcnow()
    done = []
    rules = [
        (RegStatus.REJECTED, policy.get("rejected_days"), Registration.decided_at),
        (RegStatus.PENDING_DOCUMENTS, policy.get("abandoned_pending_days"), Registration.updated_at),
    ]
    for status, days, column in rules:
        if days is None:
            continue
        regs = db.execute(
            select(Registration).where(
                Registration.status == status,
                Registration.legal_hold.is_(False),
                Registration.anonymized_at.is_(None),
                column < now - timedelta(days=int(days)),
            )
        ).scalars().all()
        for reg in regs:
            purge_registration(db, reg, f"retenção: {status} há mais de {days} dias")
            done.append(reg.code)
    return {"purged": done}
