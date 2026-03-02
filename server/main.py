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
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
RAILWAY_PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
PORT = int(os.environ.get("PORT", 8000))


# ─── App Lifecycle ─────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("🚀 Matchai Server starting up...")

    # Register Telegram webhook
    if RAILWAY_PUBLIC_DOMAIN:
        webhook_url = f"https://{RAILWAY_PUBLIC_DOMAIN}/webhook/telegram"
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
    else:
        logger.warning("⚠️ No RAILWAY_PUBLIC_DOMAIN set, webhook not registered automatically")

    # Send startup notification
    handler = TelegramHandler()
    await handler.send_message(
        TELEGRAM_CHAT_ID,
        "🤖 *Matchai Agent Server Online!*\n\nأرسل أي أمر وسأنفذه على هاتفك فوراً.\n\nأمثلة:\n• `افتح واتساب`\n• `التقط لقطة شاشة`\n• `أرسل رسالة 'مرحبا' على واتساب لـ أحمد`",
    )

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
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "status": "error"},
    )
