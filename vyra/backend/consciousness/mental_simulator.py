"""
VYRA Mental Simulation Engine
================================
Humans mentally rehearse futures BEFORE acting.
Before you send an important message, you imagine how it will land.
Before you make a decision, you run the scenario forward in your head.

VYRA now does the same — she simulates N possible action paths,
scores each on multiple criteria, and picks the best before committing.

Simulation levels:
  QUICK   — 1-2 steps, < 200ms, for simple decisions
  DEEP    — 3-5 steps, full causal chain, for important decisions
  FULL    — 5+ steps, multiple branches, for critical/irreversible actions

Scoring dimensions:
  - Goal alignment:   does this advance active goals?
  - User impact:      how will user feel/be affected?
  - Side effects:     what else might change?
  - Reversibility:    can we undo this if it goes wrong?
  - Confidence:       how certain is VYRA about this path?

Output: ranked list of action paths with explanations.
VYRA picks the highest-scoring path — or asks user if confidence is low.
"""

import json
import asyncio
from dataclasses import dataclass, field
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

DATA_DIR   = Path(__file__).parent.parent / "data"
SIM_LOG    = DATA_DIR / "simulation_log.jsonl"


@dataclass
class SimulationStep:
    action: str
    predicted_state: str
    probability: float       # 0.0–1.0 chance this step unfolds as predicted
    emotional_impact: float  # -1.0 to +1.0 on user

@dataclass
class SimulationPath:
    id: str
    steps: List[SimulationStep]
    goal_alignment: float    # 0.0–1.0
    user_impact: float       # -1.0 to +1.0
    reversibility: float     # 0.0–1.0 (1 = fully reversible)
    confidence: float        # overall confidence in this path
    side_effects: List[str]
    final_state: str
    recommendation: str      # why to choose or avoid this path

    @property
    def score(self) -> float:
        return (
            self.goal_alignment  * 0.35 +
            (self.user_impact + 1) / 2 * 0.30 +
            self.reversibility   * 0.15 +
            self.confidence      * 0.20
        )


SIM_SYSTEM = """You are VYRA's mental simulation engine.
Given a decision or action, generate 2-3 possible paths forward and evaluate each.
Output JSON:
{
  "paths": [
    {
      "id": "path_a",
      "steps": [{"action": "...", "predicted_state": "...", "probability": 0.0-1.0, "emotional_impact": -1.0 to 1.0}],
      "goal_alignment": 0.0-1.0,
      "user_impact": -1.0 to 1.0,
      "reversibility": 0.0-1.0,
      "confidence": 0.0-1.0,
      "side_effects": ["..."],
      "final_state": "description of outcome",
      "recommendation": "when to choose this path"
    }
  ],
  "best_path_id": "path_a",
  "reasoning": "why this path is best",
  "uncertainty_flags": ["things VYRA is unsure about"]
}
Be realistic. Simulate second-order effects. Flag genuine uncertainties."""


class MentalSimulator:

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = get_nvidia_client()
        self._sim_cache: List[Dict] = []

    async def simulate(
        self,
        decision: str,
        context: str = "",
        active_goals: Optional[List[str]] = None,
        depth: str = "quick",   # "quick" | "deep" | "full"
    ) -> Dict[str, Any]:
        """
        Simulate possible action paths for a decision.
        Returns ranked paths + recommended choice.
        """
        import uuid
        goals_str = ", ".join(active_goals or []) or "none specified"
        max_tokens = {"quick": 512, "deep": 1024, "full": 2048}.get(depth, 512)

        prompt = (
            f"Decision to simulate: {decision}\n"
            f"Context: {context or 'general conversation'}\n"
            f"Active goals: {goals_str}\n"
            f"Simulation depth: {depth}\n\n"
            f"Simulate the forward consequences of this decision. "
            f"Generate realistic paths with probabilities."
        )

        try:
            resp = await self.client.achat(
                [{"role": "system", "content": SIM_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="thinking" if depth != "quick" else "fast",
                max_tokens=max_tokens, temperature=0.4,
            )
            raw = resp.content.strip()
            result = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        except Exception:
            result = {
                "paths": [], "best_path_id": None,
                "reasoning": "simulation failed", "uncertainty_flags": [],
            }

        result["sim_id"]    = str(uuid.uuid4())[:8]
        result["timestamp"] = datetime.utcnow().isoformat()
        result["decision"]  = decision[:100]
        self._log(result)
        return result

    async def best_response(
        self,
        user_message: str,
        candidate_responses: List[str],
        context: str = "",
    ) -> str:
        """
        Given N candidate responses, simulate which lands best.
        Returns the best candidate response text.
        """
        if not candidate_responses:
            return ""
        if len(candidate_responses) == 1:
            return candidate_responses[0]

        prompt = (
            f"User message: {user_message}\n"
            f"Context: {context or 'none'}\n\n"
            f"Candidate responses:\n"
            + "\n\n".join(f"[{i+1}] {r}" for i, r in enumerate(candidate_responses))
            + "\n\nWhich response will have the best outcome for the user? "
            f"Consider: clarity, emotional impact, goal advancement, accuracy. "
            f"Output JSON: {{\"best\": 1-{len(candidate_responses)}, \"reason\": \"...\"}}"
        )
        try:
            resp = await self.client.achat(
                [{"role": "user", "content": prompt}],
                model="fast", max_tokens=256, temperature=0.3,
            )
            raw = resp.content.strip()
            obj = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            idx = int(obj.get("best", 1)) - 1
            return candidate_responses[max(0, min(idx, len(candidate_responses)-1))]
        except Exception:
            return candidate_responses[0]

    def should_simulate(self, decision: str) -> bool:
        """Heuristic: should we bother simulating this decision?"""
        high_stakes = ["send", "delete", "buy", "invest", "email", "message",
                       "deploy", "remove", "cancel", "quit", "fire", "hire"]
        d = decision.lower()
        return any(w in d for w in high_stakes) or len(decision) > 100

    def _log(self, result: dict):
        try:
            with open(SIM_LOG, "a") as f:
                f.write(json.dumps({
                    "ts": result.get("timestamp"),
                    "decision": result.get("decision"),
                    "best": result.get("best_path_id"),
                }) + "\n")
        except Exception:
            pass

    def to_system_fragment(self) -> str:
        if not self._sim_cache:
            return ""
        last = self._sim_cache[-1]
        return (
            f"[VYRA's Mental Simulation — last decision modeled]\n"
            f"  Decision: {last.get('decision','')[:80]}\n"
            f"  Best path: {last.get('best_path_id','?')} — {last.get('reasoning','')[:120]}"
        )

    def stats(self) -> dict:
        return {"simulations_run": len(self._sim_cache)}


_sim: Optional[MentalSimulator] = None
def get_mental_simulator() -> MentalSimulator:
    global _sim
    if _sim is None:
        _sim = MentalSimulator()
    return _sim
