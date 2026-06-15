"""
VYRA Autonomous Executor — Phase 18
======================================
VYRA executes multi-step tasks independently in the background.
She can queue, prioritize, execute, and report on tasks without
being asked each step.

Based on:
  - BDI (Belief-Desire-Intention) agent architecture (Rao & Georgeff 1995)
  - ReAct framework (Yao et al. 2022) — reason + act interleaved

Features:
  1. TASK QUEUE — ordered list of autonomous tasks
  2. EXECUTION TRACKING — status, progress, output per task
  3. CHAINED TASKS — task B can depend on task A's output
  4. BACKGROUND SAFETY — won't execute destructive actions without approval
  5. RESULT REPORTING — summarizes completed tasks for user
"""

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

DATA_DIR   = Path(__file__).parent.parent / "data"
EXEC_PATH  = DATA_DIR / "autonomous_executor.json"

SAFE_TASK_TYPES = {"research", "summarize", "analyze", "calculate", "remind", "plan", "reflect"}


@dataclass
class AutonomousTask:
    task_id: str
    title: str
    task_type: str              # must be in SAFE_TASK_TYPES
    description: str
    priority: int = 2           # 1=high 2=medium 3=low
    status: str = "queued"      # queued | running | completed | failed | needs_approval
    result: str = ""
    depends_on: Optional[str] = None   # task_id this depends on
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    approved: bool = True        # False = needs user approval before running


class AutonomousExecutor:
    """
    Manages VYRA's autonomous task queue and execution.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._tasks: Dict[str, AutonomousTask] = {}
        self._completed_results: List[Dict] = []
        self._load()

    def _load(self):
        try:
            raw = json.loads(EXEC_PATH.read_text())
            for k, v in raw.get("tasks", {}).items():
                self._tasks[k] = AutonomousTask(**v)
            self._completed_results = raw.get("completed_results", [])[-20:]
        except Exception:
            pass

    def _save(self):
        try:
            EXEC_PATH.write_text(json.dumps({
                "tasks": {k: asdict(v) for k, v in self._tasks.items()},
                "completed_results": self._completed_results[-20:],
            }, indent=2))
        except Exception:
            pass

    def queue_task(
        self,
        task_id: str,
        title: str,
        task_type: str,
        description: str,
        priority: int = 2,
        depends_on: Optional[str] = None,
        requires_approval: bool = False,
    ) -> AutonomousTask:
        task = AutonomousTask(
            task_id=task_id,
            title=title,
            task_type=task_type if task_type in SAFE_TASK_TYPES else "research",
            description=description,
            priority=priority,
            depends_on=depends_on,
            approved=not requires_approval,
        )
        if requires_approval:
            task.status = "needs_approval"
        self._tasks[task_id] = task
        self._save()
        return task

    def approve_task(self, task_id: str):
        task = self._tasks.get(task_id)
        if task and task.status == "needs_approval":
            task.status = "queued"
            task.approved = True
            self._save()

    def complete_task(self, task_id: str, result: str):
        """Called when a task finishes (by background worker or consolidator)."""
        task = self._tasks.get(task_id)
        if task:
            task.status = "completed"
            task.result = result
            task.completed_at = datetime.utcnow().isoformat()
            self._completed_results.append({
                "task_id": task_id,
                "title": task.title,
                "result": result[:200],
                "completed_at": task.completed_at,
            })
            self._save()

    def fail_task(self, task_id: str, reason: str):
        task = self._tasks.get(task_id)
        if task:
            task.status = "failed"
            task.result = f"Failed: {reason}"
            self._save()

    def get_next_runnable(self) -> Optional[AutonomousTask]:
        """Return the next task that's ready to run."""
        queued = [t for t in self._tasks.values() if t.status == "queued" and t.approved]
        if not queued:
            return None
        # Check dependencies
        ready = []
        for t in queued:
            if t.depends_on:
                dep = self._tasks.get(t.depends_on)
                if dep and dep.status != "completed":
                    continue
            ready.append(t)
        if not ready:
            return None
        ready.sort(key=lambda t: t.priority)
        return ready[0]

    def get_pending_approval(self) -> List[AutonomousTask]:
        return [t for t in self._tasks.values() if t.status == "needs_approval"]

    def get_recent_results(self, n: int = 3) -> List[Dict]:
        return self._completed_results[-n:]

    def to_system_fragment(self) -> str:
        queued = [t for t in self._tasks.values() if t.status == "queued"]
        recent = self.get_recent_results(2)
        lines = []
        if queued:
            lines.append(f"[{len(queued)} autonomous tasks queued]")
        if recent:
            done = recent[-1]
            lines.append(f"[Last completed task: {done['title']}]")
        pending = self.get_pending_approval()
        if pending:
            lines.append(f"[{len(pending)} tasks need your approval]")
        return "\n".join(lines) if lines else ""

    def snapshot(self) -> Dict[str, Any]:
        statuses: Dict[str, int] = {}
        for t in self._tasks.values():
            statuses[t.status] = statuses.get(t.status, 0) + 1
        return {
            "total_tasks": len(self._tasks),
            "status_breakdown": statuses,
            "recent_completions": len(self._completed_results),
            "pending_approval": len(self.get_pending_approval()),
        }


_ae: Optional[AutonomousExecutor] = None

def get_autonomous_executor() -> AutonomousExecutor:
    global _ae
    if _ae is None:
        _ae = AutonomousExecutor()
    return _ae


if __name__ == "__main__":
    ae = get_autonomous_executor()
    ae.queue_task("research_nse", "Research NSE circuit breakers", "research",
                  "Understand NSE market circuit breaker rules in detail", priority=2)
    ae.queue_task("summarize_week", "Weekly activity summary", "summarize",
                  "Summarize this week's key conversations and learnings", priority=3)
    ae.complete_task("research_nse", "NSE has 3 circuit breaker levels: 10%, 15%, 20% fall triggers halt.")
    print("Snapshot:", ae.snapshot())
    print("Fragment:", ae.to_system_fragment())
    print("Recent:", ae.get_recent_results(2))
