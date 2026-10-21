import logging
import asyncio
import math
import time
import io
import html
import json
import os
import string
import secrets
import urllib.parse
from datetime import datetime, timezone
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ==================== SETTINGS ====================
BOT_TOKEN = "8651415048:AAFxOLQyvHk2d9l43aTBrDO6bBXb2flA5kM"
PROXYSCRAPE_API_KEY = "czDaKHXdjCKRWuo1NtQOHbmOgYMqCD0UGWYgfWsHB1PdNtLIvc0oYIGk0RIpih4B"

CONCURRENCY = 1000
HTTP_CHECK_TIMEOUT_SECONDS = 5.0
SOCKS_CHECK_TIMEOUT_SECONDS = 6.0
PROXY_CHECK_HARD_TIMEOUT_SECONDS = 8.0

MAX_SINGLE_SCAN_CANDIDATES = 500000
MAX_ALL_SCAN_CANDIDATES = 1000000
FAST_PROXY_TARGET = 5000
FAST_PROXY_MAX_LATENCY_MS = 4000
SCAN_BATCH_SIZE = 5000

PROXY_SOURCE_CONCURRENCY = 300
PROXY_SOURCE_TIMEOUT_SECONDS = 8.0
PROXY_SOURCE_LIMIT = 500000
# ==================================================

# ==================== ACCESS CONTROL ====================
ADMIN_ID = 6537847588
ACTIVE_KEYS = {}
USER_KEYS = {}
KEY_DURATIONS = {
    "1h": 60 * 60, "2h": 2 * 60 * 60, "1d": 24 * 60 * 60,
    "7d": 7 * 24 * 60 * 60, "30d": 30 * 24 * 60 * 60,
}
KEY_STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proxycheck_keys.json")
SOURCE_STATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "source_stats.json")

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

def load_key_store():
    try:
        with open(KEY_STORE_PATH, "r", encoding="utf-8") as f:
            payload = json.load(f)
        ACTIVE_KEYS.update(payload.get("active_keys", {}))
        USER_KEYS.update({int(uid): key for uid, key in payload.get("user_keys", {}).items()})
    except Exception:
        pass
    expire_stale_keys()

def save_key_store():
    payload = {"active_keys": ACTIVE_KEYS, "user_keys": {str(uid): key for uid, key in USER_KEYS.items()}}
    try:
        with open(KEY_STORE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def expire_stale_keys(now=None):
    now = time.time() if now is None else now
    changed = False
    for key, info in list(ACTIVE_KEYS.items()):
        if float(info.get("expires_at", 0)) <= now:
            user_id = info.get("user_id")
            if user_id is not None and USER_KEYS.get(int(user_id)) == key:
                USER_KEYS.pop(int(user_id), None)
            ACTIVE_KEYS.pop(key, None)
            changed = True
    if changed:
        save_key_store()

def load_source_stats():
    try:
        with open(SOURCE_STATS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_source_stats(stats):
    try:
        with open(SOURCE_STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)
    except Exception:
        pass

def record_source_result(url, count):
    stats = load_source_stats()
    entry = stats.get(url, {"ok": 0, "fail": 0, "last_count": 0})
    if count > 0:
        entry["ok"] += 1
        entry["last_count"] = count
    else:
        entry["fail"] += 1
    entry["last_ts"] = int(time.time())
    stats[url] = entry
    save_source_stats(stats)

load_key_store()

scanning_jobs = {}
scan_tasks = {}
user_selected_type = {}
stop_events = {} # ⭐ ချက်ချင်းရပ်ဖို့ Event သုံးမယ်

def is_admin(user_id: int) -> bool:
    return int(user_id) == int(ADMIN_ID) and int(ADMIN_ID) != 0

def is_authorized(user_id: int) -> bool:
    if is_admin(user_id): return True
    expire_stale_keys()
    key = USER_KEYS.get(int(user_id))
    return bool(key and ACTIVE_KEYS.get(key) and float(ACTIVE_KEYS[key].get("expires_at", 0)) > time.time())

def generate_access_key(length=12) -> str:
    alphabet = string.ascii_uppercase + string.digits
    raw = ''.join(secrets.choice(alphabet) for _ in range(length))
    return '-'.join(raw[i:i+4] for i in range(0, length, 4))

# ==================== UI MARKUPS ====================
def access_denied_markup():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔐✨  ENTER ACCESS KEY  ✨🔑", callback_data="enter_key")]])

def admin_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲🔥  CREATE KEY", callback_data="admin_generate_key"), InlineKeyboardButton("🗝️💎  ALL KEYS", callback_data="admin_list_keys")],
        [InlineKeyboardButton("👥✨  USERS", callback_data="admin_list_users"), InlineKeyboardButton("📊🚀  CONTROL", callback_data="admin_panel")],
        [InlineKeyboardButton("🏠🌌  BACK TO MAIN MENU", callback_data="back_home")],
    ])

