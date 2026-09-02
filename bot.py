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

# --- Keep-Alive Web Server for Render / UptimeRobot ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "24h Token Auto Filter Bot is Running Successfully!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- Configuration (Environment Variables) ---
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URI = os.environ.get("MONGO_URI", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# --- Safe Database Setup ---
if not MONGO_URI:
    print("❌ ERROR: MONGO_URI environment variable is missing or empty!")
    print("Please add MONGO_URI in Render Environment Variables.")

try:
    mongo_client = MongoClient(MONGO_URI) if MONGO_URI else None
    if mongo_client:
        db = mongo_client["AutoFilterDB"]
        files_col = db["files"]
        users_col = db["users"]
        settings_col = db["settings"]
    else:
        files_col = users_col = settings_col = None
except Exception as e:
    print(f"❌ Database Connection Error: {e}")
    files_col = users_col = settings_col = None

# --- Shortener Helper Functions ---
def get_shortener_settings():
    if settings_col is not None:
        try:
            settings = settings_col.find_one({"type": "shortener"})
            if settings:
                return settings.get("url", ""), settings.get("api", ""), settings.get("status", True)
        except Exception as e:
            print(f"DB Error in get_shortener_settings: {e}")
    return os.environ.get("SHORTENER_URL", ""), os.environ.get("SHORTENER_API", ""), True

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
        print(f"Shortener API Error: {e}")
        return url

# --- 24-Hour Token Verification Logic ---
def is_user_verified(user_id):
    if users_col is None:
        return False
    try:
        user = users_col.find_one({"user_id": user_id})
        if not user:
            return False
        
        last_verified = user.get("verified_at")
        if not last_verified:
            return False
        
        now = datetime.datetime.utcnow()
        time_diff = (now - last_verified).total_seconds()
        if time_diff < 86400:  # 24 Hours in seconds
            return True
    except Exception as e:
        print(f"Verification Check Error: {e}")
    return False

# --- Bot Client ---
app = Client("AutoFilterBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# --- Admin Commands (Control Shortener from Telegram Chat) ---

@app.on_message(filters.command("set_shortener") & filters.user(ADMIN_ID))
async def set_shortener_cmd(client, message):
    if settings_col is None:
        await message.reply_text("❌ Database not connected!")
        return
    if len(message.command) < 2:
        await message.reply_text("⚠️ **Usage:** `/set_shortener gplinks.in`")
        return
    s_url = message.command[1].strip().replace("https://", "").replace("http://", "")
    settings_col.update_one({"type": "shortener"}, {"$set": {"url": s_url}}, upsert=True)
    await message.reply_text(f"✅ **Shortener Domain Updated:** `{s_url}`")

@app.on_message(filters.command("set_api") & filters.user(ADMIN_ID))
async def set_api_cmd(client, message):
    if settings_col is None:
        await message.reply_text("❌ Database not connected!")
        return
    if len(message.command) < 2:
        await message.reply_text("⚠️ **Usage:** `/set_api your_api_key_here`")
        return
    s_api = message.command[1].strip()
    settings_col.update_one({"type": "shortener"}, {"$set": {"api": s_api}}, upsert=True)
    await message.reply_text("✅ **Shortener API Key Updated Successfully!**")

@app.on_message(filters.command("shortener_off") & filters.user(ADMIN_ID))
async def shortener_off_cmd(client, message):
    if settings_col is None:
        await message.reply_text("❌ Database not connected!")
        return
    settings_col.update_one({"type": "shortener"}, {"$set": {"status": False}}, upsert=True)
    await message.reply_text("🚫 **Shortener Status:** OFF (Direct links enabled)")

@app.on_message(filters.command("shortener_on") & filters.user(ADMIN_ID))
async def shortener_on_cmd(client, message):
    if settings_col is None:
        await message.reply_text("❌ Database not connected!")
        return
    settings_col.update_one({"type": "shortener"}, {"$set": {"status": True}}, upsert=True)
    await message.reply_text("⚡ **Shortener Status:** ON (24h Pass active)")

# --- Standard User Commands ---

@app.on_message(filters.command("start") & filters.private)
async def start_cmd(client, message):
    user_id = message.from_user.id
    
    if users_col is not None and not users_col.find_one({"user_id": user_id}):
        users_col.insert_one({"user_id": user_id, "joined_at": datetime.datetime.utcnow()})

    text_args = message.text.split()

    if len(text_args) > 1 and text_args[1].startswith("verify_"):
        if users_col is not None:
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"verified_at": datetime.datetime.utcnow()}},
                upsert=True
            )
        await message.reply_text("🎉 **Access Granted!**\n\nYour 24-hour pass is active. You can now search and download files freely!")
        return

    if len(text_args) > 1:
        file_id = text_args[1]
        try:
            await client.send_cached_media(chat_id=message.chat.id, file_id=file_id)
            return
        except Exception:
            await message.reply_text("❌ Failed to send file. It may have been deleted.")
            return

    start_text = (
        f"👋 **Hello {message.from_user.first_name}!**\n\n"
        "I am an **Auto Filter Bot**.\n"
        "Send any movie or file name in the chat to search.\n\n"
        "Use /help to view available commands."
    )
    await message.reply_text(start_text)

