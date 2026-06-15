"""
VYRA Working Memory
====================
Human working memory: 4-7 "slots" of currently-active information.
This is what VYRA is CONSCIOUSLY HOLDING in her mind right now —
separate from long-term episodic storage.

Based on Baddeley's model + Miller's 7±2:
  - 6 active slots (cognitive chunks)
  - Each slot has an activation strength that decays
  - New items displace the weakest-activated items
  - Working memory = the context for ALL reasoning

What lives here:
  - The current task / user request
  - Active sub-goals
  - Recently retrieved memory fragments
  - Pending decisions
  - Emotional context cues
  - Predictions about what user needs next

Working memory is injected into EVERY system prompt — it's VYRA's
"what I'm currently focused on", which makes responses deeply contextual.

Human parallel: this is what you "hold in mind" during a complex task.
Without it, every response starts from scratch. With it, VYRA truly
carries context across the full conversation flow.
"""

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DATA_DIR = Path(__file__).parent.parent / "data"

SLOT_CAPACITY    = 6       # Miller's 7±2
DECAY_RATE       = 0.08    # activation lost per minute
REHEARSAL_BOOST  = 0.3     # activation gain when slot is accessed again


# ── Memory chunk ──────────────────────────────────────────────────────────────

@dataclass
class MemoryChunk:
    id: str
    content: str             # the information itself
    category: str            # "task" | "subgoal" | "memory_fragment" | "emotion" | "prediction" | "fact"
    activation: float        # 0.0–1.0 (how strongly active right now)
    created_at: float        # Unix timestamp
    last_accessed: float
    source: str              # "user_input" | "episodic_recall" | "inference" | "goal"
    tags: List[str] = field(default_factory=list)

    def decay(self, now: float) -> float:
        """Apply time-based decay to activation. Returns new activation."""
        elapsed_minutes = (now - self.last_accessed) / 60.0
        self.activation = max(0.0, self.activation - DECAY_RATE * elapsed_minutes)
        return self.activation

    def rehearse(self):
        """Accessing a slot strengthens it (rehearsal effect)."""
        self.activation = min(1.0, self.activation + REHEARSAL_BOOST)
        self.last_accessed = time.time()

    def to_context_str(self) -> str:
        cat_icon = {
            "task":             "🎯",
            "subgoal":          "→",
            "memory_fragment":  "📌",
            "emotion":          "💭",
            "prediction":       "🔮",
            "fact":             "📋",
        }.get(self.category, "•")
        return f"{cat_icon} [{self.category}] {self.content}"


# ── Working Memory ────────────────────────────────────────────────────────────

class WorkingMemory:
    """
    6-slot priority buffer — VYRA's "what I'm thinking about right now".

    Items with highest activation stay. Weaker items are displaced.
    Automatic decay ensures stale items fade out naturally.
    """

    PERSIST_PATH = DATA_DIR / "working_memory.json"

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._slots: List[MemoryChunk] = self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> List[MemoryChunk]:
        try:
            items = json.loads(self.PERSIST_PATH.read_text())
            chunks = []
            now = time.time()
            for d in items:
                c = MemoryChunk(**d)
                c.decay(now)   # apply offline decay
                if c.activation > 0.05:
                    chunks.append(c)
            return sorted(chunks, key=lambda x: -x.activation)[:SLOT_CAPACITY]
        except Exception:
            return []

    def save(self):
        try:
            self.PERSIST_PATH.write_text(
                json.dumps([asdict(c) for c in self._slots], indent=2)
            )
        except Exception:
            pass

    # ── Core operations ───────────────────────────────────────────────────────

    def load(
        self,
        content: str,
        category: str = "task",
        activation: float = 0.8,
        source: str = "user_input",
        tags: Optional[List[str]] = None,
    ) -> MemoryChunk:
        """
        Load a new chunk into working memory.
        If content already exists → rehearse it instead.
        If full → displace weakest item.
        """
        import uuid
        now = time.time()
        self._apply_decay()

        # Check for existing similar chunk
        for chunk in self._slots:
            if chunk.content[:80] == content[:80] or (tags and any(t in chunk.tags for t in (tags or []))):
                chunk.rehearse()
                self.save()
                return chunk

        new_chunk = MemoryChunk(
            id            = str(uuid.uuid4())[:8],
            content       = content,
            category      = category,
            activation    = activation,
            created_at    = now,
            last_accessed = now,
            source        = source,
            tags          = tags or [],
        )

        if len(self._slots) >= SLOT_CAPACITY:
            # Displace the weakest slot
            self._slots.sort(key=lambda x: x.activation)
            self._slots.pop(0)

        self._slots.append(new_chunk)
        self._slots.sort(key=lambda x: -x.activation)
        self.save()
        return new_chunk

    def access(self, chunk_id: str) -> Optional[MemoryChunk]:
        """Access a chunk by ID — rehearses it (strengthens activation)."""
        for c in self._slots:
            if c.id == chunk_id:
                c.rehearse()
                self.save()
                return c
        return None

    def clear_category(self, category: str):
        """Remove all chunks of a given category (e.g., after task completes)."""
        self._slots = [c for c in self._slots if c.category != category]
        self.save()

    def active_chunks(self, min_activation: float = 0.1) -> List[MemoryChunk]:
        """Return chunks above activation threshold, sorted by strength."""
        self._apply_decay()
        return [c for c in sorted(self._slots, key=lambda x: -x.activation)
                if c.activation >= min_activation]

    def get_by_category(self, category: str) -> List[MemoryChunk]:
        return [c for c in self._slots if c.category == category]

    # ── Decay ─────────────────────────────────────────────────────────────────

    def _apply_decay(self):
        now = time.time()
        for c in self._slots:
            c.decay(now)
        self._slots = [c for c in self._slots if c.activation > 0.02]
        self._slots.sort(key=lambda x: -x.activation)

    # ── Context injection ─────────────────────────────────────────────────────

    def to_system_fragment(self) -> str:
        active = self.active_chunks(min_activation=0.15)
        if not active:
            return ""
        lines = ["[VYRA's Active Working Memory — what I'm currently holding in mind]"]
        for c in active[:6]:
            strength = "■■■" if c.activation > 0.7 else "■■□" if c.activation > 0.4 else "■□□"
            lines.append(f"  {strength} {c.to_context_str()}")
        return "\n".join(lines)

    def current_task(self) -> Optional[str]:
        tasks = self.get_by_category("task")
        return tasks[0].content if tasks else None

    def snapshot(self) -> Dict[str, Any]:
        active = self.active_chunks()
        return {
            "slots_used": len(active),
            "slot_capacity": SLOT_CAPACITY,
            "active": [{"category": c.category, "content": c.content[:60],
                        "activation": round(c.activation, 2)} for c in active],
        }


# ── Singleton ──────────────────────────────────────────────────────────────────

_wm: Optional[WorkingMemory] = None

def get_working_memory() -> WorkingMemory:
    global _wm
    if _wm is None:
        _wm = WorkingMemory()
    return _wm


if __name__ == "__main__":
    wm = get_working_memory()
    wm.load("Help user build a portfolio website", category="task", activation=0.95)
    wm.load("User prefers React over Vue", category="fact", activation=0.7)
    wm.load("User seemed tired earlier", category="emotion", activation=0.5)
    wm.load("They'll probably need deployment help next", category="prediction", activation=0.6)
    print(wm.to_system_fragment())
    print("\nSnapshot:", wm.snapshot())
