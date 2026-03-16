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

# ─── URL cache ────────────────────────────────────────────────────────────────
url_cache: dict[str, str] = {}

def cache_url(url: str) -> str:
    short = uuid.uuid4().hex[:8]
    url_cache[short] = url
    return short

def get_url(short: str) -> str:
    return url_cache.get(short, "")

# ─── Keep-Alive Flask ─────────────────────────────────────────────────────────
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

def unique_path(ext: str) -> Path:
    return TEMP_DIR / f"{uuid.uuid4().hex}.{ext}"

def cleanup(*paths):
    for p in paths:
        try:
            Path(str(p)).unlink(missing_ok=True)
        except Exception:
            pass

def find_file(base_path: Path, preferred_ext: str = None) -> Path | None:
    if base_path.exists():
        return base_path
    candidates = list(TEMP_DIR.glob(f"{base_path.stem}.*"))
    if preferred_ext:
        for c in candidates:
            if c.suffix == f".{preferred_ext}":
                return c
    return candidates[0] if candidates else None

# ─── /start & /help ───────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *مرحباً!*\n\n"
        "🔄 *تحويل الصيغ*\n"
        "أرسل أي ملف فيديو أو صوت وسأحوله للصيغة التي تختارها.\n\n"
        "📸 *تحميل إنستقرام*\n"
        "أرسل رابط أي ريل أو منشور وسأحمله لك.\n\n"
        "الصيغ المدعومة: `MP3 | OGG | WAV | AAC | MP4 | WEBM`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await start(update, ctx)

# ─── تحميل إنستقرام ───────────────────────────────────────────────────────────
async def download_instagram(message, url: str, as_audio: bool):
    if as_audio:
        msg = await message.reply_text("⏳ جاري تحميل الصوت...")
        out  = unique_path("mp3")
        opts = {
            "format": "bestaudio/best",
            "outtmpl": str(out),
            "quiet": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "ffmpeg_location": os.path.expanduser("~/bin"),
        }
    else:
        msg = await message.reply_text("⏳ جاري تحميل المقطع...")
        out  = unique_path("mp4")
        opts = {
            "format": "best[ext=mp4][filesize<50M]/best[filesize<50M]/best",
            "outtmpl": str(out),
            "quiet": True,
        }

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: yt_dlp.YoutubeDL(opts).download([url]))

        ext   = "mp3" if as_audio else None
        final = find_file(out, preferred_ext=ext)
        if not final:
            await msg.edit_text("❌ فشل التحميل.")
            return

        if final.stat().st_size > 50 * 1024 * 1024:
            await msg.edit_text("❌ الملف أكبر من 50 ميجا.")
            cleanup(final)
            return

        await msg.edit_text("📤 جاري الرفع...")
        with open(final, "rb") as f:
            if as_audio:
                await message.reply_audio(f, caption="🎵 صوت من إنستقرام")
            else:
                await message.reply_video(f, caption="📸 مقطع من إنستقرام", supports_streaming=True)
        await msg.delete()

    except Exception as e:
        logger.error(f"Instagram download error: {e}")
        await msg.edit_text(f"❌ فشل التحميل:\n`{str(e)[:200]}`", parse_mode="Markdown")
    finally:
        cleanup(out)

# ─── Callback handler ──────────────────────────────────────────────────────────
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    # إنستقرام صوت
    if data.startswith("iga|"):
        url = get_url(data[4:])
        if url:
            await download_instagram(query.message, url, as_audio=True)
        else:
            await query.message.reply_text("❌ انتهت صلاحية الزر، أرسل الرابط مجدداً.")

    # إنستقرام مقطع
    elif data.startswith("igv|"):
        url = get_url(data[4:])
        if url:
            await download_instagram(query.message, url, as_audio=False)
        else:
            await query.message.reply_text("❌ انتهت صلاحية الزر، أرسل الرابط مجدداً.")

    # تحويل صيغة
    elif data.startswith("cv|"):
        parts = data.split("|")   # cv | file_id | fmt
        if len(parts) == 3:
            await do_convert(query.message, parts[1], parts[2])

# ─── Message handler ───────────────────────────────────────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    logger.info(f"MSG type: text={bool(msg.text)} video={bool(msg.video)} audio={bool(msg.audio)} voice={bool(msg.voice)} doc={bool(msg.document)}")

    # ── إنستقرام ──
    if msg.text and INSTAGRAM_PATTERN.search(msg.text):
        url = INSTAGRAM_PATTERN.search(msg.text).group(0)
        sid = cache_url(url)
        keyboard = [[
            InlineKeyboardButton("🎵 صوت",  callback_data=f"iga|{sid}"),
            InlineKeyboardButton("🎬 مقطع", callback_data=f"igv|{sid}"),
        ]]
        await msg.reply_text(
            "📸 رابط إنستقرام — تريد صوت أو مقطع؟",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── ملف للتحويل ──
    file_obj = msg.video or msg.audio or msg.voice or msg.document
    if file_obj:
        fid = file_obj.file_id
        # callback_data max 64 bytes: "cv|" (3) + fid (~52) + "|mp3" (4) = ~59 ✅
        keyboard = [
            [
                InlineKeyboardButton("🎵 MP3",  callback_data=f"cv|{fid}|mp3"),
                InlineKeyboardButton("🎤 OGG",  callback_data=f"cv|{fid}|ogg"),
                InlineKeyboardButton("🔊 WAV",  callback_data=f"cv|{fid}|wav"),
            ],
            [
                InlineKeyboardButton("🎬 MP4",  callback_data=f"cv|{fid}|mp4"),
                InlineKeyboardButton("📼 WEBM", callback_data=f"cv|{fid}|webm"),
                InlineKeyboardButton("🎙 AAC",  callback_data=f"cv|{fid}|aac"),
            ],
        ]
        await msg.reply_text(
            "🔄 *اختر الصيغة:*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # ── نص عادي ──
    if msg.text:
        await msg.reply_text(
            "أرسل:\n"
            "• رابط إنستقرام لتحميله\n"
            "• ملف فيديو أو صوت لتحويل صيغته"
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

        audio_fmts = {"mp3", "ogg", "wav", "aac", "opus", "flac"}
        if target_fmt in audio_fmts:
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
            elif target_fmt in audio_fmts:
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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(CallbackQueryHandler(callback_handler))

    # handlers منفصلة لكل نوع ملف — أكثر موثوقية من filters.ALL
    app.add_handler(MessageHandler(filters.VIDEO,    handle_message))
    app.add_handler(MessageHandler(filters.AUDIO,    handle_message))
    app.add_handler(MessageHandler(filters.VOICE,    handle_message))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

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