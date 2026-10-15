#!/usr/bin/env bash
# Create the venv, install pinned deps, run migrations and seed the demo data.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-/Library/Frameworks/Python.framework/Versions/3.12/bin/python3}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$(command -v python3)"
fi
echo "==> using python: $PYTHON_BIN"
"$PYTHON_BIN" -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/pip install -r backend/requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> created .env from .env.example"
fi

echo "==> running migrations"
( cd backend && ../.venv/bin/alembic -c alembic.ini upgrade head )

echo "==> seeding demo data"
./.venv/bin/python -m scripts.seed_db

echo
echo "Done. Start the API with:  ./scripts/run_server.sh"
echo "Then open http://127.0.0.1:8000/ (after building the frontend) or /docs"
