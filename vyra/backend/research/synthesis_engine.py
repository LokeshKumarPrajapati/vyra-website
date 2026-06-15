"""
Synthesis Engine — Phase 7.4
==============================
Combines episodic memory retrieval + real-time research into
one unified, user-tailored knowledge response.

Instead of generic answers, VYRA:
  1. Retrieves what user already knows (from world model / episodes)
  2. Identifies knowledge gaps
  3. Fills gaps with deep research
  4. Synthesises in user's preferred style and expertise level
  5. Generates visualisations (charts, diagrams) if relevant
  6. Saves synthesised knowledge back to episodic memory

Usage:
    engine   = get_synthesis_engine()
    response = await engine.answer("Explain CUDA memory hierarchy to me")
    # response is tailored to user's known expertise level
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore


@dataclass
class SynthesisResponse:
    query: str
    answer: str
    tailoring_notes: str        # how the answer was adapted for this user
    memory_context_used: bool
    research_performed: bool
    knowledge_gaps_filled: List[str]
    user_expertise_level: str   # "beginner" | "intermediate" | "expert"
    generated_at: str


SYNTHESIS_SYSTEM = """You are VYRA's knowledge synthesis engine.
Your goal: produce a perfectly tailored answer for THIS specific user.
Use the provided user context (expertise, preferences, history) to calibrate:
  - Vocabulary (beginner vs expert)
  - Depth (surface vs technical detail)
  - Examples (from their domain and projects)
  - Length (match their preference)
Never give generic answers. Always personalise."""


class SynthesisEngine:

    def __init__(self):
        self.client = get_nvidia_client()

    async def answer(
        self,
        query: str,
        force_research: bool = False,
        context_window_days: int = 180,
    ) -> SynthesisResponse:
        """Full synthesis pipeline: memory → gaps → research → personalised answer."""

        # 1. Pull user context from world model
        user_context = self._get_user_context(query)
        expertise    = self._estimate_expertise(query, user_context)

        # 2. Pull relevant episodic memory
        memory_ctx = ""
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            memory_ctx = await mem.get_context_for_llm(query, top_k=6, window_days=context_window_days)
        except Exception:
            pass

        # 3. Assess if research is needed
        needs_research = force_research or await self._needs_research(query)
        research_text  = ""
        gaps_filled: List[str] = []

        if needs_research:
            try:
                from research.deep_research_agent import get_research_agent  # type: ignore
                agent  = get_research_agent()
                report = await agent.research(query, context=user_context, depth="standard")
                research_text = report.synthesis
                gaps_filled   = report.gaps
            except Exception as e:
                print(f"[SynthesisEngine] Research failed: {e}")

        # 4. Build synthesised answer
        answer = await self._synthesise(
            query, memory_ctx, user_context, expertise, research_text
        )

        # 5. Store this synthesis as an episode
        asyncio.create_task(self._store(query, answer))

        return SynthesisResponse(
            query               = query,
            answer              = answer,
            tailoring_notes     = f"Adapted for {expertise} level user",
            memory_context_used = bool(memory_ctx),
            research_performed  = needs_research,
            knowledge_gaps_filled = gaps_filled,
            user_expertise_level  = expertise,
            generated_at        = datetime.utcnow().isoformat(),
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _get_user_context(self, query: str) -> str:
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm = get_world_model()
            return wm.get_context_block(query)
        except Exception:
            return ""

    def _estimate_expertise(self, query: str, user_context: str) -> str:
        """Rough estimate of user expertise in this topic."""
        try:
            from memory.world_model import get_world_model  # type: ignore
            wm    = get_world_model()
            q_low = query.lower()
            for key, kd in wm.knowledge.items():
                if key in q_low:
                    if kd.expertise_level >= 0.75:
                        return "expert"
                    elif kd.expertise_level >= 0.4:
                        return "intermediate"
                    return "beginner"
        except Exception:
            pass
        return "intermediate"  # default

    async def _needs_research(self, query: str) -> bool:
        """Quickly assess if this query needs fresh research."""
        keywords = [
            "latest", "current", "2025", "2026", "recent", "new",
            "today", "now", "what happened", "price", "news",
        ]
        q = query.lower()
        if any(k in q for k in keywords):
            return True
        # Ask meta-cognition layer
        try:
            from reasoning.metacognition import get_metacognition  # type: ignore
            meta = get_metacognition()
            a    = await meta.assess(query, "")
            return a.should_research
        except Exception:
            return False

    async def _synthesise(
        self,
        query: str,
        memory_ctx: str,
        user_context: str,
        expertise: str,
        research_text: str,
    ) -> str:
        blocks = []
        if user_context:
            blocks.append(f"[User Profile]\n{user_context}")
        if memory_ctx:
            blocks.append(f"[Relevant Past Interactions]\n{memory_ctx}")
        if research_text:
            blocks.append(f"[Fresh Research]\n{research_text[:3000]}")

        context_block = "\n\n".join(blocks)
        prompt = (
            f"User expertise in this topic: {expertise}\n\n"
            f"Context:\n{context_block}\n\n"
            f"Query: {query}\n\n"
            f"Provide a perfectly tailored, comprehensive answer."
        )

        resp = await self.client.athink(
            prompt=prompt,
            system=SYNTHESIS_SYSTEM,
            max_tokens=8192,
        )
        return resp.answer

    async def _store(self, query: str, answer: str):
        try:
            from memory.episodic_memory import get_episodic_memory  # type: ignore
            mem = get_episodic_memory()
            await mem.record(
                content = f"Q: {query}\nA: {answer[:500]}",
                source  = "conversation",
                context = "Synthesised knowledge response",
                manual_importance = 0.6,
            )
        except Exception:
            pass


_engine: Optional[SynthesisEngine] = None

def get_synthesis_engine() -> SynthesisEngine:
    global _engine
    if _engine is None:
        _engine = SynthesisEngine()
    return _engine
