#!/bin/bash
# Raspberry Pi / Linux sunucu kurulumu — Docker kullanmadan, systemd servisleriyle.
#
# Kullanım (proje klasörünün içinden):
#   bash deploy/kurulum-linux.sh
#
# Sonuç: üç servis 7/24 çalışır ve makine yeniden başlayınca kendiliğinden kalkar.

set -euo pipefail

PROJE_DIZIN="$(cd "$(dirname "$0")/.." && pwd)"
KULLANICI="$(whoami)"
PY="$PROJE_DIZIN/.venv/bin/python"

echo "============================================"
echo "  Crypto Intelligence — Linux kurulumu"
echo "============================================"
echo "  Dizin    : $PROJE_DIZIN"
echo "  Kullanıcı: $KULLANICI"
echo ""

# ---------------------------------------------------------------- ön kontrol
if ! command -v python3 >/dev/null 2>&1; then
    echo "❌ python3 bulunamadı. Kurun:  sudo apt install -y python3 python3-venv"
    exit 1
fi

echo "▶ Binance erişimi kontrol ediliyor..."
KOD=$(curl -s -o /dev/null -w "%{http_code}" -m 15 \
      "https://fapi.binance.com/fapi/v1/ping" || echo "000")
if [ "$KOD" = "451" ] || [ "$KOD" = "403" ]; then
    echo "❌ Binance bu sunucunun bulunduğu ülkeden erişimi engelliyor (HTTP $KOD)."
    echo "   ABD merkezli sunucular engellidir. Almanya/Finlandiya/Singapur gibi"
    echo "   bir bölge seçin."
    exit 1
elif [ "$KOD" != "200" ]; then
    echo "⚠ Binance'e ulaşılamadı (HTTP $KOD). Ağ bağlantınızı kontrol edin."
    exit 1
fi
echo "  ✅ Binance erişilebilir"

# ------------------------------------------------------------- sanal ortam
if [ ! -x "$PY" ]; then
    echo "▶ Sanal ortam kuruluyor..."
    python3 -m venv "$PROJE_DIZIN/.venv"
fi
echo "▶ Paketler kuruluyor (birkaç dakika sürebilir)..."
"$PY" -m pip install --upgrade pip -q
"$PY" -m pip install -q -r "$PROJE_DIZIN/requirements.txt"

echo "▶ Bağlantı testi..."
"$PY" "$PROJE_DIZIN/run.py" check || true

# ------------------------------------------------------------- servisler
echo "▶ systemd servisleri yazılıyor (sudo parolası istenebilir)..."

servis_yaz() {
    local ad="$1" aciklama="$2" komut="$3"
    sudo tee "/etc/systemd/system/${ad}.service" >/dev/null <<EOF
[Unit]
Description=${aciklama}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${KULLANICI}
WorkingDirectory=${PROJE_DIZIN}
ExecStart=${PY} ${PROJE_DIZIN}/run.py ${komut}
Restart=always
RestartSec=15
StandardOutput=append:${PROJE_DIZIN}/logs/${ad}.log
StandardError=append:${PROJE_DIZIN}/logs/${ad}.log

[Install]
WantedBy=multi-user.target
EOF
}

mkdir -p "$PROJE_DIZIN/logs" "$PROJE_DIZIN/data" "$PROJE_DIZIN/reports"

servis_yaz "kripto-panel"       "Kripto Panel (Streamlit)"      "serve --lan --no-browser"
servis_yaz "kripto-zamanlayici" "Kripto Zamanlayıcı"            "watch"
servis_yaz "kripto-toplayici"   "Kripto Likidasyon Toplayıcı"   "collect"

sudo systemctl daemon-reload
for s in kripto-panel kripto-zamanlayici kripto-toplayici; do
    sudo systemctl enable "$s" >/dev/null
    sudo systemctl restart "$s"
done

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo "============================================"
echo "  Kurulum tamamlandı"
echo "============================================"
echo ""
echo "  Panel adresi : http://${IP:-<sunucu-ip>}:8501"
echo ""
echo "  Durum        : systemctl status kripto-panel"
echo "  Günlükler    : journalctl -u kripto-zamanlayici -f"
echo "  Durdurma     : sudo systemctl stop kripto-panel kripto-zamanlayici kripto-toplayici"
echo ""
echo "  ⚠ Panel parolası için .env dosyasına DASHBOARD_PASSWORD yazmayı unutmayın,"
echo "    sonra: sudo systemctl restart kripto-panel"
echo ""
