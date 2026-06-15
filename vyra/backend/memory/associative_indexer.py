"""
VYRA Associative Indexer — Spreading Activation + Memory Priming
=================================================================
Based on Collins & Loftus (1975) spreading activation theory.

When you think of "coffee" the brain automatically activates "morning",
"caffeine", "work desk", "warmth" — related concepts spread activation
through the semantic network.

Two mechanisms:
  1. SPREADING ACTIVATION
     BFS from anchor entity/entities through the relationship graph.
     Each hop decays the activation by a decay factor.
     Returns a ranked list of related entities + scores.

  2. PRIMING
     When an entity is explicitly accessed, it gets "primed" for 2 hours.
     Primed entities receive a retrieval boost in search results.
     This mirrors the human brain's short-term spreading activation
     where recently-mentioned concepts are easier to recall.

Integration:
     AssociativeIndexer.augment_search_results() re-ranks unified memory
     search results by adding priming boosts to existing scores.
     Called by UnifiedMemory.search() as a 5th fusion dimension.
"""

import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import deque

PRIME_DURATION = 7200    # 2 hours in seconds
PRIME_BOOST    = 0.25    # max retrieval boost for primed entities


@dataclass
class PrimedEntity:
    entity_id: str
    entity_name: str
    primed_at: float = field(default_factory=time.time)
    boost: float = PRIME_BOOST

    def is_active(self) -> bool:
        return (time.time() - self.primed_at) < PRIME_DURATION

    def current_boost(self) -> float:
        """Boost decays linearly over the prime duration."""
        elapsed = time.time() - self.primed_at
        if elapsed >= PRIME_DURATION:
            return 0.0
        fraction_remaining = 1.0 - (elapsed / PRIME_DURATION)
        return self.boost * fraction_remaining


class AssociativeIndexer:
    """
    Spreading activation + priming for enhanced associative retrieval.
    """

    def __init__(self):
        self._primed: Dict[str, PrimedEntity] = {}

    def _cleanup_expired(self):
        expired = [eid for eid, p in self._primed.items() if not p.is_active()]
        for eid in expired:
            del self._primed[eid]

    # ── Priming ───────────────────────────────────────────────────────────────

    def prime(self, entity_ids: List[str], entity_names: Optional[Dict[str, str]] = None):
        """
        Mark entities as primed (boosted retrieval for 2 hours).
        entity_names: optional {entity_id: name} for display.
        """
        self._cleanup_expired()
        names = entity_names or {}
        for eid in entity_ids:
            self._primed[eid] = PrimedEntity(
                entity_id=eid,
                entity_name=names.get(eid, eid),
            )

    def get_primed_boost(self, entity_id: str) -> float:
        """Return current boost for entity (0.0 if not primed or expired)."""
        pe = self._primed.get(entity_id)
        if not pe or not pe.is_active():
            return 0.0
        return pe.current_boost()

    def get_active_primes(self) -> List[str]:
        """Names of currently primed entities — for system prompt."""
        self._cleanup_expired()
        return [p.entity_name for p in self._primed.values() if p.is_active()]

    # ── Spreading activation ──────────────────────────────────────────────────

    def spread_from(
        self,
        anchor_ids: List[str],
        entity_graph: Dict[str, List[Tuple[str, str, float]]],
        depth: int = 2,
        decay: float = 0.6,
    ) -> Dict[str, float]:
        """
        BFS spreading activation from anchor entities.

        entity_graph: {entity_id: [(target_id, relation, weight), ...]}
        Returns {entity_id: activation_score} for all reached non-anchor nodes.
        """
        activation: Dict[str, float] = {}
        queue: deque = deque()
        visited = set(anchor_ids)

        for aid in anchor_ids:
            activation[aid] = 1.0
            queue.append((aid, 1.0, 0))

        while queue:
            current_id, current_act, current_depth = queue.popleft()
            if current_depth >= depth:
                continue
            for target_id, _relation, weight in entity_graph.get(current_id, []):
                spread = current_act * decay * weight
                if spread < 0.05:
                    continue
                prev = activation.get(target_id, 0.0)
                activation[target_id] = max(prev, spread)
                if target_id not in visited:
                    visited.add(target_id)
                    queue.append((target_id, spread, current_depth + 1))

        # Remove anchors from output
        return {eid: score for eid, score in activation.items() if eid not in anchor_ids}

    # ── Search result augmentation ────────────────────────────────────────────

    def augment_search_results(
        self,
        results: List[Dict[str, Any]],
        anchor_ids: Optional[List[str]] = None,
        entity_graph: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        """
        Re-rank search results by adding priming + spreading activation boost.

        results: list of dicts with 'entity_id' and 'score' keys.
        anchor_ids: entities to spread from (optional, uses primed entities if None).
        Returns results sorted by augmented score.
        """
        self._cleanup_expired()

        # Build spreading activation if anchors provided
        spread_scores: Dict[str, float] = {}
        effective_anchors = anchor_ids or list(self._primed.keys())
        if effective_anchors and entity_graph:
            spread_scores = self.spread_from(effective_anchors, entity_graph, depth=2)

        augmented = []
        for r in results:
            eid = r.get("entity_id", "")
            original_score = r.get("score", 0.0)

            # Priming boost (decays over time)
            prime_boost = self.get_primed_boost(eid)

            # Spreading activation boost
            spread_boost = spread_scores.get(eid, 0.0) * 0.2

            augmented_score = min(1.0, original_score + prime_boost + spread_boost)
            augmented.append({**r, "score": augmented_score, "prime_boost": prime_boost})

        augmented.sort(key=lambda x: -x["score"])
        return augmented

    def snapshot(self) -> Dict[str, Any]:
        self._cleanup_expired()
        return {
            "primed_count": len(self._primed),
            "primed_entities": self.get_active_primes(),
        }


_ai: Optional[AssociativeIndexer] = None

def get_associative_indexer() -> AssociativeIndexer:
    global _ai
    if _ai is None:
        _ai = AssociativeIndexer()
    return _ai


if __name__ == "__main__":
    ai = get_associative_indexer()

    ai.prime(["e1", "e2"], {"e1": "NSE API", "e2": "Lokesh"})
    print(f"Active primes: {ai.get_active_primes()}")
    print(f"Boost for e1: {ai.get_primed_boost('e1'):.3f}")
    print(f"Boost for e3 (unprimed): {ai.get_primed_boost('e3'):.3f}")

    graph = {
        "e1": [("e3", "used_by", 0.9), ("e4", "depends_on", 0.7)],
        "e2": [("e3", "knows", 0.8)],
    }
    spread = ai.spread_from(["e1"], graph)
    print(f"Spreading from e1: {spread}")

    results = [
        {"entity_id": "e3", "score": 0.5, "text": "NSE integration"},
        {"entity_id": "e5", "score": 0.8, "text": "Python tutorial"},
    ]
    augmented = ai.augment_search_results(results, anchor_ids=["e1"], entity_graph=graph)
    print(f"Augmented results: {[(r['entity_id'], round(r['score'],3)) for r in augmented]}")
