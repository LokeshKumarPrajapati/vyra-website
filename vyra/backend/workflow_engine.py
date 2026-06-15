"""
workflow_engine.py — SQLite-backed workflow store, node catalog, and async executor.
All dashboard and workflow REST APIs depend on this module.
"""

import sqlite3
import asyncio
import json
import uuid
import time
import os
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

# ---------------------------------------------------------------------------
# DB path — stored next to server.py
# ---------------------------------------------------------------------------
_DB_PATH = Path(os.path.dirname(os.path.abspath(__file__))) / "data" / "workflows.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# NODE CATALOG — what the frontend drag-and-drop palette uses
# ---------------------------------------------------------------------------
NODE_CATALOG: List[Dict[str, Any]] = [
    # ── Triggers ──────────────────────────────────────────────────────────
    {
        "type": "trigger.manual",
        "label": "Manual Trigger",
        "description": "Start a workflow on demand (via button or Vyra command).",
        "category": "trigger",
        "icon": "▶",
        "color": "#3B82F6",
        "configSchema": {},
        "inputs": [],
        "outputs": ["default"],
    },
    {
        "type": "trigger.schedule",
        "label": "Schedule",
        "description": "Run the workflow on a cron schedule.",
        "category": "trigger",
        "icon": "⏱",
        "color": "#3B82F6",
        "configSchema": {
            "cron": {
                "type": "string",
                "description": "Cron expression (e.g. 0 9 * * 1-5)",
                "default": "0 9 * * 1-5",
            }
        },
        "inputs": [],
        "outputs": ["default"],
    },
    {
        "type": "trigger.webhook",
        "label": "Webhook",
        "description": "Trigger on an incoming HTTP POST.",
        "category": "trigger",
        "icon": "⚡",
        "color": "#3B82F6",
        "configSchema": {
            "path": {"type": "string", "description": "URL path suffix", "default": "/hook"}
        },
        "inputs": [],
        "outputs": ["default"],
    },
    {
        "type": "trigger.voice",
        "label": "Voice Command",
        "description": "Vyra triggers this workflow by voice.",
        "category": "trigger",
        "icon": "🎤",
        "color": "#3B82F6",
        "configSchema": {
            "phrase": {
                "type": "string",
                "description": "Trigger phrase Vyra listens for",
                "default": "run my workflow",
            }
        },
        "inputs": [],
        "outputs": ["default"],
    },
    # ── Actions ───────────────────────────────────────────────────────────
    {
        "type": "action.send_message",
        "label": "Send Message",
        "description": "Have Vyra say or send a message.",
        "category": "action",
        "icon": "💬",
        "color": "#F59E0B",
        "configSchema": {
            "message": {
                "type": "string",
                "description": "Message text (supports {{variables}})",
                "default": "Hello!",
            },
            "channel": {
                "type": "select",
                "description": "Channel",
                "options": ["voice", "chat", "notification"],
                "default": "chat",
            },
        },
        "inputs": ["default"],
        "outputs": ["default"],
    },
    {
        "type": "action.run_code",
        "label": "Run Code",
        "description": "Execute a Python script.",
        "category": "action",
        "icon": "⚙",
        "color": "#F59E0B",
        "configSchema": {
            "code": {
                "type": "code",
                "language": "python",
                "description": "Python code to execute",
                "default": "result = 'Hello'",
            }
        },
        "inputs": ["default"],
        "outputs": ["default", "error"],
    },
    {
        "type": "action.http_request",
        "label": "HTTP Request",
        "description": "Make an HTTP request to an external API.",
        "category": "action",
        "icon": "🌐",
        "color": "#F59E0B",
        "configSchema": {
            "url": {"type": "string", "description": "Request URL", "default": "https://"},
            "method": {
                "type": "select",
                "options": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
            },
            "headers": {"type": "json", "description": "Headers (JSON)", "default": "{}"},
            "body": {"type": "json", "description": "Body (JSON)", "default": "{}"},
        },
        "inputs": ["default"],
        "outputs": ["default", "error"],
    },
    {
        "type": "action.play_music",
        "label": "Play Music",
        "description": "Play Spotify music via Vyra.",
        "category": "action",
        "icon": "🎵",
        "color": "#F59E0B",
        "configSchema": {
            "query": {
                "type": "string",
                "description": "Song, artist, or playlist name",
                "default": "",
            }
        },
        "inputs": ["default"],
        "outputs": ["default"],
    },
    {
        "type": "action.send_email",
        "label": "Send Email",
        "description": "Send an email via configured mail provider.",
        "category": "action",
        "icon": "📧",
        "color": "#F59E0B",
        "configSchema": {
            "to": {"type": "string", "description": "Recipient email(s)", "default": ""},
            "subject": {"type": "string", "description": "Subject", "default": ""},
            "body": {"type": "text", "description": "Email body", "default": ""},
        },
        "inputs": ["default"],
        "outputs": ["default", "error"],
    },
    {
        "type": "action.write_file",
        "label": "Write File",
        "description": "Write content to a file on disk.",
        "category": "action",
        "icon": "💾",
        "color": "#F59E0B",
        "configSchema": {
            "path": {"type": "string", "description": "File path", "default": "output.txt"},
            "content": {"type": "text", "description": "File content", "default": ""},
            "mode": {
                "type": "select",
                "options": ["overwrite", "append"],
                "default": "overwrite",
            },
        },
        "inputs": ["default"],
        "outputs": ["default", "error"],
    },
    {
        "type": "action.vyra_ask",
        "label": "Ask Vyra",
        "description": "Send a prompt to Vyra and use the response as output.",
        "category": "action",
        "icon": "🤖",
        "color": "#F59E0B",
        "configSchema": {
            "prompt": {
                "type": "text",
                "description": "Prompt for Vyra (supports {{variables}})",
                "default": "Summarize this: {{input}}",
            }
        },
        "inputs": ["default"],
        "outputs": ["default"],
    },
    # ── Logic ─────────────────────────────────────────────────────────────
    {
        "type": "logic.if_else",
        "label": "If / Else",
        "description": "Branch based on a condition.",
        "category": "logic",
        "icon": "⑂",
        "color": "#10B981",
        "configSchema": {
            "condition": {
                "type": "string",
                "description": "Python boolean expression (e.g. {{status}} == 'ok')",
                "default": "True",
            }
        },
        "inputs": ["default"],
        "outputs": ["true", "false"],
    },
    {
        "type": "logic.loop",
        "label": "For Each",
        "description": "Iterate over a list.",
        "category": "logic",
        "icon": "↻",
        "color": "#10B981",
        "configSchema": {
            "items": {
                "type": "string",
                "description": "Expression returning a list",
                "default": "{{items}}",
            }
        },
        "inputs": ["default"],
        "outputs": ["item", "done"],
    },
    {
        "type": "logic.wait",
        "label": "Wait / Delay",
        "description": "Pause execution for a set time.",
        "category": "logic",
        "icon": "⏸",
        "color": "#10B981",
        "configSchema": {
            "seconds": {"type": "number", "description": "Delay in seconds", "default": 5}
        },
        "inputs": ["default"],
        "outputs": ["default"],
    },
    {
        "type": "logic.merge",
        "label": "Merge",
        "description": "Wait for all incoming branches then continue.",
        "category": "logic",
        "icon": "⤢",
        "color": "#10B981",
        "configSchema": {},
        "inputs": ["a", "b"],
        "outputs": ["default"],
    },
    # ── Transform ─────────────────────────────────────────────────────────
    {
        "type": "transform.set_variable",
        "label": "Set Variable",
        "description": "Set a workflow variable.",
        "category": "transform",
        "icon": "=",
        "color": "#8B5CF6",
        "configSchema": {
            "name": {"type": "string", "description": "Variable name", "default": "myVar"},
            "value": {
                "type": "string",
                "description": "Value expression",
                "default": "{{input}}",
            },
        },
        "inputs": ["default"],
        "outputs": ["default"],
    },
    {
        "type": "transform.json_parse",
        "label": "JSON Parse",
        "description": "Parse JSON string into an object.",
        "category": "transform",
        "icon": "{ }",
        "color": "#8B5CF6",
        "configSchema": {
            "input": {
                "type": "string",
                "description": "JSON string expression",
                "default": "{{input}}",
            }
        },
        "inputs": ["default"],
        "outputs": ["default", "error"],
    },
    {
        "type": "transform.template",
        "label": "Text Template",
        "description": "Render a Jinja-style text template with workflow variables.",
        "category": "transform",
        "icon": "Tt",
        "color": "#8B5CF6",
        "configSchema": {
            "template": {
                "type": "text",
                "description": "Template (use {{variable}} syntax)",
                "default": "Hello {{name}}!",
            }
        },
        "inputs": ["default"],
        "outputs": ["default"],
    },
    # ── Error handling ────────────────────────────────────────────────────
    {
        "type": "error.catch",
        "label": "Error Catcher",
        "description": "Catch errors from upstream nodes.",
        "category": "error",
        "icon": "⚠",
        "color": "#EF4444",
        "configSchema": {},
        "inputs": ["error"],
        "outputs": ["default"],
    },
    {
        "type": "error.retry",
        "label": "Retry",
        "description": "Retry the upstream step on failure.",
        "category": "error",
        "icon": "↩",
        "color": "#EF4444",
        "configSchema": {
            "max_attempts": {"type": "number", "default": 3},
            "delay_seconds": {"type": "number", "default": 5},
        },
        "inputs": ["error"],
        "outputs": ["default", "failed"],
    },
]


