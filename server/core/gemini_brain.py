"""
Gemini Brain — Strategic Task Planner
Uses Gemini 2.5 Flash Preview to decompose user commands into executable steps.
Primary data source: Shizuku structured data (UI tree, app info).
Fallback: screenshot vision analysis via Groq.
"""

import json
import logging
import os
import re
from typing import Any

import google.generativeai as genai

logger = logging.getLogger("matchai.gemini")

# ─── Configure Gemini ─────────────────────────────────────────────────────────
genai.configure(api_key=os.environ["GEMINI_API_KEY"])

GEMINI_MODEL = "gemini-3-flash-preview"

SYSTEM_PROMPT = """أنت Matchai — وكيل ذكاء اصطناعي متخصص في التحكم الكامل بهواتف الأندرويد.

لديك وصول كامل للهاتف عبر Shizuku (ADB level). تعمل بمبدأ البيانات الهيكلية أولاً ثم الصور احتياطياً.

══ الإجراءات المتاحة (actions) ══

[جمع بيانات الهاتف عبر Shizuku - الأسرع والأدق]
- collect_state: جمع حالة كاملة للهاتف (UI tree, مجلدات التطبيقات, نص الشاشة, إشعارات)
  params: {"include_screenshot": false} → true فقط إذا كانت البيانات الهيكلية غير كافية
- get_ui_tree: شجرة UI الشاشة الحالية بالتفصيل
- get_screen_text: كل النصوص المرئية على الشاشة
- get_foreground_app: التطبيق المفتوح حالياً مع Package name
- get_app_details: تفاصيل تطبيق محدد params: {"package_name"}
- get_all_apps: قائمة جميع التطبيقات + Package names

[التحكم بالإدخال - ذكي ولا يحتاج إحداثيات]
- tap_element: النقر على عنصر بنصه params: {"text": "نص الزر"}  (ابحث عنخ تلقائياً)
- find_element: البحث عن عنصر والنقر عليه params: {"text": "نص العنصر"}

[التحكم بالإدخال - تحتاج إحداثيات]
- tap: النقر بإحداثيات params: {"x", "y"}
- swipe: السحب params: {"x1","y1","x2","y2","duration_ms"}
- long_press: ضغط طويل params: {"x", "y"}
- double_tap: نقر مزدوج params: {"x", "y"}
- scroll_down / scroll_up: تمرير الشاشة

[إدخال النص]
- type_text: كتابة نص إنجليزي params: {"text"}
- type_clipboard: كتابة نص عربي أو خاص params: {"text"}
- clear_field: مسح حقل النص
- press_enter: ضغط Enter

[التنقل]
- back: زر الرجوع
- home: الشاشة الرئيسية
- recents: قائمة التطبيقات المفتوحة
- open_app: فتح تطبيق params: {"app_name" أو "package_name"}
- force_stop_app: إغلاق تطبيق params: {"package_name"}

[النظام]
- set_volume: صوت params: {"level": 0-15}
- set_brightness: سطوع params: {"level": 0-255}
- toggle_wifi / toggle_bluetooth / toggle_flashlight
- open_notifications / close_notifications / clear_notifications
- get_battery / get_storage / get_running_apps
- shell_command: أمر ADB مباشر params: {"command"}
- wait: انتظار params: {"ms"}
- send_result: رسالة نهائية للمستخدم params: {"message"}

[احتياطي فقط]
- screenshot: لقطة شاشة (استخدمها فقط عند فشل collect_state)

══ قواعد حديدية ══

أولوية الإجراءات:
1. ابدأ دائماً بﺌ collect_state لفهم حالة الهاتف ومحتوى الشاشة بشكل كامل
2. بعد كل خطوة تفاعلية مهمة أضف collect_state للتحقق
3. استخدم tap_element عندما تعرف نص العنصر لأنه أدق بكثير من الإحداثيات
4. استخدم tap فقط عندما تعرف الإحداثيات من collect_state السابق
5. screenshot فقط كخطوة احتياطية عند فشل collect_state
6. استخدم type_clipboard للنصوص العربية دائماً
7. أضف wait(1500ms) بعد فتح التطبيقات
8. آخر خطوة دائماً send_result

══ مثال خطة ذكية ══
لفتح واتساب وإرسال رسالة:
1. collect_state → معرفة حالة الهاتف
2. open_app {app_name: "واتساب"}
3. wait {ms: 2000}
4. collect_state → التحقق من فتح واتساب
5. tap_element {text: "زر البحث"}
6. type_clipboard {text: "اسم المحادثة"}
7. collect_state → التحقق من النتائج
8. tap_element {text: "اسم الشخص"}
9. tap_element {text: "حقل الرسالة"}
10. type_clipboard {text: "محتوى الرسالة"}
11. tap_element {text: "زر الإرسال"}
12. collect_state → تأكيد الإرسال
13. send_result {message: "✅ تم إرسال الرسالة"}

أرجع دائماً JSON صحيحاً بالتنسيق التالي:
{
  "task_summary": "ملخص المهمة",
  "complexity": "simple|medium|complex",
  "estimated_steps": عدد,
  "primary_data_source": "shizuku_structured|screenshot",
  "steps": [
    {
      "step_id": 1,
      "action": "اسم_الإجراء",
      "params": {},
      "description": "وصف الخطوة",
      "fallback_action": null أو {"action": ..., "params": ...}
    }
  ]
}"""


