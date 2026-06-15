"""
Obsidian Vault Exporter — Unified VYRA + JARVIS Memory → Obsidian Vault

Reads both memory stores and generates an Obsidian-compatible vault with:
  - Markdown files per entity (people, projects, tools, concepts, events, places)
  - YAML frontmatter for metadata
  - [[wikilinks]] for cross-referencing
  - Tags for Obsidian filtering
  - _graph.json for the JARVIS UI graph view

One-way export: Vyra + Jarvis → Obsidian markdown files.
"""

import os
import re
import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# ── Default vault path ──────────────────────────────────────────────────────
DEFAULT_VAULT_PATH = r"D:\ObsidianVaults\JarvisMemory"

# Settings file for persistence
_SETTINGS_PATH = Path(__file__).parent / "data" / "obsidian_settings.json"


def _load_settings() -> dict:
    """Load obsidian exporter settings."""
    if _SETTINGS_PATH.exists():
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"vault_path": DEFAULT_VAULT_PATH, "last_sync": None, "auto_sync": False}


def _save_settings(settings: dict) -> None:
    """Save obsidian exporter settings."""
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def get_vault_path() -> str:
    """Return configured vault path."""
    return _load_settings().get("vault_path", DEFAULT_VAULT_PATH)


def set_vault_path(path: str) -> None:
    """Update the vault path."""
    settings = _load_settings()
    settings["vault_path"] = path
    _save_settings(settings)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """Convert entity name to safe filename."""
    # Remove or replace invalid chars
    safe = re.sub(r'[<>:"/\\|?*]', '_', name)
    safe = safe.strip().strip('.')
    return safe[:100] if safe else "unnamed"


def _ts_to_iso(ts: float) -> str:
    """Convert Unix timestamp (seconds or milliseconds) to ISO string."""
    if ts > 1e12:  # milliseconds
        ts = ts / 1000
    try:
        return datetime.fromtimestamp(ts).isoformat()
    except (ValueError, OSError):
        return datetime.now().isoformat()


def _content_hash(content: str) -> str:
    """Hash content for incremental updates."""
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _write_if_changed(filepath: Path, content: str) -> bool:
    """Write file only if content changed. Returns True if written."""
    if filepath.exists():
        try:
            existing = filepath.read_text(encoding="utf-8")
            if _content_hash(existing) == _content_hash(content):
                return False
        except Exception:
            pass
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(content, encoding="utf-8")
    return True


# ── Category → Folder mapping ──────────────────────────────────────────────

TYPE_FOLDERS = {
    "person": "People",
    "project": "Projects",
    "tool": "Tools",
    "concept": "Concepts",
    "event": "Events",
    "place": "Places",
}

TYPE_ICONS = {
    "person": "👤",
    "project": "📦",
    "tool": "🔧",
    "concept": "💡",
    "event": "📅",
    "place": "📍",
}


# ── Read Vyra Memory ───────────────────────────────────────────────────────

