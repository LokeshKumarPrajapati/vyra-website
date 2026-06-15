"""
Unified Memory Engine — Single AGI-like Memory for VYRA + JARVIS

Replaces the fragmented UserMemory + RagMemory + JarvisVault with ONE store.

Architecture:
  ┌─────────────────────────────────────────────────┐
  │              UNIFIED MEMORY                      │
  │                                                  │
  │  Layer 1: Entity Graph (people, tools, concepts) │
  │  Layer 2: Vector RAG  (FAISS + MiniLM-L6-v2)    │
  │  Layer 3: Keyword     (TF-IDF token matching)    │
  │  Layer 4: Temporal    (recency-weighted decay)    │
  │                                                  │
  │  Fusion: 0.4·semantic + 0.3·graph + 0.2·kw + 0.1│
  │                                                  │
  │  retrieve_for_llm(query) → ready-to-inject str   │
  └─────────────────────────────────────────────────┘

Storage:
  - unified_store.json   → entities, facts, relationships, preferences, metadata
  - rag_store.json       → chunk metadata  (reuse existing)
  - rag_index.faiss      → FAISS vectors   (reuse existing)

Usage:
    mem = UnifiedMemory(data_dir="data")
    await mem.store_entity("Lokesh", "person", facts=["studies engineering"])
    ctx = await mem.retrieve_for_llm("What does Lokesh study?")
    # ctx is a ready-to-inject string for the LLM system instruction
"""

import os
import json
import time
import math
import asyncio
import hashlib
from pathlib import Path
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional, Set, Tuple

import numpy as np

# ── Local imports (lazy to avoid circular) ────────────────────────────────────

_rag_memory_instance = None


def _get_rag():
    """Lazy-load RagMemory to avoid heavy imports at module level."""
    global _rag_memory_instance
    if _rag_memory_instance is None:
        from rag_memory import RagMemory  # type: ignore
        _rag_memory_instance = RagMemory(data_dir=str(Path(__file__).parent / "data"))
    return _rag_memory_instance


# ── Entity / Fact / Relationship Data Classes ────────────────────────────────

class Entity:
    """A node in the knowledge graph: person, tool, concept, project, event, place."""

    VALID_TYPES = {"person", "project", "tool", "concept", "event", "place"}

    def __init__(self, entity_id: str, name: str, entity_type: str,
                 facts: List[str] = None, notes: str = "",
                 priority: int = 3, confidence: float = 0.8,
                 created_at: float = 0.0, updated_at: float = 0.0,
                 access_count: int = 0, meta: Dict[str, Any] = None):
        self.entity_id = entity_id
        self.name = name
        self.entity_type = entity_type if entity_type in self.VALID_TYPES else "concept"
        self.facts = facts or []
        self.notes = notes
        self.priority = max(1, min(5, priority))  # 1-5
        self.confidence = max(0.0, min(1.0, confidence))
        self.created_at = created_at or time.time()
        self.updated_at = updated_at or time.time()
        self.access_count = access_count
        self.meta = meta or {}

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "facts": self.facts,
            "notes": self.notes,
            "priority": self.priority,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "meta": self.meta,
        }

    @staticmethod
    def from_dict(d: dict) -> "Entity":
        return Entity(
            entity_id=d.get("entity_id", ""),
            name=d.get("name", ""),
            entity_type=d.get("entity_type", "concept"),
            facts=d.get("facts", []),
            notes=d.get("notes", ""),
            priority=d.get("priority", 3),
            confidence=d.get("confidence", 0.8),
            created_at=d.get("created_at", 0.0),
            updated_at=d.get("updated_at", 0.0),
            access_count=d.get("access_count", 0),
            meta=d.get("meta", {}),
        )

    @staticmethod
    def make_id(name: str) -> str:
        return hashlib.md5(name.strip().lower().encode()).hexdigest()[:12]


