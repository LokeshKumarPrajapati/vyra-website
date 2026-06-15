"""
Episodic Memory Engine — Phase 3.1
====================================
True event-based memory — VYRA remembers *what happened*, not just facts.

Each Episode is a structured record of a real interaction or event:
  - WHO was involved
  - WHAT was said/done
  - WHEN it happened
  - WHY it mattered (emotional valence + importance)
  - OUTCOME (what resulted)
  - LINKS to related episodes

Unlike unified_memory.py (which stores facts), this stores EVENTS.
This enables: "Last time we discussed X, you said Y" and temporal reasoning.

Storage: SQLite (episodes.db) + JSON index for fast full-text search.
Embeddings: MiniLM-L6-v2 via sentence-transformers (same as existing RAG).

Usage:
    mem = get_episodic_memory()
    ep  = await mem.record("User asked about crypto, I gave portfolio advice")
    results = await mem.search("What did we say about Bitcoin last month?", top_k=5)
    ctx = await mem.get_context_for_llm("crypto discussion", window_days=90)
"""

import asyncio
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

# Lazy embedding import
_embedder = None
def _get_embedder():
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            pass
    return _embedder

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    _NUMPY = False

DATA_DIR = Path(__file__).parent.parent / "data"


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class Episode:
    id: str
    timestamp: str                 # ISO UTC
    summary: str                   # 1-2 sentence digest
    full_content: str              # raw transcript or description
    participants: List[str]        # ["user", "vyra", "John"]
    context: str                   # what was happening at the time
    outcome: str                   # what resulted from this event
    emotional_valence: float       # -1.0 (negative) to +1.0 (positive)
    importance: float              # 0.0-1.0 auto-computed
    source: str                    # "conversation" | "observation" | "research" | "goal"
    tags: List[str] = field(default_factory=list)
    linked_episode_ids: List[str]  = field(default_factory=list)
    embedding: Optional[List[float]] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()

    def to_context_str(self) -> str:
        """Format for injection into LLM context."""
        ts = self.timestamp[:10]
        return (
            f"[{ts}] {self.summary}"
            + (f" Outcome: {self.outcome}" if self.outcome else "")
        )


# ── Engine ────────────────────────────────────────────────────────────────────

SUMMARISE_SYSTEM = """You extract a concise episode record from a conversation or event.
Output valid JSON only. Fields: summary (1-2 sentences), participants (list of strings),
context (what was happening), outcome (what resulted), emotional_valence (-1.0 to 1.0),
importance (0.0 to 1.0), tags (list of topic strings)."""


