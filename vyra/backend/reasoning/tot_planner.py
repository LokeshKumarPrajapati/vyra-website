"""
Tree-of-Thought (ToT) Planner — Phase 1.2
==========================================
For complex multi-step tasks that need planning before execution.

Process:
  1. Generate N candidate approaches (branches)
  2. Score each branch on feasibility, risk, speed, quality
  3. Select best branch
  4. Decompose into ordered, executable steps
  5. Assign each step to the correct VYRA agent/tool

Triggered when: task requires >3 tool calls, spans >1 session, or involves
irreversible actions (write_file, send_email, purchase, etc.)

Usage:
    planner = TreeOfThoughtPlanner()
    plan = await planner.plan("Build a landing page for my app and deploy it")
    for step in plan.steps:
        print(step.agent, step.instruction)
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ExecutionStep:
    index: int
    instruction: str
    agent: str           # which VYRA agent handles this
    tool: str            # which specific tool/function
    reversible: bool     # can this step be undone?
    requires_approval: bool = False   # needs user confirm before running
    estimated_seconds: int = 10
    depends_on: List[int] = field(default_factory=list)  # step indices

@dataclass
class PlanBranch:
    approach: str        # high-level strategy description
    feasibility: float   # 0.0-1.0
    risk: float          # 0.0-1.0 (lower is better)
    speed: float         # 0.0-1.0 (higher = faster)
    quality: float       # 0.0-1.0 (higher = better outcome)
    score: float = 0.0   # computed from above

    def compute_score(self):
        self.score = (
            self.feasibility * 0.35
            + (1 - self.risk) * 0.25
            + self.quality * 0.25
            + self.speed * 0.15
        )
        return self.score

@dataclass
class ExecutionPlan:
    goal: str
    chosen_approach: str
    approach_score: float
    steps: List[ExecutionStep]
    estimated_total_seconds: int
    requires_approval_before_start: bool
    alternative_approaches: List[str]
    latency_ms: float


# ── Agent catalogue (matches VYRA's existing agents) ─────────────────────────

AGENT_CATALOGUE = {
    "web_agent":     "Browse, search, fill forms, navigate websites",
    "cad_agent":     "3D CAD model generation from natural language",
    "printer_agent": "3D print slicing and job submission",
    "kasa_agent":    "Smart home device control (lights, plugs)",
    "spotify_agent": "Music playback and mood matching",
    "code_agent":    "Write, run and debug Python/JS code",
    "research_agent":"Deep multi-source research and synthesis",
    "data_agent":    "Data analysis, charts, statistics",
    "comms_agent":   "Email, messaging, calendar management",
    "win_system":    "Windows OS control (files, processes, registry)",
    "vyra_core":     "Direct VYRA response — no tool needed",
}

IRREVERSIBLE_TOOLS = {
    "write_file", "delete_file", "send_email", "send_message",
    "submit_form", "purchase", "deploy", "run_code", "modify_registry",
    "win_registry", "win_firewall", "win_defender",
}


# ── Planner ───────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are VYRA's strategic planning engine.
Given a goal, generate executable plans that leverage VYRA's capabilities.
Be practical, specific, and risk-aware. Prefer reversible actions.
Output valid JSON only when asked."""

