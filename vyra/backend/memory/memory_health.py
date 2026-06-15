"""
VYRA Memory Health Monitor
============================
Tracks how "fit" VYRA's memory system is across 5 dimensions,
builds a 0–100 overall score, and maintains 30-day trend history
so the dashboard can show improvement over time.

5 Health Dimensions:
  1. Encoding Health   — Are new experiences being captured?
     = min(1, episodes_last_7_days / 7)     target: ≥1 episode/day
  2. Retention Health  — How well are known entities retained?
     = mean retention score from ForgettingCurveTracker
  3. Consolidation Health — Are insights being extracted during idle?
     = min(1, consolidation_cycles_last_7d / 2)   target: ≥2 cycles/week
  4. Growth Rate       — Is the knowledge base expanding?
     = new entities this week / max(1, last week's count), capped at 1
  5. Retrieval Quality — Is search returning useful results?
     = exponential moving average of retrieval success signals

Overall = 0.20×encoding + 0.30×retention + 0.20×consolidation + 0.15×growth + 0.15×retrieval

The monitor saves a snapshot every hour and keeps a 30-day history,
enabling the dashboard to show weekly trends and improvement reports.
"""

import json
import time
from dataclasses import dataclass, field, asdict
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

DATA_DIR      = Path(__file__).parent.parent / "data"
HEALTH_PATH   = DATA_DIR / "memory_health.json"
HEALTH_LOG    = DATA_DIR / "memory_health_log.jsonl"

WEIGHTS = {
    "encoding":      0.20,
    "retention":     0.30,
    "consolidation": 0.20,
    "growth":        0.15,
    "retrieval":     0.15,
}

SAVE_INTERVAL = 3600   # seconds between snapshots


@dataclass
class MemoryHealthSnapshot:
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    encoding_health: float = 0.5
    retention_health: float = 0.5
    consolidation_health: float = 0.5
    growth_rate: float = 0.5
    retrieval_quality: float = 0.5
    overall: float = 0.5

    def to_score_100(self) -> int:
        return round(self.overall * 100)

    def weakest_dimension(self) -> Tuple[str, float]:
        dims = {
            "encoding":      self.encoding_health,
            "retention":     self.retention_health,
            "consolidation": self.consolidation_health,
            "growth":        self.growth_rate,
            "retrieval":     self.retrieval_quality,
        }
        k = min(dims, key=dims.get)
        return (k, dims[k])

    def strongest_dimension(self) -> Tuple[str, float]:
        dims = {
            "encoding":      self.encoding_health,
            "retention":     self.retention_health,
            "consolidation": self.consolidation_health,
            "growth":        self.growth_rate,
            "retrieval":     self.retrieval_quality,
        }
        k = max(dims, key=dims.get)
        return (k, dims[k])


