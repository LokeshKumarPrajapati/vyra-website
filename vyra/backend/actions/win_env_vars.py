"""
win_env_vars.py — Environment variable management for VYRA Windows control.
Reads/writes User and System environment variables via winreg + os.environ.
Broadcasts WM_SETTINGCHANGE so running processes pick up changes immediately.
"""
import os
import json
import ctypes
import winreg

# Registry paths
_USER_ENV_KEY  = r"Environment"
_SYS_ENV_KEY   = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"

# WM_SETTINGCHANGE broadcast so Explorer + running apps see new env vars
_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _broadcast_env_change():
    """Notify all top-level windows that environment has changed."""
    try:
        ctypes.windll.user32.SendMessageTimeoutW(
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, "Environment", 0x0002, 5000, None)
    except Exception:
        pass  # Non-critical; new processes will still see the change


def _read_reg_env(hive, key_path: str) -> dict:
    """Return all name→value pairs from a registry env key."""
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


def _write_reg_env(hive, key_path: str, name: str, value: str, reg_type=winreg.REG_EXPAND_SZ):
    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, reg_type, value)


def _delete_reg_env(hive, key_path: str, name: str):
    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, name)


def win_env_vars(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()
    name   = parameters.get("name", "").strip()
    value  = parameters.get("value", "")

    try:
        # ── list_user ─────────────────────────────────────────────────────────
        if action == "list_user":
            env = _read_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY)
            lines = [f"{k} = {v}" for k, v in sorted(env.items())]
            return _ok("\n".join(lines) if lines else "No user environment variables found.", action)

        # ── list_system ───────────────────────────────────────────────────────
        elif action == "list_system":
            env = _read_reg_env(winreg.HKEY_LOCAL_MACHINE, _SYS_ENV_KEY)
            lines = [f"{k} = {v}" for k, v in sorted(env.items())]
            return _ok("\n".join(lines) if lines else "No system environment variables found.", action)

        # ── get ───────────────────────────────────────────────────────────────
        elif action == "get":
            if not name:
                return _err("'name' parameter is required.", action)
            # Check live process env first, then registry
            live = os.environ.get(name)
            user_env = _read_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY)
            sys_env  = _read_reg_env(winreg.HKEY_LOCAL_MACHINE, _SYS_ENV_KEY)
            parts = []
            if live is not None:
                parts.append(f"Live process:  {live}")
            if name in user_env:
                parts.append(f"User registry: {user_env[name]}")
            if name in sys_env:
                parts.append(f"System registry: {sys_env[name]}")
            if not parts:
                return _ok(f"Variable '{name}' not found.", action)
            return _ok("\n".join(parts), action)

        # ── set_user ──────────────────────────────────────────────────────────
        elif action == "set_user":
            if not name:
                return _err("'name' parameter is required.", action)
            reg_type = winreg.REG_SZ if "%" not in value else winreg.REG_EXPAND_SZ
            _write_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY, name, value, reg_type)
            _broadcast_env_change()
            return _ok(f"User env var set: {name} = {value}", action)

        # ── set_system ────────────────────────────────────────────────────────
        elif action == "set_system":
            if not name:
                return _err("'name' parameter is required.", action)
            if not parameters.get("confirmed"):
                return _err(
                    f"Setting system env var '{name}' affects all users. "
                    "Set confirmed=true to proceed.", action)
            try:
                reg_type = winreg.REG_SZ if "%" not in value else winreg.REG_EXPAND_SZ
                _write_reg_env(winreg.HKEY_LOCAL_MACHINE, _SYS_ENV_KEY, name, value, reg_type)
                _broadcast_env_change()
                return _ok(f"System env var set: {name} = {value}", action)
            except PermissionError:
                return _err(
                    "Permission denied. Run VYRA as Administrator to set system variables.", action)

        # ── delete_user ───────────────────────────────────────────────────────
        elif action == "delete_user":
            if not name:
                return _err("'name' parameter is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Deleting user env var '{name}'. Set confirmed=true to proceed.", action)
            try:
                _delete_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY, name)
                _broadcast_env_change()
                return _ok(f"User env var deleted: {name}", action)
            except FileNotFoundError:
                return _err(f"Variable '{name}' not found in user environment.", action)

        # ── delete_system ─────────────────────────────────────────────────────
        elif action == "delete_system":
            if not name:
                return _err("'name' parameter is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Deleting system env var '{name}'. Set confirmed=true to proceed.", action)
            try:
                _delete_reg_env(winreg.HKEY_LOCAL_MACHINE, _SYS_ENV_KEY, name)
                _broadcast_env_change()
                return _ok(f"System env var deleted: {name}", action)
            except PermissionError:
                return _err("Permission denied. Run VYRA as Administrator.", action)
            except FileNotFoundError:
                return _err(f"Variable '{name}' not found in system environment.", action)

        # ── append_path ───────────────────────────────────────────────────────
        elif action == "append_path":
            """Append a directory to the user PATH (avoids duplicates)."""
            if not value:
                return _err("'value' parameter required (directory to append).", action)
            user_env = _read_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY)
            current_path = user_env.get("PATH", "")
            entries = [e for e in current_path.split(";") if e.strip()]
            if value in entries:
                return _ok(f"'{value}' is already in user PATH.", action)
            entries.append(value)
            new_path = ";".join(entries)
            _write_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY, "PATH", new_path, winreg.REG_EXPAND_SZ)
            _broadcast_env_change()
            return _ok(f"Appended to user PATH: {value}", action)

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            """Search for env vars containing 'name' as substring (case-insensitive)."""
            if not name:
                return _err("'name' parameter required (search term).", action)
            query = name.lower()
            user_env = _read_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY)
            sys_env  = _read_reg_env(winreg.HKEY_LOCAL_MACHINE, _SYS_ENV_KEY)
            results = []
            for k, v in user_env.items():
                if query in k.lower() or query in v.lower():
                    results.append(f"[USER]   {k} = {v}")
            for k, v in sys_env.items():
                if query in k.lower() or query in v.lower():
                    results.append(f"[SYSTEM] {k} = {v}")
            return _ok("\n".join(results) if results else f"No matches for '{name}'.", action)

        # ── list_path_entries ─────────────────────────────────────────────────
        elif action == "list_path_entries":
            """Show all PATH directories (user + system), numbered for clarity."""
            user_env = _read_reg_env(winreg.HKEY_CURRENT_USER, _USER_ENV_KEY)
            sys_env  = _read_reg_env(winreg.HKEY_LOCAL_MACHINE, _SYS_ENV_KEY)
            lines = []
            for i, e in enumerate(user_env.get("PATH", "").split(";"), 1):
                if e.strip():
                    lines.append(f"[USER #{i:>3}] {e}")
            for i, e in enumerate(sys_env.get("PATH", "").split(";"), 1):
                if e.strip():
                    lines.append(f"[SYS  #{i:>3}] {e}")
            return _ok("\n".join(lines) if lines else "PATH is empty.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_user, list_system, get, set_user, "
                "set_system, delete_user, delete_system, append_path, search, list_path_entries",
                action)

    except Exception as e:
        return _err(str(e), action)
