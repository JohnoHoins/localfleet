#!/bin/bash
# ── LocalFleet Launcher ──────────────────────────────────────────────
# One-click start: Ollama + Backend + Dashboard + Browser
# Double-click this file on your Desktop to launch everything.

cd "$(dirname "$0")"

echo "==============================="
echo "  LOCALFLEET — Starting Up"
echo "==============================="
echo ""

# 1. Ollama (skip if already running)
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "[OK] Ollama already running"
else
    echo "[..] Starting Ollama..."
    ollama serve &
    sleep 3
    echo "[OK] Ollama started"
fi

# 2. Kill stale backend/dashboard if lingering
lsof -i :8000 -t 2>/dev/null | xargs kill 2>/dev/null
lsof -i :5173 -t 2>/dev/null | xargs kill 2>/dev/null
sleep 1

# 3. Backend
echo "[..] Starting backend..."
.venv/bin/python -m uvicorn src.api.server:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
sleep 4

if curl -s http://127.0.0.1:8000/api/assets > /dev/null 2>&1; then
    echo "[OK] Backend running (PID $BACKEND_PID)"
else
    echo "[!!] Backend failed to start"
fi

# 4. Dashboard
echo "[..] Starting dashboard..."
cd dashboard && pnpm dev &
DASH_PID=$!
cd ..
sleep 3
echo "[OK] Dashboard running (PID $DASH_PID)"

# 5. Warm up LLM
echo ""
echo "[..] Warming up LLM (first call is slow)..."
curl -s -X POST http://127.0.0.1:8000/api/command \
  -H "Content-Type: application/json" \
  -d '{"text": "all vessels loiter at 500 500"}' > /dev/null 2>&1
echo "[OK] LLM warm"

# Reset to clean state after warm-up
curl -s -X POST http://127.0.0.1:8000/api/reset > /dev/null 2>&1
echo "[OK] Fleet reset to clean state"

# 6. Open browser
echo ""
echo "[OK] Opening dashboard + system monitor..."
open http://localhost:5173
open http://localhost:5173/monitor.html

echo ""
echo "==============================="
echo "  LOCALFLEET READY"
echo "  Dashboard: http://localhost:5173"
echo "  Monitor:   http://localhost:5173/monitor.html"
echo "  Backend:   http://127.0.0.1:8000"
echo "==============================="
echo ""
echo "Press Ctrl+C to shut down all services."

# Wait for Ctrl+C, then clean up
trap "echo ''; echo 'Shutting down...'; kill $BACKEND_PID $DASH_PID 2>/dev/null; echo 'Done.'; exit 0" INT
wait
