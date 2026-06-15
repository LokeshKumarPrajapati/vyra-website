"""
VYRA Metacognition II — Calibrated Self-Awareness
===================================================
Phase 1 metacognition detects complexity and hedges answers.
This goes deeper: VYRA knows WHAT SHE KNOWS with calibrated accuracy.

True metacognition = the accuracy of your confidence.
A well-calibrated mind: when it says 80% confident, it's right ~80% of the time.
LLMs are notoriously OVERCONFIDENT — they assert falsehoods with the same
tone as facts. This module fixes that.

Three layers:
  1. DOMAIN CALIBRATION
     - Tracks confidence vs accuracy per knowledge domain
     - Adjusts future confidence to match historical accuracy
     - "I'm consistently overconfident about finance — hedge more there"

  2. KNOWLEDGE BOUNDARY DETECTION
     - Proactively detects when VYRA is near the edge of what she knows
     - Flags: "I should research before answering this"
     - Prevents hallucination by stopping before the cliff

  3. STRATEGY SELECTION
     - Based on confidence + complexity, selects reasoning strategy:
       HIGH confidence + LOW complexity → fast answer
       LOW confidence + ANY complexity  → research first
       ANY confidence + HIGH complexity  → deep CoT
       CRITICAL action + ANY confidence  → simulate first

This is what makes VYRA genuinely intellectually honest —
not just saying "I'm not sure" as a safety phrase, but actually
knowing when she's sure and when she's not.
"""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR    = Path(__file__).parent.parent / "data"
META2_PATH  = DATA_DIR / "metacognition2.json"
META2_LOG   = DATA_DIR / "metacognition2_log.jsonl"

KNOWLEDGE_DOMAINS = [
    "python", "javascript", "machine_learning", "mathematics",
    "finance", "biology", "physics", "history", "law",
    "medicine", "psychology", "cooking", "music", "art",
    "hardware", "networking", "databases", "security",
    "project_management", "business", "design",
]


@dataclass
class DomainCalibration:
    domain: str
    stated_confidence: List[float] = field(default_factory=list)   # what VYRA claimed
    actual_accuracy:   List[float] = field(default_factory=list)   # what proved true
    calibration_error: float = 0.0   # positive = overconfident, negative = underconfident
    n_observations: int = 0
    knowledge_boundary: float = 0.7  # estimated edge of reliable knowledge
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def record(self, stated: float, actual: float):
        self.stated_confidence.append(stated)
        self.actual_accuracy.append(actual)
        self.stated_confidence = self.stated_confidence[-30:]
        self.actual_accuracy   = self.actual_accuracy[-30:]
        self.n_observations   += 1
        if len(self.stated_confidence) >= 5:
            avg_stated = sum(self.stated_confidence) / len(self.stated_confidence)
            avg_actual = sum(self.actual_accuracy)   / len(self.actual_accuracy)
            self.calibration_error = avg_stated - avg_actual  # + = overconfident
        self.last_updated = datetime.utcnow().isoformat()

    def calibrated_confidence(self, raw: float) -> float:
        """Adjust raw confidence by calibration error."""
        adjusted = raw - self.calibration_error * 0.5
        return max(0.05, min(0.99, adjusted))

    @property
    def is_overconfident(self) -> bool:
        return self.calibration_error > 0.15

    @property
    def is_underconfident(self) -> bool:
        return self.calibration_error < -0.15


@dataclass
class StrategyChoice:
    query: str
    domain: str
    raw_confidence: float
    calibrated_confidence: float
    complexity: float
    strategy: str     # "fast" | "cot" | "research_first" | "simulate" | "ask_user"
    reasoning: str


STRATEGY_RULES = [
    # (min_conf, max_conf, min_complexity, strategy, reasoning)
    (0.85, 1.0, 0.0, 0.3, "fast",           "High confidence, low complexity — answer directly"),
    (0.0,  0.4, 0.0, 1.0, "research_first", "Low confidence — research before answering"),
    (0.0,  1.0, 0.7, 1.0, "cot",            "High complexity — use chain of thought"),
    (0.0,  0.6, 0.4, 1.0, "cot",            "Moderate confidence + moderate complexity — think carefully"),
    (0.85, 1.0, 0.3, 1.0, "fast",           "High confidence — proceed"),
]


