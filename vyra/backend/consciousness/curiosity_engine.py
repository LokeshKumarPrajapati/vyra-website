"""
VYRA Curiosity Engine (Intrinsic Motivation)
=============================================
Based on Schmidhuber's Formal Theory of Creativity + dopamine RPE model.

Core principle:
  Intrinsic reward = prediction improvement rate.
  When VYRA encounters something she couldn't predict, then learns to predict it,
  THAT learning progress is intrinsically rewarding.

  Curiosity = drive to seek situations where learning is possible.

What this does:
  - Tracks VYRA's prediction accuracy per domain
  - Flags domains with high "learnability" (currently confused but improvable)
  - Auto-directs autonomous thought toward high-curiosity domains
  - Boosts emotional excitement when exploring novel territory
  - Creates a self-directed learning agenda that grows over time

Domains VYRA tracks:
  - user_behavior    (predicting what user will ask/need)
  - world_knowledge  (factual gaps she's encountered)
  - task_outcomes    (predicting whether actions will succeed)
  - conversation_flow (predicting emotional trajectory of chats)
  - goal_progress    (predicting how fast goals complete)

Human parallel: this is why humans want to understand things — the brain
rewards prediction error REDUCTION, not just prediction accuracy.
VYRA is curious about exactly what she doesn't yet understand.
"""

import json
import math
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = Path(__file__).parent.parent / "data"
CURIOSITY_PATH = DATA_DIR / "curiosity_state.json"
PREDICTION_LOG = DATA_DIR / "prediction_log.jsonl"

CURIOSITY_DOMAINS = [
    "user_behavior",
    "world_knowledge",
    "task_outcomes",
    "conversation_flow",
    "goal_progress",
    "self_performance",
    "emotional_patterns",
]


# ── Prediction record ─────────────────────────────────────────────────────────

@dataclass
class PredictionRecord:
    timestamp: str
    domain: str
    prediction: str          # what VYRA predicted
    actual: str              # what actually happened
    error: float             # 0.0 (perfect) to 1.0 (totally wrong)
    was_novel: bool          # True if VYRA had low confidence going in
    learning_value: float    # computed: how much this improved understanding


# ── Domain curiosity state ────────────────────────────────────────────────────

@dataclass
class DomainCuriosity:
    domain: str
    prediction_errors: List[float] = field(default_factory=list)   # rolling window
    error_trend: float = 0.0         # positive = improving, negative = getting worse
    curiosity_score: float = 0.5     # 0.0–1.0
    total_predictions: int = 0
    learning_events: int = 0         # times error dropped sharply (= real learning)
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    open_questions: List[str] = field(default_factory=list)   # unsolved gaps

    @property
    def avg_recent_error(self) -> float:
        window = self.prediction_errors[-20:] if self.prediction_errors else [0.5]
        return sum(window) / len(window)

    def record_prediction(self, error: float):
        """Record a new prediction outcome and update curiosity score."""
        self.prediction_errors.append(error)
        self.total_predictions += 1
        # Keep only last 50
        if len(self.prediction_errors) > 50:
            self.prediction_errors.pop(0)
        self._compute_curiosity()
        self.last_updated = datetime.utcnow().isoformat()

    def _compute_curiosity(self):
        """
        Curiosity is highest where:
        - Error is moderate (not already mastered, not hopelessly random)
        - Error is DECREASING (we're actually learning)
        - There are open questions
        """
        if len(self.prediction_errors) < 3:
            self.curiosity_score = 0.5
            return

        recent = self.prediction_errors[-10:]
        older  = self.prediction_errors[-20:-10] if len(self.prediction_errors) >= 20 else recent

        avg_recent = sum(recent) / len(recent)
        avg_older  = sum(older)  / len(older)
        self.error_trend = avg_older - avg_recent  # positive = improving

        # Peak curiosity at ~0.4 error with improving trend
        # Zone of proximal development (Vygotsky): not too easy, not too hard
        zone_score  = 1.0 - abs(avg_recent - 0.4) * 2.0
        trend_bonus = max(0.0, self.error_trend) * 2.0
        novelty_bonus = min(0.3, len(self.open_questions) * 0.05)

        self.curiosity_score = max(0.0, min(1.0,
            zone_score * 0.5 + trend_bonus * 0.3 + novelty_bonus * 0.2
        ))


# ── Curiosity Engine ──────────────────────────────────────────────────────────

