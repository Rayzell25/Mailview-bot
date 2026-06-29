# ⚡ Cloudflare Mail Router Bot (TMAIL1) ⚡

Bot Telegram untuk mengelola Cloudflare Email Routing Rules (Email Forwarding) dan melakukan pengecekan inbox email masuk (IMAP) secara instan, aman, dan super cepat.

## 🚀 Fitur Utama

- **➕ Create Forwarding Rules**: Mendukung pembuatan email forwarding manual (custom nama) maupun otomatis (generate random).
- **🎲 Generate Random Names (Secugen Method)**: Membuat nama email acak sepanjang 9 karakter berbasis vokal-konsonan berseling (mudah dibaca) serta dijamin **100% bebas duplikat**. Jumlah email yang dibuat diinput secara manual oleh user.
- **📋 Auto Pagination Domain List**: Membaca seluruh domain yang ada di akun Cloudflare Anda secara lengkap (mendukung akun dengan puluhan/ratusan domain) dan menyajikannya dalam format halaman interaktif (6 baris/12 domain per halaman).
- **🗑️ Multi Delete Rules**: Mempermudah penghapusan banyak email rules sekaligus secara bersamaan.
- **📬 Fast Inbox Email Checker**: Memindai seluruh inbox email secara bersamaan menggunakan teknologi multi-threading (`ThreadPoolExecutor`), memotong waktu tunggu hingga setengahnya.
- **🔄 Clean UI & Navigation**: Navigasi antar-menu yang mulus dengan auto-edit dan auto-delete pesan lama agar ruang obrolan Telegram tetap bersih dari sampah chat history.

## ⚙️ Persyaratan
- Python 3.8+
- Akun Cloudflare dengan Email Routing diaktifkan
- Akun Gmail/IMAP untuk penampungan email forwarding

## 📦 Instalasi

1. Clone repositori ini:
   ```bash
   git clone git@github.com:dadanr6699/cftmail.git
   cd cftmail
   ```

2. Instal dependensi yang diperlukan:
   ```bash
   pip install -r requirements.txt
   ```

3. Konfigurasi kredensial pada file `config.py`:
   - `TELEGRAM_TOKEN`: Token bot Telegram Anda.
   - `CF_API_TOKEN`: API Token Cloudflare Anda (pastikan memiliki izin edit Zone & Email Routing).
   - `CF_ACCOUNT_ID`: Account ID Cloudflare Anda.
   - `DESTINATION_EMAIL`: Alamat email tujuan forward.
   - `IMAP_HOST`: Alamat host IMAP penampung email.
   - `ACCOUNTS`: Daftar user & password (app password) akun penampung email.

## 🏁 Menjalankan Bot dengan PM2

Untuk memastikan bot berjalan secara terus-menerus di latar belakang, gunakan PM2:

```bash
# Menjalankan bot
pm2 start bot.py --name "tmail1-bot" --interpreter python3

# Melihat status
pm2 status tmail1-bot

# Melihat log bot
pm2 logs tmail1-bot
```
