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

TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "missing_chat_id")

# Special command shortcuts
COMMAND_SHORTCUTS = {
    "/status": "ما هي حالة الهاتف والبطارية والتخزين؟",
    "/screen": "التقط لقطة شاشة وأرسلها لي",
    "/home": "اضغط على زر الشاشة الرئيسية",
    "/back": "اضغط على زر الرجوع",
    "/apps": "اعرض قائمة التطبيقات المثبتة",
    "/stop": "__STOP__",
    "/help": "__HELP__",
    "/diagnostics": "__DIAGNOSTICS__",
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

    # Handle callback queries (buttons)
    callback_query = update.get("callback_query")
    if callback_query:
        await handle_callback_query(callback_query)
        return {"status": "callback_handled"}

    message = update.get("message") or update.get("edited_message")
    if not message:
        return {"status": "no_message"}

    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "").strip()

    # Security: only allow authorized chat
    if chat_id != TELEGRAM_CHAT_ID:
        logger.warning(f"⛔ Unauthorized access attempt from chat_id: {chat_id}")
        
        # Send a helpful message back so the user knows what's wrong
        if chat_id:
            try:
                import httpx
                import asyncio
                async def notify_unauthorized():
                    async with httpx.AsyncClient() as client:
                        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
                        msg = f"⛔ عذراً، أنت لست المالك المعتمد لهذا البوت.\n\nمعرف الدردشة الخاص بك هو: `{chat_id}`\n\nإذا كنت أنت المالك، يرجى نسخ هذا الرقم ووضعه في متغير TELEGRAM_CHAT_ID في إعدادات السيرفر (Railway)."
                        await client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"}
                        )
                asyncio.create_task(notify_unauthorized())
            except Exception:
                pass
                
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
        elif mapped == "__DIAGNOSTICS__":
            await send_diagnostics(chat_id)
            return {"status": "diagnostics_sent"}
        else:
            text = mapped

    # Execute command
    response = await sm.handle_user_command(text, chat_id)
    await sm.telegram.send_message(chat_id, response)
    return {"status": "processing"}


async def handle_callback_query(callback: dict):
    """Handle button clicks."""
    id = callback.get("id")
    data = callback.get("data")
    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    # Answer callback to remove loading state
    import httpx
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={"callback_query_id": id})

    if data == "diagnostics":
        await send_diagnostics(chat_id)


async def send_diagnostics(chat_id: str):
    """Generate and send a technical diagnostic report."""
    sm = get_state_machine()
    task = sm.last_completed_task if hasattr(sm, 'last_completed_task') else None
    
    if not task:
        await sm.telegram.send_message(chat_id, "❌ لا توجد بيانات تشخيصية متاحة للمهمة الأخيرة.")
        return

    import json
    report = [
        "🛠️ *التقرير التشخيصي للمهمة الأخيرة*",
        f"🆔 معرف المهمة: `{task.task_id}`",
        f"📝 الأمر: `{task.user_command}`",
        f"📊 الخطة: {len(task.plan.get('steps', []))} خطوات",
        f"📦 القالب: `{task.from_template or 'تخطيط Gemini'}`",
        "\n📝 *نتائج الخطوات:*",
    ]
    
    for i, res in enumerate(task.steps_results):
        status = "✅" if "success" in str(res.status).lower() else "❌"
        report.append(f"{i+1}. {status} `{res.action}`: {res.output[:100]}")
        if res.error:
            report.append(f"   ⚠️ أخطاء: `{res.error[:100]}`")

    full_text = "\n".join(report)
    
    # If too long, send as document
    if len(full_text) > 4000:
        await sm.telegram.send_message(chat_id, "📝 التقرير طويل جداً، سأرسله كملف...")
        raw_json = json.dumps({
            "task_id": task.task_id,
            "command": task.user_command,
            "plan": task.plan,
            "results": [str(r) for r in task.steps_results]
        }, indent=2, ensure_ascii=False)
        await sm.formatter.send_document(chat_id, raw_json, f"diagnostics_{task.task_id}.json", "📦 بيانات التشخيص الكاملة")
    else:
        await sm.telegram.send_message(chat_id, full_text)
