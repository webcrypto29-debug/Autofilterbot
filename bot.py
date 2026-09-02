import os
import asyncio
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# --- Render Web Service को Active रखने के लिए Web Server ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Auto Filter Bot is Alive!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- Configuration (Environment Variables) ---
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI", "YOUR_MONGO_URI")
DATABASE_NAME = os.environ.get("DATABASE_NAME", "AutoFilterBot")

# --- Database Setup ---
mongo_client = MongoClient(MONGO_URI)
db = mongo_client[DATABASE_NAME]
files_col = db["files"]

# --- Bot Setup ---
app = Client("AutoFilterBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# 1. डेटाबेस में फाइलें सेव करने का Handler (Channel से)
@app.on_message(filters.channel & (filters.document | filters.video))
async def save_file(client, message):
    media = message.document or message.video
    file_id = media.file_id
    file_name = media.file_name or "Unknown File"
    
    # Mongo DB में चेक करके सेव करें
    if not files_col.find_one({"file_id": file_id}):
        files_col.insert_one({
            "file_name": file_name.lower(),
            "file_id": file_id,
            "caption": message.caption or file_name
        })

# 2. ग्रुप/चैट में ऑटो-फिल्टर सर्च Handler
@app.on_message(filters.text & filters.group)
async def auto_filter(client, message):
    query = message.text.strip().lower()
    if len(query) < 3:
        return
    
    # DB में नाम मैच करके सर्च करें
    results = list(files_col.find({"file_name": {"$regex": query}}).limit(10))
    
    if not results:
        return

    buttons = []
    for file in results:
        btn_text = file["file_name"][:30]
        # Callback query या Direct link बटन
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"file_{file['_id']}")])
    
    await message.reply_text(
        f"🔍 **Search Results for:** `{query}`",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

# Start Keep-Alive Server and Bot
if __name__ == "__main__":
    Thread(target=run_web).start()
    app.run()
