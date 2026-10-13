"""The single entry point for every intake channel.

Desktop upload and the shared-folder watcher call ingest(); future channels (Outlook,
WhatsApp) will call it the same way with their own `source` and `source_ref`, so the
processing pipeline never needs to know where a document came from.
"""

import hashlib
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.ingestion.validation import screen
from app.models import DocStatus, Document, ProcessingJob, RegStatus, Registration, User
from app.storage import get_store

SOURCES = {"upload", "shared_folder", "email", "whatsapp"}


class DuplicateDocument(Exception):
    def __init__(self, existing: Document):
        super().__init__("duplicate")
        self.existing = existing


class RegistrationClosed(Exception):
    pass


@dataclass
class IngestResult:
    document: Document
    job: ProcessingJob


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def job_key(document_id: uuid.UUID, sha: str, attempt_round: int) -> str:
    return f"{document_id}:{sha[:16]}:{get_settings().pipeline_version}:{attempt_round}"


def ingest(
    db: Session,
    *,
    data: bytes,
    filename: str,
    source: str,
    source_ref: str | None = None,
    registration: Registration | None = None,
    actor: User | None = None,
    ip: str | None = None,
) -> IngestResult:
    """Screen, store and queue one file. Raises RejectedFile, DuplicateDocument, RegistrationClosed."""
    assert source in SOURCES
    if registration is not None and registration.status in RegStatus.FINAL:
        raise RegistrationClosed()

    screened = screen(data, filename)
    sha = sha256_hex(data)

    if registration is not None:
        existing = db.execute(
            select(Document).where(
                Document.registration_id == registration.id,
                Document.sha256 == sha,
                Document.status != DocStatus.PURGED,
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise DuplicateDocument(existing)

    key = get_store().put(data)
    doc = Document(
        id=uuid.uuid4(),
        registration_id=registration.id if registration else None,
        original_filename=screened.safe_name,
        storage_key=key,
        mime_type=screened.mime_type,
        size_bytes=len(data),
        sha256=sha,
        source=source,
        source_ref=source_ref,
        uploaded_by_id=actor.id if actor else None,
        page_count=screened.page_count,
        status=DocStatus.QUEUED,
    )
    db.add(doc)
    db.flush()
    job = ProcessingJob(document_id=doc.id, idempotency_key=job_key(doc.id, sha, 1), requested_by_id=actor.id if actor else None)
    db.add(job)

    if registration is not None and registration.status not in (RegStatus.PROCESSING,):
        registration.status = RegStatus.PROCESSING

    audit.record(
        db,
        "document.ingested",
        actor=actor,
        actor_label=None if actor else f"ingest:{source}",
        entity_type="document",
        entity_id=doc.id,
        registration_id=doc.registration_id,
        details={
            "filename": screened.safe_name,
            "source": source,
            "source_ref": source_ref,
            "sha256": sha,
            "size_bytes": len(data),
            "mime_type": screened.mime_type,
        },
        ip=ip,
    )
    db.flush()
    return IngestResult(document=doc, job=job)
