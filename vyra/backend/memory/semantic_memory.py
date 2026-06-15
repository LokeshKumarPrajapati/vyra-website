"""
VYRA Semantic Memory — Structured Factual Knowledge
=====================================================
Based on Tulving (1972) episodic vs semantic memory distinction.

Semantic memory = context-free facts about the world.
  "Python is a programming language"
  "Lokesh works in fintech"
  "NSE opens at 9:15 AM"

Distinct from episodic memory (what HAPPENED) — semantic memory
stores what IS TRUE right now, with temporal versioning for things
that change.

Features:
  1. IS-A TYPE HIERARCHY
     - Concepts inherit properties from parents
     - "Django is-a Python framework" → Django inherits Python's facts

  2. TEMPORAL VERSIONING
     - Facts can have valid_from / valid_until dates
     - Old facts are never hard-deleted (audit trail)
     - Query always returns currently-valid facts by default

  3. CONTRADICTION DETECTION
     - Flags when two facts conflict for the same (concept, property)
     - "X is Y" vs "X is Z" → contradiction

  4. KNOWLEDGE DEPTH SCORE
     - Per concept: how much does VYRA know? (0.0–1.0)
     - Based on fact count + confidence + freshness
"""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

DATA_DIR   = Path(__file__).parent.parent / "data"
SEM_PATH   = DATA_DIR / "semantic_memory.json"


@dataclass
class SemanticFact:
    concept: str
    property: str
    value: str
    confidence: float = 0.9
    source: str = "inferred"       # "user_stated" | "inferred" | "researched"
    valid_from: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    valid_until: Optional[str] = None   # None = still valid
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def is_valid(self) -> bool:
        if self.valid_until is None:
            return True
        return datetime.utcnow().isoformat() < self.valid_until

    def age_days(self) -> float:
        try:
            created = datetime.fromisoformat(self.created_at)
            return (datetime.utcnow() - created).total_seconds() / 86400.0
        except Exception:
            return 0.0


@dataclass
class ConceptNode:
    name: str
    parent: Optional[str] = None    # IS-A parent concept
    facts: List[SemanticFact] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)


