"""
win_registry.py — Windows Registry read/write/query for VYRA.
Uses stdlib winreg. Safety: hard-blocks critical system hives.
"""
import json
import winreg
import subprocess

_HIVE_MAP = {
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKU":  winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
}

_TYPE_MAP = {
    "REG_SZ":        winreg.REG_SZ,
    "REG_DWORD":     winreg.REG_DWORD,
    "REG_BINARY":    winreg.REG_BINARY,
    "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ,
    "REG_MULTI_SZ":  winreg.REG_MULTI_SZ,
    "REG_QWORD":     winreg.REG_QWORD,
}

_TYPE_NAMES = {v: k for k, v in _TYPE_MAP.items()}

# Keys that must NEVER be touched (hard block, no override)
_FORBIDDEN_KEYS = {
    r"SYSTEM\SAM",
    r"SYSTEM\SECURITY",
    r"SYSTEM\CurrentControlSet\Control\Lsa",
    r"SAM",
    r"SECURITY",
}


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _is_forbidden(key: str) -> bool:
    key_upper = key.upper().replace("/", "\\").strip("\\")
    return any(key_upper.startswith(f.upper()) for f in _FORBIDDEN_KEYS)


def _get_hive(hive_str: str):
    hive_str = hive_str.upper().strip()
    # Support full names too
    full_map = {
        "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
        "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
        "HKEY_USERS": winreg.HKEY_USERS,
        "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
    }
    return _HIVE_MAP.get(hive_str) or full_map.get(hive_str)


