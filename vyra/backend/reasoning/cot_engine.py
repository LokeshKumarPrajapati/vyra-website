"""
Chain-of-Thought (CoT) Engine — Phase 1.1
==========================================
Wraps every complex query through a 5-stage reasoning loop:
  1. Decompose → break task into sub-questions
  2. Research  → gather context per sub-question
  3. Synthesize → build intermediate answer
  4. Critique   → adversarial self-check
  5. Revise     → final polished response

Uses NVIDIA Qwen 3.5 122B with built-in thinking tokens.
Simple queries bypass CoT (latency budget).

Usage:
    engine = ChainOfThoughtEngine()
    trace  = await engine.reason("Explain quantum entanglement simply")
    print(trace.final_answer)
    print(trace.thinking_summary)
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

# ── Complexity classifier ─────────────────────────────────────────────────────

SIMPLE_TRIGGERS = {
    "what time", "open ", "play ", "volume", "turn on", "turn off",
    "weather", "remind me", "set timer", "calculate", "convert",
    "search for", "who is", "define ", "translate",
}

def _is_simple(query: str) -> bool:
    q = query.lower().strip()
    if len(q) < 30:
        return True
    return any(q.startswith(t) for t in SIMPLE_TRIGGERS)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SubQuestion:
    question: str
    answer: str = ""
    confidence: float = 1.0

@dataclass
class ReasoningTrace:
    query: str
    sub_questions: List[SubQuestion]
    raw_thinking: str          # full <think> block from Qwen
    thinking_summary: str      # 2-3 sentence digest for UI
    initial_answer: str
    critique: str
    final_answer: str
    was_revised: bool
    confidence: float
    latency_ms: float
    model_used: str
    bypassed_cot: bool = False  # True if simple query shortcut was taken


# ── Engine ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are VYRA's internal reasoning core — an advanced analytical engine.
Your job is to reason carefully, identify flaws in your own thinking, and produce
trustworthy answers. Always be honest about uncertainty."""

