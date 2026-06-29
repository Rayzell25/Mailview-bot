# =========================================================
#  KONFIGURASI MAIL VIEWER BOT
#  Edit file ini dengan: nano config.py
# =========================================================

# Token bot Telegram (dapatkan dari @BotFather).
# Biasanya diisi otomatis oleh install.sh saat instalasi.
TELEGRAM_TOKEN = "ISI_TOKEN_BOT_TELEGRAM"

# ID admin Telegram (user id berupa angka). Hanya admin yang boleh memakai bot.
# Bisa lebih dari satu: ADMIN_IDS = [12345678, 98765432]
# Kalau dikosongkan ( [] ), SEMUA orang boleh memakai bot.
# Biasanya diisi otomatis oleh install.sh saat instalasi.
ADMIN_IDS = []

# Server IMAP. Untuk Gmail biarkan seperti ini.
IMAP_HOST = "imap.gmail.com"

# Daftar akun email penampung (IMAP). EDIT MANUAL via: nano config.py
# Untuk Gmail, "pass" WAJIB pakai App Password (bukan password biasa).
# Cara buat App Password: https://myaccount.google.com/apppasswords
# Bisa isi lebih dari satu akun, dicek paralel.
IMAP_ACCOUNTS = [
    {"user": "emailkamu1@gmail.com", "pass": "app-password-1"},
    # {"user": "emailkamu2@gmail.com", "pass": "app-password-2"},
]

# =========================================================
#  Local Bot API Server (untuk RESPON TOMBOL lebih cepat)
#  install.sh otomatis memasang server ini via Docker di port 8081,
#  jadi biarkan True. Set False kalau mau pakai server resmi Telegram.
# =========================================================
USE_LOCAL_BOT_API = True
LOCAL_BOT_API_URL = "http://127.0.0.1:8081"
