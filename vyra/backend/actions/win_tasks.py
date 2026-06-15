"""
win_tasks.py — Windows Task Scheduler management for VYRA.
Uses PowerShell Register/Get/Start/Unregister-ScheduledTask.
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
        return out if out else (f"[stderr]: {err}" if err else "Done.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def win_tasks(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action        = parameters.get("action", "").lower().strip()
    task_name     = parameters.get("task_name", "").strip()
    task_path     = parameters.get("task_path", "\\").strip()
    trigger_type  = parameters.get("trigger_type", "daily").lower()
    trigger_time  = parameters.get("trigger_time", "09:00")
    trigger_days  = parameters.get("trigger_days", [])
    action_path   = parameters.get("action_path", "").strip()
    action_args   = parameters.get("action_args", "").strip()
    run_as_user   = parameters.get("run_as_user", "$env:USERNAME")
    run_level     = "Highest" if parameters.get("run_elevated") else "Limited"
    filter_status = parameters.get("filter_status", "").strip()

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            where = ""
            if filter_status.lower() in ("ready", "running", "disabled"):
                cap = filter_status.capitalize()
                where = f" | Where-Object {{$_.State -eq '{cap}'}}"
            script = (
                f"Get-ScheduledTask{where} | "
                "Select-Object TaskName,TaskPath,State,@{n='LastRun';e={$_.LastRunTime}},"
                "@{n='NextRun';e={$_.NextRunTime}} | "
                "Sort-Object TaskPath,TaskName | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            result = _run_ps(script, timeout=30)
            return _ok(result, action)

        # ── get_detail ────────────────────────────────────────────────────────
        elif action == "get_detail":
            if not task_name:
                return _err("'task_name' is required.", action)
            safe = task_name.replace("'", "''")
            script = (
                f"$t = Get-ScheduledTask -TaskName '{safe}' -ErrorAction SilentlyContinue; "
                "if ($t) { $t | Get-ScheduledTaskInfo | Format-List; $t | Format-List } "
                "else { 'Task not found.' }"
            )
            result = _run_ps(script)
            return _ok(result, action)

        # ── run_now ───────────────────────────────────────────────────────────
        elif action == "run_now":
            if not task_name:
                return _err("'task_name' is required.", action)
            safe = task_name.replace("'", "''")
            result = _run_ps(f"Start-ScheduledTask -TaskName '{safe}'")
            return _ok(f"Task '{task_name}' triggered.", action)

        # ── enable ────────────────────────────────────────────────────────────
        elif action == "enable":
            if not task_name:
                return _err("'task_name' is required.", action)
            safe = task_name.replace("'", "''")
            result = _run_ps(f"Enable-ScheduledTask -TaskName '{safe}'")
            return _ok(f"Task '{task_name}' enabled.", action)

        # ── disable ───────────────────────────────────────────────────────────
        elif action == "disable":
            if not task_name:
                return _err("'task_name' is required.", action)
            safe = task_name.replace("'", "''")
            result = _run_ps(f"Disable-ScheduledTask -TaskName '{safe}'")
            return _ok(f"Task '{task_name}' disabled.", action)

        # ── delete ────────────────────────────────────────────────────────────
        elif action == "delete":
            if not task_name:
                return _err("'task_name' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete task '{task_name}'? Set confirmed=true.", action)
            safe = task_name.replace("'", "''")
            result = _run_ps(f"Unregister-ScheduledTask -TaskName '{safe}' -Confirm:$false")
            return _ok(f"Task '{task_name}' deleted.", action)

        # ── create ────────────────────────────────────────────────────────────
        elif action == "create":
            if not task_name or not action_path:
                return _err("'task_name' and 'action_path' are required.", action)
            safe_name = task_name.replace("'", "''")
            safe_path = action_path.replace("'", "''")
            safe_args = action_args.replace("'", "''")

            # Build trigger
            if trigger_type == "daily":
                trigger_ps = f"New-ScheduledTaskTrigger -Daily -At '{trigger_time}'"
            elif trigger_type == "weekly":
                days_str = ",".join(trigger_days) if trigger_days else "Monday"
                trigger_ps = f"New-ScheduledTaskTrigger -Weekly -DaysOfWeek {days_str} -At '{trigger_time}'"
            elif trigger_type == "on_logon":
                trigger_ps = "New-ScheduledTaskTrigger -AtLogon"
            elif trigger_type == "on_startup":
                trigger_ps = "New-ScheduledTaskTrigger -AtStartup"
            elif trigger_type == "once":
                trigger_ps = f"New-ScheduledTaskTrigger -Once -At '{trigger_time}'"
            elif trigger_type == "hourly":
                trigger_ps = f"New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At '{trigger_time}'"
            elif trigger_type == "on_idle":
                trigger_ps = "New-ScheduledTaskTrigger -AtStartup"  # Best approximation
            else:
                return _err(f"Unknown trigger_type: '{trigger_type}'. Use: daily, weekly, on_logon, on_startup, once, hourly", action)

            script = f"""
$trigger = {trigger_ps}
$action  = New-ScheduledTaskAction -Execute '{safe_path}' -Argument '{safe_args}'
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId '{run_as_user}' -RunLevel {run_level}
Register-ScheduledTask -TaskName '{safe_name}' -Trigger $trigger -Action $action `
    -Settings $settings -Principal $principal -Force
"""
            result = _run_ps(script, timeout=30)
            return _ok(f"Task '{task_name}' created.\n{result}", action)

        # ── create_python ─────────────────────────────────────────────────────
        elif action == "create_python":
            """Helper: create a task that runs a Python script."""
            script_path = parameters.get("script_path", "").strip()
            if not task_name or not script_path:
                return _err("'task_name' and 'script_path' are required.", action)
            import sys
            python_exe = sys.executable.replace("\\", "\\\\")
            safe_script = script_path.replace("'", "''")
            return win_tasks({**parameters,
                              "action": "create",
                              "action_path": python_exe,
                              "action_args": f'"{safe_script}"'},
                             response, player, session_memory)

        # ── get_last_result ───────────────────────────────────────────────────
        elif action == "get_last_result":
            if not task_name:
                return _err("'task_name' is required.", action)
            safe = task_name.replace("'", "''")
            script = (
                f"$t = Get-ScheduledTask -TaskName '{safe}' | Get-ScheduledTaskInfo; "
                "$t | Select-Object TaskName,LastRunTime,LastTaskResult,NextRunTime | Format-List"
            )
            result = _run_ps(script)
            return _ok(result, action)

        # ── list_running ──────────────────────────────────────────────────────
        elif action == "list_running":
            result = _run_ps(
                "Get-ScheduledTask | Where-Object {$_.State -eq 'Running'} | "
                "Select-Object TaskName,TaskPath | Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result if result.strip() else "No tasks currently running.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, get_detail, run_now, enable, disable, "
                "delete, create, create_python, get_last_result, list_running",
                action)

    except Exception as e:
        return _err(str(e), action)
