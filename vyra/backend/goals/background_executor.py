"""
Background Executor — Phase 2.2
================================
Daemon that silently works on active Goals while the user is idle.

Behaviour:
- Polls active goals every POLL_INTERVAL seconds
- Skips if user is currently in a voice session (sets self.user_active flag)
- Picks the next PENDING task from the highest-priority goal
- Dispatches task to correct VYRA agent
- Reports milestone via voice notification callback
- Respects requires_approval flag → queues for next user interaction

Usage (in vyra.py startup):
    executor = get_executor()
    executor.set_notify_callback(lambda msg: sio.emit("vyra_notification", {"text": msg}))
    asyncio.create_task(executor.run())

    # Signal user is talking:
    executor.set_user_active(True)
    # Signal idle again:
    executor.set_user_active(False)
"""

import asyncio
import time
from datetime import datetime
from typing import Callable, Awaitable, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from goals.goal_engine import get_goal_engine, GoalStatus, TaskStatus, Task  # type: ignore

POLL_INTERVAL = 900       # check goals every 15 min
IDLE_THRESHOLD = 120      # seconds since last user interaction to be considered idle
MAX_TASKS_PER_CYCLE = 3   # don't run more than this many tasks per wakeup


class BackgroundExecutor:

    def __init__(self):
        self._user_active: bool   = False
        self._last_activity: float = time.time()
        self._running: bool        = False
        self._notify: Optional[Callable[[str], Awaitable[None]]] = None
        self._agent_dispatch: Optional[Callable] = None   # injected from vyra.py
        self._approval_queue: list[Task] = []             # tasks needing user OK

    # ── Configuration ─────────────────────────────────────────────────────────

    def set_notify_callback(self, cb: Callable[[str], Awaitable[None]]):
        """Called when VYRA wants to proactively notify the user."""
        self._notify = cb

    def set_agent_dispatch(self, dispatch_fn: Callable):
        """Injected from vyra.py: dispatch_fn(task) → result string"""
        self._agent_dispatch = dispatch_fn

    def set_user_active(self, active: bool):
        self._user_active = active
        if active:
            self._last_activity = time.time()

    def get_approval_queue(self) -> list[Task]:
        """Return tasks waiting for user approval."""
        return list(self._approval_queue)

    def approve_task(self, task_id: str):
        """User approved a queued task — move it to pending for execution."""
        self._approval_queue = [t for t in self._approval_queue if t.id != task_id]
        # The engine already has the task as PENDING — just let executor pick it up

    def reject_task(self, task_id: str, goal_id: str):
        engine = get_goal_engine()
        engine.update_task_status(goal_id, task_id, TaskStatus.SKIPPED, result="User rejected")
        self._approval_queue = [t for t in self._approval_queue if t.id != task_id]

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        print("[BackgroundExecutor] Started — watching for active goals...")
        while self._running:
            await asyncio.sleep(POLL_INTERVAL)
            await self._cycle()

    async def _cycle(self):
        """One execution cycle: pick next task from highest-priority active goal."""
        idle_seconds = time.time() - self._last_activity
        if self._user_active or idle_seconds < IDLE_THRESHOLD:
            return   # user is busy, skip this cycle

        engine  = get_goal_engine()
        active  = engine.list_active()
        if not active:
            return

        # Sort by priority (1 = highest)
        active.sort(key=lambda g: g.priority)
        tasks_run = 0

        for goal in active:
            if tasks_run >= MAX_TASKS_PER_CYCLE:
                break

            task = goal.next_task
            if task is None:
                continue

            # Tasks requiring approval → queue them
            if task.requires_approval:
                if task not in self._approval_queue:
                    self._approval_queue.append(task)
                    await self._notify_user(
                        f"I need your approval to continue on '{goal.title}': "
                        f"{task.instruction}. Say 'approve task' to proceed."
                    )
                continue

            # Execute
            print(f"[BackgroundExecutor] Running task: [{task.agent}] {task.instruction[:60]}")
            engine.update_task_status(goal.id, task.id, TaskStatus.IN_PROGRESS)
            try:
                result = await self._dispatch(task)
                engine.update_task_status(goal.id, task.id, TaskStatus.DONE, result=result)
                tasks_run += 1

                # Milestone notification if KR completed
                for kr in goal.key_results:
                    if task in kr.tasks and kr.progress >= 1.0:
                        await self._notify_user(
                            f"Milestone reached on '{goal.title}': {kr.description}"
                        )

                # Goal completion
                if goal.status == GoalStatus.DONE:
                    await self._notify_user(
                        f"I finished your goal: '{goal.title}'! "
                        f"Everything is complete. Want a summary?"
                    )

            except Exception as e:
                engine.update_task_status(goal.id, task.id, TaskStatus.FAILED, result=str(e))
                print(f"[BackgroundExecutor] Task failed: {e}")

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(self, task: Task) -> str:
        if self._agent_dispatch:
            return await self._agent_dispatch(task)
        # Fallback: log only
        return f"[Simulated] {task.instruction}"

    # ── Notify ────────────────────────────────────────────────────────────────

    async def _notify_user(self, message: str):
        print(f"[BackgroundExecutor] NOTIFY → {message}")
        if self._notify:
            try:
                await self._notify(message)
            except Exception as e:
                print(f"[BackgroundExecutor] Notify error: {e}")

    def stop(self):
        self._running = False


# ── Singleton ─────────────────────────────────────────────────────────────────

_executor: Optional[BackgroundExecutor] = None

def get_executor() -> BackgroundExecutor:
    global _executor
    if _executor is None:
        _executor = BackgroundExecutor()
    return _executor
