"""
Groq Executor — Fast Vision Analysis & Command Translation
Uses Groq Llama 3.2 Vision for ultra-fast screenshot analysis.
"""

import json
import logging
import os
import re

from groq import Groq

logger = logging.getLogger("matchai.groq")

GROQ_API_KEY = os.environ["GROQ_API_KEY"]

# Vision model for screenshot analysis
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
# Fast text model for command analysis
TEXT_MODEL = "llama-3.3-70b-versatile"


class GroqExecutor:
    """
    Fast execution engine using Groq's ultra-low latency inference.
    Specializes in:
    - Screenshot analysis (what's on screen right now?)
    - UI element detection (where are buttons/fields?)
    - Step validation (did this step succeed?)
    - Command translation (abstract → concrete coordinates)
    """

    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY)

    def analyze_screenshot(
        self,
        image_base64: str,
        context: str = "",
        task_step: str = "",
    ) -> dict:
        """
        Analyze a screenshot to understand current screen state.
        Returns structured info about UI elements and suggested actions.
        """
        prompt = f"""تحليل هذه الصورة للشاشة بدقة عالية.

السياق: {context}
الخطوة الحالية المطلوب تنفيذها: {task_step}

أرجع JSON بالتنسيق التالي:
{{
  "app_open": "اسم التطبيق المفتوح أو 'home_screen' أو 'lock_screen'",
  "screen_description": "وصف موجز لما يظهر",
  "key_elements": [
    {{
      "type": "button|text_field|text|image|list|tab|menu",
      "label": "نص أو وصف العنصر",
      "x": إحداثية_x,
      "y": إحداثية_y,
      "width": العرض,
      "height": الارتفاع
    }}
  ],
  "suggested_action": {{
    "action": "اسم_الإجراء",
    "params": {{}},
    "reason": "سبب الاقتراح"
  }},
  "task_step_completed": true/false,
  "error_detected": null أو "وصف المشكلة"
}}

مهم جداً: الإحداثيات يجب أن تكون دقيقة وتمثل مركز العنصر المرئي فعلاً في الصورة.
لا تخترع عناصر غير موجودة في الصورة."""

        try:
            response = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=2048,
                temperature=0.1,
            )
            raw = response.choices[0].message.content
            return self._extract_json(raw)
        except Exception as e:
            logger.error(f"❌ Groq vision error: {e}", exc_info=True)
            return {
                "app_open": "unknown",
                "screen_description": "تعذر تحليل الشاشة",
                "key_elements": [],
                "suggested_action": None,
                "task_step_completed": False,
                "error_detected": str(e),
            }

    def verify_step_success(
        self,
        step: dict,
        before_screenshot_b64: str,
        after_screenshot_b64: str,
    ) -> dict:
        """
        Compare before/after screenshots to verify if a step succeeded.
        """
        prompt = f"""قارن هاتين الصورتين: قبل وبعد تنفيذ الخطوة.

الخطوة المنفذة: {json.dumps(step, ensure_ascii=False)}

الصورة الأولى: قبل التنفيذ
الصورة الثانية: بعد التنفيذ

أرجع JSON:
{{
  "success": true/false,
  "change_detected": true/false,
  "change_description": "ما الذي تغير",
  "reason": "لماذا نجحت أو فشلت الخطوة",
  "next_recommended_action": null أو "الإجراء التالي المقترح"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{before_screenshot_b64}"
                                },
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{after_screenshot_b64}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=1024,
                temperature=0.1,
            )
            return self._extract_json(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"❌ Groq verify error: {e}")
            return {"success": False, "reason": str(e), "change_detected": False}

    def find_element_coordinates(
        self, image_base64: str, element_description: str
    ) -> dict | None:
        """
        Find exact coordinates of a specific UI element in the screenshot.
        Used when coordinates are unknown.
        """
        prompt = f"""ابحث عن العنصر التالي في هذه الصورة وأعطني إحداثياته الدقيقة:

العنصر المطلوب: {element_description}

أرجع JSON:
{{
  "found": true/false,
  "x": إحداثية_x_لمركز_العنصر,
  "y": إحداثية_y_لمركز_العنصر,
  "confidence": 0.0-1.0,
  "alternative_elements": [
    {{"label": "اسم بديل", "x": 0, "y": 0}}
  ]
}}

إذا لم تجد العنصر بوضوح، أعد found: false."""

        try:
            response = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=512,
                temperature=0.05,
            )
            result = self._extract_json(response.choices[0].message.content)
            return result if result.get("found") else None
        except Exception as e:
            logger.error(f"❌ Groq find element error: {e}")
            return None

    def analyze_failure(
        self, image_base64: str, failed_step: dict, error_message: str
    ) -> dict:
        """
        Analyze why a step failed and suggest recovery actions.
        """
        prompt = f"""تحليل سبب فشل الخطوة وتقديم حل.

الخطوة الفاشلة: {json.dumps(failed_step, ensure_ascii=False)}
رسالة الخطأ: {error_message}

انظر للصورة وأخبرني:
{{
  "failure_reason": "السبب الرئيسي للفشل",
  "screen_state": "وصف ما يظهر على الشاشة",
  "recovery_actions": [
    {{
      "action": "اسم_الإجراء",
      "params": {{}},
      "description": "وصف الإجراء"
    }}
  ],
  "should_retry": true/false,
  "should_replan": true/false
}}"""

        try:
            response = self.client.chat.completions.create(
                model=VISION_MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_base64}"
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                max_tokens=1024,
                temperature=0.1,
            )
            return self._extract_json(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"❌ Groq failure analysis error: {e}")
            return {
                "failure_reason": str(e),
                "recovery_actions": [],
                "should_retry": False,
                "should_replan": True,
            }

    def translate_natural_action(self, natural_command: str, context: dict) -> dict:
        """
        Translate a natural language action into a concrete device command.
        Uses fast text model (no vision needed).
        """
        prompt = f"""حوّل هذا الأمر الطبيعي إلى أمر تقني دقيق.

الأمر: {natural_command}
السياق الحالي: {json.dumps(context, ensure_ascii=False)}

الإجراءات المتاحة: screenshot, tap, swipe, long_press, double_tap, type_text, type_clipboard, 
clear_field, back, home, recents, open_app, force_stop_app, list_apps, open_notifications, 
clear_notifications, set_volume, toggle_wifi, toggle_bluetooth, toggle_flashlight, 
set_brightness, get_battery, get_storage, shell_command, wait, send_result

أرجع JSON:
{{
  "action": "اسم_الإجراء",
  "params": {{}},
  "explanation": "شرح الترجمة"
}}"""

        try:
            response = self.client.chat.completions.create(
                model=TEXT_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.1,
            )
            return self._extract_json(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"❌ Groq translate error: {e}")
            return {"action": "screenshot", "params": {}, "explanation": "fallback"}

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from Groq response."""
        text = re.sub(r"```json\n?", "", text)
        text = re.sub(r"```\n?", "", text)
        text = text.strip()

        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])

        raise ValueError(f"No JSON in response: {text[:150]}")
