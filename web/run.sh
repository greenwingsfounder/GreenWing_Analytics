#!/usr/bin/env bash
# GreenWing web panelini başlatır.
#
# Kimlik doğrulama ZORUNLUDUR. Parola tanımlanmadan panel açılmaz.
#   export GREENWING_DASHBOARD_PASSWORD='guclu-bir-parola'
#   export GREENWING_SESSION_SECRET="$(openssl rand -hex 32)"   # üretimde
#   ./web/run.sh

set -euo pipefail
cd "$(dirname "$0")/.."
exec python -m uvicorn web.app:app \
  --host "${GREENWING_WEB_HOST:-0.0.0.0}" \
  --port "${GREENWING_WEB_PORT:-8051}" \
  --proxy-headers --forwarded-allow-ips='*'
