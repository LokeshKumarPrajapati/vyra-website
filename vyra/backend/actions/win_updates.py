"""
win_updates.py — Windows Update management for VYRA.
Uses Windows Update COM API via PowerShell.
"""
import json
import subprocess


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run_ps(script: str, timeout: int = 60) -> str:
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


def win_updates(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()

    try:
        # ── check ─────────────────────────────────────────────────────────────
        if action == "check":
            ps = """
$UpdateSession = New-Object -ComObject Microsoft.Update.Session
$Searcher = $UpdateSession.CreateUpdateSearcher()
try {
    $Result = $Searcher.Search("IsInstalled=0 and IsHidden=0")
    $count = $Result.Updates.Count
    if ($count -eq 0) {
        Write-Output "System is up to date. No pending updates."
    } else {
        Write-Output "$count update(s) available:"
        $Result.Updates | ForEach-Object {
            $sev = $_.MsrcSeverity
            if (-not $sev) { $sev = "Normal" }
            Write-Output "  [$sev] $($_.Title)"
        }
    }
} catch {
    Write-Output "Could not check for updates: $_"
    Write-Output "Try: winget upgrade --all"
}
"""
            result = _run_ps(ps, timeout=90)
            return _ok(result, action)

        # ── list_available ────────────────────────────────────────────────────
        elif action == "list_available":
            ps = """
$UpdateSession = New-Object -ComObject Microsoft.Update.Session
$Searcher = $UpdateSession.CreateUpdateSearcher()
$Result = $Searcher.Search("IsInstalled=0 and IsHidden=0")
$Result.Updates | Select-Object @{n='Title';e={$_.Title}},
    @{n='Severity';e={if ($_.MsrcSeverity) {$_.MsrcSeverity} else {'Normal'}}},
    @{n='Size_MB';e={[math]::Round($_.MaxDownloadSize / 1MB, 1)}},
    @{n='KB';e={($_.KBArticleIDs -join ', ')}} |
Format-Table -AutoSize | Out-String -Width 180
"""
            result = _run_ps(ps, timeout=90)
            return _ok(result if result.strip() else "No updates available.", action)

        # ── install_all ───────────────────────────────────────────────────────
        elif action == "install_all":
            if not parameters.get("confirmed"):
                return _err("Install ALL pending updates (may restart)? Set confirmed=true.", action)
            ps = """
$UpdateSession = New-Object -ComObject Microsoft.Update.Session
$Searcher = $UpdateSession.CreateUpdateSearcher()
$SearchResult = $Searcher.Search("IsInstalled=0 and IsHidden=0")
if ($SearchResult.Updates.Count -eq 0) { Write-Output "No updates available."; exit }

Write-Output "Downloading $($SearchResult.Updates.Count) update(s)..."
$Downloader = $UpdateSession.CreateUpdateDownloader()
$Downloader.Updates = $SearchResult.Updates
$Downloader.Download()

Write-Output "Installing updates..."
$Installer = $UpdateSession.CreateUpdateInstaller()
$Installer.Updates = $SearchResult.Updates
$Result = $Installer.Install()
Write-Output "Result code: $($Result.ResultCode)"
Write-Output "Reboot required: $($Result.RebootRequired)"
"""
            result = _run_ps(ps, timeout=1800)
            return _ok(result, action)

        # ── install_specific ──────────────────────────────────────────────────
        elif action == "install_specific":
            kb_ids = parameters.get("update_ids", [])
            if not kb_ids:
                return _err("'update_ids' list (KB article IDs) is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Install updates {kb_ids}? Set confirmed=true.", action)
            kb_filter = " -or ".join([f"$_.KBArticleIDs -contains '{kb}'" for kb in kb_ids])
            ps = f"""
$UpdateSession = New-Object -ComObject Microsoft.Update.Session
$Searcher = $UpdateSession.CreateUpdateSearcher()
$SearchResult = $Searcher.Search("IsInstalled=0 and IsHidden=0")
$ToInstall = New-Object -ComObject Microsoft.Update.UpdateColl
$SearchResult.Updates | Where-Object {{ {kb_filter} }} | ForEach-Object {{ $ToInstall.Add($_) | Out-Null }}
if ($ToInstall.Count -eq 0) {{ Write-Output "Specified KBs not found in available updates."; exit }}
$Downloader = $UpdateSession.CreateUpdateDownloader()
$Downloader.Updates = $ToInstall
$Downloader.Download()
$Installer = $UpdateSession.CreateUpdateInstaller()
$Installer.Updates = $ToInstall
$Result = $Installer.Install()
Write-Output "Installed $($ToInstall.Count) update(s). Reboot required: $($Result.RebootRequired)"
"""
            result = _run_ps(ps, timeout=1800)
            return _ok(result, action)

        # ── history ───────────────────────────────────────────────────────────
        elif action == "history":
            limit = int(parameters.get("limit", 20))
            ps = f"""
$Session = New-Object -ComObject Microsoft.Update.Session
$Searcher = $Session.CreateUpdateSearcher()
$Count = $Searcher.GetTotalHistoryCount()
$History = $Searcher.QueryHistory(0, [Math]::Min($Count, {limit}))
$History | Select-Object Date,Title,
    @{{n='Result';e={{switch($_.ResultCode){{1{{'In Progress'}}2{{'Succeeded'}}3{{'Succeeded (Warning)'}}4{{'Failed'}}5{{'Aborted'}}default{{'Unknown'}}}}}}}} |
Format-Table -AutoSize | Out-String -Width 180
"""
            result = _run_ps(ps, timeout=30)
            return _ok(result, action)

        # ── get_update_settings ───────────────────────────────────────────────
        elif action == "get_update_settings":
            ps = """
$AUSettings = (New-Object -ComObject Microsoft.Update.AutoUpdate).Settings
[PSCustomObject]@{
    NotificationLevel = $AUSettings.NotificationLevel
    ScheduledInstallationDay  = $AUSettings.ScheduledInstallationDay
    ScheduledInstallationTime = $AUSettings.ScheduledInstallationTime
} | Format-List
"""
            result = _run_ps(ps)
            return _ok(result, action)

        # ── open_windows_update ───────────────────────────────────────────────
        elif action == "open_windows_update":
            import subprocess as sp
            sp.Popen(["start", "ms-settings:windowsupdate"], shell=True)
            return _ok("Windows Update settings opened.", action)

        # ── get_installed_hotfixes ─────────────────────────────────────────────
        elif action == "get_installed_hotfixes":
            limit = int(parameters.get("limit", 20))
            result = _run_ps(
                f"Get-HotFix | Sort-Object InstalledOn -Descending | "
                f"Select-Object -First {limit} | "
                "Select-Object HotFixID,Description,InstalledOn,InstalledBy | "
                "Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: check, list_available, install_all, "
                "install_specific, history, get_update_settings, open_windows_update, get_installed_hotfixes",
                action)

    except Exception as e:
        return _err(str(e), action)