class Metacognition2:
    """
    Calibrated self-awareness — VYRA knows what she knows.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._domains: Dict[str, DomainCalibration] = self._load()
        self._recent_strategies: List[StrategyChoice] = []
        self._boundary_flags: List[Dict] = []

    def _load(self) -> Dict[str, DomainCalibration]:
        try:
            raw = json.loads(META2_PATH.read_text())
            return {k: DomainCalibration(**v) for k, v in raw.items()}
        except Exception:
            return {d: DomainCalibration(domain=d) for d in KNOWLEDGE_DOMAINS}

    def _save(self):
        try:
            META2_PATH.write_text(
                json.dumps({k: asdict(v) for k, v in self._domains.items()}, indent=2)
            )
        except Exception:
            pass

    def get_domain(self, domain: str) -> DomainCalibration:
        if domain not in self._domains:
            self._domains[domain] = DomainCalibration(domain=domain)
        return self._domains[domain]

    # ── Calibration recording ─────────────────────────────────────────────────

    def record_calibration(self, domain: str, stated_confidence: float, was_correct: bool):
        """
        After learning if an answer was correct, record calibration data.
        Called by self_improvement when user corrections come in.
        """
        dc = self.get_domain(domain)
        dc.record(stated_confidence, 1.0 if was_correct else 0.0)
        self._save()

    def on_correction(self, domain: str, stated_confidence: float = 0.8):
        """User corrected VYRA — she was overconfident."""
        self.record_calibration(domain, stated_confidence, was_correct=False)

    def on_confirmed(self, domain: str, stated_confidence: float = 0.8):
        """Answer was confirmed correct."""
        self.record_calibration(domain, stated_confidence, was_correct=True)

    # ── Confidence calibration ────────────────────────────────────────────────

    def calibrate(self, domain: str, raw_confidence: float) -> float:
        """Return calibrated confidence for a domain."""
        return self.get_domain(domain).calibrated_confidence(raw_confidence)

    def is_near_boundary(self, domain: str, confidence: float) -> bool:
        """Is VYRA near the edge of reliable knowledge in this domain?"""
        dc = self.get_domain(domain)
        return confidence < dc.knowledge_boundary * 0.7

    def should_flag_uncertainty(self, domain: str, confidence: float) -> bool:
        """Should VYRA explicitly flag that she might be wrong?"""
        cal_conf = self.calibrate(domain, confidence)
        return cal_conf < 0.6 or self.is_near_boundary(domain, confidence)

    # ── Strategy selection ────────────────────────────────────────────────────

    def select_strategy(
        self,
        query: str,
        domain: str,
        raw_confidence: float = 0.7,
        complexity: float = 0.5,
    ) -> StrategyChoice:
        """
        Select the right reasoning strategy for this query.
        Returns one of: fast | cot | research_first | simulate | ask_user
        """
        cal_conf = self.calibrate(domain, raw_confidence)
        strategy = "cot"   # default
        reasoning = "Default: use chain of thought"

        # Near knowledge boundary → research first
        if self.is_near_boundary(domain, cal_conf):
            strategy  = "research_first"
            reasoning = f"Near knowledge boundary in {domain} (conf={cal_conf:.2f})"

        # Very low confidence → research
        elif cal_conf < 0.4:
            strategy  = "research_first"
            reasoning = f"Low calibrated confidence ({cal_conf:.2f}) in {domain}"

        # High confidence, low complexity → fast
        elif cal_conf >= 0.85 and complexity < 0.3:
            strategy  = "fast"
            reasoning = f"High confidence ({cal_conf:.2f}), low complexity"

        # High complexity → always CoT
        elif complexity >= 0.7:
            strategy  = "cot"
            reasoning = f"High complexity task ({complexity:.2f})"

        choice = StrategyChoice(
            query=query[:80], domain=domain,
            raw_confidence=raw_confidence,
            calibrated_confidence=cal_conf,
            complexity=complexity,
            strategy=strategy, reasoning=reasoning,
        )
        self._recent_strategies.append(choice)
        self._recent_strategies = self._recent_strategies[-20:]
        return choice

    def detect_topic_domain(self, query: str) -> str:
        """Heuristic: map a query to its primary knowledge domain."""
        q = query.lower()
        mappings = [
            (["python", "django", "flask", "asyncio", "pandas"],   "python"),
            (["javascript", "typescript", "react", "node"],        "javascript"),
            (["ml", "neural", "training", "model", "llm", "ai"],   "machine_learning"),
            (["calculus", "algebra", "statistics", "matrix"],      "mathematics"),
            (["stock", "finance", "investment", "crypto", "nse"],  "finance"),
            (["biology", "gene", "cell", "dna", "protein"],        "biology"),
            (["physics", "quantum", "relativity", "force"],        "physics"),
            (["law", "legal", "contract", "rights"],               "law"),
            (["medical", "disease", "symptom", "diagnosis"],       "medicine"),
            (["psychology", "behavior", "mental", "cognitive"],    "psychology"),
            (["database", "sql", "postgres", "mongodb"],           "databases"),
            (["security", "exploit", "vulnerability", "pen"],      "security"),
        ]
        for keywords, domain in mappings:
            if any(kw in q for kw in keywords):
                return domain
        return "general"

    # ── Overconfident domain detection ────────────────────────────────────────

    def most_overconfident_domains(self, n: int = 3) -> List[DomainCalibration]:
        return sorted(
            [dc for dc in self._domains.values() if dc.n_observations >= 3],
            key=lambda dc: -dc.calibration_error
        )[:n]

    def calibration_summary(self) -> str:
        overconf = self.most_overconfident_domains(3)
        if not overconf:
            return "Calibration data not yet collected."
        parts = []
        for dc in overconf:
            if dc.is_overconfident:
                parts.append(f"overconfident in {dc.domain} (+{dc.calibration_error:.2f})")
            elif dc.is_underconfident:
                parts.append(f"underconfident in {dc.domain} ({dc.calibration_error:.2f})")
        return "Calibration: " + "; ".join(parts) if parts else "Well calibrated."

    def to_system_fragment(self) -> str:
        summary = self.calibration_summary()
        overconf = [dc.domain for dc in self.most_overconfident_domains() if dc.is_overconfident]
        lines = [f"[VYRA's Self-Knowledge Calibration]"]
        lines.append(f"  {summary}")
        if overconf:
            lines.append(f"  Hedge more carefully on: {', '.join(overconf)}")
        if self._recent_strategies:
            last = self._recent_strategies[-1]
            lines.append(f"  Last strategy: {last.strategy} for '{last.query[:40]}' ({last.reasoning})")
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "domains_calibrated": sum(1 for dc in self._domains.values() if dc.n_observations >= 3),
            "overconfident": [dc.domain for dc in self.most_overconfident_domains() if dc.is_overconfident],
            "recent_strategy": self._recent_strategies[-1].strategy if self._recent_strategies else None,
        }


_mc2: Optional[Metacognition2] = None
def get_metacognition2() -> Metacognition2:
    global _mc2
    if _mc2 is None:
        _mc2 = Metacognition2()
    return _mc2
