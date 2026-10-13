# Cadastro AI

Desktop application for the registration (cadastro) team: it receives customer documents, reads
them, checks validity and consistency with deterministic rules, flags possible integrity problems,
and puts every case in front of a person with the evidence. People decide; the system records who
decided what, when and why.

- **Desktop client** (`desktop/`): Tauri 2 + React + TypeScript. Holds no data and no secrets.
- **Central backend** (`backend/`): FastAPI, PostgreSQL, Celery/Redis workers, a shared-folder
  watcher service, an encrypted document repository, replaceable OCR and AI providers.

All employees work on the same registrations, documents, analyses and history on the server.

## What works today

| Area | State |
| --- | --- |
| Registrations: create, search, filter, sort, paginate, detail | Working |
| FinTrust 2026 checklist as the standard company profile (two stages, year-relative financials, signatures, required information) | Working |
| Financial documents read: revenue tables, debt by institution, balance sheet lines, IRPF assets, customer concentration | Working, rule-based on text |
| Analysis report rendered as a PNG for the credit committee | Working (desktop client export) |
| Upload: native file picker, drag and drop, several files, per-file progress, retry, reasons for refusal | Working |
| Shared-folder intake: completion detection, temp-file filtering, hash de-duplication, permission and outage handling, association by code/CPF, inbox for manual association | Working (separate service) |
| OCR | Working with Tesseract (self-hosted). Azure Document Intelligence adapter written and unit-tested, not run against a live resource |
| Classification, field extraction with page/region and confidence, normalization, CPF/CNPJ check digits | Working |
| Validity rules per document type (expiry, maximum age, required values, contradictory dates) | Working, configurable |
| Cross-document consistency, completeness checklist, rule-based review priority | Working, configurable |
| Integrity signals: text layer vs visible page, editor metadata, incremental saves, ELA, file and document reuse across registrations, embedded instructions | Working |
| AI-assisted analysis (Claude, structured and schema-validated output) | Implemented and tested with recorded/fake responses. Needs `ANTHROPIC_API_KEY` to run for real; off by default |
| Review: field confirm/correct, finding accept/escalate/override, approve/request documents/reject/escalate/reopen with role checks | Working |
| Append-only, hash-chained audit trail with integrity check | Working |
| Roles, sessions, immediate revocation, rate limiting, retention and purge, legal hold, data-subject export | Working |
| Windows installer | Build pipeline provided (GitHub Actions, Windows runner). Not produced from this Mac; the macOS bundle builds here |

Backend: 83 automated tests against real PostgreSQL, Redis and Tesseract. See
[docs/evaluation.md](docs/evaluation.md) for measured results on synthetic documents and what they
do and do not mean.

## Quick start (development)

Requirements: Docker, Node.js 22+, Rust (for the desktop shell).

```bash
cp .env.example .env
```

Fill in `POSTGRES_PASSWORD`, `JWT_SECRET`, `STORAGE_ENCRYPTION_KEY` and the bootstrap admin (the
file explains how to generate each). Then:

```bash
docker compose up -d --build
```

```bash
docker compose exec api python scripts/seed_demo.py
```

The seed creates synthetic registrations and three demo users and prints their password once.

Desktop client in a browser window (fastest for development):

```bash
cd desktop && npm install && npm run dev
```

Desktop client as the native app:

```bash
cd desktop && npm run tauri dev
```

Tests and evaluation:

```bash
docker compose run --rm api pytest
```

```bash
docker compose run --rm api python scripts/evaluate.py --n 60
```

## Documentation

| Document | Contents |
| --- | --- |
| [Architecture](docs/architecture.md) | Components, data model, pipeline, statuses, intake abstraction |
| [Configuration and credentials](docs/configuration.md) | Environment variables, Azure and Anthropic credentials, operational settings |
| [OCR and AI providers](docs/providers.md) | Evaluation of providers and why Tesseract + optional Claude |
| [Deployment](docs/deployment.md) | Server, TLS, where the folder watcher runs and its permissions, backups, updates |
| [Desktop app and Windows installer](docs/desktop.md) | Build, signing, distribution, updates |
| [Security, privacy and LGPD](docs/security-privacy-lgpd.md) | Controls, legal basis, retention, data-subject rights, vendors, prompt injection |
| [Evaluation](docs/evaluation.md) | What is measured, current synthetic results, building a real labelled set |
| [Costs](docs/costs.md) | Fixed and variable costs at different volumes, with assumptions |
| [Design](docs/design.md) | How the installed Taste Skill shaped the interface |
| [Integrations roadmap](docs/integrations-roadmap.md) | Outlook and WhatsApp intake |
| [Known limitations](docs/limitations.md) | What is not done, not verified, or deliberately out of scope |
| [Assumptions](docs/assumptions.md) | Decisions taken where the brief was silent |
