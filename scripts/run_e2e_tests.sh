#!/usr/bin/env bash
# Run the Playwright suites against an already running E2E server.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
NODE_BIN_DIR="/Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/node/bin"
PNPM_JS="/Users/ee/.dsh/dsh-runtimes/dsh-primary-runtime/dependencies/pnpm/bin/pnpm.mjs"
export PATH="$NODE_BIN_DIR:$PATH"
# browsers live inside the repo because the user-level cache is not writable here
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.playwright-browsers"
E2E_BASE_URL="${E2E_BASE_URL:-http://127.0.0.1:8000}"
"$NODE_BIN_DIR/node" "$PNPM_JS" install --silent
E2E_BASE_URL="$E2E_BASE_URL" "$NODE_BIN_DIR/node" "$ROOT/node_modules/@playwright/test/cli.js" test "$@"
