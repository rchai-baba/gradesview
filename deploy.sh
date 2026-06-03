#!/usr/bin/env bash

# ------------------------------------------------------------
# Deployment script for GradesView (local testing)
# ------------------------------------------------------------
# This script:
#   1. Sets up (or re‑uses) a Python virtual‑environment.
#   2. Installs backend requirements.
#   3. Starts the FastAPI backend.
#   4. Installs frontend dependencies, builds the React app,
#      and serves it with a local `serve` binary.
#   5. Cleans up on exit (Ctrl‑C).
# ------------------------------------------------------------

set -euo pipefail

log() { echo -e "\033[1;34m[deploy]\033[0m $*"; }

# ------------------- Python backend -------------------------
log "Preparing Python virtual environment"
if [[ -d .venv ]]; then
    log "Re‑using existing .venv"
else
    log "Creating new .venv"
    python3 -m venv .venv
fi
source .venv/bin/activate

log "Installing backend dependencies (quiet, no‑op if up‑to‑date)"
pip install --quiet -r backend/requirements.txt

# Ensure backend is a package so uvicorn can import it
if [[ ! -f backend/__init__.py ]]; then
    log "Adding empty __init__.py to backend/ (makes it a package)"
    touch backend/__init__.py
fi

# Ensure no lingering backend on port 8000
if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    log "Killing existing process on port 8000"
    lsof -tiTCP:8000 -sTCP:LISTEN | xargs -r kill -9
  fi
fi

log "Starting FastAPI backend (http://0.0.0.0:8000)"
# Run uvicorn in background and capture its PID in the parent shell
uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
log "Backend PID = $BACKEND_PID"
# Ensure no lingering process on port 8080 (previous serve instance)
if command -v lsof > /dev/null 2>&1; then
  if lsof -iTCP:8080 -sTCP:LISTEN -t > /dev/null 2>&1; then
    log "Killing existing process on port 8080"
    lsof -tiTCP:8080 -sTCP:LISTEN | xargs -r kill -9
  fi
fi

# ------------------- Frontend dev server -----------------
log "Installing frontend dependencies"
cd frontend
npm ci --silent

log "Starting frontend dev server (npm run dev)"
# Ensure no lingering dev server on default Vite port 5173
if command -v lsof > /dev/null 2>&1; then
  if lsof -iTCP:5173 -sTCP:LISTEN -t > /dev/null 2>&1; then
    log "Killing existing process on port 5173"
    lsof -tiTCP:5173 -sTCP:LISTEN | xargs -r kill -9
  fi
fi

npm run dev &
FRONTEND_PID=$!
log "Frontend PID = $FRONTEND_PID"

# Return to project root
cd ..

# ------------------- Cleanup handling -----------------------
cleanup() {
    log "Cleaning up background processes"
    kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
    deactivate || true
    exit 0
}
trap cleanup INT TERM EXIT

log "✅ Deployment ready!"
log "→ Backend: http://localhost:8000"
log "→ Frontend: http://localhost:5173"

# Keep the script alive until a signal is received
while true; do sleep 86400; done
