"""
Capability Registry — Phase 5.1
==================================
Dynamic catalogue of ALL VYRA tools: built-in + synthesized.

Tracks usage, success rates, latencies. Auto-deprecates failing tools.
The ToolSynthesizer registers new tools here on creation.

Usage:
    reg  = get_registry()
    reg.record_call("web_agent.search", success=True, latency_ms=1200)
    tool = reg.get("web_agent.search")
    poor = reg.get_poor_performers()          # success_rate < 0.6
    reg.list_available()                      # all non-deprecated tools
"""

import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

DATA_DIR = Path(__file__).parent.parent / "data"


@dataclass
class ToolRecord:
    id: str                    # e.g. "web_agent.search"
    name: str
    description: str
    agent: str                 # which agent owns it
    input_schema: Dict         # JSON Schema of inputs
    output_description: str
    source: str                # "builtin" | "synthesized"
    registered_at: str         = ""
    call_count: int            = 0
    success_count: int         = 0
    total_latency_ms: float    = 0.0
    last_called: str           = ""
    deprecated: bool           = False
    deprecation_reason: str    = ""
    version: str               = "1.0"
    tags: List[str]            = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 1.0
        return self.success_count / self.call_count

    @property
    def avg_latency_ms(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_latency_ms / self.call_count

    def __post_init__(self):
        if not self.registered_at:
            self.registered_at = datetime.utcnow().isoformat()


class CapabilityRegistry:

    def __init__(self, data_dir: Path = DATA_DIR):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path  = data_dir / "capabilities.db"
        self._init_db()
        self._seed_builtins()

    def _init_db(self):
        con = sqlite3.connect(self.db_path)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS tools (
                id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                agent TEXT,
                input_schema TEXT,
                output_description TEXT,
                source TEXT,
                registered_at TEXT,
                call_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                total_latency_ms REAL DEFAULT 0.0,
                last_called TEXT,
                deprecated INTEGER DEFAULT 0,
                deprecation_reason TEXT DEFAULT '',
                version TEXT DEFAULT '1.0',
                tags TEXT DEFAULT '[]'
            );
        """)
        con.commit()
        con.close()

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def register(self, tool: ToolRecord):
        con = sqlite3.connect(self.db_path)
        con.execute("""
            INSERT OR REPLACE INTO tools
            (id,name,description,agent,input_schema,output_description,source,
             registered_at,call_count,success_count,total_latency_ms,last_called,
             deprecated,deprecation_reason,version,tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            tool.id, tool.name, tool.description, tool.agent,
            json.dumps(tool.input_schema), tool.output_description, tool.source,
            tool.registered_at, tool.call_count, tool.success_count,
            tool.total_latency_ms, tool.last_called,
            1 if tool.deprecated else 0, tool.deprecation_reason,
            tool.version, json.dumps(tool.tags),
        ))
        con.commit()
        con.close()

    def get(self, tool_id: str) -> Optional[ToolRecord]:
        con = sqlite3.connect(self.db_path)
        row = con.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
        con.close()
        return self._row_to_tool(row) if row else None

    def list_available(self, agent: Optional[str] = None) -> List[ToolRecord]:
        con = sqlite3.connect(self.db_path)
        if agent:
            rows = con.execute(
                "SELECT * FROM tools WHERE deprecated=0 AND agent=?", (agent,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM tools WHERE deprecated=0").fetchall()
        con.close()
        return [self._row_to_tool(r) for r in rows]

    def record_call(self, tool_id: str, success: bool, latency_ms: float = 0.0):
        con = sqlite3.connect(self.db_path)
        con.execute("""
            UPDATE tools SET
                call_count      = call_count + 1,
                success_count   = success_count + ?,
                total_latency_ms= total_latency_ms + ?,
                last_called     = ?
            WHERE id=?
        """, (1 if success else 0, latency_ms, datetime.utcnow().isoformat(), tool_id))
        con.commit()
        con.close()
        # Auto-deprecate tools with < 50% success rate after 20+ calls
        tool = self.get(tool_id)
        if tool and tool.call_count >= 20 and tool.success_rate < 0.5:
            self.deprecate(tool_id, reason=f"Auto-deprecated: success rate {tool.success_rate:.1%}")

    def deprecate(self, tool_id: str, reason: str = ""):
        con = sqlite3.connect(self.db_path)
        con.execute(
            "UPDATE tools SET deprecated=1, deprecation_reason=? WHERE id=?",
            (reason, tool_id)
        )
        con.commit()
        con.close()
        print(f"[Registry] Deprecated tool: {tool_id} — {reason}")

    def get_poor_performers(self, min_calls: int = 10) -> List[ToolRecord]:
        tools = self.list_available()
        return [t for t in tools if t.call_count >= min_calls and t.success_rate < 0.6]

    def stats_summary(self) -> str:
        all_tools = self.list_available()
        synth     = [t for t in all_tools if t.source == "synthesized"]
        lines = [
            f"Total tools: {len(all_tools)}",
            f"  Built-in:    {len(all_tools) - len(synth)}",
            f"  Synthesized: {len(synth)}",
        ]
        top = sorted(all_tools, key=lambda t: t.call_count, reverse=True)[:3]
        if top:
            lines.append("Top used: " + ", ".join(f"{t.id}({t.call_count})" for t in top))
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _row_to_tool(self, row) -> ToolRecord:
        (tid,name,desc,agent,schema,out_desc,source,reg_at,calls,successes,
         latency,last_called,deprecated,dep_reason,version,tags) = row
        return ToolRecord(
            id=tid, name=name, description=desc, agent=agent,
            input_schema=json.loads(schema or "{}"),
            output_description=out_desc or "",
            source=source or "builtin",
            registered_at=reg_at or "",
            call_count=calls or 0,
            success_count=successes or 0,
            total_latency_ms=latency or 0.0,
            last_called=last_called or "",
            deprecated=bool(deprecated),
            deprecation_reason=dep_reason or "",
            version=version or "1.0",
            tags=json.loads(tags or "[]"),
        )

    def _seed_builtins(self):
        """Register the core built-in VYRA tools if not already present."""
        builtins = [
            ToolRecord(id="web_agent.search",  name="Web Search",   description="Search the web", agent="web_agent",  input_schema={"query":{"type":"string"}}, output_description="Search results", source="builtin", tags=["search","web"]),
            ToolRecord(id="web_agent.browse",  name="Web Browse",   description="Navigate to URL", agent="web_agent",  input_schema={"url":{"type":"string"}},   output_description="Page content", source="builtin",   tags=["web"]),
            ToolRecord(id="cad_agent.generate",name="CAD Generate", description="Generate 3D model",agent="cad_agent", input_schema={"description":{"type":"string"}}, output_description="STL file path", source="builtin", tags=["cad","3d"]),
            ToolRecord(id="kasa_agent.control",name="Smart Home",   description="Control smart devices", agent="kasa_agent", input_schema={"device":{"type":"string"},"action":{"type":"string"}}, output_description="Control result", source="builtin", tags=["smart_home"]),
            ToolRecord(id="win_system.execute",name="Windows Control", description="Windows OS operations", agent="win_system", input_schema={"command":{"type":"string"}}, output_description="Command result", source="builtin", tags=["windows","system"]),
            ToolRecord(id="research_agent.deep_search", name="Deep Research", description="Multi-source research synthesis", agent="research_agent", input_schema={"topic":{"type":"string"}}, output_description="Research report", source="builtin", tags=["research"]),
        ]
        for tool in builtins:
            existing = self.get(tool.id)
            if not existing:
                self.register(tool)


_registry: Optional[CapabilityRegistry] = None

def get_registry() -> CapabilityRegistry:
    global _registry
    if _registry is None:
        _registry = CapabilityRegistry()
    return _registry
