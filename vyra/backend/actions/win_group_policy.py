"""
win_group_policy.py — Local Group Policy and security settings for VYRA.
Uses secedit, gpedit.msc, and registry-based policy settings.
"""
import json
import subprocess
import os


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


def _run(cmd: list, timeout: int = 30) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        return (r.stdout + "\n" + r.stderr).strip()
    except Exception as e:
        return str(e)


def win_group_policy(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()

    try:
        # ── export_policy ─────────────────────────────────────────────────────
        if action == "export_policy":
            import time
            out_path = parameters.get("output_path",
                       os.path.join(os.path.expanduser("~"), "Desktop",
                                    f"security_policy_{int(time.time())}.inf"))
            result = _run(["secedit", "/export", "/cfg", out_path])
            return _ok(f"Security policy exported to: {out_path}\n{result}", action)

        # ── import_policy ─────────────────────────────────────────────────────
        elif action == "import_policy":
            pol_file = parameters.get("policy_file", "").strip()
            if not pol_file or not os.path.exists(pol_file):
                return _err("'policy_file' (path to .inf file) is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Apply policy from '{pol_file}'? Set confirmed=true.", action)
            result = _run(["secedit", "/configure", "/cfg", pol_file,
                           "/db", os.path.join(os.environ.get("TEMP", "C:\\Temp"), "secedit.sdb"),
                           "/overwrite", "/quiet"])
            return _ok(f"Policy applied from '{pol_file}'.\n{result}", action)

        # ── refresh_policy ────────────────────────────────────────────────────
        elif action == "refresh_policy":
            result = _run(["gpupdate", "/force"])
            return _ok(f"Group Policy refreshed.\n{result}", action)

        # ── get_policy_result ─────────────────────────────────────────────────
        elif action == "get_policy_result":
            result = _run(["gpresult", "/r"])
            return _ok(result[:5000], action)

        # ── open_gpedit ───────────────────────────────────────────────────────
        elif action == "open_gpedit":
            import subprocess as sp
            sp.Popen(["gpedit.msc"])
            return _ok("Local Group Policy Editor opened.", action)

        # ── set_password_policy ───────────────────────────────────────────────
        elif action == "set_password_policy":
            """Configure password complexity, length, age via net accounts."""
            min_length = parameters.get("min_length")
            max_age    = parameters.get("max_age_days")
            min_age    = parameters.get("min_age_days")
            history    = parameters.get("history_count")
            if not parameters.get("confirmed"):
                return _err("Changing password policy affects all users. Set confirmed=true.", action)
            parts = ["net", "accounts"]
            if min_length:
                parts += ["/MINPWLEN:" + str(int(min_length))]
            if max_age:
                parts += ["/MAXPWAGE:" + str(int(max_age))]
            if min_age:
                parts += ["/MINPWAGE:" + str(int(min_age))]
            if history:
                parts += ["/UNIQUEPW:" + str(int(history))]
            result = _run(parts)
            return _ok(f"Password policy updated.\n{result}", action)

        # ── get_password_policy ───────────────────────────────────────────────
        elif action == "get_password_policy":
            result = _run(["net", "accounts"])
            return _ok(result, action)

        # ── disable_usb_storage ───────────────────────────────────────────────
        elif action == "disable_usb_storage":
            if not parameters.get("confirmed"):
                return _err("Disable USB storage devices? Set confirmed=true.", action)
            result = _run_ps(
                "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\USBSTOR' "
                "-Name 'Start' -Value 4 -Type DWord"
            )
            return _ok("USB storage disabled (Start=4). Restart required.\n" + result, action)

        # ── enable_usb_storage ────────────────────────────────────────────────
        elif action == "enable_usb_storage":
            result = _run_ps(
                "Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Services\\USBSTOR' "
                "-Name 'Start' -Value 3 -Type DWord"
            )
            return _ok("USB storage enabled (Start=3). Restart required.\n" + result, action)

        # ── disable_autoplay ──────────────────────────────────────────────────
        elif action == "disable_autoplay":
            result = _run_ps(
                "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\AutoplayHandlers' "
                "-Name 'DisableAutoplay' -Value 1 -Type DWord"
            )
            return _ok("AutoPlay disabled for current user.\n" + result, action)

        # ── enable_autoplay ───────────────────────────────────────────────────
        elif action == "enable_autoplay":
            result = _run_ps(
                "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\AutoplayHandlers' "
                "-Name 'DisableAutoplay' -Value 0 -Type DWord"
            )
            return _ok("AutoPlay enabled.\n" + result, action)

        # ── set_screen_lock_timeout ───────────────────────────────────────────
        elif action == "set_screen_lock_timeout":
            minutes = int(parameters.get("timeout_minutes", 5))
            seconds = minutes * 60
            result = _run_ps(
                f"powercfg /change monitor-timeout-ac {minutes}; "
                f"powercfg /change monitor-timeout-dc {minutes}"
            )
            return _ok(f"Screen lock timeout set to {minutes} minutes.\n{result}", action)

        # ── disable_cmd ───────────────────────────────────────────────────────
        elif action == "disable_cmd":
            if not parameters.get("confirmed"):
                return _err("Disable Command Prompt for current user? Set confirmed=true.", action)
            result = _run_ps(
                "Set-ItemProperty -Path 'HKCU:\\Software\\Policies\\Microsoft\\Windows\\System' "
                "-Name 'DisableCMD' -Value 1 -Type DWord"
            )
            return _ok("Command Prompt disabled for current user.\n" + result, action)

        # ── enable_cmd ────────────────────────────────────────────────────────
        elif action == "enable_cmd":
            result = _run_ps(
                "Remove-ItemProperty -Path 'HKCU:\\Software\\Policies\\Microsoft\\Windows\\System' "
                "-Name 'DisableCMD' -ErrorAction SilentlyContinue"
            )
            return _ok("Command Prompt restriction removed.\n" + result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: export_policy, import_policy, refresh_policy, "
                "get_policy_result, open_gpedit, set_password_policy, get_password_policy, "
                "disable_usb_storage, enable_usb_storage, disable_autoplay, enable_autoplay, "
                "set_screen_lock_timeout, disable_cmd, enable_cmd",
                action)

    except Exception as e:
        return _err(str(e), action)
