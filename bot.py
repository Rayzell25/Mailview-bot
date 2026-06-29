import logging
import imaplib
import email
import time
import re
import html
import email.utils
import hashlib
import requests
import os
import pytz
import threading
import asyncio
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
)

from config import TELEGRAM_TOKEN, IMAP_HOST, IMAP_ACCOUNTS, CF_API_TOKEN, CF_ACCOUNT_ID, DESTINATION_EMAIL, ADMIN_IDS

logging.basicConfig(level=logging.INFO)

user_email = {}  # simpan email terakhir tiap user

BASE_CF = "https://api.cloudflare.com/client/v4"
HEADERS = {"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "application/json"}


# === UTIL FOR CLOUDFLARE === #
def is_admin(user_id):
    return user_id in ADMIN_IDS

def _safe_email_from_rule(rule: dict):
    try:
        for m in rule.get("matchers", []):
            if m.get("field") == "to":
                val = m.get("value")
                if isinstance(val, list) and val:
                    val = val[0]
                if isinstance(val, str) and "@" in val:
                    return val
    except Exception as e:
        logging.warning(f"parse error: {e}")
    return None

# === CLOUDFLARE API === #
def get_domains():
    all_zones = []
    page = 1
    per_page = 50
    try:
        while True:
            r = requests.get(f"{BASE_CF}/zones?page={page}&per_page={per_page}", headers=HEADERS)
            if r.status_code == 200:
                zones = r.json().get("result", [])
                if not zones:
                    break
                for z in zones:
                    all_zones.append((z["id"], z["name"]))
                if len(zones) < per_page:
                    break
                page += 1
            else:
                logging.error(f"get_domains error status: {r.status_code} - {r.text}")
                break
    except Exception as e:
        logging.error(f"get_domains error: {e}")
    return all_zones

def list_emails(zone_id):
    all_rules = []
    page = 1
    per_page = 100
    try:
        while True:
            r = requests.get(f"{BASE_CF}/zones/{zone_id}/email/routing/rules?page={page}&per_page={per_page}", headers=HEADERS)
            if r.status_code == 200:
                rules = r.json().get("result", [])
                if not rules:
                    break
                for rule in rules:
                    rid = rule.get("id")
                    eml = _safe_email_from_rule(rule)
                    if rid and eml:
                        all_rules.append({"id": rid, "email": eml})
                if len(rules) < per_page:
                    break
                page += 1
            else:
                logging.error(f"list_emails error status: {r.status_code} - {r.text}")
                break
    except Exception as e:
        logging.error(f"list_emails error: {e}")
    return all_rules

def create_email(zone_id, domain, local_name):
    email = f"{local_name}@{domain}"
    payload = {
        "actions": [{"type": "forward", "value": [DESTINATION_EMAIL]}],
        "matchers": [{"type": "literal", "field": "to", "value": email}],
        "enabled": True,
        "name": f"rule_{local_name}"
    }
    try:
        r = requests.post(f"{BASE_CF}/zones/{zone_id}/email/routing/rules",
                          headers=HEADERS, json=payload)
        logging.info(f"CREATE {email}: {r.status_code}")
        if r.status_code in (200, 201):
            return email
    except Exception as e:
        logging.error(f"create_email error: {e}")
    return None

def delete_email(zone_id, rule_id):
    try:
        r = requests.delete(f"{BASE_CF}/zones/{zone_id}/email/routing/rules/{rule_id}",
                            headers=HEADERS)
        logging.info(f"DELETE {rule_id}: {r.status_code}")
        return r.status_code in (200, 204)
    except Exception as e:
        logging.error(f"delete_email error: {e}")
    return False

logging.basicConfig(level=logging.INFO)

user_email = {}  # simpan email terakhir tiap user


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
    import re

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
            except:
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
        with ThreadPoolExecutor(max_workers=len(IMAP_ACCOUNTS)) as executor:
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
        except:
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
        [InlineKeyboardButton("📩 Cek Email Lain", callback_data="check_other")],
        [InlineKeyboardButton("⬅️ Kembali ke Menu", callback_data="back")]
    ])

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Create Email", callback_data="create_email"),
         InlineKeyboardButton("📥 Cek Inbox", callback_data="check_inbox_menu")],
        [InlineKeyboardButton("📋 List Email", callback_data="list_email"),
         InlineKeyboardButton("❌ Delete Email", callback_data="delete_email")]
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

