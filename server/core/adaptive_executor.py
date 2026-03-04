"""
Adaptive Executor — Self-Correcting Execution Engine
=====================================================
The heart of the professional upgrade. Instead of a fixed plan,
each step is re-evaluated based on live device state. The AI
continuously adapts, corrects, and re-plans mid-execution.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("matchai.adaptive_executor")


class StepStatus(str, Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    SUCCESS    = "success"
    FAILED     = "failed"
    SKIPPED    = "skipped"
    REPLANNED  = "replanned"


class Confidence(float, Enum):
    HIGH   = 0.8   # Execute directly
    MEDIUM = 0.5   # Adjust step first
    LOW    = 0.2   # Full replan required


@dataclass
class StepResult:
    step_id: int
    action: str
    status: StepStatus
    output: str = ""
    error: str = ""
    duration_ms: float = 0
    confidence_before: float = 1.0
    retries: int = 0
    adjusted: bool = False
    device_state_after: dict = field(default_factory=dict)


@dataclass
class ExecutionContext:
    task_id: str
    original_goal: str
    completed_steps: list[StepResult] = field(default_factory=list)
    failed_steps: list[StepResult] = field(default_factory=list)
    total_retries: int = 0
    replan_count: int = 0
    start_time: float = field(default_factory=time.time)
    lessons_learned: list[str] = field(default_factory=list)

    def elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000

    def success_rate(self) -> float:
        total = len(self.completed_steps) + len(self.failed_steps)
        return len(self.completed_steps) / total if total else 0.0

    def to_summary(self) -> dict:
        return {
            "task_id":       self.task_id,
            "goal":          self.original_goal,
            "steps_done":    len(self.completed_steps),
            "steps_failed":  len(self.failed_steps),
            "retries":       self.total_retries,
            "replans":       self.replan_count,
            "duration_ms":   self.elapsed_ms(),
            "success_rate":  self.success_rate(),
            "lessons":       self.lessons_learned,
        }


class AdaptiveExecutor:
    """
    Self-correcting task executor.
    - HIGH confidence  → execute immediately
    - MEDIUM confidence → let Gemini adjust the step first
    - LOW confidence   → full replan from current state
    - FAILURE         → retry, adjust, or replan with fallback
    """

    MAX_ITERATIONS  = 40
    MAX_RETRIES     = 3
    MAX_REPLANS     = 4
    RETRY_DELAY_MS  = 1500

    def __init__(self, gemini_brain, groq_executor, state_machine):
        self.gemini   = gemini_brain
        self.groq     = groq_executor
        self.sm       = state_machine
        self._verifier = None   # Injected after import (circular dep guard)

    def set_verifier(self, verifier):
        self._verifier = verifier

    # ─── Main Entry Point ─────────────────────────────────────────────────────

    async def execute_plan(
        self,
        plan: dict,
        task_id: str,
        progress_callback=None,
    ) -> ExecutionContext:
        """
        Execute a Gemini-generated plan adaptively.
        progress_callback(step_name, completed, total, status) called on each step.
        """
        ctx = ExecutionContext(
            task_id=task_id,
            original_goal=plan.get("task_summary", ""),
        )
        steps = list(plan.get("steps", []))
        step_index = 0
        current_step_retries = 0

        logger.info(f"🚀 AdaptiveExecutor: starting '{ctx.original_goal}' ({len(steps)} steps)")

        for iteration in range(self.MAX_ITERATIONS):
            if step_index >= len(steps):
                logger.info(f"✅ All steps completed after {iteration} iterations")
                break
            if ctx.replan_count >= self.MAX_REPLANS:
                logger.warning("⚠️ Max replans reached — aborting")
                break

            step = steps[step_index]

            # ── 1. Collect live device state ──────────────────────────────────
            device_state = await self._collect_device_state()

            # ── 2. Calculate confidence for this step ─────────────────────────
            confidence = await self._calculate_confidence(step, device_state)

            if progress_callback:
                await progress_callback(
                    step.get("description", step.get("action")),
                    step_index, len(steps), "🔄 running",
                )

            # ── 3. Decision tree ──────────────────────────────────────────────
            if confidence >= Confidence.HIGH:
                result = await self._execute_step(step, task_id, ctx)

            elif confidence >= Confidence.MEDIUM:
                logger.info(f"⚠️ Medium confidence ({confidence:.2f}) — asking Gemini to adjust step")
                adjusted_step = await self._adjust_step(step, device_state)
                result = await self._execute_step(adjusted_step, task_id, ctx)
                result.adjusted = True

            else:  # LOW confidence → replan
                logger.warning(f"🔴 Low confidence ({confidence:.2f}) — triggering replan")
                new_steps = await self._trigger_replan(
                    original_goal=ctx.original_goal,
                    completed=ctx.completed_steps,
                    device_state=device_state,
                    failed_step=step,
                )
                if new_steps:
                    steps = ctx.completed_steps_as_plan() + new_steps
                    step_index = len(ctx.completed_steps)
                    ctx.replan_count += 1
                    ctx.lessons_learned.append(
                        f"Replanned at step {step.get('step_id')} due to low confidence"
                    )
                    continue
                else:
                    # Replan failed — try screenshot fallback
                    result = await self._screenshot_fallback(step, task_id, ctx)

            # ── 4. Verify step success ────────────────────────────────────────
            verified = await self._verify_step(step, device_state, result)

            if verified and result.status != StepStatus.FAILED:
                result.status = StepStatus.SUCCESS
                result.retries = current_step_retries
                ctx.completed_steps.append(result)
                logger.info(f"✅ Step {step.get('step_id')} '{step.get('action')}' verified OK")
                step_index += 1
                current_step_retries = 0

                if progress_callback:
                    await progress_callback(
                        step.get("description", step.get("action")),
                        step_index, len(steps), "✅ done",
                    )
            else:
                # Step failed or unverified
                current_step_retries += 1
                result.retries = current_step_retries
                self._log_step_failure(result, step, current_step_retries)

                if current_step_retries >= self.MAX_RETRIES:
                    # Check for fallback action
                    fallback = step.get("fallback_action")
                    if fallback and isinstance(fallback, dict):
                        logger.info(f"🔄 Trying fallback: {fallback.get('action')}")
                        fallback_result = await self._execute_step(fallback, task_id, ctx)
                        fallback_result.adjusted = True
                        ctx.completed_steps.append(fallback_result)
                        step_index += 1
                    else:
                        ctx.failed_steps.append(result)
                        step_index += 1  # Skip this step, continue
                        current_step_retries = 0
                        ctx.lessons_learned.append(
                            f"Step '{step.get('action')}' failed after {self.MAX_RETRIES} retries"
                        )
                else:
                    ctx.total_retries += 1
                    await asyncio.sleep(self.RETRY_DELAY_MS / 1000)
                    # Don't advance step_index → will retry

        logger.info(f"🏁 Execution done: {ctx.to_summary()}")
        return ctx

    # ─── Internal Methods ──────────────────────────────────────────────────────

    async def _collect_device_state(self) -> dict:
        """Request collect_state from Android device."""
        try:
            command_id = f"collect_{int(time.time()*1000)}"
            await self.sm.queue_command({
                "command_id": command_id,
                "task_id":    "internal",
                "action":     "collect_state",
                "params":     {"include_screenshot": False},
            })
            result = await self.sm.wait_for_result(command_id, timeout=35.0)
            if result and result.get("structured_data"):
                return result["structured_data"]
        except Exception as e:
            logger.warning(f"collect_state failed: {e}")
        return {}

    async def _calculate_confidence(self, step: dict, device_state: dict) -> float:
        """
        Calculate confidence that this step can be executed correctly
        given the current device state.
        """
        action = step.get("action", "")
        params = step.get("params", {})

        # Always-safe actions
        if action in ("wait", "back", "home", "recents", "collect_state"):
            return 1.0

        # System actions with no UI dependency
        if action in ("toggle_wifi", "toggle_bluetooth", "set_volume", "set_brightness",
                      "get_battery", "shell_command"):
            return 0.9

        # Check if target app is in foreground for UI actions
        if action in ("tap", "tap_element", "swipe", "type_text", "type_clipboard"):
            foreground = device_state.get("foreground_app", {})
            pkg = foreground.get("package", "")

            if not pkg:
                return 0.3  # Don't know what's on screen

            # Check if the element we need is visible
            if action == "tap_element":
                text = params.get("text", "")
                elements = device_state.get("screen_elements", [])
                found = any(
                    text.lower() in (e.get("text", "") + e.get("content_desc", "")).lower()
                    for e in elements
                )
                return 0.95 if found else 0.35

            # For tap with coordinates — check if screen is non-empty
            if action == "tap" and "x" in params and "y" in params:
                return 0.85 if pkg else 0.4

            # For text input — check keyboard is visible or editable field exists
            if action in ("type_text", "type_clipboard"):
                keyboard = device_state.get("keyboard_visible", False)
                elements = device_state.get("screen_elements", [])
                editable = any(e.get("editable") for e in elements)
                return 0.9 if (keyboard or editable) else 0.3

        # App open — always moderate (app might be missing)
        if action == "open_app":
            installed = device_state.get("installed_apps", [])
            name = params.get("app_name", params.get("package_name", ""))
            if installed:
                found = any(name.lower() in a.lower() for a in installed)
                return 0.9 if found else 0.6
            return 0.75

        # Screenshot and structured data collection — always safe
        if action in ("screenshot", "get_ui_tree", "get_screen_text", "get_foreground_app"):
            return 1.0

        return 0.7  # Default moderate confidence

    async def _adjust_step(self, step: dict, device_state: dict) -> dict:
        """Ask Gemini to adjust a step based on current device state."""
        try:
            prompt = f"""
