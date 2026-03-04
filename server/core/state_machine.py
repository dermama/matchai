"""
Task State Machine (v2) — Professional Orchestration Engine
============================================================
Now integrates:
- AdaptiveExecutor (self-correcting loop with confidence scoring)
- MemoryManager (persistent AI learning)
- TemplateEngine (pre-built workflows)
- TelegramFormatter (rich progress + inline keyboards)
- StepVerifier (per-step success validation)
"""

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.gemini_brain import GeminiBrain
from core.groq_executor import GroqExecutor
from core.telegram_handler import TelegramHandler
from core.adaptive_executor import AdaptiveExecutor, StepStatus
from core.step_verifier import StepVerifier
from core.memory_manager import get_memory, MemoryManager
from core.task_templates import TemplateEngine
from core.telegram_formatter import TelegramFormatter

logger = logging.getLogger("matchai.state_machine")

TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


class TaskState(str, Enum):
    IDLE              = "idle"
    PLANNING          = "planning"
    EXECUTING         = "executing"
    WAITING_RESULT    = "waiting_result"
    ANALYZING_FAILURE = "analyzing_failure"
    REPLANNING        = "replanning"
    COMPLETED         = "completed"
    FAILED            = "failed"


@dataclass
class Task:
    """Represents a user task being executed."""
    task_id:          str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_command:     str = ""
    chat_id:          str = ""
    state:            TaskState = TaskState.IDLE
    plan:             dict = field(default_factory=dict)
    current_step_index: int = 0
    steps_results:    list = field(default_factory=list)
    retry_count:      int = 0
    max_retries:      int = 3
    created_at:       float = field(default_factory=time.time)
    last_screenshot_b64: str = ""
    installed_apps:   list = field(default_factory=list)
    device_info:      dict = field(default_factory=dict)
    from_template:    Optional[str] = None

    @property
    def current_step(self) -> dict | None:
        steps = self.plan.get("steps", [])
        if self.current_step_index < len(steps):
            return steps[self.current_step_index]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_step_index >= len(self.plan.get("steps", []))


