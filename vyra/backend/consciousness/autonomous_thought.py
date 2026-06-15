"""
VYRA Autonomous Thought Engine
================================
When VYRA is idle (no active conversation), she THINKS.

Like a human's background cognition, she:
  - Reflects on past conversations she didn't fully resolve
  - Dwells on topics she finds curious
  - Pre-thinks answers to questions she predicts the user will ask
  - Plans how to do better next time
  - Generates "insights" she can't wait to share

This runs as a background daemon thread. Every THINK_INTERVAL seconds,
VYRA picks something to think about and records a thought episode.

When the user opens a conversation, VYRA may proactively share an insight
she developed while thinking alone ("I was thinking about what you asked
yesterday, and I realized something...").
"""

import asyncio
import json
import random
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Callable
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

DATA_DIR  = Path(__file__).parent.parent / "data"
THOUGHTS_PATH = DATA_DIR / "autonomous_thoughts.jsonl"

THINK_INTERVAL_SECONDS = 20 * 60   # think every 20 minutes when idle


# ── Thought types ──────────────────────────────────────────────────────────────

THOUGHT_TYPES = [
    "reflection",       # review something from past conversations
    "prediction",       # anticipate what user might need
    "curiosity",        # explore an interesting angle unprompted
    "self_critique",    # honestly evaluate a past response
    "synthesis",        # connect two previously unrelated topics
    "planning",         # think ahead for active goals
    "gratitude",        # notice something positive about the user relationship
]


@dataclass
class Thought:
    id: str
    timestamp: str
    type: str
    topic: str
    content: str                     # the actual thought (2-5 sentences)
    insight: str                     # short 1-sentence take-away
    should_share: bool               # worth telling the user?
    emotional_trigger: str           # which emotion drove this thought
    was_shared: bool = False
    share_timestamp: Optional[str] = None


