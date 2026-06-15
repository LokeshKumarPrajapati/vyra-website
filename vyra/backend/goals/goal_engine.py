"""
Goal Engine — Phase 2.1
========================
OKR-based autonomous goal management for VYRA.

Goals are captured from natural language ("I want to...", "Help me build..."),
decomposed into Key Results + sub-tasks, persisted to SQLite, and tracked
across sessions. The BackgroundExecutor drives execution between conversations.

Schema:
  Goal → many KeyResult → many Task
  Each Task maps to a VYRA agent + tool call

Usage:
    engine = get_goal_engine()
    goal   = await engine.create_from_text("Build a personal finance tracker app")
    engine.list_active()       # see what's in progress
    engine.update_progress(goal.id, task_id, done=True)
"""

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
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

# ── Enums ─────────────────────────────────────────────────────────────────────

class GoalStatus(str, Enum):
    ACTIVE    = "active"
    PAUSED    = "paused"
    BLOCKED   = "blocked"
    DONE      = "done"
    CANCELLED = "cancelled"

class TaskStatus(str, Enum):
    PENDING    = "pending"
    IN_PROGRESS= "in_progress"
    DONE       = "done"
    FAILED     = "failed"
    SKIPPED    = "skipped"

# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Task:
    id: str
    goal_id: str
    key_result_id: str
    instruction: str
    agent: str
    tool: str
    status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    created_at: str = ""
    completed_at: str = ""
    reversible: bool = True
    requires_approval: bool = False
    estimated_seconds: int = 30

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()

@dataclass
class KeyResult:
    id: str
    goal_id: str
    description: str
    metric: str              # e.g. "5 research papers summarised"
    target_value: float = 1.0
    current_value: float = 0.0
    tasks: List[Task] = field(default_factory=list)

    @property
    def progress(self) -> float:
        if self.target_value == 0:
            return 1.0
        return min(self.current_value / self.target_value, 1.0)

@dataclass
class Goal:
    id: str
    title: str
    description: str
    objective: str
    status: GoalStatus = GoalStatus.ACTIVE
    priority: int = 5           # 1=highest, 10=lowest
    deadline: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    key_results: List[KeyResult] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        now = datetime.utcnow().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def progress(self) -> float:
        if not self.key_results:
            return 0.0
        return sum(kr.progress for kr in self.key_results) / len(self.key_results)

    @property
    def next_task(self) -> Optional[Task]:
        for kr in self.key_results:
            for t in kr.tasks:
                if t.status == TaskStatus.PENDING:
                    return t
        return None

    def to_summary(self) -> str:
        pct = int(self.progress * 100)
        done = sum(
            1 for kr in self.key_results
            for t in kr.tasks if t.status == TaskStatus.DONE
        )
        total = sum(len(kr.tasks) for kr in self.key_results)
        return (
            f"[{self.status.value.upper()}] {self.title} — {pct}% complete "
            f"({done}/{total} tasks done)"
        )


# ── Goal Engine ───────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data"

SYSTEM_PROMPT = """You are VYRA's goal planning specialist.
Break user goals into measurable Key Results and executable tasks.
Map each task to a specific VYRA agent. Be realistic and specific.
Output valid JSON only."""

AVAILABLE_AGENTS = [
    "web_agent", "cad_agent", "printer_agent", "kasa_agent",
    "spotify_agent", "code_agent", "research_agent",
    "data_agent", "comms_agent", "win_system", "vyra_core",
]

