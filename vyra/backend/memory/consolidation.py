"""
Memory Consolidation — Phase 3.3
===================================
Runs during idle periods (user away >2 hours) to:
  1. Compress redundant/duplicate episodes
  2. Strengthen high-importance memories (boost importance score)
  3. Decay low-importance, old memories
  4. Build new LINKS between previously unconnected episodes
  5. Extract high-level insights and push to WorldModel + UnifiedMemory

This mimics biological memory consolidation during sleep.
Safe to run as a background asyncio task alongside BackgroundExecutor.

Usage:
    consolidator = get_consolidator()
    asyncio.create_task(consolidator.run())   # in vyra.py startup
    consolidator.set_user_active(True/False)  # controlled by vyra.py
"""

import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple, Dict
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore
from memory.episodic_memory import get_episodic_memory, Episode  # type: ignore

DATA_DIR  = Path(__file__).parent.parent / "data"
IDLE_WAIT = 7200      # 2 hours idle before consolidation
CYCLE_GAP = 21600     # run at most every 6 hours


INSIGHT_SYSTEM = """You are a memory analyst. Given a list of related episodes,
extract the single most important high-level insight or pattern.
Be concise (1-2 sentences). Focus on what is most useful to remember long-term.
Output plain text only — no JSON, no bullet points."""

LINK_SYSTEM = """You are a memory analyst. Given two episode summaries,
decide if they are meaningfully related (same topic, cause-effect, same person, etc.).
Reply with ONLY "yes" or "no"."""


