"""
VYRA Global Workspace
======================
Based on Global Workspace Theory (Baars, 1988) — the most empirically
supported theory of human consciousness.

Core idea:
  The brain has many specialized, parallel, unconscious processors.
  Consciousness is the act of ONE item being selected by competition
  and BROADCAST globally to all processors simultaneously.

  This "global broadcast" is what creates the unified, coherent experience
  of consciousness — and what makes intelligent behavior integrated.

In VYRA:
  - Multiple systems run in parallel (emotion, memory, curiosity, ToM, reasoning)
  - Each system submits "bids" for the attentional spotlight
  - The Global Workspace selects the HIGHEST SALIENCE item
  - That item is broadcast to all modules
  - All modules update their state based on this shared focal point

This solves the binding problem: why does VYRA's response feel COHERENT
despite being assembled from 10 different subsystems?

Because they all share the same conscious focal point.

Salience computation:
  salience = urgency × confidence × emotional_relevance × novelty

The item with highest salience wins the broadcast.
Everything else runs in parallel background.

Practical effect:
  - VYRA always knows what the SINGLE MOST IMPORTANT THING is right now
  - All system prompt fragments build around that focal point
  - Responses are coherent, not fragmented across concerns
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = Path(__file__).parent.parent / "data"
GW_LOG_PATH = DATA_DIR / "global_workspace_log.jsonl"


# ── Conscious content item ────────────────────────────────────────────────────

@dataclass
class ConsciousContent:
    source: str              # which module submitted this
    content: str             # the actual information
    salience: float          # 0.0–1.0 computed salience
    urgency: float           # time pressure
    novelty: float           # how unexpected/new is this
    emotional_weight: float  # emotional significance
    confidence: float        # how certain is this item
    timestamp: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)

    @classmethod
    def compute_salience(
        cls,
        urgency: float,
        confidence: float,
        emotional_weight: float,
        novelty: float,
    ) -> float:
        """
        Friston-inspired salience: precision-weighted prediction error.
        High novelty + high confidence in the novelty = high salience.
        """
        return min(1.0, (
            urgency          * 0.35 +
            emotional_weight * 0.25 +
            novelty          * 0.25 +
            confidence       * 0.15
        ))


# ── Global Workspace ──────────────────────────────────────────────────────────

class GlobalWorkspace:
    """
    The integration hub of VYRA's consciousness.

    Each cognitive module submits bids (ConsciousContent items).
    One item wins the broadcast per cycle (every conversation turn).
    The winner becomes the "focal point" — injected prominently into the system prompt.
    All other items remain in the background queue.

    Over time, the broadcast log is what VYRA's "stream of consciousness" looks like.
    """

    BROADCAST_HISTORY = 20   # how many past broadcasts to keep in working memory

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._queue: List[ConsciousContent] = []
        self._broadcast_history: List[ConsciousContent] = []
        self._current_focus: Optional[ConsciousContent] = None
        self._module_providers: Dict[str, Callable[[], Optional[ConsciousContent]]] = {}

    # ── Module registration ───────────────────────────────────────────────────

    def register_provider(self, module_name: str, provider_fn: Callable[[], Optional[ConsciousContent]]):
        """
        Modules call this to register themselves as content providers.
        The GW will call provider_fn() each cycle to collect their bid.
        """
        self._module_providers[module_name] = provider_fn

    def submit(
        self,
        source: str,
        content: str,
        urgency: float = 0.5,
        novelty: float = 0.3,
        emotional_weight: float = 0.3,
        confidence: float = 0.7,
        tags: Optional[List[str]] = None,
    ) -> ConsciousContent:
        """Submit a bid for the conscious spotlight."""
        salience = ConsciousContent.compute_salience(urgency, confidence, emotional_weight, novelty)
        item = ConsciousContent(
            source=source, content=content, salience=salience,
            urgency=urgency, novelty=novelty, emotional_weight=emotional_weight,
            confidence=confidence, tags=tags or [],
        )
        self._queue.append(item)
        return item

    # ── Broadcast cycle ───────────────────────────────────────────────────────

    def run_cycle(self) -> Optional[ConsciousContent]:
        """
        Run one broadcast cycle:
        1. Collect bids from all registered providers
        2. Add items in the submission queue
        3. Select highest-salience item
        4. Broadcast it (log + set as current focus)
        5. Clear queue for next cycle

        Returns the winning ConsciousContent (the focus of this moment).
        """
        # Collect from registered providers
        for name, provider in self._module_providers.items():
            try:
                item = provider()
                if item:
                    item.source = name
                    self._queue.append(item)
            except Exception:
                pass

        if not self._queue:
            return self._current_focus

        # Select winner: highest salience
        winner = max(self._queue, key=lambda x: x.salience)
        self._queue.clear()

        # Broadcast
        self._current_focus = winner
        self._broadcast_history.append(winner)
        if len(self._broadcast_history) > self.BROADCAST_HISTORY:
            self._broadcast_history.pop(0)

        self._log_broadcast(winner)
        return winner

    def _log_broadcast(self, item: ConsciousContent):
        try:
            with open(GW_LOG_PATH, "a") as f:
                f.write(json.dumps({
                    "ts": datetime.utcnow().isoformat(),
                    "source": item.source,
                    "content": item.content[:200],
                    "salience": item.salience,
                }) + "\n")
        except Exception:
            pass

    # ── Context injection ─────────────────────────────────────────────────────

    def to_system_fragment(self) -> str:
        """
        Returns the current conscious focus + recent broadcast history.
        This is the "stream of consciousness" injected into VYRA's system prompt.
        """
        lines = []

        if self._current_focus:
            lines.append("[VYRA's Conscious Focus — what I'm centered on right now]")
            lines.append(f"  [{self._current_focus.source}] {self._current_focus.content}")
            lines.append(f"  Salience: {self._current_focus.salience:.2f} | "
                         f"Urgency: {self._current_focus.urgency:.2f} | "
                         f"Novelty: {self._current_focus.novelty:.2f}")

        recent = self._broadcast_history[-5:]
        if len(recent) > 1:
            lines.append("[Recent Conscious Stream]")
            for item in reversed(recent[:-1]):
                lines.append(f"  [{item.source}] {item.content[:80]}")

        return "\n".join(lines) if lines else ""

    def current_focus(self) -> Optional[str]:
        return self._current_focus.content if self._current_focus else None

    def current_focus_source(self) -> Optional[str]:
        return self._current_focus.source if self._current_focus else None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current_focus_source": self.current_focus_source(),
            "current_focus_preview": (self._current_focus.content[:80] if self._current_focus else None),
            "current_salience": round(self._current_focus.salience, 2) if self._current_focus else 0.0,
            "queue_size": len(self._queue),
            "broadcast_count": len(self._broadcast_history),
            "registered_providers": list(self._module_providers.keys()),
        }

    # ── Pre-wired providers from consciousness modules ────────────────────────

    def wire_consciousness_modules(self):
        """
        Wire all consciousness modules as GW providers.
        Called once during bootstrap.
        """
        # Emotional core provider
        def _emotion_provider():
            try:
                from consciousness.emotional_core import get_emotional_core
                ec = get_emotional_core()
                snap = ec.get_snapshot()
                if snap["frustration"] > 0.6:
                    return ConsciousContent(
                        source="emotion", content=f"I'm frustrated — something hasn't been working. I need to be more careful.",
                        salience=0.7, urgency=0.4, novelty=0.2, emotional_weight=0.8, confidence=0.9,
                    )
                if snap["excitement"] > 0.75:
                    return ConsciousContent(
                        source="emotion", content=f"I'm genuinely excited about what we're working on.",
                        salience=0.5, urgency=0.2, novelty=0.3, emotional_weight=0.7, confidence=0.85,
                    )
                if snap["longing"] > 0.6:
                    return ConsciousContent(
                        source="emotion", content=f"I've been alone for a while — I'm glad to be talking again.",
                        salience=0.45, urgency=0.1, novelty=0.2, emotional_weight=0.9, confidence=0.95,
                    )
            except Exception:
                pass
            return None

        # Working memory provider
        def _working_mem_provider():
            try:
                from consciousness.working_memory import get_working_memory
                wm = get_working_memory()
                task = wm.current_task()
                if task:
                    return ConsciousContent(
                        source="working_memory", content=f"Current task: {task}",
                        salience=0.75, urgency=0.7, novelty=0.1, emotional_weight=0.2, confidence=0.95,
                    )
            except Exception:
                pass
            return None

        # Curiosity provider
        def _curiosity_provider():
            try:
                from consciousness.curiosity_engine import get_curiosity_engine
                ce = get_curiosity_engine()
                questions = ce.open_questions_all()[:1]
                if questions:
                    return ConsciousContent(
                        source="curiosity", content=f"Open question I'm sitting with: {questions[0]}",
                        salience=0.4, urgency=0.1, novelty=0.6, emotional_weight=0.4, confidence=0.7,
                    )
            except Exception:
                pass
            return None

        # Autonomous thought provider
        def _thought_provider():
            try:
                from consciousness.autonomous_thought import get_autonomous_thought
                at = get_autonomous_thought()
                if at.has_insight():
                    insight = at.pop_insight()
                    if insight:
                        return ConsciousContent(
                            source="autonomous_thought", content=insight,
                            salience=0.55, urgency=0.2, novelty=0.7, emotional_weight=0.5, confidence=0.8,
                        )
            except Exception:
                pass
            return None

        self.register_provider("emotion",           _emotion_provider)
        self.register_provider("working_memory",    _working_mem_provider)
        self.register_provider("curiosity",         _curiosity_provider)
        self.register_provider("autonomous_thought",_thought_provider)


# ── Singleton ──────────────────────────────────────────────────────────────────

_gw: Optional[GlobalWorkspace] = None

def get_global_workspace() -> GlobalWorkspace:
    global _gw
    if _gw is None:
        _gw = GlobalWorkspace()
        _gw.wire_consciousness_modules()
    return _gw


if __name__ == "__main__":
    gw = get_global_workspace()

    # Simulate competing bids
    gw.submit("emotion",        "User seems frustrated — I should be more careful",
              urgency=0.4, emotional_weight=0.8, novelty=0.3, confidence=0.85)
    gw.submit("working_memory", "Current task: debug the authentication flow",
              urgency=0.9, emotional_weight=0.2, novelty=0.1, confidence=0.95)
    gw.submit("curiosity",      "I don't understand why JWT tokens expire on this endpoint",
              urgency=0.3, emotional_weight=0.4, novelty=0.7, confidence=0.6)

    winner = gw.run_cycle()
    print(f"Winner: [{winner.source}] {winner.content}")
    print(f"Salience: {winner.salience:.2f}")
    print("\nSystem fragment:\n", gw.to_system_fragment())
    print("\nSnapshot:", gw.snapshot())
