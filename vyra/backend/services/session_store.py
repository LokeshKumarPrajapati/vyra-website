"""
backend/services/session_store.py

Persistent session state for JARVIS.
Stores and restores:
  - last active JARVIS route (e.g. "chat", "dashboard")
  - last VS Code workspace (name + path)
  - open files list
  - session timestamp

On double-clap restore:
  1. Frontend navigates back to last_route
  2. If VS Code is already open → bring window to front
  3. If VS Code is closed but path known → re-open with `code {path}`
  4. WelcomeOverlay shows project name in greeting
"""

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

_BACKEND_DIR = Path(os.path.dirname(os.path.abspath(__file__))).parent
_SESSION_PATH = _BACKEND_DIR / "data" / "session_state.json"

# User-targeted paths only — avoids slow full-drive scans
_SEARCH_ROOTS = [
    os.path.expanduser("~\\Desktop"),
    os.path.expanduser("~\\Documents"),
    os.path.expanduser("~\\Projects"),
    os.path.expanduser("~\\code"),
    os.path.expanduser("~\\dev"),
    os.path.expanduser("~\\source"),
]

_SCANDIR_LIMIT = 200  # max entries per root to avoid slow D:\ style scans

# In-memory state cache — loaded lazily on first access, persisted on mutation
_state: Optional[dict] = None


def _default_state() -> dict:
    return {
        "last_route": "dashboard",
        "last_route_ts": 0,
        "vscode": {
            "workspace_name": "",
            "workspace_path": "",
            "window_title": "",
            "last_seen_ts": 0,
        },
        "open_files": [],
        "session_ts": 0,
    }


def load() -> dict:
    """Return in-memory state, loading from disk once if needed."""
    global _state
    if _state is None:
        try:
            _state = json.loads(_SESSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            _state = _default_state()
    return _state


def save(state: dict) -> None:
    """Persist state to disk and update the in-memory cache."""
    global _state
    _state = state
    _SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SESSION_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def update_route(route: str) -> None:
    """Called whenever the user navigates to a different JARVIS page."""
    state = load()
    state["last_route"] = route
    state["last_route_ts"] = int(time.time() * 1000)
    save(state)


def update_vscode(window_title: str, workspace_name: str) -> None:
    """
    Called by passive_monitor when a VS Code window is detected.
    Tries to resolve the workspace folder path on disk.
    """
    state = load()
    vs = state.setdefault("vscode", {})
    vs["window_title"]   = window_title
    vs["workspace_name"] = workspace_name
    vs["last_seen_ts"]   = int(time.time() * 1000)

    # Resolve path if we don't have one yet, or the workspace name changed
    if not vs.get("workspace_path") or vs.get("workspace_name") != workspace_name:
        path = _find_workspace_path(workspace_name)
        if path:
            vs["workspace_path"] = path
            print(f"[SessionStore] Resolved VS Code workspace → {path}")

    save(state)


def _find_workspace_path(name: str) -> Optional[str]:
    """
    Search user-targeted locations for a folder whose name contains `name`.
    Returns the first match, or None.
    """
    if not name:
        return None
    name_lower = name.lower().strip()

    for root in _SEARCH_ROOTS:
        if not os.path.exists(root):
            continue
        try:
            count = 0
            for entry in os.scandir(root):
                if entry.is_dir() and name_lower in entry.name.lower():
                    return entry.path
                count += 1
                if count >= _SCANDIR_LIMIT:
                    break
        except (PermissionError, OSError):
            continue

    return None


def restore_vscode_workspace() -> dict:
    """
    Restore the last VS Code workspace:
      1. If VS Code is currently open → bring its window to front
      2. If VS Code is closed + path known → launch `code {path}`
      3. Otherwise → do nothing

    Returns: {"action": "focused"|"launched"|"not_found", "workspace": name, "path": path}
    """
    state = load()
    vs = state.get("vscode", {})
    workspace_name = vs.get("workspace_name", "")
    workspace_path = vs.get("workspace_path", "")

    if not workspace_name:
        return {"action": "not_found", "workspace": "", "path": ""}

    # ── 1. Try to focus an existing VS Code window ────────────────────────────
    try:
        import pygetwindow as gw
        vscode_windows = [
            w for w in gw.getAllWindows()
            if "Visual Studio Code" in (w.title or "")
        ]
        if vscode_windows:
            target = next(
                (w for w in vscode_windows if workspace_name.lower() in (w.title or "").lower()),
                vscode_windows[0],
            )
            try:
                target.restore()
                target.activate()
                print(f"[SessionStore] Focused VS Code window: {target.title}")
                return {"action": "focused", "workspace": workspace_name, "path": workspace_path}
            except Exception as e:
                print(f"[SessionStore] Focus failed: {e}")
    except Exception as e:
        print(f"[SessionStore] pygetwindow error: {e}")

    # ── 2. Launch VS Code with the workspace path ─────────────────────────────
    launch_path = workspace_path or workspace_name
    try:
        subprocess.Popen(
            ["code", launch_path],
            shell=True,
            creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0,
        )
        print(f"[SessionStore] Launched VS Code → {launch_path}")
        return {"action": "launched", "workspace": workspace_name, "path": launch_path}
    except Exception as e:
        print(f"[SessionStore] Could not launch VS Code: {e}")

    return {"action": "not_found", "workspace": workspace_name, "path": workspace_path}
