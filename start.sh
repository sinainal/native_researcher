#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
REQUIREMENTS_FILE="$PROJECT_DIR/requirements.txt"
REQ_HASH_FILE="$VENV_DIR/.requirements.sha256"
PLAYWRIGHT_MARKER="$VENV_DIR/.playwright.chromium.installed"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
MAX_PORT_SCAN="${MAX_PORT_SCAN:-20}"

cd "$PROJECT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 bulunamadi."
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  echo ".venv olusturuluyor..."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

CURRENT_HASH="$(sha256sum "$REQUIREMENTS_FILE" | awk '{print $1}')"
INSTALLED_HASH=""
if [ -f "$REQ_HASH_FILE" ]; then
  INSTALLED_HASH="$(cat "$REQ_HASH_FILE")"
fi

if [ "$CURRENT_HASH" != "$INSTALLED_HASH" ]; then
  echo "Bagimliliklar yukleniyor/guncelleniyor..."
  python -m pip install --upgrade pip
  python -m pip install -r "$REQUIREMENTS_FILE"
  printf '%s' "$CURRENT_HASH" > "$REQ_HASH_FILE"
else
  if ! python - <<'PY' >/dev/null 2>&1
import fastapi
import uvicorn
import httpx
import pydantic
import playwright
PY
  then
    echo "Eksik paketler bulundu, yeniden yukleniyor..."
    python -m pip install --upgrade pip
    python -m pip install -r "$REQUIREMENTS_FILE"
    printf '%s' "$CURRENT_HASH" > "$REQ_HASH_FILE"
  fi
fi

if python - <<'PY' >/dev/null 2>&1
import playwright
PY
then
  if [ ! -f "$PLAYWRIGHT_MARKER" ]; then
    echo "Chromium browser kuruluyor..."
    python -m playwright install chromium >/dev/null
    touch "$PLAYWRIGHT_MARKER"
  fi
fi

SELECTED_PORT="$(python - <<PY
import socket
host = ${HOST@Q}
start_port = int(${PORT@Q})
scan_limit = int(${MAX_PORT_SCAN@Q})

for port in range(start_port, start_port + scan_limit + 1):
    sock = socket.socket()
    try:
        sock.bind((host, port))
    except OSError:
        continue
    else:
        print(port)
        sock.close()
        break
else:
    raise SystemExit(1)
PY
)" || {
  echo "Bos port bulunamadi. HOST=$HOST baslangic PORT=$PORT"
  exit 1
}

if [ "$SELECTED_PORT" != "$PORT" ]; then
  echo "PORT $PORT dolu. Kullanilan yeni port: $SELECTED_PORT"
fi

echo "Native Researcher baslatiliyor: http://$HOST:$SELECTED_PORT"
PORT="$SELECTED_PORT"
exec python -m uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
