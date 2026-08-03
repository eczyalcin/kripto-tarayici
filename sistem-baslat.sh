#!/bin/bash
# Tüm sistemi tek komutla başlatır:
#   1) likidasyon toplayıcı (arka plan)
#   2) zamanlayıcı — saatlik tarama + alarmlar (arka plan)
#   3) panel (ön planda, Ctrl+C ile hepsi kapanır)
#
# Kullanım:
#   ./sistem-baslat.sh          → panel sadece bu bilgisayardan erişilebilir
#   ./sistem-baslat.sh --lan    → telefon/diğer bilgisayarlardan da erişilebilir

set -uo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
mkdir -p logs

if [ ! -x "$PY" ]; then
    echo "❌ Sanal ortam yok. Kurulum: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    exit 1
fi

PIDS=()

kapat() {
    echo ""
    echo "⏹  Kapatılıyor..."
    for pid in "${PIDS[@]:-}"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null
    done
    wait 2>/dev/null
    echo "✅ Tüm süreçler durduruldu."
    exit 0
}
trap kapat INT TERM

echo "🚀 Crypto Intelligence başlatılıyor"
echo ""

echo "  1/3  Likidasyon toplayıcı (WebSocket)..."
"$PY" run.py collect >> logs/collector.out 2>&1 &
PIDS+=($!)

echo "  2/3  Zamanlayıcı (saatlik tarama + alarmlar)..."
"$PY" run.py watch >> logs/scheduler.out 2>&1 &
PIDS+=($!)

sleep 2
echo "  3/3  Panel..."
echo ""
echo "  Arka plan logları:  logs/collector.out · logs/scheduler.out"
echo "  Durdurmak için:     Ctrl+C  (üçü birden kapanır)"
echo ""

"$PY" run.py serve "$@"
kapat
