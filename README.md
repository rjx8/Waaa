# 🤖 بوت تيليغرام متعدد المهام

## ✨ المميزات
- 🎬 **تحويل الصيغ**: فيديو/صوت → MP3, OGG, WAV, AAC, MP4, WEBM
- 🔍 **بحث يوتيوب**: `/yt كلمة البحث` ثم اختر نتيجة للتحميل
- 📹 **تحميل يوتيوب**: أرسل الرابط مباشرة
- 📸 **تحميل إنستقرام**: أرسل رابط أي ريل أو منشور
- 💓 **Keep-alive**: نبضة كل 14 دقيقة لمنع الإيقاف

---

## 🚀 الرفع على Render (خطوة بخطوة)

### 1. إنشاء مستودع GitHub
```bash
git init
git add .
git commit -m "Initial bot"
git remote add origin https://github.com/USERNAME/REPO.git
git push -u origin main
```

### 2. إنشاء خدمة على Render
1. اذهب إلى [render.com](https://render.com) وسجّل دخولك
2. اضغط **New → Web Service**
3. اربط مستودع GitHub
4. اضبط الإعدادات:
   - **Build Command**: `bash build.sh`
   - **Start Command**: `python main.py`
   - **Environment**: Python 3

### 3. إضافة المتغيرات البيئية
في لوحة Render → Environment:
| Key | Value |
|-----|-------|
| `BOT_TOKEN` | `7677822008:AAGv3IWbNrQEJM12v1z1oFAKIVw8ICi26hY` |
| `RENDER_URL` | `https://اسم-تطبيقك.onrender.com` (بعد النشر) |

### 4. تفعيل Keep-alive الخارجي (اختياري - أقوى)
استخدم [UptimeRobot](https://uptimerobot.com):
- أضف monitor من نوع HTTP
- URL: `https://اسم-تطبيقك.onrender.com/ping`
- الفترة: كل 14 دقيقة

---

## 📂 هيكل الملفات
```
├── main.py           # الكود الرئيسي
├── requirements.txt  # المكتبات
├── build.sh          # سكريبت البناء (يثبت ffmpeg)
├── render.yaml       # إعدادات Render
└── README.md
```

---

## 🔧 المكتبات المستخدمة
- `python-telegram-bot` — واجهة التيليغرام
- `yt-dlp` — تحميل يوتيوب وإنستقرام
- `ffmpeg` — تحويل الصيغ
- `flask` — سيرفر Keep-alive
