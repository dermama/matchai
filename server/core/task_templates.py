"""
Task Templates — Pre-built Complex Workflows
=============================================
For common tasks, skip Gemini planning entirely and use
a battle-tested, optimized step sequence instead.
Gemini still fills in the variable parameters.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("matchai.templates")


# ─── Data Models ──────────────────────────────────────────────────────────────

@dataclass
class TemplateStep:
    action: str
    params: dict = field(default_factory=dict)
    description: str = ""
    optional: bool = False
    fallback_action: Optional[dict] = None


@dataclass
class TaskTemplate:
    name: str
    description: str
    trigger_patterns: list[str]          # Regex patterns in Arabic/English
    required_params: list[str]           # Must be extracted from command
    optional_params: list[str]
    steps: list[TemplateStep]
    estimated_duration_sec: int = 10
    complexity: str = "medium"


# ─── Template Library ─────────────────────────────────────────────────────────

TEMPLATES: dict[str, TaskTemplate] = {

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    "send_whatsapp_message": TaskTemplate(
        name="send_whatsapp_message",
        description="إرسال رسالة واتساب لشخص محدد",
        trigger_patterns=[
            r"أرسل.*(واتساب|وتساب).*ل",
            r"اكتب.*(واتساب|وتساب).*ل",
            r"send.*whatsapp.*to",
            r"message.*on.*whatsapp",
        ],
        required_params=["contact_name", "message"],
        optional_params=["app_variant"],
        complexity="medium",
        estimated_duration_sec=15,
        steps=[
            TemplateStep("collect_state", {}, "جمع حالة الهاتف"),
            TemplateStep("open_app", {"app_name": "واتساب"}, "فتح واتساب"),
            TemplateStep("wait", {"ms": 2000}, "انتظار تحميل واتساب"),
            TemplateStep("collect_state", {}, "التحقق من فتح واتساب"),
            TemplateStep("tap_element", {"text": "ابحث"}, "النقر على البحث",
                         fallback_action={"action": "tap_element", "params": {"text": "Search"}}),
            TemplateStep("type_clipboard", {"text": "{contact_name}"}, "كتابة اسم الشخص"),
            TemplateStep("wait", {"ms": 1000}, "انتظار نتائج البحث"),
            TemplateStep("collect_state", {}, "التحقق من ظهور النتائج"),
            TemplateStep("tap_element", {"text": "{contact_name}"}, "النقر على المحادثة"),
            TemplateStep("collect_state", {}, "التحقق من فتح المحادثة"),
            TemplateStep("tap_element", {"text": "اكتب رسالة"}, "النقر على حقل الرسالة",
                         fallback_action={"action": "tap_element", "params": {"text": "Type a message"}}),
            TemplateStep("type_clipboard", {"text": "{message}"}, "كتابة الرسالة"),
            TemplateStep("wait", {"ms": 500}),
            TemplateStep("tap_element", {"text": "إرسال"}, "الضغط إرسال",
                         fallback_action={"action": "shell_command",
                                          "params": {"command": "input keyevent KEYCODE_ENTER"}}),
            TemplateStep("collect_state", {}, "التحقق من إرسال الرسالة"),
            TemplateStep("send_result",
                         {"message": "✅ تم إرسال الرسالة لـ {contact_name} على واتساب"},
                         "إخبار المستخدم"),
        ]
    ),

    # ── YouTube ──────────────────────────────────────────────────────────────

    "search_youtube": TaskTemplate(
        name="search_youtube",
        description="البحث عن فيديو في يوتيوب",
        trigger_patterns=[
            r"(ابحث|إبحث|بحث).*?(يوتيوب|youtube)",
            r"(شغل|شغّل|شغيل).*?(يوتيوب|youtube)",
            r"(افتح|إفتح|فتح).*?(يوتيوب|youtube).*?(و|)",
            r"search.*?youtube",
            r"play.*?youtube",
        ],
        required_params=["search_query"],
        optional_params=[],
        complexity="simple",
        estimated_duration_sec=10,
        steps=[
            TemplateStep("collect_state", {}),
            TemplateStep("open_app", {"app_name": "يوتيوب"}),
            TemplateStep("wait", {"ms": 2500}),
            TemplateStep("collect_state", {}),
            TemplateStep("tap_element", {"text": "بحث"},
                         fallback_action={"action": "tap_element", "params": {"text": "Search"}}),
            TemplateStep("type_clipboard", {"text": "{search_query}"}),
            TemplateStep("press_enter"),
            TemplateStep("wait", {"ms": 1500}),
            TemplateStep("collect_state", {}),
            TemplateStep("send_result", {"message": "🎬 تم البحث عن '{search_query}' في يوتيوب"}),
        ]
    ),

    # ── Screenshot ────────────────────────────────────────────────────────────

    "take_screenshot": TaskTemplate(
        name="take_screenshot",
        description="التقاط لقطة شاشة وإرسالها",
        trigger_patterns=[
            r"لقطة شاشة",
            r"صوّر الشاشة",
            r"screenshot",
            r"capture screen",
        ],
        required_params=[],
        optional_params=["include_state"],
        complexity="simple",
        estimated_duration_sec=5,
        steps=[
            TemplateStep("screenshot", {}, "التقاط الشاشة"),
            TemplateStep("send_result", {"message": "📸 لقطة الشاشة الحالية:"}, "إرسال الصورة"),
        ]
    ),

    # ── System Info ───────────────────────────────────────────────────────────

    "get_device_status": TaskTemplate(
        name="get_device_status",
        description="الحصول على معلومات كاملة عن حالة الهاتف",
        trigger_patterns=[
            r"حالة الهاتف",
            r"معلومات الهاتف",
            r"حالة البطارية",
            r"device status",
            r"battery",
        ],
        required_params=[],
        optional_params=[],
        complexity="simple",
        estimated_duration_sec=5,
        steps=[
            TemplateStep("collect_state", {"include_screenshot": False}),
            TemplateStep("get_battery", {}),
            TemplateStep("get_storage", {}),
            TemplateStep("get_running_apps", {}),
            TemplateStep("send_result",
                         {"message": "📊 حالة الهاتف:\n🔋 {battery}\n💾 {storage}"},
                         "إرسال التقرير"),
        ]
    ),

    # ── Open Settings ─────────────────────────────────────────────────────────

    "open_settings_section": TaskTemplate(
        name="open_settings_section",
        description="فتح قسم محدد من الإعدادات",
        trigger_patterns=[
            r"افتح إعدادات.*الواي فاي",
            r"افتح إعدادات.*البلوتوث",
            r"اذهب.*للإعدادات",
            r"open settings",
        ],
        required_params=["setting_section"],
        optional_params=[],
        complexity="simple",
        steps=[
            TemplateStep("open_app", {"app_name": "إعدادات"}),
            TemplateStep("wait", {"ms": 1500}),
            TemplateStep("collect_state", {}),
            TemplateStep("tap_element", {"text": "{setting_section}"}),
            TemplateStep("collect_state", {}),
            TemplateStep("send_result", {"message": "⚙️ تم فتح إعدادات {setting_section}"}),
        ]
    ),

    # ── Contacts ──────────────────────────────────────────────────────────────

    "make_phone_call": TaskTemplate(
        name="make_phone_call",
        description="الاتصال بشخص",
        trigger_patterns=[
            r"اتصل.*ب",
            r"تصل.*ب",
            r"call",
        ],
        required_params=["contact_name"],
        optional_params=[],
        complexity="simple",
        steps=[
            TemplateStep("collect_state", {}),
            TemplateStep("open_app", {"app_name": "هاتف"}),
            TemplateStep("wait", {"ms": 1500}),
            TemplateStep("collect_state", {}),
            TemplateStep("tap_element", {"text": "بحث"},
                         fallback_action={"action": "tap_element", "params": {"text": "Search contacts"}}),
            TemplateStep("type_clipboard", {"text": "{contact_name}"}),
            TemplateStep("wait", {"ms": 1000}),
            TemplateStep("collect_state", {}),
            TemplateStep("tap_element", {"text": "{contact_name}"}),
            TemplateStep("collect_state", {}),
            TemplateStep("tap_element", {"text": "اتصال"},
                         fallback_action={"action": "tap_element", "params": {"text": "Call"}}),
            TemplateStep("send_result", {"message": "📞 يتم الاتصال بـ {contact_name}..."}),
        ]
    ),

    # ── Alarm ─────────────────────────────────────────────────────────────────

    "set_alarm": TaskTemplate(
        name="set_alarm",
        description="ضبط منبّه على وقت محدد",
        trigger_patterns=[
            r"اضبط.*منبه",
            r"اضبط.*المنبه",
            r"نبّهني.*الساعة",
            r"set.*alarm",
        ],
        required_params=["time"],
        optional_params=["label"],
        complexity="medium",
        steps=[
            TemplateStep("open_app", {"app_name": "ساعة"}),
            TemplateStep("wait", {"ms": 1500}),
            TemplateStep("collect_state", {}),
            TemplateStep("tap_element", {"text": "منبّه"},
                         fallback_action={"action": "tap_element", "params": {"text": "Alarm"}}),
            TemplateStep("tap_element", {"text": "إضافة"},
                         fallback_action={"action": "tap_element", "params": {"text": "+"}}),
            TemplateStep("collect_state", {}),
            TemplateStep("send_result", {"message": "⏰ يتم ضبط المنبه على {time}..."}),
        ]
    ),
}


# ─── Template Engine ──────────────────────────────────────────────────────────

class TemplateEngine:
    """
    Matches user commands to pre-built templates and fills in parameters.
    If no template matches, falls back to Gemini planning.
    """

    def __init__(self, gemini_brain=None):
        self.gemini = gemini_brain

    def match(self, command: str) -> Optional[TaskTemplate]:
        """Find the best matching template for a command."""
        command_lower = command.lower().strip()
        best_match = None
        best_score = 0

        for template in TEMPLATES.values():
            for pattern in template.trigger_patterns:
                if re.search(pattern, command_lower, re.IGNORECASE):
                    # Score by specificity (more required params = more specific)
                    score = len(template.required_params) + 1
                    if score > best_score:
                        best_score = score
                        best_match = template

        if best_match:
            logger.info(f"📋 Template matched: {best_match.name}")
        return best_match

    async def extract_params(self, template: TaskTemplate, command: str) -> dict:
        """
        Extract required parameters from the command using Gemini.
        Returns {param_name: value} dict.
        """
        if not template.required_params:
            return {}

        if self.gemini is None:
            return {}

        params_list = ", ".join(template.required_params + template.optional_params)
        prompt = f"""
