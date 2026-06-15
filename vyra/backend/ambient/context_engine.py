"""
Context Engine — Phase 4.1
============================
Always-running ambient awareness scanner. Produces a ContextSnapshot
every 60 seconds that the OpportunityDetector consumes.

Tracks:
  - Time of day / day of week (drives behavioural predictions)
  - Active window / foreground app (via pygetwindow)
  - Running processes (via psutil)
  - System resources (CPU, RAM, battery)
  - User's current emotional state (pulled from perception.py if available)
  - Recent conversation topics (from episodic memory)
  - Active goals and their next tasks

Usage:
    engine = get_context_engine()
    asyncio.create_task(engine.run())
    snap = engine.snapshot       # always the latest
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False

try:
    import pygetwindow as gw
    _GW = True
except ImportError:
    _GW = False


# ── Snapshot ──────────────────────────────────────────────────────────────────

@dataclass
class ContextSnapshot:
    timestamp: str
    hour: int                          # 0–23
    day_of_week: str                   # "Monday"…
    is_weekend: bool
    active_app: str                    # foreground application title
    running_apps: List[str]            # list of process names
    cpu_percent: float
    ram_percent: float
    battery_percent: Optional[float]
    battery_charging: Optional[bool]
    user_emotion: str                  # from perception.py or "unknown"
    recent_topics: List[str]           # from episodic memory tags
    active_goals: List[str]            # from goal engine
    idle_seconds: float                # seconds since last user interaction
    session_length_minutes: float      # how long current session has been
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_work_hours(self) -> bool:
        return not self.is_weekend and 9 <= self.hour <= 18

    def is_deep_work_time(self) -> bool:
        """No meetings, IDE open, mid-morning"""
        return (
            self.is_work_hours()
            and 10 <= self.hour <= 12
            and any(app in self.active_app.lower()
                    for app in ["code", "pycharm", "intellij", "vim", "neovim"])
        )


# ── Engine ────────────────────────────────────────────────────────────────────

SCAN_INTERVAL = 60   # seconds

class ContextEngine:

    def __init__(self):
        self.snapshot: Optional[ContextSnapshot] = None
        self._running = False
        self._session_start = time.time()
        self._last_user_activity = time.time()
        self._emotion = "neutral"

    # ── Public ────────────────────────────────────────────────────────────────

    def set_user_active(self, active: bool):
        if active:
            self._last_user_activity = time.time()

    def set_emotion(self, emotion: str):
        self._emotion = emotion

    # ── Loop ──────────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        print("[ContextEngine] Started ambient scanning.")
        while self._running:
            try:
                self.snapshot = self._scan()
            except Exception as e:
                print(f"[ContextEngine] Scan error: {e}")
            await asyncio.sleep(SCAN_INTERVAL)

    def _scan(self) -> ContextSnapshot:
        now  = datetime.now()
        hour = now.hour
        dow  = now.strftime("%A")
        is_weekend = dow in ("Saturday", "Sunday")

        # Active app
        active_app = ""
        if _GW:
            try:
                wins = gw.getActiveWindow()
                active_app = wins.title if wins else ""
            except Exception:
                pass

        # Running processes
        running_apps: List[str] = []
        if _PSUTIL:
            try:
                procs = {p.info["name"] for p in psutil.process_iter(["name"])
                         if p.info.get("name")}
                # Filter to interesting apps only
                interesting = {"Code", "pycharm64", "chrome", "firefox",
                               "msedge", "slack", "discord", "zoom",
                               "python", "node", "notepad++", "idea64"}
                running_apps = sorted(procs & interesting)
            except Exception:
                pass

        # System stats
        cpu  = 0.0
        ram  = 0.0
        bat_pct: Optional[float]  = None
        bat_chg: Optional[bool]   = None
        if _PSUTIL:
            try:
                cpu = psutil.cpu_percent(interval=None)
                ram = psutil.virtual_memory().percent
                bat = psutil.sensors_battery()
                if bat:
                    bat_pct = bat.percent
                    bat_chg = bat.power_plugged
            except Exception:
                pass

        # Recent topics from episodic memory
        recent_topics: List[str] = []
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem  = get_episodic_memory()
            eps  = mem.recent(n=10)
            tags = [t for ep in eps for t in ep.tags]
            # Top-3 most frequent tags
            from collections import Counter
            recent_topics = [t for t, _ in Counter(tags).most_common(3)]
        except Exception:
            pass

        # Active goals
        active_goals: List[str] = []
        try:
            from goals.goal_engine import get_goal_engine  # type: ignore
            active_goals = [g.title for g in get_goal_engine().list_active()[:3]]
        except Exception:
            pass

        idle_secs    = time.time() - self._last_user_activity
        session_mins = (time.time() - self._session_start) / 60

        return ContextSnapshot(
            timestamp            = now.isoformat(),
            hour                 = hour,
            day_of_week          = dow,
            is_weekend           = is_weekend,
            active_app           = active_app,
            running_apps         = running_apps,
            cpu_percent          = cpu,
            ram_percent          = ram,
            battery_percent      = bat_pct,
            battery_charging     = bat_chg,
            user_emotion         = self._emotion,
            recent_topics        = recent_topics,
            active_goals         = active_goals,
            idle_seconds         = idle_secs,
            session_length_minutes = session_mins,
        )

    def stop(self):
        self._running = False


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[ContextEngine] = None

def get_context_engine() -> ContextEngine:
    global _engine
    if _engine is None:
        _engine = ContextEngine()
    return _engine