def key_duration_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ 1 HOUR", callback_data="admin_duration_1h"), InlineKeyboardButton("🔥 2 HOURS", callback_data="admin_duration_2h")],
        [InlineKeyboardButton("🌟 1 DAY", callback_data="admin_duration_1d"), InlineKeyboardButton("💎 7 DAYS", callback_data="admin_duration_7d")],
        [InlineKeyboardButton("👑 30 DAYS", callback_data="admin_duration_30d")],
        [InlineKeyboardButton("↩️  ADMIN CONTROL", callback_data="admin_panel")],
    ])

def main_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐⚡  HTTP", callback_data="select_http"), InlineKeyboardButton("🔒💠  HTTPS", callback_data="select_https")],
        [InlineKeyboardButton("🔵🛰️  SOCKS4", callback_data="select_socks4"), InlineKeyboardButton("🟣🚀  SOCKS5", callback_data="select_socks5")],
        [InlineKeyboardButton("🔐  AUTH PROXY ONLY  🔐", callback_data="select_auth")],
        [InlineKeyboardButton("🔥🌌  SCAN ALL TYPES  🌌🔥", callback_data="select_all")],
        [InlineKeyboardButton("📝  CHECK PASTED LIST", callback_data="manual_check")],
        [InlineKeyboardButton("📖💡  HOW TO USE", callback_data="help")],
    ])

# ==================== PARSING & LOGIC ====================
_PROXY_SCHEME_TO_TYPE = {"http": "http", "https": "https", "socks4": "socks4", "socks5": "socks5", "socks5h": "socks5"}

def _normalize_proxy_candidate(raw_proxy, source_protocol="mixed", requested_protocol="all"):
    proxy = raw_proxy.strip()
    if not proxy or proxy.startswith("#"): return None

    if isinstance(proxy, dict):
        ip = proxy.get("ip"); port = proxy.get("port")
        if not ip or not port: return None
        user = proxy.get("username") or proxy.get("user")
        pw = proxy.get("password") or proxy.get("pass")
        auth = f"{user}:{pw}@" if user and pw else ""
        scheme = (proxy.get("protocols") or [proxy.get("protocol", "http")])[0]
        proxy = f"{scheme}://{auth}{ip}:{port}"

    if "@" in proxy and "://" not in proxy:
        proxy = f"http://{proxy}"

    if "://" not in proxy:
        parts = proxy.split(":")
        if len(parts) == 4 and parts[0].count(".") == 3:
            ip, port, user, pw = parts
            proxy = f"http://{user}:{pw}@{ip}:{port}"
        else:
            proxy = f"{source_protocol if source_protocol != 'mixed' else 'http'}://{proxy}"

    try:
        parsed = urllib.parse.urlparse(proxy)
        scheme = parsed.scheme.lower()
        if scheme not in _PROXY_SCHEME_TO_TYPE: return None

        if requested_protocol not in ("all", "auth"):
            if _PROXY_SCHEME_TO_TYPE[scheme] != requested_protocol:
                if not (requested_protocol == "socks5" and scheme == "socks5h"): return None

        host = parsed.hostname; port = parsed.port
        if not host or not port: return None

        auth = ""
        if parsed.username and parsed.password:
            auth = f"{parsed.username}:{parsed.password}@"
        return f"{scheme}://{auth}{host}:{port}"
    except Exception:
        return None

