"""
Memory Manager — Persistent AI Memory via Redis-like Dict
=========================================================
Gives Matchai long-term memory across sessions:
- Device profile & installed apps (auto-updated)
- App knowledge: known UI elements per package
- Task history with lessons learned
- User preferences inferred from patterns
"""

import json
import logging
import os
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

logger = logging.getLogger("matchai.memory")

# ─── Data Models ────────────────────────────────────────────────────────────


@dataclass
class AppKnowledge:
    """What the agent knows about a specific app from past interactions."""
    package_name: str
    label: str = ""
    known_elements: list[dict] = field(default_factory=list)   # {text, x, y, type}
    successful_flows: dict = field(default_factory=dict)       # {flow_name: [steps]}
    last_seen_activity: str = ""
    interaction_count: int = 0
    avg_load_time_ms: float = 2000
    last_updated: float = field(default_factory=time.time)


@dataclass
class DeviceProfile:
    """Static + dynamic information about the connected Android device."""
    model: str = ""
    android_version: str = ""
    screen_width: int = 1080
    screen_height: int = 1920
    shizuku_active: bool = False
    installed_apps: list[str] = field(default_factory=list)   # "Label (package)"
    app_map: dict = field(default_factory=dict)               # {name → package}
    last_updated: float = field(default_factory=time.time)


@dataclass
class TaskRecord:
    """A completed (or failed) task record for learning."""
    task_id: str
    goal: str
    success: bool
    duration_ms: float
    steps_done: int
    steps_failed: int
    retries: int
    replans: int
    lessons: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass
class UserPreferences:
    """Inferred user preferences from interaction patterns."""
    preferred_language: str = "ar"
    frequent_apps: list[str] = field(default_factory=list)
    frequent_contacts: list[str] = field(default_factory=list)
    typical_commands: list[str] = field(default_factory=list)
    command_count: int = 0


# ─── Memory Manager ──────────────────────────────────────────────────────────


