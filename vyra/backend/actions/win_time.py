"""
win_time.py — System time, date, and timezone management for VYRA.
"""
import json
import subprocess
import datetime
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


def win_time(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()

    try:
        # ── get_time ──────────────────────────────────────────────────────────
        if action == "get_time":
            now = datetime.datetime.now()
            tz  = _run_ps("(Get-TimeZone).DisplayName")
            result = (
                f"Current Time: {now.strftime('%H:%M:%S')}\n"
                f"Current Date: {now.strftime('%A, %B %d, %Y')}\n"
                f"Timezone:     {tz}\n"
                f"Unix Epoch:   {int(now.timestamp())}"
            )
            return _ok(result, action)

        # ── set_time ──────────────────────────────────────────────────────────
        elif action == "set_time":
            time_str = parameters.get("time", "").strip()  # HH:MM or HH:MM:SS
            if not time_str:
                return _err("'time' is required (HH:MM or HH:MM:SS).", action)
            if not parameters.get("confirmed"):
                return _err(f"Set system time to '{time_str}'? Set confirmed=true.", action)
            safe = time_str.replace("'", "''")
            result = _run_ps(f"Set-Date -Date (Get-Date -Hour {safe.split(':')[0]} -Minute {safe.split(':')[1]})")
            return _ok(f"System time set to {time_str}.\n{result}", action)

        # ── set_date ──────────────────────────────────────────────────────────
        elif action == "set_date":
            date_str = parameters.get("date", "").strip()  # YYYY-MM-DD
            if not date_str:
                return _err("'date' is required (YYYY-MM-DD).", action)
            if not parameters.get("confirmed"):
                return _err(f"Set system date to '{date_str}'? Set confirmed=true.", action)
            safe = date_str.replace("'", "''")
            result = _run_ps(f"Set-Date -Date '{safe}'")
            return _ok(f"System date set to {date_str}.\n{result}", action)

        # ── get_timezone ──────────────────────────────────────────────────────
        elif action == "get_timezone":
            result = _run_ps("Get-TimeZone | Format-List | Out-String")
            return _ok(result, action)

        # ── list_timezones ────────────────────────────────────────────────────
        elif action == "list_timezones":
            query = parameters.get("filter", "").strip()
            if query:
                safe = query.replace("'", "''")
                result = _run_ps(
                    f"Get-TimeZone -ListAvailable | Where-Object {{$_.DisplayName -like '*{safe}*' -or $_.Id -like '*{safe}*'}} | "
                    "Select-Object Id,DisplayName | Format-Table -AutoSize | Out-String -Width 120"
                )
            else:
                result = _run_ps(
                    "Get-TimeZone -ListAvailable | Select-Object Id,DisplayName | "
                    "Format-Table -AutoSize | Out-String -Width 120"
                )
            return _ok(result, action)

        # ── set_timezone ──────────────────────────────────────────────────────
        elif action == "set_timezone":
            tz_id = parameters.get("timezone_id", "").strip()
            if not tz_id:
                return _err("'timezone_id' is required (e.g. 'India Standard Time').", action)
            if not parameters.get("confirmed"):
                return _err(f"Set timezone to '{tz_id}'? Set confirmed=true.", action)
            safe = tz_id.replace("'", "''")
            result = _run_ps(f"Set-TimeZone -Id '{safe}'")
            return _ok(f"Timezone set to '{tz_id}'.\n{result}", action)

        # ── sync_time ─────────────────────────────────────────────────────────
        elif action == "sync_time":
            result = subprocess.run(
                ["w32tm", "/resync", "/force"],
                capture_output=True, text=True, encoding="utf-8")
            return _ok(result.stdout.strip() or "Time sync requested.", action)

        # ── enable_auto_sync ──────────────────────────────────────────────────
        elif action == "enable_auto_sync":
            result = _run_ps(
                "Set-Service w32tm -StartupType Automatic; "
                "Start-Service w32tm -ErrorAction SilentlyContinue; "
                "w32tm /config /manualpeerlist:'time.windows.com' /syncfromflags:manual /reliable:yes /update"
            )
            return _ok("Automatic time sync enabled.\n" + result, action)

        # ── set_ntp_server ────────────────────────────────────────────────────
        elif action == "set_ntp_server":
            server = parameters.get("ntp_server", "time.windows.com").strip()
            result = _run_ps(
                f"w32tm /config /manualpeerlist:'{server}' /syncfromflags:manual /reliable:yes /update; "
                "Restart-Service w32tm"
            )
            return _ok(f"NTP server set to '{server}'.\n{result}", action)

        # ── get_uptime ────────────────────────────────────────────────────────
        elif action == "get_uptime":
            import psutil, datetime
            boot = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime = datetime.datetime.now() - boot
            days = uptime.days
            hours, remainder = divmod(uptime.seconds, 3600)
            minutes = remainder // 60
            return _ok(
                f"System uptime: {days}d {hours}h {minutes}m\n"
                f"Last boot: {boot.strftime('%A, %B %d, %Y at %H:%M:%S')}", action)

        # ── get_calendar ──────────────────────────────────────────────────────
        elif action == "get_calendar":
            month = int(parameters.get("month", datetime.datetime.now().month))
            year  = int(parameters.get("year", datetime.datetime.now().year))
            import calendar
            cal = calendar.TextCalendar().formatmonth(year, month)
            return _ok(cal, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: get_time, set_time, set_date, get_timezone, "
                "list_timezones, set_timezone, sync_time, enable_auto_sync, set_ntp_server, "
                "get_uptime, get_calendar",
                action)

    except Exception as e:
        return _err(str(e), action)
