"""
VORTE XA CLOUD — Multi-Slot Auto-Run + My Projects
════════════════════════════════════════════════════
Slot 1, 2, 3 ခွဲထားပြီး ဖိုင်ပို့လိုက်တာနဲ့ တန်း Run မယ်။
📁 My Projects ကနေ တစ်ခုချင်း Run/Stop လုပ်လို့ရမယ်။
"""

import os
import sys
import time
import json
import logging
import subprocess
import platform
import zipfile
import shutil
import glob
from datetime import datetime
from flask import Flask, jsonify

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── CONFIGURATION ────────────────────────────────────────────────────────────
API_TOKEN = os.getenv('BOT_TOKEN', '8810710930:AAFf_yQc4WBJlVk9nk9yDQuJsqfyjCGOVL8')
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', '@mgzan201')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID', '7592705124')

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HOST_DIR = os.path.join(BASE_DIR, "hosted_bots")
if not os.path.exists(HOST_DIR):
    os.makedirs(HOST_DIR)
    logger.info(f"Created hosted_bots directory at {HOST_DIR}")

running_processes = {}
start_times = {}
file_names = {}
user_selected_slot = {}
deploy_state = {}

registered_users = set()
user_usernames = {}
pro_users = set()

try:
    import telebot
    from telebot import types
    bot = telebot.TeleBot(API_TOKEN)
    logger.info("TeleBot initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize TeleBot: {e}")
    sys.exit(1)

# ── KEY-FREE ─────────────────────────────────────────────────────────────────
def get_time_balance_string(uid):
    return "♾️ Unlimited (Key-Free Edition) ✅"

def load_data():
    try:
        data_files = ['registered_users.json', 'user_usernames.json', 'pro_users.json']
        for file in data_files:
            if os.path.exists(file):
                with open(file, 'r') as f:
                    data = json.load(f)
                    if file == 'registered_users.json':
                        registered_users.update(data)
                    elif file == 'user_usernames.json':
                        user_usernames.update(data)
                    elif file == 'pro_users.json':
                        pro_users.update(data)
        logger.info("Data loaded successfully")
    except Exception as e:
        logger.error(f"Error loading data: {e}")

def save_data():
    try:
        with open('registered_users.json', 'w') as f:
            json.dump(list(registered_users), f)
        with open('user_usernames.json', 'w') as f:
            json.dump(user_usernames, f)
        with open('pro_users.json', 'w') as f:
            json.dump(list(pro_users), f)
        logger.info("Data saved successfully")
    except Exception as e:
        logger.error(f"Error saving data: {e}")

# ── UI COMPONENTS ────────────────────────────────────────────────────────────
def get_dashboard_markup(uid):
    markup = types.InlineKeyboardMarkup(row_width=3)
    slots_btns = []
    for i in range(1, 4):
        slot_str = str(i)
        is_running = False
        if uid in running_processes and slot_str in running_processes[uid]:
            if running_processes[uid][slot_str].poll() is None:
                is_running = True
        status_dot = "🟢" if is_running else "⚪"
        slots_btns.append(types.InlineKeyboardButton(f"{status_dot} Slot {i}", callback_data=f"select_slot_{i}"))
    markup.add(*slots_btns)

    current_slot = user_selected_slot.get(uid, "1")
    is_current_running = False
    if uid in running_processes and current_slot in running_processes[uid]:
        if running_processes[uid][current_slot].poll() is None:
            is_current_running = True

    has_file = os.path.exists(os.path.join(HOST_DIR, uid, current_slot, "main.py"))
    deploy_btn = types.InlineKeyboardButton(f"📤 Deploy to Slot {current_slot}", callback_data=f"deploy_{current_slot}")

    if is_current_running:
        action_btn = types.InlineKeyboardButton(f"🛑 Stop Slot {current_slot}", callback_data=f"stop_{current_slot}")
    else:
        action_btn = types.InlineKeyboardButton(f"🚀 Launch Slot {current_slot}", callback_data=f"launch_{current_slot}") if has_file else None

    if action_btn:
        markup.add(deploy_btn, action_btn)
    else:
        markup.add(deploy_btn)

    markup.add(
        types.InlineKeyboardButton(f"📋 Logs (Slot {current_slot})", callback_data=f"logs_{current_slot}"),
        types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh")
    )
    markup.add(types.InlineKeyboardButton("🛠 Support", url=f"https://t.me/{ADMIN_USERNAME.replace('@', '')}"))
    return markup

def get_reply_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add('🖥 Dashboard', '📊 Server Status', '🆘 Help Desk')
    markup.add('📁 My Projects')
    return markup

