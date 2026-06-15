"""
win_display.py — Display/monitor management for VYRA Windows control.
Uses pywin32 (win32api, win32con) + PowerShell for multi-monitor, resolution, refresh rate.
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


def _try_win32():
    """Try importing win32api. Returns module or None."""
    try:
        import win32api
        import win32con
        return win32api, win32con
    except ImportError:
        return None, None


def win_display(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action        = parameters.get("action", "").lower().strip()
    monitor_index = int(parameters.get("monitor_index", 0))
    width         = parameters.get("width")
    height        = parameters.get("height")
    refresh_rate  = parameters.get("refresh_rate")
    rotation      = parameters.get("rotation", 0)

    try:
        # ── list_displays ─────────────────────────────────────────────────────
        if action == "list_displays":
            win32api, win32con = _try_win32()
            if win32api:
                devices = []
                i = 0
                while True:
                    try:
                        dev = win32api.EnumDisplayDevices(None, i)
                        if dev.DeviceName:
                            dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                            devices.append(
                                f"  Display {i}: {dev.DeviceString}\n"
                                f"    Resolution: {dm.PelsWidth}x{dm.PelsHeight} @ {dm.DisplayFrequency}Hz\n"
                                f"    Flags: {'PRIMARY' if dev.StateFlags & 4 else 'SECONDARY'}")
                        i += 1
                    except Exception:
                        break
                return _ok("\n".join(devices) if devices else "No displays found.", action)
            else:
                result = _run_ps(
                    "Get-WmiObject Win32_VideoController | "
                    "Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution,"
                    "CurrentRefreshRate,VideoModeDescription | Format-List | Out-String"
                )
                return _ok(result, action)

        # ── get_resolution ────────────────────────────────────────────────────
        elif action == "get_resolution":
            win32api, win32con = _try_win32()
            if win32api:
                try:
                    devices = list(
                        win32api.EnumDisplayDevices(None, i)
                        for i in range(10)
                        if win32api.EnumDisplayDevices(None, i).DeviceName
                    )
                    dev = devices[monitor_index]
                    dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    return _ok(
                        f"Monitor {monitor_index}: {dm.PelsWidth}x{dm.PelsHeight} @ {dm.DisplayFrequency}Hz | "
                        f"Rotation: {dm.DisplayOrientation*90}°", action)
                except (IndexError, Exception) as e:
                    return _err(str(e), action)
            else:
                result = _run_ps(
                    "Get-WmiObject Win32_VideoController | "
                    "Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate | "
                    "Format-Table -AutoSize | Out-String"
                )
                return _ok(result, action)

        # ── set_resolution ────────────────────────────────────────────────────
        elif action == "set_resolution":
            if width is None or height is None:
                return _err("'width' and 'height' are required.", action)
            win32api, win32con = _try_win32()
            if win32api:
                try:
                    devices = []
                    for i in range(10):
                        try:
                            d = win32api.EnumDisplayDevices(None, i)
                            if d.DeviceName:
                                devices.append(d)
                        except Exception:
                            break
                    dev = devices[monitor_index]
                    dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    dm.PelsWidth  = int(width)
                    dm.PelsHeight = int(height)
                    if refresh_rate:
                        dm.DisplayFrequency = int(refresh_rate)
                    dm.Fields = (win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT |
                                 (win32con.DM_DISPLAYFREQUENCY if refresh_rate else 0))
                    result = win32api.ChangeDisplaySettingsEx(dev.DeviceName, dm, 0)
                    if result == 0:
                        return _ok(f"Resolution set to {width}x{height}" +
                                   (f" @ {refresh_rate}Hz" if refresh_rate else "") +
                                   " (may flicker briefly).", action)
                    return _err(f"Display change failed (code {result}).", action)
                except IndexError:
                    return _err(f"Monitor {monitor_index} not found.", action)
            else:
                # Fallback: PowerShell using DisplayUtil
                script = f"""
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Display {{
    [DllImport("user32.dll")] public static extern int ChangeDisplaySettings(ref DEVMODE dm, int flags);
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Ansi)]
    public struct DEVMODE {{
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmDeviceName;
        public short dmSpecVersion,dmDriverVersion,dmSize,dmDriverExtra,dmFields;
        public int dmPositionX,dmPositionY,dmDisplayOrientation,dmDisplayFixedOutput;
        public short dmColor,dmDuplex,dmYResolution,dmTTOption,dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst=32)] public string dmFormName;
        public short dmLogPixels; public int dmBitsPerPel,dmPelsWidth,dmPelsHeight;
        public int dmDisplayFlags,dmDisplayFrequency;
    }}
}}
"@
$dm = New-Object Display+DEVMODE
$dm.dmSize = [System.Runtime.InteropServices.Marshal]::SizeOf($dm)
$dm.dmPelsWidth  = {int(width)}
$dm.dmPelsHeight = {int(height)}
$dm.dmFields = 0x00080000 -bor 0x00100000
[Display]::ChangeDisplaySettings([ref]$dm, 0)
"""
                result = _run_ps(script)
                return _ok(f"Resolution changed to {width}x{height}.\n{result}", action)

        # ── list_resolutions ──────────────────────────────────────────────────
        elif action == "list_resolutions":
            win32api, win32con = _try_win32()
            if win32api:
                try:
                    devices = []
                    for i in range(10):
                        try:
                            d = win32api.EnumDisplayDevices(None, i)
                            if d.DeviceName:
                                devices.append(d)
                        except Exception:
                            break
                    dev = devices[monitor_index]
                    seen = set()
                    lines = [f"Available resolutions for Monitor {monitor_index}:"]
                    j = 0
                    while True:
                        try:
                            dm = win32api.EnumDisplaySettings(dev.DeviceName, j)
                            key = (dm.PelsWidth, dm.PelsHeight, dm.DisplayFrequency)
                            if key not in seen:
                                seen.add(key)
                                lines.append(f"  {dm.PelsWidth}x{dm.PelsHeight} @ {dm.DisplayFrequency}Hz")
                            j += 1
                        except Exception:
                            break
                    return _ok("\n".join(lines), action)
                except IndexError:
                    return _err(f"Monitor {monitor_index} not found.", action)
            else:
                return _err("pywin32 not installed. Run: pip install pywin32", action)

        # ── set_refresh_rate ──────────────────────────────────────────────────
        elif action == "set_refresh_rate":
            if not refresh_rate:
                return _err("'refresh_rate' is required.", action)
            win32api, win32con = _try_win32()
            if win32api:
                try:
                    devices = []
                    for i in range(10):
                        try:
                            d = win32api.EnumDisplayDevices(None, i)
                            if d.DeviceName:
                                devices.append(d)
                        except Exception:
                            break
                    dev = devices[monitor_index]
                    dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    dm.DisplayFrequency = int(refresh_rate)
                    dm.Fields = win32con.DM_DISPLAYFREQUENCY
                    result = win32api.ChangeDisplaySettingsEx(dev.DeviceName, dm, 0)
                    if result == 0:
                        return _ok(f"Refresh rate set to {refresh_rate}Hz.", action)
                    return _err(f"Change failed (code {result}).", action)
                except IndexError:
                    return _err(f"Monitor {monitor_index} not found.", action)
            else:
                return _err("pywin32 not installed. Run: pip install pywin32", action)

        # ── rotate_display ────────────────────────────────────────────────────
        elif action == "rotate_display":
            """0, 90, 180, 270 degrees."""
            rot_map = {0: 0, 90: 1, 180: 2, 270: 3}
            rot_val = rot_map.get(int(rotation), 0)
            win32api, win32con = _try_win32()
            if win32api:
                try:
                    devices = []
                    for i in range(10):
                        try:
                            d = win32api.EnumDisplayDevices(None, i)
                            if d.DeviceName:
                                devices.append(d)
                        except Exception:
                            break
                    dev = devices[monitor_index]
                    dm = win32api.EnumDisplaySettings(dev.DeviceName, win32con.ENUM_CURRENT_SETTINGS)
                    dm.DisplayOrientation = rot_val
                    dm.Fields = win32con.DM_DISPLAYORIENTATION
                    # Swap width/height for 90/270
                    if rot_val in (1, 3) and dm.PelsWidth > dm.PelsHeight:
                        dm.PelsWidth, dm.PelsHeight = dm.PelsHeight, dm.PelsWidth
                        dm.Fields |= win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT
                    result = win32api.ChangeDisplaySettingsEx(dev.DeviceName, dm, 0)
                    if result == 0:
                        return _ok(f"Display rotated to {rotation}°.", action)
                    return _err(f"Rotation failed (code {result}).", action)
                except IndexError:
                    return _err(f"Monitor {monitor_index} not found.", action)
            else:
                return _err("pywin32 not installed.", action)

        # ── night_light_on ────────────────────────────────────────────────────
        elif action == "night_light_on":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:display"], shell=True)
            return _ok("Opened Display settings. Toggle Night Light manually if needed.\n"
                       "Note: Night Light registry toggle is unreliable without UWP APIs.", action)

        # ── night_light_off ───────────────────────────────────────────────────
        elif action == "night_light_off":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:display"], shell=True)
            return _ok("Opened Display settings. Toggle Night Light manually.", action)

        # ── set_scale ─────────────────────────────────────────────────────────
        elif action == "set_scale":
            """Set display DPI scaling (100, 125, 150, 175, 200%)."""
            scale = int(parameters.get("scale", 100))
            valid = {100: 0, 125: 1, 150: 2, 175: 3, 200: 4}
            if scale not in valid:
                return _err(f"Invalid scale {scale}. Use: 100, 125, 150, 175, 200", action)
            # Registry path for logical DPI override
            result = _run_ps(
                f"Set-ItemProperty -Path 'HKCU:\\Control Panel\\Desktop' "
                f"-Name 'LogPixels' -Value {96 + (scale - 100) * 96 // 100} -Type DWord"
            )
            return _ok(f"DPI scale set to {scale}% (log off to apply fully).", action)

        # ── open_display_settings ─────────────────────────────────────────────
        elif action == "open_display_settings":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:display"], shell=True)
            return _ok("Display settings opened.", action)

        # ── get_gpu_info ──────────────────────────────────────────────────────
        elif action == "get_gpu_info":
            result = _run_ps(
                "Get-WmiObject Win32_VideoController | "
                "Select-Object Name,AdapterRAM,CurrentHorizontalResolution,CurrentVerticalResolution,"
                "CurrentRefreshRate,DriverVersion,VideoProcessor | Format-List | Out-String"
            )
            return _ok(result, action)

        # ── turn_off_screen ───────────────────────────────────────────────────
        elif action == "turn_off_screen":
            import subprocess as sp
            # SendMessage to HWND_BROADCAST with WM_SYSCOMMAND SC_MONITORPOWER 2
            ps = """
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class Monitor {
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    public static readonly IntPtr HWND_BROADCAST = new IntPtr(0xffff);
}
"@
[Monitor]::SendMessage([Monitor]::HWND_BROADCAST, 0x0112, new-object IntPtr(0xf170), new-object IntPtr(2))
"""
            _run_ps(ps)
            return _ok("Screen turned off.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_displays, get_resolution, set_resolution, "
                "list_resolutions, set_refresh_rate, rotate_display, night_light_on, night_light_off, "
                "set_scale, open_display_settings, get_gpu_info, turn_off_screen",
                action)

    except Exception as e:
        return _err(str(e), action)
