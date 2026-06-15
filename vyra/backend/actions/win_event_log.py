"""
win_event_log.py — Windows Event Viewer log reading for VYRA.
Reads Application, System, Security, and custom logs via PowerShell Get-WinEvent.
"""
import json
import subprocess


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
        return out if out else (f"[stderr]: {err}" if err else "No output.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def win_event_log(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action    = parameters.get("action", "").lower().strip()
    log_name  = parameters.get("log_name", "System").strip()
    level     = parameters.get("level", "").lower().strip()  # error|warning|info|all
    limit     = int(parameters.get("limit", 20))
    source    = parameters.get("source", "").strip()
    event_id  = parameters.get("event_id")
    keywords  = parameters.get("keywords", "").strip()
    hours_back = int(parameters.get("hours_back", 24))

    # Level map: 1=Critical, 2=Error, 3=Warning, 4=Info/Verbose
    level_map = {"critical": 1, "error": 2, "warning": 3, "info": 4, "verbose": 5}
    level_filter = f" -Level {level_map[level]}" if level in level_map else ""

    try:
        # ── list_logs ─────────────────────────────────────────────────────────
        if action == "list_logs":
            result = _run_ps(
                "Get-WinEvent -ListLog * | Where-Object {$_.RecordCount -gt 0} | "
                "Select-Object LogName,LogType,RecordCount,IsEnabled | "
                "Sort-Object RecordCount -Descending | "
                "Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result, action)

        # ── read ──────────────────────────────────────────────────────────────
        elif action == "read":
            filter_parts = [f"LogName='{log_name}'"]
            if source:
                safe_src = source.replace("'", "''")
                filter_parts.append(f"ProviderName='{safe_src}'")
            if event_id:
                filter_parts.append(f"Id={int(event_id)}")
            filter_str = "; ".join(filter_parts)

            script = (
                f"Get-WinEvent -FilterHashtable @{{{filter_str}}}{level_filter} "
                f"-MaxEvents {limit} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,Id,LevelDisplayName,ProviderName,Message | "
                "Format-List | Out-String -Width 200"
            )
            result = _run_ps(script, timeout=30)
            return _ok(result if result.strip() else f"No events found in '{log_name}'.", action)

        # ── read_errors ───────────────────────────────────────────────────────
        elif action == "read_errors":
            script = (
                f"Get-WinEvent -FilterHashtable @{{LogName='{log_name}'; Level=2}} "
                f"-MaxEvents {limit} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,Id,ProviderName,"
                "@{n='Msg';e={$_.Message -replace '\\s+',' ' | Select-Object -First 1}} | "
                "Format-Table -AutoSize | Out-String -Width 200"
            )
            result = _run_ps(script)
            return _ok(result if result.strip() else "No errors found.", action)

        # ── read_warnings ─────────────────────────────────────────────────────
        elif action == "read_warnings":
            script = (
                f"Get-WinEvent -FilterHashtable @{{LogName='{log_name}'; Level=3}} "
                f"-MaxEvents {limit} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,Id,ProviderName | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            result = _run_ps(script)
            return _ok(result if result.strip() else "No warnings found.", action)

        # ── recent_crashes ────────────────────────────────────────────────────
        elif action == "recent_crashes":
            """Find application crashes and BSODs."""
            app_crashes = _run_ps(
                f"Get-WinEvent -FilterHashtable @{{LogName='Application'; Id=1000}} "
                f"-MaxEvents {limit} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,@{n='App';e={$_.Properties[0].Value}},"
                "@{n='Version';e={$_.Properties[1].Value}} | Format-Table | Out-String"
            )
            bsods = _run_ps(
                f"Get-WinEvent -FilterHashtable @{{LogName='System'; Id=41}} "
                f"-MaxEvents 5 -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,Message | Format-List | Out-String"
            )
            return _ok(f"=== App Crashes (Event 1000) ===\n{app_crashes}\n=== BSOD/Kernel Errors (Event 41) ===\n{bsods}", action)

        # ── search_events ─────────────────────────────────────────────────────
        elif action == "search_events":
            if not keywords:
                return _err("'keywords' is required for search.", action)
            safe_kw = keywords.replace("'", "''")
            script = (
                f"Get-WinEvent -LogName '{log_name}' -MaxEvents 500 -ErrorAction SilentlyContinue | "
                f"Where-Object {{$_.Message -like '*{safe_kw}*' -or $_.ProviderName -like '*{safe_kw}*'}} | "
                f"Select-Object -First {limit} TimeCreated,Id,LevelDisplayName,ProviderName | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            result = _run_ps(script, timeout=45)
            return _ok(result if result.strip() else f"No events matching '{keywords}'.", action)

        # ── clear_log ─────────────────────────────────────────────────────────
        elif action == "clear_log":
            if log_name.lower() == "security":
                return _err("Clearing Security log requires elevated privileges and is an auditable action.", action)
            if not parameters.get("confirmed"):
                return _err(f"Clear all events in '{log_name}' log? Set confirmed=true.", action)
            result = _run_ps(f"Clear-EventLog -LogName '{log_name}'")
            return _ok(f"Event log '{log_name}' cleared.\n{result}", action)

        # ── get_boot_events ───────────────────────────────────────────────────
        elif action == "get_boot_events":
            result = _run_ps(
                f"Get-WinEvent -FilterHashtable @{{LogName='System'; Id=@(12,13,41,6008)}} "
                f"-MaxEvents {limit} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,Id,Message | Format-List | Out-String -Width 200"
            )
            return _ok(result if result.strip() else "No boot events found.", action)

        # ── export_log ────────────────────────────────────────────────────────
        elif action == "export_log":
            import os
            out_path = parameters.get("output_path",
                                      os.path.join(os.path.expanduser("~"), "Desktop", f"{log_name}_events.csv"))
            script = (
                f"Get-WinEvent -LogName '{log_name}' -MaxEvents {limit} -ErrorAction SilentlyContinue | "
                "Select-Object TimeCreated,Id,LevelDisplayName,ProviderName,Message | "
                f"Export-Csv -Path '{out_path}' -NoTypeInformation -Encoding UTF8"
            )
            result = _run_ps(script, timeout=30)
            return _ok(f"Events exported to: {out_path}\n{result}", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_logs, read, read_errors, read_warnings, "
                "recent_crashes, search_events, clear_log, get_boot_events, export_log",
                action)

    except Exception as e:
        return _err(str(e), action)
