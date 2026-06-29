import logging
import imaplib
import email
import time
import re
import html
import email.utils
import pytz
import threading
import asyncio
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
)

from config import TELEGRAM_TOKEN, IMAP_HOST, IMAP_ACCOUNTS

# Opsi Local Bot API (opsional). Kalau tidak ada di config, pakai Telegram Cloud biasa.
try:
    from config import USE_LOCAL_BOT_API, LOCAL_BOT_API_URL
except Exception:
    USE_LOCAL_BOT_API = False
    LOCAL_BOT_API_URL = "http://127.0.0.1:8081"

logging.basicConfig(level=logging.INFO)

user_email = {}        # simpan email terakhir tiap user
chat_messages = {}     # chat_id -> set(message_id) untuk auto-hapus

# Hapus semua chat otomatis setelah sekian detik tidak ada aktivitas
CLEANUP_DELAY = 600    # 10 menit


# =========================
# AUTO-DELETE / TRACKING
# =========================
def track(chat_id, *message_ids):
    """Catat message_id agar bisa dihapus otomatis nanti."""
    s = chat_messages.setdefault(chat_id, set())
    for mid in message_ids:
        if mid:
            s.add(mid)


async def _cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    """Hapus semua pesan yang tercatat di sebuah chat (dipanggil JobQueue)."""
    chat_id = context.job.chat_id
    ids = chat_messages.pop(chat_id, set())
    for mid in list(ids):
        try:
            await context.bot.delete_message(chat_id, mid)
        except Exception:
            pass
    # bersihkan email terakhir (chat private: chat_id == user_id)
    user_email.pop(chat_id, None)


def schedule_cleanup(context: ContextTypes.DEFAULT_TYPE, chat_id):
    """Reset timer auto-hapus 10 menit setiap ada aktivitas."""
    jq = getattr(context, "job_queue", None)
    if jq is None:
        return
    for job in jq.get_jobs_by_name(f"cleanup_{chat_id}"):
        job.schedule_removal()
    jq.run_once(_cleanup_job, CLEANUP_DELAY, chat_id=chat_id, name=f"cleanup_{chat_id}")


# =========================
# IMAP
# =========================
def imap_connect(account, folder="INBOX"):
    mail = imaplib.IMAP4_SSL(IMAP_HOST)
    mail.login(account["user"], account["pass"])

    # Deteksi nama folder Spam untuk Gmail (biasanya "[Gmail]/Spam")
    if folder == "SPAM":
        try:
            status, _ = mail.select('"[Gmail]/Spam"')
            if status != "OK":
                mail.select("INBOX")
        except Exception:
            mail.select("INBOX")
    else:
        mail.select("INBOX")

    return mail


def clean_text(text):
    if not text:
        return ""

    text = html.unescape(text)

    # hapus script & style
    text = re.sub(r'(?is)<style.*?>.*?</style>', ' ', text)
    text = re.sub(r'(?is)<script.*?>.*?</script>', ' ', text)

    # ganti <br> jadi newline
    text = re.sub(r'(?i)<br\s*/?>', '\n', text)

    # hapus semua tag html
    text = re.sub(r'<[^>]+>', ' ', text)

    # rapihin spasi
    text = re.sub(r'\s+', ' ', text)

    return text.strip()


def extract_otp(text):
    if not text:
        return None

    text_lower = text.lower()

    # keyword yang biasa ada di email OTP
    keywords = ["otp", "kode", "verification", "code", "passcode"]

    # cek apakah ada keyword OTP
    if not any(k in text_lower for k in keywords):
        return None

    # cari angka 4-6 digit
    matches = re.findall(r'\b\d{4,6}\b', text)

    if not matches:
        return None

    # ambil yang paling masuk akal (biasanya pertama)
    return matches[0]


def decode_mime_text(value):
    if not value:
        return ""

    parts = email.header.decode_header(value)
    result = ""

    for part, enc in parts:
        if isinstance(part, bytes):
            result += part.decode(enc or "utf-8", errors="ignore")
        else:
            result += part

    return result.strip()


