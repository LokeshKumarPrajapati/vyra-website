"""
Opportunity Detector — Phase 4.2
===================================
Monitors ContextSnapshots and fires proactive VYRA notifications
when predefined patterns are matched.

Rules fire at most once per cooldown period per rule.
VYRA never interrupts more than once per 30 minutes unprompted.

Usage:
    detector = get_opportunity_detector()
    detector.set_notify_callback(async_fn)
    asyncio.create_task(detector.run())

Adding custom rules:
    detector.add_rule(OpportunityRule(
        id="my_rule",
        name="Custom Trigger",
        check_fn=lambda snap: snap.hour == 9 and snap.day_of_week == "Monday",
        message_fn=lambda snap: "Good Monday morning! Ready for your weekly review?",
        cooldown_hours=168,   # once per week
    ))
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Awaitable, List, Optional, Dict
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ambient.context_engine import get_context_engine, ContextSnapshot  # type: ignore

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Opportunity:
    rule_id: str
    rule_name: str
    message: str
    priority: int = 5   # 1=urgent, 10=low
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

@dataclass
class OpportunityRule:
    id: str
    name: str
    check_fn: Callable[[ContextSnapshot], bool]
    message_fn: Callable[[ContextSnapshot], str]
    cooldown_hours: float = 1.0
    priority: int = 5
    enabled: bool = True
    _last_fired: float = field(default=0.0, repr=False)

    def can_fire(self) -> bool:
        return self.enabled and (time.time() - self._last_fired) >= self.cooldown_hours * 3600

    def fire(self, snap: ContextSnapshot) -> Opportunity:
        self._last_fired = time.time()
        return Opportunity(
            rule_id   = self.id,
            rule_name = self.name,
            message   = self.message_fn(snap),
            priority  = self.priority,
        )


# ── Detector ──────────────────────────────────────────────────────────────────

GLOBAL_COOLDOWN  = 1800   # 30 minutes between ANY proactive message
CHECK_INTERVAL   = 30     # check rules every 30 seconds

class OpportunityDetector:

    def __init__(self):
        self._rules: List[OpportunityRule] = []
        self._notify: Optional[Callable[[str], Awaitable[None]]] = None
        self._last_notify = 0.0
        self._running     = False
        self._fired_log: List[Opportunity] = []
        self._build_default_rules()

    def set_notify_callback(self, cb: Callable[[str], Awaitable[None]]):
        self._notify = cb

    def add_rule(self, rule: OpportunityRule):
        self._rules.append(rule)

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        print("[OpportunityDetector] Started.")
        while self._running:
            await asyncio.sleep(CHECK_INTERVAL)
            snap = get_context_engine().snapshot
            if snap is None:
                continue
            # Respect global cooldown
            if time.time() - self._last_notify < GLOBAL_COOLDOWN:
                continue
            await self._check_rules(snap)

    async def _check_rules(self, snap: ContextSnapshot):
        triggered = []
        for rule in self._rules:
            if rule.can_fire():
                try:
                    if rule.check_fn(snap):
                        opp = rule.fire(snap)
                        triggered.append(opp)
                except Exception:
                    pass
        if not triggered:
            return
        # Fire highest priority only (lowest number)
        triggered.sort(key=lambda o: o.priority)
        best = triggered[0]
        self._fired_log.append(best)
        if len(self._fired_log) > 100:
            self._fired_log.pop(0)
        self._last_notify = time.time()
        await self._notify_user(best.message)

    async def _notify_user(self, message: str):
        print(f"[OpportunityDetector] → {message}")
        if self._notify:
            try:
                await self._notify(message)
            except Exception as e:
                print(f"[OpportunityDetector] Notify error: {e}")

    def stop(self):
        self._running = False

    # ── Built-in rules ────────────────────────────────────────────────────────

    def _build_default_rules(self):
        self._rules = [

            # Morning briefing trigger (8–9am on weekdays)
            OpportunityRule(
                id      = "morning_briefing",
                name    = "Morning Briefing",
                check_fn= lambda s: s.hour == 8 and not s.is_weekend and s.idle_seconds < 300,
                message_fn= lambda s: (
                    "Good morning! I have your daily briefing ready. "
                    "Say 'morning briefing' to hear it."
                ),
                cooldown_hours = 20,
                priority = 1,
            ),

            # Low battery warning
            OpportunityRule(
                id       = "low_battery",
                name     = "Low Battery",
                check_fn = lambda s: (
                    s.battery_percent is not None
                    and s.battery_percent < 20
                    and s.battery_charging is False
                ),
                message_fn = lambda s: (
                    f"Your battery is at {s.battery_percent:.0f}%. "
                    f"You should plug in soon."
                ),
                cooldown_hours = 2,
                priority = 2,
            ),

            # High CPU warning
            OpportunityRule(
                id       = "high_cpu",
                name     = "High CPU",
                check_fn = lambda s: s.cpu_percent > 90,
                message_fn = lambda s: (
                    f"CPU is at {s.cpu_percent:.0f}%. "
                    f"Want me to check which process is causing it?"
                ),
                cooldown_hours = 1,
                priority = 3,
            ),

            # End of workday wrap-up (6pm weekdays)
            OpportunityRule(
                id       = "evening_wrap",
                name     = "Evening Wrap-up",
                check_fn = lambda s: (
                    s.hour == 18 and not s.is_weekend and s.idle_seconds < 600
                ),
                message_fn = lambda s: (
                    "It's 6pm! Want me to run your evening progress review "
                    "and queue up tomorrow's priorities?"
                ),
                cooldown_hours = 20,
                priority = 4,
            ),

            # Long session reminder (>3 hours)
            OpportunityRule(
                id       = "long_session",
                name     = "Long Session",
                check_fn = lambda s: s.session_length_minutes > 180 and s.idle_seconds < 60,
                message_fn = lambda s: (
                    f"You've been working for {s.session_length_minutes/60:.1f} hours straight. "
                    f"Consider a short break — it'll boost your focus."
                ),
                cooldown_hours = 3,
                priority = 6,
            ),

            # Active goal reminder (Monday mornings)
            OpportunityRule(
                id       = "goal_monday",
                name     = "Monday Goal Check",
                check_fn = lambda s: (
                    s.day_of_week == "Monday" and s.hour == 9
                    and bool(s.active_goals) and s.idle_seconds < 300
                ),
                message_fn = lambda s: (
                    f"New week! You have {len(s.active_goals)} active goal(s): "
                    + ", ".join(s.active_goals[:2])
                    + ". Want me to run the week plan?"
                ),
                cooldown_hours = 168,
                priority = 3,
            ),

            # Stress detection (negative emotion + long session)
            OpportunityRule(
                id       = "stress_detected",
                name     = "Stress Detected",
                check_fn = lambda s: (
                    s.user_emotion in ("stressed", "frustrated", "angry")
                    and s.session_length_minutes > 60
                ),
                message_fn = lambda s: (
                    "You seem a bit stressed. Want me to put on some calming music "
                    "or help you break down what you're working on?"
                ),
                cooldown_hours = 2,
                priority = 2,
            ),
        ]


# ── Singleton ─────────────────────────────────────────────────────────────────

_detector: Optional[OpportunityDetector] = None

def get_opportunity_detector() -> OpportunityDetector:
    global _detector
    if _detector is None:
        _detector = OpportunityDetector()
    return _detector
