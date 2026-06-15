"""
VYRA Forgetting Curve — Ebbinghaus Retention Science
======================================================
Based on Ebbinghaus (1885) forgetting curve + Wozniak SM-2 spaced-repetition algorithm.

Memory retention decays exponentially unless rehearsed:
    R(t) = e^(-t / stability)
    t         = days since last access
    stability = how "stable" this memory is (grows with each successful recall)

Each time VYRA accesses/retrieves an entity, stability increases:
    stability_new = stability * (1 + 0.1 * ease_factor)

This means frequently used knowledge stays sharp, while unused knowledge
fades — just like a human brain.

Strength labels:
    Fresh    R ≥ 0.80  — recently encoded or rehearsed
    Strong   R  0.60–0.80
    Fading   R  0.40–0.60
    At-Risk  R  0.20–0.40  ← proactive rehearsal recommended
    Forgotten R < 0.20   ← needs re-learning
"""

import json
import math
import sys
import os
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR   = Path(__file__).parent.parent / "data"
FC_PATH    = DATA_DIR / "forgetting_curve.json"
FC_LOG     = DATA_DIR / "forgetting_curve_log.jsonl"

STRENGTH_LABELS = ["Fresh", "Strong", "Fading", "At-Risk", "Forgotten"]

DEFAULT_STABILITY = 14.0   # days — new memories start with 2-week stability
MAX_STABILITY     = 365.0  # cap at 1 year
MIN_STABILITY     = 1.0    # floor at 1 day


@dataclass
class RetentionRecord:
    entity_id: str
    entity_name: str
    stability: float = DEFAULT_STABILITY   # days
    last_accessed: float = field(default_factory=time.time)
    review_count: int = 0
    ease_factor: float = 2.5               # SM-2 ease factor
    created_at: float = field(default_factory=time.time)

    def retention_score(self) -> float:
        """R(t) = e^(-t / stability), t in days."""
        days_since = (time.time() - self.last_accessed) / 86400.0
        return math.exp(-days_since / max(self.stability, 0.1))

    def strength_label(self) -> str:
        r = self.retention_score()
        if r >= 0.80: return "Fresh"
        if r >= 0.60: return "Strong"
        if r >= 0.40: return "Fading"
        if r >= 0.20: return "At-Risk"
        return "Forgotten"

    def days_until_at_risk(self) -> float:
        """How many days until this memory falls below 0.40 retention."""
        # R = e^(-t/S) → t = -S * ln(0.40)
        threshold = 0.40
        current_r = self.retention_score()
        if current_r <= threshold:
            return 0.0
        days_to_threshold = -self.stability * math.log(threshold)
        days_elapsed = (time.time() - self.last_accessed) / 86400.0
        return max(0.0, days_to_threshold - days_elapsed)

    def review(self, was_successful: bool):
        """Update stability and ease after a recall event."""
        self.last_accessed = time.time()
        self.review_count += 1
        if was_successful:
            self.stability = min(MAX_STABILITY, self.stability * (1 + 0.1 * self.ease_factor))
            self.ease_factor = min(3.0, self.ease_factor + 0.1)
        else:
            self.stability = max(MIN_STABILITY, self.stability * 0.5)
            self.ease_factor = max(1.3, self.ease_factor - 0.2)


class ForgettingCurveTracker:
    """
    Tracks retention scores for all known entities.
    Updated whenever VYRA accesses/retrieves an entity.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, RetentionRecord] = self._load()

    def _load(self) -> Dict[str, RetentionRecord]:
        try:
            raw = json.loads(FC_PATH.read_text())
            return {k: RetentionRecord(**v) for k, v in raw.items()}
        except Exception:
            return {}

    def _save(self):
        try:
            FC_PATH.write_text(
                json.dumps({k: asdict(v) for k, v in self._records.items()}, indent=2)
            )
        except Exception:
            pass

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, entity_id: str, entity_name: str):
        """Register a new entity when first encountered."""
        if entity_id not in self._records:
            self._records[entity_id] = RetentionRecord(
                entity_id=entity_id,
                entity_name=entity_name,
            )
            self._save()

    # ── Recall recording ──────────────────────────────────────────────────────

    def record_access(self, entity_id: str, entity_name: str = "", was_successful: bool = True):
        """
        Called whenever VYRA retrieves/uses this entity.
        Updates stability and logs the event.
        """
        if entity_id not in self._records:
            self.register(entity_id, entity_name or entity_id)
        rec = self._records[entity_id]
        old_stability = rec.stability
        rec.review(was_successful)
        self._save()

        try:
            entry = {
                "ts": datetime.utcnow().isoformat(),
                "entity_id": entity_id,
                "was_successful": was_successful,
                "old_stability": round(old_stability, 2),
                "new_stability": round(rec.stability, 2),
                "retention": round(rec.retention_score(), 3),
            }
            with FC_LOG.open("a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_retention_score(self, entity_id: str) -> float:
        rec = self._records.get(entity_id)
        return rec.retention_score() if rec else 1.0

    def get_record(self, entity_id: str) -> Optional[RetentionRecord]:
        return self._records.get(entity_id)

    def get_at_risk_memories(self, threshold: float = 0.35) -> List[RetentionRecord]:
        """Return records with retention score below threshold, sorted by urgency."""
        at_risk = [
            rec for rec in self._records.values()
            if rec.retention_score() < threshold
        ]
        at_risk.sort(key=lambda r: r.retention_score())
        return at_risk

    def get_distribution(self) -> Dict[str, int]:
        """Count of entities in each strength category."""
        dist = {label: 0 for label in STRENGTH_LABELS}
        for rec in self._records.values():
            dist[rec.strength_label()] += 1
        return dist

    def mean_retention(self) -> float:
        """Average retention score across all tracked entities."""
        if not self._records:
            return 1.0
        scores = [rec.retention_score() for rec in self._records.values()]
        return sum(scores) / len(scores)

    def get_all_scores(self) -> List[Dict[str, Any]]:
        """All records with current retention scores — for dashboard."""
        results = []
        for rec in self._records.values():
            results.append({
                "entity_id": rec.entity_id,
                "entity_name": rec.entity_name,
                "retention": round(rec.retention_score(), 3),
                "stability": round(rec.stability, 1),
                "strength": rec.strength_label(),
                "review_count": rec.review_count,
                "days_until_at_risk": round(rec.days_until_at_risk(), 1),
            })
        results.sort(key=lambda x: x["retention"])
        return results

    def snapshot(self) -> Dict[str, Any]:
        dist = self.get_distribution()
        return {
            "total_tracked": len(self._records),
            "mean_retention": round(self.mean_retention(), 3),
            "distribution": dist,
            "at_risk_count": dist.get("At-Risk", 0) + dist.get("Forgotten", 0),
        }


_fc: Optional[ForgettingCurveTracker] = None

def get_forgetting_curve() -> ForgettingCurveTracker:
    global _fc
    if _fc is None:
        _fc = ForgettingCurveTracker()
    return _fc


if __name__ == "__main__":
    fc = get_forgetting_curve()
    fc.register("e1", "NSE API")
    fc.register("e2", "Lokesh")
    fc.register("e3", "Python asyncio")

    print("Initial scores:")
    for row in fc.get_all_scores():
        print(f"  {row['entity_name']}: {row['retention']} ({row['strength']})")

    fc.record_access("e1", was_successful=True)
    fc.record_access("e2", was_successful=True)

    print(f"\nDistribution: {fc.get_distribution()}")
    print(f"Mean retention: {fc.mean_retention():.3f}")
    print(f"Snapshot: {fc.snapshot()}")
