"""Celery worker: document processing with retries, a sweeper that recovers lost or stuck
jobs, and the daily retention run."""

import logging
import uuid
from datetime import timedelta

from celery import Celery
from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import DocStatus, Document, ProcessingJob, utcnow

log = logging.getLogger(__name__)

celery = Celery("cadastro_ai", broker=get_settings().redis_url, backend=None)
celery.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_default_queue="documents",
    broker_connection_retry_on_startup=True,
    timezone="America/Sao_Paulo",
    beat_schedule={
        "sweep-stale": {"task": "app.worker.sweep_stale", "schedule": 120.0},
        "retention": {"task": "app.worker.apply_retention", "schedule": 24 * 3600.0},
    },
)

MAX_RETRIES = 4
_inline_runner = None  # tests run jobs synchronously by setting this


def execute(document_id: uuid.UUID, can_retry: bool) -> str:
    """Run the pipeline once. Returns 'done', 'skipped', 'retry' or 'failed'."""
    from app.pipeline import orchestrator as orch

    with session_scope() as db:
        try:
            result = orch.process_document(db, document_id)
            return "skipped" if result.get("skipped") else "done"
        except orch.TransientError as exc:
            db.rollback()
            if can_retry:
                orch.release_for_retry(db, document_id, f"{exc} (nova tentativa agendada)")
                return "retry"
            orch.mark_failed(db, document_id, f"{exc} — tentativas esgotadas")
        except orch.PermanentError as exc:
            db.rollback()
            orch.mark_failed(db, document_id, str(exc))
        except Exception as exc:  # noqa: BLE001 — record any unexpected failure on the document
            log.exception("unexpected pipeline error for %s", document_id)
            db.rollback()
            orch.mark_failed(db, document_id, f"erro inesperado: {type(exc).__name__}: {exc}")
    return "failed"


@celery.task(bind=True, max_retries=MAX_RETRIES, name="app.worker.process_document")
def process_document(self, document_id: str) -> str:
    outcome = execute(uuid.UUID(document_id), can_retry=self.request.retries < MAX_RETRIES)
    if outcome == "retry":
        raise self.retry(countdown=30 * (2 ** self.request.retries))
    return outcome


def enqueue(document_id: uuid.UUID) -> bool:
    """Best effort. If the broker is down the document stays queued and the sweeper picks it up."""
    if _inline_runner is not None:
        _inline_runner(document_id)
        return True
    try:
        process_document.delay(str(document_id))
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("could not enqueue %s: %s", document_id, exc)
        return False


@celery.task(name="app.worker.sweep_stale")
def sweep_stale() -> dict:
    now = utcnow()
    requeued = []
    with session_scope() as db:
        stuck = db.execute(
            select(ProcessingJob).where(ProcessingJob.status == "running", ProcessingJob.started_at < now - timedelta(minutes=15))
        ).scalars().all()
        for job in stuck:
            doc = db.get(Document, job.document_id)
            if doc and doc.status == DocStatus.PROCESSING:
                doc.status = DocStatus.QUEUED
                job.status, job.error = "queued", "worker interrompido; reenfileirado"
        queued = db.execute(
            select(Document.id).where(Document.status == DocStatus.QUEUED, Document.received_at < now - timedelta(minutes=2))
        ).scalars().all()
        requeued = list(queued)
    for doc_id in requeued:
        enqueue(doc_id)
    return {"requeued": len(requeued)}


@celery.task(name="app.worker.apply_retention")
def apply_retention() -> dict:
    from app.retention import run

    with session_scope() as db:
        return run(db)