# ── CORE FUNCTIONS ───────────────────────────────────────────────────────────
def launch_bot(uid, slot):
    user_dir = os.path.join(HOST_DIR, uid, slot)
    path = os.path.join(user_dir, "main.py")
    log_path = os.path.join(user_dir, "bot.log")
    
    if not os.path.exists(path):
        return "NO_FILE"
    
    req_path = os.path.join(user_dir, "requirements.txt")
    if os.path.exists(req_path):
        try:
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", req_path], 
                           cwd=user_dir, capture_output=True, timeout=300)
        except Exception as e:
            logger.error(f"Failed to install requirements: {e}")

    try:
        if uid in running_processes and slot in running_processes[uid]:
            if running_processes[uid][slot].poll() is None:
                running_processes[uid][slot].kill()

        log_file = open(log_path, "a")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"

        process = subprocess.Popen(
            [sys.executable, path],
            stderr=log_file,
            stdout=log_file,
            text=True,
            env=env,
            cwd=user_dir
        )

        if uid not in running_processes:
            running_processes[uid] = {}
        if uid not in start_times:
            start_times[uid] = {}

        running_processes[uid][slot] = process
        start_times[uid][slot] = time.time()
        save_data()
        return "SUCCESS"
    except Exception as e:
        logger.error(f"Error launching bot: {e}")
        return "ERROR"

def slot_status(uid, slot):
    if uid in running_processes and slot in running_processes[uid]:
        if running_processes[uid][slot].poll() is None:
            diff = int(time.time() - start_times[uid].get(slot, time.time()))
            days = diff // 86400
            hours = (diff % 86400) // 3600
            minutes = (diff % 3600) // 60
            seconds = diff % 60
            return "🟢 LIVE", f"{days}d {hours}h {minutes}m {seconds}s"
    return "🔴 OFFLINE", "—"

# ── BOT HANDLERS ─────────────────────────────────────────────────────────────
@bot.message_handler(commands=['start'])
def dashboard(message):
    uid = str(message.chat.id)
    username = message.from_user.username if message.from_user.username else "No_Username"

    registered_users.add(uid)
    user_usernames[uid] = f"@{username}"
    save_data()

    if uid not in user_selected_slot:
        user_selected_slot[uid] = "1"

    current_slot = user_selected_slot[uid]
    status_icon, uptime = slot_status(uid, current_slot)

    current_file = "No active project"
    if uid in file_names and current_slot in file_names[uid]:
        current_file = file_names[uid][current_slot]

    active_count = sum(1 for s in (running_processes.get(uid) or {}) if running_processes[uid][s].poll() is None)
    time_left_str = get_time_balance_string(uid)

    dashboard_ui = (
        f"💠 **VORTE XA CLOUD (Multi-Slot)** 💠\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👋 **Welcome, {message.from_user.first_name}!**\n"
        f"🆔 **Client ID:** `{uid}`\n"
        f"🎯 **Selected Slot:** `Slot {current_slot}`\n"
        f"💰 **Balance:** `{time_left_str}`\n\n"
        f"🚀 **INSTANCE STATUS**\n"
        f"┣ Project: `📄 {current_file}`\n"
        f"┣ Status: {status_icon}\n"
        f"┣ Uptime: `{uptime}`\n"
        f"┗ Running: `{active_count} / 3` 🔥\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
    )

    try:
        bot.send_message(message.chat.id, dashboard_ui, reply_markup=get_reply_keyboard(), parse_mode='Markdown')
        bot.send_message(message.chat.id, f"🕹 **Controller (Slot {current_slot}):**", reply_markup=get_dashboard_markup(uid))
    except Exception as e:
        logger.error(f"Error sending dashboard: {e}")

