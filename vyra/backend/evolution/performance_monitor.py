"""
Performance Monitor — Phase 5.3
==================================
Tracks VYRA's own KPIs across sessions. Provides self-awareness of quality.

Metrics:
  - task_completion_rate   : % of requests fully resolved
  - user_correction_rate   : % of responses that got corrected
  - avg_response_latency   : P50 / P95 in ms
  - memory_hit_rate        : % of queries where memory helped
  - goal_completion_rate   : % of created goals that reached DONE
  - tool_success_rate      : per-tool and aggregate
  - session_count          : total sessions
  - turns_per_session      : average conversation depth

Data is persisted to SQLite and surfaced in the Electron dashboard.
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class SessionMetrics:
    session_id: str
    started_at: str
    ended_at: str
    turn_count: int
    correction_count: int
    tool_calls: int
    tool_failures: int
    memory_hits: int
    avg_latency_ms: float


@dataclass
class KPISnapshot:
    timestamp: str
    task_completion_rate: float     # 0-1
    user_correction_rate: float     # 0-1 (lower is better)
    avg_latency_ms_p50: float
    avg_latency_ms_p95: float
    memory_hit_rate: float
    goal_completion_rate: float
    total_sessions: int
    avg_turns_per_session: float
    top_failing_tools: List[str]


class PerformanceMonitor:

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path  = data_dir / "performance.db"
        self._init_db()

        # In-memory accumulators for current session
        self._session_id     : str   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self._session_start  : float = time.time()
        self._turns          : int   = 0
        self._corrections    : int   = 0
        self._tool_calls     : int   = 0
        self._tool_failures  : int   = 0
        self._memory_hits    : int   = 0
        self._latencies      : List[float] = []

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                started_at TEXT,
                ended_at TEXT,
                turn_count INTEGER,
                correction_count INTEGER,
                tool_calls INTEGER,
                tool_failures INTEGER,
                memory_hits INTEGER,
                avg_latency_ms REAL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                event_type TEXT,
                value REAL,
                metadata TEXT,
                timestamp TEXT
            );
        """)
        con.commit()
        con.close()

    # ── Recording API ─────────────────────────────────────────────────────────

    def record_turn(self, latency_ms: float, memory_used: bool = False):
        self._turns     += 1
        self._latencies.append(latency_ms)
        if memory_used:
            self._memory_hits += 1
        self._log_event("turn", latency_ms)

    def record_correction(self):
        self._corrections += 1
        self._log_event("correction", 1.0)

    def record_tool_call(self, tool_id: str, success: bool, latency_ms: float = 0.0):
        self._tool_calls += 1
        if not success:
            self._tool_failures += 1
        self._log_event("tool_call", 1.0 if success else 0.0,
                        metadata={"tool_id": tool_id, "latency_ms": latency_ms})
        # Also update capability registry
        try:
            from evolution.capability_registry import get_registry  # type: ignore
            get_registry().record_call(tool_id, success, latency_ms)
        except Exception:
            pass

    def flush_session(self):
        """Call when session ends (vyra.py on disconnect)."""
        ended = datetime.utcnow().isoformat()
        avg_lat = sum(self._latencies) / len(self._latencies) if self._latencies else 0.0
        con = sqlite3.connect(self.db_path)
        con.execute("""
            INSERT OR REPLACE INTO sessions
            (session_id,started_at,ended_at,turn_count,correction_count,
             tool_calls,tool_failures,memory_hits,avg_latency_ms)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            self._session_id,
            datetime.utcfromtimestamp(self._session_start).isoformat(),
            ended,
            self._turns, self._corrections,
            self._tool_calls, self._tool_failures,
            self._memory_hits, avg_lat,
        ))
        con.commit()
        con.close()
        # Reset accumulators
        self._session_id    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        self._session_start = time.time()
        self._turns = self._corrections = self._tool_calls = 0
        self._tool_failures = self._memory_hits = 0
        self._latencies = []

    # ── KPI calculation ───────────────────────────────────────────────────────

    def compute_kpi(self, days_back: int = 30) -> KPISnapshot:
        cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
        con = sqlite3.connect(self.db_path)

        rows = con.execute(
            "SELECT * FROM sessions WHERE started_at >= ?", (cutoff,)
        ).fetchall()

        if not rows:
            con.close()
            return KPISnapshot(
                timestamp=datetime.utcnow().isoformat(),
                task_completion_rate=0.0, user_correction_rate=0.0,
                avg_latency_ms_p50=0.0, avg_latency_ms_p95=0.0,
                memory_hit_rate=0.0, goal_completion_rate=0.0,
                total_sessions=0, avg_turns_per_session=0.0,
                top_failing_tools=[],
            )

        total_turns       = sum(r[3] for r in rows)
        total_corrections = sum(r[4] for r in rows)
        total_tools       = sum(r[5] for r in rows)
        total_failures    = sum(r[6] for r in rows)
        total_mem_hits    = sum(r[7] for r in rows)
        latencies         = [r[8] for r in rows if r[8]]

        correction_rate   = total_corrections / total_turns if total_turns else 0.0
        tool_success_rate = 1 - (total_failures / total_tools if total_tools else 0)
        mem_hit_rate      = total_mem_hits / total_turns if total_turns else 0.0
        avg_turns         = total_turns / len(rows) if rows else 0.0

        import statistics
        p50 = statistics.median(latencies) if latencies else 0.0
        p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

        # Goal completion rate
        goal_completion = 0.0
        try:
            from goals.goal_engine import get_goal_engine, GoalStatus  # type: ignore
            engine = get_goal_engine()
            all_g  = engine.list_all()
            if all_g:
                done = sum(1 for g in all_g if g.status == GoalStatus.DONE)
                goal_completion = done / len(all_g)
        except Exception:
            pass

        # Top failing tools
        failing: List[str] = []
        try:
            from evolution.capability_registry import get_registry  # type: ignore
            failing = [t.id for t in get_registry().get_poor_performers()][:3]
        except Exception:
            pass

        con.close()
        return KPISnapshot(
            timestamp            = datetime.utcnow().isoformat(),
            task_completion_rate = tool_success_rate,
            user_correction_rate = correction_rate,
            avg_latency_ms_p50   = p50,
            avg_latency_ms_p95   = p95,
            memory_hit_rate      = mem_hit_rate,
            goal_completion_rate = goal_completion,
            total_sessions       = len(rows),
            avg_turns_per_session= avg_turns,
            top_failing_tools    = failing,
        )

    def kpi_ui_card(self) -> Dict:
        kpi = self.compute_kpi()
        return {
            "type": "kpi_dashboard",
            "timestamp": kpi.timestamp,
            "metrics": {
                "Task Success Rate":     f"{kpi.task_completion_rate:.1%}",
                "Correction Rate":       f"{kpi.user_correction_rate:.1%}",
                "Avg Response (P50)":    f"{kpi.avg_latency_ms_p50:.0f}ms",
                "Avg Response (P95)":    f"{kpi.avg_latency_ms_p95:.0f}ms",
                "Memory Hit Rate":       f"{kpi.memory_hit_rate:.1%}",
                "Goal Completion":       f"{kpi.goal_completion_rate:.1%}",
                "Total Sessions":        str(kpi.total_sessions),
                "Avg Turns/Session":     f"{kpi.avg_turns_per_session:.1f}",
            },
            "alerts": [f"Low performing tool: {t}" for t in kpi.top_failing_tools],
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _log_event(self, event_type: str, value: float, metadata: Dict = None):
        con = sqlite3.connect(self.db_path)
        con.execute("""
            INSERT INTO events (session_id,event_type,value,metadata,timestamp)
            VALUES (?,?,?,?,?)
        """, (
            self._session_id, event_type, value,
            json.dumps(metadata or {}), datetime.utcnow().isoformat(),
        ))
        con.commit()
        con.close()


_monitor: Optional[PerformanceMonitor] = None

def get_monitor() -> PerformanceMonitor:
    global _monitor
    if _monitor is None:
        _monitor = PerformanceMonitor()
    return _monitor
