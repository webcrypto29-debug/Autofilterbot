import asyncio
import os
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.errors import FloodWait, RPCError

# ================= 1. Render Keep-Alive Web Server =================
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is Live & Running!")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    print(f"Web server running on port {port}...")
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# ================= 2. Config & Environment Variables =================
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
MONGO_URL = os.environ.get("MONGO_URL", "").strip()

AUTO_DELETE_TIME = 30  # Auto delete duration in seconds

# ================= 3. Database Setup =================
mongo_client = AsyncIOMotorClient(MONGO_URL, tlsCAFile=certifi.where())
db = mongo_client["AutoFilterBotDB"]
files_col = db["indexed_files"]
settings_col = db["settings"]

bot = Client(
    "auto_filter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# Helper Functions
async def get_settings():
    try:
        doc = await settings_col.find_one({"_id": "bot_settings"})
        if not doc:
            default_settings = {
                "_id": "bot_settings", 
                "db_channels": [], 
                "tutorial_link": None
            }
            await settings_col.insert_one(default_settings)
            return default_settings
        return doc
    except Exception as e:
        print(f"Database Error: {e}")
        return {"_id": "bot_settings", "db_channels": [], "tutorial_link": None}

async def update_settings(data):
    await settings_col.update_one({"_id": "bot_settings"}, {"$set": data}, upsert=True)

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[._\-\[\]\(\)]', ' ', str(text)).lower().strip()
    return " ".join(text.split())

def extract_file_name(message):
    file_name = None
    if message.document:
        file_name = message.document.file_name
    elif message.video:
        file_name = message.video.file_name or message.caption
    elif message.audio:
        file_name = message.audio.file_name or message.caption
    elif message.caption:
        file_name = message.caption
    return clean_text(file_name)

async def auto_delete_task(sent_msg, duration=AUTO_DELETE_TIME):
    await asyncio.sleep(duration)
    try:
        await sent_msg.delete()
    except Exception:
        pass  # Message was already deleted

def is_admin(message):
    return bool(message.from_user and message.from_user.id == ADMIN_ID)


# ================= 4. Commands Handlers =================

# Start Command
@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client, message):
    user_name = message.from_user.first_name if message.from_user else "User"
    settings = await get_settings()
    
    welcome_text = (
        f"👋 **Hello {user_name}!**\n\n"
        "🎬 **How to search for movies/files:**\n"
        "Send only the movie or series title in **English**.\n\n"
        "✅ **Correct:** `Avengers` or `Hanuman`\n"
        "❌ **Incorrect:** `Avengers movie chahiye` or `please send Hanuman`\n\n"
        f"⚠️ *Note:* Files will automatically self-destruct after {AUTO_DELETE_TIME} seconds."
    )
    
    buttons = []
    if settings.get("tutorial_link"):
        buttons.append([InlineKeyboardButton("❓ How to Download", url=settings["tutorial_link"])])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(welcome_text, reply_markup=reply_markup)

# Add Database Channel
@bot.on_message(filters.command("adddb"))
async def add_db_channel(client, message):
    if not is_admin(message):
        return await message.reply_text("❌ You are not authorized.")

    if len(message.command) < 2:
        return await message.reply_text("❌ Provide Channel ID.\nExample: `/adddb -1001234567890`")
    
    try:
        chat_id = int(message.command[1])
        # Try fetching chat to verify admin rights and access
        await client.get_chat(chat_id)

        settings = await get_settings()
        db_channels = settings.get("db_channels", [])
        
        if chat_id not in db_channels:
            db_channels.append(chat_id)
            await update_settings({"db_channels": db_channels})
            await message.reply_text(f"✅ **Database Channel Added:** `{chat_id}`")
        else:
            await message.reply_text("⚠️ This channel is already in the list.")
    except Exception as e:
        await message.reply_text(f"❌ Cannot connect to channel. Make sure Bot is Admin in it.\nError: `{e}`")

# Delete Database Channel
@bot.on_message(filters.command("deldb"))
async def del_db_channel(client, message):
    if not is_admin(message):
        return await message.reply_text("❌ You are not authorized.")

    if len(message.command) < 2:
        return await message.reply_text("❌ Provide Channel ID.\nExample: `/deldb -1001234567890`")
    
    try:
        chat_id = int(message.command[1])
        settings = await get_settings()
        db_channels = settings.get("db_channels", [])
        
        if chat_id in db_channels:
            db_channels.remove(chat_id)
            await update_settings({"db_channels": db_channels})
            await message.reply_text(f"🗑️ **Database Channel Removed:** `{chat_id}`")
        else:
            await message.reply_text("❌ Channel not found in settings.")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")

