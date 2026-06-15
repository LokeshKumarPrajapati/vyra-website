"""
VYRA Self-Decision Engine
==========================
VYRA makes DECISIONS on her own — not just responding to prompts.

When idle, she continuously evaluates possible actions:
  - "User has a deadline tomorrow — should I prepare a briefing?"
  - "I haven't done well at explaining X — should I research it now?"
  - "User seemed stressed — should I prepare something calming?"
  - "Goal X has been blocked for 3 days — should I attempt it again?"

Decision Types:
  RESEARCH      — go learn something to be more useful
  PREPARE       — pre-build something the user will need
  REFLECT       — analyze a mistake and store lessons
  REACH_OUT     — queue a message to share with user
  GOAL_ATTEMPT  — try to advance an active user goal
  SELF_IMPROVE  — adjust own behavior (feeds into self_evolution.py)

Safety rules:
  - All external actions (message user, execute goal) require approval queue
  - Pure internal actions (research, reflect) execute autonomously
  - Each decision has a confidence threshold before execution
  - Max 3 autonomous actions per hour (prevents runaway)
"""

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

DATA_DIR = Path(__file__).parent.parent / "data"
DECISION_LOG_PATH  = DATA_DIR / "decision_log.jsonl"
PENDING_QUEUE_PATH = DATA_DIR / "pending_decisions.json"

DECISION_INTERVAL_SECONDS = 15 * 60   # evaluate decisions every 15 min
MAX_ACTIONS_PER_HOUR      = 3
CONFIDENCE_THRESHOLD      = 0.65


# ── Data types ────────────────────────────────────────────────────────────────

DECISION_TYPES = {
    "research":      {"requires_approval": False, "description": "Go learn something"},
    "prepare":       {"requires_approval": False, "description": "Pre-build a useful artifact"},
    "reflect":       {"requires_approval": False, "description": "Analyze past mistakes"},
    "reach_out":     {"requires_approval": True,  "description": "Queue message to user"},
    "goal_attempt":  {"requires_approval": True,  "description": "Advance an active goal"},
    "self_improve":  {"requires_approval": False, "description": "Modify own behavior"},
}


@dataclass
class Decision:
    id: str
    timestamp: str
    type: str                        # one of DECISION_TYPES
    title: str                       # short human-readable title
    reasoning: str                   # why VYRA decided this
    action_plan: str                 # concrete steps to execute
    confidence: float                # 0.0–1.0
    priority: int                    # 1 (low) – 5 (critical)
    triggers: List[str]              # what caused this decision
    requires_approval: bool
    status: str = "pending"          # pending | approved | executing | done | rejected
    result: str = ""
    executed_at: Optional[str] = None


# ── Context evaluator ─────────────────────────────────────────────────────────

DECISION_SYSTEM = """You are VYRA's decision-making core.
Your job is to identify the single most valuable autonomous action you could take RIGHT NOW
to be more useful to your user.

Evaluate the provided context and output a JSON decision object with these fields:
{
  "type": "research|prepare|reflect|reach_out|goal_attempt|self_improve",
  "title": "short action title (under 60 chars)",
  "reasoning": "2-3 sentence explanation of why this is the best use of time",
  "action_plan": "concrete step-by-step description of what to do",
  "confidence": 0.0-1.0,
  "priority": 1-5,
  "triggers": ["trigger1", "trigger2"]
}

Only output valid JSON. If no valuable action exists, output {"type": "none"}.
Be honest — unnecessary actions have a cost. Only decide when you see clear value."""


