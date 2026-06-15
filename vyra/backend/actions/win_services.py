"""
win_services.py — Windows Service management for VYRA.
Uses PowerShell Get/Start/Stop/Set-Service cmdlets.
Safety: blocks modification of critical OS services.
"""
import json
import subprocess

_PROTECTED_SERVICES = frozenset({
    "eventlog", "rpcss", "lsm", "plugplay", "winmgmt",
    "cryptsvc", "audiosrv", "schedule", "windefend",
    "wscsvc", "mpssvc",  # Windows Firewall
})


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


def _is_protected(name: str) -> bool:
    return name.lower().strip() in _PROTECTED_SERVICES


def win_services(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action       = parameters.get("action", "").lower().strip()
    service_name = parameters.get("service_name", "").strip()
    startup_type = parameters.get("startup_type", "").strip()
    filter_status = parameters.get("filter_status", "").strip()  # running|stopped|all

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            where_clause = ""
            if filter_status.lower() in ("running", "stopped"):
                cap = filter_status.capitalize()
                where_clause = f" | Where-Object {{$_.Status -eq '{cap}'}}"
            script = (
                f"Get-Service{where_clause} | "
                "Select-Object Name,DisplayName,Status,StartType | "
                "Sort-Object Status,Name | "
                "Format-Table -AutoSize | Out-String -Width 150"
            )
            result = _run_ps(script, timeout=30)
            return _ok(result, action)

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            if not service_name:
                return _err("'service_name' (search term) is required.", action)
            safe = service_name.replace("'", "''")
            script = (
                f"Get-Service | Where-Object {{$_.Name -like '*{safe}*' -or $_.DisplayName -like '*{safe}*'}} | "
                "Select-Object Name,DisplayName,Status,StartType | Format-Table -AutoSize | Out-String -Width 150"
            )
            result = _run_ps(script)
            return _ok(result, action)

        # ── status ────────────────────────────────────────────────────────────
        elif action == "status":
            if not service_name:
                return _err("'service_name' is required.", action)
            safe = service_name.replace("'", "''")
            script = (
                f"$s = Get-Service -Name '{safe}' -ErrorAction SilentlyContinue; "
                "if ($s) { $s | Select-Object Name,DisplayName,Status,StartType,DependentServices,"
                "ServicesDependedOn | Format-List | Out-String } "
                "else { 'Service not found.' }"
            )
            result = _run_ps(script)
            return _ok(result, action)

        # ── start ─────────────────────────────────────────────────────────────
        elif action == "start":
            if not service_name:
                return _err("'service_name' is required.", action)
            safe = service_name.replace("'", "''")
            result = _run_ps(f"Start-Service -Name '{safe}' -PassThru | Select-Object Name,Status | Format-Table")
            return _ok(result, action)

        # ── stop ──────────────────────────────────────────────────────────────
        elif action == "stop":
            if not service_name:
                return _err("'service_name' is required.", action)
            if _is_protected(service_name):
                return _err(f"'{service_name}' is a protected OS service. Cannot stop.", action)
            if not parameters.get("confirmed"):
                return _err(f"Stop service '{service_name}'? Set confirmed=true.", action)
            safe = service_name.replace("'", "''")
            result = _run_ps(f"Stop-Service -Name '{safe}' -Force -PassThru | Select-Object Name,Status | Format-Table")
            return _ok(result, action)

        # ── restart ───────────────────────────────────────────────────────────
        elif action == "restart":
            if not service_name:
                return _err("'service_name' is required.", action)
            if _is_protected(service_name):
                return _err(f"'{service_name}' is a protected OS service. Use the start action instead.", action)
            safe = service_name.replace("'", "''")
            result = _run_ps(f"Restart-Service -Name '{safe}' -Force -PassThru | Select-Object Name,Status | Format-Table")
            return _ok(result, action)

        # ── enable / disable ──────────────────────────────────────────────────
        elif action in ("enable", "disable"):
            if not service_name:
                return _err("'service_name' is required.", action)
            if action == "disable" and _is_protected(service_name):
                return _err(f"'{service_name}' is a protected OS service. Cannot disable.", action)
            if action == "disable" and not parameters.get("confirmed"):
                return _err(f"Disable service '{service_name}'? Set confirmed=true.", action)
            new_type = "Automatic" if action == "enable" else "Disabled"
            safe = service_name.replace("'", "''")
            result = _run_ps(f"Set-Service -Name '{safe}' -StartupType {new_type}")
            return _ok(f"Service '{service_name}' startup type set to {new_type}.", action)

        # ── set_startup ───────────────────────────────────────────────────────
        elif action == "set_startup":
            if not service_name or not startup_type:
                return _err("'service_name' and 'startup_type' are required.", action)
            valid_types = {"automatic", "manual", "disabled", "automaticdelayedstart"}
            if startup_type.lower().replace(" ", "") not in valid_types:
                return _err(f"Invalid startup_type. Use: Automatic, Manual, Disabled, AutomaticDelayedStart", action)
            if startup_type.lower() == "disabled" and _is_protected(service_name):
                return _err(f"Cannot disable protected service '{service_name}'.", action)
            if startup_type.lower() == "disabled" and not parameters.get("confirmed"):
                return _err(f"Disable '{service_name}'? Set confirmed=true.", action)
            safe = service_name.replace("'", "''")
            type_map = {"automaticdelayedstart": "AutomaticDelayedStart", "automatic": "Automatic",
                        "manual": "Manual", "disabled": "Disabled"}
            ps_type = type_map.get(startup_type.lower().replace(" ", ""), startup_type.title())
            result = _run_ps(f"Set-Service -Name '{safe}' -StartupType {ps_type}")
            return _ok(f"'{service_name}' startup type → {ps_type}", action)

        # ── get_dependencies ─────────────────────────────────────────────────
        elif action == "get_dependencies":
            if not service_name:
                return _err("'service_name' is required.", action)
            safe = service_name.replace("'", "''")
            script = (
                f"$s = Get-Service -Name '{safe}' -ErrorAction SilentlyContinue; "
                "if ($s) {"
                "  Write-Output 'Depends on:'; $s.ServicesDependedOn | Format-Table Name,DisplayName,Status; "
                "  Write-Output 'Dependents:'; $s.DependentServices | Format-Table Name,DisplayName,Status"
                "} else { 'Service not found.' }"
            )
            result = _run_ps(script)
            return _ok(result, action)

        # ── export_config ─────────────────────────────────────────────────────
        elif action == "export_config":
            """Export all services config to JSON-like table."""
            script = (
                "Get-Service | Select-Object Name,DisplayName,Status,StartType | "
                "ConvertTo-Json -Depth 2 -Compress"
            )
            result = _run_ps(script, timeout=30)
            return _ok(result, action)

        # ── list_failed ───────────────────────────────────────────────────────
        elif action == "list_failed":
            """Show services that should be running but have stopped."""
            script = (
                "Get-Service | Where-Object {$_.StartType -eq 'Automatic' -and $_.Status -ne 'Running'} | "
                "Select-Object Name,DisplayName,Status,StartType | Format-Table -AutoSize | Out-String -Width 120"
            )
            result = _run_ps(script)
            return _ok(result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, search, status, start, stop, restart, "
                "enable, disable, set_startup, get_dependencies, export_config, list_failed",
                action)

    except Exception as e:
        return _err(str(e), action)