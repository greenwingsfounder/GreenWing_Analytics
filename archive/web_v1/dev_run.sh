#!/usr/bin/env bash
# GELİŞTİRME / ÖNİZLEME başlatıcısı — tek komut, sıfır yapılandırma.
#
# Neden ayrı: üretim (web/run.sh) kimlik doğrulamayı ZORUNLU kılar ve
# hiçbir varsayılan parola kabul etmez. Önizleme ortamında kullanıcının
# terminal yok; bu yüzden burada AÇIKÇA işaretlenmiş bir demo parolası
# tanımlanır ve HTTP çerezine izin verilir.
#
#   ./web/dev_run.sh
#
# Ekrana yazılan kullanıcı/parola ile giriş yapılır.

set -euo pipefail
cd "$(dirname "$0")/.."

# DİKKAT: GREENWING_DASHBOARD_PASSWORD tek kullanıcı modunda
# kullanıcı adı __admin__ olur. Çok kullanıcı için GREENWING_USERS.
DEMO_USER="${GREENWING_DEMO_USER:-__admin__}"
DEMO_PASS="${GREENWING_DEMO_PASS:-greenwing}"
PORT="${GREENWING_WEB_PORT:-8051}"

echo ""
echo "  ┌──────────────────────────────────────────────────────┐"
echo "  │  GreenWing Analytics — önizleme sunucusu             │"
echo "  ├──────────────────────────────────────────────────────┤"
printf "  │  kullanıcı : %-40s│\n" "$DEMO_USER"
printf "  │  parola    : %-40s│\n" "$DEMO_PASS"
printf "  │  port      : %-40s│\n" "$PORT"
echo "  └──────────────────────────────────────────────────────┘"
echo ""

export GREENWING_DASHBOARD_PASSWORD="$DEMO_PASS"
export GREENWING_SESSION_SECRET="${GREENWING_SESSION_SECRET:-$(head -c 32 /dev/urandom | base64 | tr -d '=+/' | head -c 43)}"
# HTTP önizlemede Secure çerezi kapat (aksi halde oturum açılmaz)
export GREENWING_INSECURE_COOKIE=1

# Sanal ortam varsa onu kullan, yoksa sistem python'u
PYTHON_BIN="${GREENWING_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for cand in .venv/bin/python venv/bin/python /tmp/sectools/bin/python; do
    [[ -x "$cand" ]] && PYTHON_BIN="$cand" && break
  done
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"

exec "$PYTHON_BIN" -m uvicorn web.app:app \
  --host 0.0.0.0 --port "$PORT" \
  --proxy-headers --forwarded-allow-ips='*'
