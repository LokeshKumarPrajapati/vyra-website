"""
KVTC-Inspired Context Compressor for VYRA

Manages the context budget by ranking, prioritizing, and compressing
different context sources to maximize useful information within the
model's token window.

Instead of raw KV cache compression (which requires model internals),
this achieves similar goals at the application layer:
- Priority ranking of context pieces
- Smart budget allocation across categories
- Deduplication of overlapping information
- Optional summarization for long-tail history
"""

import time
from typing import List, Dict, Any, Optional


class ContextPiece:
    """A single piece of context to be injected into the model."""

    def __init__(self, text: str, category: str, priority: float = 1.0,
                 timestamp: float = 0.0, source: str = ""):
        self.text = text.strip()
        self.category = category  # "user_facts", "rag_result", "chat_history", "system"
        self.priority = priority  # 0.0 - 10.0, higher = more important
        self.timestamp = timestamp or time.time()
        self.source = source  # e.g. "user_memory", "rag_search", "project_manager"
        self.char_count = len(self.text)

    def __repr__(self):
        return f"<ContextPiece [{self.category}] prio={self.priority:.1f} chars={self.char_count}>"


# ── Priority Weights by Category ─────────────────────────────────────────────

CATEGORY_BASE_PRIORITY = {
    "system": 10.0,         # System status, admin status — always included
    "user_facts": 8.0,      # Structured facts/people from UserMemory — high value
    "rag_result": 5.0,      # Semantically retrieved memories — medium value
    "chat_history": 3.0,    # Raw chat history — lowest priority, most compressible
}

# Budget allocation ratios (fractions of total budget)
BUDGET_RATIOS = {
    "system": 0.10,         # 10% for system info
    "user_facts": 0.30,     # 30% for structured memory
    "rag_result": 0.35,     # 35% for RAG-retrieved context
    "chat_history": 0.25,   # 25% for raw chat history
}