class EpisodicMemory:

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path  = data_dir / "episodes.db"
        self.client   = get_nvidia_client()
        self._init_db()

    # ── DB ────────────────────────────────────────────────────────────────────

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                timestamp TEXT,
                summary TEXT,
                full_content TEXT,
                participants TEXT,
                context TEXT,
                outcome TEXT,
                emotional_valence REAL,
                importance REAL,
                source TEXT,
                tags TEXT,
                linked_ids TEXT,
                embedding BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_timestamp ON episodes(timestamp);
            CREATE INDEX IF NOT EXISTS idx_importance ON episodes(importance);
            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                id UNINDEXED,
                summary,
                full_content,
                tags
            );
        """)
        con.commit()
        con.close()

    def _insert(self, ep: Episode):
        import pickle
        emb_blob = pickle.dumps(ep.embedding) if ep.embedding else None
        con = sqlite3.connect(self.db_path)
        con.execute("""
            INSERT OR REPLACE INTO episodes
            (id,timestamp,summary,full_content,participants,context,outcome,
             emotional_valence,importance,source,tags,linked_ids,embedding)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            ep.id, ep.timestamp, ep.summary, ep.full_content,
            json.dumps(ep.participants), ep.context, ep.outcome,
            ep.emotional_valence, ep.importance, ep.source,
            json.dumps(ep.tags), json.dumps(ep.linked_episode_ids),
            emb_blob,
        ))
        # FTS index
        con.execute("""
            INSERT OR REPLACE INTO episodes_fts(id, summary, full_content, tags)
            VALUES (?, ?, ?, ?)
        """, (ep.id, ep.summary, ep.full_content[:2000], " ".join(ep.tags)))
        con.commit()
        con.close()

    def _row_to_episode(self, row) -> Episode:
        import pickle
        (eid, ts, summary, full_content, participants, context, outcome,
         valence, importance, source, tags, linked, emb_blob) = row
        emb = pickle.loads(emb_blob) if emb_blob else None
        return Episode(
            id=eid, timestamp=ts, summary=summary, full_content=full_content,
            participants=json.loads(participants or "[]"),
            context=context or "", outcome=outcome or "",
            emotional_valence=valence or 0.0, importance=importance or 0.5,
            source=source or "conversation",
            tags=json.loads(tags or "[]"),
            linked_episode_ids=json.loads(linked or "[]"),
            embedding=emb,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    async def record(
        self,
        content: str,
        source: str = "conversation",
        participants: Optional[List[str]] = None,
        context: str = "",
        manual_importance: Optional[float] = None,
    ) -> Episode:
        """
        Record a new episode. Automatically extracts summary, tags,
        valence, importance using the LLM and computes an embedding.
        """
        meta  = await self._extract_meta(content, context)
        embed = self._embed(meta.get("summary", content[:200]))

        ep = Episode(
            id                 = str(uuid.uuid4()),
            timestamp          = datetime.utcnow().isoformat(),
            summary            = meta.get("summary", content[:120]),
            full_content       = content,
            participants       = participants or meta.get("participants", ["user", "vyra"]),
            context            = context or meta.get("context", ""),
            outcome            = meta.get("outcome", ""),
            emotional_valence  = float(meta.get("emotional_valence", 0.0)),
            importance         = manual_importance or float(meta.get("importance", 0.5)),
            source             = source,
            tags               = meta.get("tags", []),
            embedding          = embed,
        )
        self._insert(ep)
        return ep

    async def search(
        self,
        query: str,
        top_k: int = 5,
        days_back: Optional[int] = None,
        min_importance: float = 0.0,
    ) -> List[Episode]:
        """Hybrid search: FTS + semantic similarity."""
        fts_results = self._fts_search(query, top_k * 2, days_back, min_importance)
        sem_results = self._semantic_search(query, top_k * 2, days_back)
        merged      = _merge_and_rank(fts_results, sem_results, query)
        return merged[:top_k]

    async def get_context_for_llm(
        self,
        query: str,
        top_k: int = 8,
        window_days: int = 365,
        min_importance: float = 0.2,
    ) -> str:
        """
        Returns a ready-to-inject string for LLM context.
        Called by vyra.py before every LLM call.
        """
        episodes = await self.search(query, top_k=top_k, days_back=window_days, min_importance=min_importance)
        if not episodes:
            return ""
        lines = ["[Relevant Past Events]"]
        for ep in episodes:
            lines.append("  " + ep.to_context_str())
        return "\n".join(lines)

    def recent(self, n: int = 20, source: Optional[str] = None) -> List[Episode]:
        con  = sqlite3.connect(self.db_path)
        if source:
            rows = con.execute(
                "SELECT * FROM episodes WHERE source=? ORDER BY timestamp DESC LIMIT ?",
                (source, n)
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT ?", (n,)
            ).fetchall()
        con.close()
        return [self._row_to_episode(r) for r in rows]

    def count(self) -> int:
        con = sqlite3.connect(self.db_path)
        n   = con.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
        con.close()
        return n

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _extract_meta(self, content: str, context: str) -> Dict[str, Any]:
        prompt = (
            f"Event/conversation:\n{content[:3000]}\n\n"
            f"Context: {context or 'none'}\n\n"
            f"Extract a structured episode record. JSON only."
        )
        try:
            resp = await self.client.achat(
                [{"role": "system", "content": SUMMARISE_SYSTEM},
                 {"role": "user",   "content": prompt}],
                model="fast",
                max_tokens=512,
                temperature=0.2,
            )
            raw   = resp.content.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return {
                "summary": content[:120],
                "participants": ["user", "vyra"],
                "context": context,
                "outcome": "",
                "emotional_valence": 0.0,
                "importance": 0.5,
                "tags": [],
            }

    def _embed(self, text: str) -> Optional[List[float]]:
        embedder = _get_embedder()
        if embedder is None or not _NUMPY:
            return None
        try:
            vec = embedder.encode([text], normalize_embeddings=True)[0]
            return vec.tolist()
        except Exception:
            return None

    def _fts_search(
        self, query: str, n: int, days_back: Optional[int], min_importance: float
    ) -> List[Episode]:
        con  = sqlite3.connect(self.db_path)
        date_filter = ""
        params: list = [query, n]
        if days_back:
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
            date_filter = "AND e.timestamp >= ?"
            params.insert(1, cutoff)
        rows = con.execute(f"""
            SELECT e.* FROM episodes e
            JOIN episodes_fts f ON e.id = f.id
            WHERE episodes_fts MATCH ?
            {date_filter}
            AND e.importance >= {min_importance}
            ORDER BY e.importance DESC, e.timestamp DESC
            LIMIT ?
        """, params).fetchall()
        con.close()
        return [self._row_to_episode(r) for r in rows]

    def _semantic_search(
        self, query: str, n: int, days_back: Optional[int]
    ) -> List[Episode]:
        if not _NUMPY:
            return []
        embedder = _get_embedder()
        if embedder is None:
            return []
        try:
            import pickle
            q_vec = embedder.encode([query], normalize_embeddings=True)[0]
            con   = sqlite3.connect(self.db_path)
            date_filter = ""
            params: list = []
            if days_back:
                cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
                date_filter = f"WHERE timestamp >= '{cutoff}'"
            rows = con.execute(
                f"SELECT * FROM episodes {date_filter} ORDER BY importance DESC LIMIT 200"
            ).fetchall()
            con.close()
            scored = []
            for r in rows:
                ep = self._row_to_episode(r)
                if ep.embedding:
                    ev = np.array(ep.embedding, dtype="float32")
                    score = float(np.dot(q_vec, ev))
                    scored.append((score, ep))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [ep for _, ep in scored[:n]]
        except Exception:
            return []


def _merge_and_rank(
    fts: List[Episode], sem: List[Episode], query: str
) -> List[Episode]:
    seen = set()
    merged = []
    for ep in fts + sem:
        if ep.id not in seen:
            seen.add(ep.id)
            merged.append(ep)
    merged.sort(key=lambda e: e.importance, reverse=True)
    return merged


# ── Singleton ─────────────────────────────────────────────────────────────────

_mem: Optional[EpisodicMemory] = None

def get_episodic_memory() -> EpisodicMemory:
    global _mem
    if _mem is None:
        _mem = EpisodicMemory()
    return _mem


if __name__ == "__main__":
    async def _test():
        mem = get_episodic_memory()
        ep  = await mem.record(
            content="User Lokesh asked about Python async patterns. "
                    "VYRA explained asyncio event loops and gather(). "
                    "User said it was exactly what he needed.",
            source="conversation",
            context="Lokesh is building a backend for his AI assistant",
        )
        print(f"Recorded: {ep.summary}")
        print(f"Tags: {ep.tags}  Importance: {ep.importance:.2f}")

        ctx = await mem.get_context_for_llm("asyncio Python")
        print(f"\nContext block:\n{ctx}")
        print(f"\nTotal episodes: {mem.count()}")

    asyncio.run(_test())
