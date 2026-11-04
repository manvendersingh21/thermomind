#!/usr/bin/env bash
# Start the API (uvicorn --reload on :8000) and the Vite dev server (:5173) together.
# Ctrl-C stops both.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-5173}"
UVICORN="$ROOT/.venv/bin/uvicorn"

if [ ! -x "$UVICORN" ]; then
  echo "error: $UVICORN not found; run 'make setup' first" >&2
  exit 1
fi

pids=()
cleanup() {
  echo
  echo "stopping dev servers..."
  for pid in "${pids[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(
  cd "$ROOT/apps/api"
  exec "$UVICORN" app.main:app --reload --host 127.0.0.1 --port "$API_PORT"
) &
pids+=($!)

if [ -f "$ROOT/apps/web/package.json" ]; then
  if [ ! -d "$ROOT/apps/web/node_modules" ]; then
    echo "warning: apps/web/node_modules missing; run 'npm install' in apps/web" >&2
  fi
  (
    cd "$ROOT/apps/web"
    exec npm run dev -- --port "$WEB_PORT"
  ) &
  pids+=($!)
else
  echo "warning: apps/web/package.json not found; starting API only" >&2
fi

echo "ThermoMind dev servers:"
echo "  API : http://localhost:$API_PORT   (docs: http://localhost:$API_PORT/docs)"
echo "  Web : http://localhost:$WEB_PORT"
echo "Press Ctrl-C to stop both."

wait -n 2>/dev/null || wait
