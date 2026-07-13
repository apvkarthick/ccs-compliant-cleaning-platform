#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/apps/ccs-platform}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NGINX_CONF="/etc/nginx/sites-available/ccs-platform"
NGINX_ENABLED="/etc/nginx/sites-enabled/ccs-platform"

cd "$APP_DIR"

# Python venv + deps
if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

. .venv/bin/activate
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q

# Directories
mkdir -p storage/source storage/generated uploads logs
mkdir -p /var/www/ccs-frontend/dist

python -m compileall api -q

# React frontend
if [ -d "frontend/dist" ]; then
  cp -a frontend/dist/. /var/www/ccs-frontend/dist/
fi

# LibreOffice — required for DOCX → PDF conversion
if ! command -v libreoffice >/dev/null 2>&1; then
  echo "[deploy] Installing LibreOffice headless (first run only)..."
  apt-get install -y --no-install-recommends libreoffice libreoffice-writer
fi

# Nginx config for ccs.nxai.com.au
if [ -f "$APP_DIR/deploy/nginx-ccs.conf" ]; then
  cp "$APP_DIR/deploy/nginx-ccs.conf" "$NGINX_CONF"
  ln -sf "$NGINX_CONF" "$NGINX_ENABLED" 2>/dev/null || true
  nginx -t && systemctl reload nginx
fi

systemctl restart ccs-api
systemctl restart ccs-worker
systemctl restart ccs-beat 2>/dev/null || echo "[deploy] ccs-beat not found — create /etc/systemd/system/ccs-beat.service if you want scheduled sends"