class TreeOfThoughtPlanner:

    def __init__(self, n_branches: int = 3):
        self.client = get_nvidia_client()
        self.n_branches = n_branches

    async def plan(
        self,
        goal: str,
        context: str = "",
        user_constraints: List[str] = None,
    ) -> ExecutionPlan:
        t0 = time.time()
        constraints = user_constraints or []

        # 1. Generate candidate approaches
        branches = await self._generate_branches(goal, context, constraints)

        # 2. Score branches
        scored = await self._score_branches(branches, goal)

        # 3. Pick best
        best = max(scored, key=lambda b: b.score)

        # 4. Decompose to steps
        steps = await self._decompose_to_steps(goal, best.approach, context)

        # 5. Flag approvals
        for step in steps:
            if not step.reversible or step.tool in IRREVERSIBLE_TOOLS:
                step.requires_approval = True

        plan = ExecutionPlan(
            goal                          = goal,
            chosen_approach               = best.approach,
            approach_score                = best.score,
            steps                         = steps,
            estimated_total_seconds       = sum(s.estimated_seconds for s in steps),
            requires_approval_before_start= any(s.requires_approval for s in steps),
            alternative_approaches        = [b.approach for b in scored if b is not best],
            latency_ms                    = (time.time() - t0) * 1000,
        )
        return plan

    # ── Branch generation ─────────────────────────────────────────────────────

    async def _generate_branches(
        self, goal: str, context: str, constraints: List[str]
    ) -> List[PlanBranch]:
        constraint_str = "\n".join(f"- {c}" for c in constraints) if constraints else "None"
        prompt = (
            f"Goal: {goal}\n"
            f"Context: {context or 'none'}\n"
            f"Constraints: {constraint_str}\n\n"
            f"Available VYRA agents:\n"
            + "\n".join(f"  {k}: {v}" for k, v in AGENT_CATALOGUE.items()) +
            f"\n\nGenerate exactly {self.n_branches} distinct strategic approaches to achieve this goal.\n"
            f"For each, provide feasibility (0-1), risk (0-1, lower=safer), speed (0-1), quality (0-1).\n"
            f"Respond with JSON array:\n"
            f'[{{"approach":"...", "feasibility":0.9, "risk":0.2, "speed":0.7, "quality":0.85}}, ...]'
        )
        resp = await self.client.achat(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user",   "content": prompt}],
            model="fast",
            max_tokens=1024,
            temperature=0.7,
        )
        try:
            raw   = resp.content.strip()
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            items = json.loads(raw[start:end])
            branches = []
            for item in items[:self.n_branches]:
                b = PlanBranch(
                    approach    = item.get("approach", ""),
                    feasibility = float(item.get("feasibility", 0.7)),
                    risk        = float(item.get("risk", 0.5)),
                    speed       = float(item.get("speed", 0.5)),
                    quality     = float(item.get("quality", 0.7)),
                )
                branches.append(b)
            return branches
        except Exception:
            return [PlanBranch(approach=goal, feasibility=0.8, risk=0.3, speed=0.5, quality=0.8)]

    # ── Branch scoring ────────────────────────────────────────────────────────

    async def _score_branches(self, branches: List[PlanBranch], goal: str) -> List[PlanBranch]:
        for b in branches:
            b.compute_score()
        return sorted(branches, key=lambda b: b.score, reverse=True)

    # ── Step decomposition ────────────────────────────────────────────────────

    async def _decompose_to_steps(
        self, goal: str, approach: str, context: str
    ) -> List[ExecutionStep]:
        agent_list = "\n".join(f"  {k}" for k in AGENT_CATALOGUE)
        prompt = (
            f"Goal: {goal}\n"
            f"Chosen approach: {approach}\n"
            f"Context: {context or 'none'}\n\n"
            f"Available agents: {agent_list}\n\n"
            f"Decompose the approach into 3-8 ordered execution steps.\n"
            f"For each step specify:\n"
            f"  - instruction: what to do (clear, actionable)\n"
            f"  - agent: which agent does it (from list above)\n"
            f"  - tool: specific function/tool name\n"
            f"  - reversible: true/false\n"
            f"  - estimated_seconds: rough estimate\n"
            f"  - depends_on: list of step indices (0-based) this step needs first\n\n"
            f"Respond with JSON array of steps."
        )
        resp = await self.client.athink(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=4096,
        )
        answer = resp.answer
        try:
            start = answer.find("[")
            end   = answer.rfind("]") + 1
            items = json.loads(answer[start:end])
            steps = []
            for i, item in enumerate(items):
                s = ExecutionStep(
                    index              = i,
                    instruction        = item.get("instruction", ""),
                    agent              = item.get("agent", "vyra_core"),
                    tool               = item.get("tool", ""),
                    reversible         = bool(item.get("reversible", True)),
                    estimated_seconds  = int(item.get("estimated_seconds", 10)),
                    depends_on         = [int(d) for d in item.get("depends_on", [])],
                )
                steps.append(s)
            return steps
        except Exception:
            return [ExecutionStep(
                index=0, instruction=approach, agent="vyra_core",
                tool="direct_response", reversible=True,
            )]


# ── Singleton ─────────────────────────────────────────────────────────────────

_planner: Optional[TreeOfThoughtPlanner] = None

def get_tot_planner() -> TreeOfThoughtPlanner:
    global _planner
    if _planner is None:
        _planner = TreeOfThoughtPlanner()
    return _planner


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def _test():
        planner = get_tot_planner()
        plan    = await planner.plan(
            goal    = "Research the top 5 AI startups of 2025, create a comparison report, and save it as a PDF",
            context = "User is an investor interested in AI infrastructure companies",
        )
        print(f"\nGoal: {plan.goal}")
        print(f"Approach: {plan.chosen_approach}")
        print(f"Score: {plan.approach_score:.2f}  |  ETA: {plan.estimated_total_seconds}s")
        print(f"Needs approval: {plan.requires_approval_before_start}")
        print(f"\nSteps:")
        for s in plan.steps:
            print(f"  {s.index}. [{s.agent}] {s.instruction}  (reversible={s.reversible})")
        print(f"\nAlternatives considered:")
        for alt in plan.alternative_approaches:
            print(f"  - {alt}")

    asyncio.run(_test())
