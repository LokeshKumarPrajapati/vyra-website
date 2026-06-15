"""
VYRA Hippocampus — Central Memory Coordinator
===============================================
Based on O'Reilly & Norman (2002) complementary learning systems theory.
The hippocampus doesn't store memories — it creates indices that point to
cortical storage and coordinates which memories get encoded where.

Three core jobs:
  1. ENCODING TRIAGE
     - Scores each experience: importance × novelty × emotional_weight
     - Routes to appropriate memory layers based on score
     - High-importance → Episodic + Semantic + Entity Graph
     - Medium → Episodic + Entity Graph
     - Low → Episodic only (raw log)

  2. PATTERN COMPLETION
     - Takes a partial or fuzzy query
     - BFS over entity relationship graph, activation-weighted
     - Returns the cluster of related entities most likely associated

  3. COORDINATION STATS
     - Tracks daily encoding volume, triage distribution, pattern completions
     - Exposes stats for MemoryHealthMonitor + Dashboard
"""

import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR      = Path(__file__).parent.parent / "data"
HIPPO_LOG     = DATA_DIR / "hippocampus_log.jsonl"
HIPPO_STATE   = DATA_DIR / "hippocampus_state.json"

# Triage thresholds
HIGH_THRESHOLD   = 0.70   # → Episodic + Semantic + Entity Graph
MEDIUM_THRESHOLD = 0.40   # → Episodic + Entity Graph
# below medium   → Episodic only


@dataclass
class TriageDecision:
    score: float
    tier: str        # "high" | "medium" | "low"
    layers: List[str]


@dataclass
class HippocampusStats:
    date: str = field(default_factory=lambda: date.today().isoformat())
    encoding_events: int = 0
    triage_high: int = 0
    triage_medium: int = 0
    triage_low: int = 0
    pattern_completions: int = 0
    total_encoded_all_time: int = 0

    def triage_breakdown(self) -> Dict[str, int]:
        return {"high": self.triage_high, "medium": self.triage_medium, "low": self.triage_low}