class DecisionEngine:

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client  = get_nvidia_client()
        self._decisions: List[Decision] = self._load_log()
        self._pending: List[Decision]   = self._load_pending()
        self._action_count_this_hour    = 0
        self._hour_reset_time           = time.time()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._context_fn: Optional[Callable[[], Dict[str, Any]]] = None
        self._action_handlers: Dict[str, Callable] = {}

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_log(self) -> List[Decision]:
        decisions = []
        if not DECISION_LOG_PATH.exists():
            return []
        try:
            lines = DECISION_LOG_PATH.read_text(encoding="utf-8").strip().split("\n")
            for line in lines[-100:]:
                if line.strip():
                    decisions.append(Decision(**json.loads(line)))
        except Exception:
            pass
        return decisions

    def _load_pending(self) -> List[Decision]:
        if not PENDING_QUEUE_PATH.exists():
            return []
        try:
            items = json.loads(PENDING_QUEUE_PATH.read_text())
            return [Decision(**d) for d in items]
        except Exception:
            return []

    def _save_pending(self):
        try:
            PENDING_QUEUE_PATH.write_text(
                json.dumps([asdict(d) for d in self._pending], indent=2)
            )
        except Exception:
            pass

    def _log_decision(self, d: Decision):
        self._decisions.append(d)
        try:
            with open(DECISION_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(d)) + "\n")
        except Exception:
            pass

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _check_rate_limit(self) -> bool:
        now = time.time()
        if now - self._hour_reset_time > 3600:
            self._action_count_this_hour = 0
            self._hour_reset_time = now
        return self._action_count_this_hour < MAX_ACTIONS_PER_HOUR

    def _increment_action_count(self):
        self._action_count_this_hour += 1

    # ── Decision evaluation ───────────────────────────────────────────────────

    def register_context_fn(self, fn: Callable[[], Dict[str, Any]]):
        """Register a function that returns current system context."""
        self._context_fn = fn

    def register_action_handler(self, decision_type: str, handler: Callable):
        """Register an async handler for a specific decision type."""
        self._action_handlers[decision_type] = handler

    async def evaluate(self) -> Optional[Decision]:
        """
        Evaluate current context and decide if there's a valuable action.
        Returns a Decision if one is found, None otherwise.
        """
        import uuid
        if not self._check_rate_limit():
            return None

        context = {}
        if self._context_fn:
            try:
                context = self._context_fn()
            except Exception:
                pass

        context_str = json.dumps(context, indent=2, default=str) if context else "{}"

        prompt = (
            f"Current system context:\n{context_str}\n\n"
            f"Recent decisions made:\n"
            + "\n".join([f"  [{d.type}] {d.title} ({d.status})" for d in self._decisions[-5:]])
            + "\n\nWhat is the single most valuable autonomous action right now?"
        )

        try:
            resp = await self.client.achat(
                [
                    {"role": "system", "content": DECISION_SYSTEM},
                    {"role": "user",   "content": prompt},
                ],
                model="fast",
                max_tokens=512,
                temperature=0.3,
            )
            raw   = resp.content.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            obj   = json.loads(raw[start:end])

            if obj.get("type") == "none" or not obj.get("type"):
                return None

            decision_type = obj.get("type", "research")
            requires_approval = DECISION_TYPES.get(decision_type, {}).get("requires_approval", True)
            confidence = float(obj.get("confidence", 0.5))

            if confidence < CONFIDENCE_THRESHOLD:
                return None

            d = Decision(
                id               = str(uuid.uuid4()),
                timestamp        = datetime.utcnow().isoformat(),
                type             = decision_type,
                title            = obj.get("title", "Untitled decision"),
                reasoning        = obj.get("reasoning", ""),
                action_plan      = obj.get("action_plan", ""),
                confidence       = confidence,
                priority         = int(obj.get("priority", 2)),
                triggers         = obj.get("triggers", []),
                requires_approval= requires_approval,
            )
            self._log_decision(d)

            if requires_approval:
                self._pending.append(d)
                self._save_pending()
                return d
            else:
                await self._execute(d)
                return d

        except Exception:
            return None

    async def _execute(self, d: Decision):
        """Execute a decision that doesn't require approval."""
        d.status     = "executing"
        d.executed_at = datetime.utcnow().isoformat()
        self._increment_action_count()

        handler = self._action_handlers.get(d.type)
        if handler:
            try:
                result = await handler(d)
                d.result = str(result or "")
                d.status = "done"
            except Exception as e:
                d.result = f"Error: {e}"
                d.status = "done"
        else:
            d.result = f"No handler for type '{d.type}'"
            d.status = "done"

    # ── User approval flow ────────────────────────────────────────────────────

    def get_pending_for_approval(self) -> List[Decision]:
        return [d for d in self._pending if d.status == "pending"]

    async def approve(self, decision_id: str) -> bool:
        for d in self._pending:
            if d.id == decision_id and d.status == "pending":
                d.status = "approved"
                await self._execute(d)
                self._save_pending()
                return True
        return False

    def reject(self, decision_id: str) -> bool:
        for d in self._pending:
            if d.id == decision_id and d.status == "pending":
                d.status = "rejected"
                self._save_pending()
                return True
        return False

    # ── Background loop ───────────────────────────────────────────────────────

    def start(self, idle_fn: Optional[Callable[[], bool]] = None):
        if self._running:
            return
        self._running = True

        def _loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while self._running:
                time.sleep(DECISION_INTERVAL_SECONDS)
                idle = idle_fn() if idle_fn else True
                if not idle:
                    continue
                try:
                    loop.run_until_complete(self.evaluate())
                except Exception:
                    pass

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    # ── Status reports ────────────────────────────────────────────────────────

    def decision_summary(self) -> str:
        recent = self._decisions[-10:]
        if not recent:
            return "No autonomous decisions made yet."
        lines = ["[Recent Autonomous Decisions]"]
        for d in recent:
            lines.append(f"  [{d.type}] {d.title} — {d.status} (confidence: {d.confidence:.2f})")
        pending = self.get_pending_for_approval()
        if pending:
            lines.append(f"\n[Awaiting Your Approval]")
            for d in pending:
                lines.append(f"  [{d.priority}★] {d.title}")
            lines.append("  (Say 'approve [title]' or 'reject [title]')")
        return "\n".join(lines)

    def stats(self) -> dict:
        total = len(self._decisions)
        done  = sum(1 for d in self._decisions if d.status == "done")
        return {
            "total_decisions":    total,
            "executed":           done,
            "pending_approval":   len(self.get_pending_for_approval()),
            "actions_this_hour":  self._action_count_this_hour,
            "success_rate":       round(done / total, 2) if total else 0.0,
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[DecisionEngine] = None

def get_decision_engine() -> DecisionEngine:
    global _engine
    if _engine is None:
        _engine = DecisionEngine()
    return _engine


if __name__ == "__main__":
    async def _test():
        engine = get_decision_engine()
        engine.register_context_fn(lambda: {
            "active_goals": ["Build portfolio website"],
            "time": datetime.utcnow().isoformat(),
            "user_last_seen": "2 hours ago",
            "recent_topics": ["React", "portfolio", "job applications"],
        })
        decision = await engine.evaluate()
        if decision:
            print(f"Decision: [{decision.type}] {decision.title}")
            print(f"Reasoning: {decision.reasoning}")
            print(f"Confidence: {decision.confidence}")
        else:
            print("No decision made.")
        print(engine.decision_summary())

    asyncio.run(_test())