def extract_body(msg):
    body = ""
    html_body = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition.lower():
                continue

            payload = part.get_payload(decode=True)
            if not payload:
                continue

            charset = part.get_content_charset() or "utf-8"

            try:
                decoded = payload.decode(charset, errors="ignore")
            except Exception:
                decoded = payload.decode("utf-8", errors="ignore")

            if content_type == "text/plain" and not body:
                body = decoded

            if content_type == "text/html" and not html_body:
                html_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="ignore")

    return body if body else html_body


def clean_from(value):
    name, addr = email.utils.parseaddr(value)

    name = decode_mime_text(name)
    addr = addr.strip()

    if name and addr:
        return f"{name}\n📨 Sender Email : {addr}"

    return addr or value


def check_single_account(account, target_lower, local_part):
    # Cek di INBOX terlebih dahulu, lalu di SPAM jika tidak ditemukan
    for folder_name in ["INBOX", "SPAM"]:
        mail = None
        try:
            mail = imap_connect(account, folder_name)

            # Menggunakan query search IMAP "TO" agar server Gmail langsung memfilter dengan cepat,
            # daripada mendownload header ALL satu-persatu (11.000+ email akan mengakibatkan timeout/stuck)
            status, data = mail.search(None, f'TO "{local_part}"')

            if status != "OK" or not data or not data[0]:
                # Fallback jika pencarian spesifik TO gagal
                status, data = mail.search(None, "ALL")

            if status != "OK" or not data or not data[0]:
                continue

            ids = data[0].split()
            # Urutkan dari yang terbaru (reverse)
            recent_ids = ids[-15:]
            recent_ids.reverse()

            for rid in recent_ids:
                status, msg_data = mail.fetch(rid, "(RFC822)")
                if status != "OK":
                    continue
                msg = email.message_from_bytes(msg_data[0][1])

                # Cari target email di header To, Delivered-To, X-Original-To, atau di body email
                to_headers = " ".join([
                    msg.get("To", ""),
                    msg.get("Delivered-To", ""),
                    msg.get("X-Original-To", "")
                ]).lower()

                body = extract_body(msg)
                body_lower = body.lower() if body else ""

                if target_lower in to_headers or target_lower in body_lower:
                    return msg
        except Exception as folder_err:
            logging.warning(f"Error checking {account['user']} {folder_name}: {folder_err}")
        finally:
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass
    return None


def get_latest_email(target_email):
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        # Hapus spasi dan jadikan huruf kecil
        target_email = target_email.strip()
        target_lower = target_email.lower()

        # Ambil username/local_part dari email (sebelum tanda @)
        local_part = target_lower.split("@")[0] if "@" in target_lower else target_lower

        found_msg = None

        # Cek secara paralel di semua akun Gmail menggunakan ThreadPoolExecutor untuk fast response
        with ThreadPoolExecutor(max_workers=max(1, len(IMAP_ACCOUNTS))) as executor:
            futures = {executor.submit(check_single_account, account, target_lower, local_part): account for account in IMAP_ACCOUNTS}
            for future in as_completed(futures):
                msg = future.result()
                if msg:
                    found_msg = msg
                    break

        if not found_msg:
            return f"📭 Tidak ada email terbaru yang dikirim ke <code>{html.escape(target_email)}</code>"

        subject = decode_mime_text(found_msg.get("Subject", "(No Subject)"))
        from_raw = found_msg.get("From", "-")
        name, addr = email.utils.parseaddr(from_raw)
        from_name = decode_mime_text(name) or "-"
        from_addr = addr.strip() or from_raw

        body = extract_body(found_msg)
        body = clean_text(body)

        if not body:
            body = "(Isi email kosong / tidak terbaca)"

        otp = extract_otp(body)

        date_raw = found_msg.get("Date", "")
        try:
            date_obj = email.utils.parsedate_to_datetime(date_raw)
            if date_obj.tzinfo is None:
                date_obj = pytz.utc.localize(date_obj)

            wib = pytz.timezone("Asia/Jakarta")
            date_obj = date_obj.astimezone(wib)
            date_fmt = date_obj.strftime("%d %b %Y %H:%M WIB")
        except Exception:
            date_fmt = date_raw

        safe_email = html.escape(target_email)
        safe_name = html.escape(from_name)
        safe_addr = html.escape(from_addr)
        safe_subject = html.escape(subject)
        safe_date = html.escape(date_fmt)
        safe_body = html.escape(body)

        result = f"""📩 <b>Inbox Terbaru</b>
──────────────────
<pre>Name    : {safe_name}
Email   : {safe_email}
Sender  : {safe_addr}
Subject : {safe_subject}
Date    : {safe_date}</pre>
"""

        if otp:
            result += f"🔑 OTP : <code>{html.escape(otp)}</code>\n"

        result += "──────────────────\n"
        result += safe_body

        return result

    except Exception as e:
        return f"❌ Error:\n{html.escape(str(e))}"


