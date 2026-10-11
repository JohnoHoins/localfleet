#!/bin/bash
# ── LocalFleet Launcher ──────────────────────────────────────────────
# One-click start: Ollama + model preload + Backend + Dashboard + Browser
# Double-click this file in the LocalFleet folder (a symlink to it, e.g. on
# the Desktop, also works). Every step is checked; LOCALFLEET READY is only
# printed when all of them succeeded.
#
# Optional environment overrides:
#   LOCALFLEET_MODEL       Ollama model to preload (default qwen2.5:72b; the
#                          backend reads the same variable)
#   LOCALFLEET_KEEP_ALIVE  how long Ollama keeps the model in memory after the
#                          preload (default 60m; a duration like 2h, or -1 = forever)
#   LOCALFLEET_LLM_TIMEOUT seconds the backend waits for one command parse

set -u

# Resolve symlinks so the repo is found even when launched through a link
SCRIPT="$0"
while [ -L "$SCRIPT" ]; do
    LINK="$(readlink "$SCRIPT")"
    case "$LINK" in
        /*) SCRIPT="$LINK" ;;
        *)  SCRIPT="$(dirname "$SCRIPT")/$LINK" ;;
    esac
done
cd "$(dirname "$SCRIPT")" || exit 1

BACKEND_PORT=8000
DASH_PORT=5173
BACKEND_URL="http://127.0.0.1:$BACKEND_PORT"
DASH_URL="http://localhost:$DASH_PORT"
OLLAMA_URL="http://localhost:11434"
MODEL="${LOCALFLEET_MODEL:-qwen2.5:72b}"
KEEP_ALIVE="${LOCALFLEET_KEEP_ALIVE:-60m}"
PRELOAD_MAX_SECONDS=900  # a cold load of a ~47 GB model can take minutes

BACKEND_PID=""
DASH_PID=""
PROBLEMS=""   # failures that rule out READY
WARNINGS=""   # optional features that will not work

ok()      { echo "[OK] $*"; }
problem() { echo "[!!] $*"; PROBLEMS="${PROBLEMS}  - $*"$'\n'; }
warn()    { echo "[!!] $*"; WARNINGS="${WARNINGS}  - $*"$'\n'; }

# Kill only processes LISTENING on a port. `lsof -i :PORT` also matches
# clients, e.g. a browser tab still connected to the old dashboard.
kill_listeners() {
    local pids
    pids=$(lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null)
    [ -n "$pids" ] && kill $pids 2>/dev/null
    return 0
}

stop_services() {
    [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null
    if [ -n "$DASH_PID" ]; then
        kill "$DASH_PID" 2>/dev/null
        # pnpm runs Vite as a child process; make sure the dev server goes too
        kill_listeners "$DASH_PORT"
    fi
}

cleanup() {
    trap - INT TERM HUP
    echo ""
    echo "Shutting down..."
    stop_services
    echo "Done."
    exit 0
}

# fail MESSAGE [HINT] — report a fatal step, stop what was started, exit
fail() {
    echo "[!!] $1"
    [ $# -gt 1 ] && echo "     $2"
    stop_services
    exit 1
}

# wait_for_url URL SECONDS [PID] — poll until URL answers with 2xx; give up
# early if PID (the process that should be serving it) has exited
wait_for_url() {
    local url="$1" secs="$2" pid="${3:-}" i=0
    while [ "$i" -lt "$secs" ]; do
        curl -sf -o /dev/null --max-time 2 "$url" && return 0
        if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
            return 1
        fi
        sleep 1
        i=$((i + 1))
    done
    return 1
}

# Shut down cleanly on Ctrl+C or when the Terminal window is closed
trap cleanup INT TERM HUP

echo "==============================="
echo "  LOCALFLEET — Starting Up"
echo "==============================="
echo ""

# 0. Prerequisites (see Quick Start in README.md)
for tool in curl lsof ollama pnpm; do
    command -v "$tool" >/dev/null 2>&1 \
        || fail "'$tool' not found on PATH" "Install the prerequisites listed in README.md (Quick Start)."
done
[ -x .venv/bin/python ] \
    || fail "Python environment not found (.venv)" \
            "Run in $(pwd): python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
.venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || fail ".venv uses Python $(.venv/bin/python -V 2>&1 | cut -d' ' -f2); LocalFleet needs 3.10+" \
            "Recreate it with a newer python3 (e.g. brew install python@3.12)."
[ -d dashboard/node_modules ] \
    || fail "Dashboard dependencies not installed" "Run in $(pwd): cd dashboard && pnpm install"

# 1. Ollama (skip if already running)
if curl -sf -o /dev/null --max-time 3 "$OLLAMA_URL/api/tags"; then
    ok "Ollama already running"
else
    echo "[..] Starting Ollama..."
    ollama serve &
    wait_for_url "$OLLAMA_URL/api/tags" 20 "$!" \
        || fail "Ollama did not start — see the output above"
    ok "Ollama started"
fi

# 2. The model must be pulled (ollama list shows untagged names as name:latest)
MODEL_PULLED=""
if ollama list 2>/dev/null | awk -v m="$MODEL" \
        'NR > 1 && ($1 == m || $1 == m ":latest") { found = 1 } END { exit !found }'; then
    MODEL_PULLED=1
    ok "Model $MODEL is pulled"
else
    problem "Model $MODEL is not pulled. Run: ollama pull $MODEL"
fi

# 3. Stop a stale backend/dashboard left over from a previous run
kill_listeners "$BACKEND_PORT"
kill_listeners "$DASH_PORT"
for port in "$BACKEND_PORT" "$DASH_PORT"; do
    i=0
    while lsof -nP -t -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; do
        [ "$i" -ge 10 ] && fail "Port $port is still in use" \
            "See what holds it: lsof -nP -iTCP:$port -sTCP:LISTEN"
        sleep 0.5
        i=$((i + 1))
    done
done

# 4. Backend
echo "[..] Starting backend..."
.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port "$BACKEND_PORT" &
BACKEND_PID=$!
wait_for_url "$BACKEND_URL/api/assets" 30 "$BACKEND_PID" \
    || fail "Backend failed to start — see the errors above"
ok "Backend running (PID $BACKEND_PID)"

# 5. Dashboard
echo "[..] Starting dashboard..."
(cd dashboard && exec pnpm dev --port "$DASH_PORT" --strictPort) &
DASH_PID=$!
wait_for_url "$DASH_URL/" 30 "$DASH_PID" \
    || fail "Dashboard failed to start — see the errors above" \
            "Vite needs Node.js 20.19+ or 22.12+ (node --version)."
ok "Dashboard running (PID $DASH_PID)"

# 6. Voice input: mlx-whisper decodes audio with the ffmpeg binary
if .venv/bin/python -c 'import importlib.util, sys; sys.exit(importlib.util.find_spec("mlx_whisper") is None)' 2>/dev/null; then
    if command -v ffmpeg >/dev/null 2>&1; then
        ok "Voice input available (mlx-whisper + ffmpeg)"
    else
        warn "ffmpeg not found; mlx-whisper needs it, so voice commands may fail. Install: brew install ffmpeg"
    fi
else
    warn "mlx-whisper not installed; voice commands are unavailable (Apple Silicon only)"
fi

# 7. Load the model into memory by asking Ollama directly. An empty prompt
#    only loads the model: no backend LLM timeout applies, and nothing is
#    dispatched to the fleet or written to the mission log.
if [ -n "$MODEL_PULLED" ]; then
    echo "[..] Loading $MODEL into memory (a cold load can take a few minutes)..."
    case "$KEEP_ALIVE" in
        *[!0-9-]*) KEEP_ALIVE_JSON="\"$KEEP_ALIVE\"" ;;  # duration, e.g. 60m
        *)         KEEP_ALIVE_JSON="$KEEP_ALIVE" ;;      # seconds, e.g. -1
    esac
    LOAD_START=$SECONDS
    RESP=$(curl -sS --max-time "$PRELOAD_MAX_SECONDS" "$OLLAMA_URL/api/generate" \
        -d "{\"model\": \"$MODEL\", \"keep_alive\": $KEEP_ALIVE_JSON}" 2>&1)
    if echo "$RESP" | grep -q '"done": *true'; then
        ok "LLM loaded in $((SECONDS - LOAD_START))s (Ollama keep_alive: $KEEP_ALIVE)"
    else
        problem "LLM preload failed: ${RESP:-no response from Ollama}"
    fi
fi

# 8. Open browser
echo ""
if [ "$(uname -s)" = Darwin ]; then
    if open "$DASH_URL" && open "$DASH_URL/monitor.html"; then
        ok "Opened dashboard + system monitor"
    else
        warn "Could not open the browser; open $DASH_URL manually"
    fi
fi

echo ""
echo "==============================="
if [ -z "$PROBLEMS" ]; then
    echo "  LOCALFLEET READY"
else
    echo "  LOCALFLEET RUNNING, NOT READY"
fi
echo "  Dashboard: $DASH_URL"
echo "  Monitor:   $DASH_URL/monitor.html"
echo "  Backend:   $BACKEND_URL"
echo "==============================="
if [ -n "$PROBLEMS" ]; then
    echo "Problems (commands will fail until fixed):"
    printf '%s' "$PROBLEMS"
fi
if [ -n "$WARNINGS" ]; then
    echo "Warnings:"
    printf '%s' "$WARNINGS"
fi
echo ""
echo "Press Ctrl+C to shut down all services."

# Wait for Ctrl+C (the trap above cleans up)
wait
cleanup
