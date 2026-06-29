#!/usr/bin/env bash
# =========================================================
#  Mail Viewer Bot - Installer
#  Jalankan: bash install.sh
# =========================================================
set -e

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

info "Update daftar paket (apt update)..."
$SUDO apt-get update -y

info "Install paket yang dibutuhkan (python3, pip, venv, git, nano)..."
$SUDO apt-get install -y python3 python3-pip python3-venv git nano

info "Membuat virtual environment (venv)..."
python3 -m venv venv

info "Mengaktifkan venv & install dependency Python..."
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

info "Dependency selesai diinstall."
echo ""
warn "Sekarang kita edit konfigurasi (token bot & akun IMAP)."
warn "Setelah selesai edit di nano: tekan CTRL+O lalu ENTER untuk simpan, dan CTRL+X untuk keluar."
echo ""
read -r -p "Tekan ENTER untuk membuka config.py di nano..."

nano config.py

echo ""
info "Instalasi selesai! ✅"
echo ""
echo "Cara menjalankan bot:"
echo "  source venv/bin/activate"
echo "  python3 bot.py"
echo ""
echo "Agar bot tetap jalan di background (opsional), bisa pakai screen/tmux/systemd:"
echo "  screen -S mailbot"
echo "  source venv/bin/activate && python3 bot.py"
echo "  (lepas screen dengan CTRL+A lalu D)"