class MemoryConsolidator:

    def __init__(self):
        self.client         = get_nvidia_client()
        self._user_active   = False
        self._last_activity = time.time()
        self._last_run      = 0.0
        self._running       = False
        self._last_cycle_stats: dict = {}   # populated after each cycle; read by dashboard
        self._cycle_history: list = []      # last 20 cycles for ConsolidationLog

    def set_user_active(self, active: bool):
        self._user_active = active
        if active:
            self._last_activity = time.time()

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self):
        self._running = True
        print("[Consolidator] Started.")
        while self._running:
            await asyncio.sleep(300)   # check every 5 min
            idle = time.time() - self._last_activity
            since_last = time.time() - self._last_run
            if not self._user_active and idle >= IDLE_WAIT and since_last >= CYCLE_GAP:
                print("[Consolidator] Running consolidation cycle...")
                await self._cycle()
                self._last_run = time.time()

    async def _cycle(self):
        import time as _time
        t_start  = _time.time()
        mem      = get_episodic_memory()
        episodes = mem.recent(n=200)

        if len(episodes) < 5:
            return

        insights_generated = 0
        links_built = 0

        # 1. Decay old low-importance episodes
        self._decay(episodes)

        # 2. Group by topic tags → extract insights
        grouped = self._group_by_tags(episodes)
        for tag, group in grouped.items():
            if len(group) >= 3:
                insight = await self._extract_insight(group)
                if insight:
                    await mem.record(
                        content     = insight,
                        source      = "consolidation",
                        participants= ["vyra"],
                        context     = f"Consolidated insight from {len(group)} episodes about '{tag}'",
                        manual_importance = 0.85,
                    )
                    insights_generated += 1

        # 3. Build new links between semantically close episodes
        links_built = await self._build_links(episodes[:50])   # only most recent 50

        # 4. Push top insights to world model
        await self._push_to_world_model(episodes)

        duration_ms = round((_time.time() - t_start) * 1000)
        stats = {
            "timestamp": datetime.utcnow().isoformat(),
            "episodes_processed": len(episodes),
            "insights_generated": insights_generated,
            "links_built": links_built or 0,
            "duration_ms": duration_ms,
        }
        self._last_cycle_stats = stats
        self._cycle_history.append(stats)
        self._cycle_history = self._cycle_history[-20:]

        # Notify memory health monitor
        try:
            from memory.memory_health import get_memory_health_monitor  # type: ignore
            get_memory_health_monitor().notify_consolidation_cycle()
        except Exception:
            pass

        print(f"[Consolidator] Cycle complete. Episodes: {mem.count()}")

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _decay(self, episodes: List[Episode]):
        cutoff  = datetime.utcnow() - timedelta(days=90)
        con     = sqlite3.connect(get_episodic_memory().db_path)
        for ep in episodes:
            ts = datetime.fromisoformat(ep.timestamp)
            if ts < cutoff and ep.importance < 0.4:
                # Reduce importance (soft decay, don't delete)
                new_imp = max(0.05, ep.importance * 0.85)
                con.execute(
                    "UPDATE episodes SET importance=? WHERE id=?",
                    (new_imp, ep.id)
                )
        con.commit()
        con.close()

    # ── Group by tags ─────────────────────────────────────────────────────────

    def _group_by_tags(self, episodes: List[Episode]) -> Dict[str, List[Episode]]:
        groups: Dict[str, List[Episode]] = {}
        for ep in episodes:
            for tag in ep.tags:
                if tag not in groups:
                    groups[tag] = []
                groups[tag].append(ep)
        return groups

    # ── Insight extraction ────────────────────────────────────────────────────

    async def _extract_insight(self, episodes: List[Episode]) -> Optional[str]:
        summaries = "\n".join(
            f"- [{ep.timestamp[:10]}] {ep.summary}"
            for ep in sorted(episodes, key=lambda e: e.timestamp)[-10:]
        )
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": INSIGHT_SYSTEM},
                 {"role": "user",   "content": f"Episodes:\n{summaries}"}],
                model="fast",
                max_tokens=200,
                temperature=0.3,
            )
            insight = resp.content.strip()
            return insight if len(insight) > 20 else None
        except Exception:
            return None

    # ── Link building ─────────────────────────────────────────────────────────

    async def _build_links(self, episodes: List[Episode]) -> int:
        con = sqlite3.connect(get_episodic_memory().db_path)
        links_added = 0
        # Check pairs that don't already have links
        pairs: List[Tuple[Episode, Episode]] = []
        for i, ep_a in enumerate(episodes):
            for ep_b in episodes[i+1:i+6]:   # only nearby in time
                if ep_b.id not in ep_a.linked_episode_ids:
                    pairs.append((ep_a, ep_b))

        # Check pairs in parallel (batches of 5)
        for i in range(0, min(len(pairs), 20), 5):
            batch = pairs[i:i+5]
            results = await asyncio.gather(*[
                self._are_related(a, b) for a, b in batch
            ])
            for (ep_a, ep_b), related in zip(batch, results):
                if related:
                    ep_a.linked_episode_ids.append(ep_b.id)
                    ep_b.linked_episode_ids.append(ep_a.id)
                    con.execute(
                        "UPDATE episodes SET linked_ids=? WHERE id=?",
                        (json.dumps(ep_a.linked_episode_ids), ep_a.id)
                    )
                    con.execute(
                        "UPDATE episodes SET linked_ids=? WHERE id=?",
                        (json.dumps(ep_b.linked_episode_ids), ep_b.id)
                    )
                    links_added += 1
        con.commit()
        con.close()
        return links_added

    async def _are_related(self, ep_a: Episode, ep_b: Episode) -> bool:
        prompt = f"Episode A: {ep_a.summary}\nEpisode B: {ep_b.summary}"
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": LINK_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="small",
                max_tokens=5,
                temperature=0.0,
            )
            return resp.content.strip().lower().startswith("yes")
        except Exception:
            return False

    # ── Push to world model ───────────────────────────────────────────────────

    async def _push_to_world_model(self, episodes: List[Episode]):
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm = get_world_model()
            # Collect recent high-importance conversations
            top = [e for e in episodes if e.importance > 0.7 and e.source == "conversation"]
            if top:
                combined = " | ".join(e.summary for e in top[:10])
                await wm.update_from_episode(combined, source="consolidation")
        except Exception as e:
            print(f"[Consolidator] WorldModel push error: {e}")

    def stop(self):
        self._running = False


# ── Singleton ─────────────────────────────────────────────────────────────────

_consolidator: Optional[MemoryConsolidator] = None

def get_consolidator() -> MemoryConsolidator:
    global _consolidator
    if _consolidator is None:
        _consolidator = MemoryConsolidator()
    return _consolidator
