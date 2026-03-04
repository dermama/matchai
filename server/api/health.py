"""Health check endpoint."""
import httpx
import os
import time
from fastapi import APIRouter
from core.state_machine import get_state_machine

router = APIRouter()
START_TIME = time.time()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")


@router.get("/health")
async def health():
    sm = get_state_machine()
    task = sm.active_task
    
    # Check telegram webhook status
    webhook_status = "unknown"
    webhook_url = "none"
    if TELEGRAM_BOT_TOKEN:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getWebhookInfo", timeout=3.0)
                data = resp.json()
                if data.get("ok"):
                    webhook_url = data["result"].get("url", "none")
                    webhook_status = "ok" if webhook_url else "not_set"
        except Exception as e:
            webhook_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "uptime_seconds": round(time.time() - START_TIME),
        "active_task": task.task_id if task else None,
        "task_state": task.state if task else None,
        "telegram_webhook": {
            "status": webhook_status,
            "url": webhook_url
        }
    }


@router.get("/")
async def root():
    return {"message": "🤖 Matchai AI Agent Server", "version": "1.0.0"}


@router.get("/crash_test")
async def crash_test():
    """Test endpoint to intentionally crash the server and verify Telegram error reporting."""
    raise RuntimeError("هذا انهيار متعمد لاختبار نظام إرسال الأخطاء إلى تليجرام!")

