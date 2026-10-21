# Architecture

```
 Employees' PCs                         Corporate server / private cloud (one site)
 ┌──────────────────────┐   HTTPS   ┌────────────────────────────────────────────────────────┐
 │ Cadastro AI (Tauri)  │──────────▶│ Reverse proxy (TLS)                                    │
 │  React UI            │  JSON +   │   └─▶ api (FastAPI)  ── PostgreSQL (data, audit)       │
 │  native file picker  │  bearer   │         │   │                                          │
 │  no data, no secrets │  session  │         │   └─▶ Redis (job queue, rate limits)         │
 └──────────────────────┘           │         ▼                                              │
                                    │       worker (Celery) ──▶ OCR provider                 │
 Network share  ─── SMB mount ────▶ │       watcher (folder intake)   (Tesseract local /     │
 \\files\cadastro\entrada           │       beat (sweeper, retention)  Azure DI optional)    │
                                    │         │                     ──▶ AI provider (opt.)   │
                                    │         ▼                         (Claude API)         │
                                    │   Encrypted document repository (volume / file server) │
                                    └────────────────────────────────────────────────────────┘
```

| Component | Code | Runs as |
| --- | --- | --- |
| Desktop client | `desktop/src` (React), `desktop/src-tauri` (Rust shell) | Installed app on each PC |
| API | `backend/app/main.py`, `backend/app/api/*` | `uvicorn`, behind TLS |
| Worker | `backend/app/worker.py`, `backend/app/pipeline/*` | `celery worker` |
| Scheduler | `app.worker` beat schedule | `celery beat` (sweeper every 2 min, retention daily) |
| Folder watcher | `backend/app/ingestion/watcher.py` | its own long-running process on the server |
| Repository | `backend/app/storage` | encrypted files under `STORAGE_DIR` |

The desktop app is only a client. It never talks to the database, the storage, the OCR or the AI
provider, and it ships with no credentials. Every permission and business rule is enforced by the
API.

## Intake

All channels call one function, `ingestion.service.ingest()`:

1. Screen the bytes (`ingestion/validation.py`): type sniffed from content and matched to the
   extension; PDF/JPEG/PNG only; size, page and pixel limits; truncated, repaired, encrypted or
   active-content PDFs refused.
2. Hash (SHA-256). The same file twice in one registration is refused; across registrations it
   becomes an integrity finding.
3. Store the original unchanged, encrypted, under a random key.
4. Create the document (`queued`) and a processing job with an idempotency key; audit.
5. Enqueue. If the broker is down the document stays `queued` and the sweeper re-enqueues it.

Channels: `upload` (desktop) and `shared_folder` (watcher). `email` and `whatsapp` are reserved
source names; see [integrations-roadmap.md](integrations-roadmap.md).

## Processing pipeline (`pipeline/orchestrator.py`)

```
claim (atomic: queued|failed → processing; a second worker gets "skipped")
 → load + verify hash → render pages (PyMuPDF) + embedded text layer + file metadata
 → OCR each page (provider) ; PDFs with a text layer use it, and OCR checks it
 → classify (configured keywords)  → extract fields (label/position/pattern, page + box + confidence)
 → learned lessons: drop rule readings the analysts corrected away (pipeline/learning.py)
 → integrity: text layer vs page, editor metadata, incremental saves, ELA, embedded instructions
 → AI (optional): text (+ images if allowed) as quoted data → JSON schema → validated → merged as
   findings and as fields only where rules found nothing; disagreements become findings
 → store fields (human corrections are never overwritten) → validity rules
 → reuse across registrations (hash; visual + identity data) → findings upsert by fingerprint
 → registration analysis: consistency, completeness checklist, priority, status
```

Failures: storage or OCR unavailable → `TransientError` → document back to `queued`, retried with
exponential backoff (4 tries), then `failed`. Unreadable or rejected input → `PermanentError` →
`failed` with a `PROCESSING_FAILED` finding. AI unavailable or invalid output → the document is
still processed; an informational finding records that AI did not run. Workers that die mid-job
are detected by the sweeper (job running > 15 min) and the document is re-queued.

### Learning from reviews (`pipeline/learning.py`)

The AI model is not trained on these documents, and nothing about the reviews is sent to the
provider. What the system learns is local, recomputed from `extracted_fields` and the
disagreement points, per document type and field:

