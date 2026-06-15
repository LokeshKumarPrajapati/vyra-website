"""
win_credential.py — Windows Credential Manager read/write for VYRA.
Uses keyring (which wraps Windows Credential Manager) + PowerShell cmdkey.
NEVER logs passwords. Handles generic and Windows credentials.
"""
import json
import subprocess


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 15) -> str:
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


def win_credential(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action   = parameters.get("action", "").lower().strip()
    service  = parameters.get("service", "").strip()
    username = parameters.get("username", "").strip()
    password = parameters.get("password", "")

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            result = _run_ps("cmdkey /list")
            return _ok(result if result.strip() else "No stored credentials found.", action)

        # ── list_generic ──────────────────────────────────────────────────────
        elif action == "list_generic":
            try:
                import keyring
                # keyring doesn't support listing all credentials natively
                # Use Windows Credential Manager via cmdkey
                result = _run_ps("cmdkey /list | Where-Object {$_ -match 'GENERIC|Target'}")
                return _ok(result, action)
            except ImportError:
                result = _run_ps("cmdkey /list")
                return _ok(result, action)

        # ── store ─────────────────────────────────────────────────────────────
        elif action == "store":
            if not service or not username:
                return _err("'service' and 'username' are required.", action)
            if not password:
                return _err("'password' is required.", action)
            try:
                import keyring
                keyring.set_password(service, username, password)
                return _ok(f"Credential stored for service='{service}' user='{username}'.", action)
            except ImportError:
                # Fallback: cmdkey
                safe_target = service.replace('"', '')
                safe_user   = username.replace('"', '')
                safe_pass   = password.replace('"', '')
                result = _run_ps(
                    f'cmdkey /add:"{safe_target}" /user:"{safe_user}" /pass:"{safe_pass}"')
                return _ok(f"Credential stored via cmdkey: {service}/{username}\n{result}", action)

        # ── retrieve ──────────────────────────────────────────────────────────
        elif action == "retrieve":
            if not service or not username:
                return _err("'service' and 'username' are required.", action)
            try:
                import keyring
                pwd = keyring.get_password(service, username)
                if pwd is not None:
                    return _ok(f"Password retrieved for {service}/{username}: [HIDDEN - {len(pwd)} chars]", action)
                return _ok(f"No credential found for {service}/{username}.", action)
            except ImportError:
                return _err("keyring not installed. Run: pip install keyring", action)

        # ── retrieve_to_clipboard ─────────────────────────────────────────────
        elif action == "retrieve_to_clipboard":
            """Retrieve password and put it in clipboard without displaying."""
            if not service or not username:
                return _err("'service' and 'username' are required.", action)
            try:
                import keyring, pyperclip
                pwd = keyring.get_password(service, username)
                if pwd is not None:
                    pyperclip.copy(pwd)
                    return _ok(f"Password for {service}/{username} copied to clipboard ({len(pwd)} chars).", action)
                return _ok(f"No credential found for {service}/{username}.", action)
            except ImportError as e:
                return _err(f"Missing dependency: {e}. Run: pip install keyring pyperclip", action)

        # ── delete ────────────────────────────────────────────────────────────
        elif action == "delete":
            if not service:
                return _err("'service' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete credential for '{service}'? Set confirmed=true.", action)
            try:
                import keyring
                keyring.delete_password(service, username)
                return _ok(f"Credential deleted: {service}/{username}.", action)
            except ImportError:
                safe = service.replace('"', '')
                result = _run_ps(f'cmdkey /delete:"{safe}"')
                return _ok(f"Credential deleted via cmdkey.\n{result}", action)

        # ── store_network ─────────────────────────────────────────────────────
        elif action == "store_network":
            """Store network/UNC path credentials."""
            if not service or not username or not password:
                return _err("'service' (target/server), 'username', 'password' are required.", action)
            safe_target = service.replace('"', '')
            safe_user   = username.replace('"', '')
            safe_pass   = password.replace('"', '')
            result = _run_ps(
                f'cmdkey /add:"{safe_target}" /user:"{safe_user}" /pass:"{safe_pass}"')
            return _ok(f"Network credential stored for '{service}'.\n{result}", action)

        # ── open_credential_manager ───────────────────────────────────────────
        elif action == "open_credential_manager":
            import subprocess as sp
            sp.Popen(["control", "/name", "Microsoft.CredentialManager"])
            return _ok("Windows Credential Manager opened.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, list_generic, store, retrieve, "
                "retrieve_to_clipboard, delete, store_network, open_credential_manager",
                action)

    except Exception as e:
        return _err(str(e), action)