def _read_vyra_user_memory() -> dict:
    """Read VYRA's user_memory.json."""
    mem_path = Path(__file__).parent / "data" / "user_memory.json"
    if not mem_path.exists():
        return {}
    try:
        with open(mem_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_vyra_rag_store() -> dict:
    """Read VYRA's rag_store.json."""
    rag_path = Path(__file__).parent / "data" / "rag_store.json"
    if not rag_path.exists():
        return {}
    try:
        with open(rag_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── Read Jarvis Memory ─────────────────────────────────────────────────────

def _read_jarvis_entities() -> List[dict]:
    return []


# ── Build Unified Memory Graph ─────────────────────────────────────────────

def _build_unified_graph() -> Tuple[List[dict], List[dict]]:
    """
    Merge Vyra and Jarvis memory into a unified node/edge graph.
    Returns (nodes, edges)
    """
    nodes = []      # {id, name, type, source, facts[], relationships[], tags[], properties{}, timestamps{}}
    edges = []      # {from_id, from_name, to_name, to_id, type, source}
    seen_names = {} # name_lower -> node index

    now = time.time()

    # ── 1. VYRA User Memory ────────────────────────────────────────────────
    vyra_mem = _read_vyra_user_memory()

    # Primary user
    primary_user = vyra_mem.get("primary_user_id", "User")
    display_name = vyra_mem.get("display_name", primary_user)

    # Create primary user node
    user_node = {
        "id": f"vyra-user-{_safe_filename(primary_user).lower()}",
        "name": display_name or primary_user,
        "type": "person",
        "source": ["vyra-user-memory"],
        "facts": [],
        "relationships": [],
        "tags": ["user", "primary"],
        "properties": {},
        "timestamps": {"created": _ts_to_iso(now), "updated": _ts_to_iso(now)},
        "importance": 5,
    }

    # Add preferences as facts
    prefs = vyra_mem.get("preferences", {})
    for key, val in prefs.items():
        if isinstance(val, str):
            user_node["facts"].append({
                "predicate": f"preference_{key}",
                "object": val,
                "confidence": 1.0,
            })
        elif isinstance(val, dict):
            for sub_k, sub_v in val.items():
                user_node["facts"].append({
                    "predicate": f"preference_{key}_{sub_k}",
                    "object": str(sub_v),
                    "confidence": 1.0,
                })

    nodes.append(user_node)
    seen_names[user_node["name"].lower()] = 0

    # People
    for person in vyra_mem.get("important_people", []):
        name = person.get("name", "").strip()
        if not name:
            continue
        name_lower = name.lower()

        node = {
            "id": f"vyra-person-{_safe_filename(name).lower()}",
            "name": name,
            "type": "person",
            "source": ["vyra-user-memory"],
            "facts": [],
            "relationships": [],
            "tags": ["person"],
            "properties": {},
            "timestamps": {
                "created": _ts_to_iso(person.get("first_mentioned", now)),
                "updated": _ts_to_iso(person.get("last_mentioned", now)),
            },
            "importance": person.get("importance", 3),
        }

        relation = person.get("relation", "")
        if relation:
            node["facts"].append({"predicate": "relation_to_user", "object": relation, "confidence": 1.0})
            node["tags"].append(relation.lower().replace(" ", "-"))

        notes = person.get("notes", "")
        if notes:
            node["facts"].append({"predicate": "notes", "object": notes, "confidence": 1.0})

        if name_lower in seen_names:
            # Merge into existing
            idx = seen_names[name_lower]
            nodes[idx]["facts"].extend(node["facts"])
            if "vyra-user-memory" not in nodes[idx]["source"]:
                nodes[idx]["source"].append("vyra-user-memory")
        else:
            seen_names[name_lower] = len(nodes)
            nodes.append(node)

        # Add relationship edge to user
        if relation:
            edges.append({
                "from_name": user_node["name"],
                "to_name": name,
                "type": relation,
                "source": "vyra-user-memory",
            })

    # Important facts (create a concept node per unique category)
    fact_categories = {}
    for fact in vyra_mem.get("important_facts", []):
        fact_text = fact.get("fact", "").strip()
        category = fact.get("category", "general")
        if not fact_text:
            continue

        if category not in fact_categories:
            fact_categories[category] = {
                "id": f"vyra-factcat-{_safe_filename(category).lower()}",
                "name": f"Facts: {category.replace('_', ' ').title()}",
                "type": "concept",
                "source": ["vyra-user-memory"],
                "facts": [],
                "relationships": [],
                "tags": ["facts", category.lower().replace("_", "-")],
                "properties": {"category": category},
                "timestamps": {"created": _ts_to_iso(now), "updated": _ts_to_iso(now)},
                "importance": 2,
            }

        fact_categories[category]["facts"].append({
            "predicate": "fact",
            "object": fact_text,
            "confidence": fact.get("confidence", 1.0),
        })

    for cat_name, cat_node in fact_categories.items():
        nl = cat_node["name"].lower()
        if nl not in seen_names:
            seen_names[nl] = len(nodes)
            nodes.append(cat_node)

    # Emotional context
    emo = vyra_mem.get("emotional_context", {})
    if emo and emo.get("last_emotion"):
        user_node["properties"]["last_emotion"] = emo["last_emotion"]

    # ── 2. JARVIS Vault Entities ───────────────────────────────────────────
    jarvis_profiles = _read_jarvis_entities()

    for profile in jarvis_profiles:
        entity = profile.get("entity", profile)
        name = entity.get("name", "").strip()
        if not name:
            continue
        name_lower = name.lower()
        etype = entity.get("type", "concept")
        source_tag = entity.get("source", "jarvis-vault")

        facts_list = []
        for f in profile.get("facts", []):
            facts_list.append({
                "predicate": f.get("predicate", "unknown"),
                "object": f.get("object", ""),
                "confidence": f.get("confidence", 1.0),
            })

        rels_list = []
        for r in profile.get("relationships", []):
            target_name = r.get("target", "")
            rel_type = r.get("type", "related_to")
            if target_name:
                rels_list.append({"target": target_name, "type": rel_type})
                edges.append({
                    "from_name": name,
                    "to_name": target_name,
                    "type": rel_type,
                    "source": "jarvis-vault",
                })

        node = {
            "id": entity.get("id", f"jarvis-{_safe_filename(name).lower()}"),
            "name": name,
            "type": etype,
            "source": [source_tag or "jarvis-vault"],
            "facts": facts_list,
            "relationships": rels_list,
            "tags": [etype],
            "properties": entity.get("properties", {}) or {},
            "timestamps": {
                "created": _ts_to_iso(entity.get("created_at", now)),
                "updated": _ts_to_iso(entity.get("updated_at", now)),
            },
            "importance": 3,
        }

        if name_lower in seen_names:
            # Merge
            idx = seen_names[name_lower]
            existing = nodes[idx]
            existing["facts"].extend(facts_list)
            existing["relationships"].extend(rels_list)
            for s in node["source"]:
                if s not in existing["source"]:
                    existing["source"].append(s)
            for t in node["tags"]:
                if t not in existing["tags"]:
                    existing["tags"].append(t)
        else:
            seen_names[name_lower] = len(nodes)
            nodes.append(node)

    # ── 3. RAG Chunks (summary nodes) ──────────────────────────────────────
    rag_data = _read_vyra_rag_store()
    chunks = rag_data.get("chunks", [])

    if chunks:
        # Create a summary node for RAG memory
        rag_node = {
            "id": "vyra-rag-memory",
            "name": "RAG Conversation Memory",
            "type": "concept",
            "source": ["vyra-rag"],
            "facts": [{"predicate": "total_chunks", "object": str(len(chunks)), "confidence": 1.0}],
            "relationships": [],
            "tags": ["rag", "conversations", "memory"],
            "properties": {"chunk_count": len(chunks)},
            "timestamps": {"created": _ts_to_iso(now), "updated": _ts_to_iso(now)},
            "importance": 4,
        }

        # Group recent chunks by speaker
        speakers = {}
        for chunk in chunks[-50:]:  # last 50 for summarization
            speaker = chunk.get("speaker", "unknown")
            if speaker not in speakers:
                speakers[speaker] = 0
            speakers[speaker] += 1

        for sp, count in speakers.items():
            rag_node["facts"].append({
                "predicate": f"recent_messages_from",
                "object": f"{sp}: {count} chunks",
                "confidence": 1.0,
            })

        if "rag conversation memory" not in seen_names:
            seen_names["rag conversation memory"] = len(nodes)
            nodes.append(rag_node)

    # Resolve edge IDs
    name_to_id = {}
    for n in nodes:
        name_to_id[n["name"].lower()] = n["id"]

    for edge in edges:
        edge["from_id"] = name_to_id.get(edge["from_name"].lower(), "")
        edge["to_id"] = name_to_id.get(edge["to_name"].lower(), "")

    return nodes, edges


# ── Generate Markdown for an Entity ────────────────────────────────────────

def _render_entity_md(node: dict, all_nodes: List[dict], edges: List[dict]) -> str:
    """Generate Obsidian-compatible markdown for an entity node."""
    lines = []

    # YAML frontmatter
    lines.append("---")
    lines.append(f"type: {node['type']}")
    lines.append(f"source: [{', '.join(node['source'])}]")
    lines.append(f"created: {node['timestamps']['created']}")
    lines.append(f"updated: {node['timestamps']['updated']}")
    lines.append(f"tags: [{', '.join(node['tags'])}]")
    lines.append(f"importance: {node.get('importance', 3)}")
    lines.append(f"id: {node['id']}")
    lines.append("---")
    lines.append("")

    # Title
    icon = TYPE_ICONS.get(node["type"], "📄")
    lines.append(f"# {icon} {node['name']}")
    lines.append("")

    # Properties
    props = node.get("properties", {})
    if props:
        for k, v in props.items():
            if isinstance(v, str) and v:
                lines.append(f"**{k.replace('_', ' ').title()}**: {v}  ")
        lines.append("")

    # Source badge
    sources = ", ".join(node["source"])
    lines.append(f"> Source: `{sources}`")
    lines.append("")

    # Facts
    if node["facts"]:
        lines.append("## Facts")
        lines.append("")
        for f in node["facts"]:
            pred = f["predicate"].replace("_", " ").title()
            obj = f["object"]
            conf = f.get("confidence", 1.0)
            conf_badge = f" `{int(conf * 100)}%`" if conf < 1.0 else ""
            lines.append(f"- **{pred}**: {obj}{conf_badge}")
        lines.append("")

    # Relationships (with wikilinks!)
    node_name_lower = node["name"].lower()
    related_edges = [
        e for e in edges
        if e.get("from_name", "").lower() == node_name_lower
        or e.get("to_name", "").lower() == node_name_lower
    ]

    if related_edges:
        lines.append("## Relationships")
        lines.append("")
        seen_rels = set()
        for e in related_edges:
            if e["from_name"].lower() == node_name_lower:
                target = e["to_name"]
                direction = "→"
            else:
                target = e["from_name"]
                direction = "←"
            rel_key = f"{target.lower()}-{e['type']}"
            if rel_key in seen_rels:
                continue
            seen_rels.add(rel_key)
            lines.append(f"- {direction} [[{target}]] — *{e['type']}*")
        lines.append("")

    # Backlinks section (entities that reference this one via facts)
    backlinks = []
    for other in all_nodes:
        if other["id"] == node["id"]:
            continue
        for f in other.get("facts", []):
            if node["name"].lower() in f.get("object", "").lower():
                backlinks.append(other["name"])
                break
    if backlinks:
        lines.append("## Backlinks")
        lines.append("")
        for bl in backlinks[:10]:
            lines.append(f"- [[{bl}]]")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append(f"*Last exported: {datetime.now().isoformat()}*")

    return "\n".join(lines)


# ── Generate Graph JSON ────────────────────────────────────────────────────

def _build_graph_json(nodes: List[dict], edges: List[dict]) -> dict:
    """Build D3-compatible graph JSON."""
    graph_nodes = []
    for n in nodes:
        graph_nodes.append({
            "id": n["id"],
            "name": n["name"],
            "type": n["type"],
            "source": n["source"],
            "factCount": len(n["facts"]),
            "relCount": len(n.get("relationships", [])),
            "importance": n.get("importance", 3),
            "tags": n["tags"],
        })

    graph_edges = []
    seen_edges = set()
    for e in edges:
        if not e.get("from_id") or not e.get("to_id"):
            continue
        key = f"{e['from_id']}-{e['to_id']}-{e['type']}"
        if key in seen_edges:
            continue
        seen_edges.add(key)
        graph_edges.append({
            "source": e["from_id"],
            "target": e["to_id"],
            "type": e["type"],
            "label": e["type"].replace("_", " "),
        })

    return {
        "nodes": graph_nodes,
        "links": graph_edges,
        "meta": {
            "total_nodes": len(graph_nodes),
            "total_edges": len(graph_edges),
            "exported_at": datetime.now().isoformat(),
        },
    }


# ── Main Export Function ───────────────────────────────────────────────────

def export_to_obsidian(vault_path: Optional[str] = None) -> dict:
    """
    Full export of unified VYRA+JARVIS memory to an Obsidian vault.

    Returns:
        dict with {success, vault_path, files_written, files_unchanged, total_nodes, total_edges, graph_path}
    """
    vault = Path(vault_path or get_vault_path())
    vault.mkdir(parents=True, exist_ok=True)

    # Build unified graph
    nodes, edges = _build_unified_graph()

    files_written = 0
    files_unchanged = 0

    # Create type folders
    for folder_name in TYPE_FOLDERS.values():
        (vault / folder_name).mkdir(exist_ok=True)

    # Create _meta folder
    (vault / "_meta").mkdir(exist_ok=True)

    # Write entity files
    for node in nodes:
        folder = TYPE_FOLDERS.get(node["type"], "Concepts")
        filename = _safe_filename(node["name"]) + ".md"
        filepath = vault / folder / filename

        content = _render_entity_md(node, nodes, edges)
        if _write_if_changed(filepath, content):
            files_written += 1
        else:
            files_unchanged += 1

    # Write graph JSON
    graph_data = _build_graph_json(nodes, edges)
    graph_path = vault / "_meta" / "graph.json"
    graph_path.write_text(json.dumps(graph_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write sync status
    sync_status = {
        "last_sync": datetime.now().isoformat(),
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "files_written": files_written,
        "vault_path": str(vault),
    }
    (vault / "_meta" / "sync_status.json").write_text(
        json.dumps(sync_status, indent=2), encoding="utf-8"
    )

    # Create .obsidian config if it doesn't exist
    obsidian_dir = vault / ".obsidian"
    obsidian_dir.mkdir(exist_ok=True)
    app_json = obsidian_dir / "app.json"
    if not app_json.exists():
        app_json.write_text(json.dumps({
            "theme": "obsidian",
            "cssTheme": "",
            "baseFontSize": 16,
        }, indent=2), encoding="utf-8")

    graph_json = obsidian_dir / "graph.json"
    if not graph_json.exists():
        graph_json.write_text(json.dumps({
            "collapse-filter": True,
            "search": "",
            "showTags": True,
            "showAttachments": False,
            "hideUnresolved": False,
            "showOrphans": True,
            "collapse-color": False,
            "colorGroups": [
                {"query": "tag:#person", "color": {"a": 1, "rgb": 6333684}},
                {"query": "tag:#project", "color": {"a": 1, "rgb": 3618559}},
                {"query": "tag:#tool", "color": {"a": 1, "rgb": 4940543}},
                {"query": "tag:#concept", "color": {"a": 1, "rgb": 3461913}},
                {"query": "tag:#event", "color": {"a": 1, "rgb": 2282462}},
                {"query": "tag:#place", "color": {"a": 1, "rgb": 16506676}},
            ],
            "collapse-display": True,
            "showArrow": True,
            "textFadeMultiplier": -2,
            "nodeSizeMultiplier": 1.2,
            "lineSizeMultiplier": 1,
            "collapse-forces": True,
            "centerStrength": 0.5,
            "repelStrength": 10,
            "linkStrength": 1,
            "linkDistance": 250,
            "scale": 1,
        }, indent=2), encoding="utf-8")

    # Write a welcome / index note
    index_path = vault / "Memory Vault.md"
    if not index_path.exists():
        index_content = f"""---
type: index
tags: [index, memory-vault]
---

# 🧠 Memory Vault

**Unified memory from VYRA + JARVIS**

This vault is auto-generated and synced from your AI assistants.

## Quick Links

### People
```dataview
LIST FROM "People"
SORT file.name ASC
```

### Projects
```dataview
LIST FROM "Projects"
SORT file.name ASC
```

### Concepts
```dataview
LIST FROM "Concepts"
SORT file.name ASC
```

---
*Last sync: {datetime.now().isoformat()}*
*Total entities: {len(nodes)} | Relationships: {len(edges)}*
"""
        index_path.write_text(index_content, encoding="utf-8")
        files_written += 1

    # Update settings
    settings = _load_settings()
    settings["last_sync"] = time.time()
    settings["vault_path"] = str(vault)
    _save_settings(settings)

    return {
        "success": True,
        "vault_path": str(vault),
        "files_written": files_written,
        "files_unchanged": files_unchanged,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "graph_path": str(graph_path),
    }


def get_graph_data(vault_path: Optional[str] = None) -> dict:
    """Read the pre-computed graph JSON for the UI."""
    vault = Path(vault_path or get_vault_path())
    graph_path = vault / "_meta" / "graph.json"
    if graph_path.exists():
        try:
            with open(graph_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # If no cached graph, build fresh
    nodes, edges = _build_unified_graph()
    return _build_graph_json(nodes, edges)


def get_obsidian_status() -> dict:
    """Return current status of the Obsidian vault."""
    settings = _load_settings()
    vault = Path(settings.get("vault_path", DEFAULT_VAULT_PATH))

    status = {
        "vault_path": str(vault),
        "vault_exists": vault.exists(),
        "last_sync": settings.get("last_sync"),
        "auto_sync": settings.get("auto_sync", False),
        "file_count": 0,
        "folder_count": 0,
    }

    if vault.exists():
        md_files = list(vault.rglob("*.md"))
        status["file_count"] = len(md_files)
        status["folder_count"] = len([d for d in vault.iterdir() if d.is_dir() and d.name != ".obsidian"])

    # Read sync_status if available
    sync_path = vault / "_meta" / "sync_status.json"
    if sync_path.exists():
        try:
            with open(sync_path, "r", encoding="utf-8") as f:
                sync_data = json.load(f)
            status["total_nodes"] = sync_data.get("total_nodes", 0)
            status["total_edges"] = sync_data.get("total_edges", 0)
        except Exception:
            pass

    return status


# ── CLI entry point for testing ────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--test" in sys.argv:
        print("Building unified graph...")
        nodes, edges = _build_unified_graph()
        print(f"  Nodes: {len(nodes)}")
        print(f"  Edges: {len(edges)}")
        for n in nodes[:5]:
            print(f"    {n['type']}: {n['name']} ({len(n['facts'])} facts)")
        print("\nExporting to vault...")
        result = export_to_obsidian()
        print(json.dumps(result, indent=2))
    else:
        result = export_to_obsidian()
        print(json.dumps(result, indent=2))