async def get_geoip(session, ip):
    try:
        async with session.get(f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=2.0) as r:
            if r.status == 200:
                data = await r.json()
                cc = data.get("countryCode")
                if cc:
                    return "".join(chr(ord(c) + 127397) for c in cc.upper())
    except Exception:
        pass
    return "🌍"

# ⭐ 4-Pass Check Function
async def check_proxy_alive_with_ping(session, proxy, proxy_type="http"):
    start_time = time.monotonic()
    scheme = proxy.partition("://")[0].lower()
    try:
        if scheme in ("socks4", "socks5", "socks5h"):
            from aiohttp_socks import ProxyConnector
            timeout = aiohttp.ClientTimeout(total=SOCKS_CHECK_TIMEOUT_SECONDS)
            connector = ProxyConnector.from_url(proxy)
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as socks_session:
                async with socks_session.get("https://www.google.com/generate_204") as resp:
                    if 200 <= resp.status < 400:
                        return True, math.ceil((time.monotonic() - start_time) * 1000)
        else:
            test_url = "https://www.google.com/generate_204" if scheme == "https" else "http://www.google.com/generate_204"
            async with session.get(test_url, proxy=proxy, timeout=HTTP_CHECK_TIMEOUT_SECONDS) as resp:
                if 200 <= resp.status < 400:
                    return True, math.ceil((time.monotonic() - start_time) * 1000)
    except Exception:
        pass
    return False, 0