أنت خبير في استخراج المعاملات من الأوامر العربية والإنجليزية.
المطلوب استخراج: [{params_list}]
الأمر: "{command}"

قواعد الاستخراج:
1. إذا كان الأمر "ابحث عن [كلمة] في يوتيوب"، فإن search_query هي "[كلمة]".
2. إذا كان الأمر "أرسل [رسالة] لـ [اسم]"، فإن contact_name هو "[اسم]" و message هي "[رسالة]".
3. استخرج القيم بدقة كما وردت.

أرجع JSON فقط وصريح:
{{{", ".join(f'"{p}": "value"' for p in template.required_params)}}}
"""
        try:
            import asyncio
            response = await asyncio.to_thread(self.gemini.model.generate_content, prompt)
            extracted = self.gemini._extract_json(response.text)
            
            # Regex Fallback for search_query if Gemini fails or returns empty
            if "search_query" in template.required_params and not extracted.get("search_query"):
                match = re.search(r"(?:ابحث عن|بحث عن|search for|find)\s+(.+?)(?:\s+في|\s+في\s+يوتيوب|\s+on\s+youtube|$)", command, re.IGNORECASE)
                if match:
                    extracted["search_query"] = match.group(1).strip()
                    logger.info(f"Fallback regex extracted search_query: {extracted['search_query']}")

            logger.info(f"Extracted params for {template.name}: {extracted}")
            return extracted
        except Exception as e:
            logger.warning(f"Param extraction failed: {e}")
            return {}

    def fill_template(self, template: TaskTemplate, params: dict) -> dict:
        """
        Fill a template with extracted parameters to produce an execution plan.
        Variables like {contact_name} in params are replaced with actual values.
        """
        filled_steps = []
        for i, step in enumerate(template.steps):
            filled_params = {}
            for key, value in step.params.items():
                if isinstance(value, str):
                    # Replace {variable} placeholders
                    for param_name, param_value in params.items():
                        if param_value:
                            value = value.replace(f"{{{param_name}}}", str(param_value))
                filled_params[key] = value

            filled_steps.append({
                "step_id": i + 1,
                "action": step.action,
                "params": filled_params,
                "description": step.description or step.action,
                "fallback_action": step.fallback_action,
                "optional": step.optional,
            })

        return {
            "task_summary": f"{template.description} — params: {params}",
            "complexity": template.complexity,
            "estimated_steps": len(filled_steps),
            "primary_data_source": "shizuku_structured",
            "steps": filled_steps,
            "from_template": template.name,
        }

    async def build_plan(self, command: str) -> Optional[dict]:
        """
        Try to build an execution plan from a template.
        Returns None if no template matches (caller should use Gemini).
        """
        template = self.match(command)
        if not template:
            return None

        params = await self.extract_params(template, command)

        # Check all required params are present
        missing = [p for p in template.required_params if not params.get(p)]
        if missing:
            logger.warning(f"Missing required params {missing} for template {template.name}")
            # Still proceed with what we have — adaptive executor will handle

        plan = self.fill_template(template, params)
        logger.info(
            f"📋 Plan from template '{template.name}': "
            f"{len(plan['steps'])} steps, params={params}"
        )
        return plan