# =========================
# TELEGRAM UI & UTILS
# =========================
def refresh_button():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Refresh Email", callback_data="refresh_last")],
        [InlineKeyboardButton("📩 Cek Email Lain", callback_data="check_other")]
    ])


def start_loading(msg, loop):
    stop_loading = threading.Event()

    def loading_progress():
        frames = [
            "▰▱▱▱▱▱▱▱▱▱",
            "▰▰▱▱▱▱▱▱▱▱",
            "▰▰▰▱▱▱▱▱▱▱",
            "▰▰▰▰▱▱▱▱▱▱",
            "▰▰▰▰▰▱▱▱▱▱",
            "▰▰▰▰▰▰▱▱▱▱",
            "▰▰▰▰▰▰▰▱▱▱",
            "▰▰▰▰▰▰▰▰▱▱",
            "▰▰▰▰▰▰▰▰▰▱",
            "▰▰▰▰▰▰▰▰▰▰",
        ]

        i = 0

        async def edit_msg(frame):
            try:
                await msg.edit_text(
                    f"╭─ 📬 <b>Mengecek Inbox</b>\n"
                    f"│ {frame}\n"
                    f"╰─ ⏳ Mohon tunggu...",
                    parse_mode="HTML"
                )
            except Exception:
                pass

        while not stop_loading.is_set():
            bar = frames[i % len(frames)]
            asyncio.run_coroutine_threadsafe(edit_msg(bar), loop)
            i += 1
            time.sleep(0.7)

    t = threading.Thread(target=loading_progress)
    t.daemon = True
    t.start()

    return stop_loading