# ==================== MASSIVE SOURCE REGISTRY ====================
PROXY_SOURCE_REGISTRY = [
    # ---------- PROXYSCRAPE v4 (plain) ----------
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=text", "http", "plain"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=text&ssl=yes", "https", "plain"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks4&proxy_format=protocolipport&format=text", "socks4", "plain"),
    ("https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&proxy_format=protocolipport&format=text", "socks5", "plain"),

    # ---------- PROXYSCRAPE v2 (premium auth) ----------
    (f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&auth={PROXYSCRAPE_API_KEY}", "http", "auth"),
    (f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks4&auth={PROXYSCRAPE_API_KEY}", "socks4", "auth"),
    (f"https://api.proxyscrape.com/v2/?request=displayproxies&protocol=socks5&auth={PROXYSCRAPE_API_KEY}", "socks5", "auth"),
    (f"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=ipport&format=json&auth={PROXYSCRAPE_API_KEY}", "http", "json"),
    (f"https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&protocol=socks5&proxy_format=ipport&format=json&auth={PROXYSCRAPE_API_KEY}", "socks5", "json"),

    # ---------- TheSpeedX ----------
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt", "socks5", "plain"),

    # ---------- monosans ----------
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt", "socks5", "plain"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies_anonymous/socks5.txt", "socks5", "plain"),
    ("https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/all.txt", "mixed", "plain"),

    # ---------- proxifly ----------
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/https/data.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks4/data.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt", "socks5", "plain"),
    ("https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/all/data.txt", "mixed", "plain"),

    # ---------- gfpcom (auth-capable) ----------
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_plain_http.txt", "http", "auth"),
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_plain_https.txt", "https", "auth"),
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_plain_socks4.txt", "socks4", "auth"),
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_plain_socks5.txt", "socks5", "auth"),
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_protocol_http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_protocol_socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/gfpcom/free-proxy-list/main/list/format_protocol_socks5.txt", "socks5", "plain"),

    # ---------- vakhov ----------
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/https.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/vakhov/fresh-proxy-list/master/socks5.txt", "socks5", "plain"),

    # ---------- ErcinDedeoglu ----------
    ("https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/https.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/ErcinDedeoglu/proxies/main/proxies/socks5.txt", "socks5", "plain"),

    # ---------- zloi-user ----------
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/https.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/zloi-user/hideip.me/main/socks5.txt", "socks5", "plain"),

    # ---------- roosterkid ----------
    ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS4_RAW.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/roosterkid/openproxylist/main/SOCKS5_RAW.txt", "socks5", "plain"),

    # ---------- clarketm ----------
    ("https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt", "http", "plain"),

    # ---------- proxyspace ----------
    ("https://proxyspace.pro/http.txt", "http", "plain"),
    ("https://proxyspace.pro/https.txt", "https", "plain"),
    ("https://proxyspace.pro/socks4.txt", "socks4", "plain"),
    ("https://proxyspace.pro/socks5.txt", "socks5", "plain"),

    # ---------- geonode JSON ----------
    ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps", "http", "json"),
    ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=2&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps", "http", "json"),
    ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=socks4%2Csocks5", "socks5", "json"),
    ("https://proxylist.geonode.com/api/proxy-list?limit=500&page=2&sort_by=lastChecked&sort_type=desc&protocols=socks4%2Csocks5", "socks5", "json"),

    # ---------- openproxylist.xyz ----------
    ("https://openproxylist.xyz/http.txt", "http", "plain"),
    ("https://openproxylist.xyz/socks4.txt", "socks4", "plain"),
    ("https://openproxylist.xyz/socks5.txt", "socks5", "plain"),

    # ---------- proxyscan.io ----------
    ("https://www.proxyscan.io/download?type=http", "http", "plain"),
    ("https://www.proxyscan.io/download?type=https", "https", "plain"),
    ("https://www.proxyscan.io/download?type=socks4", "socks4", "plain"),
    ("https://www.proxyscan.io/download?type=socks5", "socks5", "plain"),

    # ---------- proxy-list.download ----------
    ("https://www.proxy-list.download/api/v1/get?type=http", "http", "plain"),
    ("https://www.proxy-list.download/api/v1/get?type=https", "https", "plain"),
    ("https://www.proxy-list.download/api/v1/get?type=socks4", "socks4", "plain"),
    ("https://www.proxy-list.download/api/v1/get?type=socks5", "socks5", "plain"),

    # ---------- ShiftyTR ----------
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/https.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/socks5.txt", "socks5", "plain"),

    # ---------- hookzof ----------
    ("https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt", "socks5", "plain"),

    # ---------- mmpx12 ----------
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/https.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/mmpx12/proxy-list/master/socks5.txt", "socks5", "plain"),

    # ---------- sunny9577 ----------
    ("https://raw.githubusercontent.com/sunny9577/proxy-scraper/master/proxies.txt", "mixed", "plain"),

    # ---------- jetkai ----------
    ("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt", "http", "plain"),
    ("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt", "https", "plain"),
    ("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks4.txt", "socks4", "plain"),
    ("https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-socks5.txt", "socks5", "plain"),
]

# ==================== SCAN RUNNERS ====================
async def run_manual_scan(msg, context, chat_id, raw_text):
    stop_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP SCAN", callback_data="stop_scan")]])
    proxies = []
    for line in raw_text.splitlines():
        p = _normalize_proxy_candidate(line, "mixed", "all")
        if p: proxies.append(p)

    total = len(proxies)
    if total == 0:
        await msg.edit_text("⚠️ No valid proxies found in your text.")
        return

    await msg.edit_text(f"🌌🚀 <b>CHECKING CUSTOM LIST (4-PASS)</b>\n📦 Total: {total}", parse_mode=ParseMode.HTML, reply_markup=stop_keyboard)

    checked = 0
    found = 0
    found_proxy_records = []
    semaphore = asyncio.Semaphore(CONCURRENCY)
    start_time = time.time()
    
    if chat_id in stop_events: stop_events[chat_id].clear()
    else: stop_events[chat_id] = asyncio.Event()

    async def worker(proxy, session):
        nonlocal checked, found
        if stop_events[chat_id].is_set(): return
        
        async with semaphore:
            # ⭐ ၄ ကြိမ် စစ်မယ်
            is_ok = False
            ping = 0
            for _ in range(4):
                if stop_events[chat_id].is_set(): break
                try:
                    is_ok, ping = await asyncio.wait_for(check_proxy_alive_with_ping(session, proxy, "all"), timeout=PROXY_CHECK_HARD_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    is_ok, ping = False, 0
                
                if not is_ok: break # တစ်ခါမှ မှားရင် ချက်ချင်း ပစ်

            checked += 1
            if is_ok:
                host = proxy.split("@")[-1].split("://")[-1].split(":")[0]
                flag = await get_geoip(session, host)
                found += 1
                found_proxy_records.append((ping, proxy, flag))

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=CONCURRENCY)) as session:
        tasks = [worker(p, session) for p in proxies]
        await asyncio.gather(*tasks)

    if stop_events[chat_id].is_set():
        await msg.edit_text("🛑 Scan stopped by user.")
        return

    if found_proxy_records:
        found_proxy_records.sort()
        text = f"✅ <b>FINISHED (4-PASS VERIFIED)</b>\nChecked: {checked}\nLive: <b>{found}</b>\n\n"
        for ping, p, flag in found_proxy_records[:100]:
            text += f"• <code>{html.escape(p)}</code> · {ping} ms · {flag}\n"

        file_content = "\n".join(proxy for ping, proxy, flag in found_proxy_records)
        file_bytes = io.BytesIO(file_content.encode("utf-8"))
        file_bytes.name = "manual_live_proxies.txt"

        await msg.edit_text(text[:4000], parse_mode=ParseMode.HTML)
        if len(text) > 4000:
            await context.bot.send_message(chat_id, text[4000:], parse_mode=ParseMode.HTML)

        await context.bot.send_document(chat_id, file_bytes, caption=f"✅ {len(found_proxy_records)} live proxies")
    else:
        await msg.edit_text("❌ No live proxies found in your list.")


