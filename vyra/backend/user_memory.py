"""
User-Centric Permanent Memory for VYRA

Provides robust, persistent storage of user-specific context:
- Important people (friends, family) and relationships
- Critical facts and preferences
- Emotional context for adaptive responses
- Auto-merged extractions from conversation (no repeated explicit instructions)

All context is seamlessly injected into the model for personalization and
conversational relevance over extended periods.
"""

import os
import json
import time
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict


@dataclass
class ImportantPerson:
    name: str
    relation: str  # e.g. "friend", "family", "mom", "colleague"
    notes: str = ""
    first_mentioned: float = 0.0
    last_mentioned: float = 0.0
    # Derived importance score for social graph / prioritization (1-5, higher = more important)
    importance: int = 3

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ImportantPerson":
        return ImportantPerson(
            name=d.get("name", ""),
            relation=d.get("relation", ""),
            notes=d.get("notes", ""),
            first_mentioned=d.get("first_mentioned", 0.0),
            last_mentioned=d.get("last_mentioned", 0.0),
        )


@dataclass
class ImportantFact:
    fact: str
    category: str  # e.g. "preference", "life_event", "constraint", "interest"
    source_timestamp: float = 0.0
    confidence: float = 1.0
    # Priority for long-term storage (1-5, 5 = critical / never forget)
    priority: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "ImportantFact":
        return ImportantFact(
            fact=d.get("fact", ""),
            category=d.get("category", "general"),
            source_timestamp=d.get("source_timestamp", 0.0),
            confidence=d.get("confidence", 1.0),
        )


@dataclass
class EmotionalContext:
    last_emotion: str = "neutral"
    last_updated: float = 0.0
    recent_emotions: List[str] = field(
        default_factory=list)  # last N for trend

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "EmotionalContext":
        return EmotionalContext(
            last_emotion=d.get("last_emotion", "neutral"),
            last_updated=d.get("last_updated", 0.0),
            recent_emotions=d.get("recent_emotions", []),
        )


@dataclass
class Relationship:
    person_a: str  # Name of first person
    person_b: str  # Name of second person
    relation: str  # e.g. "colleague", "partner", "friend"
    notes: str = ""
    start_date: str = ""  # Optional ISO date or description

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Relationship":
        return Relationship(
            person_a=d.get("person_a", ""),
            person_b=d.get("person_b", ""),
            relation=d.get("relation", ""),
            notes=d.get("notes", ""),
            start_date=d.get("start_date", ""),
        )