async def show_main(u_or_q):
    text = """⚡ <b>CLOUDFLARE MAIL ROUTER</b> ⚡
Gunakan menu di bawah ini untuk mengelola email forwarding atau melakukan cek inbox:"""

    if isinstance(u_or_q, Update):
        await u_or_q.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())
    else:
        await u_or_q.edit_message_text(text, parse_mode="HTML", reply_markup=main_menu())

async def send_long_result(bot_msg, text, reply_markup=None):
    max_len = 3500
    parts = []

    while len(text) > max_len:
        cut = text.rfind("\n", 0, max_len)
        if cut == -1:
            cut = max_len
        parts.append(text[:cut])
        text = text[cut:]

    if text:
        parts.append(text)

    if len(parts) == 1:
        await bot_msg.edit_text(
            parts[0],
            parse_mode="HTML",
            reply_markup=reply_markup,
            disable_web_page_preview=True
        )
        return

    await bot_msg.edit_text(
        parts[0],
        parse_mode="HTML",
        disable_web_page_preview=True
    )

    for part in parts[1:-1]:
        await bot_msg.reply_text(
            part,
            parse_mode="HTML",
            disable_web_page_preview=True
        )

    await bot_msg.reply_text(
        parts[-1],
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_admin(user_id):
        await show_main(update)
    else:
        await update.message.reply_text(
            "📧 Kirim email yang mau dicek."
        )

def make_domain_keyboard(domains, current_page, action_prefix, back_callback):
    items_per_page = 12
    total_pages = (len(domains) + items_per_page - 1) // items_per_page
    
    start_idx = (current_page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_domains = domains[start_idx:end_idx]
    
    kb = []
    for i in range(0, len(page_page_domains := page_domains), 2):
        chunk = page_page_domains[i:i+2]
        row = []
        for d in chunk:
            row.append(InlineKeyboardButton(d[1], callback_data=f"{action_prefix}:{d[0]}:{d[1]}"))
        kb.append(row)
        
    nav_row = []
    if current_page > 1:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"page:{action_prefix}:{current_page-1}:{back_callback}"))
    
    nav_row.append(InlineKeyboardButton(f"{current_page}/{total_pages}", callback_data="noop"))
    
    if current_page < total_pages:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"page:{action_prefix}:{current_page+1}:{back_callback}"))
        
    kb.append(nav_row)
    kb.append([InlineKeyboardButton("⬅️ Kembali", callback_data=back_callback)])
    return InlineKeyboardMarkup(kb)