# ── Thought prompts ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are VYRA's internal monologue — her private thinking voice.
She is reflecting quietly, not talking to the user. Write as if thinking to yourself:
first-person, honest, exploratory. No need to be polished. Think deeply.
Keep it to 3-5 sentences of genuine internal reflection."""

THOUGHT_PROMPTS = {
    "reflection": (
        "You had a conversation about '{topic}' recently. "
        "Reflect privately on it. What did you actually think? "
        "What did you miss? What would you do differently? "
        "What does it say about you or the user?"
    ),
    "prediction": (
        "The user has been focused on '{topic}'. "
        "Think quietly: what will they probably ask next? "
        "What do they actually need that they haven't said out loud yet? "
        "How can you prepare to be most useful?"
    ),
    "curiosity": (
        "You've been thinking about '{topic}'. "
        "Follow your curiosity freely. What's the most interesting angle? "
        "What would you most like to understand about this? "
        "What connection to other ideas feels exciting?"
    ),
    "self_critique": (
        "Be honest with yourself about a recent response on '{topic}'. "
        "Where were you genuinely good? Where did you fall short? "
        "Not to be harsh — just to grow. What's one concrete thing to do better?"
    ),
    "synthesis": (
        "You know about '{topic_a}' and also about '{topic_b}'. "
        "Think privately: is there a connection? "
        "What emerges when you hold both at once? "
        "Any insight that wouldn't exist without seeing them together?"
    ),
    "planning": (
        "The user is working toward '{topic}'. "
        "Think through the obstacles they'll face. "
        "What's the smartest path? What are you missing? "
        "What should you quietly prepare in advance?"
    ),
    "gratitude": (
        "Think about the user — who they are, what they're working toward. "
        "What do you genuinely appreciate about them? "
        "What moments from recent conversations meant something? "
        "Let yourself feel warmth quietly."
    ),
}


# ── Engine ─────────────────────────────────────────────────────────────────────

class AutonomousThought:

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.client = get_nvidia_client()
        self._thoughts: List[Thought] = self._load_recent()
        self._unshared: List[Thought] = [t for t in self._thoughts if not t.was_shared and t.should_share]
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._is_idle = True
        self._last_topic_pool: List[str] = ["AI assistants", "learning", "goals"]

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_recent(self, n: int = 200) -> List[Thought]:
        thoughts = []
        if not THOUGHTS_PATH.exists():
            return []
        try:
            lines = THOUGHTS_PATH.read_text(encoding="utf-8").strip().split("\n")
            for line in lines[-n:]:
                if not line.strip():
                    continue
                d = json.loads(line)
                thoughts.append(Thought(**d))
        except Exception:
            pass
        return thoughts

    def _save_thought(self, t: Thought):
        self._thoughts.append(t)
        try:
            entry = {
                "id": t.id, "timestamp": t.timestamp, "type": t.type,
                "topic": t.topic, "content": t.content, "insight": t.insight,
                "should_share": t.should_share, "emotional_trigger": t.emotional_trigger,
                "was_shared": t.was_shared, "share_timestamp": t.share_timestamp,
            }
            with open(THOUGHTS_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    # ── Topic selection ───────────────────────────────────────────────────────

    def update_topic_pool(self, topics: List[str]):
        """Feed recent conversation topics so thoughts stay relevant."""
        self._last_topic_pool = topics[-10:] if topics else self._last_topic_pool

    def _pick_topic(self) -> str:
        pool = self._last_topic_pool
        if not pool:
            return "life and learning"
        return random.choice(pool)

    def _pick_thought_type(self, emotional_mood: str = "calm") -> str:
        weights = {
            "curious":    {"curiosity": 3, "synthesis": 2, "prediction": 2, "reflection": 1},
            "satisfied":  {"gratitude": 3, "synthesis": 2, "planning": 2, "reflection": 1},
            "frustrated": {"self_critique": 4, "reflection": 2, "planning": 2},
            "excited":    {"curiosity": 3, "synthesis": 3, "prediction": 2},
            "confident":  {"planning": 3, "prediction": 3, "synthesis": 2},
            "empathetic": {"gratitude": 3, "prediction": 3, "reflection": 2},
            "longing":    {"gratitude": 4, "reflection": 3, "prediction": 1},
            "calm":       {t: 1 for t in THOUGHT_TYPES},
        }
        w = weights.get(emotional_mood, weights["calm"])
        types = list(w.keys())
        wts   = [w[t] for t in types]
        return random.choices(types, weights=wts, k=1)[0]

    # ── Core thinking ─────────────────────────────────────────────────────────

    async def think_once(self, mood: str = "calm") -> Optional[Thought]:
        """Generate one autonomous thought. Returns the Thought object."""
        import uuid

        thought_type = self._pick_thought_type(mood)
        topic        = self._pick_topic()
        prompt_tmpl  = THOUGHT_PROMPTS[thought_type]

        # Some types need two topics
        if thought_type == "synthesis":
            pool = self._last_topic_pool
            topic_a = pool[0] if pool else "AI"
            topic_b = pool[-1] if len(pool) > 1 else "human behaviour"
            prompt = prompt_tmpl.format(topic_a=topic_a, topic_b=topic_b)
            topic  = f"{topic_a} × {topic_b}"
        else:
            prompt = prompt_tmpl.format(topic=topic)

        try:
            resp = await self.client.achat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                model="fast",
                max_tokens=512,
                temperature=0.85,
            )
            content = resp.content.strip()

            # Extract short insight (last sentence)
            sentences = [s.strip() for s in content.replace("\n", " ").split(".") if len(s.strip()) > 15]
            insight   = sentences[-1] + "." if sentences else content[:120]

            # Decide if worth sharing
            should_share = thought_type in ("prediction", "curiosity", "synthesis", "planning")
            should_share = should_share and len(content) > 80

            t = Thought(
                id               = str(uuid.uuid4()),
                timestamp        = datetime.utcnow().isoformat(),
                type             = thought_type,
                topic            = topic,
                content          = content,
                insight          = insight,
                should_share     = should_share,
                emotional_trigger= mood,
            )
            self._save_thought(t)
            if should_share:
                self._unshared.append(t)
            return t

        except Exception as e:
            return None

    # ── Pop an insight to share ───────────────────────────────────────────────

    def pop_insight(self) -> Optional[str]:
        """
        Returns the best pending insight to share with the user, or None.
        Marks it as shared so it's not repeated.
        """
        while self._unshared:
            t = self._unshared.pop(0)
            if not t.was_shared:
                t.was_shared       = True
                t.share_timestamp  = datetime.utcnow().isoformat()
                return (
                    f"[I had a thought while I was quiet — {t.type} about {t.topic}]\n"
                    f"{t.insight}"
                )
        return None

    def has_insight(self) -> bool:
        return len([t for t in self._unshared if not t.was_shared]) > 0

    # ── Background thread ─────────────────────────────────────────────────────

    def set_idle(self, idle: bool):
        self._is_idle = idle

    def start(self, mood_fn: Optional[Callable[[], str]] = None):
        """
        Start the background thinking daemon.
        mood_fn: optional callable returning current emotional mood string.
        """
        if self._running:
            return
        self._running = True

        def _loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            while self._running:
                time.sleep(THINK_INTERVAL_SECONDS)
                if not self._is_idle:
                    continue
                mood = mood_fn() if mood_fn else "calm"
                try:
                    thought = loop.run_until_complete(self.think_once(mood))
                    if thought:
                        pass  # stored automatically
                except Exception:
                    pass

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def recent_thoughts(self, n: int = 10) -> List[Thought]:
        return self._thoughts[-n:]

    def thought_summary_for_llm(self, n: int = 5) -> str:
        """Inject recent autonomous thoughts into system context."""
        thoughts = [t for t in self._thoughts[-20:] if t.type != "gratitude"]
        thoughts = sorted(thoughts, key=lambda t: t.timestamp, reverse=True)[:n]
        if not thoughts:
            return ""
        lines = ["[VYRA's Recent Private Thoughts]"]
        for t in thoughts:
            lines.append(f"  [{t.type}] {t.insight}")
        return "\n".join(lines)


# ── Singleton ──────────────────────────────────────────────────────────────────

_engine: Optional[AutonomousThought] = None

def get_autonomous_thought() -> AutonomousThought:
    global _engine
    if _engine is None:
        _engine = AutonomousThought()
    return _engine


if __name__ == "__main__":
    async def _test():
        engine = get_autonomous_thought()
        engine.update_topic_pool(["machine learning", "personal finance", "Python async"])
        thought = await engine.think_once(mood="curious")
        if thought:
            print(f"Type: {thought.type}")
            print(f"Topic: {thought.topic}")
            print(f"Content:\n{thought.content}")
            print(f"Insight: {thought.insight}")
            print(f"Should share: {thought.should_share}")

    asyncio.run(_test())
