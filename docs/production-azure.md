# Production: Azure (installed 2026-10-14)

| Item | Value |
| --- | --- |
| Address | https://cadastro.fintrustsec.com.br (browser), installers at `/download/` |
| Server | VM `cadastroai-srv`, resource group `rg-cadastroai`, subscription "Microsoft Azure" (FINTRUST SECURITIZADORA), Brazil South, Standard_B2ms, Ubuntu 24.04 |
| Public IP | 20.206.200.132 (static) |
| DNS | A record `cadastro` in the fintrustsec.com.br zone at HostGator |
| HTTPS | Let's Encrypt, obtained and renewed by Caddy |
| Code | `/opt/cadastro-ai`, settings in `/opt/cadastro-ai/deploy/.env` (mode 600) |
| SSH | `ssh -i ~/.ssh/cadastroai_azure cadastro@20.206.200.132` |

## Network rules (network security group `cadastroai-srv-nsg`)

- **HTTPS (443) and SSH (22):** only from the office IP, 177.92.53.232. If the office IP changes,
  update both rules in the Azure portal (VM › Networking › Network settings).
- **HTTP (80):** open to everyone. Let's Encrypt validates and renews the certificate through it.
  The site only redirects it to HTTPS.
- **Database and Redis:** not exposed outside the Docker network.

## Secrets

The production `.env` holds:
- `STORAGE_ENCRYPTION_KEY`: without it the stored documents cannot be decrypted;
- the database password and the JWT secret;
- the AI key;
- the first administrator's initial password.

A copy is kept outside git, on the administrator's computer, in `backups/producao-azure.env`. It
belongs in a password vault as well. The backup passphrase is `/etc/cadastro/backup.pass` on the
server, with a copy in `backups/producao-azure-backup.pass`.

## Backups

- **Schedule:** `/etc/cron.d/cadastro-backup` runs `scripts/backup.sh` daily at 02:30. It writes
  an encrypted archive (database dump plus documents) to `/var/backups/cadastro` and keeps 35
  days. The log is `/var/log/cadastro-backup.log`.
- **Off-server copy:** these archives live on the same VM. Azure Backup of the VM, if enabled when
  the VM was created, adds a copy outside it. Otherwise, copy the archives periodically to other
  storage.

Restore an archive:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/etc/cadastro/backup.pass -in cadastro-AAAAMMDD-HHMMSS.tar.enc | tar -xf -
```

This yields `cadastro.dump` (use `pg_restore`) and `documents.tgz`.

## Updating

From the developer's machine, in the repository:

```bash
git archive --format=tar HEAD | ssh -i ~/.ssh/cadastroai_azure cadastro@20.206.200.132 'tar -x -C /opt/cadastro-ai'
```

```bash
ssh -i ~/.ssh/cadastroai_azure cadastro@20.206.200.132 'cd /opt/cadastro-ai/deploy && sudo docker compose -f docker-compose.prod.yml up -d --build'
```

`git archive` never overwrites `deploy/.env` (it is not in git). Migrations run when the api
starts.

**Desktop app:** tag `desktop-vX.Y.Z`. The repository variable `CADASTRO_API_URL` already points at
this server. Copy the release's `CadastroAI-setup.exe` and `CadastroAI.msi` to
`/opt/cadastro-ai/deploy/download/`.

## Database viewer (read-only)

pgweb runs on the server's loopback only (`127.0.0.1:8081`) and logs in as `leitura`, which can
only SELECT (password hashes and sessions excluded). It is reached through SSH, so the same
office-IP rule applies. From the administrator's Mac:

```bash
ssh -i ~/.ssh/cadastroai_azure -N -L 8082:127.0.0.1:8081 cadastro@20.206.200.132
```

then open http://localhost:8082 and leave the terminal open while using it (Ctrl+C closes it). If
the viewer is not running: `docker compose -f docker-compose.prod.yml --profile ferramentas up -d dbweb`.

## Initial data

The portfolio was copied from the development database: 105 clients, 15 commercials (Vitra
Connect already merged into Vittra), 25 signature records and the status catalog. User accounts
and test registrations were not copied. The first administrator is
`leonardosilva@fintrustsec.com.br`; the other accounts are created in Configurações › Usuários.
AI analysis is on.
