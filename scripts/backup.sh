#!/usr/bin/env bash
# Encrypted backup of the database and the document repository.
#
#   BACKUP_DIR=/mnt/backup BACKUP_PASSPHRASE_FILE=/etc/cadastro/backup.pass scripts/backup.sh
#
# On the production server add COMPOSE_FILE=deploy/docker-compose.prod.yml.
#
# Documents are already encrypted at rest with STORAGE_ENCRYPTION_KEY; the archive is encrypted
# again with the backup passphrase. Keep STORAGE_ENCRYPTION_KEY in the vault separately from the
# backups: without it the documents cannot be read, with it and the backup they can.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:?set BACKUP_DIR}"
PASS_FILE="${BACKUP_PASSPHRASE_FILE:?set BACKUP_PASSPHRASE_FILE}"
KEEP_DAYS="${KEEP_DAYS:-35}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$(dirname "$0")/.."
docker compose exec -T db pg_dump -U cadastro -d cadastro --format=custom > "$WORK/cadastro.dump"
# the api container runs unprivileged, so the archive comes out on stdout rather than a mounted folder
docker compose run --rm --no-deps -T --entrypoint tar api -C /data -czf - documents > "$WORK/documents.tgz"
tar -C "$WORK" -cf - cadastro.dump documents.tgz \
  | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "file:$PASS_FILE" \
  > "$BACKUP_DIR/cadastro-$STAMP.tar.enc"
sha256sum "$BACKUP_DIR/cadastro-$STAMP.tar.enc" > "$BACKUP_DIR/cadastro-$STAMP.tar.enc.sha256"
find "$BACKUP_DIR" -name 'cadastro-*.tar.enc*' -mtime +"$KEEP_DAYS" -delete
echo "backup written: $BACKUP_DIR/cadastro-$STAMP.tar.enc"
