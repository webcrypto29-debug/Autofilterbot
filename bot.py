import os
import time
import asyncio
import datetime
import requests
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# --- Web Server (Keep-Alive for Render / UptimeRobot) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "24h Token Auto Filter Bot Active & Running!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- Configuration (Environment Variables) ---
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI", "YOUR_MONGO_URI")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))  # आपकी Telegram User ID

# --- Database Setup ---
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["AutoFilterDB"]
files_col = db["files"]
users_col = db["users"]
settings_col = db["settings"] # Dynamic Shortener Settings Store करने के लिए

# --- Helper: Get Dynamic Shortener Settings from DB ---
def get_shortener_settings():
    settings = settings_col.find_one({"type": "shortener"})
    if settings:
        return settings.get("url", ""), settings.get("api", ""), settings.get("status", True)
    # Default Render Env
    return os.environ.get("SHORTENER_URL", ""), os.environ.get("SHORTENER_API", ""), True

# --- Helper: URL Shortener API Call ---
def get_shortlink(url):
    s_url, s_api, status = get_shortener_settings()
    if not status or not s_api or not s_url:
        return url
    try:
        api_url = f"https://{s_url}/api?api={s_api}&url={url}"
        res = requests.get(api_url, timeout=5).json()
        if res.get("status") == "success":
            return res.get("shortlink")
        return url
    except Exception as e:
        print(f"Shortener Error: {e}")
        return url

# --- Helper: 24-Hour Token Verification Check ---
def is_user_verified(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return False
    
    last_verified = user.get("verified_at")
    if not last_verified:
        return False
    
    now = datetime.datetime.utcnow()
    time_diff = (now - last_verified).total_seconds()
    if time_diff < 86400:  # 24 Hours
        return True
    return False

# --- Bot Client ---
app = Client("AutoFilterBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Admin Dynamic Shortener Commands ---

@app.on_message(filters.command("set_shortener") & filters.user(ADMIN_ID))
async def set_shortener_cmd(client, message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ **Usage:** `/set_shortener gplinks.in`")
        return
    
    s_url = message.command[1].strip().replace("https://", "").replace("http://", "")
    settings_col.update_one({"type": "shortener"}, {"$set": {"url": s_url}}, upsert=True)
    await message.reply_text(f"✅ **Shortener Domain Updated to:** `{s_url}`")

@app.on_message(filters.command("set_api") & filters.user(ADMIN_ID))
async def set_api_cmd(client, message):
    if len(message.command) < 2:
        await message.reply_text("⚠️ **Usage:** `/set_api your_api_key_here`")
        return
    
    s_api = message.command[1].strip()
    settings_col.update_one({"type": "shortener"}, {"$set": {"api": s_api}}, upsert=True)
    await message.reply_text("✅ **Shortener API Key Updated Successfully!**")

@app.on_message(filters.command("shortener_off") & filters.user(ADMIN_ID))
async def shortener_off_cmd(client, message):
    settings_col.update_one({"type": "shortener"}, {"$set": {"status": False}}, upsert=True)
    await message.reply_text("🚫 **Shortener Status:** OFF (Users get direct links without verification)")

@app.on_message(filters.command("shortener_on") & filters.user(ADMIN_ID))
async def shortener_on_cmd(client, message):
    settings_col.update_one({"type": "shortener"}, {"$set": {"status": True}}, upsert=True)
    await message.reply_text("⚡ **Shortener Status:** ON (24h Token Verification Active)")

# --- Standard Command Handlers ---

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user_id = message.from_user.id
    
    if not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "joined_at": datetime.datetime.utcnow()})

    text_args = message.text.split()

    if len(text_args) > 1 and text_args[1].startswith("verify_"):
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"verified_at": datetime.datetime.utcnow()}},
            upsert=True
        )
        await message.reply_text(
            "🎉 **Access Granted!**\n\nYour 24-hour token pass has been activated successfully. You can now search and download files directly!"
        )
        return

    if len(text_args) > 1:
        file_id = text_args[1]
        try:
            await client.send_cached_media(chat_id=message.chat.id, file_id=file_id)
            return
        except Exception as e:
            await message.reply_text("❌ Failed to send file. It might have been deleted or invalid.")
            return

    start_text = (
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        "I am an **Advanced Auto Filter Bot**.\n"
        "Just type the name of any movie or file in the group/chat to search.\n\n"
        "Use /help to see all available commands."
    )
    btn = InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Help", callback_data="help_data"),
         InlineKeyboardButton("📄 About", callback_data="about_data")]
    ])
    await message.reply_text(start_text, reply_markup=btn)

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    help_text = (
        "📖 **Bot Help & Commands Menu**\n\n"
        "• Type any movie title to search.\n"
        "• `/start` - Start bot / verify token.\n"
        "• `/stats` - View file and user statistics.\n"
        "• `/ping` - Check bot latency.\n\n"
        "🛠 **Admin Commands:**\n"
        "• `/set_shortener <domain>` - Change shortener site\n"
        "• `/set_api <key>` - Change shortener API key\n"
        "• `/shortener_off` - Disable shortener verification\n"
        "• `/shortener_on` - Enable shortener verification"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("stats"))
async def stats_cmd(client, message):
    total_files = files_col.count_documents({})
    total_users = users_col.count_documents({})
    s_url, s_api, s_status = get_shortener_settings()
    
    stats_text = (
        "📊 **Bot Current Statistics**\n\n"
        f"📁 **Total Files Saved:** `{total_files}`\n"
        f"👤 **Total Users:** `{total_users}`\n"
        f"🌐 **Active Shortener:** `{s_url if s_url else 'None'}`\n"
        f"⚡ **Shortener Mode:** `{'ON' if s_status else 'OFF'}`"
    )
    await message.reply_text(stats_text)

# --- Channel File Saver ---
@app.on_message(filters.channel & (filters.document | filters.video))
async def index_files(client, message):
    try:
        media = message.document or message.video
        file_id = media.file_id
        file_name = media.file_name or message.caption or "Unknown File"
        
        if not files_col.find_one({"file_id": file_id}):
            files_col.insert_one({
                "
