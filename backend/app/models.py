import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class Role:
    ANALYST = "analyst"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    AUDITOR = "auditor"
    ALL = (ANALYST, SUPERVISOR, ADMIN, AUDITOR)


class RegStatus:
    AWAITING_PROCESSING = "awaiting_processing"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    PENDING_DOCUMENTS = "pending_documents"
    REJECTED = "rejected"
    PROCESSING_FAILED = "processing_failed"
    ALL = (
        AWAITING_PROCESSING,
        PROCESSING,
        AWAITING_REVIEW,
        APPROVED,
        PENDING_DOCUMENTS,
        REJECTED,
        PROCESSING_FAILED,
    )
    FINAL = (APPROVED, REJECTED)
    # closed to new documents and edits; an approved registration still receives formalização documents
    CLOSED = (REJECTED,)


class DocStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    PURGED = "purged"


class FindingStatus:
    OPEN = "open"
    ACCEPTED = "accepted"  # reviewer judged it legitimate / not a problem
    ESCALATED = "escalated"
    OVERRIDDEN = "overridden"  # rule result overridden with documented reason
    SUPERSEDED = "superseded"  # no longer produced by the latest analysis
    OPEN_STATES = (OPEN, ESCALATED)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(String(64))


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32))  # requirement profile key, e.g. "PF", "PJ"
    subject_name: Mapped[str] = mapped_column(String(300))
    tax_id: Mapped[str | None] = mapped_column(String(32), index=True)  # digits only
    reference_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default=RegStatus.AWAITING_PROCESSING, index=True)
    priority_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    priority_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    checklist: Mapped[dict] = mapped_column(JSONB, default=dict)
    ready_for_decision: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    last_analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    documents: Mapped[list["Document"]] = relationship(back_populates="registration", foreign_keys="Document.registration_id")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = uuid_pk()
    registration_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registrations.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str | None] = mapped_column(String(128))
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    phash: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(32))  # upload | shared_folder | (future) email | whatsapp
    source_ref: Mapped[str | None] = mapped_column(Text)
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)

    doc_type: Mapped[str | None] = mapped_column(String(64))
    doc_type_confidence: Mapped[float | None] = mapped_column(Float)
    doc_type_source: Mapped[str | None] = mapped_column(String(16))  # rules | ai | human
    issuer: Mapped[str | None] = mapped_column(String(200))

    status: Mapped[str] = mapped_column(String(16), default=DocStatus.QUEUED, index=True)
    processing_error: Mapped[str | None] = mapped_column(Text)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_status: Mapped[str | None] = mapped_column(String(16))  # skipped | done | failed
    ai_error: Mapped[str | None] = mapped_column(Text)

    ocr_provider: Mapped[str | None] = mapped_column(String(32))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_pages: Mapped[list | None] = mapped_column(JSONB)  # per page: size, words with boxes
    file_metadata: Mapped[dict | None] = mapped_column(JSONB)
    validity: Mapped[dict | None] = mapped_column(JSONB)
    classification: Mapped[dict | None] = mapped_column(JSONB)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    suggested_registration_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registrations.id"))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    registration: Mapped[Registration | None] = relationship(
        back_populates="documents", foreign_keys=[registration_id]
    )
    fields: Mapped[list["ExtractedField"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="ExtractedField.name"
    )


class ExtractedField(Base):
    __tablename__ = "extracted_fields"
    __table_args__ = (UniqueConstraint("document_id", "name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    value: Mapped[str | None] = mapped_column(Text)  # normalized
    raw_value: Mapped[str | None] = mapped_column(Text)  # as read
    confidence: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(16))  # pdf_text | ocr | ai | human
    page: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list | None] = mapped_column(JSONB)  # [x0, y0, x1, y1] as page fractions
    valid: Mapped[bool | None] = mapped_column(Boolean)
    validation_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="extracted")  # extracted | confirmed | corrected
    previous_value: Mapped[str | None] = mapped_column(Text)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="fields")


class Finding(Base):
    __tablename__ = "findings"
    __table_args__ = (Index("ix_findings_reg_status", "registration_id", "status"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    registration_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registrations.id"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(64))
    category: Mapped[str] = mapped_column(String(32))  # validity | consistency | completeness | integrity | quality | processing | ai
    severity: Mapped[str] = mapped_column(String(16))  # info | low | medium | high | critical
    title: Mapped[str] = mapped_column(String(300))
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    field_name: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    confidence_basis: Mapped[str | None] = mapped_column(String(200))
    recommended_action: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))  # rule | forensics | ai
    rule_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=FindingStatus.OPEN, index=True)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    resolved_by: Mapped[User | None] = relationship()


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | running | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)  # provider, pages, tokens, cost estimate


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = uuid_pk()
    registration_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("registrations.id"), index=True)
    action: Mapped[str] = mapped_column(String(32))  # approve | request_documents | reject | escalate | reopen
    reason: Mapped[str | None] = mapped_column(Text)
    requested_items: Mapped[list] = mapped_column(JSONB, default=list)
    overrides: Mapped[list] = mapped_column(JSONB, default=list)
    decided_by_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    decided_by: Mapped[User] = relationship()


class IngestRecord(Base):
    __tablename__ = "ingest_records"
    __table_args__ = (UniqueConstraint("source", "source_ref", "sha256"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(String(32))
    source_ref: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(16))  # ingested | duplicate | rejected | failed
    detail: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class WatcherStatus(Base):
    __tablename__ = "watcher_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    folder: Mapped[str | None] = mapped_column(Text)
    reachable: Mapped[bool] = mapped_column(Boolean, default=False)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    pending_files: Mapped[int] = mapped_column(Integer, default=0)
    ingested_total: Mapped[int] = mapped_column(Integer, default=0)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    """Append-only, hash-chained. UPDATE and DELETE are blocked by a database trigger."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    actor_label: Mapped[str] = mapped_column(String(254))
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    registration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class Counter(Base):
    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer, default=0)


__all__ = [
    "AppSetting",
    "AuditEvent",
    "Counter",
    "Decision",
    "DocStatus",
    "Document",
    "ExtractedField",
    "Finding",
    "FindingStatus",
    "IngestRecord",
    "ProcessingJob",
    "RegStatus",
    "Registration",
    "Role",
    "User",
    "UserSession",
    "WatcherStatus",
]
