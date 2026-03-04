"""
Telegram Formatter — Rich, Professional UX
==========================================
Live progress updates, inline keyboards, photo results,
and formatted reports sent beautifully through Telegram.
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger("matchai.formatter")


class TelegramFormatter:
    """
    Sends professional, rich Telegram messages with:
    - Live progress bars (edit existing message)
    - Inline keyboards for user actions
    - Step-by-step progress tracking
    - Rich result reports with photos
    """

    BASE_URL = "https://api.telegram.org/bot{token}"

    # Progress bar characters
    BAR_FILLED = "█"
    BAR_EMPTY  = "░"
    BAR_WIDTH  = 10

    def __init__(self, bot_token: str):
        self.token    = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._client  = httpx.AsyncClient(timeout=10)

    # ─── Core Methods ─────────────────────────────────────────────────────────

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None,
    ) -> Optional[int]:
        """Send a message. Returns message_id for later editing."""
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            resp = await self._client.post(f"{self.base_url}/sendMessage", json=payload)
            data = resp.json()
            if data.get("ok"):
                return data["result"]["message_id"]
        except Exception as e:
            logger.error(f"send_message error: {e}")
        return None

    async def edit_message(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        parse_mode: str = "Markdown",
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """Edit an existing message (for live progress updates)."""
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            resp = await self._client.post(f"{self.base_url}/editMessageText", json=payload)
            return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"edit_message error: {e}")
            return False

    async def send_photo(
        self,
        chat_id: str,
        photo_b64: str,
        caption: str = "",
        reply_markup: Optional[dict] = None,
    ) -> bool:
        """Send a base64-encoded photo."""
        import base64
        try:
            photo_bytes = base64.b64decode(photo_b64)
            files = {"photo": ("screenshot.jpg", photo_bytes, "image/jpeg")}
            data  = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "Markdown",
            }
            if reply_markup:
                import json
                data["reply_markup"] = json.dumps(reply_markup)
            resp = await self._client.post(
                f"{self.base_url}/sendPhoto", data=data, files=files
            )
            return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"send_photo error: {e}")
            return False

    async def send_typing(self, chat_id: str):
        """Show typing indicator."""
        try:
            await self._client.post(
                f"{self.base_url}/sendChatAction",
                json={"chat_id": chat_id, "action": "typing"},
            )
        except Exception:
            pass

    # ─── Progress Tracking ────────────────────────────────────────────────────

    def _build_progress_bar(self, current: int, total: int) -> str:
        if total == 0:
            return self.BAR_FILLED * self.BAR_WIDTH
        filled = int((current / total) * self.BAR_WIDTH)
        return self.BAR_FILLED * filled + self.BAR_EMPTY * (self.BAR_WIDTH - filled)

    def _build_progress_message(
        self,
        task_summary: str,
        steps_done: list[dict],
        current_step: Optional[str],
        total_steps: int,
        elapsed_sec: float,
    ) -> str:
        lines = [f"🤖 *{task_summary}*\n"]

        # Progress bar
        current_count = len(steps_done)
        bar = self._build_progress_bar(current_count, total_steps)
        pct = int((current_count / total_steps * 100)) if total_steps else 0
        lines.append(f"`{bar}` {pct}%\n")

        # Completed steps
        for step in steps_done[-5:]:  # Show last 5 completed
            status_icon = "✅" if step.get("success") else "❌"
            lines.append(f"{status_icon} {step.get('name', 'خطوة')}")

        # Current step
        if current_step:
            lines.append(f"🔄 *{current_step}*")

        # Remaining
        remaining = total_steps - current_count - 1
        if remaining > 0:
            lines.append(f"\n⏳ `{remaining}` خطوة متبقية | `{elapsed_sec:.0f}s`")

        return "\n".join(lines)

    class LiveProgress:
        """Context manager for live progress tracking on a single Telegram message."""

        def __init__(self, formatter, chat_id: str, task_summary: str, total_steps: int):
            self.formatter    = formatter
            self.chat_id      = chat_id
            self.task_summary = task_summary
            self.total_steps  = total_steps
            self.message_id   = None
            self.steps_done: list[dict] = []
            self.start_time   = time.time()

        async def start(self) -> "TelegramFormatter.LiveProgress":
            text = f"🤖 *{self.task_summary}*\n\n`{'░' * 10}` 0%\n\n⏳ جاري التحضير..."
            self.message_id = await self.formatter.send_message(self.chat_id, text)
            return self

        async def update(self, step_name: str, success: bool = True):
            self.steps_done.append({"name": step_name, "success": success})
            elapsed = time.time() - self.start_time
            text = self.formatter._build_progress_message(
                self.task_summary,
                self.steps_done,
                None,
                self.total_steps,
                elapsed,
            )
            if self.message_id:
                await self.formatter.edit_message(self.chat_id, self.message_id, text)

        async def step_running(self, step_name: str):
            elapsed = time.time() - self.start_time
            text = self.formatter._build_progress_message(
                self.task_summary,
                self.steps_done,
                step_name,
                self.total_steps,
                elapsed,
            )
            if self.message_id:
                await self.formatter.edit_message(self.chat_id, self.message_id, text)

        async def finish(self, success: bool, message: str, screenshot_b64: str = ""):
            elapsed = time.time() - self.start_time
            icon  = "✅" if success else "❌"
            final = f"{icon} *{self.task_summary}*\n\n{message}\n\n⏱️ `{elapsed:.1f}s`"
            markup = {
                "inline_keyboard": [[
                    {"text": "🛠️ التقرير التقني", "callback_data": "diagnostics"}
                ]]
            }
            if screenshot_b64:
                await self.formatter.send_photo(self.chat_id, screenshot_b64, caption=final, reply_markup=markup)
                # Delete progress message
                if self.message_id:
                    await self.formatter.delete_message(self.chat_id, self.message_id)
            else:
                if self.message_id:
                    # Add action buttons
                    markup = TelegramFormatter.build_inline_keyboard([
                        [{"text": "🔁 كرر", "callback_data": "repeat_task"},
                         {"text": "📸 شاشة", "callback_data": "screenshot"}],
                        [{"text": "📊 تقرير", "callback_data": "report"}],
                    ])
                    await self.formatter.edit_message(
                        self.chat_id, self.message_id, final, reply_markup=markup
                    )

    def create_live_progress(
        self, chat_id: str, task_summary: str, total_steps: int
    ) -> LiveProgress:
        return self.LiveProgress(self, chat_id, task_summary, total_steps)

    # ─── Inline Keyboards ─────────────────────────────────────────────────────

    @staticmethod
    def build_inline_keyboard(buttons: list[list[dict]]) -> dict:
        """Build inline keyboard markup."""
        return {"inline_keyboard": buttons}

    @staticmethod
    def main_menu_keyboard() -> dict:
        return TelegramFormatter.build_inline_keyboard([
            [{"text": "📸 لقطة شاشة", "callback_data": "screenshot"},
             {"text": "📊 حالة الهاتف", "callback_data": "status"}],
            [{"text": "🏠 الرئيسية", "callback_data": "home"},
             {"text": "↩️ رجوع", "callback_data": "back"}],
            [{"text": "📋 التطبيقات", "callback_data": "apps"}],
        ])

    # ─── Rich Result Messages ──────────────────────────────────────────────────

    async def send_task_result(
        self,
        chat_id: str,
        task_summary: str,
        success: bool,
        steps_done: int,
        steps_failed: int,
        duration_ms: float,
        result_message: str,
        screenshot_b64: str = "",
        retries: int = 0,
        replans: int = 0,
    ):
        """Send a final rich task result message."""
        icon    = "✅" if success else "⚠️"
        dur_sec = duration_ms / 1000

        text = (
            f"{icon} *{task_summary}*\n\n"
            f"{result_message}\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"✅ خطوات ناجحة: `{steps_done}`\n"
        )
        if steps_failed:
            text += f"❌ خطوات فاشلة: `{steps_failed}`\n"
        if retries:
            text += f"🔄 محاولات إعادة: `{retries}`\n"
        if replans:
            text += f"🗺️ إعادة تخطيط: `{replans}`\n"
        text += f"⏱️ المدة: `{dur_sec:.1f}s`"

        markup = self.build_inline_keyboard([
            [{"text": "🔁 كرر المهمة", "callback_data": "repeat_last"},
             {"text": "📸 لقطة شاشة", "callback_data": "screenshot"}],
        ])

        if screenshot_b64:
            await self.send_photo(chat_id, screenshot_b64, caption=text, reply_markup=markup)
        else:
            await self.send_message(chat_id, text, reply_markup=markup)

    async def send_error_message(
        self,
        chat_id: str,
        task_summary: str,
        error: str,
        suggestion: str = "",
    ):
        """Send a helpful error message."""
        text = (
            f"❌ *فشل التنفيذ*\n\n"
            f"المهمة: _{task_summary}_\n"
            f"السبب: `{error[:200]}`\n"
        )
        if suggestion:
            text += f"\n💡 *اقتراح:* {suggestion}"

        markup = self.build_inline_keyboard([
            [{"text": "🔁 حاول مجدداً", "callback_data": "retry_last"},
             {"text": "📸 شاشة الآن", "callback_data": "screenshot"}],
        ])
        await self.send_message(chat_id, text, reply_markup=markup)

    async def send_welcome(self, chat_id: str):
        """Welcome/help message."""
        text = (
            "🤖 *Matchai — وكيل الأندرويد الذكي*\n\n"
            "أنا أتحكم في هاتفك بأوامرك! إليك أمثلة:\n\n"
            "📱 `افتح واتساب وأرسل لأحمد مرحبا`\n"
            "🎬 `ابحث في يوتيوب عن أغاني أم كلثوم`\n"
            "📸 `لقطة شاشة`\n"
            "📞 `اتصل بسارة`\n"
            "⚙️ `شغّل الواي فاي`\n"
            "🔋 `ما حالة البطارية؟`\n\n"
            "أو أرسل أي أمر بالعربية! 🚀"
        )
        markup = self.main_menu_keyboard()
        await self.send_message(chat_id, text, reply_markup=markup)

    # ─── Utility ──────────────────────────────────────────────────────────────

    async def delete_message(self, chat_id: str, message_id: int):
        try:
            await self._client.post(
                f"{self.base_url}/deleteMessage",
                json={"chat_id": chat_id, "message_id": message_id},
            )
        except Exception:
            pass

    async def send_document(self, chat_id: str, content: str, filename: str, caption: str = ""):
        """Send text content as a document."""
        try:
            files = {"document": (filename, content.encode(), "text/plain")}
            data  = {"chat_id": chat_id, "caption": caption}
            await self._client.post(f"{self.base_url}/sendDocument", data=data, files=files)
        except Exception as e:
            logger.error(f"send_document error: {e}")

    async def close(self):
        await self._client.aclose()