async def run_proxy_scan(query, context, chat_id, proxy_type):
    try:
        display_name = "AUTH ONLY" if proxy_type == "auth" else ("ALL" if proxy_type == "all" else proxy_type.upper())
        stop_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP SCAN", callback_data="stop_scan")]])

        try:
            await query.edit_message_text(f"🌌⚡ <b>NEBULA · PIPELINE SCAN</b> ⚡🌌\n📡 Mode: <b>{display_name}</b>\n⏳ Starting pipeline...", parse_mode=ParseMode.HTML, reply_markup=stop_keyboard)
        except Exception: pass

        proxy_queue = asyncio.Queue(maxsize=50000)
        
        if chat_id in stop_events: stop_events[chat_id].clear()
        else: stop_events[chat_id] = asyncio.Event()
            
        stats = {"sourced": 0, "checked": 0, "found": 0}
        found_proxy_records = []
        formatted_items = []
        start_time = time.time()
        speed_history = []

        async def source_producer(session):
            registry = PROXY_SOURCE_REGISTRY
            if proxy_type not in ("all", "auth"):
                registry = [s for s in registry if s[1] == proxy_type]

            sem = asyncio.Semaphore(PROXY_SOURCE_CONCURRENCY)
            timeout = aiohttp.ClientTimeout(total=PROXY_SOURCE_TIMEOUT_SECONDS, connect=5.0)
            limit_count = MAX_ALL_SCAN_CANDIDATES if proxy_type in ("all", "auth") else MAX_SINGLE_SCAN_CANDIDATES

            async def fetch_and_enqueue(url, default_proto, category):
                if stop_events[chat_id].is_set(): return
                async with sem:
                    try:
                        async with session.get(url, timeout=timeout) as res:
                            if res.status != 200: return
                            text = await res.text()
                            
                            result = []
                            if category == "json" or text.lstrip().startswith("{"):
                                try:
                                    data = json.loads(text)
                                    items = data.get("data", data) if isinstance(data, dict) else data
                                    if isinstance(items, list):
                                        for item in items:
                                            if isinstance(item, dict):
                                                ip, port = item.get("ip"), item.get("port")
                                                if ip and port:
                                                    proto = (item.get("protocols") or [default_proto])[0]
                                                    user = item.get("username") or item.get("user")
                                                    pw = item.get("password") or item.get("pass")
                                                    auth = f"{user}:{pw}@" if user and pw else ""
                                                    result.append(f"{proto}://{auth}{ip}:{port}")
                                except json.JSONDecodeError: pass
                            else:
                                for line in text.splitlines():
                                    p = _normalize_proxy_candidate(line, default_proto, "all")
                                    if p: result.append(p)

                            record_source_result(url, len(result))
                            
                            for p in result:
                                if stop_events[chat_id].is_set(): break
                                if stats["sourced"] >= limit_count: break
                                await proxy_queue.put(p)
                                stats["sourced"] += 1
                    except Exception as e:
                        logger.debug(f"Source fail: {e}")

            tasks = [fetch_and_enqueue(url, proto, cat) for url, proto, cat in registry]
            await asyncio.gather(*tasks)
            
            for _ in range(CONCURRENCY):
                await proxy_queue.put(None)

        async def proxy_worker(session):
            while not stop_events[chat_id].is_set():
                try:
                    proxy = await asyncio.wait_for(proxy_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                if proxy is None:
                    proxy_queue.task_done()
                    break
                
                if proxy_type == "auth" and "@" not in proxy:
                    stats["checked"] += 1
                    proxy_queue.task_done()
                    continue

                # ⭐ ၄ ကြိမ် စစ်မယ်
                is_ok = False
                ping = 0
                for _ in range(4):
                    if stop_events[chat_id].is_set(): break
                    try:
                        is_ok, ping = await asyncio.wait_for(
                            check_proxy_alive_with_ping(session, proxy, proxy_type), 
                            timeout=PROXY_CHECK_HARD_TIMEOUT_SECONDS
                        )
                    except asyncio.TimeoutError:
                        is_ok, ping = False, 0
                    
                    if not is_ok: break

                stats["checked"] += 1
                if is_ok and 0 < ping <= FAST_PROXY_MAX_LATENCY_MS:
                    host = proxy.split("@")[-1].split("://")[-1].split(":")[0]
                    flag = await get_geoip(session, host)
                    stats["found"] += 1
                    found_proxy_records.append((ping, proxy, flag))
                    formatted_items.append((ping, f"• <code>{proxy}</code> · {ping}ms · {flag} · 4/4"))
                
                proxy_queue.task_done()

        async def ui_updater(msg):
            while not stop_events[chat_id].is_set():
                await asyncio.sleep(3.5)
                if stop_events[chat_id].is_set(): break
                
                elapsed = time.time() - start_time
                current_speed = int(stats["checked"] / elapsed) if elapsed > 0 else 0
                
                speed_history.append(current_speed)
                if len(speed_history) > 3:
                    speed_history.pop(0)
                avg_speed = sum(speed_history) // len(speed_history) if speed_history else 0

                header = (
                    f"🌐 KYAWZIN PROXY · PIPELINE (4-PASS)\n"
                    f"🛰 Mode: {display_name}\n"
                    f"📥 Sourced: {stats['sourced']:,} | 📦 Checked: {stats['checked']:,}\n"
                    f"⚡ Speed: {avg_speed:,}/s | ✅ Live: {stats['found']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                )
                
                temp = []
                current_len = len(header)
                for _, item in sorted(formatted_items, key=lambda r: r[0])[:20]:
                    item_len = len(item) + 1
                    if current_len + item_len < 3800:
                        temp.append(item)
                        current_len += item_len
                
                box = "\n".join(temp) if temp else "<i>Waiting for proxies…</i>"
                try:
                    await msg.edit_text(header + box, parse_mode=ParseMode.HTML, reply_markup=stop_keyboard)
                except Exception:
                    pass

        connector = aiohttp.TCPConnector(
            limit=CONCURRENCY,
            limit_per_host=0,
            ttl_dns_cache=300,
            force_close=False,
            enable_cleanup_closed=True
        )
        async with aiohttp.ClientSession(connector=connector) as session:
            msg = await query.edit_message_text("⏳ Starting pipeline engine...", reply_markup=stop_keyboard)
            
            ui_task = asyncio.create_task(ui_updater(msg))
            producer_task = asyncio.create_task(source_producer(session))
            worker_tasks = [asyncio.create_task(proxy_worker(session)) for _ in range(CONCURRENCY)]
            
            await producer_task
            
            await asyncio.gather(*worker_tasks)
            
            stop_events[chat_id].set()
            ui_task.cancel()

        if stop_events[chat_id].is_set():
             await msg.edit_text("🛑 Scan stopped by user.")
             return

        ordered_proxy_results = sorted(found_proxy_records, key=lambda r: r[0])
        
        final_text = (
            f"🌌 <b>NEBULA · PIPELINE COMPLETE (4-PASS)</b>\n"
            f"📥 Sourced: {stats['sourced']:,}\n"
            f"📦 Checked: {stats['checked']:,}\n"
            f"✅ Qualified: <b>{stats['found']}</b>\n"
            f"📊 Total Time: {int(time.time() - start_time)}s"
        )
        try: 
            await msg.edit_text(final_text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Menu", callback_data="back_home")]]))
        except Exception: pass

        if ordered_proxy_results:
            file_content = "\n".join(proxy for ping, proxy, flag in ordered_proxy_results)
            file_bytes = io.BytesIO(file_content.encode("utf-8"))
            file_bytes.name = f"proxy_{proxy_type}.txt"
            try:
                await context.bot.send_document(chat_id=chat_id, document=file_bytes, caption=f"📁 Live proxies: <b>{len(ordered_proxy_results)}</b> (4-Pass Verified)", parse_mode=ParseMode.HTML)
            except Exception: pass

    except Exception as e:
        logger.exception("Pipeline scan failed")
        try: await query.edit_message_text(f"❌ Scan failed: {e}")
        except Exception: pass
    finally:
        scanning_jobs[chat_id] = False


# ==================== HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id):
        text = "🔐 <b>ACCESS REQUIRED</b>"
        if update.message:
            await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=access_denied_markup())
        else:
            await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=access_denied_markup())
        return
    text = "🌌✨ <b>NEBULA PROXY SCANNER</b> ✨🌌\n🛰️ Choose your proxy mode below."
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_markup())
    else:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_markup())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_authorized(user_id): return
    text = update.message.text.strip()

    if context.user_data.get("awaiting_key"):
        context.user_data["awaiting_key"] = False
        key = text.upper()
        expire_stale_keys()
        if key not in ACTIVE_KEYS:
            await update.message.reply_text("❌ Invalid key.", reply_markup=access_denied_markup())
            return
        ACTIVE_KEYS[key]["user_id"] = user_id
        USER_KEYS[user_id] = key
        save_key_store()
        await update.message.reply_text("✅ Access granted.", reply_markup=main_menu_markup())
        return

    if context.user_data.get("awaiting_manual_proxies"):
        context.user_data["awaiting_manual_proxies"] = False
        scanning_jobs[user_id] = True
        msg = await update.message.reply_text("🔍 Parsing and checking list...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 STOP", callback_data="stop_scan")]]))
        asyncio.create_task(run_manual_scan(msg, context, user_id, text))
        return

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    try: await query.answer()
    except Exception: pass

    if data == "manual_check":
        if not is_authorized(chat_id): return
        context.user_data["awaiting_manual_proxies"] = True
        await query.edit_message_text("📝 <b>PASTE PROXY LIST</b>\n\nSend a message with 1 proxy per line.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ CANCEL", callback_data="back_home")]]))
        return

    if data == "enter_key":
        context.user_data["awaiting_key"] = True
        await query.edit_message_text("🔐 <b>ENTER ACCESS KEY</b>\n\nSend your key as a message.", parse_mode=ParseMode.HTML)
        return

    if not is_authorized(chat_id):
        await query.edit_message_text("🔐 ACCESS REQUIRED", reply_markup=access_denied_markup())
        return

    if data.startswith("select_"):
        proxy_type = data.split("_")[1]
        user_selected_type[chat_id] = proxy_type
        display_name = "AUTH ONLY" if proxy_type == "auth" else ("ALL" if proxy_type == "all" else proxy_type.upper())
        keyboard = [[InlineKeyboardButton("🚀🔥  START SCAN  🔥🚀", callback_data="start_scan")], [InlineKeyboardButton("🏠🌌  MAIN MENU", callback_data="back_home")]]
        try: await query.edit_message_text(f"🌌 <b>NEBULA SCANNER</b>\n📡 Selected mode: <b>{display_name}</b>\n\nReady when you are. Tap <b>START SCAN</b> to begin.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception: pass

    elif data == "start_scan":
        active_task = scan_tasks.get(chat_id)
        if active_task is not None and not active_task.done():
            await query.answer("A scan is already running.", show_alert=True)
            return
        proxy_type = user_selected_type.get(chat_id, "all")
        scanning_jobs[chat_id] = True

        async def run_guarded_scan():
            try:
                await run_proxy_scan(query, context, chat_id, proxy_type)
            finally:
                scanning_jobs[chat_id] = False
                scan_tasks.pop(chat_id, None)

        scan_tasks[chat_id] = asyncio.create_task(run_guarded_scan())

    elif data == "stop_scan":
        # ⭐ ဒီနေရာမှာ Event ကို set လုပ်လိုက်တာနဲ့ ချက်ချင်း ရပ်သွားမယ်
        if chat_id in stop_events:
            stop_events[chat_id].set()
        scanning_jobs[chat_id] = False
        
        # Queue ထဲက အမှိုက်တွေ ရှင်းမယ်
        try:
            while not proxy_queue.empty():
                proxy_queue.get_nowait()
                proxy_queue.task_done()
        except: pass

        try: await query.edit_message_text("🛑 <b>SCAN STOPPED</b>\nAll pending checks cancelled.", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️ BACK", callback_data="back_home")]]))
        except Exception: pass

    elif data == "back_home":
        if chat_id in stop_events:
            stop_events[chat_id].set()
        scanning_jobs[chat_id] = False
        try: await query.edit_message_text("🌌 <b>NEBULA</b>\n📡 Choose a protocol.", parse_mode=ParseMode.HTML, reply_markup=main_menu_markup())
        except Exception: pass

    elif data == "help":
        try: await query.edit_message_text("📖 <b>HOW TO USE (4-PASS)</b>\n1. Choose protocol or Auth mode.\n2. Tap START SCAN.\n3. Wait for results (4x Checked + GeoIP).", parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩️  BACK", callback_data="back_home")]]))
        except Exception: pass

def main():
    from telegram.request import HTTPXRequest
    bot_request = HTTPXRequest(connection_pool_size=50, read_timeout=20.0, write_timeout=20.0)
    updates_request = HTTPXRequest(connection_pool_size=1, read_timeout=35.0)
    app = Application.builder().token(BOT_TOKEN).request(bot_request).get_updates_request(updates_request).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    print("🤖 Proxy Scanner Bot Running... (4-Pass + Instant Stop)")
    app.run_polling(timeout=15, drop_pending_updates=True)

if __name__ == "__main__":
    main()