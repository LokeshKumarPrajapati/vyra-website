"""
win_audio_devices.py — Audio device management for VYRA Windows control.
Primary: pycaw for per-app volume, device enumeration.
Fallback: PowerShell Get-WmiObject Win32_SoundDevice.
"""
import json
import subprocess


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
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def _get_pycaw_devices(device_type: str = "output"):
    """Returns list of (index, name, device_object) via pycaw."""
    from pycaw.pycaw import AudioUtilities, EDataFlow, IMMDeviceEnumerator, ERole
    from pycaw.pycaw import IMMDeviceCollection
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL

    devices = AudioUtilities.GetAllDevices()
    result = []
    for i, d in enumerate(devices):
        try:
            if d.FriendlyName:
                result.append((i, d.FriendlyName, d))
        except Exception:
            pass
    return result


def win_audio_devices(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action      = parameters.get("action", "").lower().strip()
    device_name = parameters.get("device_name", "").strip()
    app_name    = parameters.get("app_name", "").strip()
    volume      = parameters.get("volume")

    try:
        # ── list_outputs ──────────────────────────────────────────────────────
        if action == "list_outputs":
            try:
                from pycaw.pycaw import AudioUtilities
                devices = AudioUtilities.GetAllDevices()
                lines = ["Output/Playback Devices:"]
                for i, d in enumerate(devices):
                    try:
                        lines.append(f"  [{i}] {d.FriendlyName}")
                    except Exception:
                        pass
                return _ok("\n".join(lines) if len(lines) > 1 else "No devices found.", action)
            except ImportError:
                result = _run_ps(
                    "Get-WmiObject Win32_SoundDevice | "
                    "Select-Object Name,Manufacturer,Status | "
                    "Format-Table -AutoSize | Out-String"
                )
                return _ok(result, action)

        # ── list_inputs ───────────────────────────────────────────────────────
        elif action == "list_inputs":
            result = _run_ps(
                "Get-WmiObject Win32_SoundDevice | Where-Object {$_.Name -like '*microphone*' -or $_.Name -like '*input*' -or $_.Name -like '*mic*'} | "
                "Select-Object Name,Status | Format-Table | Out-String"
            )
            if not result.strip():
                result = _run_ps("Get-WmiObject Win32_SoundDevice | Select-Object Name,Status | Format-Table | Out-String")
            return _ok(result, action)

        # ── get_default_output ────────────────────────────────────────────────
        elif action == "get_default_output":
            try:
                from pycaw.pycaw import AudioUtilities
                device = AudioUtilities.GetSpeakers()
                if device:
                    return _ok(f"Default output: {device.GetId()}", action)
            except ImportError:
                pass
            result = _run_ps(
                "(Get-WmiObject Win32_SoundDevice | Where-Object {$_.Name -notlike '*microphone*'} | Select-Object -First 1).Name"
            )
            return _ok(f"Default audio output: {result}", action)

        # ── set_default_output ────────────────────────────────────────────────
        elif action == "set_default_output":
            if not device_name:
                return _err("'device_name' is required.", action)
            # Try nircmd if available
            safe = device_name.replace('"', '')
            result = _run_ps(
                f"try {{ "
                f"  $obj = New-Object -ComObject '{{}}';"  # placeholder
                f"}} catch {{ }}"
            )
            # Best approach: use AudioDeviceCmdlets or Set-AudioDevice if installed
            check = _run_ps(
                "if (Get-Module -ListAvailable -Name AudioDeviceCmdlets) { 'yes' } else { 'no' }")
            if check.strip() == "yes":
                result = _run_ps(f"Get-AudioDevice -List | Where-Object {{$_.Name -like '*{safe}*'}} | Set-AudioDevice")
                return _ok(f"Default output changed to device matching '{device_name}'.", action)
            else:
                return _ok(
                    f"To set default audio device, install AudioDeviceCmdlets:\n"
                    f"  Install-Module AudioDeviceCmdlets -Force\n"
                    f"Or open Sound settings (Win+I → System → Sound) and select '{device_name}'.", action)

        # ── get_volume ────────────────────────────────────────────────────────
        elif action == "get_volume":
            try:
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume_ctl = cast(interface, POINTER(IAudioEndpointVolume))
                vol = round(volume_ctl.GetMasterVolumeLevelScalar() * 100)
                muted = volume_ctl.GetMute()
                return _ok(f"System volume: {vol}% {'(MUTED)' if muted else ''}", action)
            except ImportError:
                return _err("pycaw not installed. Run: pip install pycaw", action)

        # ── set_volume ────────────────────────────────────────────────────────
        elif action == "set_volume":
            if volume is None:
                return _err("'volume' (0-100) is required.", action)
            vol_val = max(0, min(100, int(volume)))
            try:
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume_ctl = cast(interface, POINTER(IAudioEndpointVolume))
                volume_ctl.SetMasterVolumeLevelScalar(vol_val / 100.0, None)
                return _ok(f"System volume set to {vol_val}%.", action)
            except ImportError:
                # Fallback via nircmd or PowerShell audio API
                result = _run_ps(
                    f"$wshShell = New-Object -ComObject WScript.Shell; "
                    f"# Simulate keystrokes to set volume - limited fallback\n"
                    f"Add-Type -AssemblyName System.Windows.Forms; "
                    f"[System.Windows.Forms.SendKeys]::SendWait('')"
                )
                return _err("pycaw required for volume control. Run: pip install pycaw", action)

        # ── mute / unmute ─────────────────────────────────────────────────────
        elif action in ("mute", "unmute"):
            try:
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                from ctypes import cast, POINTER
                from comtypes import CLSCTX_ALL
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume_ctl = cast(interface, POINTER(IAudioEndpointVolume))
                volume_ctl.SetMute(1 if action == "mute" else 0, None)
                return _ok(f"System {'muted' if action == 'mute' else 'unmuted'}.", action)
            except ImportError:
                import pyautogui
                pyautogui.press("volumemute")
                return _ok(f"Mute toggled (via keyboard shortcut).", action)

        # ── list_app_volumes ──────────────────────────────────────────────────
        elif action == "list_app_volumes":
            try:
                from pycaw.pycaw import AudioUtilities
                sessions = AudioUtilities.GetAllSessions()
                lines = ["Application Volumes:"]
                for s in sessions:
                    try:
                        from pycaw.pycaw import ISimpleAudioVolume
                        from ctypes import cast, POINTER
                        sv = s._ctl.QueryInterface(ISimpleAudioVolume)
                        vol = round(sv.GetMasterVolume() * 100)
                        muted = sv.GetMute()
                        proc_name = s.Process.name() if s.Process else "System"
                        lines.append(f"  {proc_name:<35} {vol:>3}% {'(muted)' if muted else ''}")
                    except Exception:
                        pass
                return _ok("\n".join(lines), action)
            except ImportError:
                return _err("pycaw not installed. Run: pip install pycaw", action)

        # ── set_app_volume ────────────────────────────────────────────────────
        elif action == "set_app_volume":
            if not app_name or volume is None:
                return _err("'app_name' and 'volume' are required.", action)
            vol_val = max(0, min(100, int(volume))) / 100.0
            try:
                from pycaw.pycaw import AudioUtilities, ISimpleAudioVolume
                from ctypes import cast, POINTER
                sessions = AudioUtilities.GetAllSessions()
                matched = []
                for s in sessions:
                    try:
                        if s.Process and app_name.lower() in s.Process.name().lower():
                            sv = s._ctl.QueryInterface(ISimpleAudioVolume)
                            sv.SetMasterVolume(vol_val, None)
                            matched.append(s.Process.name())
                    except Exception:
                        pass
                if matched:
                    return _ok(f"Volume set to {int(vol_val*100)}% for: {', '.join(matched)}", action)
                return _err(f"No running app matching '{app_name}' found.", action)
            except ImportError:
                return _err("pycaw not installed. Run: pip install pycaw", action)

        # ── open_sound_settings ───────────────────────────────────────────────
        elif action == "open_sound_settings":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:sound"], shell=True)
            return _ok("Sound settings opened.", action)

        # ── install_audio_cmdlets ─────────────────────────────────────────────
        elif action == "install_audio_cmdlets":
            result = _run_ps("Install-Module AudioDeviceCmdlets -Force -Scope CurrentUser", timeout=60)
            return _ok(result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_outputs, list_inputs, get_default_output, "
                "set_default_output, get_volume, set_volume, mute, unmute, list_app_volumes, "
                "set_app_volume, open_sound_settings, install_audio_cmdlets",
                action)

    except Exception as e:
        return _err(str(e), action)
