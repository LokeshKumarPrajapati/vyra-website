"""
VYRA Skill Memory (Procedural Memory)
========================================
Humans get better at tasks through practice.
The first time you parallel-park, you think consciously about every step.
After 100 times, it's automatic — you barely think about it.

VYRA now accumulates procedural knowledge the same way:
  - Every time she completes a task type, she stores the successful sequence
  - Success rates and latency are tracked per skill
  - Over time, high-frequency skills become "fluent" — faster, more accurate
  - Failed procedures are analyzed for what went wrong → improved next run
  - Skills below 40% success rate are flagged for relearning

Skill taxonomy:
  code_debugging, code_generation, research_synthesis, explanation,
  emotional_support, planning, creative_writing, data_analysis,
  system_control, scheduling, memory_recall, reasoning_chain, ...

This is what makes VYRA GET BETTER at the things she does repeatedly —
not through retraining, but through accumulated procedural knowledge.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR    = Path(__file__).parent.parent / "data"
SKILL_PATH  = DATA_DIR / "skill_memory.json"


@dataclass
class SkillExecution:
    timestamp: str
    steps: List[str]         # what VYRA actually did
    duration_ms: float
    succeeded: bool
    user_satisfied: bool     # inferred from correction signals
    notes: str               # what went well / what failed


@dataclass
class Skill:
    name: str                # e.g. "code_debugging"
    description: str
    category: str            # "cognitive" | "creative" | "technical" | "social"
    executions: List[SkillExecution] = field(default_factory=list)
    best_procedure: List[str] = field(default_factory=list)   # distilled best steps
    total_runs: int    = 0
    successes: int     = 0
    fluency: float     = 0.0   # 0.0 (novice) → 1.0 (automatic)
    avg_duration_ms: float = 0.0
    last_used: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    needs_relearning: bool = False

    @property
    def success_rate(self) -> float:
        return self.successes / self.total_runs if self.total_runs > 0 else 0.0

    def practice(self, execution: SkillExecution):
        """Record a skill execution and update fluency."""
        self.executions.append(execution)
        self.executions = self.executions[-50:]  # keep last 50
        self.total_runs += 1
        if execution.succeeded and execution.user_satisfied:
            self.successes += 1
        self.last_used = execution.timestamp
        self.avg_duration_ms = (
            (self.avg_duration_ms * (self.total_runs - 1) + execution.duration_ms)
            / self.total_runs
        )
        # Fluency grows with successes, decays with failures
        # Like a forgetting curve in reverse
        if execution.succeeded:
            self.fluency = min(1.0, self.fluency + 0.05 * (1.0 - self.fluency))
        else:
            self.fluency = max(0.0, self.fluency - 0.08)

        # Update best procedure from successful runs
        if execution.succeeded and execution.steps:
            self.best_procedure = execution.steps

        # Flag for relearning if success rate drops
        if self.total_runs >= 5 and self.success_rate < 0.4:
            self.needs_relearning = True

    def fluency_label(self) -> str:
        if self.fluency < 0.2: return "novice"
        if self.fluency < 0.5: return "developing"
        if self.fluency < 0.75: return "proficient"
        if self.fluency < 0.9: return "advanced"
        return "fluent"


# ── Predefined skill templates ─────────────────────────────────────────────────

DEFAULT_SKILLS: List[Dict] = [
    {"name": "code_debugging",    "description": "Find and fix bugs in code", "category": "technical"},
    {"name": "code_generation",   "description": "Write working code from requirements", "category": "technical"},
    {"name": "research_synthesis","description": "Find, verify, and synthesize information", "category": "cognitive"},
    {"name": "explanation",       "description": "Explain complex topics clearly", "category": "cognitive"},
    {"name": "planning",          "description": "Break goals into actionable steps", "category": "cognitive"},
    {"name": "emotional_support", "description": "Respond to emotional states effectively", "category": "social"},
    {"name": "creative_writing",  "description": "Generate creative text content", "category": "creative"},
    {"name": "data_analysis",     "description": "Analyze data and find patterns", "category": "technical"},
    {"name": "memory_recall",     "description": "Retrieve relevant past information", "category": "cognitive"},
    {"name": "scheduling",        "description": "Manage time and calendar tasks", "category": "technical"},
    {"name": "reasoning_chain",   "description": "Multi-step logical reasoning", "category": "cognitive"},
    {"name": "creative_problem",  "description": "Novel solutions to unusual problems", "category": "creative"},
]


class SkillMemory:
    """
    VYRA's procedural memory — skills she's accumulated through practice.
    The more she does something, the better and faster she gets.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._skills: Dict[str, Skill] = self._load()

    def _load(self) -> Dict[str, Skill]:
        try:
            raw = json.loads(SKILL_PATH.read_text())
            skills = {}
            for name, data in raw.items():
                execs = [SkillExecution(**e) for e in data.pop("executions", [])]
                s = Skill(**data)
                s.executions = execs
                skills[name] = s
            return skills
        except Exception:
            skills = {}
            for sd in DEFAULT_SKILLS:
                skills[sd["name"]] = Skill(**sd)
            return skills

    def _save(self):
        try:
            out = {}
            for name, skill in self._skills.items():
                d = asdict(skill)
                out[name] = d
            SKILL_PATH.write_text(json.dumps(out, indent=2))
        except Exception:
            pass

    def get_skill(self, name: str) -> Skill:
        if name not in self._skills:
            self._skills[name] = Skill(
                name=name,
                description=f"Skill: {name.replace('_',' ')}",
                category="cognitive",
            )
        return self._skills[name]

    def record_execution(
        self,
        skill_name: str,
        steps: List[str],
        duration_ms: float,
        succeeded: bool,
        user_satisfied: bool = True,
        notes: str = "",
    ):
        """Record that VYRA just performed a skill. Updates fluency."""
        skill = self.get_skill(skill_name)
        exec_ = SkillExecution(
            timestamp=datetime.utcnow().isoformat(),
            steps=steps, duration_ms=duration_ms,
            succeeded=succeeded, user_satisfied=user_satisfied, notes=notes,
        )
        skill.practice(exec_)
        self._save()

    def get_procedure(self, skill_name: str) -> List[str]:
        """Get VYRA's best known procedure for a skill (empty if novice)."""
        skill = self._skills.get(skill_name)
        return skill.best_procedure if skill else []

    def fluent_skills(self, threshold: float = 0.75) -> List[Skill]:
        return [s for s in self._skills.values() if s.fluency >= threshold]

    def skills_needing_work(self) -> List[Skill]:
        return [s for s in self._skills.values() if s.needs_relearning or
                (s.total_runs >= 3 and s.success_rate < 0.5)]

    def classify_task(self, task_text: str) -> str:
        """Heuristic: map a task description to a skill name."""
        t = task_text.lower()
        if any(w in t for w in ["bug", "error", "fix", "debug", "traceback"]): return "code_debugging"
        if any(w in t for w in ["write", "create", "generate", "code", "function", "class"]): return "code_generation"
        if any(w in t for w in ["research", "find", "search", "look up", "what is"]): return "research_synthesis"
        if any(w in t for w in ["explain", "understand", "how does", "why"]): return "explanation"
        if any(w in t for w in ["plan", "schedule", "steps", "roadmap", "todo"]): return "planning"
        if any(w in t for w in ["feel", "sad", "stressed", "worried", "anxious", "happy"]): return "emotional_support"
        if any(w in t for w in ["write a story", "poem", "creative", "imagine"]): return "creative_writing"
        if any(w in t for w in ["data", "analyze", "chart", "graph", "csv", "statistics"]): return "data_analysis"
        return "reasoning_chain"

    def to_system_fragment(self) -> str:
        fluent = self.fluent_skills(0.7)
        weak   = self.skills_needing_work()
        lines  = ["[VYRA's Skill Fluency — procedural knowledge accumulated through practice]"]
        if fluent:
            lines.append(f"  Fluent at: {', '.join(s.name for s in fluent[:5])}")
        if weak:
            lines.append(f"  Still developing: {', '.join(s.name for s in weak[:3])}")
        all_skills = sorted(self._skills.values(), key=lambda s: -s.fluency)[:5]
        for s in all_skills:
            lines.append(f"  {s.name}: {s.fluency_label()} ({s.success_rate*100:.0f}% success, {s.total_runs} runs)")
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        return {
            name: {
                "fluency": round(s.fluency, 2),
                "level": s.fluency_label(),
                "success_rate": round(s.success_rate, 2),
                "total_runs": s.total_runs,
            }
            for name, s in self._skills.items()
        }


_sm: Optional[SkillMemory] = None
def get_skill_memory() -> SkillMemory:
    global _sm
    if _sm is None:
        _sm = SkillMemory()
    return _sm
