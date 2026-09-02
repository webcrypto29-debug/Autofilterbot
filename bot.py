import os
import asyncio
import datetime
import requests
from flask import Flask
from threading import Thread
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# --- Web Server (Render Keep-Alive) ---
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "24h Token Auto Filter Bot Active!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

# --- Configuration (Environment Variables) ---
API_ID = int(os.environ.get("API_ID", "123456"))
API_HASH = os.environ.get("API_HASH", "YOUR_API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
MONGO_URI = os.environ.get("MONGO_URI", "YOUR_MONGO_URI")

# Shortener Settings
SHORTENER_API = os.environ.get("SHORTENER_API", "YOUR_SHORTENER_API")
SHORTENER_URL = os.environ.get("SHORTENER_URL", "gplinks.in")

# --- Database Setup ---
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["AutoFilterDB"]
files_col = db["files"]
users_col = db["users"] # 24 Hours Token Status स्टोर करने के लिए

# --- Shortener Helper Function ---
def get_shortlink(url):
    if not SHORTENER_API or not SHORTENER_URL:
        return url
    try:
        api_url = f"https://{SHORTENER_URL}/api?api={SHORTENER_API}&url={url}"
        res = requests.get(api_url, timeout=5).json()
        if res.get("status") == "success":
            return res.get("shortlink")
        return url
    except Exception as e:
        print(f"Shortener Error: {e}")
        return url

# --- User Token Check Helper (24 Hours Logic) ---
def is_user_verified(user_id):
    user = users_col.find_one({"user_id": user_id})
    if not user:
        return False
    
    last_verified = user.get("verified_at")
    if not last_verified:
        return False
    
    # चेक करें कि क्या 24 घंटे बीत चुके हैं?
    now = datetime.datetime.utcnow()
    time_diff = (now - last_verified).total_seconds()
    if time_diff < 86400: # 86400 Seconds = 24 Hours
        return True
    return False

# --- Bot App ---
app = Client("AutoFilterBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# 1. Start Command & Token Verification Handler
@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    user_id = message.from_user.id
    text = message.text

    # अगर यूज़र Shortener Link पास करके आया है (e.g. /start verify_12345)
    if len(text.split()) > 1 and text.split()[1].startswith("verify_"):
        # यूज़र का टाइमस्टैम्प अपडेट करें (24 घंटे चालू)
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"verified_at": datetime.datetime.utcnow()}},
            upsert=True
        )
        await message.reply_text("🎉 **बधाई हो! आपका 24 घंटे का एक्सेस वेरीफाई हो गया है।**\n\nअब आप बिना किसी Shortener के डायरेक्ट फाइलें डाउनलोड कर सकते हैं!")
        return

    await message.reply_text("👋 **नमस्ते!** मैं आपका Auto Filter Bot हूँ। किसी भी मूवी या फ़ाइल का नाम लिखकर ग्रुप में सर्च करें।")

# 2. File Saver from Database Channel
@app.on_message(filters.channel & (filters.document | filters.video))
async def index_files(client, message):
    try:
        media = message.document or message.video
        file_id = media.file_id
        file_name = media.file_name or message.caption or "Unknown File"
        
        if not files_col.find_one({"file_id": file_id}):
            files_col.insert_one({
                "file_name": file_name,
                "file_id": file_id
            })
    except Exception as e:
        print(f"Index Error: {e}")

# 3. Auto Filter Search Logic (with 24 Hours Token System)
@app.on_message(filters.text & (filters.group | filters.private))
async def auto_filter(client, message):
    if message.text.startswith("/"):
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

    # अगर यूज़र 24 घंटे के अंदर वेरीफाइड नहीं है
    if not verified:
        # Token Generate URL बनाएँ
        raw_verify_url = f"https://t.me/{bot_username}?start=verify_{user_id}"
        short_verify_url = get_shortlink(raw_verify_url)

        btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔑 Get 24-Hour Access Token", url=short_verify_url)]
        ])

        await message.reply_text(
            f"🔒 **आपकी खोज:** `{query}`\n\n"
            f"आपका 24 घंटे का एक्सेस समाप्त हो गया है या आप नए यूज़र हैं।\n"
            f"नीचे दिए गए बटन पर क्लिक करके **24 घंटे का टोकन** प्राप्त करें। उसके बाद आप पूरे दिन डायरेक्ट फाइल्स पा सकेंगे!",
            reply_markup=btn
        )
        return

    # अगर यूज़र वेरीफाइड है 👉 डायरेक्ट फाइल्स दें!
    buttons = []
    for file in results:
        f_name = file["file_name"]
        file_id = file["file_id"]
        # Direct Telegram File Link
        direct_link = f"https://t.me/{bot_username}?start={file_id}"
        buttons.append([InlineKeyboardButton(text=f"🎬 {f_name[:35]}...", url=direct_link)])

    await message.reply_text(
        f"🔍 **Search Results For:** `{query}`\n\n✅ **24h Pass Active! डायरेक्ट डाउनलोड लिंक:**",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    app.run()