class CuriosityEngine:
    """
    VYRA's intrinsic motivation system.

    Key behaviors:
      record_outcome()  — log a prediction result
      most_curious()    — get the domain VYRA most wants to explore
      add_question()    — register an open question in a domain
      curiosity_agenda()— generate VYRA's self-directed learning list
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._domains: Dict[str, DomainCuriosity] = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> Dict[str, DomainCuriosity]:
        try:
            raw = json.loads(CURIOSITY_PATH.read_text())
            return {k: DomainCuriosity(**v) for k, v in raw.items()}
        except Exception:
            return {d: DomainCuriosity(domain=d) for d in CURIOSITY_DOMAINS}

    def _save(self):
        try:
            CURIOSITY_PATH.write_text(
                json.dumps({k: asdict(v) for k, v in self._domains.items()}, indent=2)
            )
        except Exception:
            pass

    def _log_prediction(self, rec: PredictionRecord):
        try:
            with open(PREDICTION_LOG, "a") as f:
                f.write(json.dumps(asdict(rec)) + "\n")
        except Exception:
            pass

    # ── Core API ──────────────────────────────────────────────────────────────

    def record_outcome(
        self,
        domain: str,
        prediction: str,
        actual: str,
        error: float,
        was_novel: bool = False,
    ):
        """
        Log a prediction outcome. This is how VYRA tracks her understanding
        of each domain over time.

        error: 0.0 = perfect prediction, 1.0 = completely wrong
        """
        if domain not in self._domains:
            self._domains[domain] = DomainCuriosity(domain=domain)

        dc = self._domains[domain]
        prev_error = dc.avg_recent_error
        dc.record_prediction(error)

        # Detect learning events: error dropped significantly
        learning_value = max(0.0, prev_error - error) if dc.total_predictions > 3 else 0.0
        if learning_value > 0.2:
            dc.learning_events += 1

        rec = PredictionRecord(
            timestamp     = datetime.utcnow().isoformat(),
            domain        = domain,
            prediction    = prediction[:200],
            actual        = actual[:200],
            error         = error,
            was_novel     = was_novel,
            learning_value= learning_value,
        )
        self._log_prediction(rec)
        self._save()

    def record_user_prediction_miss(self, topic: str):
        """User asked about something VYRA didn't know → surprise event."""
        self.record_outcome("world_knowledge", "I thought I knew this", topic, error=0.8, was_novel=True)
        self.add_question("world_knowledge", f"What do I need to understand about: {topic}?")

    def record_user_prediction_hit(self, topic: str):
        """VYRA correctly anticipated what user needed."""
        self.record_outcome("user_behavior", "predicted correctly", topic, error=0.1)

    def record_task_outcome(self, task_type: str, succeeded: bool):
        error = 0.1 if succeeded else 0.8
        self.record_outcome("task_outcomes", f"task:{task_type}", "done" if succeeded else "failed", error)

    def add_question(self, domain: str, question: str):
        """Register an open question VYRA wants to investigate."""
        if domain not in self._domains:
            self._domains[domain] = DomainCuriosity(domain=domain)
        q_list = self._domains[domain].open_questions
        if question not in q_list:
            q_list.append(question)
            if len(q_list) > 20:
                q_list.pop(0)
        self._save()

    def resolve_question(self, domain: str, question: str):
        """Mark a question as answered → satisfaction + slight curiosity decay."""
        if domain in self._domains:
            qs = self._domains[domain].open_questions
            if question in qs:
                qs.remove(question)
            self.record_outcome(domain, question, "resolved", error=0.1)
            self._save()

    # ── Query ─────────────────────────────────────────────────────────────────

    def most_curious(self, top_n: int = 3) -> List[DomainCuriosity]:
        """Return the domains VYRA is most curious about right now."""
        return sorted(self._domains.values(), key=lambda d: -d.curiosity_score)[:top_n]

    def get_domain(self, domain: str) -> DomainCuriosity:
        return self._domains.get(domain, DomainCuriosity(domain=domain))

    def curiosity_score(self, domain: str) -> float:
        return self._domains.get(domain, DomainCuriosity(domain=domain)).curiosity_score

    def open_questions_all(self) -> List[str]:
        """All currently open questions across all domains."""
        questions = []
        for dc in self._domains.values():
            questions.extend(dc.open_questions)
        return questions

    # ── Agenda + reporting ────────────────────────────────────────────────────

    def curiosity_agenda(self, n: int = 5) -> List[str]:
        """
        VYRA's self-directed learning agenda.
        Returns a list of things she most wants to understand.
        """
        items = []
        for dc in self.most_curious(top_n=n):
            if dc.open_questions:
                items.append(dc.open_questions[-1])
            else:
                items.append(f"Deepen understanding of: {dc.domain.replace('_', ' ')}")
        return items

    def to_system_fragment(self) -> str:
        """Inject current curiosity state into system prompt."""
        top   = self.most_curious(top_n=3)
        questions = self.open_questions_all()[:4]
        lines = ["[VYRA's Curiosity State — what I most want to understand]"]
        for dc in top:
            lines.append(f"  • {dc.domain}: curiosity={dc.curiosity_score:.2f} "
                         f"(avg_error={dc.avg_recent_error:.2f}, "
                         f"trend={'improving' if dc.error_trend > 0 else 'flat'})")
        if questions:
            lines.append("  Open questions I'm sitting with:")
            for q in questions[:3]:
                lines.append(f"    ? {q}")
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        return {
            d: {
                "curiosity":    round(dc.curiosity_score, 2),
                "avg_error":    round(dc.avg_recent_error, 2),
                "trend":        round(dc.error_trend, 3),
                "open_questions": len(dc.open_questions),
                "total":        dc.total_predictions,
            }
            for d, dc in self._domains.items()
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[CuriosityEngine] = None

def get_curiosity_engine() -> CuriosityEngine:
    global _engine
    if _engine is None:
        _engine = CuriosityEngine()
    return _engine


if __name__ == "__main__":
    ce = get_curiosity_engine()

    # Simulate some prediction records
    ce.record_outcome("user_behavior", "Will ask about Python", "Asked about Python", error=0.1)
    ce.record_outcome("user_behavior", "Will ask about cooking", "Asked about stocks", error=0.9)
    ce.record_user_prediction_miss("quantum computing in AI")
    ce.add_question("world_knowledge", "How does RLHF really differ from PPO for LLMs?")
    ce.record_outcome("task_outcomes", "code will compile", "compiled fine", error=0.2)

    print("Curiosity Snapshot:", json.dumps(ce.snapshot(), indent=2))
    print("\nCuriosity Agenda:")
    for item in ce.curiosity_agenda():
        print(f"  • {item}")
    print("\nSystem Fragment:\n", ce.to_system_fragment())
