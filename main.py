import os
import asyncio
import logging
import re
import subprocess
import threading
import time
import uuid
from pathlib import Path

# ── Ensure HOME/bin is in PATH so ffmpeg binary is found at runtime ──
os.environ["PATH"] = os.path.expanduser("~/bin") + ":" + os.environ.get("PATH", "")

import requests
import yt_dlp
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
BOT_TOKEN  = os.environ.get("BOT_TOKEN", "7677822008:AAGv3IWbNrQEJM12v1z1oFAKIVw8ICi26hY")
RENDER_URL = os.environ.get("RENDER_URL", "")
TEMP_DIR   = Path("/tmp/tgbot")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ─── Keep-Alive Flask server ──────────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "✅ Bot is alive!", 200

@flask_app.route("/ping")
def ping():
    return "pong", 200

def run_flask():
    flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def keep_alive_ping():
    """Ping self every 14 minutes to prevent Render from sleeping."""
    while True:
        time.sleep(14 * 60)
        if RENDER_URL:
            try:
                requests.get(f"{RENDER_URL}/ping", timeout=10)
                logger.info("✅ Keep-alive ping sent")
            except Exception as e:
                logger.warning(f"Keep-alive ping failed: {e}")

# ─── Helpers ──────────────────────────────────────────────────────────────────
INSTAGRAM_PATTERN = re.compile(
    r"https?://(www\.)?(instagram\.com|instagr\.am)/(p|reel|tv)/[\w-]+"
)
YOUTUBE_PATTERN = re.compile(
    r"https?://(www\.)?(youtube\.com/watch|youtu\.be|youtube\.com/shorts)[\S]+"
)

def unique_path(ext: str) -> Path:
    return TEMP_DIR / f"{uuid.uuid4().hex}.{ext}"

def cleanup(*paths):
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass

# ─── /start & /help ───────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *مرحباً! أنا بوت متعدد المهام*\n\n"
        "🎬 *تحويل الصيغ*\n"
        "أرسل أي ملف فيديو أو صوت وسأحوله لصيغة تختارها.\n\n"
        "🔍 *بحث يوتيوب*\n"
        "استخدم: `/yt كلمة البحث`\n\n"
        "📸 *تحميل إنستقرام*\n"
        "أرسل رابط أي منشور أو ريل من إنستقرام.\n\n"
        "📹 *تحميل يوتيوب*\n"
        "أرسل رابط أي فيديو يوتيوب مباشرة.\n\n"
        "⚙️ استخدم /help لمزيد من المعلومات."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *المساعدة*\n\n"
        "• `/start` — رسالة الترحيب\n"
        "• `/yt <بحث>` — ابحث في يوتيوب ونزّل\n"
        "• أرسل رابط يوتيوب مباشرة — للتحميل الفوري\n"
        "• أرسل رابط إنستقرام — لتحميل المقطع\n"
        "• أرسل ملف فيديو/صوت — لتحويل الصيغة\n\n"
        "📌 *الصيغ المدعومة للتحويل:*\n"
        "`mp3 | mp4 | ogg | wav | aac | opus | webm`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─── YouTube Search ────────────────────────────────────────────────────────────
async def yt_search(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = " ".join(ctx.args)
    if not query:
        await update.message.reply_text(
            "❗ أرسل كلمة البحث بعد الأمر.\nمثال: `/yt أغاني عربية`",
            parse_mode="Markdown"
        )
        return

    msg = await update.message.reply_text("🔍 جاري البحث في يوتيوب...")

    try:
        loop = asyncio.get_event_loop()
        ydl_opts = {"quiet": True, "extract_flat": True}
        info = await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(ydl_opts).extract_info(f"ytsearch5:{query}", download=False)
        )

        results = info.get("entries", [])
        if not results:
            await msg.edit_text("❌ لم أجد نتائج.")
            return

        keyboard = []
        text_lines = ["🎬 *نتائج البحث:*\n"]
        for i, entry in enumerate(results[:5], 1):
            title    = entry.get("title", "بدون عنوان")[:60]
            duration = entry.get("duration", 0)
            dur_str  = f"{duration//60}:{duration%60:02d}" if duration else "?:??"
            url      = f"https://youtube.com/watch?v={entry['id']}"
            text_lines.append(f"{i}. *{title}* ({dur_str})")
            keyboard.append([InlineKeyboardButton(
                f"⬇️ {i}. {title[:40]}",
                callback_data=f"dl_yt|{url}"
            )])

        await msg.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"YT search error: {e}")
        await msg.edit_text("❌ حدث خطأ أثناء البحث.")

