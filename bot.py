import os
import logging
import asyncio
import sqlite3
import re
import uuid
from threading import Thread
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from telegram.error import BadRequest
import yt_dlp

# ================= WEB SERVER FOR RENDER (KEEP-ALIVE) =================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Bot is running 24/7 with Mandatory Subscription!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app_web.run(host='0.0.0.0', port=port)

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
CHANNEL_ID = "@bre766202"  # معرف القناة للاشتراك الإجباري
CHANNEL_URL = "https://t.me/bre766202"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("bot_data.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        downloads INTEGER DEFAULT 0,
        username TEXT
    )
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS temp_links (
        id TEXT PRIMARY KEY,
        url TEXT
    )
    """)
    conn.commit()
    return conn, cursor

conn, cursor = init_db()

# ================= UTILS =================
async def is_subscribed(user_id, context):
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        if member.status in ['member', 'administrator', 'creator']:
            return True
        return False
    except BadRequest:
        # في حال لم يتم إضافة البوت كمسؤول في القناة
        logger.warning(f"البوت ليس مسؤولاً في القناة {CHANNEL_ID}")
        return True # السماح بالمرور لتجنب تعطل البوت
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return True

def subscription_keyboard():
    keyboard = [
        [InlineKeyboardButton("📢 انضم للقناة الآن", url=CHANNEL_URL)],
        [InlineKeyboardButton("✅ تم الاشتراك", callback_data="check_sub")]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= KEYBOARDS =================
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("ℹ️ كيف أستخدم البوت؟", callback_data="help")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")]
    ]
    return InlineKeyboardMarkup(keyboard)

def download_options_keyboard(link_id):
    keyboard = [
        [
            InlineKeyboardButton("🎬 فيديو (MP4)", callback_data=f"dl_video|{link_id}"),
            InlineKeyboardButton("🎵 صوت (MP3)", callback_data=f"dl_audio|{link_id}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    
    # التحقق من الاشتراك
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            f"⚠️ عذراً يا {user.first_name}، يجب عليك الاشتراك في قناتنا أولاً لاستخدام البوت!\n\n"
            "اشترك ثم اضغط على زر 'تم الاشتراك' بالأسفل 👇",
            reply_markup=subscription_keyboard()
        )
        return

    cursor.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user.id, user.username))
    conn.commit()

    welcome_text = (
        f"👋 أهلاً بك يا {user.first_name} في بوت تحميل الفيديوهات الاحترافي! 🚀\n\n"
        "📥 **أرسل رابط أي فيديو وسأقوم بتحميله لك فوراً.**"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # التحقق من الاشتراك قبل معالجة أي رابط
    if not await is_subscribed(user_id, context):
        await update.message.reply_text(
            "⚠️ يجب عليك الاشتراك في القناة أولاً لاستخدام ميزات التحميل!",
            reply_markup=subscription_keyboard()
        )
        return

    url = update.message.text.strip()
    if re.match(r'http[s]?://', url):
        link_id = str(uuid.uuid4())[:8]
        cursor.execute("INSERT INTO temp_links (id, url) VALUES (?, ?)", (link_id, url))
        conn.commit()
        
        await update.message.reply_text(
            "✅ تم استلام الرابط! اختر الصيغة المطلوبة:",
            reply_markup=download_options_keyboard(link_id)
        )
    else:
        await update.message.reply_text("❌ يرجى إرسال رابط فيديو صحيح يبدأ بـ http.")

async def download_task(update: Update, context: ContextTypes.DEFAULT_TYPE, link_id, mode):
    query = update.callback_query
    user_id = query.from_user.id
    
    cursor.execute("SELECT url FROM temp_links WHERE id=?", (link_id,))
    row = cursor.fetchone()
    if not row:
        await query.message.reply_text("❌ انتهت صلاحية الرابط. أعد الإرسال.")
        return
    
    url = row[0]
    status_msg = await query.message.reply_text("⏳ جاري التحميل...")

    try:
        if not os.path.exists("downloads"):
            os.makedirs("downloads")

        file_id = str(uuid.uuid4())[:8]
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best' if mode == 'video' else 'bestaudio/best',
            'outtmpl': f'downloads/{file_id}_%(id)s.%(ext)s',
            'max_filesize': 45 * 1024 * 1024,
            'quiet': True,
        }
        
        if mode == 'audio':
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]

        def download():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)

        file_path = await asyncio.to_thread(download)
        
        if mode == 'audio':
            file_path = os.path.splitext(file_path)[0] + ".mp3"

        await status_msg.edit_text("📤 جاري الرفع...")
        with open(file_path, 'rb') as f:
            if mode == 'video':
                await context.bot.send_video(chat_id=user_id, video=f, caption="✅ تم التحميل!")
            else:
                await context.bot.send_audio(chat_id=user_id, audio=f, caption="🎵 تم التحويل!")

        cursor.execute("UPDATE users SET downloads = downloads + 1 WHERE id = ?", (user_id,))
        conn.commit()

        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ خطأ: {str(e)[:100]}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    await query.answer()

    if data == "check_sub":
        if await is_subscribed(user_id, context):
            await query.message.edit_text(
                "✅ شكراً لاشتراكك! يمكنك الآن استخدام البوت.\nأرسل رابط الفيديو للبدء:",
                reply_markup=main_menu_keyboard()
            )
        else:
            await query.answer("❌ لم تشترك في القناة بعد!", show_alert=True)

    elif data.startswith("dl_"):
        # التحقق من الاشتراك حتى عند الضغط على أزرار التحميل
        if not await is_subscribed(user_id, context):
            await query.message.reply_text("⚠️ يجب عليك الاشتراك في القناة أولاً!", reply_markup=subscription_keyboard())
            return
            
        mode_part, link_id = data.split("|")
        mode = "video" if "video" in mode_part else "audio"
        await download_task(update, context, link_id, mode)
    
    elif data == "stats":
        cursor.execute("SELECT downloads FROM users WHERE id=?", (user_id,))
        row = cursor.fetchone()
        count = row[0] if row else 0
        await query.edit_message_text(f"📊 إحصائياتك:\n📥 عدد التحميلات: {count}", reply_markup=main_menu_keyboard())
    
    elif data == "help":
        await query.edit_message_text("📖 أرسل رابط الفيديو فقط.", reply_markup=main_menu_keyboard())

def main():
    Thread(target=run_web).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))
    
    logger.info("🚀 البوت مع الاشتراك الإجباري يعمل الآن!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