- **Values corrected away.** A rule reading that analysts replaced is not offered again for that
  type and field: it is dropped, so the AI (or the analyst) fills the field. A value with digits
  needs corrections on two documents, and a value an analyst ever kept is never dropped.
- **Whose reading wins.** When rules and AI disagreed (`AI_RULE_DISAGREEMENT`) and the reviewed
  value matched the AI's reading at least twice and more often than the rules', the AI's reading
  becomes the field value. The rules' reading stays in the disagreement point.

Settings → Sistema lists the lessons in force (counts only: the values may be personal data).
Systematic errors still become rule fixes, with a test built from the production layout and
invented data (`tests/test_extraction_layouts.py`).

Findings carry a fingerprint (registration, document, code, field, discriminator). Re-running
the analysis updates machine output but keeps a reviewer's resolution; findings no longer
produced become `superseded`, never deleted.

## Data model (PostgreSQL, `backend/app/models.py`, migration `alembic/versions/0001_initial_schema.py`)

| Table | Holds |
| --- | --- |
| `users`, `user_sessions` | Accounts, roles, server-side sessions (revocable) |
| `registrations` | Code, profile (PF/PJ), subject name, CPF/CNPJ, configurable reference fields, status, checklist, priority and reasons, decision, legal hold |
| `documents` | Original name, storage key, type, size, SHA-256, perceptual hash, source, classification, issuer, status, OCR text and word boxes, metadata, validity, AI status |
| `extracted_fields` | Value, raw text, confidence, source, page, box, validity check, human confirmation/correction with previous value |
| `findings` | Code, category, severity, explanation, evidence (values, page, box), confidence and its basis, recommended action, source, status and resolution |
| `decisions` | Approve / request documents / reject / escalate / reopen with reason and overrides |
| `processing_jobs` | Idempotency key, attempts, timings, provider metrics, cost |
| `ingest_records` | Every file seen by the watcher and what happened to it |
| `watcher_status` | Folder reachability and last scan |
| `app_settings` | Versioned operational configuration |
| `audit_events` | Append-only, hash-chained; UPDATE/DELETE/TRUNCATE blocked by trigger |

Migration `0002_modality_and_portfolio.py` adds `registrations.modality` (normal | one7, existing
rows default to normal) and `registrations.client_id`, and the portfolio tables: `commercials`,
`portfolio_clients`, `signature_trackings`, `signature_contracts`, `data_imports`. See
[portfolio.md](portfolio.md).

## Points to check and notes

Every finding goes through a triage (`pipeline/findings.py`, `is_note`). Points to check are what
asks for action:
- missing or out-of-date documents, and required values that do not match;
- conflicts between documents;
- signs of alteration;
- reuse of files;
- disagreements between the AI's and the rules' reading or classification;
- AI observations rated high, a possible alteration from medium, or an inconsistency the AI is
  sure about.

Everything else becomes a **note** (`status = "note"`). Notes are shown, folded, on the document
page and never count in the queue, the priority, the checklist or the reports. This covers
informative findings, incremental PDF saves, the ELA hint, several documents of the same type, a
classification the AI settled, and AI observations that are low or uncertain. A reviewer's
resolution is never changed by the triage.

## Statuses

Registration: `awaiting_processing` (no documents yet) → `processing` → `awaiting_review` →
`approved` | `pending_documents` | `rejected`; `processing_failed` when a document failed.
`approved`/`rejected` are final until a supervisor reopens. New documents on a
`pending_documents` registration return it to review.

Document: `queued` → `processing` → `processed` | `failed`; `purged` after retention.

Finding: `open` → `accepted` | `escalated` | `overridden`; `superseded` when no longer produced.

## Authorization (enforced in the API)

| Action | Analyst | Supervisor | Admin | Auditor |
| --- | --- | --- | --- | --- |
| Read registrations and documents | ✓ | ✓ | ✓ | ✓ |
| Create, upload, correct fields, request documents, escalate | ✓ | ✓ | ✓ | |
| Accept low/medium findings | ✓ | ✓ | ✓ | |
| Accept high/critical findings, override rules, approve, reject, reopen | | ✓ | ✓ | |
| Full audit history, integrity check | | ✓ | ✓ | ✓ |
| Settings, users, purge | | | ✓ | |

Approve/reject/override roles are configurable in Settings.