class MemoryManager:
    """
    In-memory store with optional file persistence.
    In production, replace with Redis for multi-process support.
    """

    PERSISTENCE_FILE = "/tmp/matchai_memory.json"
    MAX_TASK_HISTORY = 100
    MAX_KNOWN_ELEMENTS = 50  # per app

    def __init__(self):
        self.device_profile: DeviceProfile = DeviceProfile()
        self.app_knowledge: dict[str, AppKnowledge] = {}
        self.task_history: list[TaskRecord] = []
        self.user_prefs: UserPreferences = UserPreferences()
        self._load_from_disk()
        logger.info("🧠 MemoryManager initialized")

    # ─── Device Profile ────────────────────────────────────────────────────

    def update_device_profile(self, device_info: dict, installed_apps: list[str]):
        """Called every time the device registers or sends collect_state."""
        self.device_profile.model          = device_info.get("model", self.device_profile.model)
        self.device_profile.android_version = device_info.get("android", self.device_profile.android_version)
        self.device_profile.shizuku_active  = device_info.get("shizuku", "") == "true"
        self.device_profile.last_updated    = time.time()

        if installed_apps:
            self.device_profile.installed_apps = installed_apps
            # Build app map for fast lookup
            for entry in installed_apps:
                # Entry format: "Label (com.package.name)"
                if "(" in entry and entry.endswith(")"):
                    label = entry[:entry.rfind("(")].strip()
                    pkg   = entry[entry.rfind("(")+1:-1]
                    if label:
                        self.device_profile.app_map[label.lower()] = pkg
                        self.device_profile.app_map[pkg] = pkg

        self._save_to_disk()
        logger.debug(f"📱 Device profile updated: {len(installed_apps)} apps")

    def resolve_package(self, name: str) -> Optional[str]:
        """Resolve an app name (Arabic/English) to its package name."""
        name_lower = name.lower().strip()

        # Exact match in app map
        if name_lower in self.device_profile.app_map:
            return self.device_profile.app_map[name_lower]

        # Partial match
        for key, pkg in self.device_profile.app_map.items():
            if name_lower in key or key in name_lower:
                return pkg

        return None

    def get_installed_apps_context(self, limit: int = 40) -> list[str]:
        """Return installed apps for Gemini context (top N)."""
        return self.device_profile.installed_apps[:limit]

    # ─── App Knowledge ─────────────────────────────────────────────────────

    def learn_from_device_state(self, package_name: str, device_state: dict):
        """
        Extract and store UI knowledge from a collect_state result.
        Called automatically after every collect_state.
        """
        if not package_name:
            return

        knowledge = self.app_knowledge.setdefault(
            package_name,
            AppKnowledge(package_name=package_name)
        )

        knowledge.interaction_count += 1
        knowledge.last_updated = time.time()

        # Learn UI elements
        elements = device_state.get("screen_elements", [])
        for el in elements:
            text = el.get("text", "")
            if not text or len(text) < 2:
                continue
            # Store clickable elements with their coordinates
            if el.get("clickable") or el.get("editable"):
                entry = {
                    "text": text,
                    "x": el.get("x", 0),
                    "y": el.get("y", 0),
                    "type": el.get("type", ""),
                    "editable": el.get("editable", False),
                }
                # Update or add
                existing = next(
                    (e for e in knowledge.known_elements if e["text"] == text), None
                )
                if existing:
                    existing.update(entry)  # Update coordinates (may shift)
                else:
                    knowledge.known_elements.append(entry)

        # Keep only most recent elements
        knowledge.known_elements = knowledge.known_elements[-self.MAX_KNOWN_ELEMENTS:]

        # Learn activity
        fg = device_state.get("foreground_app", {})
        if fg.get("package") == package_name:
            knowledge.last_seen_activity = fg.get("activity", "")
            knowledge.label = fg.get("label", knowledge.label)

        self._save_to_disk()

    def get_app_knowledge(self, package_name: str) -> Optional[AppKnowledge]:
        return self.app_knowledge.get(package_name)

    def find_element_coordinates(self, package_name: str, text: str) -> Optional[dict]:
        """
        Return stored element coordinates from past interactions.
        Used to avoid needing collect_state for known elements.
        """
        knowledge = self.app_knowledge.get(package_name)
        if not knowledge:
            return None
        text_lower = text.lower()
        for el in knowledge.known_elements:
            if text_lower in el.get("text", "").lower():
                return el
        return None

    def record_successful_flow(self, package_name: str, flow_name: str, steps: list):
        """Record a sequence of steps that worked for a specific app."""
        knowledge = self.app_knowledge.setdefault(
            package_name,
            AppKnowledge(package_name=package_name)
        )
        knowledge.successful_flows[flow_name] = steps
        self._save_to_disk()
        logger.info(f"💾 Learned flow '{flow_name}' for {package_name}")

    def get_flow(self, package_name: str, flow_name: str) -> Optional[list]:
        """Retrieve a known flow for an app."""
        knowledge = self.app_knowledge.get(package_name)
        if knowledge:
            return knowledge.successful_flows.get(flow_name)
        return None

    # ─── Task History ──────────────────────────────────────────────────────

    def record_task(self, ctx) -> None:
        """Record completed/failed task execution for learning."""
        summary = ctx.to_summary()
        record = TaskRecord(
            task_id=summary["task_id"],
            goal=summary["goal"],
            success=len(ctx.failed_steps) == 0,
            duration_ms=summary["duration_ms"],
            steps_done=summary["steps_done"],
            steps_failed=summary["steps_failed"],
            retries=summary["retries"],
            replans=summary["replans"],
            lessons=summary["lessons"],
        )
        self.task_history.append(record)
        if len(self.task_history) > self.MAX_TASK_HISTORY:
            self.task_history = self.task_history[-self.MAX_TASK_HISTORY:]

        # Update user preferences
        self._update_user_prefs(record)
        self._save_to_disk()

    def get_relevant_history(self, goal: str, limit: int = 5) -> list[TaskRecord]:
        """Find past tasks similar to the current goal."""
        goal_words = set(goal.lower().split())
        scored = []
        for record in self.task_history:
            hist_words = set(record.goal.lower().split())
            overlap = len(goal_words & hist_words)
            if overlap > 0:
                scored.append((overlap, record))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:limit]]

    def build_context_for_gemini(self, goal: str) -> dict:
        """
        Build a rich context dict to include in Gemini's planning prompt.
        Includes: installed apps, relevant history, known element hints.
        """
        relevant_history = self.get_relevant_history(goal, limit=3)
        history_summary = [
            {
                "goal": r.goal,
                "success": r.success,
                "steps": r.steps_done,
                "lesson": r.lessons[0] if r.lessons else None,
            }
            for r in relevant_history
        ]

        # Detect likely packages involved
        likely_packages = self._extract_likely_packages(goal)
        element_hints = {}
        for pkg in likely_packages:
            knowledge = self.app_knowledge.get(pkg)
            if knowledge and knowledge.known_elements:
                element_hints[knowledge.label or pkg] = [
                    el["text"] for el in knowledge.known_elements[:10]
                ]

        return {
            "installed_apps":   self.get_installed_apps_context(30),
            "relevant_history": history_summary,
            "element_hints":    element_hints,  # Known UI elements per app
            "user_prefs":       {
                "frequent_apps":      self.user_prefs.frequent_apps[:5],
                "frequent_contacts":  self.user_prefs.frequent_contacts[:5],
            },
        }

    # ─── User Preferences ─────────────────────────────────────────────────

    def _update_user_prefs(self, record: TaskRecord):
        """Infer preferences from task patterns."""
        self.user_prefs.command_count += 1
        goal = record.goal

        # Track frequent apps
        for pkg, knowledge in self.app_knowledge.items():
            if knowledge.label and knowledge.label.lower() in goal.lower():
                label = knowledge.label
                if label not in self.user_prefs.frequent_apps:
                    self.user_prefs.frequent_apps.insert(0, label)
                self.user_prefs.frequent_apps = self.user_prefs.frequent_apps[:10]

        # Track typical commands
        if goal not in self.user_prefs.typical_commands:
            self.user_prefs.typical_commands.insert(0, goal)
        self.user_prefs.typical_commands = self.user_prefs.typical_commands[:20]

    def _extract_likely_packages(self, goal: str) -> list[str]:
        """Guess which packages are involved in this goal."""
        goal_lower = goal.lower()
        matches = []
        for name, pkg in self.device_profile.app_map.items():
            if len(name) > 2 and name in goal_lower:
                matches.append(pkg)
        return list(set(matches))[:3]

    # ─── Persistence ──────────────────────────────────────────────────────

    def _save_to_disk(self):
        try:
            data = {
                "device_profile": asdict(self.device_profile),
                "app_knowledge":  {k: asdict(v) for k, v in self.app_knowledge.items()},
                "task_history":   [asdict(r) for r in self.task_history[-20:]],
                "user_prefs":     asdict(self.user_prefs),
            }
            with open(self.PERSISTENCE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Memory persist failed: {e}")

    def _load_from_disk(self):
        try:
            if not os.path.exists(self.PERSISTENCE_FILE):
                return
            with open(self.PERSISTENCE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "device_profile" in data:
                self.device_profile = DeviceProfile(**data["device_profile"])
            if "user_prefs" in data:
                self.user_prefs = UserPreferences(**data["user_prefs"])
            if "app_knowledge" in data:
                for pkg, kd in data["app_knowledge"].items():
                    self.app_knowledge[pkg] = AppKnowledge(**kd)
            if "task_history" in data:
                for td in data["task_history"]:
                    self.task_history.append(TaskRecord(**td))

            logger.info(
                f"🧠 Memory loaded: {len(self.app_knowledge)} apps, "
                f"{len(self.task_history)} past tasks"
            )
        except Exception as e:
            logger.warning(f"Memory load failed: {e}")


# ─── Singleton ────────────────────────────────────────────────────────────────

_memory: Optional[MemoryManager] = None


def get_memory() -> MemoryManager:
    global _memory
    if _memory is None:
        _memory = MemoryManager()
    return _memory