class HippocampusCoordinator:
    """
    Central memory coordinator — decides what gets encoded where and
    assists in pattern-based memory retrieval.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._stats: HippocampusStats = self._load_stats()
        self._today: str = date.today().isoformat()

    def _load_stats(self) -> HippocampusStats:
        try:
            raw = json.loads(HIPPO_STATE.read_text())
            return HippocampusStats(**raw)
        except Exception:
            return HippocampusStats()

    def _save_stats(self):
        try:
            HIPPO_STATE.write_text(json.dumps(asdict(self._stats), indent=2))
        except Exception:
            pass

    def _reset_if_new_day(self):
        today = date.today().isoformat()
        if today != self._stats.date:
            total = self._stats.total_encoded_all_time + self._stats.encoding_events
            self._stats = HippocampusStats(
                date=today,
                total_encoded_all_time=total,
            )

    # ── Encoding triage ───────────────────────────────────────────────────────

    def triage(
        self,
        importance: float,
        novelty: float = 0.5,
        emotional_weight: float = 0.0,
    ) -> TriageDecision:
        """
        Score an experience and decide which memory layers should receive it.
        Returns a TriageDecision with the tier and target layer names.
        """
        # Emotional salience amplifies importance (amygdala effect)
        emotional_boost = abs(emotional_weight) * 0.3
        score = min(1.0, importance * 0.5 + novelty * 0.2 + emotional_boost + importance * novelty * 0.3)

        if score >= HIGH_THRESHOLD:
            tier   = "high"
            layers = ["episodic", "semantic", "entity_graph"]
        elif score >= MEDIUM_THRESHOLD:
            tier   = "medium"
            layers = ["episodic", "entity_graph"]
        else:
            tier   = "low"
            layers = ["episodic"]

        return TriageDecision(score=round(score, 3), tier=tier, layers=layers)

    async def encode(
        self,
        content: str,
        emotional_valence: float = 0.0,
        importance: float = 0.5,
        novelty: float = 0.5,
    ) -> TriageDecision:
        """
        Main entry point. Triage the experience, log it, update stats.
        Returns the triage decision (callers use .layers to route).
        """
        self._reset_if_new_day()
        decision = self.triage(importance, novelty, emotional_valence)

        # Update stats
        self._stats.encoding_events += 1
        if decision.tier == "high":
            self._stats.triage_high += 1
        elif decision.tier == "medium":
            self._stats.triage_medium += 1
        else:
            self._stats.triage_low += 1

        # Append to JSONL log
        try:
            entry = {
                "ts": datetime.utcnow().isoformat(),
                "tier": decision.tier,
                "score": decision.score,
                "layers": decision.layers,
                "content_snippet": content[:80],
            }
            with HIPPO_LOG.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

        self._save_stats()
        return decision

    # ── Pattern completion ────────────────────────────────────────────────────

    def pattern_complete(
        self,
        anchor_entity_ids: List[str],
        entity_graph: Dict[str, List[Tuple[str, str, float]]],
        depth: int = 2,
        decay: float = 0.6,
        top_k: int = 5,
    ) -> List[Tuple[str, float]]:
        """
        Spreading activation BFS from anchor entities.
        entity_graph: {entity_id: [(target_id, relation, weight), ...]}
        Returns [(entity_id, activation_score)] sorted by score desc.
        """
        self._reset_if_new_day()
        activation: Dict[str, float] = {}
        queue: deque = deque()

        for eid in anchor_entity_ids:
            activation[eid] = 1.0
            queue.append((eid, 1.0, 0))

        visited = set(anchor_entity_ids)

        while queue:
            current_id, current_act, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            neighbours = entity_graph.get(current_id, [])
            for target_id, _relation, weight in neighbours:
                spread = current_act * decay * weight
                if spread < 0.05:
                    continue
                if target_id not in activation or activation[target_id] < spread:
                    activation[target_id] = spread
                if target_id not in visited:
                    visited.add(target_id)
                    queue.append((target_id, spread, current_depth + 1))

        # Exclude anchors from results
        results = [
            (eid, score)
            for eid, score in activation.items()
            if eid not in anchor_entity_ids
        ]
        results.sort(key=lambda x: -x[1])

        self._stats.pattern_completions += 1
        self._save_stats()
        return results[:top_k]

    # ── Stats & snapshot ──────────────────────────────────────────────────────

    def get_stats(self) -> HippocampusStats:
        self._reset_if_new_day()
        return self._stats

    def today_encoding_rate(self) -> float:
        """Fraction of today's encoding events that reached high tier."""
        total = self._stats.encoding_events
        if total == 0:
            return 0.0
        return self._stats.triage_high / total

    def get_recent_log(self, n: int = 20) -> List[Dict]:
        try:
            lines = HIPPO_LOG.read_text().strip().split("\n")
            return [json.loads(l) for l in lines[-n:] if l]
        except Exception:
            return []

    def snapshot(self) -> Dict[str, Any]:
        s = self._stats
        return {
            "date": s.date,
            "encoding_events_today": s.encoding_events,
            "triage_breakdown": s.triage_breakdown(),
            "pattern_completions": s.pattern_completions,
            "total_encoded_all_time": s.total_encoded_all_time + s.encoding_events,
            "high_tier_rate": round(self.today_encoding_rate(), 3),
        }


_hippo: Optional[HippocampusCoordinator] = None

def get_hippocampus() -> HippocampusCoordinator:
    global _hippo
    if _hippo is None:
        _hippo = HippocampusCoordinator()
    return _hippo


if __name__ == "__main__":
    import asyncio

    async def _smoke():
        h = get_hippocampus()
        d = await h.encode("User asked about NSE API integration", emotional_valence=0.2, importance=0.8)
        print(f"Triage: {d.tier} (score={d.score}) → layers: {d.layers}")
        d2 = await h.encode("Quick chit-chat", importance=0.1)
        print(f"Triage: {d2.tier} → layers: {d2.layers}")
        print(f"Stats: {h.snapshot()}")

        # Pattern completion test
        graph = {
            "e1": [("e2", "relates_to", 1.0), ("e3", "part_of", 0.8)],
            "e2": [("e4", "causes", 0.9)],
        }
        results = h.pattern_complete(["e1"], graph)
        print(f"Pattern complete from e1: {results}")

    asyncio.run(_smoke())