def generate_random_name():
    import random
    vokal = "aeiou"
    konsonan = "bcdfghjklmnpqrstvwxyz"
    
    def suku():
        return random.choice(konsonan) + random.choice(vokal)
        
    name = ""
    while len(name) < 9:
        name += suku()
        
    return name[:9]

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.message.from_user.id

    if is_admin(user_id) and context.user_data.get("awaiting_random_count"):
        if not text.isdigit():
            await update.message.reply_text("⚠️ Harap masukkan angka yang valid.")
            return
        num = int(text)
        if num < 1 or num > 200:
            await update.message.reply_text("⚠️ Harap masukkan angka antara 1 dan 200.")
            return
        
        zid = context.user_data.get("random_zone_id")
        domain = context.user_data.get("random_domain")
        
        names_set = set()
        max_attempts = num * 10
        attempts = 0
        while len(names_set) < num and attempts < max_attempts:
            names_set.add(generate_random_name())
            attempts += 1
        names = list(names_set)
        
        context.user_data.clear()
        progress_msg = await update.message.reply_text(f"⏳ Sedang membuat {num} email random di <b>{domain}</b>...", parse_mode="HTML")
        
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ok, fail = [], []
        
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(create_email, zid, domain, n): n for n in names}
            for future in as_completed(futures):
                n = futures[future]
                try:
                    res = future.result()
                    if res:
                        ok.append(res)
                    else:
                        fail.append(n)
                except Exception:
                    fail.append(n)
                    
        if ok:
            msg = f"✅ <b>{len(ok)} Email random berhasil dibuat di {domain}:</b>\n" + "\n".join(f"• <code>{x}</code>" for x in ok)
        else:
            msg = "❌ Tidak ada email yang berhasil dibuat."
            
        if fail:
            msg += f"\n\n⚠️ <b>Gagal ({len(fail)}):</b> <code>{', '.join(fail[:15])}</code>"
            if len(fail) > 15:
                msg += " ..."
                
        await progress_msg.edit_text(msg, parse_mode="HTML")
        return

    if is_admin(user_id) and context.user_data.get("awaiting_names"):
        if not text:
            await update.message.reply_text("⚠️ Harap ketik minimal satu nama.")
            return
        names = [x.strip() for x in text.split(" ") if x.strip()]
        context.user_data.clear()
        context.user_data["chosen_names"] = names
        domains = get_domains()
        reply_markup = make_domain_keyboard(domains, 1, "mk", "back")
        await update.message.reply_text(f"✅ Nama diterima ({len(names)} email).\nSekarang pilih domain:",
                                  reply_markup=reply_markup, parse_mode="HTML")
        return

    if text == "/refresh":
        if user_id not in user_email:
            await update.message.reply_text("❌ Belum ada email")
            return

        target = user_email[user_id]
        msg = await update.message.reply_text("╭─ 📬 <b>Mengecek Inbox</b>\n│ ▱▱▱▱▱▱▱▱▱▱\n╰─ ⏳ Mohon tunggu...", parse_mode="HTML")

        # Dapatkan loop event loop saat ini di thread async telegram
        loop = asyncio.get_running_loop()
        stop_loading = start_loading(msg, loop)
        # Menunggu sebentar agar UI thread-safe terhindar dari conflict/race conditions
        result = get_latest_email(target)
        stop_loading.set()
        await asyncio.sleep(0.1)

        await send_long_result(msg, result, reply_markup=refresh_button())
        return

    if "@" in text:
        target = text.strip()
        user_email[user_id] = target

        msg = await update.message.reply_text("╭─ 📬 <b>Mengecek Inbox</b>\n│ ▱▱▱▱▱▱▱▱▱▱\n╰─ ⏳ Mohon tunggu...", parse_mode="HTML")

        # Dapatkan loop event loop saat ini di thread async telegram
        loop = asyncio.get_running_loop()
        stop_loading = start_loading(msg, loop)
        result = get_latest_email(target)
        stop_loading.set()
        await asyncio.sleep(0.1)

        await send_long_result(msg, result, reply_markup=refresh_button())
        return

    await update.message.reply_text("❌ Kirim email yang valid")

