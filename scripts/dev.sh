#!/usr/bin/env bash
# Start PostgreSQL (if managed locally), run migrations, then start backend (8000) and frontend (3000).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="${LOG_DIR:-$ROOT/data/logs}"; mkdir -p "$LOG"

if command -v pg_isready >/dev/null && ! pg_isready -q -h localhost 2>/dev/null; then
  service postgresql start || true
fi
cd "$ROOT/backend"
.venv/bin/alembic upgrade head
nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$LOG/backend.log" 2>&1 &
echo "backend  -> http://localhost:8000  (log: $LOG/backend.log)"
cd "$ROOT/frontend"
if [ ! -d .next ] || [ "${REBUILD:-0}" = "1" ]; then NEXT_TELEMETRY_DISABLED=1 npx next build; fi
nohup npx next start -p 3000 > "$LOG/frontend.log" 2>&1 &
echo "frontend -> http://localhost:3000  (log: $LOG/frontend.log)"