class TaskStateMachine:
    """
    Professional AI orchestrator (v2).
    Integrates: Gemini 3 Flash + AdaptiveExecutor + MemoryManager
                + TemplateEngine + TelegramFormatter.
    """

    def __init__(self):
        self.gemini    = GeminiBrain()
        self.groq      = GroqExecutor()
        self.telegram  = TelegramHandler()

        # New intelligence layer
        self.memory    = get_memory()
        self.verifier  = StepVerifier()
        self.executor  = AdaptiveExecutor(self.gemini, self.groq, self)
        self.executor.set_verifier(self.verifier)
        self.templates = TemplateEngine(self.gemini)
        self.formatter = TelegramFormatter(os.environ.get("TELEGRAM_BOT_TOKEN", ""))

        # Single active task (one device)
        self.active_task: Task | None = None
        self.last_completed_task: Task | None = None

        # Command queue and result futures
        self._pending_commands: asyncio.Queue = asyncio.Queue()
        self._pending_results: dict[str, asyncio.Future] = {}
        self._result_store: dict[str, dict] = {}  # For wait_for_result

    # ─── Public API ───────────────────────────────────────────────────────────

    async def handle_user_command(self, user_command: str, chat_id: str) -> str:
        """Entry point: receive user Telegram command."""
        if self.active_task and self.active_task.state not in (
            TaskState.COMPLETED, TaskState.FAILED, TaskState.IDLE
        ):
            return (
                f"⏳ جاري تنفيذ: _{self.active_task.user_command[:50]}..._\n"
                f"انتظر حتى تنتهي."
            )

        task = Task(user_command=user_command, chat_id=chat_id)
        self.active_task = task
        logger.info(f"📋 New task [{task.task_id}]: {user_command[:80]}")

        asyncio.create_task(self._run_task(task))
        return f"🧠 فهمت الأمر... `[{task.task_id}]`"

    async def receive_device_result(self, command_id: str, result: dict):
        """Called when device POSTs /device/result."""
        # Store in result_store for wait_for_result()
        self._result_store[command_id] = result

        # Also resolve any waiting future
        future = self._pending_results.pop(command_id, None)
        if future and not future.done():
            future.set_result(result)

        # Update memory if structured data available
        if result.get("structured_data"):
            sd = result["structured_data"]
            # Defensive check: sometimes sd is deeply nested within multiple string layers (double serialization)
            loop_count = 0
            while isinstance(sd, str) and loop_count < 5:
                import json
                try:
                    parsed = json.loads(sd)
                    # If parsing returns the EXACT same string, we are stuck. Break out.
                    if parsed == sd:
                        break
                    sd = parsed
                except Exception as e:
                    logger.warning(f"Failed to deeply parse structured_data string: {e}")
                    break
                loop_count += 1
            
            # If it STILL ended up as a string after peeling layers, forcibly wrap it in a dict to prevent .get() crashes
            if isinstance(sd, str):
                sd = {"raw_text_payload": sd}
            if isinstance(sd, dict):
                pkg = sd.get("foreground_app", {}).get("package", "")
                if pkg:
                    self.memory.learn_from_device_state(pkg, sd)
                if result.get("installed_apps"):
                    self.memory.update_device_profile(
                        result.get("device_info", {}),
                        result["installed_apps"],
                    )

        logger.debug(f"📨 Result stored for [{command_id}]")

    async def get_next_command(self, timeout: float = 30.0) -> dict | None:
        """Called by device polling endpoint."""
        try:
            return await asyncio.wait_for(self._pending_commands.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def queue_command(self, command: dict):
        """Queue a command for the device (used by AdaptiveExecutor)."""
        await self._pending_commands.put(command)

    async def wait_for_result(self, command_id: str, timeout: float = 30.0) -> Optional[dict]:
        """Wait for a specific command result (used by AdaptiveExecutor)."""
        # Check if already arrived
        if command_id in self._result_store:
            return self._result_store.pop(command_id)

        # Create future and wait
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_results[command_id] = future
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            self._result_store.pop(command_id, None)
            return result
        except asyncio.TimeoutError:
            self._pending_results.pop(command_id, None)
            logger.warning(f"⏰ Timeout waiting for result [{command_id}]")
            return None

    # ─── Main Task Runner ─────────────────────────────────────────────────────

    async def _run_task(self, task: Task):
        """Full task lifecycle with all new intelligence components."""
        start = time.time()
        try:
            # ── 1. PLANNING ───────────────────────────────────────────────────
            task.state = TaskState.PLANNING
            await self.formatter.send_typing(task.chat_id)

            # Get initial device state (structured data preferred)
            device_state = await self._get_device_state(task)

            # Try template first (faster, battle-tested)
            plan = await self.templates.build_plan(task.user_command)
            if plan:
                task.from_template = plan.get("from_template")
                logger.info(f"📋 Using template: {task.from_template}")
                await self.formatter.send_message(
                    task.chat_id,
                    f"📋 *{plan.get('task_summary', task.user_command)[:80]}*\n"
                    f"🔢 {len(plan.get('steps', []))} خطوات ⚡ قالب محسّن",
                )
            else:
                # Fall back to Gemini planning with memory context
                memory_context = self.memory.build_context_for_gemini(task.user_command)
                plan = await self.gemini.plan_task(
                    user_command=task.user_command,
                    device_state=device_state,
                    installed_apps=memory_context.get("installed_apps"),
                )
                # Inject memory hints into prompt if Gemini didn't use them
                hint_count = len(memory_context.get("element_hints", {}))
                if hint_count:
                    logger.info(f"🧠 Memory context: {hint_count} app hints available")

                await self.formatter.send_message(
                    task.chat_id,
                    f"🗺️ *{plan.get('task_summary', task.user_command)[:80]}*\n"
                    f"🔢 {len(plan.get('steps', []))} خطوات | "
                    f"🎯 {plan.get('complexity', 'medium')}",
                )

            task.plan = plan
            steps_count = len(plan.get("steps", []))

            # ── 2. EXECUTING via AdaptiveExecutor ─────────────────────────────
            task.state = TaskState.EXECUTING

            # Create live progress tracker
            progress = self.formatter.create_live_progress(
                chat_id=task.chat_id,
                task_summary=plan.get("task_summary", task.user_command)[:60],
                total_steps=steps_count,
            )
            await progress.start()

            # Progress callback for live updates
            async def on_progress(step_name: str, completed: int, total: int, status: str):
                if "done" in status:
                    await progress.update(step_name, success="✅" in status)
                else:
                    await progress.step_running(step_name)

            # Execute with self-correcting adaptive loop
            ctx = await self.executor.execute_plan(
                plan=plan,
                task_id=task.task_id,
                progress_callback=on_progress,
            )

            # ── 3. FINALIZE ───────────────────────────────────────────────────
            success = len(ctx.failed_steps) == 0 or ctx.success_rate() >= 0.7
            task.state = TaskState.COMPLETED if success else TaskState.FAILED

            # Build final message
            if success:
                final_msg = await self.gemini.generate_final_message(
                    plan.get("task_summary", task.user_command),
                    [{"action": r.action, "status": r.status} for r in ctx.completed_steps],
                )
            else:
                failed_actions = ", ".join(r.action for r in ctx.failed_steps)
                final_msg = f"⚠️ أُكمِلت المهمة جزئياً. فشل في: {failed_actions}"

            # Finish with rich output
            await progress.finish(
                success=success,
                message=final_msg,
                screenshot_b64=task.last_screenshot_b64,
            )

            # Save to AI memory for future tasks
            self.memory.record_task(ctx)
            task.steps_results = ctx.completed_steps + ctx.failed_steps
            self.last_completed_task = task
            
            logger.info(
                f"✅ Task [{task.task_id}] done in "
                f"{(time.time()-start)*1000:.0f}ms | "
                f"success_rate={ctx.success_rate():.0%}"
            )

        except Exception as e:
            logger.error(f"❌ Task [{task.task_id}] crashed: {e}", exc_info=True)
            task.state = TaskState.FAILED
            await self.formatter.send_error_message(
                task.chat_id,
                task.user_command[:60],
                str(e)[:200],
                suggestion="حاول صياغة الأمر بشكل مختلف أو تحقق من أن الهاتف متصل.",
            )

    # ─── Device State Collection ──────────────────────────────────────────────

    async def _get_device_state(self, task: Task) -> dict:
        """
        Collect structured device state (PRIMARY) via Shizuku.
        Falls back to screenshot if needed.
        """
        try:
            command_id = f"init_{task.task_id}"
            await self.queue_command({
                "command_id": command_id,
                "task_id":    task.task_id,
                "action":     "collect_state",
                "params":     {"include_screenshot": False},
            })
            result = await self.wait_for_result(command_id, timeout=35.0)
            if result:
                if result.get("installed_apps"):
                    task.installed_apps = result["installed_apps"]
                    self.memory.update_device_profile(
                        result.get("device_info", {}),
                        task.installed_apps,
                    )
                if result.get("structured_data"):
                    return result["structured_data"]

        except Exception as e:
            logger.warning(f"collect_state failed: {e} — falling back to screenshot")

        # Fallback: screenshot
        try:
            ss_id = f"ss_{task.task_id}"
            await self.queue_command({
                "command_id": ss_id,
                "task_id":    task.task_id,
                "action":     "screenshot",
                "params":     {},
            })
            result = await self.wait_for_result(ss_id, timeout=25.0)
            if result and result.get("success"):
                task.last_screenshot_b64 = result.get("screenshot_b64", "")
                task.installed_apps = result.get("installed_apps", [])
                return {"screenshot_taken": True, "device_info": result.get("device_info", {})}
        except Exception as e:
            logger.warning(f"Screenshot fallback failed too: {e}")

        return {}


# ─── Singleton ────────────────────────────────────────────────────────────────

_state_machine: Optional[TaskStateMachine] = None


def get_state_machine() -> TaskStateMachine:
    global _state_machine
    if _state_machine is None:
        _state_machine = TaskStateMachine()
    return _state_machine