@app.on_message(filters.command("help"))
async def help_cmd(client, message):
    help_text = (
        "📖 **Commands List:**\n\n"
        "• `/start` - Start bot / verify access pass\n"
        "• `/stats` - View database statistics\n"
        "• `/ping` - Check server speed\n\n"
        "🛠 **Admin Commands:**\n"
        "• `/set_shortener <domain>` - Set shortener site\n"
        "• `/set_api <key>` - Set API key\n"
        "• `/shortener_off` - Turn off shortener\n"
        "• `/shortener_on` - Turn on shortener"
    )
    await message.reply_text(help_text)

@app.on_message(filters.command("ping"))
async def ping_cmd(client, message):
    start_time = time.time()
    reply = await message.reply_text("🏓 Pinging...")
    end_time = time.time()
    ms = round((end_time - start_time) * 1000, 2)
    await reply.edit_text(f"⚡ **Pong!** `{ms} ms`")

@app.on_message(filters.command("stats"))
async def stats_cmd(client, message):
    if files_col is None or users_col is None:
        await message.reply_text("❌ Database Connection Error.")
        return
    total_files = files_col.count_documents({})
    total_users = users_col.count_documents({})
    s_url, _, s_status = get_shortener_settings()
    
    stats_text = (
        "📊 **Bot Statistics**\n\n"
        f"📁 **Saved Files:** `{total_files}`\n"
        f"👤 **Total Users:** `{total_users}`\n"
        f"🌐 **Shortener Site:** `{s_url if s_url else 'None'}`\n"
        f"⚡ **Shortener Status:** `{'ON' if s_status else 'OFF'}`"
    )
    await message.reply_text(stats_text)

# --- Index Files From Channel ---
@app.on_message(filters.channel & (filters.document | filters.video))
async def index_files(client, message):
    if files_col is None:
        return
    try:
        media = message.document or message.video
        file_id = media.file_id
        file_name = media.file_name or message.caption or "Unknown File"
        
        if not files_col.find_one({"file_id": file_id}):
            files_col.insert_one({"file_name": file_name, "file_id": file_id})
    except Exception as e:
        print(f"Index Error: {e}")

# --- Auto Filter Engine ---
@app.on_message(filters.text & (filters.group | filters.private))
async def auto_filter(client, message):
    if message.text.startswith("/") or files_col is None:
        return

    query = message.text.strip()
    if len(query) < 2:
        return

    user_id = message.from_user.id
    results = list(files_col.find({"file_name": {"$regex": query, "$options": "i"}}).limit(7))

    if not results:
        return

    bot_username = (await client.get_me()).username
    verified = is_user_verified(user_id)
    _, _, s_status = get_shortener_settings()

    if s_status and not verified:
        raw_verify_url = f"https://t.me/{bot_username}?start=verify_{user_id}"
        short_verify_url = get_shortlink(raw_verify_url)

        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Get 24-Hour Access Pass", url=short_verify_url)]
        ])

        await message.reply_text(
            f"🔒 **Search Result For:** `{query}`\n\n"
            "Your 24-hour pass has expired or you are a new user.\n"
            "Click below to get your **24-Hour Access Pass**.",
            reply_markup=btn
        )
        return

    buttons = []
    for file in results:
        f_name = file["file_name"]
        file_id = file["file_id"]
        direct_link = f"https://t.me/{bot_username}?start={file_id}"
        buttons.append([InlineKeyboardButton(text=f"🎬 {f_name[:35]}...", url=direct_link)])

    await message.reply_text(
        f"🔍 **Search Results For:** `{query}`\n\n✅ **Direct Links:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# --- Async Main Loop ---
async def main():
    Thread(target=run_web, daemon=True).start()
    await app.start()
    print("Auto Filter Bot Started Successfully!")
    from pyrogram import idle
    await idle()
    await app.stop()

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
