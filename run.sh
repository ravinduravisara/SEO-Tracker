#!/bin/bash
set -e

# Automatically find project root (where requirements.txt is located)
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
if [ ! -f "$DIR/requirements.txt" ] && [ -f "$DIR/../requirements.txt" ]; then
  DIR="$( cd "$DIR/.." >/dev/null 2>&1 && pwd )"
fi
cd "$DIR"

# Ensure .env exists in project root
if [ ! -f .env ]; then
  if [ -f backend/.env ]; then
    cp backend/.env .env
  elif [ -f .env.example ]; then
    cp .env.example .env
  fi
fi

# Ensure frontend/static symlink exists
if [ ! -e frontend/static ]; then
  (cd frontend && ln -sf . static)
fi

# Locate Python
if [ ! -d ".venv" ]; then
  echo "Creating .venv virtual environment..."
  if command -v /opt/homebrew/bin/python3 >/dev/null 2>&1; then
    /opt/homebrew/bin/python3 -m venv .venv
  else
    python3 -m venv .venv
  fi
fi

PYTHON=".venv/bin/python"

PORT=${PORT:-8000}
echo ""
echo "=========================================================="
echo " Starting eSupport SEO Platform v10.4.0 (MongoDB Atlas)"
echo " Access at: http://127.0.0.1:$PORT"
echo " Admin:     http://127.0.0.1:$PORT/admin"
echo " Docs:      http://127.0.0.1:$PORT/docs"
echo "=========================================================="
echo ""

exec "$PYTHON" -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" --reload
