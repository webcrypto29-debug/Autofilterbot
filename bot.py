import asyncio
try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

import os
import re
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from rapidfuzz import fuzz
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
from motor.motor_asyncio import AsyncIOMotorClient

# ================= Render Web Server =================
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
# ====================================================

# Environment variables
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
MONGO_URL = os.environ.get("MONGO_URL", "")

AUTO_DELETE_TIME = 30

# Database Connection
mongo_client = AsyncIOMotorClient(MONGO_URL)
db = mongo_client["AutoFilterBotDB"]
files_col = db["indexed_files"]
settings_col = db["settings"]

bot = Client(
    "auto_filter_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True
)

async def get_settings():
    doc = await settings_col.find_one({"_id": "bot_settings"})
    if not doc:
        default_settings = {"_id": "bot_settings", "db_channels": [], "tutorial_link": None, "custom_direct_link": None}
        await settings_col.insert_one(default_settings)
        return default_settings
    return doc

async def update_settings(data):
    await settings_col.update_one({"_id": "bot_settings"}, {"$set": data}, upsert=True)

def is_admin(_, __, message):
    if not message.from_user:
        return False
    return message.from_user.id == ADMIN_ID

admin_filter = filters.create(is_admin)

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
    elif message.text:
        file_name = message.text

    return clean_text(file_name)

async def auto_delete_task(sent_msg, duration=AUTO_DELETE_TIME):
    await asyncio.sleep(duration)
    try:
        await sent_msg.delete()
    except Exception as e:
        print(f"Error deleting message: {e}")

# 1. /start Command
@bot.on_message(filters.command("start"))
async def start_handler(client, message):
    user_name = message.from_user.first_name if message.from_user else "User"
    settings = await get_settings()
    welcome_text = (
        f"👋 **Hello {user_name}!**\n\n"
        "🎬 **How to search for movies/files:**\n"
        "Send only the exact title in **English**.\n\n"
        "✅ **Correct:** `Avengers` or `Avatar`\n"
        "❌ **Incorrect:** `Avengers movie chahiye` or `please send Avengers`\n\n"
        "⚠️ *Note:* Files will automatically self-destruct after 30 seconds."
    )
    buttons = []
    if settings.get("tutorial_link"):
        buttons.append([InlineKeyboardButton("❓ How to Download", url=settings["tutorial_link"])])

    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None
    await message.reply_text(welcome_text, reply_markup=reply_markup)