class UserMemory:
    """
    Permanent, user-centric memory store. Persists to JSON and provides
    context strings for the language model. Supports automatic merging
    of extracted entities and facts from conversation.
    """

    DEFAULT_PRIMARY_USER = "Lokesh"
    RECENT_EMOTIONS_SIZE = 10
    MAX_PEOPLE = 100
    MAX_FACTS = 200
    MAX_PREFERENCES = 50

    def __init__(self, data_dir: str = "data", primary_user_id: str = "Lokesh",
                 enable_rag: bool = True):
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = Path(__file__).parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.primary_user_id = primary_user_id
        self.memory_path = self.data_dir / "user_memory.json"

        self.display_name: str = primary_user_id
        self.important_people: List[ImportantPerson] = []
        self.important_facts: List[ImportantFact] = []
        self.relationships: List[Relationship] = []  # Relationship edges
        self.preferences: Dict[str, str] = {}  # key -> value
        self.emotional_context: EmotionalContext = EmotionalContext()
        self.metadata: Dict[str, Any] = {
            "first_seen": 0.0, "last_updated": 0.0, "version": 2}

        # ── RAG Memory (vector-based semantic search) ──
        self.rag_memory = None
        if enable_rag:
            try:
                from rag_memory import RagMemory  # type: ignore
                self.rag_memory = RagMemory(data_dir=str(self.data_dir))
                print(f"[UserMemory] ✅ RAG Memory initialized ({self.rag_memory.get_stats()['total_chunks']} chunks)")
            except Exception as e:
                print(f"[UserMemory] ⚠️ RAG Memory failed to init: {e}")
                self.rag_memory = None

        self._load()

    def _load(self) -> None:
        if not self.memory_path.exists():
            self.metadata["first_seen"] = time.time()
            return
        try:
            with open(self.memory_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.display_name = data.get("display_name", self.primary_user_id)
            self.important_people = [ImportantPerson.from_dict(
                p) for p in data.get("important_people", [])]
            self.relationships = [Relationship.from_dict(
                r) for r in data.get("relationships", [])]
            self.important_facts = [ImportantFact.from_dict(
                f) for f in data.get("important_facts", [])]
            self.preferences = data.get("preferences", {})
            self.emotional_context = EmotionalContext.from_dict(
                data.get("emotional_context", {}))
            self.metadata = data.get("metadata", self.metadata)
        except Exception as e:
            print(f"[UserMemory] Failed to load: {e}")

    def save(self) -> None:
        """Persist memory to disk atomically so it survives restarts safely."""
        self.metadata["last_updated"] = time.time()
        data = {
            "primary_user_id": self.primary_user_id,
            "display_name": self.display_name,
            "important_people": [p.to_dict() for p in self.important_people],
            "relationships": [r.to_dict() for r in self.relationships],
            "important_facts": [f.to_dict() for f in self.important_facts],
            "preferences": self.preferences,
            "emotional_context": self.emotional_context.to_dict(),
            "metadata": self.metadata,
        }
        tmp_path = self.memory_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            # Atomic replace on most platforms
            os.replace(tmp_path, self.memory_path)
        except Exception as e:
            print(f"[UserMemory] Failed to save: {e}")

    def get_context_for_model(self, max_chars_approx: int = 2500, include_emotion: bool = True) -> str:
        """
        Build a string to inject into the model for personalization and
        context-aware reasoning. Kept within roughly max_chars_approx.
        """
        lines = [
            "=== Persistent User Context (use for personalization; do not ask again for this) ==="]
        lines.append(f"Primary user: {self.display_name}.")

        if self.important_people:
            lines.append("Important people in their life:")
            for p in self.important_people[:20]:  # cap for token budget
                note = f" — {p.notes}" if p.notes else ""
                lines.append(f"  - {p.name} ({p.relation}){note}")
            if len(self.important_people) > 20:
                lines.append(
                    f"  ... and {len(self.important_people) - 20} more.")

        if self.relationships:
            lines.append("Known connections:")
            count = 0
            for r in self.relationships:
                if count >= 15:
                    break
                note = f" ({r.notes})" if r.notes else ""
                lines.append(
                    f"  - {r.person_a} is {r.relation} of {r.person_b}{note}")
                count += 1

        if self.important_facts:
            lines.append("Important facts (remember and use naturally):")
            # Show highest-priority facts first
            sorted_facts = sorted(
                self.important_facts,
                key=lambda f: (f.priority, f.confidence, f.source_timestamp),
                reverse=True,
            )
            for f in sorted_facts[:25]:
                lines.append(f"  - [p{f.priority}/{f.category}] {f.fact}")
            if len(self.important_facts) > 25:
                lines.append(
                    f"  ... and {len(self.important_facts) - 25} more.")

        if self.preferences:
            lines.append("Stored preferences:")
            for k, v in list(self.preferences.items())[:15]:
                lines.append(f"  - {k}: {v}")

        if include_emotion and self.emotional_context.last_emotion != "neutral":
            lines.append(
                f"Emotional context: User's recent/relevant emotion is '{self.emotional_context.last_emotion}'. "
                "Adapt tone, empathy, and support accordingly without announcing it."
            )

        lines.append("=== End of persistent user context ===")
        out = "\n".join(lines)
        if len(out) > max_chars_approx:
            out = out[: max_chars_approx - 50] + \
                "\n... (truncated)\n=== End of persistent user context ==="
        return out

    # ── RAG Integration Methods ───────────────────────────────────────────

    async def store_interaction(self, text: str, speaker: str = "",
                                 timestamp: float = 0.0,
                                 category: str = "conversation") -> bool:
        """Store a conversation chunk in the RAG vector store."""
        if not self.rag_memory:
            return False
        try:
            return await self.rag_memory.store(
                text=text, speaker=speaker,
                timestamp=timestamp, category=category
            )
        except Exception as e:
            print(f"[UserMemory] RAG store failed: {e}")
            return False

    async def store_conversation_batch(self, messages: List[Dict[str, str]],
                                        base_timestamp: float = 0.0) -> int:
        """Store a batch of conversation messages in the RAG store."""
        if not self.rag_memory:
            return 0
        try:
            return await self.rag_memory.store_conversation(
                messages, base_timestamp=base_timestamp
            )
        except Exception as e:
            print(f"[UserMemory] RAG batch store failed: {e}")
            return 0

    async def retrieve_relevant(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Retrieve semantically relevant memories from the RAG store."""
        if not self.rag_memory:
            return []
        try:
            return await self.rag_memory.search(query=query, k=k)
        except Exception as e:
            print(f"[UserMemory] RAG search failed: {e}")
            return []

    def get_rag_stats(self) -> Dict[str, Any]:
        """Get stats about the RAG memory store."""
        if not self.rag_memory:
            return {"enabled": False}
        stats = self.rag_memory.get_stats()
        stats["enabled"] = True
        return stats

    def add_person(self, name: str, relation: str, notes: str = "") -> bool:
        name = name.strip()
        if not name or not relation.strip():
            return False
        now = time.time()
        # Simple importance heuristic based on relation
        rel_lower = relation.strip().lower()
        importance = 3
        if any(k in rel_lower for k in ["wife", "husband", "partner", "girlfriend", "boyfriend"]):
            importance = 5
        elif any(k in rel_lower for k in ["mother", "father", "mom", "dad", "parent"]):
            importance = 5
        elif any(k in rel_lower for k in ["sister", "brother", "sibling", "family"]):
            importance = 4
        elif any(k in rel_lower for k in ["best friend", "bestfriend", "fiancé", "fiance"]):
            importance = 4
        for p in self.important_people:
            if p.name.lower() == name.lower():
                p.relation = relation
                p.notes = p.notes or notes
                p.last_mentioned = now
                # Update importance if this relation is stronger
                p.importance = max(p.importance, importance)
                self.save()
                return True
        if len(self.important_people) >= self.MAX_PEOPLE:
            self.important_people.pop(0)
        self.important_people.append(
            ImportantPerson(
                name=name,
                relation=relation.strip(),
                notes=notes,
                first_mentioned=now,
                last_mentioned=now,
                importance=importance,
            )
        )
        self.save()
        return True

    def add_relationship(self, person_a: str, person_b: str, relation: str, notes: str = "") -> bool:
        """Add a relationship edge between two people."""
        if not person_a or not person_b or not relation:
            return False

        # Normalize order to avoid duplicates if relation is symmetric?
        # For now, store as is, but maybe check for existing
        for r in self.relationships:
            # Check matches in either direction for undirected or just update logic
            if (r.person_a.lower() == person_a.lower() and r.person_b.lower() == person_b.lower()):
                r.relation = relation
                if notes:
                    r.notes = notes
                self.save()
                return True

        self.relationships.append(Relationship(
            person_a, person_b, relation, notes))
        self.save()
        return True

    def _base_priority_for_category(self, category: str) -> int:
        """Map fact category to a base long-term priority (1-5)."""
        c = (category or "general").lower()
        if c in {"constraint", "health", "medical", "health_routine",
                 "self_improvement", "behavioral_rule"}:
            return 5
        if c in {"life_event", "emergency", "contact", "work_project", "project", "deadline"}:
            return 4
        if c in {"preference", "goal", "routine"}:
            return 3
        if c in {"interest", "hobby"}:
            return 2
        return 1

    def add_fact(self, fact: str, category: str = "general", confidence: float = 1.0) -> bool:
        fact = fact.strip()
        if not fact:
            return False
        now = time.time()
        base_priority = self._base_priority_for_category(category)
        for f in self.important_facts:
            if f.fact.strip().lower() == fact.lower():
                f.source_timestamp = now
                f.confidence = max(f.confidence, confidence)
                # Reinforcement: bump priority up to base or slightly above
                f.priority = max(f.priority, base_priority)
                if confidence >= 0.9 and f.priority < 5:
                    f.priority += 1
                self.save()
                return True
        if len(self.important_facts) >= self.MAX_FACTS:
            # Drop the lowest-priority / oldest fact to make room
            self.important_facts.sort(
                key=lambda f: (f.priority, f.source_timestamp))
            self.important_facts.pop(0)
        # Initial priority based on category + simple keyword heuristics
        priority = base_priority
        lower_fact = fact.lower()
        if any(k in lower_fact for k in ["allergic", "allergy", "emergency", "hospital", "doctor"]):
            priority = max(priority, 5)
        if any(k in lower_fact for k in ["birthday", "anniversary"]):
            priority = max(priority, 4)
        self.important_facts.append(
            ImportantFact(
                fact=fact,
                category=category,
                source_timestamp=now,
                confidence=confidence,
                priority=priority,
            )
        )
        self.save()
        return True

    def add_preference(self, key: str, value: str) -> None:
        self.preferences[key.strip()] = value.strip()
        if len(self.preferences) > self.MAX_PREFERENCES:
            keys = list(self.preferences.keys())
            for k in keys[: len(keys) - self.MAX_PREFERENCES]:
                del self.preferences[k]
        self.save()

    def record_emotion(self, emotion: str) -> None:
        emotion = (emotion or "neutral").strip().lower()
        now = time.time()
        self.emotional_context.last_emotion = emotion
        self.emotional_context.last_updated = now
        self.emotional_context.recent_emotions.append(emotion)
        if len(self.emotional_context.recent_emotions) > self.RECENT_EMOTIONS_SIZE:
            self.emotional_context.recent_emotions.pop(0)
        self.save()

    def merge_from_extraction(self, extracted: Dict[str, Any]) -> int:
        """
        Merge LLM-extracted people, facts, and preferences into storage.
        Returns number of items merged.
        """
        count = 0
        time.time()

        for p in extracted.get("people", []):
            name = p.get("name") or p.get("name_raw")
            rel = p.get("relation") or p.get("relation_type") or "unknown"
            notes = p.get("notes") or ""
            if name and isinstance(name, str):
                if self.add_person(name, rel, notes):
                    count += 1

        for f in extracted.get("facts", []):
            fact = f.get("fact") or f.get("text")
            cat = f.get("category") or "general"
            conf = float(f.get("confidence", 1.0))
            if fact and isinstance(fact, str):
                if self.add_fact(fact, cat, conf):
                    count += 1

        for k, v in extracted.get("preferences", {}).items():
            if k and v is not None:
                self.add_preference(str(k), str(v))
                count += 1

        # Merge Relationships
        for r in extracted.get("relationships", []):
            p_a = r.get("person_a")
            p_b = r.get("person_b")
            rel = r.get("relation")
            notes = r.get("notes", "")
            if p_a and p_b and rel:
                if self.add_relationship(p_a, p_b, rel, notes):
                    count += 1

        if count > 0:
            self.save()
        return count
