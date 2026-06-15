"""
win_shortcuts.py — Desktop, Start Menu, and taskbar shortcut management for VYRA.
Creates/deletes .lnk files via PowerShell WScript.Shell COM object.
"""
import json
import subprocess
import os


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 20) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = r.stdout.strip()
        err = r.stderr.strip()
        return out if out else (f"[stderr]: {err}" if err else "Done.")
    except subprocess.TimeoutExpired:
        return "Timed out."
    except Exception as e:
        return f"Error: {e}"


_LOCATIONS = {
    "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
    "start_menu": os.path.join(os.environ.get("APPDATA", ""),
                               r"Microsoft\Windows\Start Menu\Programs"),
    "startup": os.path.join(os.environ.get("APPDATA", ""),
                            r"Microsoft\Windows\Start Menu\Programs\Startup"),
    "public_desktop": r"C:\Users\Public\Desktop",
    "common_start": r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs",
}


def _make_shortcut(name: str, target: str, location: str = "desktop",
                   icon: str = "", args: str = "", description: str = "",
                   working_dir: str = "", window_style: int = 1) -> str:
    loc_path = _LOCATIONS.get(location.lower(), location)
    lnk_path = os.path.join(loc_path, f"{name}.lnk")
    lnk_path_ps = lnk_path.replace("\\", "\\\\")
    target_ps  = target.replace("\\", "\\\\").replace("'", "''")
    icon_ps    = icon.replace("\\", "\\\\").replace("'", "''") if icon else target_ps
    args_ps    = args.replace("'", "''")
    desc_ps    = description.replace("'", "''")
    wd_ps      = (working_dir or os.path.dirname(target)).replace("\\", "\\\\").replace("'", "''")

    script = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{lnk_path_ps}'); "
        f"$s.TargetPath = '{target_ps}'; "
        f"$s.Arguments = '{args_ps}'; "
        f"$s.WorkingDirectory = '{wd_ps}'; "
        f"$s.Description = '{desc_ps}'; "
        f"$s.IconLocation = '{icon_ps}'; "
        f"$s.WindowStyle = {window_style}; "
        f"$s.Save(); "
        f"Write-Output 'Created: {lnk_path_ps}'"
    )
    return _run_ps(script)


def win_shortcuts(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action      = parameters.get("action", "").lower().strip()
    name        = parameters.get("name", "").strip()
    target      = parameters.get("target", "").strip()
    location    = parameters.get("location", "desktop").strip()
    icon        = parameters.get("icon", "").strip()
    args        = parameters.get("args", "").strip()
    description = parameters.get("description", "").strip()
    working_dir = parameters.get("working_dir", "").strip()

    try:
        # ── create ────────────────────────────────────────────────────────────
        if action == "create":
            if not name or not target:
                return _err("'name' and 'target' are required.", action)
            if not os.path.exists(target):
                # Allow URL shortcuts (https://, etc.)
                if not target.startswith(("http://", "https://", "ms-settings:", "shell:")):
                    return _err(f"Target not found: {target}", action)
            result = _make_shortcut(name, target, location, icon, args, description, working_dir)
            return _ok(f"Shortcut '{name}' created on {location}.\n{result}", action)

        # ── create_url ────────────────────────────────────────────────────────
        elif action == "create_url":
            """Create a .url (internet shortcut) instead of .lnk."""
            if not name or not target:
                return _err("'name' (shortcut name) and 'target' (URL) are required.", action)
            loc_path = _LOCATIONS.get(location.lower(), location)
            url_path = os.path.join(loc_path, f"{name}.url")
            content = f"[InternetShortcut]\nURL={target}\n"
            if icon:
                content += f"IconFile={icon}\nIconIndex=0\n"
            with open(url_path, "w", encoding="utf-8") as f:
                f.write(content)
            return _ok(f"URL shortcut created: {url_path}", action)

        # ── delete ────────────────────────────────────────────────────────────
        elif action == "delete":
            if not name:
                return _err("'name' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete shortcut '{name}'? Set confirmed=true.", action)
            removed = []
            loc_path = _LOCATIONS.get(location.lower(), location)
            for ext in (".lnk", ".url"):
                fp = os.path.join(loc_path, f"{name}{ext}")
                if os.path.exists(fp):
                    os.remove(fp)
                    removed.append(fp)
            if removed:
                return _ok(f"Deleted: {', '.join(removed)}", action)
            return _err(f"Shortcut '{name}' not found in {location}.", action)

        # ── list ──────────────────────────────────────────────────────────────
        elif action == "list":
            loc_path = _LOCATIONS.get(location.lower(), location)
            if not os.path.isdir(loc_path):
                return _err(f"Location not found: {loc_path}", action)
            items = []
            for root, dirs, files in os.walk(loc_path):
                for f in files:
                    if f.lower().endswith((".lnk", ".url")):
                        items.append(os.path.relpath(os.path.join(root, f), loc_path))
            return _ok(f"Shortcuts in {location} ({len(items)}):\n" + "\n".join(sorted(items)), action)

        # ── get_target ────────────────────────────────────────────────────────
        elif action == "get_target":
            """Resolve .lnk target path."""
            if not name:
                return _err("'name' is required.", action)
            loc_path = _LOCATIONS.get(location.lower(), location)
            lnk_path = os.path.join(loc_path, f"{name}.lnk")
            if not os.path.exists(lnk_path):
                return _err(f"Shortcut '{name}' not found in {location}.", action)
            lnk_ps = lnk_path.replace("\\", "\\\\")
            result = _run_ps(
                f"$ws = New-Object -ComObject WScript.Shell; "
                f"$s = $ws.CreateShortcut('{lnk_ps}'); "
                f"\"Target: $($s.TargetPath)\"; "
                f"\"Arguments: $($s.Arguments)\"; "
                f"\"WorkDir: $($s.WorkingDirectory)\""
            )
            return _ok(result, action)

        # ── pin_to_taskbar ────────────────────────────────────────────────────
        elif action == "pin_to_taskbar":
            if not target:
                return _err("'target' (exe path) is required.", action)
            safe = target.replace("'", "''")
            result = _run_ps(
                f"$Shell = New-Object -ComObject Shell.Application; "
                f"$Folder = $Shell.Namespace((Split-Path '{safe}')); "
                f"$Item = $Folder.ParseName((Split-Path '{safe}' -Leaf)); "
                f"$Item.InvokeVerb('taskbarpin')"
            )
            return _ok(f"Pinned to taskbar: {target}\n{result}", action)

        # ── create_admin_shortcut ─────────────────────────────────────────────
        elif action == "create_admin_shortcut":
            """Create a shortcut that runs as administrator."""
            if not name or not target:
                return _err("'name' and 'target' are required.", action)
            result = _make_shortcut(name, target, location, icon, args, description, working_dir)
            # Set RunAsAdministrator flag in the .lnk file (byte 0x15 = 0x20)
            loc_path = _LOCATIONS.get(location.lower(), location)
            lnk_path = os.path.join(loc_path, f"{name}.lnk")
            with open(lnk_path, "r+b") as f:
                data = bytearray(f.read())
                if len(data) > 0x15:
                    data[0x15] |= 0x20  # RunAsAdministrator bit
                f.seek(0)
                f.write(data)
            return _ok(f"Admin shortcut '{name}' created on {location}.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: create, create_url, delete, list, "
                "get_target, pin_to_taskbar, create_admin_shortcut",
                action)

    except Exception as e:
        return _err(str(e), action)
