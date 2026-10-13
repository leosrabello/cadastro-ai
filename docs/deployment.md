# Backend deployment

Target: one Linux server (VM) on the corporate network or in a private cloud VPC, reachable by
employees' PCs over HTTPS only. The compose file in the repository is for development; production
uses the same images with the changes below.

## Server

- 4 vCPU, 8–16 GB RAM, SSD. OCR is CPU-bound: each worker process handles one document at a time
  (≈0.2–2 s per page depending on the scan). Scale with `--concurrency` and more worker replicas.
- Docker Engine + Compose plugin, or the equivalent services on the company's container platform.
- PostgreSQL 15+: preferably the company's managed instance with encrypted storage, point-in-time
  recovery and a dedicated database/user. Remove the `db` service from compose and set
  `DATABASE_URL`.
- Redis 7 with persistence (only queue and rate-limit state; no personal data).

## TLS and network

- Put a reverse proxy (nginx, Caddy, or the corporate load balancer) in front of `api:8000` with a
  certificate from the corporate CA; redirect HTTP to HTTPS; allow only the internal network or VPN.
- Do not publish PostgreSQL, Redis or the worker to the network.
- Set `CORS_ORIGINS` to the Tauri origins only (`tauri://localhost,http://tauri.localhost,https://tauri.localhost`).
- The desktop app warns when the configured server address is plain HTTP and not on the local
  machine.

## Where the folder watcher runs, and its permissions

The watcher is a **server-side service** (`python -m app.ingestion.watcher`, the `watcher` service
in compose). It must not run inside the desktop app: it has to keep working when every PC is
switched off, and only one instance may consume the folder (it takes a PostgreSQL advisory lock,
so a second copy stands by).

Mount the share on the server host and pass it into the container under one of the
`WATCH_ALLOWED_ROOTS`:

```bash
sudo mount -t cifs //fileserver/cadastro /srv/cadastro-share -o credentials=/etc/cadastro/smb.cred,uid=10001,gid=10001,file_mode=0660,dir_mode=0770,vers=3.0,seal
```

Then mount `/srv/cadastro-share:/watch` for the watcher service and set the folder in Settings
(for example `/watch/entrada`).

Service account on the file server (least privilege):

| Path | Permission | Why |
| --- | --- | --- |
| `entrada\` | Read, List | read new files |
| `entrada\` | Delete (or Modify) | move taken files out (`after_ingest: move`). With `leave`, read-only is enough |
| `entrada\_processados`, `_falhas`, `_duplicados` | Create, Write | receive moved files and `.motivo.txt` notes |

`seal` (SMB 3 encryption) protects documents on the wire between file server and API server.

Behaviour under failure: the folder unreachable (share down, VPN drop) is reported on the dashboard
and retried with exponential backoff; files being copied are taken only after they stop changing
and their trailer is complete; locked files are retried; unreadable files are recorded once and not
retried until they change; identical content is never ingested twice.

## First start

```bash
docker compose up -d --build
```

The API container runs `alembic upgrade head` before starting. Set `BOOTSTRAP_ADMIN_*` for the
first start, sign in, create named accounts, then remove those variables.

## Backups and recovery

`scripts/backup.sh` writes an encrypted archive with a `pg_dump` and the document repository. Run
it nightly from cron on the server and copy the archives to separate storage (another site or an
immutable bucket):

```bash
BACKUP_DIR=/mnt/backup BACKUP_PASSPHRASE_FILE=/etc/cadastro/backup.pass /opt/cadastro-ai/scripts/backup.sh
```

Keep `STORAGE_ENCRYPTION_KEY`, `JWT_SECRET` and the backup passphrase in the corporate vault, apart
from the backups.

Restore, on a stopped stack:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/etc/cadastro/backup.pass -in cadastro-YYYYMMDD-HHMMSS.tar.enc | tar -x
```

```bash
docker compose exec -T db pg_restore -U cadastro -d cadastro --clean --if-exists < cadastro.dump
```

Then unpack `documents.tgz` into the documents volume and start the stack. After a restore, run
*Conferir integridade* in Histórico to verify the audit chain. Test a restore at least quarterly.

## Updates

1. Back up.
2. `git pull` the tagged release; `docker compose build`.
3. `docker compose up -d`: the API applies migrations on start. Workers drain their current job
   (`acks_late`) and the sweeper re-queues anything interrupted.
4. Desktop: publish the new installer (docs/desktop.md). The API is backwards compatible within a
   major version, so PCs can update over a few days.

## Monitoring

- `GET /api/health` (no auth): database, queue, storage.
- Dashboard shows watcher reachability, documents in flight and failures.
- Container logs: failed jobs are logged with the document id; every failure is also a finding on
  the document.
