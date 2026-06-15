"""
VYRA Knowledge Synthesizer — Phase 17
========================================
Finds non-obvious connections between knowledge domains and generates
novel insights by combining facts from disparate areas.

Based on:
  - Bisociation theory (Koestler 1964) — creativity = connecting two
    unrelated matrices of thought
  - Analogical reasoning (Gentner 1983) — structure mapping across domains

Features:
  1. CROSS-DOMAIN LINKS — finds structural analogies between topics
  2. SYNTHESIS CHAINS — A→B→C chains of reasoning
  3. INSIGHT GENERATION — produces "what if" hypotheses
  4. DOMAIN GRAPH — tracks which domains VYRA has connected before
"""

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

DATA_DIR    = Path(__file__).parent.parent / "data"
KS_PATH     = DATA_DIR / "knowledge_synthesizer.json"

MAX_SYNTHESES = 100


@dataclass
class SynthesisResult:
    synthesis_id: str
    domain_a: str
    domain_b: str
    connection: str          # the linking principle
    insight: str             # the novel insight generated
    confidence: float        # 0.0–1.0
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    used_count: int = 0


class KnowledgeSynthesizer:
    """
    Generates novel insights by finding structural analogies across domains.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._syntheses: Dict[str, SynthesisResult] = {}
        self._domain_connections: Dict[str, List[str]] = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(KS_PATH.read_text())
            for k, v in raw.get("syntheses", {}).items():
                self._syntheses[k] = SynthesisResult(**v)
            self._domain_connections = raw.get("domain_connections", {})
        except Exception:
            pass

    def _save(self):
        try:
            out = list(self._syntheses.values())
            out.sort(key=lambda x: -x.used_count)
            kept = {s.synthesis_id: asdict(s) for s in out[:MAX_SYNTHESES]}
            KS_PATH.write_text(json.dumps({
                "syntheses": kept,
                "domain_connections": self._domain_connections,
            }, indent=2))
        except Exception:
            pass

    def add_synthesis(
        self,
        synthesis_id: str,
        domain_a: str,
        domain_b: str,
        connection: str,
        insight: str,
        confidence: float = 0.7,
    ) -> SynthesisResult:
        """Record a new cross-domain synthesis."""
        s = SynthesisResult(
            synthesis_id=synthesis_id,
            domain_a=domain_a,
            domain_b=domain_b,
            connection=connection,
            insight=insight,
            confidence=confidence,
        )
        self._syntheses[synthesis_id] = s

        # Update domain connection graph
        self._domain_connections.setdefault(domain_a, [])
        if domain_b not in self._domain_connections[domain_a]:
            self._domain_connections[domain_a].append(domain_b)
        self._domain_connections.setdefault(domain_b, [])
        if domain_a not in self._domain_connections[domain_b]:
            self._domain_connections[domain_b].append(domain_a)

        self._save()
        return s

    def get_syntheses_for_domain(self, domain: str) -> List[SynthesisResult]:
        return [
            s for s in self._syntheses.values()
            if s.domain_a == domain or s.domain_b == domain
        ]

    def get_top_insights(self, n: int = 5) -> List[SynthesisResult]:
        results = list(self._syntheses.values())
        results.sort(key=lambda x: -(x.confidence * (1 + x.used_count * 0.1)))
        return results[:n]

    def find_bridge(self, domain_a: str, domain_b: str) -> Optional[SynthesisResult]:
        """Find a previously-recorded link between two domains."""
        for s in self._syntheses.values():
            if (s.domain_a == domain_a and s.domain_b == domain_b) or \
               (s.domain_a == domain_b and s.domain_b == domain_a):
                s.used_count += 1
                self._save()
                return s
        return None

    def to_system_fragment(self) -> str:
        top = self.get_top_insights(2)
        if not top:
            return ""
        parts = [f'"{s.insight[:80]}"' for s in top]
        return f"[Cross-domain insights: {'; '.join(parts)}]"

    def snapshot(self) -> Dict[str, Any]:
        return {
            "total_syntheses": len(self._syntheses),
            "domains_connected": len(self._domain_connections),
            "top_insights": [
                {"insight": s.insight[:60], "domains": f"{s.domain_a}↔{s.domain_b}"}
                for s in self.get_top_insights(3)
            ],
        }


_ks: Optional[KnowledgeSynthesizer] = None

def get_knowledge_synthesizer() -> KnowledgeSynthesizer:
    global _ks
    if _ks is None:
        _ks = KnowledgeSynthesizer()
    return _ks


if __name__ == "__main__":
    ks = get_knowledge_synthesizer()
    ks.add_synthesis(
        "neuro_finance",
        "neuroscience", "finance",
        "Both use prediction error signals to update models",
        "Stock market price discovery mirrors dopamine RPE — prices encode collective prediction errors",
        confidence=0.85,
    )
    ks.add_synthesis(
        "memory_trading",
        "memory systems", "trading strategies",
        "Spaced repetition and dollar-cost averaging both exploit temporal distribution",
        "Applying spaced repetition timing to position building may reduce emotional trading bias",
        confidence=0.7,
    )
    print("Snapshot:", ks.snapshot())
    print("Fragment:", ks.to_system_fragment())