def win_registry(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action     = parameters.get("action", "").lower().strip()
    hive_str   = parameters.get("hive", "HKCU").upper().strip()
    key        = parameters.get("key", "").strip().strip("\\")
    value_name = parameters.get("value_name", "")
    value_data = parameters.get("value_data", "")
    value_type = parameters.get("value_type", "REG_SZ").upper()

    hive = _get_hive(hive_str)
    if hive is None:
        return _err(f"Invalid hive '{hive_str}'. Use: HKCU, HKLM, HKCR, HKU, HKCC", action)

    if _is_forbidden(key):
        return _err(f"Access to '{key}' is forbidden for safety reasons.", action)

    try:
        # ── read ──────────────────────────────────────────────────────────────
        if action == "read":
            if not key:
                return _err("'key' is required.", action)
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
                    if value_name:
                        data, reg_type = winreg.QueryValueEx(k, value_name)
                        type_name = _TYPE_NAMES.get(reg_type, str(reg_type))
                        return _ok(f"{value_name} [{type_name}] = {data}", action)
                    else:
                        # Read all values
                        lines = [f"Key: {hive_str}\\{key}"]
                        i = 0
                        while True:
                            try:
                                name, data, reg_type = winreg.EnumValue(k, i)
                                type_name = _TYPE_NAMES.get(reg_type, str(reg_type))
                                lines.append(f"  {name or '(Default)'} [{type_name}] = {data}")
                                i += 1
                            except OSError:
                                break
                        if len(lines) == 1:
                            lines.append("  (no values)")
                        return _ok("\n".join(lines), action)
            except FileNotFoundError:
                return _err(f"Key not found: {hive_str}\\{key}", action)
            except PermissionError:
                return _err("Permission denied. Run VYRA as Administrator for this key.", action)

        # ── write ─────────────────────────────────────────────────────────────
        elif action == "write":
            if not key or not value_name:
                return _err("'key' and 'value_name' are required.", action)
            if hive_str == "HKLM" and not parameters.get("confirmed"):
                return _err("Writing to HKLM affects all users. Set confirmed=true.", action)
            if value_type not in _TYPE_MAP:
                return _err(f"Unknown value_type '{value_type}'. Use: {', '.join(_TYPE_MAP)}", action)
            reg_type = _TYPE_MAP[value_type]
            # Type coercion
            if reg_type in (winreg.REG_DWORD, winreg.REG_QWORD):
                try:
                    typed_data = int(value_data)
                except (ValueError, TypeError):
                    return _err(f"'{value_type}' requires an integer value.", action)
            elif reg_type == winreg.REG_MULTI_SZ:
                typed_data = value_data if isinstance(value_data, list) else str(value_data).split(";")
            elif reg_type == winreg.REG_BINARY:
                if isinstance(value_data, str):
                    typed_data = bytes.fromhex(value_data.replace(" ", ""))
                else:
                    typed_data = bytes(value_data)
            else:
                typed_data = str(value_data)

            try:
                with winreg.CreateKeyEx(hive, key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, value_name, 0, reg_type, typed_data)
                return _ok(f"Written: {hive_str}\\{key}\\{value_name} = {typed_data}", action)
            except PermissionError:
                return _err("Permission denied. Run VYRA as Administrator.", action)

        # ── delete_value ──────────────────────────────────────────────────────
        elif action == "delete_value":
            if not key or not value_name:
                return _err("'key' and 'value_name' are required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete value '{value_name}' from {hive_str}\\{key}? Set confirmed=true.", action)
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.DeleteValue(k, value_name)
                return _ok(f"Deleted: {hive_str}\\{key}\\{value_name}", action)
            except FileNotFoundError:
                return _err(f"Value '{value_name}' not found.", action)
            except PermissionError:
                return _err("Permission denied.", action)

        # ── list_keys ─────────────────────────────────────────────────────────
        elif action == "list_keys":
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ) as k:
                    subkeys = []
                    i = 0
                    while True:
                        try:
                            subkeys.append(winreg.EnumKey(k, i))
                            i += 1
                        except OSError:
                            break
                if subkeys:
                    return _ok(f"Subkeys of {hive_str}\\{key}:\n" + "\n".join(f"  {s}" for s in sorted(subkeys)), action)
                return _ok(f"No subkeys under {hive_str}\\{key}.", action)
            except FileNotFoundError:
                return _err(f"Key not found: {hive_str}\\{key}", action)

        # ── create_key ────────────────────────────────────────────────────────
        elif action == "create_key":
            if not key:
                return _err("'key' is required.", action)
            if hive_str == "HKLM" and not parameters.get("confirmed"):
                return _err("Creating HKLM key affects all users. Set confirmed=true.", action)
            try:
                winreg.CreateKeyEx(hive, key, 0, winreg.KEY_WRITE)
                return _ok(f"Key created: {hive_str}\\{key}", action)
            except PermissionError:
                return _err("Permission denied.", action)

        # ── delete_key ────────────────────────────────────────────────────────
        elif action == "delete_key":
            if not key:
                return _err("'key' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete entire key {hive_str}\\{key}? Set confirmed=true.", action)
            try:
                winreg.DeleteKey(hive, key)
                return _ok(f"Key deleted: {hive_str}\\{key}", action)
            except FileNotFoundError:
                return _err(f"Key not found: {hive_str}\\{key}", action)
            except PermissionError:
                return _err("Permission denied.", action)

        # ── export_key ────────────────────────────────────────────────────────
        elif action == "export_key":
            if not key:
                return _err("'key' is required.", action)
            import os
            hive_prefix = f"{hive_str}\\" if not key.startswith(hive_str) else ""
            full_key = f"{hive_str}\\{key}"
            out_path = parameters.get("output_path",
                       os.path.join(os.path.expanduser("~"), "Desktop", "registry_export.reg"))
            result = subprocess.run(
                ["reg", "export", full_key, out_path, "/y"],
                capture_output=True, text=True, encoding="utf-8")
            if result.returncode == 0:
                return _ok(f"Key exported to: {out_path}", action)
            return _err(result.stderr.strip() or "Export failed.", action)

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            """Search registry for a value name or data (uses reg query)."""
            search_term = parameters.get("search_term", value_name or value_data)
            if not search_term:
                return _err("'search_term' (or value_name/value_data) is required.", action)
            root_key = f"{hive_str}\\{key}" if key else hive_str
            result = subprocess.run(
                ["reg", "query", root_key, "/f", search_term, "/s"],
                capture_output=True, text=True, encoding="utf-8", timeout=30)
            out = result.stdout.strip()
            return _ok(out[:3000] if out else f"No matches for '{search_term}'.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: read, write, delete_value, list_keys, "
                "create_key, delete_key, export_key, search",
                action)

    except Exception as e:
        return _err(str(e), action)
