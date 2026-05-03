import os
import logging
import asyncio
import sqlite3
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import yt_dlp

# ================= CONFIG =================
TOKEN = os.getenv("TOKEN")
ADMIN_ID = os.getenv("ADMIN_ID")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        downloads INTEGER DEFAULT 0,
        username TEXT
    )
    """)
    conn.commit()
    return conn, cursor

conn, cursor = init_db()

# ================= KEYBOARDS =================
def main_menu_keyboard():
    keyboard = [
        [InlineKeyboardButton("ℹ️ كيف أستخدم البوت؟", callback_data="help")],
        [InlineKeyboardButton("📊 إحصائياتي", callback_data="stats")]
    ]
    return InlineKeyboardMarkup(keyboard)

def download_options_keyboard(url):
    keyboard = [
        [
            InlineKeyboardButton("🎬 فيديو (MP4)", callback_data=f"dl_video|{url}"),
            InlineKeyboardButton("🎵 صوت (MP3)", callback_data=f"dl_audio|{url}")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    cursor.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (user.id, user.username))
    conn.commit()

    welcome_text = (
        f"👋 أهلاً بك يا {user.first_name} في بوت تحميل الفيديوهات الاحترافي! 🚀\n\n"
        "📥 **ماذا يمكنني أن أفعل؟**\n"
        "أرسل لي رابط أي فيديو من (يوتيوب، تيك توك، إنستغرام، فيسبوك، تويتر) وسأقوم بتحميله لك فوراً بأعلى جودة ممكنة.\n\n"
        "👇 أرسل الرابط الآن للبدء:"
    )
    await update.message.reply_text(welcome_text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    # التحقق من أن النص هو رابط (بسيط)
    if re.match(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', url):
        await update.message.reply_text(
            "✅ تم استلام الرابط! اختر الصيغة المطلوبة للتحميل:",
            reply_markup=download_options_keyboard(url)
        )
    else:
        await update.message.reply_text("❌ عذراً، يرجى إرسال رابط فيديو صحيح.")

async def download_task(update: Update, context: ContextTypes.DEFAULT_TYPE, url, mode):
    query = update.callback_query
    user_id = query.from_user.id
    
    status_msg = await query.message.reply_text("⏳ جاري معالجة الفيديو... قد يستغرق ذلك لحظات.")

    try:
        # إعدادات yt-dlp
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best' if mode == 'video' else 'bestaudio/best',
            'outtmpl': f'downloads/%(id)s_{user_id}.%(ext)s',
            'max_filesize': 50 * 1024 * 1024, # حد 50 ميجا لتيليجرام بوت العادي
            'quiet': True,
            'no_warnings': True,
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

        # تشغيل التحميل في thread منفصل لعدم حظر البوت (نصيحة من مهارة telegram-bot-pro)
        file_path = await asyncio.to_thread(download)
        
        # إذا كان صوت، الامتداد سيتغير لـ mp3 بواسطة postprocessor
        if mode == 'audio':
            file_path = os.path.splitext(file_path)[0] + ".mp3"

        # إرسال الملف
        await status_msg.edit_text("📤 جاري رفع الملف إلى تيليجرام...")
        with open(file_path, 'rb') as f:
            if mode == 'video':
                await context.bot.send_video(chat_id=user_id, video=f, caption="✅ تم التحميل بنجاح بواسطة بوتك الخرافي!")
            else:
                await context.bot.send_audio(chat_id=user_id, audio=f, caption="✅ تم تحويل الصوت بنجاح!")

        # تحديث الإحصائيات
        cursor.execute("UPDATE users SET downloads = downloads + 1 WHERE id = ?", (user_id,))
        conn.commit()

        await status_msg.delete()
        # تنظيف الملف بعد الإرسال
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        logger.error(f"Download Error: {e}")
        await status_msg.edit_text("❌ عذراً، حدث خطأ أثناء التحميل. قد يكون الفيديو طويلاً جداً أو الرابط غير مدعوم.")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data.startswith("dl_"):
        mode, url = data.split("|", 1)
        mode = "video" if "video" in mode else "audio"
        await download_task(update, context, url, mode)
    
    elif data == "stats":
        cursor.execute("SELECT downloads FROM users WHERE id=?", (query.from_user.id,))
        row = cursor.fetchone()
        count = row[0] if row else 0
        await query.edit_message_text(f"📊 إحصائياتك:\n\n📥 عدد الفيديوهات المحملة: {count}", reply_markup=main_menu_keyboard())
    
    elif data == "help":
        help_text = "📖 **كيفية الاستخدام:**\n1. انسخ رابط الفيديو من أي منصة.\n2. أرسل الرابط هنا.\n3. اختر الجودة المطلوبة.\n4. انتظر ثوانٍ وسيصلك الملف!"
        await query.edit_message_text(help_text, reply_markup=main_menu_keyboard(), parse_mode="Markdown")

# ================= MAIN =================
def main():
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    if not TOKEN:
        logger.error("TOKEN not found!")
        return

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("🚀 بوت التحميل يعمل الآن!")
    app.run_polling()

if __name__ == "__main__":
    main()
