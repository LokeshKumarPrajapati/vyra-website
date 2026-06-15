"""
win_file_perms.py — NTFS file permission and ACL management for VYRA.
Uses icacls CLI + PowerShell Get-Acl/Set-Acl for fine-grained access control.
"""
import json
import subprocess
import os


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run(cmd: list, timeout: int = 30) -> tuple[str, bool]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (r.stdout + "\n" + r.stderr).strip()
        return out, r.returncode == 0
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s.", False
    except Exception as e:
        return str(e), False


def _run_ps(script: str, timeout: int = 30) -> str:
    out, _ = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    return out


def win_file_perms(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action   = parameters.get("action", "").lower().strip()
    path     = parameters.get("path", "").strip()
    username = parameters.get("username", "").strip()
    perms    = parameters.get("permissions", "").strip().upper()  # F,M,RX,R,W,D,N
    inherit  = parameters.get("inherit", True)

    if path and not os.path.exists(path):
        return _err(f"Path not found: {path}", action)

    try:
        # ── get_permissions ───────────────────────────────────────────────────
        if action == "get_permissions":
            if not path:
                return _err("'path' is required.", action)
            out, ok = _run(["icacls", path])
            return _ok(out, action)

        # ── get_owner ─────────────────────────────────────────────────────────
        elif action == "get_owner":
            if not path:
                return _err("'path' is required.", action)
            safe = path.replace("'", "''")
            result = _run_ps(f"(Get-Acl '{safe}').Owner")
            return _ok(f"Owner of '{path}': {result}", action)

        # ── set_owner ─────────────────────────────────────────────────────────
        elif action == "set_owner":
            if not path or not username:
                return _err("'path' and 'username' are required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Change owner of '{path}' to '{username}'? Set confirmed=true.", action)
            safe_path = path.replace("'", "''")
            safe_user = username.replace("'", "''")
            result = _run_ps(
                f"$acl = Get-Acl '{safe_path}'; "
                f"$acl.SetOwner([System.Security.Principal.NTAccount]'{safe_user}'); "
                f"Set-Acl '{safe_path}' $acl"
            )
            return _ok(f"Owner set to '{username}' for '{path}'.\n{result}", action)

        # ── grant ─────────────────────────────────────────────────────────────
        elif action == "grant":
            if not path or not username or not perms:
                return _err("'path', 'username', and 'permissions' are required.", action)
            valid_perms = {"F", "M", "RX", "R", "W", "D", "N", "RC", "DC",
                           "DELETE", "READ", "WRITE", "EXECUTE", "FULL"}
            if perms not in valid_perms:
                return _err(f"Invalid permissions '{perms}'. Use: F (Full), M (Modify), RX (Read+Execute), R (Read), W (Write)", action)
            inherit_flag = ":(OI)(CI)" if inherit else ""
            cmd = ["icacls", path, "/grant", f"{username}{inherit_flag}:{perms}"]
            out, ok = _run(cmd)
            return _ok(f"Granted '{perms}' to '{username}' on '{path}'.\n{out}", action)

        # ── deny ──────────────────────────────────────────────────────────────
        elif action == "deny":
            if not path or not username or not perms:
                return _err("'path', 'username', and 'permissions' are required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Deny '{perms}' for '{username}' on '{path}'? Set confirmed=true.", action)
            cmd = ["icacls", path, "/deny", f"{username}:{perms}"]
            out, ok = _run(cmd)
            return _ok(f"Denied '{perms}' for '{username}' on '{path}'.\n{out}", action)

        # ── revoke ────────────────────────────────────────────────────────────
        elif action == "revoke":
            if not path or not username:
                return _err("'path' and 'username' are required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Revoke all permissions for '{username}' on '{path}'? Set confirmed=true.", action)
            cmd = ["icacls", path, "/remove", username]
            out, ok = _run(cmd)
            return _ok(f"Permissions revoked for '{username}' on '{path}'.\n{out}", action)

        # ── reset_inheritance ─────────────────────────────────────────────────
        elif action == "reset_inheritance":
            if not path:
                return _err("'path' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Reset permissions on '{path}' to inherit from parent? Set confirmed=true.", action)
            out, ok = _run(["icacls", path, "/reset", "/T"])
            return _ok(f"Permissions reset to inherited on '{path}'.\n{out}", action)

        # ── disable_inheritance ───────────────────────────────────────────────
        elif action == "disable_inheritance":
            if not path:
                return _err("'path' is required.", action)
            copy = "C" if parameters.get("copy_inherited", True) else "R"
            out, ok = _run(["icacls", path, "/inheritance:d" + copy])
            return _ok(f"Inheritance disabled on '{path}' (existing rules {('copied' if copy=='C' else 'removed')}).\n{out}", action)

        # ── take_ownership ────────────────────────────────────────────────────
        elif action == "take_ownership":
            if not path:
                return _err("'path' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Take ownership of '{path}'? Set confirmed=true.", action)
            # Use takeown /f and then grant full control
            out1, _ = _run(["takeown", "/f", path, "/r", "/d", "y"])
            out2, _ = _run(["icacls", path, "/grant", "Administrators:F", "/T"])
            return _ok(f"Ownership taken for '{path}'.\n{out1}\n{out2}", action)

        # ── export_acl ────────────────────────────────────────────────────────
        elif action == "export_acl":
            if not path:
                return _err("'path' is required.", action)
            import time
            out_path = parameters.get("output_path",
                       os.path.join(os.path.expanduser("~"), "Desktop",
                                    f"acl_backup_{int(time.time())}.txt"))
            out, ok = _run(["icacls", path, "/save", out_path, "/T"])
            return _ok(f"ACL exported to: {out_path}\n{out}", action)

        # ── import_acl ────────────────────────────────────────────────────────
        elif action == "import_acl":
            acl_file = parameters.get("acl_file", "").strip()
            if not acl_file or not os.path.exists(acl_file):
                return _err("'acl_file' pointing to a saved ACL file is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Restore ACL from '{acl_file}'? Set confirmed=true.", action)
            parent = os.path.dirname(path) if path else "C:\\"
            out, ok = _run(["icacls", parent, "/restore", acl_file])
            return _ok(f"ACL restored.\n{out}", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: get_permissions, get_owner, set_owner, "
                "grant, deny, revoke, reset_inheritance, disable_inheritance, "
                "take_ownership, export_acl, import_acl",
                action)

    except Exception as e:
        return _err(str(e), action)
