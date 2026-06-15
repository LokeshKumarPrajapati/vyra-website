"""
backend/services/passive_monitor.py

Passive background monitor: logs the active window title + process every 30s
to data/passive_log.jsonl.  Runs forever as an asyncio task; never produces
TTS or any user-facing output — pure silent logging.

Also detects VS Code windows and updates the session workspace in session_store
so double-clap can restore the last open project.

pygetwindow is used inside asyncio.to_thread() because it is synchronous/blocking.
Log rotates automatically at 10 MB.
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

LOG_INTERVAL_SEC = 30
_LOG_PATH = Path(os.path.dirname(os.path.abspath(__file__))).parent / "data" / "passive_log.jsonl"


def _parse_vscode_workspace(title: str) -> Optional[str]:
    """
    Extract workspace name from a VS Code window title.
    Title format: "[filename — ]workspace — Visual Studio Code"
    Returns workspace name, or None if not a VS Code window.
    """
    if "Visual Studio Code" not in title:
        return None
    parts = [p.strip() for p in title.split("—")]  # em-dash separator
    if len(parts) >= 2 and parts[-1] == "Visual Studio Code":
        return parts[-2]
    return None


def _get_active_window_info() -> dict:
    """
    Runs synchronously — call via asyncio.to_thread().
    Returns dict with window title, process name, and optional vscode_workspace.
    """
    try:
        import pygetwindow as gw
        win = gw.getActiveWindow()
        if win is None:
            return {"title": "", "process": ""}
        title = getattr(win, "title", "") or ""
        proc_name = ""
        try:
            import ctypes
            import psutil
            hwnd = getattr(win, "_hWnd", None)
            if hwnd:
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    proc_name = psutil.Process(pid.value).name()
        except Exception:
            pass
        result: dict = {"title": title, "process": proc_name}
        ws = _parse_vscode_workspace(title)
        if ws:
            result["vscode_workspace"] = ws
        return result
    except Exception as e:
        return {"title": "", "process": "", "error": str(e)}


async def run_passive_monitor():
    """
    Endless asyncio loop. Logs active window context every LOG_INTERVAL_SEC seconds.
    One JSON line per tick to data/passive_log.jsonl.
    """
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    print(f"[PassiveMonitor] Started — logging every {LOG_INTERVAL_SEC}s to {_LOG_PATH}")

    while True:
        await asyncio.sleep(LOG_INTERVAL_SEC)
        try:
            info = await asyncio.to_thread(_get_active_window_info)
            entry = {
                "ts":      int(time.time() * 1000),
                "iso":     time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                "title":   info.get("title", ""),
                "process": info.get("process", ""),
            }

            # Update session store when VS Code is the active window
            ws_name = info.get("vscode_workspace")
            if ws_name:
                try:
                    from services import session_store
                    session_store.update_vscode(
                        window_title=info.get("title", ""),
                        workspace_name=ws_name,
                    )
                    entry["vscode_workspace"] = ws_name
                except Exception as e:
                    print(f"[PassiveMonitor] session_store error: {e}")

            # Rotate at 10 MB to prevent unbounded growth
            try:
                if _LOG_PATH.stat().st_size > 10 * 1024 * 1024:
                    _LOG_PATH.rename(_LOG_PATH.with_suffix(".jsonl.bak"))
                    print("[PassiveMonitor] Log rotated.")
            except (FileNotFoundError, OSError):
                pass

            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")

        except asyncio.CancelledError:
            print("[PassiveMonitor] Stopped.")
            break
        except Exception as e:
            print(f"[PassiveMonitor] Error: {e}")