class Relationship:
    """An edge in the knowledge graph: source --[relation]--> target."""

    def __init__(self, source_id: str, target_id: str, relation: str,
                 weight: float = 1.0, notes: str = "", created_at: float = 0.0):
        self.source_id = source_id
        self.target_id = target_id
        self.relation = relation
        self.weight = weight
        self.notes = notes
        self.created_at = created_at or time.time()

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation": self.relation,
            "weight": self.weight,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(d: dict) -> "Relationship":
        return Relationship(
            source_id=d.get("source_id", ""),
            target_id=d.get("target_id", ""),
            relation=d.get("relation", "related_to"),
            weight=d.get("weight", 1.0),
            notes=d.get("notes", ""),
            created_at=d.get("created_at", 0.0),
        )


# ── Unified Memory Store ─────────────────────────────────────────────────────

class UnifiedMemory:
    """
    Single AGI-like memory store for VYRA + JARVIS.

    Combines:
      - Entity Graph (knowledge triples: Entity --relation--> Entity)
      - Vector RAG   (FAISS semantic search over conversation history)
      - Keyword TF-IDF (token-level matching)
      - Temporal decay (recency weighting)

    Key method:
      retrieve_for_llm(query, budget) → formatted context string
    """

    # Retrieval fusion weights (Layer 5: priming boost applied additively)
    SEMANTIC_W = 0.40
    GRAPH_W    = 0.30
    KEYWORD_W  = 0.20
    RECENCY_W  = 0.10

    # Limits
    MAX_ENTITIES = 10_000
    MAX_RELATIONSHIPS = 50_000

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        if not self.data_dir.is_absolute():
            self.data_dir = Path(__file__).parent / data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.store_path = self.data_dir / "unified_store.json"

        # Core storage
        self.entities: Dict[str, Entity] = {}          # entity_id → Entity
        self.relationships: List[Relationship] = []     # All edges
        self.preferences: Dict[str, str] = {}           # key → value
        self.behavioral_rules: List[str] = []           # High-priority rules
        self.metadata: Dict[str, Any] = {
            "version": 1,
            "created_at": time.time(),
            "last_updated": 0.0,
            "migration_done": False,
        }

        # Graph adjacency (built from relationships)
        self._adj: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)  # id → [(target_id, relation, weight)]
        self._rev_adj: Dict[str, List[Tuple[str, str, float]]] = defaultdict(list)  # reverse

        # Name → entity_id lookup (case-insensitive)
        self._name_index: Dict[str, str] = {}

        # RAG memory (lazy loaded)
        self._rag = None

        # Load from disk
        self._load()

        # Auto-migrate from legacy stores if needed
        if not self.metadata.get("migration_done"):
            self._migrate_legacy()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load unified store from disk."""
        if not self.store_path.exists():
            print("[UnifiedMemory] Fresh store created.")
            return

        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.entities = {
                eid: Entity.from_dict(e) for eid, e in data.get("entities", {}).items()
            }
            self.relationships = [
                Relationship.from_dict(r) for r in data.get("relationships", [])
            ]
            self.preferences = data.get("preferences", {})
            self.behavioral_rules = data.get("behavioral_rules", [])
            self.metadata = data.get("metadata", self.metadata)

            self._rebuild_indices()

            print(f"[UnifiedMemory] ✅ Loaded {len(self.entities)} entities, "
                  f"{len(self.relationships)} relationships, "
                  f"{len(self.preferences)} preferences")
        except Exception as e:
            print(f"[UnifiedMemory] Load error: {e}")

    def save(self) -> None:
        """Persist to disk atomically."""
        self.metadata["last_updated"] = time.time()
        data = {
            "entities": {eid: e.to_dict() for eid, e in self.entities.items()},
            "relationships": [r.to_dict() for r in self.relationships],
            "preferences": self.preferences,
            "behavioral_rules": self.behavioral_rules,
            "metadata": self.metadata,
        }
        tmp = self.store_path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.store_path)
        except Exception as e:
            print(f"[UnifiedMemory] Save error: {e}")

        # Trigger background auto-sync to Obsidian
        try:
            import threading
            from obsidian_exporter import export_to_obsidian
            threading.Thread(target=export_to_obsidian, kwargs={"vault_path": None}, daemon=True).start()
        except Exception as e:
            print(f"[UnifiedMemory] Obsidian Auto-Sync error: {e}")


    def _rebuild_indices(self) -> None:
        """Rebuild adjacency lists and name index from current data."""
        self._adj.clear()
        self._rev_adj.clear()
        self._name_index.clear()

        for eid, entity in self.entities.items():
            self._name_index[entity.name.strip().lower()] = eid

        for rel in self.relationships:
            self._adj[rel.source_id].append((rel.target_id, rel.relation, rel.weight))
            self._rev_adj[rel.target_id].append((rel.source_id, rel.relation, rel.weight))

    # ── Legacy Migration ─────────────────────────────────────────────────────

    def _migrate_legacy(self) -> None:
        """Migrate data from user_memory.json into unified store."""
        legacy_path = self.data_dir / "user_memory.json"
        if not legacy_path.exists():
            self.metadata["migration_done"] = True
            self.save()
            return

        try:
            with open(legacy_path, "r", encoding="utf-8") as f:
                legacy = json.load(f)

            migrated_entities = 0
            migrated_facts = 0
            migrated_rels = 0

            display_name = legacy.get("display_name", "Lokesh")

            # ── Migrate People ──
            for p in legacy.get("important_people", []):
                name = p.get("name", "").strip()
                if not name:
                    continue
                eid = Entity.make_id(name)
                facts = []
                if p.get("notes"):
                    facts.append(p["notes"])
                entity = Entity(
                    entity_id=eid, name=name, entity_type="person",
                    facts=facts, notes=p.get("relation", ""),
                    priority=3, confidence=0.8,
                )
                self.entities[eid] = entity
                migrated_entities += 1

                # Create relationship to primary user
                if p.get("relation"):
                    primary_id = Entity.make_id(display_name)
                    if primary_id not in self.entities:
                        self.entities[primary_id] = Entity(
                            entity_id=primary_id, name=display_name,
                            entity_type="person", priority=5, confidence=1.0,
                        )
                    self.relationships.append(Relationship(
                        source_id=primary_id, target_id=eid,
                        relation=p["relation"], weight=1.0,
                    ))
                    migrated_rels += 1

            # ── Migrate Facts ──
            for f in legacy.get("important_facts", []):
                fact_text = f.get("fact", "").strip()
                if not fact_text:
                    continue
                category = f.get("category", "general")
                priority = f.get("priority", 3)
                confidence = f.get("confidence", 0.7)

                # Behavioral rules go to special list
                if category in ("self_improvement", "behavioral_rule"):
                    if fact_text not in self.behavioral_rules:
                        self.behavioral_rules.append(fact_text)
                    continue

                # Map fact to an entity or create a fact-concept
                entity_name = f.get("entity", "") or f"Facts: {category.title()}"
                eid = Entity.make_id(entity_name)

                if eid in self.entities:
                    if fact_text not in self.entities[eid].facts:
                        self.entities[eid].facts.append(fact_text)
                else:
                    etype = self._guess_entity_type(entity_name, category)
                    self.entities[eid] = Entity(
                        entity_id=eid, name=entity_name, entity_type=etype,
                        facts=[fact_text], priority=priority,
                        confidence=confidence,
                    )
                    migrated_entities += 1
                migrated_facts += 1

            # ── Migrate Relationships ──
            for r in legacy.get("relationships", []):
                a = r.get("person_a", "").strip()
                b = r.get("person_b", "").strip()
                rel = r.get("relation", "related_to")
                if a and b:
                    aid = Entity.make_id(a)
                    bid = Entity.make_id(b)
                    # Ensure entities exist
                    for name, eid in [(a, aid), (b, bid)]:
                        if eid not in self.entities:
                            self.entities[eid] = Entity(
                                entity_id=eid, name=name, entity_type="person",
                            )
                    self.relationships.append(Relationship(
                        source_id=aid, target_id=bid, relation=rel,
                        notes=r.get("notes", ""),
                    ))
                    migrated_rels += 1

            # ── Migrate Preferences ──
            self.preferences.update(legacy.get("preferences", {}))

            self._rebuild_indices()
            self.metadata["migration_done"] = True
            self.save()

            print(f"[UnifiedMemory] ✅ Migration complete: "
                  f"{migrated_entities} entities, {migrated_facts} facts, "
                  f"{migrated_rels} relationships, {len(self.preferences)} preferences, "
                  f"{len(self.behavioral_rules)} behavioral rules")

        except Exception as e:
            print(f"[UnifiedMemory] Migration error: {e}")
            import traceback; traceback.print_exc()

    def _guess_entity_type(self, name: str, category: str = "") -> str:
        """Heuristic to guess entity type from name/category."""
        nl = name.lower()
        cl = category.lower()
        if cl in ("person", "people"):
            return "person"
        if cl in ("project", "work"):
            return "project"
        if cl in ("tool", "technology", "software"):
            return "tool"
        if cl in ("event", "calendar"):
            return "event"
        if cl in ("place", "location"):
            return "place"
        # Name-based heuristics
        tool_keywords = {"chrome", "vscode", "python", "node", "git", "docker",
                         "spotify", "whatsapp", "telegram", "discord", "slack",
                         "jarvis", "vyra", "excel", "notion", "obsidian"}
        if any(kw in nl for kw in tool_keywords):
            return "tool"
        return "concept"

    # ── Entity CRUD ──────────────────────────────────────────────────────────

    def store_entity(self, name: str, entity_type: str = "concept",
                     facts: List[str] = None, notes: str = "",
                     priority: int = 3, connections: List[Dict] = None) -> str:
        """
        Add or update an entity. Merges facts if entity already exists.
        Returns the entity_id.
        """
        name = name.strip()
        if not name:
            return ""

        eid = Entity.make_id(name)
        facts = facts or []

        if eid in self.entities:
            # Merge facts
            existing = self.entities[eid]
            for f in facts:
                if f and f not in existing.facts:
                    existing.facts.append(f)
            if notes:
                existing.notes = notes
            existing.priority = max(existing.priority, priority)
            existing.updated_at = time.time()
        else:
            self.entities[eid] = Entity(
                entity_id=eid, name=name, entity_type=entity_type,
                facts=facts, notes=notes, priority=priority,
            )
            self._name_index[name.strip().lower()] = eid

        # Add connections
        if connections:
            for conn in connections:
                target_name = conn.get("name", "").strip()
                if not target_name:
                    continue
                tid = Entity.make_id(target_name)
                if tid not in self.entities:
                    self.entities[tid] = Entity(
                        entity_id=tid, name=target_name,
                        entity_type=conn.get("type", "concept"),
                    )
                    self._name_index[target_name.lower()] = tid
                rel = Relationship(
                    source_id=eid, target_id=tid,
                    relation=conn.get("relation", "related_to"),
                    weight=conn.get("weight", 1.0),
                )
                # Avoid duplicate edges
                exists = any(
                    r.source_id == rel.source_id and r.target_id == rel.target_id
                    and r.relation == rel.relation
                    for r in self.relationships
                )
                if not exists:
                    self.relationships.append(rel)
                    self._adj[eid].append((tid, rel.relation, rel.weight))
                    self._rev_adj[tid].append((eid, rel.relation, rel.weight))

        self.save()
        return eid

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get entity by ID."""
        return self.entities.get(entity_id)

    def find_entity(self, name: str) -> Optional[Entity]:
        """Find entity by name (case-insensitive)."""
        eid = self._name_index.get(name.strip().lower())
        if eid:
            return self.entities.get(eid)
        return None

    def get_connections(self, entity_id: str) -> List[Dict[str, Any]]:
        """Get all connections (outgoing + incoming) for an entity."""
        connections = []
        for tid, rel, w in self._adj.get(entity_id, []):
            target = self.entities.get(tid)
            if target:
                connections.append({
                    "entity_id": tid, "name": target.name,
                    "type": target.entity_type, "relation": rel,
                    "direction": "outgoing", "weight": w,
                })
        for sid, rel, w in self._rev_adj.get(entity_id, []):
            source = self.entities.get(sid)
            if source:
                connections.append({
                    "entity_id": sid, "name": source.name,
                    "type": source.entity_type, "relation": rel,
                    "direction": "incoming", "weight": w,
                })
        return connections

    # ── Graph Traversal ──────────────────────────────────────────────────────

    def graph_search(self, entity_ids: Set[str], max_depth: int = 2,
                     max_results: int = 20) -> List[Dict[str, Any]]:
        """
        BFS traversal from seed entities. Returns related entities + facts
        within max_depth hops, ranked by proximity and priority.
        """
        if not entity_ids:
            return []

        visited: Set[str] = set()
        results: List[Dict[str, Any]] = []
        queue: List[Tuple[str, int, float]] = []  # (entity_id, depth, score)

        for eid in entity_ids:
            if eid in self.entities:
                queue.append((eid, 0, 1.0))

        while queue and len(results) < max_results:
            queue.sort(key=lambda x: x[2], reverse=True)
            eid, depth, score = queue.pop(0)

            if eid in visited:
                continue
            visited.add(eid)

            entity = self.entities.get(eid)
            if not entity:
                continue

            results.append({
                "entity_id": eid,
                "name": entity.name,
                "type": entity.entity_type,
                "facts": entity.facts,
                "notes": entity.notes,
                "priority": entity.priority,
                "depth": depth,
                "graph_score": score,
            })

            if depth < max_depth:
                # Explore neighbors
                for tid, rel, w in self._adj.get(eid, []):
                    if tid not in visited:
                        child_score = score * 0.5 * w
                        queue.append((tid, depth + 1, child_score))
                for sid, rel, w in self._rev_adj.get(eid, []):
                    if sid not in visited:
                        child_score = score * 0.5 * w
                        queue.append((sid, depth + 1, child_score))

        return results

    def _find_mentioned_entities(self, text: str) -> Set[str]:
        """Find entity IDs mentioned in text (case-insensitive substring match)."""
        text_lower = text.lower()
        found = set()
        for name_lower, eid in self._name_index.items():
            if len(name_lower) >= 3 and name_lower in text_lower:
                found.add(eid)
        return found

    # ── RAG Integration ──────────────────────────────────────────────────────

    @property
    def rag(self):
        """Lazy-load RAG memory."""
        if self._rag is None:
            try:
                from rag_memory import RagMemory  # type: ignore
                self._rag = RagMemory(data_dir=str(self.data_dir))
                print(f"[UnifiedMemory] RAG loaded: {self._rag.get_stats()['total_chunks']} chunks")
            except Exception as e:
                print(f"[UnifiedMemory] RAG load failed: {e}")
        return self._rag

    async def store_conversation_chunk(self, text: str, speaker: str = "",
                                        category: str = "conversation",
                                        importance: int = 1) -> bool:
        """Store a conversation chunk in the RAG vector store."""
        if not self.rag:
            return False
        return await self.rag.store(
            text=text, speaker=speaker, category=category, importance=importance
        )

    async def store_conversation_batch(self, messages: List[Dict[str, str]],
                                        base_timestamp: float = 0.0) -> int:
        """Batch-store conversation messages in the RAG store."""
        if not self.rag:
            return 0
        return await self.rag.store_conversation(messages, base_timestamp=base_timestamp)

    # ── Multi-Layer Retrieval ────────────────────────────────────────────────

    async def search(self, query: str, k: int = 10,
                     entity_type: str = None) -> List[Dict[str, Any]]:
        """
        Unified search across all memory layers. Returns fused results.
        """
        results = []

        # Layer 1: Semantic RAG search
        rag_results = []
        if self.rag:
            try:
                rag_results = await self.rag.search(query=query, k=k)
            except Exception as e:
                print(f"[UnifiedMemory] RAG search error: {e}")

        for r in rag_results:
            results.append({
                "text": r.get("text", ""),
                "source": "rag",
                "score": r.get("score", 0.0) * self.SEMANTIC_W,
                "timestamp": r.get("timestamp", 0.0),
                "category": r.get("category", "conversation"),
            })

        # Layer 2: Entity graph search
        mentioned = self._find_mentioned_entities(query)
        if mentioned:
            graph_results = self.graph_search(mentioned, max_depth=2, max_results=k)
            for gr in graph_results:
                facts_text = "; ".join(gr["facts"]) if gr["facts"] else gr.get("notes", "")
                if facts_text:
                    results.append({
                        "text": f"{gr['name']} ({gr['type']}): {facts_text}",
                        "source": "graph",
                        "score": gr["graph_score"] * self.GRAPH_W * (gr["priority"] / 5.0),
                        "timestamp": 0.0,
                        "category": "entity",
                        "entity_id": gr["entity_id"],
                    })

        # Layer 3: Keyword match across entity facts
        query_lower = query.lower()
        query_tokens = set(query_lower.split())
        for eid, entity in self.entities.items():
            if entity_type and entity.entity_type != entity_type:
                continue
            # Check if any fact matches query keywords
            all_text = " ".join(entity.facts + [entity.name, entity.notes]).lower()
            overlap = len(query_tokens & set(all_text.split()))
            if overlap > 0:
                kw_score = (overlap / max(len(query_tokens), 1)) * self.KEYWORD_W
                # Check if already in results from graph search
                already = any(r.get("entity_id") == eid for r in results)
                if not already and entity.facts:
                    results.append({
                        "text": f"{entity.name}: {'; '.join(entity.facts[:3])}",
                        "source": "keyword",
                        "score": kw_score * (entity.priority / 5.0),
                        "timestamp": entity.updated_at,
                        "category": "entity",
                        "entity_id": eid,
                    })

        # Layer 4: Temporal boost
        now = time.time()
        for r in results:
            ts = r.get("timestamp", 0.0)
            if ts > 0:
                age_hours = (now - ts) / 3600
                recency = 1.0 if age_hours < 1 else (0.5 if age_hours < 24 else 0.1)
                r["score"] += recency * self.RECENCY_W

        # Layer 5: Associative priming boost (Phase 13)
        try:
            from memory.associative_indexer import get_associative_indexer
            _ai = get_associative_indexer()
            anchor_ids = [r["entity_id"] for r in results if r.get("entity_id")]
            # Build lightweight adjacency for spreading activation
            eg: Dict[str, list] = {}
            for rel in self.relationships:
                eg.setdefault(rel.source_id, []).append((rel.target_id, rel.relation_type, rel.weight))
                eg.setdefault(rel.target_id, []).append((rel.source_id, rel.relation_type, rel.weight))
            results = _ai.augment_search_results(results, anchor_ids=anchor_ids or None, entity_graph=eg)
        except Exception:
            pass

        # Sort by fused score
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:k]

    # ── LLM Context Builder ──────────────────────────────────────────────────

    async def retrieve_for_llm(self, query: str = "", budget_chars: int = 5000) -> str:
        """
        Build a complete, budget-aware context string for LLM injection.

        Combines:
          1. Behavioral rules (always included, highest priority)
          2. User preferences (always included)
          3. Entity context (people, facts — from graph search on query)
          4. RAG results (semantically relevant past conversations)

        Returns a formatted string ready to prepend to the system instruction.
        """
        sections = []
        used_chars = 0

        # ── Section 1: Behavioral Rules (always included, ~400 chars) ──
        if self.behavioral_rules:
            rules_section = "BEHAVIORAL CORRECTIONS & RULES (strictly follow — highest priority):\n"
            for rule in self.behavioral_rules[:15]:
                rules_section += f"  ⚠ {rule}\n"
            sections.append(rules_section)
            used_chars += len(rules_section)

        # ── Section 2: Preferences (always included, ~300 chars) ──
        if self.preferences:
            pref_section = "USER PREFERENCES & TOOL CHOICES (always respect):\n"
            for k, v in list(self.preferences.items())[:20]:
                pref_section += f"  • {k.replace('_', ' ')}: {v}\n"
            sections.append(pref_section)
            used_chars += len(pref_section)

        remaining = budget_chars - used_chars

        # ── Section 3: Key People (~500 chars) ──
        people = [e for e in self.entities.values() if e.entity_type == "person"]
        people.sort(key=lambda e: (e.priority, e.access_count), reverse=True)
        if people:
            people_section = "IMPORTANT PEOPLE:\n"
            for p in people[:12]:
                note = f" — {p.notes}" if p.notes else ""
                facts_str = f" | {'; '.join(p.facts[:2])}" if p.facts else ""
                people_section += f"  - {p.name}{note}{facts_str}\n"
            sections.append(people_section)
            used_chars += len(people_section)
            remaining = budget_chars - used_chars

        # ── Section 4: Query-Relevant Entity Context (~800 chars) ──
        if query and remaining > 200:
            mentioned = self._find_mentioned_entities(query)
            if mentioned:
                graph_results = self.graph_search(mentioned, max_depth=2, max_results=8)
                if graph_results:
                    ctx_section = "RELEVANT KNOWLEDGE (from memory graph):\n"
                    for gr in graph_results:
                        if not gr["facts"]:
                            continue
                        line = f"  [{gr['type']}] {gr['name']}: {'; '.join(gr['facts'][:3])}\n"
                        if used_chars + len(line) > budget_chars - 500:
                            break
                        ctx_section += line
                        used_chars += len(line)
                    if len(ctx_section) > 50:
                        sections.append(ctx_section)

        # ── Section 5: RAG Conversation Memory (~1500 chars) ──
        remaining = budget_chars - used_chars
        if query and remaining > 200 and self.rag:
            try:
                rag_results = await self.rag.search(query=query, k=5)
                if rag_results:
                    rag_section = "RETRIEVED LONG-TERM MEMORIES (from past conversations):\n"
                    for r in rag_results:
                        text = r.get("text", "")
                        score = r.get("score", 0.0)
                        if score < 0.3:  # Skip low-relevance results
                            continue
                        line = f"  - {text}\n"
                        if used_chars + len(line) > budget_chars - 100:
                            break
                        rag_section += line
                        used_chars += len(line)
                    if len(rag_section) > 60:
                        sections.append(rag_section)
            except Exception as e:
                print(f"[UnifiedMemory] RAG retrieval error: {e}")

        # ── Section 6: General Facts (~600 chars) ──
        remaining = budget_chars - used_chars
        if remaining > 200:
            # Top facts from non-person entities
            fact_entities = [
                e for e in self.entities.values()
                if e.entity_type != "person" and e.facts
            ]
            fact_entities.sort(key=lambda e: e.priority, reverse=True)
            if fact_entities:
                facts_section = "KNOWN FACTS (use naturally):\n"
                for fe in fact_entities[:10]:
                    for fact in fe.facts[:2]:
                        line = f"  - [{fe.entity_type}] {fe.name}: {fact}\n"
                        if used_chars + len(line) > budget_chars - 50:
                            break
                        facts_section += line
                        used_chars += len(line)
                if len(facts_section) > 40:
                    sections.append(facts_section)

        if not sections:
            return ""

        header = "=== UNIFIED MEMORY (survives restarts — always apply) ===\n"
        footer = "=== END UNIFIED MEMORY ===\n"
        return header + "\n".join(sections) + footer

    # ── Graph Data for Frontend D3 ───────────────────────────────────────────

    def get_graph_data(self) -> Dict[str, Any]:
        """Return node/link data for D3 force-directed graph visualization."""
        nodes = []
        for eid, entity in self.entities.items():
            nodes.append({
                "id": eid,
                "name": entity.name,
                "type": entity.entity_type,
                "facts": entity.facts,
                "notes": entity.notes,
                "priority": entity.priority,
                "factCount": len(entity.facts),
                "connectionCount": len(self._adj.get(eid, [])) + len(self._rev_adj.get(eid, [])),
            })

        links = []
        for rel in self.relationships:
            if rel.source_id in self.entities and rel.target_id in self.entities:
                links.append({
                    "source": rel.source_id,
                    "target": rel.target_id,
                    "relation": rel.relation,
                    "weight": rel.weight,
                })

        return {
            "nodes": nodes,
            "links": links,
            "stats": {
                "entities": len(self.entities),
                "relationships": len(self.relationships),
                "rag_chunks": self.rag.get_stats()["total_chunks"] if self.rag else 0,
                "preferences": len(self.preferences),
                "behavioral_rules": len(self.behavioral_rules),
            },
            "lastUpdated": self.metadata.get("last_updated", 0),
        }

    # ── Stats ────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Return comprehensive stats."""
        type_counts = defaultdict(int)
        total_facts = 0
        for e in self.entities.values():
            type_counts[e.entity_type] += 1
            total_facts += len(e.facts)

        return {
            "total_entities": len(self.entities),
            "total_relationships": len(self.relationships),
            "total_facts": total_facts,
            "total_preferences": len(self.preferences),
            "total_behavioral_rules": len(self.behavioral_rules),
            "rag_chunks": self.rag.get_stats()["total_chunks"] if self.rag else 0,
            "type_counts": dict(type_counts),
            "last_updated": self.metadata.get("last_updated", 0),
        }