الخطوة المخططة: {json.dumps(step, ensure_ascii=False)}
حالة الشاشة الحالية: {json.dumps(device_state, ensure_ascii=False)[:2000]}

الخطوة لا تتطابق تماماً مع الشاشة الحالية. كيف تعدّلها لتنجح؟
أرجع نفس التنسيق JSON مع التعديلات اللازمة فقط. لا تعليق.
"""
            response = await asyncio.to_thread(
                self.gemini.model.generate_content, prompt
            )
            adjusted = self.gemini._extract_json(response.text)
            logger.info(f"📝 Gemini adjusted step: {adjusted.get('action')}")
            return adjusted
        except Exception as e:
            logger.warning(f"Step adjustment failed: {e}")
            return step

    async def _execute_step(self, step: dict, task_id: str, ctx: ExecutionContext) -> StepResult:
        """Send step command to device and wait for result."""
        start = time.time()
        action = step.get("action", "unknown")

        try:
            command = {
                "command_id": f"cmd_{int(time.time()*1000)}",
                "task_id":    task_id,
                "action":     action,
                "params":     step.get("params", {}),
                "step_id":    step.get("step_id", 0),
            }
            await self.sm.queue_command(command)
            result_data = await self.sm.wait_for_result(
                command["command_id"], timeout=45.0
            )

            duration = (time.time() - start) * 1000

            if result_data:
                return StepResult(
                    step_id=step.get("step_id", 0),
                    action=action,
                    status=StepStatus.SUCCESS if result_data.get("success") else StepStatus.FAILED,
                    output=result_data.get("output", ""),
                    error=result_data.get("error", ""),
                    duration_ms=duration,
                    device_state_after=result_data.get("structured_data", {}),
                )
            else:
                return StepResult(
                    step_id=step.get("step_id", 0),
                    action=action,
                    status=StepStatus.FAILED,
                    error="No result received (timeout)",
                    duration_ms=duration,
                )
        except Exception as e:
            logger.error(f"Step execution error: {e}")
            return StepResult(
                step_id=step.get("step_id", 0),
                action=action,
                status=StepStatus.FAILED,
                error=str(e),
            )

    async def _verify_step(self, step: dict, before_state: dict, result: StepResult) -> bool:
        """Verify a step succeeded using the injected StepVerifier."""
        if self._verifier is None:
            return result.status == StepStatus.SUCCESS
        try:
            after_state = result.device_state_after or await self._collect_device_state()
            return await self._verifier.verify(step, before_state, after_state, result)
        except Exception as e:
            logger.warning(f"Verification error: {e}")
            return result.status == StepStatus.SUCCESS

    async def _trigger_replan(
        self,
        original_goal: str,
        completed: list,
        device_state: dict,
        failed_step: dict,
    ) -> list:
        """Ask Gemini to replan from current position."""
        try:
            completed_summary = [
                {"action": r.action, "status": r.status, "output": r.output[:100]}
                for r in completed
            ]
            prompt = f"""