# ── ADMIN COMMANDS ───────────────────────────────────────────────────────────
@bot.message_handler(commands=['userlist'])
def admin_userlist(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return
    if not registered_users:
        bot.send_message(ADMIN_CHAT_ID, "No users yet.")
        return
    msg = "📊 **Registered Users:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for idx, user_id in enumerate(sorted(registered_users), start=1):
        uname = user_usernames.get(user_id, "@No_Username")
        tag = "👑 [OWNER]" if user_id == ADMIN_CHAT_ID else "👤 [USER]"
        msg += f"{idx}. `{user_id}` | {uname} {tag}\n"
    bot.send_message(ADMIN_CHAT_ID, msg, parse_mode='Markdown')

@bot.message_handler(commands=['allmessage'])
def admin_broadcast(message):
    if str(message.chat.id) != ADMIN_CHAT_ID:
        bot.reply_to(message, "❌ Unauthorized.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage: `/allmessage <text>`")
        return
    text = parts[1]
    count = 0
    for user_id in registered_users:
        try:
            bot.send_message(user_id, f"📢 **[ANNOUNCEMENT]**\n\n{text}")
            count += 1
            time.sleep(0.05)
        except Exception:
            continue
    bot.send_message(ADMIN_CHAT_ID, f"✅ Sent to `{count}` users.")

# ── FILE HANDLER (AUTO-RUN per Slot) ─────────────────────────────────────────
@bot.message_handler(content_types=['document'])
def handle_document(message):
    uid = str(message.chat.id)
    slot = deploy_state.get(uid) or user_selected_slot.get(uid, "1")
    user_dir = os.path.join(HOST_DIR, uid, slot)
    
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)
    os.makedirs(user_dir)
    
    file_name = message.document.file_name
    file_path = os.path.join(user_dir, file_name)
    
    try:
        file_info = bot.get_file(message.document.file_id)
        with open(file_path, "wb") as f:
            f.write(bot.download_file(file_info.file_path))
        
        if file_name.endswith(".zip"):
            with zipfile.ZipFile(file_path, 'r') as zip_ref:
                zip_ref.extractall(user_dir)
            os.remove(file_path)
            
            py_files = glob.glob(os.path.join(user_dir, "**", "main.py"), recursive=True)
            if not py_files:
                py_files = glob.glob(os.path.join(user_dir, "**", "*.py"), recursive=True)
            
            if py_files:
                main_script = py_files[0]
                target_main = os.path.join(user_dir, "main.py")
                if main_script != target_main:
                    shutil.move(main_script, target_main)
            else:
                bot.send_message(message.chat.id, "❌ No .py file found in ZIP.")
                return
        else:
            target_main = os.path.join(user_dir, "main.py")
            if file_path != target_main:
                shutil.move(file_path, target_main)
        
        file_names.setdefault(uid, {})[slot] = file_name
        
        try:
            os.chmod(os.path.join(user_dir, "main.py"), 0o755)
        except Exception:
            pass
        
        bot.send_message(
            message.chat.id,
            f"✅ **Upload Successful!**\n\n"
            f"📄 File: `{file_name}`\n"
            f"🎯 Slot: `{slot}`\n"
            f"🚀 **Auto-launching now...**",
            parse_mode='Markdown'
        )
        
        result = launch_bot(uid, slot)
        if result == "SUCCESS":
            bot.send_message(message.chat.id, f"🟢 **Slot {slot} is now RUNNING!**", reply_markup=get_dashboard_markup(uid))
        else:
            bot.send_message(message.chat.id, "❌ **Launch failed.**", reply_markup=get_dashboard_markup(uid))
        if uid in deploy_state:
            del deploy_state[uid]
        save_data()
    except Exception as e:
        logger.error(f"Error handling document: {e}")
        bot.send_message(message.chat.id, "❌ **Upload failed.**")

# ── CALLBACK HANDLERS ────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: True)
def callbacks(call):
    uid = str(call.message.chat.id)

    if call.data.startswith("select_slot_"):
        slot = call.data.split("_")[-1]
        user_selected_slot[uid] = slot
        bot.answer_callback_query(call.id, f"Switched to Slot {slot}")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.delete_message(call.message.chat.id, call.message.message_id - 1)
        except Exception:
            pass
        dashboard(call.message)
        return

    if call.data.startswith("stop_"):
        slot = call.data.split("_")[-1]
        if uid in running_processes and slot in running_processes[uid]:
            if running_processes[uid][slot].poll() is None:
                running_processes[uid][slot].kill()
                bot.send_message(call.message.chat.id, f"🛑 **Slot {slot} stopped.**")
                bot.answer_callback_query(call.id, f"Stopped Slot {slot}")
            else:
                bot.answer_callback_query(call.id, "Already stopped.")
        else:
            bot.answer_callback_query(call.id, "No process in this slot.")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        dashboard(call.message)

    elif call.data.startswith("launch_"):
        slot = call.data.split("_")[-1]
        result = launch_bot(uid, slot)
        if result == "SUCCESS":
            bot.answer_callback_query(call.id, f"🚀 Launching Slot {slot}...")
            dashboard(call.message)
        elif result == "NO_FILE":
            bot.answer_callback_query(call.id, "❌ No file in this slot.", show_alert=True)
            bot.send_message(call.message.chat.id, f"⚠️ **Slot {slot} မှာ ဖိုင် မရှိပါ။**")
        else:
            bot.answer_callback_query(call.id, "❌ Launch failed.")

    elif call.data == "refresh":
        bot.answer_callback_query(call.id, "Refreshing...")
        dashboard(call.message)

    elif call.data == "refresh_projects":
        bot.answer_callback_query(call.id, "Refreshing projects...")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        # Projects ကို ပြန်ပြ
        message = call.message
        message.text = '📁 My Projects'
        handle_text(message)

    elif call.data == "go_dashboard":
        bot.answer_callback_query(call.id, "Going to Dashboard...")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        dashboard(call.message)

    elif call.data.startswith("deploy_"):
        slot = call.data.split("_")[-1]
        deploy_state[uid] = slot
        user_selected_slot[uid] = slot
        bot.answer_callback_query(call.id, f"Ready for Slot {slot}")
        bot.send_message(call.message.chat.id, f"📤 **Upload .py or .zip for Slot {slot}.**")

    elif call.data.startswith("logs_"):
        slot = call.data.split("_")[-1]
        log_path = os.path.join(HOST_DIR, uid, slot, "bot.log")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                last_logs = "".join(lines[-30:]) if lines else "Empty log."
            bot.send_message(call.message.chat.id, f"📋 **Logs (Slot {slot}):**\n```\n{last_logs}\n```", parse_mode='Markdown')
        else:
            bot.send_message(call.message.chat.id, f"❌ No logs for Slot {slot}.")

