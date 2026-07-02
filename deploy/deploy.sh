#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/apps/ccs-platform}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$APP_DIR"

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

mkdir -p storage/source storage/generated uploads logs
mkdir -p /var/www/ccs-frontend/dist

python -m compileall api

if [ -d "frontend/dist" ]; then
  cp -a frontend/dist/. /var/www/ccs-frontend/dist/
fi

systemctl restart ccs-api
systemctl restart ccs-worker
systemctl reload nginx
