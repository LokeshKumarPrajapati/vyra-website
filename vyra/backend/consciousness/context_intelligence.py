"""
VYRA Context Intelligence — Phase 19
========================================
Smart context window management — VYRA decides WHAT to include in her
context window to maximize relevance and minimize noise.

Based on:
  - Bounded rationality (Simon 1955) — optimal decisions under constraints
  - Information foraging theory (Pirolli & Card 1999)
  - Attention as a scarce resource (Kahneman 1973)

Features:
  1. CONTEXT SCORING — rates each potential context fragment by relevance
  2. CONTEXT BUDGET — allocates token budget across sources
  3. RELEVANCE DECAY — old context loses priority unless re-accessed
  4. URGENCY BOOST — time-sensitive items get priority
  5. CONTEXT AUDIT — reports what's currently loaded and why
"""

import json
import time
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

DATA_DIR = Path(__file__).parent.parent / "data"
CI_PATH  = DATA_DIR / "context_intelligence.json"

CONTEXT_BUDGET = 2000    # approximate token budget for injected context
DECAY_HALF_LIFE = 3600   # context relevance halves every hour


@dataclass
class ContextFragment:
    fragment_id: str
    source: str              # "memory" | "goal" | "project" | "alert" | "emotion"
    content: str
    relevance: float         # 0.0–1.0 base relevance
    urgency: float = 0.0     # 0.0–1.0 time pressure
    token_estimate: int = 50
    last_used: float = field(default_factory=time.time)
    use_count: int = 0

    def current_relevance(self) -> float:
        """Relevance decays exponentially since last use."""
        hours_since = (time.time() - self.last_used) / 3600.0
        decay = 0.5 ** (hours_since / (DECAY_HALF_LIFE / 3600.0))
        return min(1.0, self.relevance * decay + self.urgency)


class ContextIntelligence:
    """
    Manages what goes into VYRA's context window for maximum relevance.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._fragments: Dict[str, ContextFragment] = {}
        self._selection_history: List[Dict] = []
        self._load()

    def _load(self):
        try:
            raw = json.loads(CI_PATH.read_text())
            for k, v in raw.get("fragments", {}).items():
                self._fragments[k] = ContextFragment(**v)
            self._selection_history = raw.get("selection_history", [])[-20:]
        except Exception:
            pass

    def _save(self):
        try:
            CI_PATH.write_text(json.dumps({
                "fragments": {k: asdict(v) for k, v in self._fragments.items()},
                "selection_history": self._selection_history[-20:],
            }, indent=2))
        except Exception:
            pass

    def register_fragment(
        self,
        fragment_id: str,
        source: str,
        content: str,
        relevance: float,
        urgency: float = 0.0,
        token_estimate: int = 50,
    ):
        """Register a context fragment for potential inclusion."""
        self._fragments[fragment_id] = ContextFragment(
            fragment_id=fragment_id,
            source=source,
            content=content,
            relevance=relevance,
            urgency=urgency,
            token_estimate=token_estimate,
        )
        self._save()

    def select_context(self, budget: int = CONTEXT_BUDGET) -> List[ContextFragment]:
        """
        Select the optimal set of context fragments within token budget.
        Greedy selection by relevance/token ratio.
        """
        candidates = list(self._fragments.values())
        candidates.sort(key=lambda x: -x.current_relevance())

        selected = []
        tokens_used = 0
        for frag in candidates:
            if tokens_used + frag.token_estimate > budget:
                continue
            selected.append(frag)
            tokens_used += frag.token_estimate
            frag.last_used = time.time()
            frag.use_count += 1

        self._selection_history.append({
            "timestamp": datetime.utcnow().isoformat(),
            "selected": len(selected),
            "tokens_used": tokens_used,
            "fragments": [f.fragment_id for f in selected],
        })
        self._save()
        return selected

    def boost_fragment(self, fragment_id: str, boost: float = 0.2):
        """Boost a fragment's relevance (e.g., it was just referenced)."""
        frag = self._fragments.get(fragment_id)
        if frag:
            frag.relevance = min(1.0, frag.relevance + boost)
            frag.last_used = time.time()
            self._save()

    def prune_stale(self, threshold: float = 0.05):
        """Remove fragments with very low current relevance."""
        stale = [k for k, v in self._fragments.items() if v.current_relevance() < threshold]
        for k in stale:
            del self._fragments[k]
        if stale:
            self._save()

    def to_system_fragment(self) -> str:
        selected = self.select_context(500)  # small budget for the fragment itself
        if not selected:
            return ""
        sources = list(set(f.source for f in selected))
        return f"[Context loaded: {len(selected)} fragments from {', '.join(sources[:3])}]"

    def snapshot(self) -> Dict[str, Any]:
        return {
            "registered_fragments": len(self._fragments),
            "avg_relevance": round(
                sum(f.current_relevance() for f in self._fragments.values()) / max(1, len(self._fragments)), 3
            ),
            "selection_runs": len(self._selection_history),
        }


_ci: Optional[ContextIntelligence] = None

def get_context_intelligence() -> ContextIntelligence:
    global _ci
    if _ci is None:
        _ci = ContextIntelligence()
    return _ci


if __name__ == "__main__":
    ci = get_context_intelligence()
    ci.register_fragment("goal_1", "goal", "Build VYRA to AGI level by June 2026", relevance=0.9, urgency=0.3)
    ci.register_fragment("mem_1",  "memory", "Lokesh works in fintech, likes Python", relevance=0.8)
    ci.register_fragment("alert_1", "alert", "NSE opens in 5 minutes", relevance=0.7, urgency=0.9)
    selected = ci.select_context(200)
    print("Selected:", [(f.fragment_id, round(f.current_relevance(), 2)) for f in selected])
    print("Snapshot:", ci.snapshot())
