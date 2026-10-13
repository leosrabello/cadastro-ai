"""Append-only, hash-chained audit trail.

Each event stores sha256(prev_hash + canonical JSON of the event). A database trigger
(see the initial migration) rejects UPDATE and DELETE on audit_events, and an advisory
lock serialises writers so the chain never forks.
"""

import hashlib
import json
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent, User, utcnow

GENESIS = "0" * 64
_LOCK_KEY = 74_221_001


def _canonical(event: AuditEvent) -> str:
    return json.dumps(
        {
            "at": event.at.isoformat(),
            "actor_id": str(event.actor_id) if event.actor_id else None,
            "actor_label": event.actor_label,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "registration_id": str(event.registration_id) if event.registration_id else None,
            "details": event.details,
            "ip": event.ip,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )


def compute_hash(prev_hash: str, event: AuditEvent) -> str:
    return hashlib.sha256((prev_hash + _canonical(event)).encode()).hexdigest()


def record(
    db: Session,
    action: str,
    *,
    actor: User | None = None,
    actor_label: str | None = None,
    entity_type: str,
    entity_id: Any = None,
    registration_id: uuid.UUID | None = None,
    details: dict | None = None,
    ip: str | None = None,
) -> AuditEvent:
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    prev = db.execute(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)).scalar()
    event = AuditEvent(
        at=utcnow(),
        actor_id=actor.id if actor else None,
        actor_label=actor_label or (actor.email if actor else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        registration_id=registration_id,
        details=json.loads(json.dumps(details or {}, default=str)),
        ip=ip,
        prev_hash=prev or GENESIS,
    )
    event.hash = compute_hash(event.prev_hash, event)
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session) -> dict:
    prev = GENESIS
    checked = 0
    for event in db.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars():
        if event.prev_hash != prev or compute_hash(prev, event) != event.hash:
            return {"valid": False, "checked": checked, "broken_at": event.id}
        prev = event.hash
        checked += 1
    return {"valid": True, "checked": checked, "broken_at": None}