# ── TEXT HANDLERS ────────────────────────────────────────────────────────────
@bot.message_handler(content_types=['text'])
def handle_text(message):
    uid = str(message.chat.id)
    username = message.from_user.username if message.from_user.username else "No_Username"
    registered_users.add(uid)
    user_usernames[uid] = f"@{username}"

    if uid not in user_selected_slot:
        user_selected_slot[uid] = "1"

    if message.text == '🖥 Dashboard':
        dashboard(message)
    elif message.text == '📊 Server Status':
        active_global = sum(1 for u in running_processes for s in running_processes[u] if running_processes[u][s].poll() is None)
        bot.send_message(
            message.chat.id,
            f"📊 **Server Status**\n"
            f"┣ Node: `Stable` ✅\n"
            f"┣ Python: `{platform.python_version()}`\n"
            f"┗ Global: `{active_global}` live"
        )
    elif message.text == '📁 My Projects':
        projects_text = "📂 **Your Projects:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for s in ["1", "2", "3"]:
            st_icon, st_uptime = slot_status(uid, s)
            fname = file_names.get(uid, {}).get(s, "No file")
            projects_text += f"┣ **Slot {s}:** {st_icon} | `{fname}` | {st_uptime}\n"
            
            if st_icon == "🟢 LIVE":
                btn = types.InlineKeyboardButton(f"🛑 Stop Slot {s}", callback_data=f"stop_{s}")
            else:
                has_file = os.path.exists(os.path.join(HOST_DIR, uid, s, "main.py"))
                if has_file:
                    btn = types.InlineKeyboardButton(f"🚀 Launch Slot {s}", callback_data=f"launch_{s}")
                else:
                    btn = types.InlineKeyboardButton(f"📤 Deploy Slot {s}", callback_data=f"deploy_{s}")
            markup.add(btn)
        
        markup.add(types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_projects"))
        markup.add(types.InlineKeyboardButton("🖥 Dashboard", callback_data="go_dashboard"))
        
        bot.send_message(message.chat.id, projects_text, reply_markup=markup, parse_mode='Markdown')
    elif message.text == '🆘 Help Desk':
        bot.send_message(
            message.chat.id,
            f"🆘 **Help Desk**\n━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📤 **Upload:** Slot တစ်ခုကို ရွေးပြီး ဖိုင် ပို့ပါ (Auto-run)\n"
            f"🛑 **Stop:** ရပ်ချင်တဲ့ Slot ကို ရွေးပြီး Stop နှိပ်\n"
            f"🚀 **Launch:** ပြန် Run ချင်ရင် Launch နှိပ်\n"
            f"📋 **Logs:** Slot အလိုက် Logs ကြည့်\n"
            f"📁 **My Projects:** Run ထားတဲ့ Project တွေ ကြည့်ရန်\n\n"
            f"💬 Support: {ADMIN_USERNAME}"
        )
    else:
        if not (message.text or "").startswith('/'):
            bot.send_message(
                message.chat.id,
                f"👋 @ {username}\nခလုတ်များကို သုံးပါ။",
                reply_markup=get_reply_keyboard()
            )

@app.route('/health')
def health():
    return jsonify({"status": "ok", "time": datetime.now().isoformat()})

# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    load_data()
    logger.info("VORTE XA Multi-Slot + My Projects starting...")
    try:
        me = bot.get_me()
        logger.info(f"Bot authenticated: @{me.username}")
    except Exception as e:
        logger.error(f"Bot auth failed: {e}")
    logger.info("Starting long polling...")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)