async def send_long_result(bot_msg, text, reply_markup=None):
    """Edit pesan bot_msg dengan hasil. Kalau hasil terlalu panjang, sambung sebagai pesan baru.
    Mengembalikan list message_id pesan tambahan (untuk auto-hapus)."""
    max_len = 3500
    parts = []
    extra_ids = []

    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(text[:cut])
        text = text[cut:]

    if text:
        parts.append(text)

    if len(parts) == 1:
        try:
            await bot_msg.edit_text(
                parts[0],
                parse_mode="HTML",
                reply_markup=reply_markup,
                disable_web_page_preview=True
            )
        except Exception:
            pass
        return extra_ids

    try:
        await bot_msg.edit_text(
            parts[0],
            parse_mode="HTML",
            disable_web_page_preview=True
        )
    except Exception:
        pass

    for part in parts[1:-1]:
        m = await bot_msg.reply_text(
            part,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        extra_ids.append(m.message_id)

    m = await bot_msg.reply_text(
        parts[-1],
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )
    extra_ids.append(m.message_id)
    return extra_ids


async def run_check(bot_msg, target, chat_id):
    """Jalankan pengecekan inbox + animasi loading, lalu EDIT pesan bot_msg dengan hasil."""
    loop = asyncio.get_running_loop()
    stop_loading = start_loading(bot_msg, loop)

    result = get_latest_email(target)

    stop_loading.set()
    await asyncio.sleep(0.1)

    # Tambahkan jam refresh -> menjamin isi pesan selalu berubah (anti "message not modified")
    now = datetime.now(pytz.timezone("Asia/Jakarta")).strftime("%H:%M:%S")
    result += f"\n\n<i>🕒 Diperbarui: {now} WIB</i>"

    extra = await send_long_result(bot_msg, result, reply_markup=refresh_button())
    track(chat_id, bot_msg.message_id, *extra)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    track(chat_id, update.message.message_id)

    m = await update.message.reply_text(
        "👋 <b>Selamat datang di Mail Viewer Bot</b>\n\n"
        "📧 Kirim alamat email yang ingin kamu cek inbox / OTP-nya.\n\n"
        "<i>ℹ️ Semua chat akan terhapus otomatis setelah 10 menit tidak ada aktivitas.</i>",
        parse_mode="HTML"
    )
    track(chat_id, m.message_id)
    schedule_cleanup(context, chat_id)


async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id
    chat_id = update.effective_chat.id

    track(chat_id, update.message.message_id)

    if text == "/refresh":
        if user_id not in user_email:
            m = await update.message.reply_text("❌ Belum ada email yang dicek.")
            track(chat_id, m.message_id)
            schedule_cleanup(context, chat_id)
            return

        target = user_email[user_id]
        msg = await update.message.reply_text(
            "╭─ 📬 <b>Mengecek Inbox</b>\n│ ▱▱▱▱▱▱▱▱▱▱\n╰─ ⏳ Mohon tunggu...",
            parse_mode="HTML"
        )
        await run_check(msg, target, chat_id)
        schedule_cleanup(context, chat_id)
        return

    if "@" in text:
        target = text.strip()
        user_email[user_id] = target

        msg = await update.message.reply_text(
            "╭─ 📬 <b>Mengecek Inbox</b>\n│ ▱▱▱▱▱▱▱▱▱▱\n╰─ ⏳ Mohon tunggu...",
            parse_mode="HTML"
        )
        await run_check(msg, target, chat_id)
        schedule_cleanup(context, chat_id)
        return

    m = await update.message.reply_text("❌ Kirim alamat email yang valid (mengandung @).")
    track(chat_id, m.message_id)
    schedule_cleanup(context, chat_id)


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    # Jawab callback DULUAN -> animasi loading di tombol langsung hilang (anti-ngendat)
    await q.answer()

    user_id = q.from_user.id
    chat_id = q.message.chat.id
    data = q.data

    if data == "check_other":
        user_email.pop(user_id, None)
        try:
            await q.edit_message_text("📧 Kirim email lain yang mau dicek.")
        except Exception:
            pass
        track(chat_id, q.message.message_id)
        schedule_cleanup(context, chat_id)
        return

    if data == "refresh_last":
        if user_id not in user_email:
            try:
                await q.edit_message_text("❌ Belum ada email yang dicek.")
            except Exception:
                pass
            schedule_cleanup(context, chat_id)
            return

        target = user_email[user_id]
        # EDIT pesan yang sama (tidak membuat pesan baru)
        await run_check(q.message, target, chat_id)
        schedule_cleanup(context, chat_id)
        return


# =========================
# MAIN
# =========================
def main():
    builder = Application.builder().token(TELEGRAM_TOKEN)

    # Pakai Local Bot API server hanya jika diaktifkan di config (respon tombol lebih cepat)
    if USE_LOCAL_BOT_API:
        builder = (
            builder
            .base_url(f"{LOCAL_BOT_API_URL}/bot")
            .base_file_url(f"{LOCAL_BOT_API_URL}/file/bot")
            .local_mode(True)
        )

    app = builder.build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("🤖 BOT RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()
