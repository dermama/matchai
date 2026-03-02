"""
Telegram Webhook Router — Receives updates from Telegram.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.state_machine import get_state_machine

logger = logging.getLogger("matchai.webhook")

router = APIRouter()

TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# Special command shortcuts
COMMAND_SHORTCUTS = {
    "/status": "ما هي حالة الهاتف والبطارية والتخزين؟",
    "/screen": "التقط لقطة شاشة وأرسلها لي",
    "/home": "اضغط على زر الشاشة الرئيسية",
    "/back": "اضغط على زر الرجوع",
    "/apps": "اعرض قائمة التطبيقات المثبتة",
    "/stop": "__STOP__",
    "/help": "__HELP__",
}

HELP_TEXT = """🤖 *Matchai — وكيل الذكاء الاصطناعي للأندرويد*

*أوامر سريعة:*
/status — حالة الجهاز
/screen — لقطة شاشة فورية
/home — الشاشة الرئيسية
/back — زر الرجوع
/apps — قائمة التطبيقات
/help — هذه القائمة

*أمثلة على الأوامر الطبيعية:*
• افتح واتساب
• ابحث عن أغنية في يوتيوب
• أرسل رسالة 'أهلاً' لأحمد على تيليجرام
• شغل الواي فاي
• اضبط الصوت على 5
• افتح الإعدادات واذهب لإعدادات الشاشة
• التقط لقطة شاشة وأرسلها لي
• خفف السطوع إلى 50%"""


@router.post("/telegram")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram updates."""
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "no_message"}

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    # Security: only allow authorized chat
    if chat_id != TELEGRAM_CHAT_ID:
        logger.warning(f"⛔ Unauthorized access attempt from chat_id: {chat_id}")
        return {"status": "unauthorized"}

    if not text:
        return {"status": "no_text"}

    logger.info(f"📩 Telegram message from {chat_id}: {text[:80]}")

    sm = get_state_machine()

    # Handle special commands
    if text in COMMAND_SHORTCUTS:
        mapped = COMMAND_SHORTCUTS[text]
        if mapped == "__STOP__":
            if sm.active_task:
                sm.active_task = None
            await sm.telegram.send_message(chat_id, "⏹ تم إيقاف المهمة الحالية.")
            return {"status": "stopped"}
        elif mapped == "__HELP__":
            await sm.telegram.send_message(chat_id, HELP_TEXT)
            return {"status": "help_sent"}
        else:
            text = mapped

    # Execute command
    response = await sm.handle_user_command(text, chat_id)
    await sm.telegram.send_message(chat_id, response)
    return {"status": "processing"}
