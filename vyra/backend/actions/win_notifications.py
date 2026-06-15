"""
win_notifications.py — Windows 10/11 toast notifications for VYRA.
Primary: winotify. Fallback: PowerShell BurntToast / WScript balloon.
"""
import json
import subprocess
import os
import tempfile


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


def _toast_via_ps(title: str, message: str, icon_path: str = "", app_id: str = "VYRA") -> str:
    """Fallback: use PowerShell BurntToast or raw XML toast."""
    # Try BurntToast module first
    ps_check = "if (Get-Module -ListAvailable -Name BurntToast) { 'yes' } else { 'no' }"
    has_bt = _run_ps(ps_check).strip().lower() == "yes"

    if has_bt:
        safe_title = title.replace("'", "''")
        safe_msg   = message.replace("'", "''")
        script = f"New-BurntToastNotification -Text '{safe_title}', '{safe_msg}'"
        _run_ps(script)
        return "Toast sent via BurntToast."
    else:
        # Raw Windows Runtime toast via PowerShell
        safe_title = title.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        safe_msg   = message.replace('"', '&quot;').replace('<', '&lt;').replace('>', '&gt;')
        ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null

$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{safe_title}</text>
      <text>{safe_msg}</text>
    </binding>
  </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
"""
        _run_ps(ps_script)
        return "Toast sent via PowerShell WinRT."


def win_notifications(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action    = parameters.get("action", "").lower().strip()
    title     = parameters.get("title", "VYRA")
    message   = parameters.get("message", "")
    icon      = parameters.get("icon", "")
    image_path = parameters.get("image_path", "")
    buttons   = parameters.get("buttons", [])
    duration  = parameters.get("duration", "short")
    app_id    = parameters.get("app_id", "VYRA")
    sound     = parameters.get("sound", True)

    try:
        # ── send ──────────────────────────────────────────────────────────────
        if action == "send":
            if not message:
                return _err("'message' is required.", action)
            try:
                from winotify import Notification
                toast = Notification(app_id=app_id, title=title, msg=message,
                                     duration="short" if duration == "short" else "long")
                if icon and os.path.exists(icon):
                    toast.set_icon(icon)
                toast.show()
                return _ok(f"Notification sent: '{title}' — {message[:80]}", action)
            except ImportError:
                result = _toast_via_ps(title, message, icon, app_id)
                return _ok(result, action)

        # ── send_with_image ───────────────────────────────────────────────────
        elif action == "send_with_image":
            if not message:
                return _err("'message' is required.", action)
            try:
                from winotify import Notification
                toast = Notification(app_id=app_id, title=title, msg=message,
                                     duration="short" if duration == "short" else "long")
                if image_path and os.path.exists(image_path):
                    toast.set_image(image_path)
                elif icon and os.path.exists(icon):
                    toast.set_icon(icon)
                toast.show()
                return _ok(f"Image notification sent: '{title}'", action)
            except ImportError:
                return _toast_via_ps(title, f"[Image: {image_path}] {message}", icon, app_id)

        # ── send_with_buttons ─────────────────────────────────────────────────
        elif action == "send_with_buttons":
            if not message:
                return _err("'message' is required.", action)
            try:
                from winotify import Notification, audio
                toast = Notification(app_id=app_id, title=title, msg=message)
                for btn in (buttons or [])[:5]:
                    label = btn if isinstance(btn, str) else btn.get("label", "Action")
                    launch = btn.get("launch", "") if isinstance(btn, dict) else ""
                    toast.add_actions(label=label, launch=launch)
                toast.show()
                return _ok(f"Notification with {len(buttons)} button(s) sent: '{title}'", action)
            except ImportError:
                result = _toast_via_ps(title, f"[Buttons: {buttons}] {message}", icon, app_id)
                return _ok(result, action)

        # ── send_progress ─────────────────────────────────────────────────────
        elif action == "send_progress":
            """Send a progress-bar toast notification via PowerShell XML."""
            progress = min(100, max(0, int(parameters.get("progress", 0))))
            status_text = parameters.get("status_text", f"{progress}% complete")
            safe_title = title.replace('"', '&quot;')
            safe_msg   = message.replace('"', '&quot;')
            safe_status = status_text.replace('"', '&quot;')
            ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null

$xml_str = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{safe_title}</text>
      <text>{safe_msg}</text>
      <progress title="" value="{progress / 100:.2f}" valueStringOverride="{safe_status}" status="{safe_status}"/>
    </binding>
  </visual>
</toast>
"@
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($xml_str)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}").Show($toast)
"""
            _run_ps(ps_script)
            return _ok(f"Progress toast sent ({progress}%): '{title}'", action)

        # ── clear_all ─────────────────────────────────────────────────────────
        elif action == "clear_all":
            result = _run_ps(
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null; "
                f"[Windows.UI.Notifications.ToastNotificationManager]::History.Clear('{app_id}')"
            )
            return _ok(f"Notification history cleared for '{app_id}'.", action)

        # ── send_reminder ─────────────────────────────────────────────────────
        elif action == "send_reminder":
            """Send a toast with a reminder sound."""
            try:
                from winotify import Notification, audio
                toast = Notification(app_id=app_id, title=title, msg=message, duration="long")
                toast.set_audio(audio.Reminder, loop=False)
                toast.show()
                return _ok(f"Reminder notification sent: '{title}'", action)
            except ImportError:
                result = _toast_via_ps(title, message, icon, app_id)
                return _ok(result, action)

        # ── send_alarm ────────────────────────────────────────────────────────
        elif action == "send_alarm":
            try:
                from winotify import Notification, audio
                toast = Notification(app_id=app_id, title=title, msg=message, duration="long")
                toast.set_audio(audio.Alarm, loop=True)
                toast.show()
                return _ok(f"Alarm notification sent: '{title}'", action)
            except ImportError:
                result = _toast_via_ps(title, message, icon, app_id)
                return _ok(result, action)

        # ── install_burnttoast ────────────────────────────────────────────────
        elif action == "install_burnttoast":
            """Install BurntToast PowerShell module as fallback."""
            result = _run_ps("Install-Module -Name BurntToast -Force -Scope CurrentUser", timeout=60)
            return _ok(result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: send, send_with_image, send_with_buttons, "
                "send_progress, send_reminder, send_alarm, clear_all, install_burnttoast",
                action)

    except Exception as e:
        return _err(str(e), action)