class SemanticMemory:
    """
    Structured factual world knowledge with IS-A inheritance and temporal versioning.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._concepts: Dict[str, ConceptNode] = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(SEM_PATH.read_text())
            for name, data in raw.items():
                facts = [SemanticFact(**f) for f in data.get("facts", [])]
                node = ConceptNode(
                    name=data["name"],
                    parent=data.get("parent"),
                    facts=facts,
                    aliases=data.get("aliases", []),
                )
                self._concepts[name] = node
        except Exception:
            pass

    def _save(self):
        try:
            out = {}
            for name, node in self._concepts.items():
                out[name] = {
                    "name": node.name,
                    "parent": node.parent,
                    "aliases": node.aliases,
                    "facts": [asdict(f) for f in node.facts],
                }
            SEM_PATH.write_text(json.dumps(out, indent=2))
        except Exception:
            pass

    def _get_or_create(self, concept: str) -> ConceptNode:
        key = concept.lower().strip()
        if key not in self._concepts:
            self._concepts[key] = ConceptNode(name=concept)
        return self._concepts[key]

    # ── IS-A hierarchy ────────────────────────────────────────────────────────

    def declare_is_a(self, concept: str, parent: str):
        """Declare that concept IS-A parent (e.g. Django IS-A Python framework)."""
        node = self._get_or_create(concept)
        node.parent = parent.lower().strip()
        self._get_or_create(parent)
        self._save()

    def get_ancestors(self, concept: str) -> List[str]:
        """Return chain of IS-A ancestors for a concept."""
        ancestors = []
        current = concept.lower().strip()
        seen = set()
        while current and current not in seen:
            seen.add(current)
            node = self._concepts.get(current)
            if not node or not node.parent:
                break
            ancestors.append(node.parent)
            current = node.parent
        return ancestors

    # ── Fact assertion ────────────────────────────────────────────────────────

    def assert_fact(
        self,
        concept: str,
        property: str,
        value: str,
        confidence: float = 0.9,
        source: str = "inferred",
    ) -> SemanticFact:
        """
        Assert a fact. If a conflicting fact exists for (concept, property),
        retract the old one first.
        """
        node = self._get_or_create(concept)
        prop_key = property.lower().strip()

        # Retract any existing valid facts for this property
        for existing in node.facts:
            if existing.property.lower() == prop_key and existing.is_valid():
                existing.valid_until = datetime.utcnow().isoformat()

        fact = SemanticFact(
            concept=concept,
            property=property,
            value=value,
            confidence=confidence,
            source=source,
        )
        node.facts.append(fact)
        self._save()
        return fact

    def retract(self, concept: str, property: str):
        """Mark a fact as expired (temporal versioning — never hard-delete)."""
        node = self._concepts.get(concept.lower().strip())
        if not node:
            return
        for fact in node.facts:
            if fact.property.lower() == property.lower() and fact.is_valid():
                fact.valid_until = datetime.utcnow().isoformat()
        self._save()

    # ── Querying ──────────────────────────────────────────────────────────────

    def query(self, concept: str, include_inherited: bool = True) -> List[SemanticFact]:
        """
        Return all currently-valid facts for a concept.
        Optionally include facts inherited from parent concepts (IS-A).
        """
        key = concept.lower().strip()
        direct = []
        node = self._concepts.get(key)
        if node:
            direct = [f for f in node.facts if f.is_valid()]

        if not include_inherited:
            return direct

        inherited = []
        for ancestor in self.get_ancestors(concept):
            anc_node = self._concepts.get(ancestor)
            if anc_node:
                # Only inherit properties not already set on the concept
                direct_props = {f.property.lower() for f in direct}
                for f in anc_node.facts:
                    if f.is_valid() and f.property.lower() not in direct_props:
                        inherited.append(f)

        return direct + inherited

    def get_value(self, concept: str, property: str) -> Optional[str]:
        """Get the current value of a specific property for a concept."""
        for fact in self.query(concept):
            if fact.property.lower() == property.lower():
                return fact.value
        return None

    # ── Contradiction detection ───────────────────────────────────────────────

    def detect_contradictions(self) -> List[Tuple[SemanticFact, SemanticFact]]:
        """
        Find pairs of simultaneously-valid facts on the same (concept, property)
        with different values — these are contradictions.
        """
        contradictions = []
        for node in self._concepts.values():
            valid = [f for f in node.facts if f.is_valid()]
            by_prop: Dict[str, List[SemanticFact]] = {}
            for f in valid:
                pk = f.property.lower()
                by_prop.setdefault(pk, []).append(f)
            for _prop, facts in by_prop.items():
                if len(facts) >= 2:
                    # All unique value pairs are contradictions
                    for i in range(len(facts)):
                        for j in range(i + 1, len(facts)):
                            if facts[i].value != facts[j].value:
                                contradictions.append((facts[i], facts[j]))
        return contradictions

    # ── Knowledge depth ───────────────────────────────────────────────────────

    def get_concept_depth(self, concept: str) -> float:
        """
        0.0–1.0 score representing how deeply VYRA knows this concept.
        Based on: fact count (weighted), avg confidence, recency.
        """
        facts = self.query(concept, include_inherited=False)
        if not facts:
            return 0.0
        fact_score   = min(1.0, len(facts) / 10.0)
        avg_conf     = sum(f.confidence for f in facts) / len(facts)
        # Recency: facts < 30 days old get full credit
        recency_scores = [max(0.0, 1.0 - f.age_days() / 365.0) for f in facts]
        avg_recency  = sum(recency_scores) / len(recency_scores)
        return round(fact_score * 0.4 + avg_conf * 0.4 + avg_recency * 0.2, 3)

    def get_all_concepts(self) -> List[Dict[str, Any]]:
        """All concepts with depth scores — for dashboard brain map."""
        results = []
        for key, node in self._concepts.items():
            valid_facts = [f for f in node.facts if f.is_valid()]
            results.append({
                "concept": node.name,
                "parent": node.parent,
                "fact_count": len(valid_facts),
                "depth": self.get_concept_depth(key),
                "aliases": node.aliases,
            })
        results.sort(key=lambda x: -x["depth"])
        return results

    def snapshot(self) -> Dict[str, Any]:
        total_facts = sum(
            len([f for f in n.facts if f.is_valid()])
            for n in self._concepts.values()
        )
        contradictions = self.detect_contradictions()
        return {
            "total_concepts": len(self._concepts),
            "total_valid_facts": total_facts,
            "contradiction_count": len(contradictions),
            "top_concepts": [c["concept"] for c in self.get_all_concepts()[:5]],
        }


_sm: Optional[SemanticMemory] = None

def get_semantic_memory() -> SemanticMemory:
    global _sm
    if _sm is None:
        _sm = SemanticMemory()
    return _sm


if __name__ == "__main__":
    sm = get_semantic_memory()

    sm.declare_is_a("Django", "Python Framework")
    sm.declare_is_a("FastAPI", "Python Framework")
    sm.assert_fact("Python", "type", "programming language", confidence=1.0, source="user_stated")
    sm.assert_fact("Python", "paradigm", "multi-paradigm", confidence=0.95)
    sm.assert_fact("Lokesh", "occupation", "software engineer", confidence=0.9, source="user_stated")
    sm.assert_fact("NSE", "opens_at", "9:15 AM IST", confidence=1.0, source="user_stated")

    print("Python facts:", [(f.property, f.value) for f in sm.query("Python")])
    print("Django depth:", sm.get_concept_depth("django"))
    print("Contradictions:", sm.detect_contradictions())
    print("Snapshot:", sm.snapshot())