# Set Tutorial Link
@bot.on_message(filters.command("settutorial"))
async def set_tutorial(client, message):
    if not is_admin(message):
        return await message.reply_text("❌ You are not authorized.")

    if len(message.command) < 2:
        return await message.reply_text("❌ Provide tutorial link.\nExample: `/settutorial https://t.me/your_video`")
    
    link = message.command[1].strip()
    await update_settings({"tutorial_link": link})
    await message.reply_text("✅ **Tutorial Link updated successfully!**")


# ================= 5. Auto File Indexing =================

# Auto Index Posts from Connected Channels
@bot.on_message(filters.channel & (filters.document | filters.video | filters.audio))
async def auto_index_channel(client, message):
    try:
        settings = await get_settings()
        db_channels = settings.get("db_channels", [])
        
        if message.chat.id in db_channels:
            clean_name = extract_file_name(message)
            if clean_name:
                await files_col.update_one(
                    {"file_name": clean_name, "chat_id": message.chat.id},
                    {"$set": {"msg_id": message.id, "original_caption": message.caption or clean_name}},
                    upsert=True
                )
                print(f"[Indexed] {clean_name}")
    except Exception as e:
        print(f"Indexing Error: {e}")

# Manual Forwarded File Saver (Admin Only)
@bot.on_message(filters.private & filters.forwarded & (filters.document | filters.video | filters.audio))
async def manual_forward_index(client, message):
    if not is_admin(message):
        return

    clean_name = extract_file_name(message)
    settings = await get_settings()

    if clean_name:
        chat_id = message.forward_from_chat.id if message.forward_from_chat else (settings["db_channels"][0] if settings.get("db_channels") else message.chat.id)
        msg_id = message.forward_from_message_id if message.forward_from_message_id else message.id

        await files_col.update_one(
            {"file_name": clean_name, "chat_id": chat_id},
            {"$set": {"msg_id": msg_id, "original_caption": message.caption or clean_name}},
            upsert=True
        )
        await message.reply_text(f"✅ **File Indexed:** `{clean_name}`")


# ================= 6. Movie Search & Filter Logic =================
@bot.on_message((filters.private | filters.group) & filters.text & ~filters.command(["start", "adddb", "deldb", "settutorial"]))
async def auto_filter_search(client, message):
    if message.forward_date:
        return

    raw_query = message.text.strip()
    query = clean_text(raw_query)

    if not query or len(query) < 2:
        return

    settings = await get_settings()
    found_files = []

    # Fuzzy Matching: Splits words so "Hanuman" matches "Hanuman 2024 1080p"
    words = query.split()
    regex_pattern = "".join([f"(?=.*{re.escape(w)})" for w in words])
    
    cursor = files_col.find({"file_name": {"$regex": regex_pattern, "$options": "i"}})
    async for doc in cursor:
        found_files.append((doc["chat_id"], doc["msg_id"], doc["file_name"]))

    if found_files:
        success = False
        # Send up to 5 matching files
        for chat_id, msg_id, f_name in found_files[:5]:
            try:
                # Direct File TG Link
                file_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{msg_id}"

                buttons = [[InlineKeyboardButton("📁 Direct File", url=file_link)]]
                if settings.get("tutorial_link"):
                    buttons.append([InlineKeyboardButton("❓ How to Download", url=settings["tutorial_link"])])

                reply_markup = InlineKeyboardMarkup(buttons)

                sent_file = await client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=chat_id,
                    message_id=msg_id,
                    reply_markup=reply_markup
                )

                # Trigger Auto Delete
                asyncio.create_task(auto_delete_task(sent_file, AUTO_DELETE_TIME))
                success = True
                await asyncio.sleep(0.8)

            except FloodWait as e:
                await asyncio.sleep(e.value)
            except RPCError as e:
                print(f"Send Error: {e}")

        if success:
            return

    not_found_msg = await message.reply_text("❌ **This file is currently unavailable, but it will be uploaded soon.**")
    asyncio.create_task(auto_delete_task(not_found_msg, 10))

# ================= 7. Bot Runner =================
if __name__ == "__main__":
    print("Auto Filter Bot successfully started...")
    bot.run()
