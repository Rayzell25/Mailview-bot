# 📬 Mail Viewer Bot

Bot Telegram sederhana untuk **mengecek inbox / OTP** dari email masuk lewat IMAP (Gmail), langsung dari Telegram. Cepat karena memindai semua akun penampung secara paralel (multi-threading) dan otomatis mengekstrak kode OTP.

> Catatan: Fitur Create / Delete / List email forwarding (Cloudflare) sudah dihapus. Bot ini fokus **hanya untuk cek inbox**.

## 🚀 Fitur

- 📥 **Cek Inbox**: Kirim alamat email, bot menampilkan email terbaru yang masuk.
- 🔑 **Auto Extract OTP**: Mendeteksi kode OTP 4-6 digit dari isi email.
- ⚡ **Multi-Account Paralel**: Memindai beberapa akun IMAP sekaligus dengan `ThreadPoolExecutor`.
- 🧹 **Cek INBOX + SPAM**: Otomatis ikut memeriksa folder Spam Gmail.
- 🔄 **Refresh & Cek Email Lain**: Tombol cepat tanpa ketik ulang.

## ⚙️ Persyaratan

- VPS / server Linux (Debian/Ubuntu) dengan akses `apt`
- Python 3.8+
- Akun Gmail dengan **App Password** (bukan password biasa) — buat di https://myaccount.google.com/apppasswords
- Token bot Telegram dari [@BotFather](https://t.me/BotFather)

## 📦 Instalasi (VPS baru, sekali jalan)

VPS baru biasanya belum ada `git`, jadi pasang dulu lalu clone & jalankan installer:

```bash
apt update && apt install -y git
git clone https://github.com/Rayzell25/Mailview-bot.git
cd Mailview-bot
bash install.sh
```

`install.sh` otomatis melakukan **semuanya**:
- `apt update` + install `python3`, `pip`, `venv`, `git`, `nano`, `curl`
- install **Docker** + jalankan **Local Bot API server** (`telegram-bot-api`, `api_id`/`api_hash` sudah disertakan) di `127.0.0.1:8081` untuk respon tombol cepat
- install dependency Python (virtualenv)
- di akhir, **meminta input**:
  - 👉 **TOKEN BOT** (dari [@BotFather](https://t.me/BotFather))
  - 👉 **ID ADMIN** Telegram (boleh lebih dari satu, pisah spasi; kosongkan kalau ingin semua orang boleh pakai)

  Keduanya otomatis ditulis ke `config.py`.
- lalu membuka `config.py` di **nano** untuk kamu isi bagian **IMAP_ACCOUNTS** secara manual:

  ```python
  IMAP_ACCOUNTS = [
      {"user": "emailkamu@gmail.com", "pass": "app-password-16-digit"},
  ]
  ```

  > Gmail WAJIB pakai **App Password** (buat di https://myaccount.google.com/apppasswords). Simpan di nano: `CTRL+O` lalu `ENTER`, keluar `CTRL+X`.

## 🏁 Menjalankan Bot

```bash
source venv/bin/activate
python3 bot.py
```

Agar tetap jalan di background, gunakan `screen` (atau tmux/systemd):

```bash
screen -S mailbot
source venv/bin/activate && python3 bot.py
# lepas screen: CTRL+A lalu D
```

## 💬 Cara Pakai

1. Buka chat bot di Telegram, kirim `/start`.
2. Kirim alamat email yang ingin dicek.
3. Bot menampilkan email terbaru + OTP (jika ada).
4. Gunakan tombol **🔄 Refresh Email** atau **📩 Cek Email Lain**.

## ⚡ Opsional: Local Bot API Server

Kalau punya server `telegram-bot-api` sendiri (untuk respon lebih cepat), set di `config.py`:

```python
USE_LOCAL_BOT_API = True
LOCAL_BOT_API_URL = "http://127.0.0.1:8081"
```

Biarkan `False` jika belum punya — bot akan pakai Telegram Cloud biasa.
