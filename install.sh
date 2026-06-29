#!/usr/bin/env bash
# =========================================================
#  Mail Viewer Bot - Installer
#  - Install dependency Python (venv)
#  - Install Docker + Local Bot API server (telegram-bot-api) + Redis
#    supaya respon tombol/callback bot cepat (anti-lag)
#  - Edit config.py via nano
#  Jalankan: bash install.sh
# =========================================================
set -e

# Kredensial app Telegram untuk Local Bot API server (dari repo premium-emoji-buat-bot).
# Ambil sendiri di https://my.telegram.org bila ingin ganti. Ini BUKAN token bot.
TELEGRAM_API_ID="32773999"
TELEGRAM_API_HASH="d2eb7260911dbce615a1fb27f36d4b12"

# Warna
GREEN="\033[0;32m"
YELLOW="\033[1;33m"
RED="\033[0;31m"
NC="\033[0m"

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Pakai sudo otomatis kalau bukan root
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

# Folder tempat script ini berada
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# ---------------------------------------------------------
# 1. Paket dasar + dependency Python
# ---------------------------------------------------------
info "Update daftar paket (apt update)..."
$SUDO apt-get update -y

info "Install paket dasar (python3, pip, venv, git, nano, curl)..."
$SUDO apt-get install -y python3 python3-pip python3-venv git nano curl ca-certificates

info "Membuat virtual environment (venv)..."
python3 -m venv venv

info "Mengaktifkan venv & install dependency Python..."
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate || true

# ---------------------------------------------------------
# 2. Install Docker (kalau belum ada)
# ---------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
    info "Docker sudah terpasang, lewati instalasi Docker."
else
    info "Install Docker via script resmi (get.docker.com)..."
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    $SUDO sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
    $SUDO systemctl enable docker >/dev/null 2>&1 || true
    $SUDO systemctl start docker >/dev/null 2>&1 || true
fi

# Tentukan perintah docker compose (v2 plugin "docker compose" atau v1 "docker-compose")
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    warn "Plugin docker compose tidak ditemukan, mencoba install docker-compose-plugin..."
    $SUDO apt-get install -y docker-compose-plugin || true
    DC="docker compose"
fi

# ---------------------------------------------------------
# 3. Setup Local Bot API server + Redis (Docker)
# ---------------------------------------------------------
info "Menyiapkan Local Bot API server (telegram-bot-api) + Redis..."
mkdir -p bot-api

cat > bot-api/.env <<EOF
TELEGRAM_API_ID=${TELEGRAM_API_ID}
TELEGRAM_API_HASH=${TELEGRAM_API_HASH}
EOF

cat > bot-api/docker-compose.yml <<'EOF'
# Local Bot API server + Redis untuk respon bot yang cepat.
# Image telegram-bot-api WAJIB versi terbaru (9.4+) supaya fitur terbaru dikenali.
services:
  telegram-bot-api:
    image: aiogram/telegram-bot-api:latest
    container_name: telegram-bot-api
    restart: always
    environment:
      - TELEGRAM_API_ID=${TELEGRAM_API_ID}
      - TELEGRAM_API_HASH=${TELEGRAM_API_HASH}
      - TELEGRAM_LOCAL=1
    # Diikat ke localhost VPS -> tidak terbuka ke internet (aman).
    ports:
      - "127.0.0.1:8081:8081"
    volumes:
      - telegram-bot-api-data:/var/lib/telegram-bot-api
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"

  redis:
    image: redis:7-alpine
    container_name: bot-redis
    restart: always
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - bot-redis-data:/data

volumes:
  telegram-bot-api-data:
    name: telegram-bot-api-data
  bot-redis-data:
    name: bot-redis-data
EOF

info "Menarik image terbaru & menjalankan container..."
( cd bot-api && $SUDO $DC pull && $SUDO $DC up -d )

info "Local Bot API server jalan di http://127.0.0.1:8081 ✅"

# ---------------------------------------------------------
# 4. Edit konfigurasi bot
# ---------------------------------------------------------
echo ""
warn "Sekarang kita edit konfigurasi (token bot & akun IMAP)."
warn "Setelah selesai edit di nano: tekan CTRL+O lalu ENTER untuk simpan, dan CTRL+X untuk keluar."
echo ""
read -r -p "Tekan ENTER untuk membuka config.py di nano..."

nano config.py

# ---------------------------------------------------------
# Selesai
# ---------------------------------------------------------
echo ""
info "Instalasi selesai! ✅"
echo ""
echo "Cara menjalankan bot:"
echo "  source venv/bin/activate"
echo "  python3 bot.py"
echo ""
warn "Catatan: jika token bot ini PERNAH dipakai di server resmi Telegram,"
warn "logout dulu sekali agar bisa pindah ke Local Bot API:"
echo "  curl https://api.telegram.org/bot<TOKEN_BOT>/logOut"
echo ""
echo "Agar bot tetap jalan di background (opsional), pakai screen/tmux/systemd:"
echo "  screen -S mailbot"
echo "  source venv/bin/activate && python3 bot.py   (lepas: CTRL+A lalu D)"
echo ""
echo "Cek / update Local Bot API server:"
echo "  cd bot-api && $DC pull && $DC up -d"
