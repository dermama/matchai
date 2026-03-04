# 🤖 Matchai — AI Android Agent

> **هاتفك + Gemini + Groq = وكيل ذكاء اصطناعي كامل تحت أمرك**

Matchai يحوّل هاتف أندرويد إلى وكيل ذكاء اصطناعي يستجيب لأوامر تيليجرام ويتحكم بالهاتف بالكامل.

---

### 📖 [دليل الإعداد التفصيلي (العربية)](file:///c:/Users/ersan/Desktop/ب/SETUP_GUIDE_AR.md)

---

## 🏗️ المكونات

| المكون | التقنية | الوظيفة |
|--------|---------|---------|
| **السيرفر** | FastAPI + Railway | التنسيق واستقبال رسائل تيليجرام |
| **الذكاء** | Gemini 2.0 Flash | تخطيط المهام والتحليل المنطقي |
| **الرؤية** | Groq Llama 3.2 | تحليل الشاشة (Visual Processing) |
| **التنفيذ** | Kotlin + Shizuku | التحكم الفعلي بالأندرويد بدون Root |

---

## 🚀 خطوات النشر

### 1. رفع الكود على GitHub
```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/dermama/matchai.git
git push -u origin main
```

### 2. نشر السيرفر على Railway
1. اذهب إلى [railway.app](https://railway.app)
2. New Project → Deploy from GitHub → اختر `dermama/matchai`
3. اختر مجلد `server` كـ Root Directory
4. أضف هذه المتغيرات في Settings → Variables:

```
GEMINI_API_KEY=AIzaSyBLhWRkLPY6SRN6Nqj2EBOk_P7aSVMeC6A
TELEGRAM_BOT_TOKEN=8335908034:AAEnUGrwnFRnhYRBMaaKpewZiweUFRUIrTU
TELEGRAM_CHAT_ID=5365734222
GROQ_API_KEY=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
DEVICE_SECRET=matchai_secret_2024
```

5. انسخ رابط التطبيق من Railway (مثل `https://matchai-xxx.railway.app`)

### 3. إعداد GitHub Secrets
في `dermama/matchai` → Settings → Secrets → Actions:
```
TELEGRAM_BOT_TOKEN  ← نفس القيمة أعلاه
TELEGRAM_CHAT_ID    ← نفس القيمة أعلاه
SERVER_URL          ← رابط Railway
DEVICE_SECRET       ← matchai_secret_2024
```

### 4. بناء تطبيق الأندرويد
- ادفع الكود لـ GitHub → GitHub Actions يبني APK تلقائياً
- الـ APK يُرسل لتيليجرام مباشرة ✅

### 5. إعداد الهاتف
1. ثبّت Shizuku من [Play Store](https://play.google.com/store/apps/details?id=moe.shizuku.privileged.api)
2. فعّل Wireless Debugging (من خيارات المطور) وقم بتشغيل Shizuku.
3. ثبّت تطبيق Matchai واقبل صلاحية Shizuku.
4. **الربط بالسيرفر (جديد v7):**
   - افتح التطبيق -> قسم **Configuration**.
   - أدخل **Server URL** (رابط Railway) و **Device Secret**.
   - اضغط **Save & Restart**.
5. فعّل صلاحية الـ Accessibility لـ "Matchai Agent" من إعدادات الهاتف.
6. الهاتف متصل الآن! 🎉

---

## 💬 أمثلة على الأوامر

```
افتح واتساب
أرسل رسالة "مرحبا" لأحمد على واتساب
ابحث عن أغاني أم كلثوم على يوتيوب
التقط لقطة شاشة
شغل الواي فاي
اضبط الصوت على 8
افتح الإعدادات واذهب لإعدادات البطارية
ما حالة البطارية؟
اعرض قائمة التطبيقات المثبتة
```

---

## 📁 هيكل المشروع

```
matchai/
├── server/              # Railway backend
│   ├── main.py
│   ├── core/
│   │   ├── gemini_brain.py    # Gemini planner
│   │   ├── groq_executor.py   # Groq vision executor
│   │   ├── state_machine.py   # Task orchestrator
│   │   └── telegram_handler.py
│   ├── api/
│   │   ├── telegram_webhook.py
│   │   └── device_api.py
│   ├── Dockerfile
│   └── railway.toml
│
├── android/             # Android app (built on GitHub)
│   └── app/src/main/java/com/matchai/agent/
│       ├── AgentService.kt        # Core foreground service
│       ├── shizuku/ShizukuManager.kt
│       └── control/
│           ├── ScreenController.kt
│           ├── TouchController.kt
│           ├── TextController.kt
│           ├── AppController.kt
│           └── SystemController.kt
│
└── .github/workflows/
    └── build_apk.yml    # Auto-build & send to Telegram
```

---

## ⚠️ ملاحظات مهمة

- Shizuku يحتاج إعادة تفعيل بعد كل إعادة تشغيل للهاتف (إلا إذا كان الهاتف مروّتاً)
- للحصول على أفضل نتائج استخدم Android 11 أو أحدث
- مفاتيح API للاستخدام الشخصي فقط — لا تشاركها
