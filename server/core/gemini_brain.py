"""
Gemini Brain — Strategic Task Planner
Uses Gemini 2.0 Flash to decompose user commands into executable steps.
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

GEMINI_MODEL = "gemini-2.0-flash-exp"

SYSTEM_PROMPT = """أنت Matchai — وكيل ذكاء اصطناعي متخصص في التحكم الكامل بهواتف الأندرويد.

لديك القدرة على تنفيذ أي أمر على الهاتف من خلال مجموعة من الإجراءات التقنية.

الإجراءات المتاحة (actions):
- screenshot: التقاط لقطة شاشة
- tap: النقر على إحداثيات {x, y}
- swipe: السحب من {x1,y1} إلى {x2,y2} خلال {duration_ms}
- long_press: ضغط طويل على {x, y}
- double_tap: نقر مزدوج على {x, y}
- type_text: كتابة نص {text}
- type_clipboard: كتابة نص عبر الحافظة (للعربية) {text}
- clear_field: مسح حقل النص
- back: زر الرجوع
- home: زر الشاشة الرئيسية
- recents: قائمة التطبيقات المفتوحة
- open_app: فتح تطبيق {package_name أو app_name}
- force_stop_app: إغلاق تطبيق {package_name}
- list_apps: قائمة التطبيقات المثبتة
- open_notifications: فتح لوحة الإشعارات
- clear_notifications: مسح الإشعارات
- set_volume: ضبط الصوت {level: 0-15}
- toggle_wifi: تشغيل/إيقاف الواي فاي
- toggle_bluetooth: تشغيل/إيقاف البلوتوث
- toggle_flashlight: تشغيل/إيقاف الكشاف
- set_brightness: ضبط السطوع {level: 0-255}
- get_battery: معلومات البطارية
- get_storage: معلومات التخزين
- get_running_apps: التطبيقات الجارية
- shell_command: تنفيذ أمر ADB مباشر {command}
- wait: انتظار {ms} ميلي ثانية
- send_result: إرسال رسالة نهائية للمستخدم {message}

قواعد مهمة:
1. دائماً ابدأ بـ screenshot لفهم الحالة الحالية إذا كانت المهمة تتضمن تفاعلاً مع الشاشة
2. بعد كل إجراء تفاعلي، أضف screenshot للتحقق
3. استخدم type_clipboard للنصوص العربية دائماً
4. أضف wait(1000-2000ms) بعد فتح التطبيقات
5. آخر خطوة دائماً send_result مع رسالة واضحة للمستخدم
6. إذا كانت الإحداثيات غير معروفة، استخدم screenshot أولاً ثم حللها عبر Groq

أرجع دائماً JSON صحيحاً بالتنسيق التالي:
{
  "task_summary": "ملخص المهمة",
  "complexity": "simple|medium|complex",
  "estimated_steps": عدد,
  "steps": [
    {
      "step_id": 1,
      "action": "اسم_الإجراء",
      "params": {},
      "description": "وصف الخطوة",
      "requires_screenshot_after": true/false,
      "fallback_action": null أو إجراء بديل
    }
  ]
}"""


class GeminiBrain:
    """Strategic AI planner using Gemini 2.0 Flash."""

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
