"""
win_users.py — Windows local user account management for VYRA.
Uses PowerShell Get/New/Remove/Set-LocalUser + Get/Add/Remove-LocalGroupMember.
"""
import json
import subprocess

_PROTECTED_ACCOUNTS = frozenset({"administrator", "guest", "defaultaccount", "wdagutilityaccount"})


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 30) -> str:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        out = r.stdout.strip()
        err = r.stderr.strip()
        return out if out else (f"[stderr]: {err}" if err else "Done.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def _safe_username(username: str) -> str:
    return username.replace("'", "''")


def win_users(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action    = parameters.get("action", "").lower().strip()
    username  = parameters.get("username", "").strip()
    password  = parameters.get("password", "").strip()
    full_name = parameters.get("full_name", "").strip()
    group     = parameters.get("group", "").strip()
    desc      = parameters.get("description", "").strip()

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            result = _run_ps(
                "Get-LocalUser | Select-Object Name,Enabled,FullName,LastLogon,"
                "PasswordLastSet,PasswordExpires,UserMayChangePassword | "
                "Format-Table -AutoSize | Out-String -Width 180"
            )
            return _ok(result, action)

        # ── whoami ────────────────────────────────────────────────────────────
        elif action == "whoami":
            result = _run_ps(
                "$env:USERNAME; "
                "whoami /all"
            )
            return _ok(result, action)

        # ── get_detail ────────────────────────────────────────────────────────
        elif action == "get_detail":
            if not username:
                return _err("'username' is required.", action)
            safe = _safe_username(username)
            result = _run_ps(
                f"$u = Get-LocalUser -Name '{safe}' -ErrorAction SilentlyContinue; "
                "if ($u) { $u | Format-List; "
                f"Write-Output 'Groups:'; Get-LocalGroup | ForEach-Object {{ "
                f"  if (Get-LocalGroupMember -Group $_.Name -ErrorAction SilentlyContinue | "
                f"  Where-Object {{$_.Name -like '*{safe}*'}}) {{ $_.Name }} }} "
                "} else { 'User not found.' }"
            )
            return _ok(result, action)

        # ── add ───────────────────────────────────────────────────────────────
        elif action == "add":
            if not username:
                return _err("'username' is required.", action)
            safe = _safe_username(username)
            safe_pass = password.replace("'", "''") if password else ""
            safe_full = full_name.replace("'", "''") if full_name else ""
            safe_desc = desc.replace("'", "''") if desc else ""

            if safe_pass:
                ps = (
                    f"$SecPass = ConvertTo-SecureString '{safe_pass}' -AsPlainText -Force; "
                    f"New-LocalUser -Name '{safe}' -Password $SecPass"
                )
            else:
                ps = f"New-LocalUser -Name '{safe}' -NoPassword"

            if safe_full:
                ps += f" -FullName '{safe_full}'"
            if safe_desc:
                ps += f" -Description '{safe_desc}'"

            result = _run_ps(ps)

            # Add to Users group by default
            add_group = _run_ps(f"Add-LocalGroupMember -Group 'Users' -Member '{safe}' -ErrorAction SilentlyContinue")
            return _ok(f"User '{username}' created.\n{result}", action)

        # ── remove ────────────────────────────────────────────────────────────
        elif action == "remove":
            if not username:
                return _err("'username' is required.", action)
            if username.lower() in _PROTECTED_ACCOUNTS:
                return _err(f"Cannot remove built-in account '{username}'.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete user '{username}' and their data? Set confirmed=true.", action)
            safe = _safe_username(username)
            result = _run_ps(f"Remove-LocalUser -Name '{safe}'")
            return _ok(f"User '{username}' removed.\n{result}", action)

        # ── enable / disable ──────────────────────────────────────────────────
        elif action in ("enable", "disable"):
            if not username:
                return _err("'username' is required.", action)
            if username.lower() in _PROTECTED_ACCOUNTS and action == "disable":
                return _err(f"Cannot disable built-in account '{username}'.", action)
            safe = _safe_username(username)
            ps = f"Enable-LocalUser -Name '{safe}'" if action == "enable" else f"Disable-LocalUser -Name '{safe}'"
            result = _run_ps(ps)
            return _ok(f"User '{username}' {action}d.\n{result}", action)

        # ── change_password ───────────────────────────────────────────────────
        elif action == "change_password":
            if not username or not password:
                return _err("'username' and 'password' are required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Change password for '{username}'? Set confirmed=true.", action)
            safe = _safe_username(username)
            safe_pass = password.replace("'", "''")
            result = _run_ps(
                f"$SecPass = ConvertTo-SecureString '{safe_pass}' -AsPlainText -Force; "
                f"Set-LocalUser -Name '{safe}' -Password $SecPass"
            )
            return _ok(f"Password changed for '{username}'.", action)

        # ── get_groups ────────────────────────────────────────────────────────
        elif action == "get_groups":
            result = _run_ps(
                "Get-LocalGroup | Select-Object Name,Description,PrincipalSource | "
                "Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result, action)

        # ── get_group_members ─────────────────────────────────────────────────
        elif action == "get_group_members":
            if not group:
                return _err("'group' is required.", action)
            safe_group = group.replace("'", "''")
            result = _run_ps(
                f"Get-LocalGroupMember -Group '{safe_group}' | "
                "Select-Object Name,ObjectClass,PrincipalSource | "
                "Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result, action)

        # ── add_to_group ──────────────────────────────────────────────────────
        elif action == "add_to_group":
            if not username or not group:
                return _err("'username' and 'group' are required.", action)
            safe = _safe_username(username)
            safe_group = group.replace("'", "''")
            result = _run_ps(f"Add-LocalGroupMember -Group '{safe_group}' -Member '{safe}'")
            return _ok(f"User '{username}' added to group '{group}'.\n{result}", action)

        # ── remove_from_group ─────────────────────────────────────────────────
        elif action == "remove_from_group":
            if not username or not group:
                return _err("'username' and 'group' are required.", action)
            safe = _safe_username(username)
            safe_group = group.replace("'", "''")
            result = _run_ps(f"Remove-LocalGroupMember -Group '{safe_group}' -Member '{safe}'")
            return _ok(f"User '{username}' removed from '{group}'.\n{result}", action)

        # ── set_password_never_expires ────────────────────────────────────────
        elif action == "set_password_never_expires":
            if not username:
                return _err("'username' is required.", action)
            safe = _safe_username(username)
            never = parameters.get("never_expires", True)
            result = _run_ps(
                f"Set-LocalUser -Name '{safe}' -PasswordNeverExpires ${str(never).lower()}"
            )
            return _ok(f"Password never expires set to {never} for '{username}'.", action)

        # ── list_logged_in ────────────────────────────────────────────────────
        elif action == "list_logged_in":
            result = _run_ps("query user")
            return _ok(result if result.strip() else "No active sessions.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, whoami, get_detail, add, remove, "
                "enable, disable, change_password, get_groups, get_group_members, "
                "add_to_group, remove_from_group, set_password_never_expires, list_logged_in",
                action)

    except Exception as e:
        return _err(str(e), action)
