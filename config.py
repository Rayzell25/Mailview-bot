# =========================================================
#  KONFIGURASI MAIL VIEWER BOT
#  Edit file ini dengan: nano config.py
# =========================================================

# Token bot Telegram (dapatkan dari @BotFather)
TELEGRAM_TOKEN = "ISI_TOKEN_BOT_TELEGRAM"

# Server IMAP. Untuk Gmail biarkan seperti ini.
IMAP_HOST = "imap.gmail.com"

# Daftar akun email penampung (IMAP).
# Untuk Gmail, "pass" WAJIB pakai App Password (bukan password biasa).
# Cara buat App Password: https://myaccount.google.com/apppasswords
# Bisa isi lebih dari satu akun, dicek paralel.
IMAP_ACCOUNTS = [
    {"user": "emailkamu1@gmail.com", "pass": "app-password-1"},
    # {"user": "emailkamu2@gmail.com", "pass": "app-password-2"},
]

# =========================================================
#  OPSIONAL: Local Bot API Server (untuk respon lebih cepat)
#  Biarkan False kalau kamu belum punya server telegram-bot-api sendiri.
#  Kalau diaktifkan, pastikan server jalan di LOCAL_BOT_API_URL.
# =========================================================
USE_LOCAL_BOT_API = False
LOCAL_BOT_API_URL = "http://127.0.0.1:8081"
