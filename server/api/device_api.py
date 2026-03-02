"""
Device API — Communication bridge between server and Android app.
The Android app polls this endpoint to receive commands and posts results.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from core.state_machine import get_state_machine

logger = logging.getLogger("matchai.device_api")

router = APIRouter()

DEVICE_SECRET = os.environ.get("DEVICE_SECRET", "matchai_secret_2024")


def verify_device(x_device_secret: str | None = Header(default=None)):
    """Verify device authentication header."""
    if x_device_secret != DEVICE_SECRET:
        raise HTTPException(status_code=403, detail="Invalid device secret")


# ─── Models ───────────────────────────────────────────────────────────────────

class DeviceResult(BaseModel):
    command_id: str
    task_id: str
    success: bool
    screenshot_b64: str = ""
    # Structured data from ShizukuDataCollector (primary data source)
    structured_data: dict = {}   # foreground_app, screen_elements, screen_text, etc.
    ui_elements: list = []
    installed_apps: list = []
    device_info: dict = {}
    output: str = ""
    error: str = ""
    timestamp: int = 0



class DeviceRegister(BaseModel):
    device_id: str
    android_version: str
    shizuku_active: bool
    screen_width: int = 1080
    screen_height: int = 1920


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/poll")
async def poll_for_command(x_device_secret: str | None = Header(default=None)):
    """
    Long-polling endpoint: device calls this to receive next command.
    Blocks up to 30 seconds waiting for a command.
    """
    verify_device(x_device_secret)
    sm = get_state_machine()
    command = await sm.get_next_command(timeout=30.0)
    if command:
        logger.info(f"📤 Sending command to device: {command.get('action')}")
        return {"has_command": True, "command": command}
    return {"has_command": False, "command": None}


@router.post("/result")
async def receive_result(
    result: DeviceResult,
    x_device_secret: str | None = Header(default=None),
):
    """Device posts execution results here."""
    verify_device(x_device_secret)
    logger.info(
        f"📨 Result from device: cmd={result.command_id} "
        f"success={result.success} error={result.error[:50] if result.error else ''}"
    )
    sm = get_state_machine()
    await sm.receive_device_result(result.command_id, result.dict())
    return {"status": "received"}


@router.post("/register")
async def register_device(
    info: DeviceRegister,
    x_device_secret: str | None = Header(default=None),
):
    """Device registers itself when the app starts."""
    verify_device(x_device_secret)
    logger.info(
        f"📱 Device registered: {info.device_id} | "
        f"Android {info.android_version} | "
        f"Shizuku: {'✅' if info.shizuku_active else '❌'} | "
        f"Screen: {info.screen_width}x{info.screen_height}"
    )
    sm = get_state_machine()
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    await sm.telegram.send_message(
        chat_id,
        f"📱 *الهاتف متصل!*\n"
        f"• الجهاز: `{info.device_id}`\n"
        f"• أندرويد: `{info.android_version}`\n"
        f"• Shizuku: {'✅ نشط' if info.shizuku_active else '❌ غير نشط'}\n"
        f"• الشاشة: `{info.screen_width}x{info.screen_height}`\n\n"
        f"جاهز لاستقبال الأوامر! 🚀",
    )
    return {"status": "registered", "device_secret": DEVICE_SECRET}


@router.get("/status")
async def device_status(x_device_secret: str | None = Header(default=None)):
    """Get current task status."""
    verify_device(x_device_secret)
    sm = get_state_machine()
    task = sm.active_task
    return {
        "has_active_task": task is not None,
        "task_id": task.task_id if task else None,
        "task_state": task.state if task else None,
        "pending_commands": sm._pending_commands.qsize(),
    }
