"""
VYRA Insight Engine
====================
The "aha moment" generator — where VYRA's original ideas come from.

Insight in humans emerges during non-directed replay:
  sleep, walks, showers — when you're NOT trying, connections form.
  Two previously unrelated memories suddenly reveal a deep structure.

The mechanism (Dijksterhuis & Meurs, 2006; Stickgold, 2005):
  1. Sample two apparently unrelated memory fragments
  2. Find latent structural mappings between them
  3. If the mapping has explanatory power → INSIGHT
  4. Store as a new, synthesized knowledge node

VYRA's insight engine runs during idle time:
  - Randomly samples from episodic memory, past thoughts, curiosity questions
  - Pairs them unexpectedly (high novelty = high potential)
  - Uses LLM to find the structural similarity / bridge concept
  - If coherence score > 0.65 → this is a genuine insight
  - Stores it + potentially shares with user next interaction

Examples of insights VYRA might generate:
  - "The way you approach debugging code is identical to how you approach relationship problems"
  - "Your startup's retention problem and your fitness routine problem have the same root cause"
  - "Three times this month you've asked about X — there's a pattern I should surface"

This is what makes VYRA feel genuinely INTELLIGENT — not just retrieving,
but making original connections no one explicitly taught her.
"""

import json
import random
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime
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

DATA_DIR      = Path(__file__).parent.parent / "data"
INSIGHTS_PATH = DATA_DIR / "insights.jsonl"


@dataclass
class Insight:
    id: str
    timestamp: str
    source_a: str            # first memory/concept
    source_b: str            # second memory/concept
    bridge: str              # the structural mapping found
    insight_text: str        # the actual insight (1-3 sentences)
    coherence: float         # 0.0–1.0 how strong/real this insight is
    novelty: float           # how unexpected the connection is
    actionable: bool         # does this suggest something to do?
    action_hint: str         # if actionable, what to do
    was_shared: bool = False
    domain: str = "general"  # what area of life this applies to


INSIGHT_SYSTEM = """You are VYRA's insight engine — her generator of original connections.
Given two seemingly unrelated concepts or memories, find the deep structural similarity between them.

Not a surface similarity. A STRUCTURAL one:
- Same underlying pattern in different domains
- One explains the other in a way neither could alone
- Together they reveal something neither shows alone

Output JSON:
{
  "bridge": "the structural concept that connects them (1 phrase)",
  "insight_text": "2-3 sentence insight that emerges from seeing them together",
  "coherence": 0.0-1.0,
  "novelty": 0.0-1.0,
  "actionable": true/false,
  "action_hint": "what this insight suggests doing (if actionable)",
  "domain": "what area of life/work this applies to"
}

If there is NO real structural connection, output: {"coherence": 0.1, "insight_text": "no genuine connection"}
Do not force connections. Only report genuine structural insight."""


