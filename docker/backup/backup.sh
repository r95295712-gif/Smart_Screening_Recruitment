#!/bin/sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
STAMP="$(date +%Y-%m-%d)"
TARGET="${BACKUP_DIR}/smart-screening-${STAMP}.sql.gz.enc"

if [ "${1:-}" = "--dry-run" ]; then
  echo "Would create encrypted database backup: ${TARGET}"
  echo "Would retain the latest 7 files."
  exit 0
fi

if [ -z "${BACKUP_ENCRYPTION_PASSWORD:-}" ]; then
  echo "BACKUP_ENCRYPTION_PASSWORD is required." >&2
  exit 1
fi

mkdir -p "${BACKUP_DIR}"
pg_dump | gzip | openssl enc -aes-256-cbc -pbkdf2 \
  -pass env:BACKUP_ENCRYPTION_PASSWORD \
  -out "${TARGET}"

find "${BACKUP_DIR}" -type f -name "smart-screening-*.sql.gz.enc" \
  -printf "%T@ %p\n" | sort -nr | awk 'NR > 7 {print $2}' | xargs -r rm -f

echo "Backup created: ${TARGET}"