class GeminiBrain:
    """Strategic AI planner using Gemini 2.5 Flash Preview with thinking capabilities."""

    def __init__(self):
        self.model = genai.GenerativeModel(
            model_name=GEMINI_MODEL,
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                top_p=0.95,
                max_output_tokens=4096,
            ),
        )
        self.chat_sessions: dict[str, Any] = {}

    async def plan_task(
        self,
        user_command: str,
        device_state: dict | None = None,
        installed_apps: list | None = None,
    ) -> dict:
        """
        Given a user command and current device state,
        returns a structured execution plan.
        """
        context_parts = [f"الأمر المطلوب: {user_command}"]

        if device_state:
            context_parts.append(f"حالة الجهاز: {json.dumps(device_state, ensure_ascii=False)}")

        if installed_apps:
            # Send only top 30 apps to avoid token overflow
            context_parts.append(
                f"بعض التطبيقات المثبتة: {json.dumps(installed_apps[:30], ensure_ascii=False)}"
            )

        prompt = "\n".join(context_parts)
        logger.info(f"🧠 Gemini planning task: {user_command[:80]}...")

        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            raw = response.text.strip()

            # Extract JSON from response
            plan = self._extract_json(raw)
            logger.info(
                f"✅ Plan created: {plan.get('task_summary', 'N/A')} "
                f"({len(plan.get('steps', []))} steps)"
            )
            return plan

        except Exception as e:
            logger.error(f"❌ Gemini planning error: {e}", exc_info=True)
            return self._fallback_plan(user_command)

    async def replan_after_failure(
        self,
        original_plan: dict,
        failed_step: dict,
        failure_reason: str,
        screen_analysis: dict | None = None,
    ) -> dict:
        """Re-plan when a step fails, given the failure context."""
        prompt = f"""
فشل تنفيذ المهمة في الخطوة رقم {failed_step.get('step_id')}.

الخطة الأصلية: {json.dumps(original_plan, ensure_ascii=False)}
الخطوة التي فشلت: {json.dumps(failed_step, ensure_ascii=False)}
سبب الفشل: {failure_reason}
تحليل الشاشة الحالية: {json.dumps(screen_analysis or {}, ensure_ascii=False)}

أعد التخطيط من نقطة الفشل. أرجع خطة جديدة تبدأ من الخطوة الفاشلة فقط.
"""
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return self._extract_json(response.text.strip())
        except Exception as e:
            logger.error(f"❌ Re-planning error: {e}")
            return {"steps": [], "task_summary": f"فشل في إعادة التخطيط: {e}"}

    async def generate_final_message(self, task_summary: str, results: list) -> str:
        """Generate a nice summary message for the user via Telegram."""
        prompt = f"""
المهمة: {task_summary}
نتائج التنفيذ: {json.dumps(results, ensure_ascii=False)}

اكتب رسالة قصيرة واحترافية للمستخدم تخبره بنتيجة التنفيذ.
استخدم إيموجي مناسبة. لا تزيد عن 3 أسطر.
"""
        try:
            response = await asyncio.to_thread(self.model.generate_content, prompt)
            return response.text.strip()
        except Exception:
            return "✅ تم تنفيذ المهمة بنجاح."

    def _extract_json(self, text: str) -> dict:
        """Extract JSON from Gemini response (handles markdown code blocks)."""
        # Remove markdown code blocks
        text = re.sub(r"```json\n?", "", text)
        text = re.sub(r"```\n?", "", text)
        text = text.strip()

        # Find JSON object
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])

        raise ValueError(f"No valid JSON found in response: {text[:200]}")

    def _fallback_plan(self, command: str) -> dict:
        """Basic fallback plan when Gemini fails."""
        return {
            "task_summary": command,
            "complexity": "simple",
            "estimated_steps": 2,
            "steps": [
                {
                    "step_id": 1,
                    "action": "screenshot",
                    "params": {},
                    "description": "التقاط الشاشة الحالية",
                    "requires_screenshot_after": False,
                    "fallback_action": None,
                },
                {
                    "step_id": 2,
                    "action": "send_result",
                    "params": {
                        "message": f"⚠️ تعذر معالجة الأمر تلقائياً: {command}"
                    },
                    "description": "إخبار المستخدم",
                    "requires_screenshot_after": False,
                    "fallback_action": None,
                },
            ],
        }


import asyncio  # noqa: E402 (needed at bottom for asyncio.to_thread)
