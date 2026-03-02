"""
Task State Machine — Orchestrates the full execution lifecycle.
States: IDLE → PLANNING → EXECUTING → WAITING → ANALYZING → COMPLETED/FAILED
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.gemini_brain import GeminiBrain
from core.groq_executor import GroqExecutor
from core.telegram_handler import TelegramHandler

logger = logging.getLogger("matchai.state_machine")


class TaskState(str, Enum):
    IDLE = "idle"
    PLANNING = "planning"
    EXECUTING = "executing"
    WAITING_RESULT = "waiting_result"
    ANALYZING_FAILURE = "analyzing_failure"
    REPLANNING = "replanning"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """Represents a single user task being executed."""
    task_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_command: str = ""
    chat_id: str = ""
    state: TaskState = TaskState.IDLE
    plan: dict = field(default_factory=dict)
    current_step_index: int = 0
    steps_results: list = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    last_screenshot_b64: str = ""
    installed_apps: list = field(default_factory=list)
    device_info: dict = field(default_factory=dict)

    @property
    def current_step(self) -> dict | None:
        steps = self.plan.get("steps", [])
        if self.current_step_index < len(steps):
            return steps[self.current_step_index]
        return None

    @property
    def is_complete(self) -> bool:
        steps = self.plan.get("steps", [])
        return self.current_step_index >= len(steps)


class TaskStateMachine:
    """
    Central orchestrator for the AI agent workflow.
    Manages state transitions and coordinates Gemini + Groq + Device.
    """

    def __init__(self):
        self.gemini = GeminiBrain()
        self.groq = GroqExecutor()
        self.telegram = TelegramHandler()

        # Active task (single device = single task at a time)
        self.active_task: Task | None = None

        # Pending commands queue for device polling
        self._pending_commands: asyncio.Queue = asyncio.Queue()
        # Results from device
        self._pending_results: dict[str, asyncio.Future] = {}

    # ─── Public API ────────────────────────────────────────────────────────────

    async def handle_user_command(self, user_command: str, chat_id: str) -> str:
        """Entry point: receive user command from Telegram."""
        if self.active_task and self.active_task.state not in (
            TaskState.COMPLETED, TaskState.FAILED, TaskState.IDLE
        ):
            return f"⏳ جاري تنفيذ مهمة أخرى: {self.active_task.user_command[:50]}...\nانتظر حتى تنتهي."

        task = Task(user_command=user_command, chat_id=chat_id)
        self.active_task = task
        logger.info(f"📋 New task [{task.task_id}]: {user_command[:80]}")

        # Run in background
        asyncio.create_task(self._run_task(task))
        return f"🧠 جاري التخطيط... `[{task.task_id}]`"

    async def receive_device_result(self, command_id: str, result: dict):
        """Called when device sends back execution result."""
        future = self._pending_results.pop(command_id, None)
        if future and not future.done():
            future.set_result(result)
            logger.debug(f"📨 Result received for command [{command_id}]")
        else:
            logger.warning(f"⚠️ No pending future for command [{command_id}]")

    async def get_next_command(self, timeout: float = 30.0) -> dict | None:
        """Called by device polling endpoint to get next command."""
        try:
            cmd = await asyncio.wait_for(self._pending_commands.get(), timeout=timeout)
            return cmd
        except asyncio.TimeoutError:
            return None

    # ─── Internal State Machine ────────────────────────────────────────────────

    async def _run_task(self, task: Task):
        """Main task execution loop."""
        try:
            # ── PLANNING ──────────────────────────────────────────────────────
            task.state = TaskState.PLANNING
            await self.telegram.send_typing(task.chat_id)

            # Get current screen state first for context
            device_state = await self._get_quick_device_state(task)

            plan = await self.gemini.plan_task(
                user_command=task.user_command,
                device_state=device_state,
                installed_apps=task.installed_apps or None,
            )
            task.plan = plan

            steps_count = len(plan.get("steps", []))
            complexity = plan.get("complexity", "medium")

            await self.telegram.send_message(
                task.chat_id,
                f"📋 *الخطة جاهزة* `[{task.task_id}]`\n"
                f"📌 {plan.get('task_summary', task.user_command)}\n"
                f"🔢 {steps_count} خطوات | 🎯 {complexity}",
            )

            # ── EXECUTING ─────────────────────────────────────────────────────
            task.state = TaskState.EXECUTING
            await self._execute_plan(task)

        except Exception as e:
            logger.error(f"❌ Task [{task.task_id}] crashed: {e}", exc_info=True)
            task.state = TaskState.FAILED
            await self.telegram.send_message(
                task.chat_id,
                f"❌ خطأ غير متوقع في تنفيذ المهمة:\n`{str(e)[:200]}`"
            )

    async def _execute_plan(self, task: Task):
        """Execute plan steps sequentially with error recovery."""
        steps = task.plan.get("steps", [])

        while task.current_step_index < len(steps):
            step = steps[task.current_step_index]
            action = step.get("action", "")
            params = step.get("params", {})

            logger.info(
                f"▶ Task [{task.task_id}] Step {step.get('step_id')}/{len(steps)}: {action}"
            )

            # ── Handle send_result specially ──────────────────────────────────
            if action == "send_result":
                msg = params.get("message", "✅ تم تنفيذ المهمة.")
                await self.telegram.send_message(task.chat_id, msg)

                # If there's a screenshot to send
                if task.last_screenshot_b64:
                    await self.telegram.send_photo(task.chat_id, task.last_screenshot_b64)

                task.state = TaskState.COMPLETED
                task.current_step_index += 1
                logger.info(f"✅ Task [{task.task_id}] completed successfully.")
                return

            # ── Send command to device ────────────────────────────────────────
            command_id = str(uuid.uuid4())[:8]
            command = {
                "command_id": command_id,
                "task_id": task.task_id,
                "step_id": step.get("step_id"),
                "action": action,
                "params": params,
            }

            # Enqueue for device polling
            task.state = TaskState.WAITING_RESULT
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending_results[command_id] = future
            await self._pending_commands.put(command)

            # Wait for device result (with timeout)
            try:
                result = await asyncio.wait_for(future, timeout=60.0)
            except asyncio.TimeoutError:
                result = {"success": False, "error": "timeout: device did not respond in 60s"}

            logger.debug(f"Device result for step {step.get('step_id')}: {result}")

            # ── Handle screenshot result ──────────────────────────────────────
            if action == "screenshot" and result.get("success"):
                screenshot_b64 = result.get("screenshot_b64", "")
                task.last_screenshot_b64 = screenshot_b64

                # Analyze with Groq Vision
                if screenshot_b64:
                    next_step = steps[task.current_step_index + 1] if task.current_step_index + 1 < len(steps) else {}
                    analysis = self.groq.analyze_screenshot(
                        screenshot_b64,
                        context=task.plan.get("task_summary", ""),
                        task_step=next_step.get("description", ""),
                    )
                    logger.info(f"📊 Screen: {analysis.get('app_open')} | {analysis.get('screen_description', '')[:60]}")
                    result["screen_analysis"] = analysis

            # ── Handle step result ────────────────────────────────────────────
            task.steps_results.append({
                "step": step,
                "result": result,
            })

            if result.get("success", False):
                task.retry_count = 0
                task.current_step_index += 1
            else:
                # Step failed — analyze and recover
                await self._handle_step_failure(task, step, result)

                # Check if recovery was successful (state changed)
                if task.state == TaskState.FAILED:
                    return

        # All steps done without explicit send_result
        if task.state != TaskState.COMPLETED:
            task.state = TaskState.COMPLETED
            final_msg = await self.gemini.generate_final_message(
                task.plan.get("task_summary", task.user_command),
                task.steps_results,
            )
            await self.telegram.send_message(task.chat_id, final_msg)

    async def _handle_step_failure(self, task: Task, step: dict, result: dict):
        """Handle a failed step with intelligent recovery."""
        task.retry_count += 1
        error_msg = result.get("error", "Unknown error")

        logger.warning(
            f"⚠️ Task [{task.task_id}] Step {step.get('step_id')} failed "
            f"(attempt {task.retry_count}/{task.max_retries}): {error_msg}"
        )

        if task.retry_count >= task.max_retries:
            task.state = TaskState.FAILED
            await self.telegram.send_message(
                task.chat_id,
                f"❌ فشل تنفيذ الخطوة بعد {task.max_retries} محاولات:\n"
                f"الخطوة: {step.get('description', step.get('action'))}\n"
                f"السبب: `{error_msg[:200]}`"
            )
            return

        # Analyze failure with Groq vision if we have a screenshot
        task.state = TaskState.ANALYZING_FAILURE
        if task.last_screenshot_b64:
            failure_analysis = self.groq.analyze_failure(
                task.last_screenshot_b64, step, error_msg
            )
            logger.info(f"🔍 Failure analysis: {failure_analysis.get('failure_reason')}")

            if failure_analysis.get("should_replan"):
                # Ask Gemini to re-plan
                task.state = TaskState.REPLANNING
                new_plan = await self.gemini.replan_after_failure(
                    original_plan=task.plan,
                    failed_step=step,
                    failure_reason=error_msg,
                    screen_analysis=failure_analysis,
                )
                if new_plan.get("steps"):
                    # Insert recovery steps at current position
                    remaining = task.plan["steps"][task.current_step_index + 1:]
                    task.plan["steps"] = (
                        task.plan["steps"][:task.current_step_index]
                        + new_plan["steps"]
                        + remaining
                    )
                    task.retry_count = 0
                    task.state = TaskState.EXECUTING
                    return

            # Try recovery actions
            recovery_actions = failure_analysis.get("recovery_actions", [])
            if recovery_actions:
                for rec_action in recovery_actions[:2]:
                    # Insert recovery steps
                    recovery_step = {
                        "step_id": f"r{task.current_step_index}",
                        "action": rec_action.get("action"),
                        "params": rec_action.get("params", {}),
                        "description": f"[استرداد] {rec_action.get('description', '')}",
                        "requires_screenshot_after": True,
                        "fallback_action": None,
                    }
                    task.plan["steps"].insert(task.current_step_index, recovery_step)

                task.state = TaskState.EXECUTING
                return

        # Simple retry
        logger.info(f"🔄 Retrying step {step.get('step_id')}...")
        await asyncio.sleep(1)
        task.state = TaskState.EXECUTING

    async def _get_quick_device_state(self, task: Task) -> dict:
        """Take a quick screenshot to understand device state before planning."""
        try:
            command_id = str(uuid.uuid4())[:8]
            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending_results[command_id] = future
            await self._pending_commands.put({
                "command_id": command_id,
                "task_id": task.task_id,
                "action": "screenshot",
                "params": {},
            })
            result = await asyncio.wait_for(future, timeout=15.0)
            if result.get("success"):
                task.last_screenshot_b64 = result.get("screenshot_b64", "")
                task.installed_apps = result.get("installed_apps", [])
                task.device_info = result.get("device_info", {})
                return {
                    "screenshot_taken": True,
                    "device_info": task.device_info,
                }
        except asyncio.TimeoutError:
            logger.warning("⚠️ Device state check timed out")
        except Exception as e:
            logger.warning(f"⚠️ Device state check error: {e}")
        return {"screenshot_taken": False}


# ─── Singleton ────────────────────────────────────────────────────────────────
_state_machine: TaskStateMachine | None = None


def get_state_machine() -> TaskStateMachine:
    global _state_machine
    if _state_machine is None:
        _state_machine = TaskStateMachine()
    return _state_machine
