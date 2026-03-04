"""
Matchai Server - AI-Powered Android Agent Backend
Deployed on Railway | Telegram Bot + Gemini Brain + Groq Executor
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.telegram_webhook import router as telegram_router
from api.device_api import router as device_router
from api.health import router as health_router
from core.telegram_handler import TelegramHandler
from utils.logger import setup_logger

# ─── Setup Logging ────────────────────────────────────────────────────────────
logger = setup_logger("matchai.main")

# ─── Environment ──────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
PORT = int(os.environ.get("PORT", 8000))


# ─── App Lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("🚀 Matchai Server starting up...")

    # Register Telegram webhook in background to not block healthcheck
    if RAILWAY_PUBLIC_DOMAIN:
        # Prevent double https:// if user accidentally added it in Railway env vars
        clean_domain = RAILWAY_PUBLIC_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        webhook_url = f"https://{clean_domain}/webhook/telegram"
        async def register_webhook():
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook",
                        json={"url": webhook_url, "drop_pending_updates": True},
                    )
                    result = resp.json()
                    if result.get("ok"):
                        logger.info(f"✅ Telegram webhook set: {webhook_url}")
                    else:
                        logger.warning(f"⚠️ Webhook registration issue: {result}")
            except Exception as e:
                logger.error(f"❌ Webhook registration failed: {e}")

        asyncio.create_task(register_webhook())
    else:
        logger.warning("⚠️ No RAILWAY_PUBLIC_DOMAIN set, webhook not registered automatically")

    # Startup notifications sent in background
    yield

    logger.info("👋 Matchai Server shutting down...")


# ─── FastAPI App ───────────────────────────────────────────────────────────────
app = FastAPI(
    title="Matchai - AI Android Agent",
    description="AI-powered Android phone control via Telegram",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(telegram_router, prefix="/webhook")
app.include_router(device_router, prefix="/device")


# ─── Global Error Handler ─────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    
    if TELEGRAM_CHAT_ID and TELEGRAM_BOT_TOKEN:
        try:
            import traceback
            handler = TelegramHandler()
            tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            error_msg = (
                f"🚨 *خطأ داخلي في السيرفر (500)* 🚨\n\n"
                f"*المسار:* `{request.url.path}`\n"
                f"*الخطأ:* `{exc}`\n\n"
                f"*التفاصيل:*\n```python\n{tb_str[-1000:]}\n```"
            )
            asyncio.create_task(handler.send_message(TELEGRAM_CHAT_ID, error_msg))
        except Exception as notification_error:
            logger.error(f"Failed to send error to Telegram: {notification_error}")

    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "status": "error"},
    )