class ContextCompressor:
    """
    Manages and compresses context to fit within a character budget.

    Takes context pieces from multiple sources and produces a single
    optimized context string that maximizes useful information within
    the token limit.
    """

    def __init__(self, total_budget_chars: int = 4000):
        self.total_budget = total_budget_chars

    def compress(self, pieces: List[ContextPiece]) -> str:
        """
        Take raw context pieces, rank them, allocate budget, and produce
        a compressed context string.

        Returns the final context string ready for injection.
        """
        if not pieces:
            return ""

        # 1. Score each piece
        scored = self._score_pieces(pieces)

        # 2. Allocate budget per category
        budgets = self._allocate_budgets(scored)

        # 3. Fill each category's budget with top-priority pieces
        selected = self._select_within_budget(scored, budgets)

        # 4. Build final context string
        return self._build_context_string(selected)

    def _score_pieces(self, pieces: List[ContextPiece]) -> List[ContextPiece]:
        """Score and sort pieces by effective priority."""
        now = time.time()
        for p in pieces:
            base = CATEGORY_BASE_PRIORITY.get(p.category, 1.0)
            # Recency boost: pieces from last hour get +2, last day +1
            age_hours = (now - p.timestamp) / 3600 if p.timestamp > 0 else 999
            recency_boost = 2.0 if age_hours < 1 else (1.0 if age_hours < 24 else 0.0)
            # Final score = base * custom priority + recency
            p.priority = base * (p.priority / 5.0) + recency_boost

        # Sort by priority descending
        pieces.sort(key=lambda p: p.priority, reverse=True)
        return pieces

    def _allocate_budgets(self, pieces: List[ContextPiece]) -> Dict[str, int]:
        """Allocate character budgets per category, redistributing unused budget."""
        categories_present = set(p.category for p in pieces)
        total_chars_by_cat = {}
        for p in pieces:
            total_chars_by_cat[p.category] = total_chars_by_cat.get(p.category, 0) + p.char_count

        budgets = {}
        unused = 0

        # Initial allocation
        for cat, ratio in BUDGET_RATIOS.items():
            budget = int(self.total_budget * ratio)
            if cat not in categories_present:
                unused += budget
                budgets[cat] = 0
            else:
                # Don't allocate more than what's available
                available = total_chars_by_cat.get(cat, 0)
                if available < budget:
                    unused += budget - available
                    budgets[cat] = available
                else:
                    budgets[cat] = budget

        # Redistribute unused budget to categories that need it
        if unused > 0:
            needy = [(cat, total_chars_by_cat.get(cat, 0) - budgets[cat])
                     for cat in budgets if budgets[cat] < total_chars_by_cat.get(cat, 0)]
            needy.sort(key=lambda x: x[1], reverse=True)

            for cat, deficit in needy:
                give = min(unused, deficit)
                budgets[cat] += give
                unused -= give
                if unused <= 0:
                    break

        return budgets

    def _select_within_budget(self, pieces: List[ContextPiece],
                               budgets: Dict[str, int]) -> List[ContextPiece]:
        """Select pieces within each category's budget, sorted by priority."""
        selected = []
        used = {cat: 0 for cat in budgets}

        for p in pieces:
            cat = p.category
            budget = budgets.get(cat, 0)
            if used[cat] + p.char_count <= budget:
                selected.append(p)
                used[cat] += p.char_count
            elif used[cat] < budget:
                # Truncate to fit remaining budget
                remaining = budget - used[cat]
                if remaining > 50:  # Don't bother with tiny scraps
                    truncated = ContextPiece(
                        text=p.text[:remaining - 20] + "\n... (truncated)",
                        category=p.category,
                        priority=p.priority,
                        timestamp=p.timestamp,
                        source=p.source,
                    )
                    selected.append(truncated)
                    used[cat] = budget

        return selected

    def _build_context_string(self, pieces: List[ContextPiece]) -> str:
        """Assemble selected pieces into a coherent context string."""
        if not pieces:
            return ""

        # Group by category for clean output
        grouped: Dict[str, List[ContextPiece]] = {}
        for p in pieces:
            grouped.setdefault(p.category, []).append(p)

        sections = []

        # System info first
        if "system" in grouped:
            for p in grouped["system"]:
                sections.append(p.text)

        # User facts
        if "user_facts" in grouped:
            for p in grouped["user_facts"]:
                sections.append(p.text)

        # RAG results
        if "rag_result" in grouped:
            sections.append("=== Retrieved Long-Term Memories (you remember these from past conversations) ===")
            for p in grouped["rag_result"]:
                sections.append(p.text)
            sections.append("=== End of retrieved memories ===")

        # Chat history
        if "chat_history" in grouped:
            for p in grouped["chat_history"]:
                sections.append(p.text)

        return "\n\n".join(sections)


def build_startup_context(
    system_snapshot: str = "",
    user_memory_context: str = "",
    rag_results: List[Dict[str, Any]] = None,
    chat_history_text: str = "",
    budget: int = 5000,
) -> str:
    """
    Convenience function to build the full startup context using
    the context compressor.

    Args:
        system_snapshot: Battery/CPU/time status string
        user_memory_context: Output from UserMemory.get_context_for_model()
        rag_results: List of dicts from RagMemory.search()
        chat_history_text: Formatted chat history string
        budget: Total character budget

    Returns:
        Compressed context string ready for model injection
    """
    pieces = []

    if system_snapshot:
        pieces.append(ContextPiece(
            text=f"System Status: {system_snapshot}",
            category="system",
            priority=5.0,
            source="system",
        ))

    if user_memory_context:
        pieces.append(ContextPiece(
            text=user_memory_context,
            category="user_facts",
            priority=5.0,
            source="user_memory",
        ))

    if rag_results:
        for r in rag_results:
            pieces.append(ContextPiece(
                text=r.get("text", ""),
                category="rag_result",
                priority=r.get("score", 0.5) * 10,  # Scale 0-1 score to 0-10
                timestamp=r.get("timestamp", 0.0),
                source="rag_search",
            ))

    if chat_history_text:
        pieces.append(ContextPiece(
            text=chat_history_text,
            category="chat_history",
            priority=5.0,
            source="project_manager",
        ))

    compressor = ContextCompressor(total_budget_chars=budget)
    return compressor.compress(pieces)
