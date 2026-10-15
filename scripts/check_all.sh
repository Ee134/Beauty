#!/usr/bin/env bash
# One command to reproduce every check that this repository claims to pass.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
NODE_BIN_DIR="/Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin"
PNPM_JS="/Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs"
export PATH="$NODE_BIN_DIR:$PATH"
export NODE_BIN_DIR PNPM_JS
# pnpm is not on PATH in this environment; call it through its own node binary
pnpm() { "$NODE_BIN_DIR/node" "$PNPM_JS" "$@"; }
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.playwright-browsers"

status=0
run() {
  echo
  echo "=============================================================="
  echo "== $1"
  echo "=============================================================="
  shift
  "$@" || { echo "!! FAILED: $*"; status=1; }
}

run "pytest: unit + integration + AC01-AC48" ./.venv/bin/python -m pytest tests -q
run "evaluation harness" ./.venv/bin/python -m tests.eval.run_eval
run "openapi + frontend type generation" ./.venv/bin/python -m scripts.export_openapi
run "frontend type-check and build" bash -c "$(declare -f pnpm); cd frontend && pnpm install --silent && pnpm build"

if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8000/api/v1/health; then
  run "playwright E2E (server already running on :8000)" pnpm exec playwright test
else
  echo
  echo "!! Playwright skipped: no E2E server on http://127.0.0.1:8000"
  echo "   start one with: ./scripts/run_e2e_server.sh"
fi

echo
if [ "$status" -eq 0 ]; then
  echo "ALL CHECKS PASSED"
else
  echo "SOME CHECKS FAILED (see above)"
fi
exit "$status"