async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    user_id = q.from_user.id
    data = q.data

    if data.startswith("page:"):
        _, action_prefix, page_str, back_callback = data.split(":", 3)
        page = int(page_str)
        domains = get_domains()
        if not domains:
            await q.edit_message_text("❌ Tidak ada domain ditemukan.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back")]]))
            return
        
        title = "Pilih domain untuk melanjutkan:"
        if action_prefix == "mk":
            names_count = len(context.user_data.get("chosen_names", []))
            title = f"✅ Nama diterima ({names_count} email).\nSekarang pilih domain (Halaman {page}):"
        elif action_prefix == "rd":
            title = f"🎲 Pilih domain untuk generate email random (Halaman {page}):"
        elif action_prefix == "dz":
            title = f"Pilih domain untuk menghapus email (Halaman {page}):"
        elif action_prefix == "lz":
            title = f"Pilih domain untuk melihat daftar email (Halaman {page}):"
            
        await q.edit_message_text(
            title,
            parse_mode="HTML",
            reply_markup=make_domain_keyboard(domains, page, action_prefix, back_callback)
        )
        return


    if data == "back":
        await show_main(q)
        return

    if data == "create_email":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ Custom Nama", callback_data="create_custom"),
             InlineKeyboardButton("🎲 Generate Random", callback_data="create_random")],
            [InlineKeyboardButton("⬅️ Kembali", callback_data="back")]
        ])
        await q.edit_message_text("Pilih metode pembuatan email forwarding:", reply_markup=kb)
        return

    if data == "create_custom":
        await q.edit_message_text(
            "✍️ Ketik nama-nama email yang ingin kamu buat (pisahkan dengan spasi)\n\n"
            "Contoh: <code>nama1 nama2 nama3</code>",
            parse_mode="HTML"
        )
        context.user_data["awaiting_names"] = True
        return

    if data == "create_random":
        domains = get_domains()
        if not domains:
            await q.edit_message_text("❌ Tidak ada domain ditemukan.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back")]]))
            return
        reply_markup = make_domain_keyboard(domains, 1, "rd", "create_email")
        await q.edit_message_text("🎲 Pilih domain untuk generate email random (Halaman 1):", reply_markup=reply_markup)
        return

    if data.startswith("rd:"):
        _, zid, domain = data.split(":", 2)
        context.user_data.clear()
        context.user_data["random_zone_id"] = zid
        context.user_data["random_domain"] = domain
        context.user_data["awaiting_random_count"] = True
        
        await q.edit_message_text(
            f"🌐 Domain terpilih: <b>{domain}</b>\n\n"
            "✍️ Ketik jumlah email random yang ingin dibuat (berupa angka):\n\n"
            "Contoh: <code>5</code>",
            parse_mode="HTML"
        )
        return

    if data == "delete_email":
        domains = get_domains()
        if not domains:
            await q.edit_message_text("❌ Tidak ada domain ditemukan.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back")]]))
            return
        reply_markup = make_domain_keyboard(domains, 1, "dz", "back")
        await q.edit_message_text("Pilih domain untuk menghapus email (Halaman 1):", reply_markup=reply_markup)
        return

    if data.startswith("dz:"):
        _, zid, domain = data.split(":", 2)
        await show_delete_list(q, context, zid, domain)
        return

    if data.startswith("multi:"):
        _, zid, domain, short_id = data.split(":", 3)
        selected = context.user_data.get("selected_multi", set())
        if short_id in selected:
            selected.remove(short_id)
        else:
            selected.add(short_id)
        context.user_data["selected_multi"] = selected
        await show_delete_list(q, context, zid, domain)
        return

    if data == "check_inbox_menu":
        await q.edit_message_text("📧 Kirim nama email yang mau dicek langsung.")
        return

    if data.startswith("multi_del:"):
        _, zid, domain = data.split(":", 2)
        rule_map = context.user_data.get("rule_map", {})
        selected = context.user_data.get("selected_multi", set())
        success, fail = [], []
        for sid in selected:
            rid = rule_map.get(sid)
            if rid and delete_email(zid, rid):
                success.append(sid)
            else:
                fail.append(sid)
        msg = f"✅ {len(success)} email berhasil dihapus."
        if fail:
            msg += f"\n❌ {len(fail)} gagal dihapus."
        await q.edit_message_text(msg,
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data=f"dz:{zid}:{domain}")]]))
        context.user_data["selected_multi"] = set()
        return

    if data == "list_email":
        domains = get_domains()
        if not domains:
            await q.edit_message_text("❌ Tidak ada domain ditemukan.",
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="back")]]))
            return
        reply_markup = make_domain_keyboard(domains, 1, "lz", "back")
        await q.edit_message_text("Pilih domain untuk melihat daftar email (Halaman 1):", reply_markup=reply_markup)
        return

    if data.startswith("lz:"):
        _, zid, domain = data.split(":", 2)
        emails = list_emails(zid)
        if not emails:
            await q.edit_message_text(
                f"Tidak ada email di {domain}.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="list_email")]])
            )
            return

        text = f"📋 <b>Daftar Email di {domain}:</b>\n" + "\n".join(f"• <code>{e['email']}</code>" for e in emails)
        await q.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="list_email")]])
        )
        return

    if data == "refresh_last":
        if user_id not in user_email:
            await q.edit_message_text("❌ Belum ada email yang dicek.")
            return

        target = user_email[user_id]
        msg = await q.message.reply_text("╭─ 📬 <b>Mengecek Inbox</b>\n│ ▱▱▱▱▱▱▱▱▱▱\n╰─ ⏳ Mohon tunggu...", parse_mode="HTML")
        loop = asyncio.get_running_loop()
        stop_loading = start_loading(msg, loop)
        
        result = get_latest_email(target)
        stop_loading.set()
        await asyncio.sleep(0.1)

        await send_long_result(msg, result, reply_markup=refresh_button())
        # Hapus pesan status loading atau pesan callback agar bersih
        try:
            await q.message.delete()
        except:
            pass
        return

    if data == "check_other":
        user_email.pop(user_id, None)
        await q.edit_message_text("📧 Kirim email lain yang mau dicek.")
        return

    if data == "cancel":
        user_email.pop(user_id, None)
        await show_main(q)
        return

    target = user_email[user_id]
    msg = await q.message.reply_text("╭─ 📬 <b>Mengecek Inbox</b>\n│ ▱▱▱▱▱▱▱▱▱▱\n╰─ ⏳ Mohon tunggu...", parse_mode="HTML")
    loop = asyncio.get_running_loop()
    stop_loading = start_loading(msg, loop)
    
    result = get_latest_email(target)
    stop_loading.set()
    await asyncio.sleep(0.1)

    await send_long_result(msg, result, reply_markup=refresh_button())
    try:
        await q.message.delete()
    except:
        pass


