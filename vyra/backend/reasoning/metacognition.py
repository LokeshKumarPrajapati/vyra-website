"""
Metacognition Layer — Phase 1.3
================================
VYRA's self-awareness engine: knows what it knows, what it doesn't,
and decides HOW to answer based on confidence.

Decision matrix:
  HIGH confidence + clear answer   → answer directly
  MEDIUM confidence               → answer with hedge ("I believe...")
  LOW confidence                  → research first, then answer
  VERY LOW / flagged gap          → admit uncertainty, offer to research
  Irreversible action detected    → require explicit user confirmation

Usage:
    meta = MetacognitionLayer()
    assessment = await meta.assess("What was the outcome of the 2025 Fed rate decision?",
                                   proposed_answer="The Fed cut rates by 0.25%")
    if assessment.should_research:
        # trigger research agent
    elif assessment.should_hedge:
        # prepend "I believe..." to answer
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from nvidia_client import get_nvidia_client, ChatResponse, ThinkingResponse  # type: ignore
except ImportError:
    def get_nvidia_client(*a, **kw): return None  # type: ignore
    class ChatResponse: pass  # type: ignore
    class ThinkingResponse: pass  # type: ignore

# ── Thresholds ────────────────────────────────────────────────────────────────

CONFIDENCE_DIRECT   = 0.85   # answer without any hedge
CONFIDENCE_HEDGE    = 0.65   # answer with "I believe / I think"
CONFIDENCE_RESEARCH = 0.45   # research before answering
CONFIDENCE_ADMIT    = 0.25   # admit gap, offer to research

# ── Patterns that flag a knowledge gap in VYRA's own response ─────────────────

GAP_PATTERNS = [
    r"i'?m not sure",
    r"i don'?t know",
    r"i'?m unable to",
    r"i cannot",
    r"i have no information",
    r"i'?m not aware",
    r"i cannot find",
    r"my knowledge",
    r"as of my (last |knowledge )?cutoff",
    r"i don'?t have access",
    r"i'?m not confident",
    r"it'?s unclear",
    r"i'?m unsure",
    r"not in my training",
    r"recent events",
    r"latest information",
    r"up-to-date",
]

IRREVERSIBLE_PATTERNS = [
    r"send.{0,20}email",
    r"delete.{0,20}file",
    r"purchase|buy|order",
    r"deploy|publish|release",
    r"write.{0,20}registry",
    r"format.{0,20}drive",
    r"transfer.{0,20}funds",
    r"submit.{0,20}form",
    r"post.{0,20}(twitter|linkedin|instagram|facebook)",
    r"git push",
    r"rm -rf",
]

TEMPORAL_PATTERNS = [
    r"\b(today|yesterday|last week|last month|this year|current|latest|recent|now)\b",
    r"\b(2025|2026)\b",
    r"right now",
    r"at the moment",
]


# ── Response class ────────────────────────────────────────────────────────────

@dataclass
class MetaAssessment:
    query: str
    proposed_answer: str

    confidence: float             # 0.0-1.0
    knowledge_gaps: List[str]     # specific gaps identified
    temporal_sensitivity: bool    # is the answer time-sensitive?
    is_irreversible_action: bool  # does it involve a dangerous action?

    # Decision flags
    should_answer_directly: bool
    should_hedge: bool
    should_research: bool
    should_admit_gap: bool
    requires_user_confirmation: bool

    hedge_prefix: str             # prepend to answer if hedging
    reasoning: str                # why this decision was made
    latency_ms: float


# ── Layer ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are VYRA's metacognitive self-evaluation layer.
Your job: estimate the confidence in a proposed answer and identify knowledge gaps.
Be accurate — overconfidence leads to errors, excessive doubt wastes time.
Output valid JSON only."""

