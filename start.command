#!/bin/bash
# MoCA web app -- double-click this file to start it.
# First start: sets everything up (a few minutes, needs internet once).
# After that: opens the app in the browser in a few seconds.
cd "$(dirname "$0")" || exit 1
PORT="${MOCA_PORT:-8000}"
URL="http://127.0.0.1:$PORT"

if curl -s "$URL/api/status" >/dev/null 2>&1; then
  echo "The MoCA app is already running."
  open "$URL"
  exit 0
fi

if [ ! -x .venv/bin/python ]; then
  echo "First start: setting up (this takes a few minutes)..."
  PY=""
  # 3.11-3.13 have ready-made packages for everything the app uses
  for c in python3.12 python3.11 python3.13 python3; do
    if command -v "$c" >/dev/null 2>&1 &&
       "$c" -c 'import sys; sys.exit(not (3, 10) <= sys.version_info[:2] < (3, 14))' 2>/dev/null; then
      PY="$c"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.12 is needed. Install it from https://www.python.org/downloads/ and try again."
    read -r -p "Press Enter to close."
    exit 1
  fi
  "$PY" -m venv .venv || { echo "Could not create the Python environment."; read -r -p "Press Enter to close."; exit 1; }
fi
if [ ! -f .venv/.installed ] || [ requirements-web.txt -nt .venv/.installed ]; then
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements-web.txt || {
    echo "Installing failed -- check the internet connection and try again."
    read -r -p "Press Enter to close."
    exit 1
  }
  touch .venv/.installed
fi

if [ ! -f .env ]; then
  echo "The app needs its settings first: copy .env.example to .env and fill it in."
  echo "README.md section 1 explains where each value comes from."
  read -r -p "Press Enter to close."
  exit 1
fi

# Build the screens when they have changed (needs Node.js 20 or newer)
if [ ! -f frontend/dist/index.html ] || [ -n "$(find frontend/src frontend/index.html frontend/package.json -newer frontend/dist/index.html 2>/dev/null | head -1)" ]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "Node.js is needed to build the app. Install it from https://nodejs.org and try again."
    read -r -p "Press Enter to close."
    exit 1
  fi
  echo "Building the app..."
  ( cd frontend && npm ci && npm run build ) || {
    echo "Building failed."
    read -r -p "Press Enter to close."
    exit 1
  }
fi

echo "Starting the MoCA app at $URL"
echo "Keep this window open while you use the app. Close it to stop the app."
( sleep 3; open "$URL" ) &
exec .venv/bin/python -m uvicorn webapp.server:app --host 127.0.0.1 --port "$PORT"