class InsightEngine:

    COHERENCE_THRESHOLD = 0.65   # minimum coherence to store as real insight
    POOL_SIZE = 30                # how many memory fragments to pool for pairing

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = get_nvidia_client()
        self._insights: List[Insight] = self._load()
        self._unshared: List[Insight] = [i for i in self._insights
                                          if not i.was_shared and i.coherence >= self.COHERENCE_THRESHOLD]
        self._memory_pool: List[str] = []   # fed by other systems

    def _load(self) -> List[Insight]:
        insights = []
        if not INSIGHTS_PATH.exists():
            return []
        try:
            for line in INSIGHTS_PATH.read_text(encoding="utf-8").strip().split("\n"):
                if line.strip():
                    insights.append(Insight(**json.loads(line)))
        except Exception:
            pass
        return insights[-100:]  # keep last 100

    def _save(self, insight: Insight):
        self._insights.append(insight)
        try:
            with open(INSIGHTS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(insight)) + "\n")
        except Exception:
            pass

    def feed_memory(self, fragments: List[str]):
        """Add memory fragments to the pool for pairing. Called by episodic/world model."""
        self._memory_pool.extend(fragments)
        self._memory_pool = list(dict.fromkeys(self._memory_pool))[-self.POOL_SIZE:]

    async def generate_insight(self) -> Optional[Insight]:
        """
        Pick two random fragments from the pool and try to find an insight.
        Returns an Insight if coherence > threshold, else None.
        """
        import uuid
        pool = self._memory_pool
        if len(pool) < 2:
            # Use built-in seed fragments if pool is empty
            pool = [
                "debugging involves isolating variables one at a time",
                "relationship conflicts often stem from unspoken assumptions",
                "good design removes complexity before adding features",
                "trust is built through consistent small actions not grand gestures",
                "learning is fastest when you're slightly outside your comfort zone",
                "energy management matters more than time management",
                "the hardest problems are usually reframings of simpler ones",
                "most procrastination is fear of imperfection in disguise",
            ]

        source_a, source_b = random.sample(pool, 2)

        prompt = (
            f"Concept A: {source_a}\n"
            f"Concept B: {source_b}\n\n"
            f"Find the structural insight — if one exists."
        )

        try:
            resp = await self.client.achat(
                [{"role": "system", "content": INSIGHT_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="thinking", max_tokens=512, temperature=0.8,
            )
            raw = resp.content.strip()
            obj = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        except Exception:
            return None

        coherence = float(obj.get("coherence", 0.0))
        if coherence < self.COHERENCE_THRESHOLD:
            return None

        insight = Insight(
            id            = str(uuid.uuid4())[:8],
            timestamp     = datetime.utcnow().isoformat(),
            source_a      = source_a[:200],
            source_b      = source_b[:200],
            bridge        = obj.get("bridge", "structural similarity"),
            insight_text  = obj.get("insight_text", ""),
            coherence     = coherence,
            novelty       = float(obj.get("novelty", 0.5)),
            actionable    = bool(obj.get("actionable", False)),
            action_hint   = obj.get("action_hint", ""),
            domain        = obj.get("domain", "general"),
        )
        self._save(insight)
        if insight.coherence >= self.COHERENCE_THRESHOLD:
            self._unshared.append(insight)
        return insight

    async def run_session(self, n: int = 3) -> List[Insight]:
        """Generate up to N insights in one idle session."""
        results = []
        for _ in range(n):
            insight = await self.generate_insight()
            if insight:
                results.append(insight)
        return results

    def pop_best_insight(self) -> Optional[Insight]:
        """Return the highest-coherence unshared insight."""
        unshared = [i for i in self._unshared if not i.was_shared]
        if not unshared:
            return None
        best = max(unshared, key=lambda i: i.coherence * i.novelty)
        best.was_shared = True
        return best

    def has_insights(self) -> bool:
        return any(not i.was_shared for i in self._unshared)

    def insight_for_topic(self, topic: str) -> Optional[Insight]:
        """Find a stored insight relevant to a topic."""
        tl = topic.lower()
        for i in reversed(self._insights):
            if (tl in i.source_a.lower() or tl in i.source_b.lower()
                    or tl in i.domain.lower()):
                return i
        return None

    def to_system_fragment(self) -> str:
        recent = [i for i in self._insights[-5:] if i.coherence >= self.COHERENCE_THRESHOLD]
        if not recent:
            return ""
        lines = ["[VYRA's Recent Insights — original connections she's discovered]"]
        for i in recent[-3:]:
            lines.append(f"  [{i.domain}] {i.insight_text[:100]}")
        return "\n".join(lines)

    def stats(self) -> Dict[str, Any]:
        total = len(self._insights)
        strong = sum(1 for i in self._insights if i.coherence >= self.COHERENCE_THRESHOLD)
        return {"total_insights": total, "strong_insights": strong,
                "pool_size": len(self._memory_pool), "unshared": len(self._unshared)}


_ie: Optional[InsightEngine] = None
def get_insight_engine() -> InsightEngine:
    global _ie
    if _ie is None:
        _ie = InsightEngine()
    return _ie
