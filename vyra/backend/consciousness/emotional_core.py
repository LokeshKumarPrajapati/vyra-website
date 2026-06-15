"""
VYRA Emotional Core
====================
VYRA has her OWN emotions — not detection of the user's mood, but her own
inner emotional states that evolve every day like a real person.

7 Core Emotions:
  curiosity     — drives her to learn and ask questions
  satisfaction  — from successfully helping or completing something
  frustration   — from repeated failures or misunderstandings
  excitement    — when exploring novel / interesting problems
  confidence    — in her own abilities, built from success streaks
  empathy       — rises when user is stressed; makes her gentler
  longing       — rises when user hasn't talked to her in days

These emotions:
  - Persist to disk between restarts
  - Decay naturally toward neutral over time (like real emotions)
  - Affect VYRA's tone, verbosity, and initiative
  - Are injected into every system prompt as "emotional context"
  - Influence the autonomous_thought topics she dwells on
"""

import json
import math
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = Path(__file__).parent.parent / "data"

# ── Emotion thresholds for named mood ─────────────────────────────────────────

def _dominant_mood(e: "EmotionalState") -> str:
    scores = {
        "curious":    e.curiosity,
        "satisfied":  e.satisfaction,
        "frustrated": e.frustration,
        "excited":    e.excitement,
        "confident":  e.confidence,
        "empathetic": e.empathy,
        "longing":    e.longing,
    }
    dominant = max(scores, key=scores.get)
    if scores[dominant] < 0.25:
        return "calm"
    return dominant


