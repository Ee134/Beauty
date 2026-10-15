#!/usr/bin/env bash
# Serve the built PWA + API for the Playwright suite on a dedicated, freshly seeded database.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -d frontend/dist ]; then
  echo "frontend/dist is missing. Build it first:"
  echo "  cd frontend && pnpm install && pnpm build"
  exit 1
fi

DB="$ROOT/e2e.db"
rm -f "$DB" "$DB-wal" "$DB-shm"
export DATABASE_URL="sqlite+pysqlite:///$DB"
export UPLOAD_DIR="$ROOT/var/e2e-uploads"
export DATA_DIR="$ROOT/data"
export SCHEDULER_ENABLED=true
export SCHEDULER_INTERVAL=5
export NOTIFICATION_MODE=in_app
export AUTH_MODE=demo
rm -rf "$UPLOAD_DIR"

( cd backend && ../.venv/bin/alembic -c alembic.ini upgrade head )
./.venv/bin/python -m scripts.seed_db

echo "==> serving on http://127.0.0.1:8000 (Ctrl+C to stop)"
exec ./.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