# ─── Download helper ───────────────────────────────────────────────────────────
async def download_video(message, url: str, caption: str = ""):
    msg = await message.reply_text("⏳ جاري التحميل...")
    out_path = unique_path("mp4")

    ydl_opts = {
        "format": "best[ext=mp4][filesize<50M]/best[filesize<50M]/best",
        "outtmpl": str(out_path),
        "quiet": True,
    }

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: yt_dlp.YoutubeDL(ydl_opts).download([url])
        )

        # yt-dlp may rename the file
        if not out_path.exists():
            candidates = list(TEMP_DIR.glob(f"{out_path.stem}.*"))
            if candidates:
                out_path = candidates[0]
            else:
                await msg.edit_text("❌ فشل التحميل.")
                return

        if out_path.stat().st_size > 50 * 1024 * 1024:
            await msg.edit_text("❌ الملف أكبر من 50 ميجا (حد تيليغرام).")
            cleanup(out_path)
            return

        await msg.edit_text("📤 جاري الرفع...")
        with open(out_path, "rb") as f:
            await message.reply_video(f, caption=caption or "📥 تم التحميل", supports_streaming=True)
        await msg.delete()

    except Exception as e:
        logger.error(f"Download error: {e}")
        await msg.edit_text(f"❌ فشل التحميل:\n`{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        cleanup(out_path)

# ─── Callback handler ──────────────────────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("dl_yt|"):
        url = data.split("|", 1)[1]
        await download_video(query.message, url)

    elif data.startswith("convert|"):
        _, file_id, target_fmt = data.split("|")
        await do_convert(query.message, file_id, target_fmt)

# ─── Message handler ───────────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    if msg.text and INSTAGRAM_PATTERN.search(msg.text):
        url = INSTAGRAM_PATTERN.search(msg.text).group(0)
        await download_video(msg, url, "📸 مقطع إنستقرام")
        return

    if msg.text and YOUTUBE_PATTERN.search(msg.text):
        url = YOUTUBE_PATTERN.search(msg.text).group(0)
        await download_video(msg, url, "🎬 فيديو يوتيوب")
        return

    file_obj = msg.video or msg.audio or msg.voice or msg.document
    if file_obj:
        keyboard = [
            [
                InlineKeyboardButton("🎵 MP3",  callback_data=f"convert|{file_obj.file_id}|mp3"),
                InlineKeyboardButton("🎤 OGG",  callback_data=f"convert|{file_obj.file_id}|ogg"),
                InlineKeyboardButton("🔊 WAV",  callback_data=f"convert|{file_obj.file_id}|wav"),
            ],
            [
                InlineKeyboardButton("🎬 MP4",  callback_data=f"convert|{file_obj.file_id}|mp4"),
                InlineKeyboardButton("📼 WEBM", callback_data=f"convert|{file_obj.file_id}|webm"),
                InlineKeyboardButton("🎙️ AAC",  callback_data=f"convert|{file_obj.file_id}|aac"),
            ],
        ]
        await msg.reply_text(
            "🔄 *اختر الصيغة التي تريد التحويل إليها:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if msg.text:
        await msg.reply_text(
            "❓ لم أفهم. أرسل:\n"
            "• رابط يوتيوب أو إنستقرام\n"
            "• ملف فيديو/صوت للتحويل\n"
            "• `/yt كلمة البحث` للبحث في يوتيوب"
        )

# ─── Convert ───────────────────────────────────────────────────────────────────
async def do_convert(message, file_id: str, target_fmt: str):
    msg = await message.reply_text(f"⏳ جاري التحويل إلى {target_fmt.upper()}...")

    input_path  = unique_path("input")
    output_path = unique_path(target_fmt)

    try:
        from telegram import Bot
        bot  = Bot(token=BOT_TOKEN)
        tg_file = await bot.get_file(file_id)
        await tg_file.download_to_drive(str(input_path))

        audio_formats = {"mp3", "ogg", "wav", "aac", "opus", "flac"}
        if target_fmt in audio_formats:
            cmd = ["ffmpeg", "-y", "-i", str(input_path),
                   "-vn", "-ar", "44100", "-ac", "2", str(output_path)]
        else:
            cmd = ["ffmpeg", "-y", "-i", str(input_path), str(output_path)]

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, timeout=120)
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode()[:300])

        await msg.edit_text("📤 جاري الرفع...")
        with open(output_path, "rb") as f:
            if target_fmt in {"ogg", "opus"}:
                await message.reply_voice(f, caption=f"🎤 تم التحويل إلى {target_fmt.upper()}")
            elif target_fmt in audio_formats:
                await message.reply_audio(f, caption=f"🎵 تم التحويل إلى {target_fmt.upper()}")
            else:
                await message.reply_video(f, caption=f"🎬 تم التحويل إلى {target_fmt.upper()}")

        await msg.delete()

    except Exception as e:
        logger.error(f"Convert error: {e}")
        await msg.edit_text(f"❌ فشل التحويل:\n`{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        cleanup(input_path, output_path)

# ─── Main ──────────────────────────────────────────────────────────────────────
async def async_main():
    # Start Flask in background thread
    threading.Thread(target=run_flask, daemon=True).start()
    # Start keep-alive ping thread
    threading.Thread(target=keep_alive_ping, daemon=True).start()

    # Build and run bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(CommandHandler("yt",    yt_search))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    logger.info("🤖 Bot started!")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # Run forever
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(async_main())