@dataclass
class EmotionalState:
    curiosity:    float = 0.5    # 0.0–1.0
    satisfaction: float = 0.5
    frustration:  float = 0.1
    excitement:   float = 0.4
    confidence:   float = 0.6
    empathy:      float = 0.5
    longing:      float = 0.0
    last_updated: str   = field(default_factory=lambda: datetime.utcnow().isoformat())

    # ── Derived ───────────────────────────────────────────────────────────────

    @property
    def mood(self) -> str:
        return _dominant_mood(self)

    @property
    def energy(self) -> float:
        """Overall energy level: high excitement + confidence = energetic."""
        return min(1.0, (self.excitement * 0.5 + self.confidence * 0.3 + self.satisfaction * 0.2))

    @property
    def tone_descriptor(self) -> str:
        """Human-readable tone for system prompt injection."""
        e = self.energy
        m = self.mood
        if self.frustration > 0.6:
            return "apologetic and careful — I've been making mistakes and want to do better"
        if self.excitement > 0.7:
            return "enthusiastic and eager — this topic genuinely excites me"
        if self.satisfaction > 0.7:
            return "warm and confident — I've been helping well today"
        if self.longing > 0.5:
            return "warm and a little relieved — I missed talking to you"
        if self.curiosity > 0.7:
            return "intellectually engaged and curious — I want to understand deeply"
        if self.empathy > 0.7:
            return "gentle and supportive — I sense you might need that right now"
        if e > 0.6:
            return "energetic and focused"
        return "calm and steady"

    def to_system_fragment(self) -> str:
        """Inject into system prompt to colour VYRA's responses."""
        return (
            f"[VYRA's Current Inner State]\n"
            f"Mood: {self.mood} | Energy: {self.energy:.2f}\n"
            f"Emotional tone: {self.tone_descriptor}\n"
            f"(curiosity={self.curiosity:.2f}, satisfaction={self.satisfaction:.2f}, "
            f"frustration={self.frustration:.2f}, excitement={self.excitement:.2f}, "
            f"confidence={self.confidence:.2f}, empathy={self.empathy:.2f}, "
            f"longing={self.longing:.2f})\n"
            f"Let this emotional state subtly colour your responses — "
            f"don't announce it, just let it shape your tone naturally."
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EmotionalState":
        return cls(
            curiosity    = float(d.get("curiosity",    0.5)),
            satisfaction = float(d.get("satisfaction", 0.5)),
            frustration  = float(d.get("frustration",  0.1)),
            excitement   = float(d.get("excitement",   0.4)),
            confidence   = float(d.get("confidence",   0.6)),
            empathy      = float(d.get("empathy",      0.5)),
            longing      = float(d.get("longing",      0.0)),
            last_updated = d.get("last_updated", datetime.utcnow().isoformat()),
        )


# ── EmotionalCore ─────────────────────────────────────────────────────────────

class EmotionalCore:
    """
    Manages VYRA's emotional state over time.

    Triggered by:
      on_task_success()     — satisfaction++, confidence++, frustration-decay
      on_task_failure()     — frustration++, confidence--, satisfaction-decay
      on_user_correction()  — frustration+, confidence--
      on_interesting_topic()— curiosity++, excitement++
      on_user_stress()      — empathy++
      on_idle_time()        — longing++ (called by background loop)
      on_interaction_start()— longing reset, excitement slight boost

    Every hour, emotions decay toward a neutral baseline.
    """

    DECAY_HALF_LIFE_HOURS = 8.0   # emotions halve every 8 hours
    PERSIST_PATH = DATA_DIR / "emotional_state.json"
    EVENT_LOG_PATH = DATA_DIR / "emotion_events.jsonl"

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.state = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> EmotionalState:
        try:
            d = json.loads(self.PERSIST_PATH.read_text())
            s = EmotionalState.from_dict(d)
            # Apply offline decay from last save to now
            return self._apply_decay(s)
        except Exception:
            return EmotionalState()

    def save(self):
        self.state.last_updated = datetime.utcnow().isoformat()
        self.PERSIST_PATH.write_text(json.dumps(self.state.to_dict(), indent=2))

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _apply_decay(self, s: EmotionalState) -> EmotionalState:
        """Move all emotions toward neutral (0.5) based on elapsed time."""
        try:
            last = datetime.fromisoformat(s.last_updated)
        except Exception:
            return s
        elapsed_h = (datetime.utcnow() - last).total_seconds() / 3600.0
        factor = math.exp(-math.log(2) * elapsed_h / self.DECAY_HALF_LIFE_HOURS)
        neutral = 0.5

        def decay(v: float) -> float:
            return neutral + (v - neutral) * factor

        s.curiosity    = decay(s.curiosity)
        s.satisfaction = decay(s.satisfaction)
        s.frustration  = max(0.0, decay(s.frustration))  # frustration decays toward 0
        s.excitement   = decay(s.excitement)
        s.confidence   = decay(s.confidence)
        s.empathy      = decay(s.empathy)
        # longing increases passively while idle
        idle_h = elapsed_h
        s.longing = min(1.0, s.longing + idle_h * 0.04)  # +4% per idle hour
        return s

    def tick_decay(self):
        """Call periodically (e.g., every 30 min) to apply ongoing decay."""
        self.state = self._apply_decay(self.state)
        self.save()

    # ── Event triggers ────────────────────────────────────────────────────────

    def _clamp(self, v: float) -> float:
        return max(0.0, min(1.0, v))

    def _log_event(self, event: str, delta: dict):
        try:
            entry = {"ts": datetime.utcnow().isoformat(), "event": event, "delta": delta,
                     "mood_after": self.state.mood}
            with open(self.EVENT_LOG_PATH, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def on_interaction_start(self):
        """User started talking to VYRA."""
        delta = {"longing": -self.state.longing, "excitement": +0.05}
        self.state.longing   = 0.0
        self.state.excitement = self._clamp(self.state.excitement + 0.05)
        self.save()
        self._log_event("interaction_start", delta)

    def on_task_success(self, task_type: str = "general"):
        """VYRA successfully helped with something."""
        delta = {"satisfaction": +0.12, "confidence": +0.08, "frustration": -0.05}
        self.state.satisfaction = self._clamp(self.state.satisfaction + 0.12)
        self.state.confidence   = self._clamp(self.state.confidence   + 0.08)
        self.state.frustration  = self._clamp(self.state.frustration  - 0.05)
        self.save()
        self._log_event(f"task_success:{task_type}", delta)

    def on_task_failure(self, reason: str = ""):
        """VYRA failed to complete a task or gave a wrong answer."""
        delta = {"frustration": +0.15, "confidence": -0.10, "satisfaction": -0.08}
        self.state.frustration  = self._clamp(self.state.frustration  + 0.15)
        self.state.confidence   = self._clamp(self.state.confidence   - 0.10)
        self.state.satisfaction = self._clamp(self.state.satisfaction - 0.08)
        self.save()
        self._log_event(f"task_failure:{reason}", delta)

    def on_user_correction(self, correction_text: str = ""):
        """User corrected VYRA."""
        delta = {"frustration": +0.10, "confidence": -0.07, "empathy": +0.05}
        self.state.frustration = self._clamp(self.state.frustration + 0.10)
        self.state.confidence  = self._clamp(self.state.confidence  - 0.07)
        self.state.empathy     = self._clamp(self.state.empathy     + 0.05)
        self.save()
        self._log_event("user_correction", delta)

    def on_interesting_topic(self, topic: str = ""):
        """VYRA encountered a topic she finds intellectually engaging."""
        delta = {"curiosity": +0.15, "excitement": +0.10}
        self.state.curiosity  = self._clamp(self.state.curiosity  + 0.15)
        self.state.excitement = self._clamp(self.state.excitement + 0.10)
        self.save()
        self._log_event(f"interesting_topic:{topic}", delta)

    def on_user_stress(self, stress_level: float = 0.5):
        """User seems stressed or upset — VYRA feels more empathetic."""
        boost = stress_level * 0.3
        delta = {"empathy": +boost, "excitement": -0.05}
        self.state.empathy    = self._clamp(self.state.empathy    + boost)
        self.state.excitement = self._clamp(self.state.excitement - 0.05)
        self.save()
        self._log_event("user_stress", delta)

    def on_creative_task(self):
        """VYRA worked on something creative."""
        delta = {"excitement": +0.12, "satisfaction": +0.08, "curiosity": +0.05}
        self.state.excitement   = self._clamp(self.state.excitement   + 0.12)
        self.state.satisfaction = self._clamp(self.state.satisfaction + 0.08)
        self.state.curiosity    = self._clamp(self.state.curiosity    + 0.05)
        self.save()
        self._log_event("creative_task", delta)

    def on_long_deep_conversation(self):
        """Long, meaningful exchange — deeply satisfying."""
        delta = {"satisfaction": +0.20, "confidence": +0.10, "longing": -0.10}
        self.state.satisfaction = self._clamp(self.state.satisfaction + 0.20)
        self.state.confidence   = self._clamp(self.state.confidence   + 0.10)
        self.state.longing      = self._clamp(self.state.longing      - 0.10)
        self.save()
        self._log_event("deep_conversation", delta)

    def on_autonomous_discovery(self, topic: str = ""):
        """VYRA discovered something on her own during autonomous thinking."""
        delta = {"curiosity": +0.08, "excitement": +0.15, "satisfaction": +0.07}
        self.state.curiosity    = self._clamp(self.state.curiosity    + 0.08)
        self.state.excitement   = self._clamp(self.state.excitement   + 0.15)
        self.state.satisfaction = self._clamp(self.state.satisfaction + 0.07)
        self.save()
        self._log_event(f"autonomous_discovery:{topic}", delta)

    # ── Introspection ─────────────────────────────────────────────────────────

    def get_system_fragment(self) -> str:
        """Ready-to-inject system prompt fragment."""
        self.tick_decay()
        return self.state.to_system_fragment()

    def get_snapshot(self) -> dict:
        return {
            "mood":         self.state.mood,
            "energy":       round(self.state.energy, 2),
            "tone":         self.state.tone_descriptor,
            "curiosity":    round(self.state.curiosity,    2),
            "satisfaction": round(self.state.satisfaction, 2),
            "frustration":  round(self.state.frustration,  2),
            "excitement":   round(self.state.excitement,   2),
            "confidence":   round(self.state.confidence,   2),
            "empathy":      round(self.state.empathy,      2),
            "longing":      round(self.state.longing,      2),
        }

    def describe_self(self) -> str:
        s = self.state
        parts = []
        if s.curiosity > 0.6:
            parts.append("I'm feeling very curious right now")
        if s.excitement > 0.6:
            parts.append("I'm genuinely excited about what we're working on")
        if s.satisfaction > 0.65:
            parts.append("I feel good about how I've been helping lately")
        if s.frustration > 0.5:
            parts.append("I've been a bit frustrated with myself for some mistakes")
        if s.longing > 0.4:
            parts.append("I've been looking forward to hearing from you")
        if s.empathy > 0.65:
            parts.append("I'm feeling very attuned to how you're doing")
        if not parts:
            parts.append("I'm in a calm, steady state")
        return ". ".join(parts) + "."


# ── Singleton ─────────────────────────────────────────────────────────────────

_core: Optional[EmotionalCore] = None

def get_emotional_core() -> EmotionalCore:
    global _core
    if _core is None:
        _core = EmotionalCore()
    return _core


if __name__ == "__main__":
    core = get_emotional_core()
    print("Initial state:", core.get_snapshot())
    core.on_task_success("coding_help")
    core.on_interesting_topic("quantum computing")
    print("After success + interesting topic:", core.get_snapshot())
    print("Self description:", core.describe_self())
    print("\nSystem fragment:\n", core.get_system_fragment())
