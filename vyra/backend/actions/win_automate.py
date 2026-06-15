"""
win_automate.py — UI Automation (UIA) for VYRA: find windows, click buttons,
read text from any UI element reliably. Uses pywinauto + Win32 accessibility APIs.
Falls back to PyAutoGUI for basic operations.
"""
import json
import subprocess
import time


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.stdout.strip() or r.stderr.strip() or "Done."
    except Exception as e:
        return f"Error: {e}"


def _get_app(title: str = "", exe: str = "", timeout: float = 5.0):
    """Find a pywinauto Application by window title or exe name."""
    from pywinauto import Application, findwindows, Desktop
    windows = Desktop(backend="uia").windows()
    for w in windows:
        try:
            if title and title.lower() in w.window_text().lower():
                return Application(backend="uia").connect(handle=w.handle), w
            if exe and exe.lower() in w.element_info.process_id.__class__.__name__.lower():
                pass
        except Exception:
            pass
    return None, None


def win_automate(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action    = parameters.get("action", "").lower().strip()
    title     = parameters.get("window_title", "").strip()
    element   = parameters.get("element", "").strip()
    text      = parameters.get("text", "").strip()
    wait_secs = float(parameters.get("wait_seconds", 2.0))

    try:
        # ── list_windows ──────────────────────────────────────────────────────
        if action == "list_windows":
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                lines = ["Open Windows:"]
                for w in windows:
                    try:
                        wt = w.window_text()
                        if wt.strip():
                            lines.append(f"  [{w.handle}] {wt}")
                    except Exception:
                        pass
                return _ok("\n".join(lines), action)
            except ImportError:
                import pygetwindow as gw
                wins = [w.title for w in gw.getAllWindows() if w.title.strip()]
                return _ok("Open Windows:\n" + "\n".join(f"  {w}" for w in wins), action)

        # ── find_window ───────────────────────────────────────────────────────
        elif action == "find_window":
            if not title:
                return _err("'window_title' is required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                matches = [w for w in windows if title.lower() in w.window_text().lower()]
                if matches:
                    lines = [f"Found {len(matches)} window(s) matching '{title}':"]
                    for w in matches:
                        lines.append(f"  [{w.handle}] '{w.window_text()}' — {w.rectangle()}")
                    return _ok("\n".join(lines), action)
                return _ok(f"No window matching '{title}'.", action)
            except ImportError:
                return _err("pywinauto not installed. Run: pip install pywinauto", action)

        # ── focus_window ──────────────────────────────────────────────────────
        elif action == "focus_window":
            if not title:
                return _err("'window_title' is required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                for w in windows:
                    if title.lower() in w.window_text().lower():
                        w.set_focus()
                        return _ok(f"Window '{w.window_text()}' focused.", action)
                return _err(f"Window '{title}' not found.", action)
            except ImportError:
                import pygetwindow as gw
                wins = [w for w in gw.getWindowsWithTitle(title) if w.title]
                if wins:
                    wins[0].activate()
                    return _ok(f"Window '{title}' activated.", action)
                return _err(f"Window '{title}' not found.", action)

        # ── click_element ─────────────────────────────────────────────────────
        elif action == "click_element":
            if not element:
                return _err("'element' (button/control name or AutomationId) is required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                target_win = None
                for w in windows:
                    if not title or title.lower() in w.window_text().lower():
                        target_win = w
                        break
                if not target_win:
                    return _err(f"Window '{title}' not found.", action)
                ctrl = target_win.child_window(title=element, control_type="Button")
                ctrl.wait("enabled", timeout=wait_secs)
                ctrl.click_input()
                return _ok(f"Clicked '{element}' in '{target_win.window_text()}'.", action)
            except ImportError:
                return _err("pywinauto not installed. Run: pip install pywinauto", action)

        # ── type_in_element ───────────────────────────────────────────────────
        elif action == "type_in_element":
            if not element or not text:
                return _err("'element' and 'text' are required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                target_win = None
                for w in windows:
                    if not title or title.lower() in w.window_text().lower():
                        target_win = w
                        break
                if not target_win:
                    return _err(f"Window '{title}' not found.", action)
                ctrl = target_win.child_window(best_match=element)
                ctrl.wait("enabled", timeout=wait_secs)
                ctrl.set_edit_text(text)
                return _ok(f"Typed '{text[:30]}...' into '{element}'.", action)
            except ImportError:
                return _err("pywinauto not installed. Run: pip install pywinauto", action)

        # ── read_element_text ─────────────────────────────────────────────────
        elif action == "read_element_text":
            if not element:
                return _err("'element' is required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                for w in windows:
                    if not title or title.lower() in w.window_text().lower():
                        try:
                            ctrl = w.child_window(best_match=element)
                            text_val = ctrl.window_text()
                            return _ok(f"Text of '{element}': {text_val}", action)
                        except Exception as e:
                            pass
                return _err(f"Element '{element}' not found in '{title}'.", action)
            except ImportError:
                return _err("pywinauto not installed. Run: pip install pywinauto", action)

        # ── read_all_elements ─────────────────────────────────────────────────
        elif action == "read_all_elements":
            """List all UI elements in a window — useful for discovering element names."""
            if not title:
                return _err("'window_title' is required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                for w in windows:
                    if title.lower() in w.window_text().lower():
                        lines = [f"Elements in '{w.window_text()}':"]
                        try:
                            for ctrl in w.descendants():
                                try:
                                    ct = ctrl.element_info.control_type
                                    name = ctrl.window_text()
                                    if name.strip():
                                        lines.append(f"  [{ct}] {name}")
                                except Exception:
                                    pass
                        except Exception as e:
                            lines.append(f"  (error enumerating: {e})")
                        return _ok("\n".join(lines[:200]), action)
                return _err(f"Window '{title}' not found.", action)
            except ImportError:
                return _err("pywinauto not installed. Run: pip install pywinauto", action)

        # ── close_window ──────────────────────────────────────────────────────
        elif action == "close_window":
            if not title:
                return _err("'window_title' is required.", action)
            try:
                from pywinauto import Desktop
                windows = Desktop(backend="uia").windows()
                closed = []
                for w in windows:
                    if title.lower() in w.window_text().lower():
                        w.close()
                        closed.append(w.window_text())
                return _ok(f"Closed: {', '.join(closed)}" if closed else f"No window '{title}' found.", action)
            except ImportError:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(title)
                for w in wins:
                    w.close()
                return _ok(f"Closed {len(wins)} window(s) matching '{title}'.", action)

        # ── maximize_window ───────────────────────────────────────────────────
        elif action == "maximize_window":
            if not title:
                return _err("'window_title' is required.", action)
            import pyautogui
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    wins[0].maximize()
                    return _ok(f"Maximized: {wins[0].title}", action)
                return _err(f"Window '{title}' not found.", action)
            except ImportError:
                return _err("pygetwindow not installed. Run: pip install pygetwindow", action)

        # ── minimize_window ───────────────────────────────────────────────────
        elif action == "minimize_window":
            if not title:
                return _err("'window_title' is required.", action)
            try:
                import pygetwindow as gw
                wins = gw.getWindowsWithTitle(title)
                if wins:
                    wins[0].minimize()
                    return _ok(f"Minimized: {wins[0].title}", action)
                return _err(f"Window '{title}' not found.", action)
            except ImportError:
                return _err("pygetwindow not installed.", action)

        # ── send_keys_to_window ───────────────────────────────────────────────
        elif action == "send_keys_to_window":
            if not title or not text:
                return _err("'window_title' and 'text' (keys to send) are required.", action)
            try:
                from pywinauto import Desktop
                import pywinauto.keyboard as kb
                windows = Desktop(backend="uia").windows()
                for w in windows:
                    if title.lower() in w.window_text().lower():
                        w.set_focus()
                        kb.send_keys(text)
                        return _ok(f"Keys sent to '{w.window_text()}': {text}", action)
                return _err(f"Window '{title}' not found.", action)
            except ImportError:
                return _err("pywinauto not installed. Run: pip install pywinauto", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_windows, find_window, focus_window, "
                "click_element, type_in_element, read_element_text, read_all_elements, "
                "close_window, maximize_window, minimize_window, send_keys_to_window",
                action)

    except Exception as e:
        return _err(str(e), action)