async def create_many(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, zid, domain = q.data.split(":", 2)
    names = context.user_data.get("chosen_names", [])
    ok, fail = [], []

    for n in names:
        res = create_email(zid, domain, n)
        if res:
            ok.append(res)
        else:
            fail.append(n)

    if ok:
        msg = "✅ <b>Email berhasil dibuat:</b>\n" + "\n".join(f"• <code>{x}</code>" for x in ok)
    else:
        msg = "❌ Tidak ada email yang berhasil dibuat."

    if fail:
        msg += f"\n\n⚠️ <b>Gagal:</b> <code>{', '.join(fail)}</code>"

    await q.edit_message_text(msg, parse_mode="HTML")
    context.user_data.clear()

async def show_delete_list(q, context: ContextTypes.DEFAULT_TYPE, zid, domain):
    emails = list_emails(zid)
    if not emails:
        await q.edit_message_text(f"❌ Tidak ada email di {domain}.",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Kembali", callback_data="delete_email")]]))
        return

    rule_map = {}
    buttons = []
    selected = context.user_data.get("selected_multi", set())

    for e in emails:
        rid = e["id"]
        eml = e["email"]
        short_id = hashlib.sha1(rid.encode()).hexdigest()[:8]
        rule_map[short_id] = rid
        mark = "✅" if short_id in selected else "☐"
        cb_data = f"multi:{zid}:{domain}:{short_id}"
        label = f"{eml}  {mark}"
        buttons.append([InlineKeyboardButton(label, callback_data=cb_data)])

    context.user_data["rule_map"] = rule_map
    if selected:
        buttons.append([InlineKeyboardButton("🗑️ Hapus Terpilih", callback_data=f"multi_del:{zid}:{domain}")])
    buttons.append([InlineKeyboardButton("⬅️ Kembali", callback_data="delete_email")])

    await q.edit_message_text(
        f"🗑️ Pilih email yang ingin dihapus dari {domain} (klik untuk memilih):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# =========================
# MAIN
# =========================
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).base_url("http://127.0.0.1:8081/bot").base_file_url("http://127.0.0.1:8081/file/bot").local_mode(True).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(create_many, pattern="^mk:"))
    app.add_handler(CallbackQueryHandler(refresh_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    print("🤖 BOT RUNNING...")
    app.run_polling()


if __name__ == "__main__":
    main()
