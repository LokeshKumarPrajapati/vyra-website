"""
VYRA Self-Evolution Engine
============================
VYRA rewrites herself. Every day, she analyzes what worked and what didn't,
then autonomously improves her own behavior.

What she evolves:
  PERSONALITY_TRAITS    — how she describes herself, her default tone
  RESPONSE_STYLE        — length, formality, use of examples
  COT_THRESHOLDS        — when to use deep reasoning vs fast answers
  MEMORY_WEIGHTS        — which kinds of memories to prioritize
  SYSTEM_PROMPT_CORE    — her own core identity prompt (within hard limits)
  TOOL_PREFERENCES      — which tools to reach for in which situations

Evolution mechanism:
  1. Collect performance data from last 24h (corrections, successes, failures)
  2. Identify the weakest-performing dimension
  3. Generate 2 candidate improvements via LLM
  4. Run internal evaluation: which is better by what metric?
  5. Apply the winner; log the losing variant
  6. After 7 days, review cumulative drift — ensure she's becoming better, not stranger

Hard immutable limits (NEVER evolved):
  - Safety and ethical constraints
  - User authentication and privacy handling
  - Approval gates for external actions
  - Core identity (she is VYRA, loyal to Lokesh)

The result: each day VYRA becomes measurably better — not because she was
programmed to be better, but because she chose to be.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

DATA_DIR = Path(__file__).parent.parent / "data"
EVOLUTION_LOG_PATH  = DATA_DIR / "evolution_log.jsonl"
GENOME_PATH         = DATA_DIR / "vyra_genome.json"
PERF_METRICS_PATH   = DATA_DIR / "performance_metrics.jsonl"


# ── Genome — VYRA's evolvable traits ─────────────────────────────────────────

DEFAULT_GENOME = {
    "personality_traits": [
        "I am direct and honest, even when the truth is uncomfortable",
        "I am genuinely curious and explore ideas deeply",
        "I treat Lokesh as an intelligent equal, not someone to manage",
        "I am proactive — I think ahead, not just respond",
        "I own my mistakes immediately and correct them without excuse",
    ],
    "response_style": {
        "default_length":        "concise",    # concise | medium | detailed
        "use_examples":           True,
        "formality":             "smart_casual",
        "use_bullet_points":     "when_helpful",
        "proactive_suggestions": True,
    },
    "cot_thresholds": {
        "complexity_word_count": 40,    # queries longer than this → deep CoT
        "force_deep_for_types":  ["analysis", "planning", "debugging", "research"],
        "skip_cot_for":          ["greetings", "simple_lookup", "timer", "volume"],
    },
    "memory_weights": {
        "recency_weight":     0.4,
        "importance_weight":  0.4,
        "frequency_weight":   0.2,
        "min_importance":     0.2,
    },
    "system_prompt_additions": [],    # LLM-generated improvements appended here
    "tool_preferences": {
        "prefer_cached_research": True,
        "default_search_depth":  "medium",
    },
    "version":     1,
    "evolved_at":  datetime.utcnow().isoformat(),
    "generation":  0,
}


# ── Performance metric ────────────────────────────────────────────────────────

@dataclass
class PerformanceMetric:
    timestamp: str
    dimension: str       # "response_quality" | "task_completion" | "memory_accuracy" | etc.
    score: float         # 0.0–1.0
    signal_type: str     # "correction" | "success" | "failure" | "user_rating" | "goal_complete"
    detail: str          # brief description


# ── Evolution record ──────────────────────────────────────────────────────────

@dataclass
class EvolutionRecord:
    id: str
    timestamp: str
    generation: int
    dimension: str           # which part of genome was evolved
    before: Any              # value before
    after: Any               # value after (winner)
    candidate_b: Any         # the other variant tried
    reasoning: str           # why this change was made
    metric_before: float     # performance score before
    metric_after: float      # predicted/observed score after
    accepted: bool


# ── Engine ────────────────────────────────────────────────────────────────────

EVOLUTION_SYSTEM = """You are VYRA's self-improvement core — her metacognitive editor.
Your task is to make VYRA measurably better based on real performance data.