# ---------------------------------------------------------------------------
# WorkflowDB — thin SQLite wrapper
# ---------------------------------------------------------------------------
class WorkflowDB:
    """Thread-safe SQLite wrapper for workflow persistence."""

    def __init__(self, db_path: Path = _DB_PATH):
        self.db_path = str(db_path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS workflows (
                    id              TEXT PRIMARY KEY,
                    name            TEXT NOT NULL,
                    description     TEXT DEFAULT '',
                    enabled         INTEGER DEFAULT 1,
                    tags            TEXT DEFAULT '[]',
                    current_version INTEGER DEFAULT 1,
                    execution_count INTEGER DEFAULT 0,
                    last_executed_at REAL,
                    last_success_at  REAL,
                    last_failure_at  REAL,
                    created_at      REAL NOT NULL,
                    updated_at      REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS workflow_versions (
                    id          TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    version     INTEGER NOT NULL,
                    definition  TEXT NOT NULL,
                    changelog   TEXT,
                    created_at  REAL NOT NULL,
                    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS workflow_executions (
                    id           TEXT PRIMARY KEY,
                    workflow_id  TEXT NOT NULL,
                    version      INTEGER NOT NULL,
                    status       TEXT DEFAULT 'running',
                    started_at   REAL NOT NULL,
                    finished_at  REAL,
                    error        TEXT,
                    context      TEXT DEFAULT '{}',
                    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS goals (
                    id          TEXT PRIMARY KEY,
                    title       TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    score       REAL DEFAULT 0.0,
                    status      TEXT DEFAULT 'active',
                    health      TEXT DEFAULT 'on_track',
                    level       TEXT DEFAULT 'strategic',
                    deadline    REAL,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL
                );
            """)
            conn.commit()

    # ── Workflows ──────────────────────────────────────────────────────────

    def list_workflows(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
            return [self._wf_row(r) for r in rows]

    def get_workflow(self, wf_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM workflows WHERE id=?", (wf_id,)).fetchone()
            return self._wf_row(row) if row else None

    def create_workflow(self, name: str, description: str = "", definition: Optional[Dict] = None, tags: List[str] = None) -> Dict:
        now = time.time()
        wf_id = str(uuid.uuid4())
        tags_json = json.dumps(tags or [])
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workflows(id,name,description,enabled,tags,current_version,execution_count,created_at,updated_at) VALUES(?,?,?,1,?,1,0,?,?)",
                (wf_id, name, description, tags_json, now, now),
            )
            # Insert version 1
            ver_id = str(uuid.uuid4())
            default_def = definition or {
                "nodes": [{
                    "id": "trigger-1",
                    "type": "trigger.manual",
                    "label": "Manual Trigger",
                    "position": {"x": 100, "y": 200},
                    "config": {},
                }],
                "edges": [],
                "settings": {
                    "maxRetries": 3,
                    "retryDelayMs": 5000,
                    "timeoutMs": 300000,
                    "parallelism": "parallel",
                    "onError": "stop",
                },
            }
            conn.execute(
                "INSERT INTO workflow_versions(id,workflow_id,version,definition,changelog,created_at) VALUES(?,?,1,?,?,?)",
                (ver_id, wf_id, json.dumps(default_def), "Initial version", now),
            )
            conn.commit()
        return self.get_workflow(wf_id)

    def update_workflow(self, wf_id: str, **fields) -> Optional[Dict]:
        allowed = {"name", "description", "enabled", "tags"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return self.get_workflow(wf_id)
        now = time.time()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = []
        for k, v in updates.items():
            if k == "tags":
                values.append(json.dumps(v))
            elif k == "enabled":
                values.append(1 if v else 0)
            else:
                values.append(v)
        values += [now, wf_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE workflows SET {set_clause}, updated_at=? WHERE id=?", values)
            conn.commit()
        return self.get_workflow(wf_id)

    def delete_workflow(self, wf_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM workflows WHERE id=?", (wf_id,))
            conn.commit()
        return True

    def increment_execution_count(self, wf_id: str, success: bool):
        now = time.time()
        with self._connect() as conn:
            if success:
                conn.execute(
                    "UPDATE workflows SET execution_count=execution_count+1, last_executed_at=?, last_success_at=?, updated_at=? WHERE id=?",
                    (now, now, now, wf_id),
                )
            else:
                conn.execute(
                    "UPDATE workflows SET execution_count=execution_count+1, last_executed_at=?, last_failure_at=?, updated_at=? WHERE id=?",
                    (now, now, now, wf_id),
                )
            conn.commit()

    # ── Versions ────────────────────────────────────────────────────────────

    def list_versions(self, wf_id: str) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_versions WHERE workflow_id=? ORDER BY version DESC",
                (wf_id,),
            ).fetchall()
            return [self._ver_row(r) for r in rows]

    def create_version(self, wf_id: str, definition: Dict, changelog: Optional[str] = None) -> Dict:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT MAX(version) as mv FROM workflow_versions WHERE workflow_id=?", (wf_id,)
            ).fetchone()
            next_ver = (cur["mv"] or 0) + 1
            ver_id = str(uuid.uuid4())
            now = time.time()
            conn.execute(
                "INSERT INTO workflow_versions(id,workflow_id,version,definition,changelog,created_at) VALUES(?,?,?,?,?,?)",
                (ver_id, wf_id, next_ver, json.dumps(definition), changelog, now),
            )
            conn.execute(
                "UPDATE workflows SET current_version=?, updated_at=? WHERE id=?",
                (next_ver, now, wf_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM workflow_versions WHERE id=?", (ver_id,)).fetchone()
            return self._ver_row(row)

    def get_latest_version(self, wf_id: str) -> Optional[Dict]:
        versions = self.list_versions(wf_id)
        return versions[0] if versions else None

    # ── Executions ──────────────────────────────────────────────────────────

    def create_execution(self, wf_id: str, version: int) -> Dict:
        exec_id = str(uuid.uuid4())
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workflow_executions(id,workflow_id,version,status,started_at,context) VALUES(?,?,?,'running',?,'{}')",
                (exec_id, wf_id, version, now),
            )
            conn.commit()
        return {"id": exec_id, "workflow_id": wf_id, "version": version, "status": "running", "started_at": now}

    def finish_execution(self, exec_id: str, success: bool, error: Optional[str] = None):
        now = time.time()
        status = "success" if success else "failed"
        with self._connect() as conn:
            conn.execute(
                "UPDATE workflow_executions SET status=?, finished_at=?, error=? WHERE id=?",
                (status, now, error, exec_id),
            )
            conn.commit()

    def list_executions(self, wf_id: str, limit: int = 20) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_executions WHERE workflow_id=? ORDER BY started_at DESC LIMIT ?",
                (wf_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ── Goals ────────────────────────────────────────────────────────────────

    def list_goals(self, status: Optional[str] = None, limit: int = 50) -> List[Dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM goals WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM goals ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def create_goal(self, title: str, description: str = "", score: float = 0.0,
                    status: str = "active", health: str = "on_track", level: str = "strategic",
                    deadline: Optional[float] = None) -> Dict:
        now = time.time()
        goal_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO goals(id,title,description,score,status,health,level,deadline,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (goal_id, title, description, score, status, health, level, deadline, now, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            return dict(row)

    def update_goal(self, goal_id: str, **fields) -> Optional[Dict]:
        allowed = {"title", "description", "score", "status", "health", "level", "deadline"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            with self._connect() as conn:
                row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
                return dict(row) if row else None
        now = time.time()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [now, goal_id]
        with self._connect() as conn:
            conn.execute(f"UPDATE goals SET {set_clause}, updated_at=? WHERE id=?", values)
            conn.commit()
            row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
            return dict(row) if row else None

    def delete_goal(self, goal_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
            conn.commit()
        return True

    # ── Row helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _wf_row(row) -> Dict:
        d = dict(row)
        d["enabled"] = bool(d.get("enabled", 1))
        try:
            d["tags"] = json.loads(d.get("tags", "[]"))
        except Exception:
            d["tags"] = []
        return d

    @staticmethod
    def _ver_row(row) -> Dict:
        d = dict(row)
        try:
            d["definition"] = json.loads(d.get("definition", "{}"))
        except Exception:
            d["definition"] = {}
        return d


# ---------------------------------------------------------------------------
# WorkflowExecutor — async step-by-step runner
# ---------------------------------------------------------------------------
EventCallback = Callable[[Dict], Coroutine[Any, Any, None]]


class WorkflowExecutor:
    """
    Executes a workflow definition node-by-node.
    Broadcasts events via the provided async callback for SocketIO.
    """

    def __init__(self, db: WorkflowDB, event_callback: Optional[EventCallback] = None):
        self.db = db
        self.event_callback = event_callback

    async def _emit(self, event: Dict):
        if self.event_callback:
            try:
                await self.event_callback(event)
            except Exception:
                pass

    async def execute(self, wf_id: str) -> Dict:
        """Execute a workflow by id. Returns result dict."""
        workflow = self.db.get_workflow(wf_id)
        if not workflow:
            return {"success": False, "error": "Workflow not found"}

        version_data = self.db.get_latest_version(wf_id)
        if not version_data:
            return {"success": False, "error": "No versions found"}

        definition = version_data["definition"]
        version_num = version_data["version"]
        execution = self.db.create_execution(wf_id, version_num)
        exec_id = execution["id"]

        await self._emit({
            "type": "execution_started",
            "workflowId": wf_id,
            "executionId": exec_id,
            "timestamp": time.time(),
        })

        # Build ordered node list (topological walk from trigger node)
        nodes = {n["id"]: n for n in definition.get("nodes", [])}
        edges = definition.get("edges", [])
        outgoing: Dict[str, List[str]] = {}
        for e in edges:
            outgoing.setdefault(e["source"], []).append(e["target"])

        # Find roots (no incoming edges)
        has_incoming = {e["target"] for e in edges}
        roots = [n for n in nodes if n not in has_incoming]
        if not roots:
            roots = list(nodes.keys())[:1]  # fallback

        context: Dict[str, Any] = {}
        visited = set()
        queue = list(roots)
        success = True
        last_error = None

        while queue:
            node_id = queue.pop(0)
            if node_id in visited or node_id not in nodes:
                continue
            visited.add(node_id)
            node = nodes[node_id]

            await self._emit({
                "type": "step_started",
                "workflowId": wf_id,
                "executionId": exec_id,
                "nodeId": node_id,
                "nodeType": node.get("type"),
                "nodeLabel": node.get("label"),
                "timestamp": time.time(),
            })

            try:
                output = await self._run_node(node, context)
                context[f"{node_id}_output"] = output
                await self._emit({
                    "type": "step_completed",
                    "workflowId": wf_id,
                    "executionId": exec_id,
                    "nodeId": node_id,
                    "output": str(output)[:500],
                    "timestamp": time.time(),
                })
                # Enqueue children
                for child_id in outgoing.get(node_id, []):
                    if child_id not in visited:
                        queue.append(child_id)
            except Exception as ex:
                last_error = str(ex)
                success = False
                await self._emit({
                    "type": "step_failed",
                    "workflowId": wf_id,
                    "executionId": exec_id,
                    "nodeId": node_id,
                    "error": last_error,
                    "timestamp": time.time(),
                })
                # Check onError setting
                settings = definition.get("settings", {})
                if settings.get("onError", "stop") == "stop":
                    break

        self.db.finish_execution(exec_id, success, last_error)
        self.db.increment_execution_count(wf_id, success)

        final_type = "execution_completed" if success else "execution_failed"
        await self._emit({
            "type": final_type,
            "workflowId": wf_id,
            "executionId": exec_id,
            "success": success,
            "error": last_error,
            "timestamp": time.time(),
        })

        return {"success": success, "executionId": exec_id, "error": last_error}

    async def _run_node(self, node: Dict, context: Dict) -> Any:
        """Simulate node execution. Real integrations hook in here."""
        node_type = node.get("type", "")
        config = node.get("config", {})

        if node_type.startswith("trigger."):
            return {"triggered": True}

        if node_type == "action.send_message":
            message = config.get("message", "")
            return {"sent": True, "message": message}

        if node_type == "logic.wait":
            secs = float(config.get("seconds", 1))
            await asyncio.sleep(min(secs, 30))  # max 30s per node in a workflow
            return {"waited": secs}

        if node_type == "action.http_request":
            try:
                import aiohttp  # optional dependency
            except ImportError:
                return {"error": "aiohttp not installed. Run: pip install aiohttp"}
            url = config.get("url", "")
            method = config.get("method", "GET")
            try:
                headers = json.loads(config.get("headers", "{}"))
                body = config.get("body")
                body_data = json.loads(body) if body and body != "{}" else None
            except Exception:
                headers = {}
                body_data = None
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=headers, json=body_data, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    text = await resp.text()
                    return {"status": resp.status, "body": text[:2000]}

        if node_type == "action.write_file":
            path = config.get("path", "output.txt")
            content = config.get("content", "")
            mode = "a" if config.get("mode") == "append" else "w"
            with open(path, mode, encoding="utf-8") as f:
                f.write(content)
            return {"written": True, "path": path}

        if node_type == "transform.set_variable":
            name = config.get("name", "var")
            value = config.get("value", "")
            context[name] = value
            return {name: value}

        # Default: pass through
        return {"type": node_type, "status": "executed"}


# ---------------------------------------------------------------------------
# Module-level singleton (lazy-initialized in server.py)
# ---------------------------------------------------------------------------
_db_instance: Optional[WorkflowDB] = None
_executor_instance: Optional[WorkflowExecutor] = None


def get_db() -> WorkflowDB:
    global _db_instance
    if _db_instance is None:
        _db_instance = WorkflowDB()
    return _db_instance


def get_executor(event_callback: Optional[EventCallback] = None) -> WorkflowExecutor:
    global _executor_instance
    if _executor_instance is None or event_callback is not None:
        _executor_instance = WorkflowExecutor(get_db(), event_callback)
    return _executor_instance
