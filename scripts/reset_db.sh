#!/usr/bin/env bash
# Delete the local database and uploads, re-run migrations and re-seed.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DB_FILE="$ROOT/beautycare.db"
if [ -f "$DB_FILE" ]; then
  rm -f "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"
  echo "==> removed $DB_FILE"
fi
rm -rf "$ROOT/var/uploads"
mkdir -p "$ROOT/var/uploads"
( cd backend && ../.venv/bin/alembic -c alembic.ini upgrade head )
./.venv/bin/python -m scripts.seed_db
echo "==> database reset and reseeded"
