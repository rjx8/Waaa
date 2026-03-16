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

# ─── URL cache: short_id → full_url ──────────────────────────────────────────
# Avoids putting long URLs in callback_data (max 64 bytes)
url_cache: dict[str, str] = {}

def cache_url(url: str) -> str:
    short = uuid.uuid4().hex[:8]
    url_cache[short] = url
    return short

def get_url(short: str) -> str:
    return url_cache.get(short, "")

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
    r"https?://(www\.)?(youtube\.com/watch\?[\S]+|youtu\.be/[\w-]+|youtube\.com/shorts/[\w-]+)"
)

def unique_path(ext: str) -> Path:
    return TEMP_DIR / f"{uuid.uuid4().hex}.{ext}"

def cleanup(*paths):
    for p in paths:
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass

def fmt_duration(duration) -> str:
    try:
        d = int(float(duration))
        return f"{d//60}:{d%60:02d}"
    except Exception:
        return "?:??"

# ─── /start & /help ───────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *مرحباً! أنا بوت متعدد المهام*\n\n"
        "🎬 *تحويل الصيغ*\n"
        "أرسل أي ملف فيديو أو صوت وسأحوله لصيغة تختارها.\n\n"
        "🔍 *بحث يوتيوب*\n"
        "استخدم: `/yt كلمة البحث`\n\n"
        "📸 *تحميل إنستقرام*\n"
        "أرسل رابط أي منشور أو ريل.\n\n"
        "📹 *تحميل يوتيوب*\n"
        "أرسل رابط أي فيديو يوتيوب مباشرة.\n\n"
        "⚙️ /help لمزيد من المعلومات."
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *المساعدة*\n\n"
        "• `/yt <نص>` — بحث في يوتيوب\n"
        "• أرسل رابط يوتيوب — للتحميل الفوري\n"
        "• أرسل رابط إنستقرام — لتحميل المقطع\n"
        "• أرسل ملف فيديو/صوت — لتحويل الصيغة\n\n"
        "📌 *الصيغ المدعومة:*\n"
        "`mp3 | mp4 | ogg | wav | aac | webm`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─── بحث يوتيوب ───────────────────────────────────────────────────────────────
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
            title   = entry.get("title", "بدون عنوان")[:50]
            dur_str = fmt_duration(entry.get("duration", 0))
            vid_id  = entry.get("id", "")
            url     = f"https://youtu.be/{vid_id}"
            sid     = cache_url(url)   # short 8-char id

            text_lines.append(f"{i}. *{title}* ({dur_str})")
            # Two buttons per result: audio | video — callback max ~20 chars ✅
            keyboard.append([
                InlineKeyboardButton(f"🎵 {i}. صوت", callback_data=f"yta|{sid}"),
                InlineKeyboardButton(f"🎬 {i}. مقطع", callback_data=f"ytv|{sid}"),
            ])

        await msg.edit_text(
            "\n".join(text_lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"YT search error: {e}")
        await msg.edit_text("❌ حدث خطأ أثناء البحث.")

# ─── تحميل فيديو (مقطع) ───────────────────────────────────────────────────────
async def download_as_video(message, url: str, caption: str = ""):
    msg = await message.reply_text("⏳ جاري تحميل المقطع...")
    out_path = unique_path("mp4")

    ydl_opts = {
        "format": "best[ext=mp4][filesize<50M]/best[filesize<50M]/best",
        "outtmpl": str(out_path),
        "quiet": True,
    }

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

        final = _find_file(out_path)
        if not final:
            await msg.edit_text("❌ فشل التحميل.")
            return

        if final.stat().st_size > 50 * 1024 * 1024:
            await msg.edit_text("❌ الملف أكبر من 50 ميجا (حد تيليغرام).")
            cleanup(final)
            return

        await msg.edit_text("📤 جاري الرفع...")
        with open(final, "rb") as f:
            await message.reply_video(f, caption=caption or "🎬 تم التحميل", supports_streaming=True)
        await msg.delete()

    except Exception as e:
        logger.error(f"Video download error: {e}")
        await msg.edit_text(f"❌ فشل التحميل:\n`{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        cleanup(out_path)

# ─── تحميل صوت فقط ────────────────────────────────────────────────────────────
async def download_as_audio(message, url: str, caption: str = ""):
    msg = await message.reply_text("⏳ جاري تحميل الصوت...")
    out_path = unique_path("mp3")

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(out_path),
        "quiet": True,
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
        "ffmpeg_location": os.path.expanduser("~/bin"),
    }

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

        # yt-dlp adds .mp3 extension
        final = _find_file(out_path, preferred_ext="mp3")
        if not final:
            await msg.edit_text("❌ فشل التحميل.")
            return

        await msg.edit_text("📤 جاري الرفع...")
        with open(final, "rb") as f:
            await message.reply_audio(f, caption=caption or "🎵 تم التحميل")
        await msg.delete()

    except Exception as e:
        logger.error(f"Audio download error: {e}")
        await msg.edit_text(f"❌ فشل التحميل:\n`{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        cleanup(out_path)
        # cleanup possible .mp3 variant
        mp3_path = Path(str(out_path) + ".mp3")
        cleanup(mp3_path)

def _find_file(base_path: Path, preferred_ext: str = None) -> Path | None:
    if base_path.exists():
        return base_path
    # yt-dlp may rename
    candidates = list(TEMP_DIR.glob(f"{base_path.stem}.*"))
    if preferred_ext:
        for c in candidates:
            if c.suffix == f".{preferred_ext}":
                return c
    return candidates[0] if candidates else None

# ─── Callback handler ──────────────────────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    # YouTube audio
    if data.startswith("yta|"):
        sid = data[4:]
        url = get_url(sid)
        if url:
            await download_as_audio(query.message, url, "🎵 صوت من يوتيوب")
        else:
            await query.message.reply_text("❌ انتهت صلاحية الزر، ابحث مجدداً.")

    # YouTube video
    elif data.startswith("ytv|"):
        sid = data[4:]
        url = get_url(sid)
        if url:
            await download_as_video(query.message, url, "🎬 مقطع من يوتيوب")
        else:
            await query.message.reply_text("❌ انتهت صلاحية الزر، ابحث مجدداً.")

    # تحويل صيغة
    elif data.startswith("convert|"):
        _, file_id, target_fmt = data.split("|")
        await do_convert(query.message, file_id, target_fmt)

# ─── Message handler ───────────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message

    # إنستقرام
    if msg.text and INSTAGRAM_PATTERN.search(msg.text):
        url = INSTAGRAM_PATTERN.search(msg.text).group(0)
        sid = cache_url(url)
        keyboard = [[
            InlineKeyboardButton("🎵 صوت",  callback_data=f"yta|{sid}"),
            InlineKeyboardButton("🎬 مقطع", callback_data=f"ytv|{sid}"),
        ]]
        await msg.reply_text(
            "📸 رابط إنستقرام — تريد صوت أو مقطع؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # يوتيوب
    if msg.text and YOUTUBE_PATTERN.search(msg.text):
        url = YOUTUBE_PATTERN.search(msg.text).group(0)
        sid = cache_url(url)
        keyboard = [[
            InlineKeyboardButton("🎵 صوت",  callback_data=f"yta|{sid}"),
            InlineKeyboardButton("🎬 مقطع", callback_data=f"ytv|{sid}"),
        ]]
        await msg.reply_text(
            "🎬 رابط يوتيوب — تريد صوت أو مقطع؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ملف للتحويل
    file_obj = msg.video or msg.audio or msg.voice or msg.document
    if file_obj:
        fid = file_obj.file_id
        keyboard = [
            [
                InlineKeyboardButton("🎵 MP3",  callback_data=f"convert|{fid}|mp3"),
                InlineKeyboardButton("🎤 OGG",  callback_data=f"convert|{fid}|ogg"),
                InlineKeyboardButton("🔊 WAV",  callback_data=f"convert|{fid}|wav"),
            ],
            [
                InlineKeyboardButton("🎬 MP4",  callback_data=f"convert|{fid}|mp4"),
                InlineKeyboardButton("📼 WEBM", callback_data=f"convert|{fid}|webm"),
                InlineKeyboardButton("🎙️ AAC",  callback_data=f"convert|{fid}|aac"),
            ],
        ]
        await msg.reply_text(
            "🔄 *اختر الصيغة التي تريد التحويل إليها:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if msg.text and msg.text.startswith("بحث "):
        ctx.args = msg.text[4:].split()
        await yt_search(update, ctx)
        return

    if msg.text:
        await msg.reply_text(
            "❓ لم أفهم. أرسل:\n"
            "• رابط يوتيوب أو إنستقرام\n"
            "• ملف فيديو/صوت للتحويل\n"
            "• `/yt كلمة البحث` للبحث في يوتيوب"
        )

# ─── تحويل الصيغ ───────────────────────────────────────────────────────────────
async def do_convert(message, file_id: str, target_fmt: str):
    msg = await message.reply_text(f"⏳ جاري التحويل إلى {target_fmt.upper()}...")

    input_path  = unique_path("input")
    output_path = unique_path(target_fmt)

    try:
        from telegram import Bot
        bot     = Bot(token=BOT_TOKEN)
        tg_file = await bot.get_file(file_id)
        await tg_file.download_to_drive(str(input_path))

        audio_formats = {"mp3", "ogg", "wav", "aac", "opus", "flac"}
        if target_fmt in audio_formats:
            cmd = ["ffmpeg", "-y", "-i", str(input_path),
                   "-vn", "-ar", "44100", "-ac", "2", str(output_path)]
        else:
            cmd = ["ffmpeg", "-y", "-i", str(input_path), str(output_path)]

        loop   = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: subprocess.run(cmd, capture_output=True, timeout=120)
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode()[:300])

        await msg.edit_text("📤 جاري الرفع...")
        with open(output_path, "rb") as f:
            if target_fmt in {"ogg", "opus"}:
                await message.reply_voice(f, caption=f"🎤 {target_fmt.upper()}")
            elif target_fmt in audio_formats:
                await message.reply_audio(f, caption=f"🎵 {target_fmt.upper()}")
            else:
                await message.reply_video(f, caption=f"🎬 {target_fmt.upper()}")

        await msg.delete()

    except Exception as e:
        logger.error(f"Convert error: {e}")
        await msg.edit_text(f"❌ فشل التحويل:\n`{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        cleanup(input_path, output_path)

# ─── Main ──────────────────────────────────────────────────────────────────────
async def async_main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",  start))
    app.add_handler(CommandHandler("help",   help_cmd))
    app.add_handler(CommandHandler("yt", yt_search))
    app.add_handler(CommandHandler("search", yt_search))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL, handle_message))

    logger.info("🤖 Bot started!")
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(async_main())