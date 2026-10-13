# Configuration and credentials

Two kinds of configuration, kept apart on purpose:

- **Secrets and process settings**: environment variables on the server (`.env`, or the secret
  store of the deployment platform). Never shown in the app, never in the desktop build.
- **Operational rules**: stored in the database, edited by administrators in *Configurações*,
  versioned, and every change recorded in the audit trail with before and after values.

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `APP_ENV` | | `production` disables the interactive API docs and the demo seed |
| `DATABASE_URL` / `POSTGRES_PASSWORD` | ✓ | PostgreSQL connection |
| `REDIS_URL` | | Queue and rate limiting (default `redis://redis:6379/0`) |
| `JWT_SECRET` | ✓ | Signs session tokens. 32+ random characters. Rotating it signs everyone out |
| `SESSION_HOURS` | | Session length (default 10) |
| `STORAGE_DIR` | | Where encrypted originals are written |
| `STORAGE_ENCRYPTION_KEY` | ✓ | Fernet key for documents at rest. **Losing it makes every document unreadable** |
| `MAX_UPLOAD_MB`, `MAX_PAGES` | | Intake limits (25 MB, 15 pages) |
| `OCR_PROVIDER` | | `tesseract` (default) or `azure` |
| `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` | if azure | Azure AI Document Intelligence resource |
| `AI_PROVIDER` | | `none` (default) or `anthropic` |
| `ANTHROPIC_API_KEY` | if anthropic | Claude API key |
| `AI_MODEL` | | Default `claude-opus-5-5` |
| `AI_ALLOW_IMAGES` | | Server-side ceiling for sending page images to the AI (default `false`) |
| `WATCH_ALLOWED_ROOTS` | | Folders the watcher may be pointed at from Settings |
| `CORS_ORIGINS` | | Origins allowed to call the API (the Tauri app origins) |
| `BOOTSTRAP_ADMIN_EMAIL`, `BOOTSTRAP_ADMIN_PASSWORD` | first run | Creates the first administrator when none exists. Remove afterwards |

Generate secrets:

```bash
openssl rand -hex 32
```

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Credentials for external services

### Azure AI Document Intelligence (optional OCR)

1. In the company's Azure subscription create a *Document Intelligence* resource in **Brazil
   South** (keeps processing in Brazil), pricing tier S0.
2. Copy the endpoint (`https://<name>.cognitiveservices.azure.com`) and one key.
3. Set `OCR_PROVIDER=azure`, `AZURE_DI_ENDPOINT`, `AZURE_DI_KEY` on the server and restart the
   worker.
4. Before production: DPO approval and Microsoft's data-processing terms on file (see
   [security-privacy-lgpd.md](security-privacy-lgpd.md)). Prefer a managed identity or key vault
   reference over a static key where the platform supports it.

The adapter (`pipeline/ocr/azure.py`) uses the `prebuilt-read` model, REST API `2024-11-30`. It is
covered by tests with recorded response shapes but has **not** been run against a live resource
from this repository.

### Anthropic Claude (optional AI-assisted analysis)

1. Create an organization/workspace for this application in the Claude Console and an API key
   restricted to it. Set a monthly spend limit for the workspace.
2. Set `AI_PROVIDER=anthropic`, `ANTHROPIC_API_KEY`, and optionally `AI_MODEL`, then restart the
   worker.
3. An administrator turns on *Analisar cada documento também com IA* in Settings. The switch
   refuses to turn on while the server has no provider configured.
4. Page images are sent only if `AI_ALLOW_IMAGES=true` **and** the administrator also enables
   *Mandar também as imagens das páginas*.
5. Before production: confirm the commercial terms (no training on API data), the data-retention
   arrangement and the processing location with Anthropic, and record them in the vendor register.

Never put either key in the desktop app, in `desktop/.env`, or in a repository.

## Operational settings (Configurações)

| Tab | Setting key | What it controls |
| --- | --- | --- |
| Processamento | `processing` | AI on/off, images to AI, text-layer check, auto-association by extracted CPF/CNPJ |
| Pasta monitorada | `watcher` | Folder path (inside `WATCH_ALLOWED_ROOTS`), polling interval, stability window, move/leave, association pattern, ignore patterns |
| Documentos e validade | `document_types` | Per type: label, keywords, fields, expiry rule, tolerance, maximum age, required values |
| Exigências | `requirement_profiles`, `approval` | Mandatory documents per profile; which roles approve, reject, override |
| Prioridade | `priority_rules` | Points per explicit rule |
| Retenção | `retention` | Purge periods for rejected and abandoned registrations |
| Usuários | (users table) | Accounts, roles, revocation |

Defaults are in `backend/app/config_defaults.py`; they are assumptions to be confirmed by
compliance (see [assumptions.md](assumptions.md)).
