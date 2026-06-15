"""
win_clipboard.py — Clipboard read/write/history for VYRA Windows control.
Uses pyperclip for current clipboard; Windows 10+ history via registry/WinRT.
"""
import json
import subprocess


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
        return out if out else (f"[stderr]: {err}" if err else "No output.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def win_clipboard(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()

    try:
        if action == "get_current":
            try:
                import pyperclip
                text = pyperclip.paste()
                return _ok(text if text else "(clipboard is empty)", action)
            except Exception as e:
                # Fallback to PowerShell
                result = _run_ps("Get-Clipboard")
                return _ok(result, action)

        elif action == "set":
            text = parameters.get("text", "")
            try:
                import pyperclip
                pyperclip.copy(text)
                return _ok(f"Clipboard set to: {text[:100]}{'...' if len(text)>100 else ''}", action)
            except Exception:
                # Fallback via PowerShell
                safe = text.replace("'", "''")
                _run_ps(f"Set-Clipboard -Value '{safe}'")
                return _ok("Clipboard updated via PowerShell.", action)

        elif action == "get_history":
            # Windows clipboard history — requires Clipboard History enabled in Windows settings
            ps_script = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.ApplicationModel.DataTransfer.Clipboard,Windows.ApplicationModel.DataTransfer,ContentType=WindowsRuntime]
$history = [Windows.ApplicationModel.DataTransfer.Clipboard]::GetHistoryItemsAsync().GetAwaiter().GetResult()
if ($history.Status -eq 'Success') {
    $items = $history.Items | Select-Object -First 20
    $out = @()
    foreach ($item in $items) {
        $text = $item.Content.GetTextAsync().GetAwaiter().GetResult()
        $out += $text
    }
    $out -join "`n---`n"
} else {
    "Clipboard history not available. Enable it in Settings > System > Clipboard."
}
"""
            result = _run_ps(ps_script, timeout=20)
            return _ok(result, action)

        elif action == "clear_history":
            result = _run_ps("""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.ApplicationModel.DataTransfer.Clipboard,Windows.ApplicationModel.DataTransfer,ContentType=WindowsRuntime]
[Windows.ApplicationModel.DataTransfer.Clipboard]::ClearHistory()
"Clipboard history cleared."
""", timeout=15)
            return _ok(result, action)

        elif action == "paste_from_history":
            # Not directly controllable via API — guide user
            return _ok("To paste from clipboard history, press Win+V to open the clipboard history panel and click an item.", action)

        else:
            return _err(f"Unknown action: '{action}'. Use: get_current, set, get_history, clear_history, paste_from_history", action)

    except Exception as e:
        return _err(str(e), action)
