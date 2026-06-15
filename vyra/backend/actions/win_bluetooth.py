"""
win_bluetooth.py — Bluetooth device management for VYRA Windows control.
Uses PowerShell + Windows Device Manager PnP APIs.
Note: Full BT pairing requires WinRT APIs (PowerShell 7+ / C# interop).
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


def win_bluetooth(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action      = parameters.get("action", "").lower().strip()
    device_name = parameters.get("device_name", "").strip()
    device_addr = parameters.get("device_address", "").strip()

    try:
        # ── get_status ────────────────────────────────────────────────────────
        if action == "get_status":
            result = _run_ps(
                "$bt = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
                "Where-Object {$_.FriendlyName -like '*Bluetooth*' -or $_.FriendlyName -like '*Radio*'} | "
                "Select-Object -First 1; "
                "if ($bt) { "
                "  Write-Output \"Bluetooth adapter: $($bt.FriendlyName)\"; "
                "  Write-Output \"Status: $($bt.Status)\" "
                "} else { Write-Output 'No Bluetooth adapter found or driver not loaded.' }"
            )
            return _ok(result, action)

        # ── list_paired ───────────────────────────────────────────────────────
        elif action == "list_paired":
            result = _run_ps(
                "Get-PnpDevice -Class Bluetooth | "
                "Where-Object {$_.Status -in ('OK', 'Unknown', 'Degraded')} | "
                "Select-Object FriendlyName,Status,InstanceId | "
                "Format-Table -AutoSize | Out-String -Width 150"
            )
            return _ok(result if result.strip() else "No paired Bluetooth devices found.", action)

        # ── list_all_bt_devices ───────────────────────────────────────────────
        elif action == "list_all_bt_devices":
            result = _run_ps(
                "Get-PnpDevice -Class Bluetooth | "
                "Select-Object FriendlyName,Status,InstanceId | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result if result.strip() else "No Bluetooth devices found.", action)

        # ── enable ────────────────────────────────────────────────────────────
        elif action == "enable":
            result = _run_ps(
                "Get-PnpDevice -Class Bluetooth | "
                "Where-Object {$_.Status -eq 'Disabled'} | "
                "ForEach-Object { Enable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false }; "
                "Write-Output 'Bluetooth devices enabled.'"
            )
            return _ok(result, action)

        # ── disable ───────────────────────────────────────────────────────────
        elif action == "disable":
            if not parameters.get("confirmed"):
                return _err("Disable Bluetooth adapter? Set confirmed=true.", action)
            result = _run_ps(
                "Get-PnpDevice -Class Bluetooth | "
                "Where-Object {$_.Status -eq 'OK'} | "
                "ForEach-Object { Disable-PnpDevice -InstanceId $_.InstanceId -Confirm:$false }; "
                "Write-Output 'Bluetooth adapter disabled.'"
            )
            return _ok(result, action)

        # ── open_settings ─────────────────────────────────────────────────────
        elif action == "open_settings":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:bluetooth"], shell=True)
            return _ok("Bluetooth settings opened.", action)

        # ── connect ───────────────────────────────────────────────────────────
        elif action == "connect":
            if not device_name and not device_addr:
                return _err("'device_name' or 'device_address' is required.", action)
            # WinRT-based connect via PowerShell 7+
            search = device_addr if device_addr else device_name
            safe = search.replace("'", "''")
            ps_script = f"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Devices.Bluetooth.BluetoothDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime]
$null = [Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime]

$selector = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelector()
$devices = [Windows.Devices.Enumeration.DeviceInformation]::FindAllAsync($selector).GetAwaiter().GetResult()
$target = $devices | Where-Object {{$_.Name -like '*{safe}*'}} | Select-Object -First 1

if ($target) {{
    $btDevice = [Windows.Devices.Bluetooth.BluetoothDevice]::FromIdAsync($target.Id).GetAwaiter().GetResult()
    Write-Output "Found: $($btDevice.Name) [$($btDevice.ConnectionStatus)]"
}} else {{
    Write-Output "Device '{safe}' not found in paired devices. Open Bluetooth settings to pair."
}}
"""
            result = _run_ps(ps_script, timeout=30)
            return _ok(result, action)

        # ── disconnect ────────────────────────────────────────────────────────
        elif action == "disconnect":
            if not device_name and not device_addr:
                return _err("'device_name' or 'device_address' is required.", action)
            safe = (device_addr or device_name).replace("'", "''")
            result = _run_ps(
                f"$dev = Get-PnpDevice -Class Bluetooth | "
                f"Where-Object {{$_.FriendlyName -like '*{safe}*'}} | Select-Object -First 1; "
                "if ($dev) { Disable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false; "
                "Start-Sleep 1; Enable-PnpDevice -InstanceId $dev.InstanceId -Confirm:$false; "
                "Write-Output 'Device disconnected and re-enabled.' } "
                "else { Write-Output 'Device not found.' }"
            )
            return _ok(result, action)

        # ── remove_device ─────────────────────────────────────────────────────
        elif action == "remove_device":
            if not device_name and not device_addr:
                return _err("'device_name' or 'device_address' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Remove Bluetooth device '{device_name or device_addr}'? Set confirmed=true.", action)
            safe = (device_addr or device_name).replace("'", "''")
            result = _run_ps(
                f"$dev = Get-PnpDevice -Class Bluetooth | "
                f"Where-Object {{$_.FriendlyName -like '*{safe}*'}} | Select-Object -First 1; "
                "if ($dev) { & pnputil /remove-device $dev.InstanceId; Write-Output 'Device removed.' } "
                "else { Write-Output 'Device not found.' }"
            )
            return _ok(result, action)

        # ── scan ──────────────────────────────────────────────────────────────
        elif action == "scan":
            """Start BT discovery scan (opens settings for user to pair)."""
            ps_script = """
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Devices.Enumeration.DeviceInformation,Windows.Devices.Enumeration,ContentType=WindowsRuntime]
$selector = [Windows.Devices.Bluetooth.BluetoothDevice]::GetDeviceSelectorFromPairingState($false)
$watcher = [Windows.Devices.Enumeration.DeviceInformation]::CreateWatcher($selector)
$found = [System.Collections.Generic.List[string]]::new()
$watcher.add_Added([Windows.Foundation.TypedEventHandler[Windows.Devices.Enumeration.DeviceWatcher, Windows.Devices.Enumeration.DeviceInformation]]{
    param($s,$e); $found.Add($e.Name)
})
$watcher.Start()
Start-Sleep 5
$watcher.Stop()
if ($found.Count -gt 0) {
    "Discovered nearby BT devices:"
    $found | ForEach-Object { "  - $_" }
} else {
    "No nearby Bluetooth devices found. Ensure devices are discoverable."
}
"""
            result = _run_ps(ps_script, timeout=20)
            return _ok(result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: get_status, list_paired, list_all_bt_devices, "
                "enable, disable, open_settings, connect, disconnect, remove_device, scan",
                action)

    except Exception as e:
        return _err(str(e), action)
