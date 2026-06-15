"""
win_defender.py — Windows Defender / Microsoft Defender Antivirus management for VYRA.
Uses PowerShell Defender cmdlets (Get-MpComputerStatus, Start-MpScan, etc.).
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


def win_defender(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action     = parameters.get("action", "").lower().strip()
    scan_path  = parameters.get("scan_path", "").strip()
    excl_path  = parameters.get("exclusion_path", "").strip()
    excl_ext   = parameters.get("exclusion_extension", "").strip()
    excl_proc  = parameters.get("exclusion_process", "").strip()

    try:
        # ── get_status ────────────────────────────────────────────────────────
        if action == "get_status":
            result = _run_ps(
                "Get-MpComputerStatus | Select-Object "
                "AntivirusEnabled,RealTimeProtectionEnabled,IoavProtectionEnabled,"
                "AntispywareEnabled,BehaviorMonitorEnabled,"
                "AntivirusSignatureLastUpdated,AntivirusSignatureVersion,"
                "FullScanAge,QuickScanAge | Format-List | Out-String"
            )
            return _ok(result, action)

        # ── quick_scan ────────────────────────────────────────────────────────
        elif action == "quick_scan":
            result = _run_ps("Start-MpScan -ScanType QuickScan", timeout=30)
            return _ok("Quick scan started (running in background).\n" + result, action)

        # ── full_scan ─────────────────────────────────────────────────────────
        elif action == "full_scan":
            if not parameters.get("confirmed"):
                return _err("Full system scan can take 1-2 hours. Set confirmed=true.", action)
            result = _run_ps("Start-MpScan -ScanType FullScan", timeout=30)
            return _ok("Full scan started in background. Check Task Tray for progress.\n" + result, action)

        # ── custom_scan ───────────────────────────────────────────────────────
        elif action == "custom_scan":
            if not scan_path:
                return _err("'scan_path' is required for custom scan.", action)
            safe = scan_path.replace("'", "''")
            result = _run_ps(f"Start-MpScan -ScanType CustomScan -ScanPath '{safe}'", timeout=30)
            return _ok(f"Custom scan started on: {scan_path}\n{result}", action)

        # ── update_definitions ────────────────────────────────────────────────
        elif action == "update_definitions":
            result = _run_ps("Update-MpSignature", timeout=120)
            return _ok("Defender definitions update initiated.\n" + result, action)

        # ── list_exclusions ───────────────────────────────────────────────────
        elif action == "list_exclusions":
            result = _run_ps(
                "$p = Get-MpPreference; "
                "Write-Output '=== Paths ==='; $p.ExclusionPath; "
                "Write-Output '=== Extensions ==='; $p.ExclusionExtension; "
                "Write-Output '=== Processes ==='; $p.ExclusionProcess"
            )
            return _ok(result, action)

        # ── add_exclusion_path ────────────────────────────────────────────────
        elif action == "add_exclusion_path":
            if not excl_path:
                return _err("'exclusion_path' is required.", action)
            if not parameters.get("confirmed"):
                return _err(
                    f"Adding '{excl_path}' as exclusion reduces security. Set confirmed=true.", action)
            safe = excl_path.replace("'", "''")
            result = _run_ps(f"Add-MpPreference -ExclusionPath '{safe}'")
            return _ok(f"Exclusion path added: {excl_path}", action)

        # ── remove_exclusion_path ─────────────────────────────────────────────
        elif action == "remove_exclusion_path":
            if not excl_path:
                return _err("'exclusion_path' is required.", action)
            safe = excl_path.replace("'", "''")
            result = _run_ps(f"Remove-MpPreference -ExclusionPath '{safe}'")
            return _ok(f"Exclusion path removed: {excl_path}", action)

        # ── add_exclusion_extension ───────────────────────────────────────────
        elif action == "add_exclusion_extension":
            if not excl_ext:
                return _err("'exclusion_extension' is required (e.g. '.log').", action)
            if not parameters.get("confirmed"):
                return _err(f"Exclude extension '{excl_ext}'? Set confirmed=true.", action)
            safe = excl_ext.replace("'", "''")
            result = _run_ps(f"Add-MpPreference -ExclusionExtension '{safe}'")
            return _ok(f"Extension exclusion added: {excl_ext}", action)

        # ── add_exclusion_process ─────────────────────────────────────────────
        elif action == "add_exclusion_process":
            if not excl_proc:
                return _err("'exclusion_process' is required (e.g. 'python.exe').", action)
            if not parameters.get("confirmed"):
                return _err(f"Exclude process '{excl_proc}'? Set confirmed=true.", action)
            safe = excl_proc.replace("'", "''")
            result = _run_ps(f"Add-MpPreference -ExclusionProcess '{safe}'")
            return _ok(f"Process exclusion added: {excl_proc}", action)

        # ── get_threat_history ────────────────────────────────────────────────
        elif action == "get_threat_history":
            result = _run_ps(
                "Get-MpThreatDetection | Select-Object ThreatID,ActionSuccess,CurrentThreatExecutionStatusID,"
                "DetectionSourceTypeID,DomainUser,InitialDetectionTime,LastThreatStatusChangeTime,"
                "ProcessName,RemediationTime | "
                "Sort-Object InitialDetectionTime -Descending | "
                "Select-Object -First 20 | Format-Table -AutoSize | Out-String -Width 180"
            )
            return _ok(result if result.strip() else "No threat history found.", action)

        # ── get_quarantine ────────────────────────────────────────────────────
        elif action == "get_quarantine":
            result = _run_ps(
                "Get-MpThreat | Select-Object ThreatID,ThreatName,SeverityID,StatusID,IsActive | "
                "Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result if result.strip() else "No quarantined threats.", action)

        # ── enable_real_time / disable_real_time ──────────────────────────────
        elif action in ("enable_real_time", "disable_real_time"):
            if action == "disable_real_time" and not parameters.get("confirmed"):
                return _err("Disabling real-time protection is a security risk. Set confirmed=true.", action)
            state = "$false" if action == "disable_real_time" else "$true"
            result = _run_ps(f"Set-MpPreference -DisableRealtimeMonitoring {state}")
            return _ok(f"Real-time protection {'disabled' if action == 'disable_real_time' else 'enabled'}.", action)

        # ── get_preferences ───────────────────────────────────────────────────
        elif action == "get_preferences":
            result = _run_ps("Get-MpPreference | Format-List | Out-String")
            return _ok(result, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: get_status, quick_scan, full_scan, custom_scan, "
                "update_definitions, list_exclusions, add_exclusion_path, remove_exclusion_path, "
                "add_exclusion_extension, add_exclusion_process, get_threat_history, get_quarantine, "
                "enable_real_time, disable_real_time, get_preferences",
                action)

    except Exception as e:
        return _err(str(e), action)