الهدف الأصلي: {original_goal}
الخطوات المكتملة: {json.dumps(completed_summary, ensure_ascii=False)}
الخطوة الفاشلة: {json.dumps(failed_step, ensure_ascii=False)}
حالة الشاشة الحالية: {json.dumps(device_state, ensure_ascii=False)[:2000]}

أعد التخطيط من نقطة الفشل فقط. أرجع قائمة الخطوات المتبقية بتنسيق JSON:
{{"steps": [...]}}
"""
            response = await asyncio.to_thread(self.gemini.model.generate_content, prompt)
            new_plan = self.gemini._extract_json(response.text)
            return new_plan.get("steps", [])
        except Exception as e:
            logger.error(f"Replan failed: {e}")
            return []

    async def _screenshot_fallback(self, step: dict, task_id: str, ctx: ExecutionContext) -> StepResult:
        """Last resort: take screenshot and let Groq analyze then retry."""
        logger.warning("📸 Falling back to screenshot analysis")
        try:
            # Take screenshot
            screenshot_cmd = {
                "command_id": f"ss_{int(time.time()*1000)}",
                "task_id":    task_id,
                "action":     "screenshot",
                "params":     {},
            }
            await self.sm.queue_command(screenshot_cmd)
            ss_result = await self.sm.wait_for_result(screenshot_cmd["command_id"], timeout=25.0)

            if ss_result and ss_result.get("screenshot_b64"):
                b64 = ss_result["screenshot_b64"]
                analysis = await self.groq.analyze_screenshot(
                    b64,
                    f"كيف أنفذ هذه الخطوة على هذه الشاشة: {json.dumps(step, ensure_ascii=False)}",
                )
                logger.info(f"Groq screenshot analysis: {analysis.get('action_suggestion','')[:100]}")
                # Try executing based on Groq's suggestion
                if analysis.get("suggested_action"):
                    adjusted = {**step, **analysis["suggested_action"]}
                    return await self._execute_step(adjusted, task_id, ctx)

        except Exception as e:
            logger.error(f"Screenshot fallback error: {e}")

        return StepResult(
            step_id=step.get("step_id", 0),
            action=step.get("action", "unknown"),
            status=StepStatus.FAILED,
            error="All fallbacks exhausted",
        )

    def _log_step_failure(self, result: StepResult, step: dict, attempt: int):
        logger.warning(
            f"❌ Step '{result.action}' failed (attempt {attempt}/{self.MAX_RETRIES}): "
            f"{result.error[:100]}"
        )


# Allow ExecutionContext to generate remaining plan
def _completed_steps_as_plan(self) -> list:
    return []  # Completed steps don't need re-execution

ExecutionContext.completed_steps_as_plan = _completed_steps_as_plan
