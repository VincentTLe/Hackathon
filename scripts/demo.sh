#!/usr/bin/env bash
# Spin up the Bridge demo with two cloudflared quick tunnels so the founder
# and the receiver can use the app from different laptops.
#
# Usage:  ./scripts/demo.sh
# Requires: cloudflared (brew install cloudflared), python venv at backend/.venv
#           (or a global uvicorn on PATH), node/npm for the frontend.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"
LOG_DIR="$ROOT/.demo-logs"
mkdir -p "$LOG_DIR"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install it with:  brew install cloudflared"
  exit 1
fi

cleanup() {
  echo ""
  echo "Shutting down demo processes..."
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PIDS=()

start_tunnel() {
  local port="$1"
  local logfile="$2"
  : > "$logfile"
  cloudflared tunnel --no-autoupdate --url "http://localhost:$port" \
    > "$logfile" 2>&1 &
  PIDS+=("$!")
  # Wait for the trycloudflare URL to appear in the log.
  local url=""
  for _ in $(seq 1 40); do
    url=$(grep -Eo 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$logfile" | head -n1 || true)
    if [[ -n "$url" ]]; then
      echo "$url"
      return 0
    fi
    sleep 0.5
  done
  echo "ERROR: cloudflared tunnel for port $port never produced a URL. See $logfile" >&2
  return 1
}

echo "Starting cloudflared tunnel for frontend (port 3000)..."
FRONTEND_URL="$(start_tunnel 3000 "$LOG_DIR/cloudflared-frontend.log")"
echo "  -> $FRONTEND_URL"

echo "Starting cloudflared tunnel for backend (port 8000)..."
BACKEND_URL="$(start_tunnel 8000 "$LOG_DIR/cloudflared-backend.log")"
echo "  -> $BACKEND_URL"

# Write env files so both servers use the public URLs.
BACKEND_ENV="$BACKEND/.env"
FRONTEND_ENV="$FRONTEND/.env.local"

# Preserve existing GEMINI_API_KEY and MODEL_ID if already configured.
EXISTING_KEY=""
EXISTING_MODEL=""
if [[ -f "$BACKEND_ENV" ]]; then
  EXISTING_KEY="$(grep -E '^GEMINI_API_KEY=' "$BACKEND_ENV" | head -n1 || true)"
  EXISTING_MODEL="$(grep -E '^MODEL_ID=' "$BACKEND_ENV" | head -n1 || true)"
fi
if [[ -z "$EXISTING_KEY" && -n "${GEMINI_API_KEY:-}" ]]; then
  EXISTING_KEY="GEMINI_API_KEY=$GEMINI_API_KEY"
fi
if [[ -z "$EXISTING_MODEL" ]]; then
  EXISTING_MODEL="MODEL_ID=gemini-2.5-flash-lite"
fi
if [[ -z "$EXISTING_KEY" ]]; then
  echo "WARNING: no GEMINI_API_KEY found in $BACKEND_ENV or environment."
  echo "         Set it before starting, or the backend will fail to boot."
fi

cat > "$BACKEND_ENV" <<EOF
${EXISTING_KEY}
${EXISTING_MODEL}
APP_BASE_URL=${FRONTEND_URL}
ALLOWED_ORIGINS=${FRONTEND_URL}
ALLOWED_ORIGIN_REGEX=https://.*\\.trycloudflare\\.com|http://localhost(:\\d+)?|http://127\\.0\\.0\\.1(:\\d+)?
EOF

cat > "$FRONTEND_ENV" <<EOF
NEXT_PUBLIC_API_URL=${BACKEND_URL}
EOF

echo ""
echo "Wrote:"
echo "  $BACKEND_ENV"
echo "  $FRONTEND_ENV"
echo ""

# Start backend.
echo "Starting backend (uvicorn)..."
(
  cd "$BACKEND"
  if [[ -d ".venv" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
  fi
  exec uvicorn app.main:app --host 0.0.0.0 --port 8000
) > "$LOG_DIR/backend.log" 2>&1 &
PIDS+=("$!")

# Start frontend.
echo "Starting frontend (next dev)..."
(
  cd "$FRONTEND"
  exec npm run dev -- -p 3000
) > "$LOG_DIR/frontend.log" 2>&1 &
PIDS+=("$!")

echo ""
echo "================================================================"
echo "  Founder (this laptop):   $FRONTEND_URL"
echo "  Receiver (other laptop): open whatever invite link the app"
echo "                           generates — it will point at the same"
echo "                           $FRONTEND_URL host, so it just works."
echo ""
echo "  Logs: $LOG_DIR/"
echo "  Press Ctrl-C to stop everything."
echo "================================================================"

wait
