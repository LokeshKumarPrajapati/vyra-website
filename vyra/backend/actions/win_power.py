"""
win_power.py — Power plan, sleep, hibernate, and battery management for VYRA.
Uses powercfg CLI + PowerShell for WMI battery queries.
"""
import json
import subprocess
import re


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run(cmd: list, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = r.stdout.strip()
        err = r.stderr.strip()
        return out if out else (f"[stderr]: {err}" if err else "Done.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def _run_ps(script: str, timeout: int = 30) -> str:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def _get_plan_guid(plan_name: str) -> str | None:
    """Resolve 'balanced', 'high_performance', 'power_saver' or a raw GUID."""
    friendly_names = {
        "balanced":        "381b4222-f694-41f0-9685-ff5bb260df2e",
        "high_performance":"8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        "power_saver":     "a1841308-3541-4fab-bc81-f71556f20b4a",
        "ultimate":        "e9a42b02-d5df-448d-aa00-03f14749eb61",
    }
    key = plan_name.lower().replace(" ", "_")
    if key in friendly_names:
        return friendly_names[key]
    # Check if it's already a GUID
    if re.match(r"[0-9a-f-]{36}", plan_name.lower()):
        return plan_name
    return None


def win_power(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action          = parameters.get("action", "").lower().strip()
    plan_name       = parameters.get("plan_name", "balanced").strip()
    timeout_minutes = parameters.get("timeout_minutes", 30)
    power_source    = parameters.get("power_source", "ac").lower()  # ac | dc
    lid_action      = parameters.get("lid_action", "sleep").lower()

    try:
        # ── list_plans ────────────────────────────────────────────────────────
        if action == "list_plans":
            result = _run(["powercfg", "/list"])
            return _ok(result, action)

        # ── get_active_plan ───────────────────────────────────────────────────
        elif action == "get_active_plan":
            result = _run(["powercfg", "/getactivescheme"])
            return _ok(result, action)

        # ── set_plan ──────────────────────────────────────────────────────────
        elif action == "set_plan":
            guid = _get_plan_guid(plan_name)
            if not guid:
                return _err(
                    f"Unknown plan '{plan_name}'. Use: balanced, high_performance, power_saver, "
                    "ultimate, or a GUID.", action)
            result = _run(["powercfg", "/setactive", guid])
            return _ok(f"Power plan set to '{plan_name}' ({guid}).\n{result}", action)

        # ── set_sleep_timeout ─────────────────────────────────────────────────
        elif action == "set_sleep_timeout":
            src = "ac" if power_source == "ac" else "dc"
            result = _run(["powercfg", f"/change", f"standby-timeout-{src}",
                           str(int(timeout_minutes))])
            return _ok(f"Sleep timeout set to {timeout_minutes} min ({src.upper()}).\n{result}", action)

        # ── set_hibernate_timeout ─────────────────────────────────────────────
        elif action == "set_hibernate_timeout":
            src = "ac" if power_source == "ac" else "dc"
            result = _run(["powercfg", "/change", f"hibernate-timeout-{src}",
                           str(int(timeout_minutes))])
            return _ok(f"Hibernate timeout set to {timeout_minutes} min ({src.upper()}).\n{result}", action)

        # ── set_screen_timeout ────────────────────────────────────────────────
        elif action == "set_screen_timeout":
            src = "ac" if power_source == "ac" else "dc"
            result = _run(["powercfg", "/change", f"monitor-timeout-{src}",
                           str(int(timeout_minutes))])
            return _ok(f"Screen timeout set to {timeout_minutes} min ({src.upper()}).\n{result}", action)

        # ── enable_hibernate / disable_hibernate ──────────────────────────────
        elif action == "enable_hibernate":
            result = _run(["powercfg", "/hibernate", "on"])
            return _ok("Hibernate enabled.\n" + result, action)

        elif action == "disable_hibernate":
            if not parameters.get("confirmed"):
                return _err("Disable hibernate (saves disk space but loses quick resume)? Set confirmed=true.", action)
            result = _run(["powercfg", "/hibernate", "off"])
            return _ok("Hibernate disabled.\n" + result, action)

        # ── sleep ─────────────────────────────────────────────────────────────
        elif action == "sleep":
            if not parameters.get("confirmed"):
                return _err("Put computer to sleep? Set confirmed=true.", action)
            result = _run_ps(
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)"
            )
            return _ok("System going to sleep.\n" + result, action)

        # ── hibernate ────────────────────────────────────────────────────────
        elif action == "hibernate":
            if not parameters.get("confirmed"):
                return _err("Hibernate system? Set confirmed=true.", action)
            result = _run_ps(
                "Add-Type -AssemblyName System.Windows.Forms; "
                "[System.Windows.Forms.Application]::SetSuspendState('Hibernate', $false, $false)"
            )
            return _ok("System hibernating.\n" + result, action)

        # ── get_battery_info ──────────────────────────────────────────────────
        elif action == "get_battery_info":
            result = _run_ps(
                "$b = Get-WmiObject Win32_Battery; "
                "if ($b) { "
                "$b | Select-Object Caption,EstimatedChargeRemaining,BatteryStatus,"
                "EstimatedRunTime,FullChargeCapacity,DesignCapacity | Format-List } "
                "else { 'No battery found (desktop system).' }"
            )
            return _ok(result, action)

        # ── battery_report ────────────────────────────────────────────────────
        elif action == "battery_report":
            import os
            out_path = os.path.join(os.path.expanduser("~"), "Desktop", "battery-report.html")
            result = _run(["powercfg", "/batteryreport", "/output", out_path])
            return _ok(f"Battery report saved to: {out_path}\n{result}", action)

        # ── set_lid_action ────────────────────────────────────────────────────
        elif action == "set_lid_action":
            action_map = {
                "nothing":   0,
                "do_nothing": 0,
                "sleep":     1,
                "hibernate": 2,
                "shutdown":  3,
            }
            val = action_map.get(lid_action)
            if val is None:
                return _err(f"Invalid lid_action. Use: do_nothing, sleep, hibernate, shutdown", action)
            src = "AC" if power_source == "ac" else "DC"
            # GUID for lid close action
            sub = "4f971e89-eebd-4455-a8de-9e59040e7347"
            setting = "5ca83367-6e45-459f-a27b-476b1d01c936"  # Lid close action
            result = _run(["powercfg", "/setacvalueindex" if src == "AC" else "/setdcvalueindex",
                           "SCHEME_CURRENT", sub, setting, str(val)])
            _run(["powercfg", "/setactive", "SCHEME_CURRENT"])
            return _ok(f"Lid {src} action set to '{lid_action}'.\n{result}", action)

        # ── get_power_report ──────────────────────────────────────────────────
        elif action == "get_power_report":
            import os
            out_path = os.path.join(os.path.expanduser("~"), "Desktop", "energy-report.html")
            result = _run(["powercfg", "/energy", "/output", out_path, "/duration", "10"])
            return _ok(f"Energy report saved to: {out_path}\n{result}", action)

        # ── prevent_sleep ─────────────────────────────────────────────────────
        elif action == "prevent_sleep":
            """Keep system awake (until VYRA releases)."""
            result = _run_ps(
                "[Windows.PowerManagement.PowerManager,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null; "
                "# Use SetThreadExecutionState as fallback\n"
                "Add-Type -TypeDefinition @\"\n"
                "using System; using System.Runtime.InteropServices;\n"
                "public class Sleep { [DllImport(\"kernel32.dll\")] "
                "public static extern uint SetThreadExecutionState(uint esFlags); }\n"
                "\"@\n"
                "[Sleep]::SetThreadExecutionState(0x80000003)  # ES_CONTINUOUS|ES_SYSTEM_REQUIRED|ES_DISPLAY_REQUIRED"
            )
            return _ok("System sleep prevented (display + system awake).", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_plans, get_active_plan, set_plan, "
                "set_sleep_timeout, set_hibernate_timeout, set_screen_timeout, "
                "enable_hibernate, disable_hibernate, sleep, hibernate, "
                "get_battery_info, battery_report, set_lid_action, get_power_report, prevent_sleep",
                action)

    except Exception as e:
        return _err(str(e), action)