class GoalEngine:

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path  = data_dir / "goals.db"
        self.client   = get_nvidia_client()
        self._goals: Dict[str, Goal] = {}
        self._init_db()
        self._load_all()

    # ── DB setup ──────────────────────────────────────────────────────────────

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER DEFAULT 5,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                goal_id TEXT,
                data TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT,
                completed_at TEXT,
                FOREIGN KEY(goal_id) REFERENCES goals(id)
            );
        """)
        con.commit()
        con.close()

    def _save_goal(self, goal: Goal):
        con = sqlite3.connect(self.db_path)
        data = json.dumps({
            "title": goal.title,
            "description": goal.description,
            "objective": goal.objective,
            "deadline": goal.deadline,
            "tags": goal.tags,
            "notes": goal.notes,
            "priority": goal.priority,
            "key_results": [
                {
                    "id": kr.id,
                    "description": kr.description,
                    "metric": kr.metric,
                    "target_value": kr.target_value,
                    "current_value": kr.current_value,
                    "tasks": [asdict(t) for t in kr.tasks],
                }
                for kr in goal.key_results
            ],
        })
        con.execute("""
            INSERT OR REPLACE INTO goals (id, data, status, priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (goal.id, data, goal.status.value, goal.priority, goal.created_at, goal.updated_at))
        con.commit()
        con.close()
        self._goals[goal.id] = goal

    def _load_all(self):
        con = sqlite3.connect(self.db_path)
        rows = con.execute("SELECT id, data, status, created_at, updated_at FROM goals").fetchall()
        con.close()
        for row in rows:
            gid, raw, status, created_at, updated_at = row
            try:
                d = json.loads(raw)
                krs = []
                for kr_d in d.get("key_results", []):
                    tasks = [Task(**t) for t in kr_d.get("tasks", [])]
                    kr = KeyResult(
                        id=kr_d["id"], goal_id=gid,
                        description=kr_d["description"],
                        metric=kr_d.get("metric", ""),
                        target_value=kr_d.get("target_value", 1.0),
                        current_value=kr_d.get("current_value", 0.0),
                        tasks=tasks,
                    )
                    krs.append(kr)
                goal = Goal(
                    id=gid,
                    title=d["title"],
                    description=d.get("description", ""),
                    objective=d.get("objective", ""),
                    status=GoalStatus(status),
                    priority=d.get("priority", 5),
                    deadline=d.get("deadline"),
                    created_at=created_at,
                    updated_at=updated_at,
                    key_results=krs,
                    tags=d.get("tags", []),
                    notes=d.get("notes", ""),
                )
                self._goals[gid] = goal
            except Exception as e:
                print(f"[GoalEngine] Failed to load goal {gid}: {e}")

    # ── Public API ────────────────────────────────────────────────────────────

    async def create_from_text(
        self,
        user_text: str,
        context: str = "",
        deadline_days: Optional[int] = None,
    ) -> Goal:
        """Parse natural language and create a structured Goal with KRs + Tasks."""
        prompt = self._build_decompose_prompt(user_text, context, deadline_days)
        resp   = await self.client.athink(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            max_tokens=8192,
        )
        goal = self._parse_goal_json(resp.answer, user_text, deadline_days)
        self._save_goal(goal)
        print(f"[GoalEngine] Created goal: {goal.title} ({len(goal.key_results)} KRs)")
        return goal

    def list_active(self) -> List[Goal]:
        return [g for g in self._goals.values() if g.status == GoalStatus.ACTIVE]

    def list_all(self) -> List[Goal]:
        return list(self._goals.values())

    def get(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    def update_task_status(
        self,
        goal_id: str,
        task_id: str,
        status: TaskStatus,
        result: str = "",
    ) -> bool:
        goal = self._goals.get(goal_id)
        if not goal:
            return False
        for kr in goal.key_results:
            for t in kr.tasks:
                if t.id == task_id:
                    t.status = status
                    t.result = result
                    if status == TaskStatus.DONE:
                        t.completed_at = datetime.utcnow().isoformat()
                        kr.current_value += 1
                    goal.updated_at = datetime.utcnow().isoformat()
                    # Mark goal done if all tasks complete
                    all_done = all(
                        tsk.status in (TaskStatus.DONE, TaskStatus.SKIPPED)
                        for kr2 in goal.key_results
                        for tsk in kr2.tasks
                    )
                    if all_done:
                        goal.status = GoalStatus.DONE
                    self._save_goal(goal)
                    return True
        return False

    def pause(self, goal_id: str):
        if goal_id in self._goals:
            self._goals[goal_id].status = GoalStatus.PAUSED
            self._save_goal(self._goals[goal_id])

    def resume(self, goal_id: str):
        if goal_id in self._goals:
            self._goals[goal_id].status = GoalStatus.ACTIVE
            self._save_goal(self._goals[goal_id])

    def cancel(self, goal_id: str):
        if goal_id in self._goals:
            self._goals[goal_id].status = GoalStatus.CANCELLED
            self._save_goal(self._goals[goal_id])

    def active_summary(self) -> str:
        active = self.list_active()
        if not active:
            return "No active goals."
        lines = [f"You have {len(active)} active goal(s):"]
        for g in active[:5]:
            lines.append(f"  • {g.to_summary()}")
        return "\n".join(lines)

    # ── Prompt builder ────────────────────────────────────────────────────────

    def _build_decompose_prompt(
        self, text: str, context: str, deadline_days: Optional[int]
    ) -> str:
        deadline_str = f"in {deadline_days} days" if deadline_days else "no strict deadline"
        agents_str   = ", ".join(AVAILABLE_AGENTS)
        return f"""
User wants to: {text}

User context: {context or 'not provided'}
Deadline: {deadline_str}
Available VYRA agents: {agents_str}

Create a structured Goal with:
- title: short, clear goal name
- description: 1-2 sentences about what success looks like
- objective: the single most important outcome
- tags: list of topic tags
- key_results: 2-4 measurable outcomes (OKRs), each with:
    - description: what this result means
    - metric: how we measure it (e.g. "3 reports generated")
    - target_value: number (e.g. 3)
    - tasks: 2-5 executable steps, each with:
        - instruction: clear action in imperative form
        - agent: which VYRA agent handles this
        - tool: specific function name
        - reversible: true/false
        - requires_approval: true/false
        - estimated_seconds: rough estimate

Output ONLY valid JSON matching this schema. No extra text.
JSON:
"""

    def _parse_goal_json(
        self, raw: str, original_text: str, deadline_days: Optional[int]
    ) -> Goal:
        try:
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            d     = json.loads(raw[start:end])
        except Exception:
            d = {"title": original_text[:60], "description": original_text,
                 "objective": original_text, "key_results": [], "tags": []}

        gid  = str(uuid.uuid4())
        deadline = (
            (datetime.utcnow() + timedelta(days=deadline_days)).isoformat()
            if deadline_days else None
        )
        krs = []
        for kr_d in d.get("key_results", []):
            kr_id = str(uuid.uuid4())
            tasks = []
            for t_d in kr_d.get("tasks", []):
                tasks.append(Task(
                    id               = str(uuid.uuid4()),
                    goal_id          = gid,
                    key_result_id    = kr_id,
                    instruction      = t_d.get("instruction", ""),
                    agent            = t_d.get("agent", "vyra_core"),
                    tool             = t_d.get("tool", ""),
                    reversible       = bool(t_d.get("reversible", True)),
                    requires_approval= bool(t_d.get("requires_approval", False)),
                    estimated_seconds= int(t_d.get("estimated_seconds", 30)),
                ))
            krs.append(KeyResult(
                id=kr_id, goal_id=gid,
                description=kr_d.get("description", ""),
                metric=kr_d.get("metric", ""),
                target_value=float(kr_d.get("target_value", len(tasks))),
                tasks=tasks,
            ))

        return Goal(
            id=gid,
            title=d.get("title", original_text[:60]),
            description=d.get("description", ""),
            objective=d.get("objective", ""),
            deadline=deadline,
            key_results=krs,
            tags=d.get("tags", []),
        )


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[GoalEngine] = None

def get_goal_engine() -> GoalEngine:
    global _engine
    if _engine is None:
        _engine = GoalEngine()
    return _engine


if __name__ == "__main__":
    async def _test():
        engine = get_goal_engine()
        goal   = await engine.create_from_text(
            "Research the top 5 open-source LLM frameworks, compare them, and write a summary report"
        )
        print(f"\nCreated: {goal.title}")
        print(f"Progress: {int(goal.progress*100)}%")
        for kr in goal.key_results:
            print(f"\n  KR: {kr.description}")
            for t in kr.tasks:
                print(f"    [{t.agent}] {t.instruction}")
        print(f"\nSummary: {engine.active_summary()}")

    asyncio.run(_test())