# 2. /adddb Command
@bot.on_message(filters.command("adddb") & admin_filter)
async def add_db_channel(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide Channel ID.\nExample: `/adddb -1001234567890`")
        return
    try:
        chat_id = int(message.command[1])
        settings = await get_settings()
        db_channels = settings.get("db_channels", [])
        if chat_id not in db_channels:
            db_channels.append(chat_id)
            await update_settings({"db_channels": db_channels})
            await message.reply_text(f"✅ **Database Channel Added:** `{chat_id}`")
        else:
            await message.reply_text("⚠️ **यह चैनल पहले से ही ऐड है!**")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

# 3. /deldb Command
@bot.on_message(filters.command("deldb") & admin_filter)
async def del_db_channel(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide Channel ID.\nExample: `/deldb -1001234567890`")
        return
    try:
        chat_id = int(message.command[1])
        settings = await get_settings()
        db_channels = settings.get("db_channels", [])
        if chat_id in db_channels:
            db_channels.remove(chat_id)
            await update_settings({"db_channels": db_channels})
            await message.reply_text(f"🗑️ **Database Channel Removed:** `{chat_id}`")
        else:
            await message.reply_text("❌ **यह चैनल लिस्ट में नहीं मिला।**")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")

# 4. /mydb Command
@bot.on_message(filters.command("mydb") & admin_filter)
async def my_db_handler(client, message):
    settings = await get_settings()
    channels = settings.get("db_channels", [])
    total_files = await files_col.count_documents({})
    if not channels:
        await message.reply_text("❌ कोई भी Database Channel सेट नहीं है। `/adddb` का उपयोग करें।")
    else:
        chan_list = "\n".join([f"• `{cid}`" for cid in channels])
        await message.reply_text(
            f"📢 **Connected Channels ({len(channels)}):**\n{chan_list}\n\n"
            f"📁 **Total Indexed Files:** `{total_files}`"
        )

# 5. /setdirectlink Command
@bot.on_message(filters.command("setdirectlink") & admin_filter)
async def set_direct_link(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide link or reset command.\nExample: `/setdirectlink https://t.me/your_channel`")
        return

    link = message.command[1].strip()
    if link.lower() == "reset":
        await update_settings({"custom_direct_link": None})
        await message.reply_text("✅ **Direct File link reset to default!**")
    else:
        await update_settings({"custom_direct_link": link})
        await message.reply_text(f"✅ **Custom Direct Link updated to:**\n`{link}`")

# 6. /settutorial Command
@bot.on_message(filters.command("settutorial") & admin_filter)
async def set_tutorial(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Please provide tutorial link.\nExample: `/settutorial https://t.me/your_video`")
        return
    await update_settings({"tutorial_link": message.command[1]})
    await message.reply_text("✅ **Tutorial Link updated!**")

# 7. /delete Command
@bot.on_message(filters.command("delete") & admin_filter)
async def delete_file_handler(client, message):
    if len(message.command) < 2:
        await message.reply_text("❌ Provide movie/file name to delete.\nExample: `/delete avengers`")
        return

    query = clean_text(" ".join(message.command[1:]))
    result = await files_col.delete_many({"file_name": {"$regex": query, "$options": "i"}})

    if result.deleted_count > 0:
        await message.reply_text(f"🗑️ Removed **{result.deleted_count}** indexed file(s) for query: **'{query}'**")
    else:
        await message.reply_text("❌ File not found in database.")

# 8. Manual Forward Index
@bot.on_message(filters.private & admin_filter & filters.forwarded)
async def manual_forward_index(client, message):
    clean_name = extract_file_name(message)
    settings = await get_settings()
    if clean_name:
        chat_id = message.forward_from_chat.id if message.forward_from_chat else (settings["db_channels"][0] if settings.get("db_channels") else message.chat.id)
        msg_id = message.forward_from_message_id if message.forward_from_message_id else message.id

        await files_col.update_one(
            {"file_name": clean_name},
            {"$set": {"chat_id": chat_id, "msg_id": msg_id}},
            upsert=True
        )
        await message.reply_text(f"✅ **Manual File Saved!**\n📌 `{clean_name}`")

# 9. MULTI-CHANNEL AUTO-INDEX LISTENER
@bot.on_message(filters.channel)
async def auto_index_new_file(client, message):
    settings = await get_settings()
    db_channels = settings.get("db_channels", [])
    if message.chat.id in db_channels:
        clean_name = extract_file_name(message)
        if clean_name:
            await files_col.update_one(
                {"file_name": clean_name},
                {"$set": {"chat_id": message.chat.id, "msg_id": message.id}},
                upsert=True
            )
            print(f"[Auto-Index Live] 🔥 न्यू फाइल अपने आप सेव हुई ({message.chat.title}): {clean_name}")

# 10. AUTO FILTER SEARCH LOGIC WITH AUTO-DELETE
@bot.on_message((filters.private | filters.group) & filters.text & ~filters.command(["start", "adddb", "deldb", "mydb", "settutorial", "setdirectlink", "delete"]))
async def auto_filter_search(client, message):
    if message.forward_date:
        return

    query = clean_text(message.text)

    if not query or len(query) < 2:
        return

    settings = await get_settings()
    found_files = []

    # MongoDB Exact/Partial Match Search
    cursor = files_col.find({"file_name": {"$regex": re.escape(query), "$options": "i"}})
    async for doc in cursor:
        found_files.append((doc["chat_id"], doc["msg_id"], doc["file_name"]))

    # Fuzzy Search fallback if no exact regex match
    if not found_files:
        all_files = files_col.find({})
        async for doc in all_files:
            if fuzz.partial_ratio(query, doc["file_name"]) >= 80:
                found_files.append((doc["chat_id"], doc["msg_id"], doc["file_name"]))

    if found_files:
        for chat_id, msg_id, f_name in found_files[:3]:
            try:
                buttons = []

                if settings.get("custom_direct_link"):
                    file_link = settings["custom_direct_link"]
                else:
                    file_link = f"https://t.me/c/{str(chat_id).replace('-100', '')}/{msg_id}"

                buttons.append([InlineKeyboardButton("📁 Direct File", url=file_link)])

                if settings.get("tutorial_link"):
                    buttons.append([InlineKeyboardButton("❓ How to Download", url=settings["tutorial_link"])])

                reply_markup = InlineKeyboardMarkup(buttons)

                sent_file = await client.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=chat_id,
                    message_id=msg_id,
                    reply_markup=reply_markup
                )

                asyncio.create_task(auto_delete_task(sent_file, AUTO_DELETE_TIME))
                await asyncio.sleep(1)

            except Exception as e:
                print(f"Error sending file: {e}")
        return

    not_found_msg = await message.reply_text("❌ **This file is currently unavailable, but it will be uploaded soon.**")
    asyncio.create_task(auto_delete_task(not_found_msg, 10))

if __name__ == "__main__":
    print("Auto Filter Bot successfully started...")
    bot.run()