class ChainOfThoughtEngine:
    """
    5-stage CoT reasoning over NVIDIA Qwen 3.5 122B.
    Automatically skips to fast-path for simple queries.
    """

    def __init__(self, complexity_threshold: int = 50):
        self.client = get_nvidia_client()
        self.complexity_threshold = complexity_threshold
        self._trace_log: List[ReasoningTrace] = []   # in-memory log (last 50)

    # ── Public API ────────────────────────────────────────────────────────────

    async def reason(
        self,
        query: str,
        context: str = "",
        force_deep: bool = False,
    ) -> ReasoningTrace:
        """
        Main entry point.  Returns a ReasoningTrace with the final_answer.
        """
        t0 = time.time()

        if not force_deep and _is_simple(query):
            return await self._fast_path(query, context, t0)

        return await self._deep_path(query, context, t0)

    def get_last_trace(self) -> Optional[ReasoningTrace]:
        return self._trace_log[-1] if self._trace_log else None

    def get_trace_log(self, last_n: int = 10) -> List[ReasoningTrace]:
        return self._trace_log[-last_n:]

    # ── Fast path (simple queries) ────────────────────────────────────────────

    async def _fast_path(self, query: str, context: str, t0: float) -> ReasoningTrace:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context:
            msgs.append({"role": "system", "content": f"Context:\n{context}"})
        msgs.append({"role": "user", "content": query})

        resp = await self.client.achat(msgs, model="fast", max_tokens=1024)
        trace = ReasoningTrace(
            query          = query,
            sub_questions  = [],
            raw_thinking   = "",
            thinking_summary = "",
            initial_answer = resp.content,
            critique       = "",
            final_answer   = resp.content,
            was_revised    = False,
            confidence     = 0.9,
            latency_ms     = (time.time() - t0) * 1000,
            model_used     = resp.model,
            bypassed_cot   = True,
        )
        self._store_trace(trace)
        return trace

    # ── Deep path (5-stage CoT) ───────────────────────────────────────────────

    async def _deep_path(self, query: str, context: str, t0: float) -> ReasoningTrace:
        # Stage 1 — Decompose
        sub_qs = await self._decompose(query, context)

        # Stage 2 — Research each sub-question (parallel for speed)
        sub_qs = await self._research_parallel(sub_qs, context)

        # Stage 3 — Synthesize with full thinking mode
        think_resp = await self._synthesize(query, sub_qs, context)

        # Stage 4 — Critique
        critique, confidence = await self._critique(query, think_resp.answer)

        # Stage 5 — Revise if critique found issues
        final_answer = think_resp.answer
        was_revised  = False
        if _critique_is_negative(critique):
            final_answer = await self._revise(query, think_resp.answer, critique)
            was_revised  = True

        trace = ReasoningTrace(
            query            = query,
            sub_questions    = sub_qs,
            raw_thinking     = think_resp.thinking,
            thinking_summary = _summarise_thinking(think_resp.thinking),
            initial_answer   = think_resp.answer,
            critique         = critique,
            final_answer     = final_answer,
            was_revised      = was_revised,
            confidence       = confidence,
            latency_ms       = (time.time() - t0) * 1000,
            model_used       = think_resp.model,
        )
        self._store_trace(trace)
        return trace

    # ── Stage implementations ─────────────────────────────────────────────────

    async def _decompose(self, query: str, context: str) -> List[SubQuestion]:
        prompt = (
            f"Break the following request into 2-4 clear sub-questions "
            f"that, when answered, will fully address it.\n\n"
            f"Request: {query}\n\n"
            f"Respond with a JSON array of strings only. Example:\n"
            f'["What is X?", "How does Y work?", "What are the implications?"]'
        )
        resp = await self.client.achat(
            [{"role": "user", "content": prompt}],
            model="fast",
            max_tokens=512,
            temperature=0.3,
        )
        try:
            raw = resp.content.strip()
            # Extract JSON array even if model adds extra text
            start = raw.find("[")
            end   = raw.rfind("]") + 1
            questions: List[str] = json.loads(raw[start:end])
            return [SubQuestion(question=q) for q in questions[:4]]
        except Exception:
            return [SubQuestion(question=query)]

    async def _research_one(self, sq: SubQuestion, context: str) -> SubQuestion:
        prompt = f"Answer concisely (2-4 sentences): {sq.question}"
        if context:
            prompt = f"Context: {context}\n\n{prompt}"
        resp = await self.client.achat(
            [{"role": "user", "content": prompt}],
            model="fast",
            max_tokens=512,
        )
        sq.answer = resp.content.strip()
        return sq

    async def _research_parallel(self, sub_qs: List[SubQuestion], context: str) -> List[SubQuestion]:
        tasks = [self._research_one(sq, context) for sq in sub_qs]
        return list(await asyncio.gather(*tasks))

    async def _synthesize(
        self, query: str, sub_qs: List[SubQuestion], context: str
    ) -> ThinkingResponse:
        qa_block = "\n".join(
            f"Q{i+1}: {sq.question}\nA{i+1}: {sq.answer}"
            for i, sq in enumerate(sub_qs)
        )
        prompt = (
            f"Original request: {query}\n\n"
            f"Sub-question research:\n{qa_block}\n\n"
            f"Now synthesize a complete, accurate, and well-structured answer "
            f"to the original request using the sub-question research above."
        )
        if context:
            prompt = f"Context about the user:\n{context}\n\n{prompt}"

        return await self.client.athink(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            temperature=0.5,
            max_tokens=8192,
        )

    async def _critique(self, query: str, answer: str) -> tuple[str, float]:
        prompt = (
            f"Original question: {query}\n\n"
            f"Proposed answer:\n{answer}\n\n"
            f"Critically evaluate this answer:\n"
            f"1. Is it factually accurate? Any likely errors?\n"
            f"2. Does it fully address the question?\n"
            f"3. Is there anything misleading or missing?\n"
            f"4. Rate your confidence in the answer: 0.0 to 1.0\n\n"
            f"Reply as JSON: {{\"issues\": \"...\", \"confidence\": 0.85}}"
        )
        resp = await self.client.achat(
            [{"role": "user", "content": prompt}],
            model="fast",
            max_tokens=512,
            temperature=0.3,
        )
        try:
            raw = resp.content.strip()
            start = raw.find("{")
            end   = raw.rfind("}") + 1
            obj = json.loads(raw[start:end])
            return obj.get("issues", ""), float(obj.get("confidence", 0.8))
        except Exception:
            return resp.content, 0.75

    async def _revise(self, query: str, answer: str, critique: str) -> str:
        prompt = (
            f"Question: {query}\n\n"
            f"Initial answer:\n{answer}\n\n"
            f"Critique:\n{critique}\n\n"
            f"Write an improved answer that addresses the critique. "
            f"Be accurate and concise."
        )
        resp = await self.client.achat(
            [{"role": "user", "content": prompt}],
            model="thinking",
            max_tokens=4096,
            temperature=0.4,
        )
        return resp.content.strip()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _store_trace(self, trace: ReasoningTrace):
        self._trace_log.append(trace)
        if len(self._trace_log) > 50:
            self._trace_log.pop(0)


# ── Utility helpers ───────────────────────────────────────────────────────────

def _critique_is_negative(critique: str) -> bool:
    negative_words = ["error", "incorrect", "inaccurate", "missing", "wrong",
                      "incomplete", "misleading", "false", "flawed"]
    cl = critique.lower()
    return any(w in cl for w in negative_words) and len(critique) > 30

def _summarise_thinking(thinking: str) -> str:
    if not thinking:
        return ""
    # Take first 3 meaningful sentences from the thinking block
    sentences = [s.strip() for s in thinking.replace("\n", " ").split(".") if len(s.strip()) > 20]
    return ". ".join(sentences[:3]) + "." if sentences else thinking[:300]


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[ChainOfThoughtEngine] = None

def get_cot_engine() -> ChainOfThoughtEngine:
    global _engine
    if _engine is None:
        _engine = ChainOfThoughtEngine()
    return _engine


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def _test():
        engine = get_cot_engine()
        trace  = await engine.reason(
            "What are the key differences between transformer and mamba architectures, "
            "and when would you choose one over the other for a production system?"
        )
        print(f"\n=== REASONING TRACE ===")
        print(f"Query: {trace.query}")
        print(f"Sub-questions: {[sq.question for sq in trace.sub_questions]}")
        print(f"Thinking: {trace.thinking_summary}")
        print(f"Revised: {trace.was_revised}  |  Confidence: {trace.confidence:.2f}")
        print(f"Latency: {trace.latency_ms:.0f}ms")
        print(f"\n=== FINAL ANSWER ===\n{trace.final_answer}")

    asyncio.run(_test())
