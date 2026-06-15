"""
win_theme.py — Windows theme, appearance, and personalization for VYRA.
Controls dark/light mode, accent color, wallpaper, taskbar, transparency, lock screen.
"""
import json
import subprocess
import os
import winreg


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


_PERSONALIZE_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_ACCENT_KEY      = r"SOFTWARE\Microsoft\Windows\DWM"


def _set_reg(key_path: str, name: str, value: int, reg_type=winreg.REG_DWORD,
             hive=winreg.HKEY_CURRENT_USER):
    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, reg_type, value)


def _get_reg(key_path: str, name: str, hive=winreg.HKEY_CURRENT_USER):
    try:
        with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, name)
            return val
    except (FileNotFoundError, OSError):
        return None


def win_theme(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()

    try:
        # ── set_dark_mode ─────────────────────────────────────────────────────
        if action == "set_dark_mode":
            # 0 = dark, 1 = light
            _set_reg(_PERSONALIZE_KEY, "AppsUseLightTheme", 0)
            _set_reg(_PERSONALIZE_KEY, "SystemUsesLightTheme", 0)
            # Notify explorer to refresh
            _run_ps("Stop-Process -Name Explorer -Force -ErrorAction SilentlyContinue")
            return _ok("Dark mode enabled.", action)

        # ── set_light_mode ────────────────────────────────────────────────────
        elif action == "set_light_mode":
            _set_reg(_PERSONALIZE_KEY, "AppsUseLightTheme", 1)
            _set_reg(_PERSONALIZE_KEY, "SystemUsesLightTheme", 1)
            _run_ps("Stop-Process -Name Explorer -Force -ErrorAction SilentlyContinue")
            return _ok("Light mode enabled.", action)

        # ── get_current_theme ─────────────────────────────────────────────────
        elif action == "get_current_theme":
            apps_light  = _get_reg(_PERSONALIZE_KEY, "AppsUseLightTheme")
            sys_light   = _get_reg(_PERSONALIZE_KEY, "SystemUsesLightTheme")
            transparency = _get_reg(_PERSONALIZE_KEY, "EnableTransparency")
            accent_color = _get_reg(_ACCENT_KEY, "AccentColor")

            mode = "Light" if apps_light else "Dark"
            sys_mode = "Light" if sys_light else "Dark"
            transp = "Enabled" if transparency else "Disabled"

            result = (
                f"App Mode:      {mode}\n"
                f"System Mode:   {sys_mode}\n"
                f"Transparency:  {transp}\n"
                f"Accent Color:  #{accent_color:06X}" if accent_color else "Accent Color: N/A"
            )
            return _ok(result, action)

        # ── set_accent_color ──────────────────────────────────────────────────
        elif action == "set_accent_color":
            """Set accent color by hex (#RRGGBB) or named color."""
            color_hex = parameters.get("color", "").strip().lstrip("#")
            named_colors = {
                "blue":    "FF005FB8", "red":     "FFFE3620",
                "green":   "FF107C10", "purple":  "FF8764B8",
                "orange":  "FFCA5010", "teal":    "FF038387",
                "pink":    "FFFF0099", "yellow":  "FFFFD700",
            }
            if color_hex.lower() in named_colors:
                abgr_hex = named_colors[color_hex.lower()]
            elif len(color_hex) == 6:
                # Convert RGB → ABGR (Windows stores as ABGR)
                r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
                abgr = (0xFF << 24) | (b << 16) | (g << 8) | r
                abgr_hex = f"{abgr:08X}"
            else:
                return _err("'color' must be a hex color (#RRGGBB) or name: blue/red/green/purple/orange/teal/pink/yellow", action)
            color_int = int(abgr_hex, 16)
            _set_reg(_ACCENT_KEY, "AccentColor", color_int)
            _set_reg(_ACCENT_KEY, "ColorizationColor", color_int)
            _run_ps("Stop-Process -Name Explorer -Force -ErrorAction SilentlyContinue")
            return _ok(f"Accent color set to #{color_hex.upper()}.", action)

        # ── set_wallpaper ─────────────────────────────────────────────────────
        elif action == "set_wallpaper":
            img_path = parameters.get("image_path", "").strip()
            if not img_path or not os.path.exists(img_path):
                return _err("'image_path' must be a valid file path.", action)
            abs_path = os.path.abspath(img_path)
            result = _run_ps(
                f"Add-Type -TypeDefinition @\"\n"
                "using System; using System.Runtime.InteropServices;\n"
                "public class Wallpaper {\n"
                "  [DllImport(\"user32.dll\")] public static extern int SystemParametersInfo(int a, int b, string c, int d);\n"
                "}\n\"@\n"
                f"[Wallpaper]::SystemParametersInfo(20, 0, '{abs_path.replace(chr(39), chr(39)*2)}', 3)"
            )
            return _ok(f"Wallpaper set to: {abs_path}", action)

        # ── set_wallpaper_style ───────────────────────────────────────────────
        elif action == "set_wallpaper_style":
            """Set wallpaper fill style: fill, fit, stretch, tile, center, span."""
            style = parameters.get("style", "fill").lower()
            style_map = {
                "fill": ("10", "0"), "fit": ("6", "0"), "stretch": ("2", "0"),
                "tile": ("0", "1"), "center": ("0", "0"), "span": ("22", "0")
            }
            if style not in style_map:
                return _err(f"Invalid style. Use: fill, fit, stretch, tile, center, span", action)
            wall_style, tile_wall = style_map[style]
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Control Panel\Desktop", 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "WallpaperStyle", 0, winreg.REG_SZ, wall_style)
                winreg.SetValueEx(k, "TileWallpaper",  0, winreg.REG_SZ, tile_wall)
            _run_ps("RUNDLL32.EXE user32.dll, UpdatePerUserSystemParameters")
            return _ok(f"Wallpaper style set to '{style}'.", action)

        # ── enable_transparency ───────────────────────────────────────────────
        elif action == "enable_transparency":
            _set_reg(_PERSONALIZE_KEY, "EnableTransparency", 1)
            return _ok("Window transparency enabled.", action)

        # ── disable_transparency ──────────────────────────────────────────────
        elif action == "disable_transparency":
            _set_reg(_PERSONALIZE_KEY, "EnableTransparency", 0)
            return _ok("Window transparency disabled.", action)

        # ── set_taskbar_position ──────────────────────────────────────────────
        elif action == "set_taskbar_position":
            """Windows 11 only supports bottom. For Win10: top/bottom/left/right."""
            position = parameters.get("position", "bottom").lower()
            pos_map = {"bottom": 3, "top": 1, "left": 0, "right": 2}
            if position not in pos_map:
                return _err("Use: top, bottom, left, right", action)
            result = _run_ps(
                f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StuckRects3' "
                f"-Name 'Settings' -Type Binary -Value ([byte[]]@(0x28,0x00,0x00,0x00,0xFF,0xFF,0xFF,0xFF,"
                f"0x02,0x00,0x00,0x00,0x{pos_map[position]:02x},0x00,0x00,0x00))"
            )
            _run_ps("Stop-Process -Name Explorer -Force -ErrorAction SilentlyContinue")
            return _ok(f"Taskbar position set to '{position}' (Explorer restarted).", action)

        # ── set_taskbar_size ──────────────────────────────────────────────────
        elif action == "set_taskbar_size":
            """Set taskbar icon size: small or large."""
            size = parameters.get("size", "small").lower()
            val = 1 if size == "small" else 0
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "TaskbarSmallIcons", 0, winreg.REG_DWORD, val)
            _run_ps("Stop-Process -Name Explorer -Force -ErrorAction SilentlyContinue")
            return _ok(f"Taskbar icons set to {'small' if val else 'large'}.", action)

        # ── open_personalization ──────────────────────────────────────────────
        elif action == "open_personalization":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:personalization"], shell=True)
            return _ok("Personalization settings opened.", action)

        # ── toggle_show_desktop_icons ─────────────────────────────────────────
        elif action == "toggle_show_desktop_icons":
            current = _get_reg(
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                "HideIcons") or 0
            new_val = 0 if current else 1
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
                                0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, "HideIcons", 0, winreg.REG_DWORD, new_val)
            _run_ps(
                "Add-Type -TypeDefinition @\"\n"
                "using System; using System.Runtime.InteropServices;\n"
                "public class RefreshDesktop { [DllImport(\"user32.dll\")] "
                "public static extern IntPtr FindWindow(string a, string b); "
                "[DllImport(\"user32.dll\")] public static extern int SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l); }\n"
                "\"@\n"
                "$hwnd = [RefreshDesktop]::FindWindow('Progman', 'Program Manager');\n"
                "[RefreshDesktop]::SendMessage($hwnd, 0x0111, [IntPtr]0x7402, [IntPtr]0)"
            )
            state = "hidden" if new_val else "shown"
            return _ok(f"Desktop icons {state}.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: set_dark_mode, set_light_mode, get_current_theme, "
                "set_accent_color, set_wallpaper, set_wallpaper_style, enable_transparency, "
                "disable_transparency, set_taskbar_position, set_taskbar_size, "
                "open_personalization, toggle_show_desktop_icons",
                action)

    except Exception as e:
        return _err(str(e), action)
