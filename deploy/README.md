# Deploying CadastroAI on the company server

What employees get: a link, `https://<server>/`. They open it in the browser (Edge or Chrome), sign
in with the account an administrator created, and work. Nothing to install, nothing to configure,
and every update reaches everyone at once.

The Windows desktop app is optional, for those who prefer a separate window: it is offered at
`https://<server>/download/`.

## 1. Server

Linux VM (4 vCPU, 16 GB, SSD) on the corporate network, with Docker Engine and the Compose plugin,
and a DNS name employees' computers resolve (for example `cadastro.fintrust.local`). Open only ports
80 and 443 to the office network or VPN.

## 2. Configure

```bash
git clone <this repository> /opt/cadastro-ai && cd /opt/cadastro-ai/deploy
cp .env.production.example .env
```

Fill in `.env`: `CADASTRO_HOST`, the three secrets (generate them as described in
`docs/configuration.md`), the first administrator, and the HTTPS certificate:

- **Company certificate (recommended):** put `cert.pem` and `key.pem` in `deploy/tls/` and set
  `TLS_DIRECTIVE=tls /etc/caddy/tls/cert.pem /etc/caddy/tls/key.pem`.
- **No company certificate:** keep `tls internal`; then distribute Caddy's root certificate
  (`docker compose -f docker-compose.prod.yml exec caddy cat /data/caddy/pki/authorities/local/root.crt`)
  to the computers' trusted roots through group policy.

Mount the shared folder at `WATCH_FOLDER` (see `docs/deployment.md` for the SMB mount and the
service account's permissions).

## 3. Start

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

```bash
docker compose -f docker-compose.prod.yml exec api python scripts/apply_checklist_2026.py
```

Check `https://<CADASTRO_HOST>/api/health`, sign in with the bootstrap administrator from the desktop
app, create the employees' accounts, then remove `BOOTSTRAP_ADMIN_*` from `.env`.

## 4. Optional: publish the desktop installer

The Windows installers are built by GitHub Actions (`.github/workflows/desktop-windows.yml`) on every
tag `desktop-vX.Y.Z`, with the repository variable `CADASTRO_API_URL` set to
`https://<CADASTRO_HOST>` so new installs point at this server. Download the release files and copy
them into `deploy/download/` with these names:

```
deploy/download/CadastroAI-setup.exe
deploy/download/CadastroAI.msi
```

No restart is needed. IT can also push the `.msi` silently through Intune/SCCM/GPO:
`msiexec /i CadastroAI.msi /qn`.

## 5. Updates

Backend: `git pull && docker compose -f docker-compose.prod.yml up -d --build` (back up first,
`scripts/backup.sh`). Desktop: tag a new version, replace the two files in `deploy/download/`;
running the new installer upgrades in place.
