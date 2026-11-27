#!/usr/bin/env bash
set -euo pipefail
: "${BACKUP_DIR:?Set BACKUP_DIR to an encrypted/off-host mounted destination}"
COMPOSE=(docker compose --env-file .env.production -f docker-compose.yml)
DB="$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_DB | tr -d '\r')"
DBUSER="$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_USER | tr -d '\r')"
mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$BACKUP_DIR/llm-qoe-${STAMP}.dump"
"${COMPOSE[@]}" exec -T postgres pg_dump -U "$DBUSER" -d "$DB" -Fc > "$FILE"
sha256sum "$FILE" > "$FILE.sha256"
chmod 600 "$FILE" "$FILE.sha256"
echo "Backup written: $FILE"
echo "Store this on encrypted storage and periodically test restore to a separate database."