class MetacognitionLayer:

    def __init__(self):
        self.client = get_nvidia_client()
        self._assessment_log: List[MetaAssessment] = []

    async def assess(
        self,
        query: str,
        proposed_answer: str = "",
        extra_context: str = "",
    ) -> MetaAssessment:
        t0 = time.time()

        # Quick heuristic checks (no API call needed)
        has_gap_signal    = _has_pattern(proposed_answer, GAP_PATTERNS)
        is_irreversible   = _has_pattern(query.lower(), IRREVERSIBLE_PATTERNS)
        is_temporal       = _has_pattern(query.lower() + " " + proposed_answer.lower(), TEMPORAL_PATTERNS)

        # If no answer yet or obvious gap signals → light check
        if not proposed_answer or has_gap_signal:
            confidence, gaps, reasoning = await self._evaluate_gaps(query, proposed_answer, extra_context)
        else:
            confidence, gaps, reasoning = await self._evaluate_confidence(query, proposed_answer, extra_context)

        # Decision tree
        should_answer_directly     = confidence >= CONFIDENCE_DIRECT   and not is_irreversible
        should_hedge               = CONFIDENCE_HEDGE <= confidence < CONFIDENCE_DIRECT
        should_research            = confidence < CONFIDENCE_RESEARCH  or (is_temporal and confidence < 0.8)
        should_admit_gap           = confidence < CONFIDENCE_ADMIT
        requires_user_confirmation = is_irreversible

        hedge_prefix = _build_hedge(confidence)

        assessment = MetaAssessment(
            query                      = query,
            proposed_answer            = proposed_answer,
            confidence                 = confidence,
            knowledge_gaps             = gaps,
            temporal_sensitivity       = is_temporal,
            is_irreversible_action     = is_irreversible,
            should_answer_directly     = should_answer_directly,
            should_hedge               = should_hedge,
            should_research            = should_research,
            should_admit_gap           = should_admit_gap,
            requires_user_confirmation = requires_user_confirmation,
            hedge_prefix               = hedge_prefix,
            reasoning                  = reasoning,
            latency_ms                 = (time.time() - t0) * 1000,
        )
        self._assessment_log.append(assessment)
        if len(self._assessment_log) > 100:
            self._assessment_log.pop(0)
        return assessment

    # ── Evaluators ────────────────────────────────────────────────────────────

    async def _evaluate_confidence(
        self, query: str, answer: str, context: str
    ) -> tuple[float, List[str], str]:
        prompt = (
            f"Query: {query}\n\n"
            f"Proposed answer:\n{answer}\n\n"
            f"Additional context: {context or 'none'}\n\n"
            f"Evaluate the confidence in this answer (0.0-1.0).\n"
            f"Identify specific knowledge gaps or uncertain claims.\n"
            f"JSON format: {{\"confidence\": 0.82, \"gaps\": [\"gap1\", \"gap2\"], \"reasoning\": \"...\"}}"
        )
        resp = await self.client.achat(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user",   "content": prompt}],
            model="fast",
            max_tokens=512,
            temperature=0.2,
        )
        return _parse_eval(resp.content)

    async def _evaluate_gaps(
        self, query: str, answer: str, context: str
    ) -> tuple[float, List[str], str]:
        prompt = (
            f"Query: {query}\n"
            f"Partial/uncertain answer: {answer or '(no answer yet)'}\n\n"
            f"What specific knowledge gaps prevent a confident answer?\n"
            f"What confidence is possible given available information?\n"
            f"JSON: {{\"confidence\": 0.4, \"gaps\": [\"...\"], \"reasoning\": \"...\"}}"
        )
        resp = await self.client.achat(
            [{"role": "system", "content": SYSTEM_PROMPT},
             {"role": "user",   "content": prompt}],
            model="fast",
            max_tokens=512,
            temperature=0.2,
        )
        return _parse_eval(resp.content)

    # ── Convenience ───────────────────────────────────────────────────────────

    def last_assessment(self) -> Optional[MetaAssessment]:
        return self._assessment_log[-1] if self._assessment_log else None

    async def quick_confidence(self, query: str, answer: str) -> float:
        """Fast confidence check without full assessment."""
        a = await self.assess(query, answer)
        return a.confidence


# ── Helpers ───────────────────────────────────────────────────────────────────

def _has_pattern(text: str, patterns: List[str]) -> bool:
    for p in patterns:
        if re.search(p, text, re.IGNORECASE):
            return True
    return False

def _parse_eval(raw: str) -> tuple[float, List[str], str]:
    try:
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        obj   = json.loads(raw[start:end])
        return (
            float(obj.get("confidence", 0.6)),
            list(obj.get("gaps", [])),
            str(obj.get("reasoning", "")),
        )
    except Exception:
        return 0.6, [], raw[:200]

def _build_hedge(confidence: float) -> str:
    if confidence >= CONFIDENCE_DIRECT:
        return ""
    if confidence >= CONFIDENCE_HEDGE:
        return "I believe "
    if confidence >= CONFIDENCE_RESEARCH:
        return "I think, though I'm not entirely certain, that "
    return "I'm not fully confident, but my best understanding is that "


# ── Singleton ─────────────────────────────────────────────────────────────────

_layer: Optional[MetacognitionLayer] = None

def get_metacognition() -> MetacognitionLayer:
    global _layer
    if _layer is None:
        _layer = MetacognitionLayer()
    return _layer


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    async def _test():
        meta = get_metacognition()

        # Test 1: time-sensitive question
        a1 = await meta.assess(
            query           = "What is the current Bitcoin price?",
            proposed_answer = "Bitcoin is trading around $67,000.",
        )
        print(f"[Test 1] Confidence: {a1.confidence:.2f} | Research: {a1.should_research} | Temporal: {a1.temporal_sensitivity}")

        # Test 2: irreversible action
        a2 = await meta.assess(
            query           = "Send an email to my boss resigning from my job",
            proposed_answer = "I'll send the resignation email now.",
        )
        print(f"[Test 2] Irreversible: {a2.is_irreversible_action} | Needs confirm: {a2.requires_user_confirmation}")

        # Test 3: high-confidence factual
        a3 = await meta.assess(
            query           = "What is the capital of France?",
            proposed_answer = "The capital of France is Paris.",
        )
        print(f"[Test 3] Confidence: {a3.confidence:.2f} | Direct: {a3.should_answer_directly}")

    asyncio.run(_test())
