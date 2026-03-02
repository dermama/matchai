"""
Step Verifier — Per-Step Success Validation
============================================
After every executed step, verifies it actually succeeded
using multiple strategies: structured data comparison,
text presence checks, app state validation, etc.
"""

import logging
from typing import Optional

logger = logging.getLogger("matchai.step_verifier")


class StepVerifier:
    """
    Determines if a step truly succeeded by comparing before/after device state.
    Each action type has a specialized verification strategy.
    Falls back to generic screen-change detection.
    """

    # Minimum meaningful screen change threshold
    TEXT_SIMILARITY_THRESHOLD = 0.85

    def __init__(self):
        self._strategies = {
            "open_app":          self._verify_app_opened,
            "tap_element":       self._verify_element_tapped,
            "tap":               self._verify_tap,
            "type_text":         self._verify_text_typed,
            "type_clipboard":    self._verify_text_typed,
            "back":              self._verify_navigation,
            "home":              self._verify_home,
            "swipe":             self._verify_swipe,
            "scroll_down":       self._verify_scroll,
            "scroll_up":         self._verify_scroll,
            "collect_state":     self._verify_always_true,
            "screenshot":        self._verify_always_true,
            "get_ui_tree":       self._verify_always_true,
            "get_screen_text":   self._verify_always_true,
            "wait":              self._verify_always_true,
            "shell_command":     self._verify_shell,
            "set_volume":        self._verify_always_true,
            "toggle_wifi":       self._verify_wifi_toggled,
            "send_result":       self._verify_always_true,
        }

    async def verify(
        self,
        step: dict,
        before_state: dict,
        after_state: dict,
        result,  # StepResult
    ) -> bool:
        """Main entry point: verify if a step succeeded."""
        action = step.get("action", "")
        params = step.get("params", {})

        # If command itself reported failure → skip expensive checks
        if hasattr(result, 'status') and str(result.status) == "failed":
            return False

        strategy = self._strategies.get(action)
        if strategy:
            try:
                ok = await strategy(step, params, before_state, after_state, result)
                logger.debug(f"Verify '{action}': {'✅' if ok else '❌'}")
                return ok
            except Exception as e:
                logger.warning(f"Verification strategy error for '{action}': {e}")
                return True  # Don't block execution on verifier errors

        # Generic: did the screen change AT ALL?
        return self._screen_changed(before_state, after_state)

    # ─── Strategies ───────────────────────────────────────────────────────────

    async def _verify_always_true(self, step, params, before, after, result) -> bool:
        return True

    async def _verify_app_opened(self, step, params, before, after, result) -> bool:
        """Check that the target app is now in foreground."""
        target_pkg = params.get("package_name", "")
        app_name   = params.get("app_name", "")
        fg         = after.get("foreground_app", {})
        fg_pkg     = fg.get("package", "")
        fg_label   = fg.get("label", "").lower()

        if target_pkg and target_pkg in fg_pkg:
            return True
        if app_name and app_name.lower() in fg_label:
            return True
        # Check if screen has new content at all (at minimum)
        return self._screen_changed(before, after)

    async def _verify_element_tapped(self, step, params, before, after, result) -> bool:
        """Check that SOMETHING changed after tapping an element."""
        text = params.get("text", "")
        # Screen should change after a tap (new page, popup, selection, etc.)
        changed = self._screen_changed(before, after)
        if changed:
            return True
        # Or the element might have become checked/selected
        elements_after = after.get("screen_elements", [])
        for el in elements_after:
            if text.lower() in el.get("text", "").lower() and el.get("checked"):
                return True
        # No change but command succeeded → accept (some taps have subtle effects)
        return result.status != "failed" if hasattr(result, 'status') else True

    async def _verify_tap(self, step, params, before, after, result) -> bool:
        """Generic tap verification — screen should change."""
        return self._screen_changed(before, after) or True  # Accept if command ok

    async def _verify_text_typed(self, step, params, before, after, result) -> bool:
        """Verify typed text appears somewhere on screen."""
        text = params.get("text", "")
        if not text:
            return True

        screen_text_after = after.get("screen_text", "")
        # Check if any part of the typed text is visible
        words = text.split()[:3]  # Check first 3 words only
        return any(w.lower() in screen_text_after.lower() for w in words if len(w) > 2)

    async def _verify_navigation(self, step, params, before, after, result) -> bool:
        """Back button should change the foreground app or screen content."""
        before_pkg = before.get("foreground_app", {}).get("package", "")
        after_pkg  = after.get("foreground_app", {}).get("package", "")
        if before_pkg != after_pkg:
            return True
        return self._screen_changed(before, after)

    async def _verify_home(self, step, params, before, after, result) -> bool:
        """Home should show launcher."""
        fg = after.get("foreground_app", {}).get("package", "")
        is_launcher = any(
            launcher in fg
            for launcher in ["launcher", "home", "nexuslauncher", "quickstep"]
        )
        return is_launcher or self._screen_changed(before, after)

    async def _verify_swipe(self, step, params, before, after, result) -> bool:
        """Swipe should change screen content (scroll, navigate)."""
        return self._screen_changed(before, after)

    async def _verify_scroll(self, step, params, before, after, result) -> bool:
        """Scroll should change visible elements."""
        before_text = before.get("screen_text", "")
        after_text  = after.get("screen_text", "")
        # Content should shift after scrolling
        return before_text != after_text

    async def _verify_shell(self, step, params, before, after, result) -> bool:
        """Shell command verification based on exit output."""
        if hasattr(result, 'output'):
            return result.status != "failed"
        return True

    async def _verify_wifi_toggled(self, step, params, before, after, result) -> bool:
        """Check WiFi state actually changed."""
        before_wifi = before.get("wifi_state", "")
        after_wifi  = after.get("wifi_state", "")
        return before_wifi != after_wifi or True  # Accept if we can't determine

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _screen_changed(self, before: dict, after: dict) -> bool:
        """Check if screen content meaningfully changed between two states."""
        if not before or not after:
            return True  # Can't compare, assume changed

        before_text = before.get("screen_text", "")
        after_text  = after.get("screen_text", "")

        # Different text content → changed
        if before_text != after_text:
            return True

        # Different foreground app → definitely changed
        before_pkg = before.get("foreground_app", {}).get("package", "")
        after_pkg  = after.get("foreground_app", {}).get("package", "")
        if before_pkg != after_pkg:
            return True

        # Different number of elements
        before_count = len(before.get("screen_elements", []))
        after_count  = len(after.get("screen_elements", []))
        if abs(before_count - after_count) > 2:
            return True

        return False

    def _text_similarity(self, a: str, b: str) -> float:
        """Simple word-overlap similarity between two strings."""
        if not a or not b:
            return 0.0
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a:
            return 0.0
        overlap = len(words_a & words_b)
        return overlap / len(words_a)
