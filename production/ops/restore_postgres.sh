#!/usr/bin/env bash
set -euo pipefail
: "${DUMP_FILE:?Set DUMP_FILE to a verified pg_dump custom-format file}"
COMPOSE=(docker compose --env-file .env.production -f docker-compose.yml)
DB="$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_DB | tr -d '\r')"
DBUSER="$("${COMPOSE[@]}" exec -T postgres printenv POSTGRES_USER | tr -d '\r')"
sha256sum -c "$DUMP_FILE.sha256"
echo "WARNING: This replaces the target database contents."
read -r -p "Type RESTORE-TO-TARGET to continue: " c
[[ "$c" == "RESTORE-TO-TARGET" ]] || exit 1
"${COMPOSE[@]}" exec -T postgres pg_restore --clean --if-exists --no-owner -U "$DBUSER" -d "$DB" < "$DUMP_FILE"
