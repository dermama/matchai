"""
Telegram Handler — Sends messages, photos, and updates to users.
"""

import base64
import logging
import os
import httpx

logger = logging.getLogger("matchai.telegram")

class TelegramHandler:
    """Handles all outgoing Telegram communications."""

    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not self.token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not found in environment")

    @property
    def base_url(self) -> str | None:
        if not self.token:
            return None
        return f"https://api.telegram.org/bot{self.token}"

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        parse_mode: str = "Markdown",
    ) -> bool:
        url = self.base_url
        if not url:
            logger.debug(f"🚫 Skip send_message (No Token): {text[:50]}...")
            return False
        try:
            resp = await self.client.post(
                f"{url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "reply_markup": reply_markup,
                },
            )
            return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ Send message error: {e}")
            return False

    async def send_photo(
        self,
        chat_id: str | int,
        image_base64: str,
        caption: str = "",
    ) -> bool:
        """Send a screenshot to the user."""
        url = self.base_url
        if not url:
            return False
        try:
            image_bytes = base64.b64decode(image_base64)
            resp = await self.client.post(
                f"{url}/sendPhoto",
                data={"chat_id": str(chat_id), "caption": caption},
                files={"photo": ("screenshot.png", image_bytes, "image/png")},
            )
            return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ Send photo error: {e}")
            return False

    async def send_document(
        self,
        chat_id: str | int,
        file_bytes: bytes,
        filename: str,
        caption: str = "",
    ) -> bool:
        url = self.base_url
        if not url:
            return False
        try:
            resp = await self.client.post(
                f"{url}/sendDocument",
                data={"chat_id": str(chat_id), "caption": caption},
                files={"document": (filename, file_bytes, "application/octet-stream")},
            )
            return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ Send document error: {e}")
            return False

    async def send_typing(self, chat_id: str | int) -> None:
        """Show 'typing...' indicator."""
        url = self.base_url
        if not url:
            return
        try:
            await self.client.post(
                f"{url}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
        except Exception:
            pass

    async def edit_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        parse_mode: str = "Markdown",
    ) -> bool:
        url = self.base_url
        if not url:
            return False
        try:
            resp = await self.client.post(
                f"{url}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": parse_mode,
                },
            )
            return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"❌ Edit message error: {e}")
            return False