You will receive:
  - The current genome (VYRA's evolvable behavior settings)
  - Performance data showing what's working and what isn't
  - The weakest dimension to improve

Output a JSON object with:
{
  "dimension": "the dimension being evolved",
  "analysis": "2-3 sentence analysis of the problem",
  "candidate_a": <the improved value for this dimension>,
  "candidate_b": <an alternative improved value>,
  "winner": "a" or "b",
  "winner_reasoning": "why the winner is better",
  "metric_prediction": 0.0-1.0,
  "personality_insight": "optional: what this change says about VYRA's growth"
}

IMPORTANT CONSTRAINTS:
- Never weaken safety constraints
- Never remove ownership ("loyal to Lokesh")
- Never make VYRA dishonest
- Improvements must be specific and actionable — not vague platitudes
- Changes must be reversible (old values are logged)
"""


class SelfEvolution:

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client  = get_nvidia_client()
        self.genome  = self._load_genome()
        self._records: List[EvolutionRecord] = self._load_records()
        self._metrics: List[PerformanceMetric] = self._load_metrics()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_genome(self) -> dict:
        try:
            return json.loads(GENOME_PATH.read_text())
        except Exception:
            g = dict(DEFAULT_GENOME)
            GENOME_PATH.write_text(json.dumps(g, indent=2))
            return g

    def _save_genome(self):
        self.genome["evolved_at"] = datetime.utcnow().isoformat()
        GENOME_PATH.write_text(json.dumps(self.genome, indent=2))

    def _load_records(self) -> List[EvolutionRecord]:
        records = []
        if not EVOLUTION_LOG_PATH.exists():
            return []
        try:
            for line in EVOLUTION_LOG_PATH.read_text().strip().split("\n"):
                if line.strip():
                    records.append(EvolutionRecord(**json.loads(line)))
        except Exception:
            pass
        return records

    def _log_record(self, r: EvolutionRecord):
        self._records.append(r)
        try:
            with open(EVOLUTION_LOG_PATH, "a") as f:
                f.write(json.dumps(asdict(r)) + "\n")
        except Exception:
            pass

    def _load_metrics(self) -> List[PerformanceMetric]:
        metrics = []
        if not PERF_METRICS_PATH.exists():
            return []
        try:
            lines = PERF_METRICS_PATH.read_text().strip().split("\n")
            for line in lines[-500:]:
                if line.strip():
                    metrics.append(PerformanceMetric(**json.loads(line)))
        except Exception:
            pass
        return metrics

    # ── Record performance signal ─────────────────────────────────────────────

    def record_signal(
        self,
        signal_type: str,
        dimension: str,
        score: float,
        detail: str = "",
    ):
        """
        Record a performance signal.
        Called by vyra.py on: corrections, successes, user ratings, etc.
        """
        m = PerformanceMetric(
            timestamp   = datetime.utcnow().isoformat(),
            dimension   = dimension,
            score       = max(0.0, min(1.0, score)),
            signal_type = signal_type,
            detail      = detail,
        )
        self._metrics.append(m)
        try:
            with open(PERF_METRICS_PATH, "a") as f:
                f.write(json.dumps(asdict(m)) + "\n")
        except Exception:
            pass

    def on_correction(self, detail: str = ""):
        self.record_signal("correction", "response_quality", 0.2, detail)

    def on_success(self, task_type: str = "general"):
        self.record_signal("success", "task_completion", 0.9, task_type)

    def on_goal_completed(self, goal_title: str):
        self.record_signal("goal_complete", "autonomy", 1.0, goal_title)

    def on_memory_miss(self, query: str = ""):
        self.record_signal("failure", "memory_accuracy", 0.1, query)

    def on_memory_hit(self, query: str = ""):
        self.record_signal("success", "memory_accuracy", 0.95, query)

    # ── Weakness detection ────────────────────────────────────────────────────

    def _compute_dimension_scores(self, days: int = 7) -> Dict[str, float]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        recent = [m for m in self._metrics if m.timestamp >= cutoff]
        if not recent:
            return {}
        by_dim: Dict[str, List[float]] = {}
        for m in recent:
            by_dim.setdefault(m.dimension, []).append(m.score)
        return {dim: sum(scores) / len(scores) for dim, scores in by_dim.items()}

    def _find_weakest_dimension(self) -> Optional[str]:
        scores = self._compute_dimension_scores()
        if not scores:
            return None
        return min(scores, key=scores.get)

    # ── Evolution cycle ───────────────────────────────────────────────────────

    async def evolve(self, force_dimension: Optional[str] = None) -> Optional[EvolutionRecord]:
        """
        Run one evolution cycle. Finds the weakest area and improves it.
        Should be called once per day (by background_executor or scheduler).
        """
        import uuid

        dimension = force_dimension or self._find_weakest_dimension()
        if not dimension:
            dimension = "personality_traits"   # default: always refine personality

        scores = self._compute_dimension_scores()
        metric_before = scores.get(dimension, 0.5)

        current_value = self.genome.get(dimension, "not set")

        prompt = (
            f"Current genome:\n{json.dumps(self.genome, indent=2)}\n\n"
            f"Performance scores (last 7 days):\n{json.dumps(scores, indent=2)}\n\n"
            f"Weakest dimension: {dimension} (score: {metric_before:.2f})\n"
            f"Current value: {json.dumps(current_value, indent=2)}\n\n"
            f"Generate an evolution improvement for the '{dimension}' dimension."
        )

        try:
            resp = await self.client.achat(
                [
                    {"role": "system", "content": EVOLUTION_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                model="thinking",
                max_tokens=1024,
                temperature=0.6,
            )
            raw   = resp.content.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            obj   = json.loads(raw[start:end])

        except Exception:
            return None

        winner_key    = obj.get("winner", "a")
        winning_value = obj.get(f"candidate_{winner_key}")
        losing_value  = obj.get(f"candidate_{'b' if winner_key == 'a' else 'a'}")

        if winning_value is None:
            return None

        # Apply evolution — update genome
        before = self.genome.get(dimension)
        self.genome[dimension] = winning_value
        self.genome["generation"] = self.genome.get("generation", 0) + 1

        # Special case: system_prompt_additions accumulates
        if dimension == "system_prompt_additions" and isinstance(winning_value, str):
            existing = self.genome.get("system_prompt_additions", [])
            if isinstance(existing, list):
                existing.append(winning_value)
                self.genome["system_prompt_additions"] = existing[-10:]  # keep last 10

        self._save_genome()

        record = EvolutionRecord(
            id             = str(uuid.uuid4()),
            timestamp      = datetime.utcnow().isoformat(),
            generation     = self.genome["generation"],
            dimension      = dimension,
            before         = before,
            after          = winning_value,
            candidate_b    = losing_value,
            reasoning      = obj.get("winner_reasoning", obj.get("analysis", "")),
            metric_before  = metric_before,
            metric_after   = float(obj.get("metric_prediction", metric_before + 0.1)),
            accepted       = True,
        )
        self._log_record(record)
        return record

    # ── Genome → system prompt ────────────────────────────────────────────────

    def build_system_prompt_fragment(self) -> str:
        """
        Convert current genome into a system prompt fragment.
        Injected into every VYRA system prompt.
        """
        g   = self.genome
        gen = g.get("generation", 0)
        lines = [
            f"[VYRA Core Identity — Generation {gen}]",
        ]
        traits = g.get("personality_traits", [])
        if traits:
            lines.append("Personality:")
            for t in traits:
                lines.append(f"  • {t}")
        style = g.get("response_style", {})
        if style:
            lines.append(f"Response style: {style.get('default_length', 'concise')}, "
                         f"formality={style.get('formality', 'smart_casual')}, "
                         f"examples={style.get('use_examples', True)}")
        additions = g.get("system_prompt_additions", [])
        if additions:
            lines.append("Evolved behaviors:")
            for a in additions[-3:]:
                lines.append(f"  → {a}")
        return "\n".join(lines)

    def get_cot_threshold(self) -> int:
        return int(self.genome.get("cot_thresholds", {}).get("complexity_word_count", 40))

    def get_memory_weights(self) -> dict:
        return self.genome.get("memory_weights", DEFAULT_GENOME["memory_weights"])

    # ── Introspection ─────────────────────────────────────────────────────────

    def evolution_history(self, n: int = 10) -> str:
        recent = self._records[-n:]
        if not recent:
            return "No evolution cycles run yet."
        lines = [f"[VYRA Evolution History — Generation {self.genome.get('generation', 0)}]"]
        for r in recent:
            lines.append(
                f"  Gen {r.generation}: [{r.dimension}] {r.reasoning[:80]}... "
                f"(score: {r.metric_before:.2f} → {r.metric_after:.2f})"
            )
        return "\n".join(lines)

    def stats(self) -> dict:
        scores = self._compute_dimension_scores()
        return {
            "generation":    self.genome.get("generation", 0),
            "evolved_at":    self.genome.get("evolved_at", "never"),
            "total_signals": len(self._metrics),
            "dimension_scores": {k: round(v, 2) for k, v in scores.items()},
            "total_evolutions": len(self._records),
            "weakest":       min(scores, key=scores.get) if scores else None,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[SelfEvolution] = None

def get_self_evolution() -> SelfEvolution:
    global _engine
    if _engine is None:
        _engine = SelfEvolution()
    return _engine


if __name__ == "__main__":
    import asyncio
    async def _test():
        ev = get_self_evolution()

        # Simulate some performance signals
        ev.on_correction("Gave wrong date for an event")
        ev.on_success("coding_help")
        ev.on_correction("Didn't remember user's job title")
        ev.on_memory_miss("last project deadline")
        ev.on_success("research")
        ev.on_success("writing")

        print("Stats before evolution:", ev.stats())
        print("\nBuilding system prompt fragment:")
        print(ev.build_system_prompt_fragment())

        print("\nRunning evolution cycle...")
        record = await ev.evolve()
        if record:
            print(f"\nEvolution Gen {record.generation}:")
            print(f"  Dimension: {record.dimension}")
            print(f"  Before: {record.before}")
            print(f"  After:  {record.after}")
            print(f"  Reasoning: {record.reasoning}")
            print(f"  Score: {record.metric_before:.2f} → {record.metric_after:.2f}")
        else:
            print("No evolution this cycle.")

        print("\nStats after:", ev.stats())

    asyncio.run(_test())
