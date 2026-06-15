"""
win_startup.py — Startup program management for VYRA Windows control.
Reads/writes HKCU Run key and Startup folder; mirrors Task Manager's Startup tab.
"""
import os
import json
import winreg

_RUN_KEY   = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_RUN_APPROVED_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
_STARTUP_FOLDER = os.path.join(
    os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _read_run_key(hive, key_path: str) -> dict:
    result = {}
    try:
        with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ) as k:
            i = 0
            while True:
                try:
                    name, data, _ = winreg.EnumValue(k, i)
                    result[name] = data
                    i += 1
                except OSError:
                    break
    except FileNotFoundError:
        pass
    return result


def _is_approved(name: str) -> bool:
    """Check StartupApproved key — disabled items have first byte = 03."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_APPROVED_KEY, 0, winreg.KEY_READ) as k:
            data, _ = winreg.QueryValueEx(k, name)
            if isinstance(data, (bytes, bytearray)):
                return data[0] == 0x02  # 02 = enabled, 03 = disabled
    except (FileNotFoundError, OSError):
        pass
    return True  # Not in Approved key = enabled


def _set_approved(name: str, enabled: bool):
    """Write to StartupApproved key to enable/disable without deleting the Run entry."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_APPROVED_KEY,
                            0, winreg.KEY_SET_VALUE | winreg.KEY_READ) as k:
            # Read existing data to preserve timestamp bytes 4-12
            try:
                existing, _ = winreg.QueryValueEx(k, name)
                data = bytearray(existing) if isinstance(existing, (bytes, bytearray)) else bytearray(12)
            except OSError:
                data = bytearray(12)
            data[0] = 0x02 if enabled else 0x03
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, bytes(data))
    except FileNotFoundError:
        # Create the key
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_APPROVED_KEY) as k:
            data = bytearray(12)
            data[0] = 0x02 if enabled else 0x03
            winreg.SetValueEx(k, name, 0, winreg.REG_BINARY, bytes(data))


def win_startup(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action       = parameters.get("action", "").lower().strip()
    program_name = parameters.get("program_name", "").strip()
    program_path = parameters.get("program_path", "").strip()

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            lines = ["=== Registry (HKCU\\Run) ==="]
            user_run = _read_run_key(winreg.HKEY_CURRENT_USER, _RUN_KEY)
            for name, cmd in sorted(user_run.items()):
                status = "ENABLED" if _is_approved(name) else "DISABLED"
                lines.append(f"  [{status}] {name}: {cmd}")

            lines.append("\n=== Registry (HKLM\\Run — read-only) ===")
            sys_run = _read_run_key(winreg.HKEY_LOCAL_MACHINE, _RUN_KEY)
            for name, cmd in sorted(sys_run.items()):
                lines.append(f"  [SYSTEM] {name}: {cmd}")

            lines.append("\n=== Startup Folder ===")
            if os.path.isdir(_STARTUP_FOLDER):
                items = os.listdir(_STARTUP_FOLDER)
                for item in sorted(items):
                    lines.append(f"  {item}")
            else:
                lines.append("  (folder not found)")

            return _ok("\n".join(lines), action)

        # ── enable ────────────────────────────────────────────────────────────
        elif action == "enable":
            if not program_name:
                return _err("'program_name' is required.", action)
            user_run = _read_run_key(winreg.HKEY_CURRENT_USER, _RUN_KEY)
            if program_name not in user_run:
                return _err(f"'{program_name}' not found in HKCU Run key.", action)
            _set_approved(program_name, True)
            return _ok(f"Startup entry enabled: {program_name}", action)

        # ── disable ───────────────────────────────────────────────────────────
        elif action == "disable":
            if not program_name:
                return _err("'program_name' is required.", action)
            user_run = _read_run_key(winreg.HKEY_CURRENT_USER, _RUN_KEY)
            if program_name not in user_run:
                return _err(f"'{program_name}' not found in HKCU Run key.", action)
            _set_approved(program_name, False)
            return _ok(f"Startup entry disabled: {program_name}", action)

        # ── add ───────────────────────────────────────────────────────────────
        elif action == "add":
            if not program_name or not program_path:
                return _err("Both 'program_name' and 'program_path' are required.", action)
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY,
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, program_name, 0, winreg.REG_SZ, program_path)
            _set_approved(program_name, True)
            return _ok(f"Startup entry added: {program_name} → {program_path}", action)

        # ── remove ────────────────────────────────────────────────────────────
        elif action == "remove":
            if not program_name:
                return _err("'program_name' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Removing startup entry '{program_name}'. Set confirmed=true to proceed.", action)
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY,
                                    0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, program_name)
                # Also clean up Approved key
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_APPROVED_KEY,
                                        0, winreg.KEY_SET_VALUE) as k:
                        winreg.DeleteValue(k, program_name)
                except (FileNotFoundError, OSError):
                    pass
                return _ok(f"Startup entry removed: {program_name}", action)
            except FileNotFoundError:
                return _err(f"'{program_name}' not found in startup registry.", action)

        # ── add_to_folder ─────────────────────────────────────────────────────
        elif action == "add_to_folder":
            """Create a .lnk shortcut in the user Startup folder."""
            if not program_name or not program_path:
                return _err("'program_name' and 'program_path' are required.", action)
            import subprocess
            lnk_path = os.path.join(_STARTUP_FOLDER, f"{program_name}.lnk")
            ps = (
                f'$ws = New-Object -ComObject WScript.Shell; '
                f'$s = $ws.CreateShortcut("{lnk_path}"); '
                f'$s.TargetPath = "{program_path}"; '
                f'$s.Save()'
            )
            subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                           capture_output=True, timeout=15)
            return _ok(f"Shortcut created in Startup folder: {lnk_path}", action)

        # ── remove_from_folder ────────────────────────────────────────────────
        elif action == "remove_from_folder":
            if not program_name:
                return _err("'program_name' is required.", action)
            if not parameters.get("confirmed"):
                return _err("Set confirmed=true to remove from Startup folder.", action)
            # Try with and without .lnk
            removed = []
            for fname in [program_name, f"{program_name}.lnk"]:
                fp = os.path.join(_STARTUP_FOLDER, fname)
                if os.path.exists(fp):
                    os.remove(fp)
                    removed.append(fname)
            if removed:
                return _ok(f"Removed from Startup folder: {', '.join(removed)}", action)
            return _err(f"'{program_name}' not found in Startup folder.", action)

        # ── open_folder ───────────────────────────────────────────────────────
        elif action == "open_folder":
            import subprocess
            subprocess.Popen(["explorer", _STARTUP_FOLDER])
            return _ok(f"Opened Startup folder: {_STARTUP_FOLDER}", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, enable, disable, add, remove, "
                "add_to_folder, remove_from_folder, open_folder",
                action)

    except Exception as e:
        return _err(str(e), action)