class MemoryHealthMonitor:
    """
    Computes, stores, and serves memory health metrics.
    Integrates with ForgettingCurveTracker and EpisodicMemory.
    """

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._retrieval_ema: float = 0.7       # exponential moving average
        self._retrieval_alpha: float = 0.15    # EMA smoothing factor
        self._last_snapshot_time: float = 0.0
        self._entity_count_last_week: int = 0
        self._consolidation_cycles_7d: int = 0
        self._load()

    def _load(self):
        try:
            raw = json.loads(HEALTH_PATH.read_text())
            self._retrieval_ema          = raw.get("retrieval_ema", 0.7)
            self._entity_count_last_week = raw.get("entity_count_last_week", 0)
            self._consolidation_cycles_7d = raw.get("consolidation_cycles_7d", 0)
            self._last_snapshot_time     = raw.get("last_snapshot_time", 0.0)
        except Exception:
            pass

    def _save_state(self):
        try:
            HEALTH_PATH.write_text(json.dumps({
                "retrieval_ema": self._retrieval_ema,
                "entity_count_last_week": self._entity_count_last_week,
                "consolidation_cycles_7d": self._consolidation_cycles_7d,
                "last_snapshot_time": self._last_snapshot_time,
            }, indent=2))
        except Exception:
            pass

    # ── Signal recording ──────────────────────────────────────────────────────

    def record_retrieval_signal(self, success: bool):
        """Call after every search/retrieval to track quality."""
        signal = 1.0 if success else 0.0
        self._retrieval_ema = (
            self._retrieval_alpha * signal
            + (1 - self._retrieval_alpha) * self._retrieval_ema
        )
        # Auto-save snapshot every SAVE_INTERVAL
        if time.time() - self._last_snapshot_time > SAVE_INTERVAL:
            snap = self.compute_snapshot()
            self._append_to_log(snap)
            self._last_snapshot_time = time.time()
            self._save_state()

    def notify_consolidation_cycle(self):
        """Called by MemoryConsolidator after each cycle."""
        self._consolidation_cycles_7d += 1
        self._save_state()

    def update_entity_baseline(self, current_count: int):
        """Called weekly to update growth rate baseline."""
        self._entity_count_last_week = current_count
        self._save_state()

    # ── Snapshot computation ──────────────────────────────────────────────────

    def compute_snapshot(self) -> MemoryHealthSnapshot:
        """Compute current health scores from live memory systems."""
        enc  = self._encoding_health()
        ret  = self._retention_health()
        cons = self._consolidation_health()
        grow = self._growth_rate()
        retr = self._retrieval_quality()

        overall = (
            WEIGHTS["encoding"]      * enc
            + WEIGHTS["retention"]   * ret
            + WEIGHTS["consolidation"] * cons
            + WEIGHTS["growth"]      * grow
            + WEIGHTS["retrieval"]   * retr
        )

        return MemoryHealthSnapshot(
            encoding_health      = round(enc, 3),
            retention_health     = round(ret, 3),
            consolidation_health = round(cons, 3),
            growth_rate          = round(grow, 3),
            retrieval_quality    = round(retr, 3),
            overall              = round(overall, 3),
        )

    def _encoding_health(self) -> float:
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
            recent = [e for e in mem.recent(n=500) if e.timestamp >= cutoff]
            return min(1.0, len(recent) / 7.0)
        except Exception:
            return 0.5

    def _retention_health(self) -> float:
        try:
            from memory.forgetting_curve import get_forgetting_curve  # type: ignore
            fc = get_forgetting_curve()
            return fc.mean_retention()
        except Exception:
            return 0.7

    def _consolidation_health(self) -> float:
        return min(1.0, self._consolidation_cycles_7d / 2.0)

    def _growth_rate(self) -> float:
        try:
            # Try both import paths — works whether called from backend/ or backend/memory/
            try:
                from unified_memory import get_unified_memory  # type: ignore
            except ImportError:
                import importlib, sys as _sys
                spec = importlib.util.spec_from_file_location(
                    "unified_memory",
                    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "unified_memory.py")
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    _sys.modules["unified_memory"] = mod
                    spec.loader.exec_module(mod)  # type: ignore
                    get_unified_memory = mod.get_unified_memory
                else:
                    return 0.5
            um = get_unified_memory()
            stats = um.get_stats() if hasattr(um, "get_stats") else {}
            current = stats.get("total_entities", 0)
            if self._entity_count_last_week == 0:
                # Seed baseline on first call
                self._entity_count_last_week = max(1, current)
                return 0.5
            ratio = current / max(1, self._entity_count_last_week)
            return min(1.0, max(0.0, (ratio - 1.0) * 5.0 + 0.5))
        except Exception:
            return 0.5

    def _retrieval_quality(self) -> float:
        return self._retrieval_ema

    # ── History ───────────────────────────────────────────────────────────────

    def _append_to_log(self, snap: MemoryHealthSnapshot):
        try:
            with HEALTH_LOG.open("a") as f:
                f.write(json.dumps(asdict(snap)) + "\n")
        except Exception:
            pass

    def get_trend(self, days: int = 30) -> List[MemoryHealthSnapshot]:
        """Return health snapshots from the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        snaps = []
        try:
            lines = HEALTH_LOG.read_text().strip().split("\n")
            for line in lines:
                if not line:
                    continue
                data = json.loads(line)
                if data.get("timestamp", "") >= cutoff:
                    snaps.append(MemoryHealthSnapshot(**data))
        except Exception:
            pass
        return snaps

    def get_improvement_report(self) -> Dict[str, Any]:
        """Week-over-week comparison of health scores."""
        trend = self.get_trend(days=14)
        if len(trend) < 2:
            current = self.compute_snapshot()
            weak_dim, weak_val = current.weakest_dimension()
            strong_dim, strong_val = current.strongest_dimension()
            return {
                "7d_delta": 0.0,
                "30d_delta": 0.0,
                "weakest_dimension": weak_dim,
                "weakest_score": round(weak_val * 100),
                "strongest_dimension": strong_dim,
                "strongest_score": round(strong_val * 100),
                "weekly_scores": [current.to_score_100()],
                "trend": "insufficient_data",
            }

        now_snaps  = trend[len(trend)//2:]
        prev_snaps = trend[:len(trend)//2]
        now_avg  = sum(s.overall for s in now_snaps)  / len(now_snaps)
        prev_avg = sum(s.overall for s in prev_snaps) / len(prev_snaps)
        delta_7d = round((now_avg - prev_avg) * 100, 1)

        current = self.compute_snapshot()
        weak_dim, weak_val   = current.weakest_dimension()
        strong_dim, strong_val = current.strongest_dimension()

        return {
            "7d_delta": delta_7d,
            "30d_delta": 0.0,   # would need 60-day log
            "weakest_dimension": weak_dim,
            "weakest_score": round(weak_val * 100),
            "strongest_dimension": strong_dim,
            "strongest_score": round(strong_val * 100),
            "weekly_scores": [round(s.overall * 100) for s in trend[-8:]],
            "trend": "improving" if delta_7d > 2 else ("declining" if delta_7d < -2 else "stable"),
        }

    # ── System prompt fragment ────────────────────────────────────────────────

    def to_system_fragment(self) -> str:
        snap = self.compute_snapshot()
        score = snap.to_score_100()
        weak, weak_val = snap.weakest_dimension()
        try:
            from memory.forgetting_curve import get_forgetting_curve  # type: ignore
            at_risk = len(get_forgetting_curve().get_at_risk_memories())
        except Exception:
            at_risk = 0
        lines = [f"[Memory Health: {score}/100]"]
        if at_risk > 0:
            lines.append(f"  ⚠ {at_risk} entities at risk of being forgotten")
        if weak_val < 0.5:
            lines.append(f"  Weakest dimension: {weak} ({round(weak_val*100)}%)")
        return "\n".join(lines) if score < 90 or at_risk > 0 else ""

    def snapshot(self) -> Dict[str, Any]:
        snap = self.compute_snapshot()
        return {
            "overall_score": snap.to_score_100(),
            "dimensions": {
                "encoding":      round(snap.encoding_health * 100),
                "retention":     round(snap.retention_health * 100),
                "consolidation": round(snap.consolidation_health * 100),
                "growth":        round(snap.growth_rate * 100),
                "retrieval":     round(snap.retrieval_quality * 100),
            },
        }


_mhm: Optional[MemoryHealthMonitor] = None

def get_memory_health_monitor() -> MemoryHealthMonitor:
    global _mhm
    if _mhm is None:
        _mhm = MemoryHealthMonitor()
    return _mhm


if __name__ == "__main__":
    mhm = get_memory_health_monitor()
    snap = mhm.compute_snapshot()
    print(f"Memory Health: {snap.to_score_100()}/100")
    print(f"Dimensions: {mhm.snapshot()}")
    print(f"Weakest: {snap.weakest_dimension()}")
    print(f"Improvement report: {mhm.get_improvement_report()}")
    print(f"System fragment: '{mhm.to_system_fragment()}'")
