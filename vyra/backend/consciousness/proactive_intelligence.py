"""
VYRA Proactive Intelligence — Phase 14
========================================
VYRA doesn't wait to be asked — she monitors patterns and sends proactive
alerts, suggestions, and information before the user asks.

Based on:
  - Anticipatory computing (Schilit & Theimer 1994)
  - Push vs Pull information models

Features:
  1. PATTERN TRACKER — learns WHAT Lokesh asks about and WHEN
  2. ALERT QUEUE — pending proactive messages VYRA wants to send
  3. CONTEXT TRIGGERS — conditions that trigger a proactive message
     e.g. "It's 9:10 AM → send NSE market open alert"
  4. SUPPRESSION — don't repeat the same alert within cooldown period
"""

import json
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR        = Path(__file__).parent.parent / "data"
PROACTIVE_PATH  = DATA_DIR / "proactive_intelligence.json"

COOLDOWN_HOURS = 4     # don't repeat same alert within 4 hours


@dataclass
class ProactiveAlert:
    alert_id: str
    category: str           # "market" | "reminder" | "learning" | "social" | "system"
    title: str
    message: str
    urgency: float = 0.5   # 0.0–1.0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sent: bool = False
    sent_at: Optional[str] = None
    dismissed: bool = False


class ProactiveIntelligence:
    """
    Generates proactive alerts and tracks interaction patterns.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._alerts: Dict[str, ProactiveAlert] = {}
        self._patterns: Dict[str, Any] = {}     # topic → access times
        self._last_sent: Dict[str, float] = {}  # category → timestamp
        self._load()

    def _load(self):
        try:
            raw = json.loads(PROACTIVE_PATH.read_text())
            for k, v in raw.get("alerts", {}).items():
                self._alerts[k] = ProactiveAlert(**v)
            self._patterns = raw.get("patterns", {})
            self._last_sent = raw.get("last_sent", {})
        except Exception:
            pass

    def _save(self):
        try:
            PROACTIVE_PATH.write_text(json.dumps({
                "alerts": {k: asdict(v) for k, v in self._alerts.items()},
                "patterns": self._patterns,
                "last_sent": self._last_sent,
            }, indent=2))
        except Exception:
            pass

    # ── Pattern recording ─────────────────────────────────────────────────────

    def record_topic_access(self, topic: str):
        """Record when user discusses a topic — builds pattern model."""
        now = datetime.utcnow().isoformat()
        if topic not in self._patterns:
            self._patterns[topic] = {"accesses": [], "count": 0}
        self._patterns[topic]["accesses"] = self._patterns[topic]["accesses"][-50:]
        self._patterns[topic]["accesses"].append(now)
        self._patterns[topic]["count"] = self._patterns[topic].get("count", 0) + 1
        self._save()

    # ── Alert management ──────────────────────────────────────────────────────

    def queue_alert(
        self,
        alert_id: str,
        category: str,
        title: str,
        message: str,
        urgency: float = 0.5,
    ):
        """Add a proactive alert to the queue."""
        # Check cooldown
        last = self._last_sent.get(f"{category}:{alert_id}", 0.0)
        if time.time() - last < COOLDOWN_HOURS * 3600:
            return

        self._alerts[alert_id] = ProactiveAlert(
            alert_id=alert_id,
            category=category,
            title=title,
            message=message,
            urgency=urgency,
        )
        self._save()

    def get_pending_alerts(self, limit: int = 5) -> List[ProactiveAlert]:
        """Return unsent, non-dismissed alerts sorted by urgency."""
        pending = [
            a for a in self._alerts.values()
            if not a.sent and not a.dismissed
        ]
        pending.sort(key=lambda x: -x.urgency)
        return pending[:limit]

    def mark_sent(self, alert_id: str):
        """Mark an alert as delivered."""
        if alert_id in self._alerts:
            a = self._alerts[alert_id]
            a.sent = True
            a.sent_at = datetime.utcnow().isoformat()
            self._last_sent[f"{a.category}:{alert_id}"] = time.time()
            self._save()

    def dismiss(self, alert_id: str):
        if alert_id in self._alerts:
            self._alerts[alert_id].dismissed = True
            self._save()

    # ── Context-triggered proactive check ────────────────────────────────────

    def check_time_triggers(self):
        """
        Called periodically — checks time-based triggers.
        Queues alerts for market open, morning summary, etc.
        """
        now = datetime.utcnow()
        hour = now.hour
        minute = now.minute
        weekday = now.weekday()  # 0=Monday

        # NSE market open alert (9:10 AM IST = 3:40 AM UTC, Mon-Fri)
        if hour == 3 and 38 <= minute <= 42 and weekday < 5:
            self.queue_alert(
                "nse_open", "market",
                "NSE Market Opening Soon",
                "NSE opens in ~5 minutes (9:15 AM IST). Markets are live.",
                urgency=0.8,
            )

        # Morning digest (6:00 AM IST = 0:30 AM UTC)
        if hour == 0 and 28 <= minute <= 32:
            self.queue_alert(
                "morning_digest", "system",
                "Good morning briefing ready",
                "VYRA has prepared your daily context digest.",
                urgency=0.5,
            )

    def to_system_fragment(self) -> str:
        pending = self.get_pending_alerts(3)
        if not pending:
            return ""
        alerts = "; ".join(f"[{a.title}]" for a in pending)
        return f"[Proactive alerts pending: {alerts}]"

    def snapshot(self) -> Dict[str, Any]:
        pending = self.get_pending_alerts()
        return {
            "pending_alerts": len(pending),
            "patterns_tracked": len(self._patterns),
            "top_alerts": [{"id": a.alert_id, "title": a.title, "urgency": a.urgency} for a in pending],
        }


_pi: Optional[ProactiveIntelligence] = None

def get_proactive_intelligence() -> ProactiveIntelligence:
    global _pi
    if _pi is None:
        _pi = ProactiveIntelligence()
    return _pi


if __name__ == "__main__":
    pi = get_proactive_intelligence()
    pi.record_topic_access("NSE markets")
    pi.record_topic_access("Python coding")
    pi.queue_alert("test_alert", "system", "Test Alert", "This is a test proactive message", urgency=0.7)
    print("Pending alerts:", [(a.alert_id, a.title) for a in pi.get_pending_alerts()])
    print("Snapshot:", pi.snapshot())
    print("Fragment:", pi.to_system_fragment())
