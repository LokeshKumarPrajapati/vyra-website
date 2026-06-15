"""
VYRA Long-Term Planner — Phase 15
====================================
Hierarchical Task Network planner for multi-week projects.

Based on:
  - HTN Planning (Erol, Hendler & Nau 1994)
  - Getting Things Done (Allen 2001) — capture, clarify, organize

Features:
  1. PROJECTS — multi-week goals broken into milestones
  2. TASK DECOMPOSITION — projects → milestones → tasks
  3. DEADLINE TRACKING — warns when deadlines approach
  4. PROGRESS SCORING — 0.0–1.0 completion per project
  5. SMART SUGGESTIONS — next best action for each project
"""

import json
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

DATA_DIR     = Path(__file__).parent.parent / "data"
PLANNER_PATH = DATA_DIR / "long_term_planner.json"


@dataclass
class PlanTask:
    task_id: str
    title: str
    status: str = "pending"   # pending | in_progress | done | blocked
    priority: int = 2          # 1=high 2=medium 3=low
    due_date: Optional[str] = None
    notes: str = ""
    completed_at: Optional[str] = None


@dataclass
class Project:
    project_id: str
    title: str
    goal: str
    status: str = "active"    # active | paused | completed | archived
    priority: int = 2
    deadline: Optional[str] = None
    tasks: List[PlanTask] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None

    def progress(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t.status == "done")
        return round(done / len(self.tasks), 3)

    def next_action(self) -> Optional[PlanTask]:
        pending = [t for t in self.tasks if t.status in ("pending", "in_progress")]
        if not pending:
            return None
        pending.sort(key=lambda t: t.priority)
        return pending[0]

    def days_until_deadline(self) -> Optional[int]:
        if not self.deadline:
            return None
        try:
            dl = datetime.fromisoformat(self.deadline)
            return (dl - datetime.utcnow()).days
        except Exception:
            return None


class LongTermPlanner:
    """
    Manages multi-week projects with task decomposition and progress tracking.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._projects: Dict[str, Project] = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(PLANNER_PATH.read_text())
            for k, v in raw.items():
                tasks = [PlanTask(**t) for t in v.get("tasks", [])]
                proj_data = {**v, "tasks": tasks}
                self._projects[k] = Project(**proj_data)
        except Exception:
            pass

    def _save(self):
        try:
            out = {}
            for k, p in self._projects.items():
                d = asdict(p)
                out[k] = d
            PLANNER_PATH.write_text(json.dumps(out, indent=2))
        except Exception:
            pass

    def add_project(
        self,
        project_id: str,
        title: str,
        goal: str,
        deadline: Optional[str] = None,
        priority: int = 2,
    ) -> Project:
        proj = Project(
            project_id=project_id,
            title=title,
            goal=goal,
            deadline=deadline,
            priority=priority,
        )
        self._projects[project_id] = proj
        self._save()
        return proj

    def add_task(
        self,
        project_id: str,
        task_id: str,
        title: str,
        priority: int = 2,
        due_date: Optional[str] = None,
    ) -> Optional[PlanTask]:
        proj = self._projects.get(project_id)
        if not proj:
            return None
        task = PlanTask(task_id=task_id, title=title, priority=priority, due_date=due_date)
        proj.tasks.append(task)
        self._save()
        return task

    def update_task_status(self, project_id: str, task_id: str, status: str):
        proj = self._projects.get(project_id)
        if not proj:
            return
        for task in proj.tasks:
            if task.task_id == task_id:
                task.status = status
                if status == "done":
                    task.completed_at = datetime.utcnow().isoformat()
                break
        if proj.progress() >= 1.0:
            proj.status = "completed"
            proj.completed_at = datetime.utcnow().isoformat()
        self._save()

    def get_active_projects(self) -> List[Project]:
        active = [p for p in self._projects.values() if p.status == "active"]
        active.sort(key=lambda p: p.priority)
        return active

    def get_deadline_warnings(self) -> List[Dict[str, Any]]:
        warnings = []
        for p in self.get_active_projects():
            days = p.days_until_deadline()
            if days is not None and days <= 7:
                warnings.append({
                    "project": p.title,
                    "days_left": days,
                    "progress": p.progress(),
                })
        return sorted(warnings, key=lambda x: x["days_left"])

    def to_system_fragment(self) -> str:
        active = self.get_active_projects()
        if not active:
            return ""
        lines = [f"[Active projects: {len(active)}]"]
        for p in active[:3]:
            nxt = p.next_action()
            nxt_title = f" → Next: {nxt.title}" if nxt else ""
            lines.append(f"  • {p.title} ({round(p.progress()*100)}%){nxt_title}")
        warnings = self.get_deadline_warnings()
        if warnings:
            lines.append(f"  ⚠ Deadline warning: {warnings[0]['project']} ({warnings[0]['days_left']}d left)")
        return "\n".join(lines)

    def snapshot(self) -> Dict[str, Any]:
        active = self.get_active_projects()
        total_tasks = sum(len(p.tasks) for p in active)
        done_tasks  = sum(sum(1 for t in p.tasks if t.status == "done") for p in active)
        return {
            "active_projects": len(active),
            "total_tasks": total_tasks,
            "completed_tasks": done_tasks,
            "overall_progress": round(done_tasks / max(1, total_tasks), 3),
            "deadline_warnings": len(self.get_deadline_warnings()),
        }


_ltp: Optional[LongTermPlanner] = None

def get_long_term_planner() -> LongTermPlanner:
    global _ltp
    if _ltp is None:
        _ltp = LongTermPlanner()
    return _ltp


if __name__ == "__main__":
    ltp = get_long_term_planner()
    ltp.add_project("vyra_agi", "VYRA AGI Build", "Complete all 20 AGI phases", deadline="2026-06-01")
    ltp.add_task("vyra_agi", "p13", "Brain memory architecture", priority=1)
    ltp.add_task("vyra_agi", "p14", "Proactive intelligence", priority=1)
    ltp.add_task("vyra_agi", "p20", "AGI controller", priority=1)
    ltp.update_task_status("vyra_agi", "p13", "done")
    print("Projects:", [(p.title, round(p.progress(), 2)) for p in ltp.get_active_projects()])
    print("Snapshot:", ltp.snapshot())
    print("Fragment:", ltp.to_system_fragment())
