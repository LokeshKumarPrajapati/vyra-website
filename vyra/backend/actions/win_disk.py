"""
win_disk.py — Disk and partition management for VYRA Windows control.
Uses PowerShell storage cmdlets + SMART data via Get-StorageReliabilityCounter.
"""
import json
import subprocess
import os


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


def win_disk(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action       = parameters.get("action", "").lower().strip()
    disk_number  = parameters.get("disk_number")
    drive_letter = parameters.get("partition_letter", "").upper().strip(":")
    filesystem   = parameters.get("filesystem", "NTFS").upper()
    label        = parameters.get("label", "").strip()
    shrink_mb    = parameters.get("shrink_mb")

    try:
        # ── list_disks ────────────────────────────────────────────────────────
        if action == "list_disks":
            result = _run_ps(
                "Get-Disk | Select-Object Number,FriendlyName,SerialNumber,"
                "@{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}},PartitionStyle,HealthStatus,OperationalStatus | "
                "Format-Table -AutoSize | Out-String -Width 180"
            )
            return _ok(result, action)

        # ── list_partitions ───────────────────────────────────────────────────
        elif action == "list_partitions":
            disk_filter = f" -DiskNumber {disk_number}" if disk_number is not None else ""
            result = _run_ps(
                f"Get-Partition{disk_filter} | "
                "Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,"
                "@{n='SizeGB';e={[math]::Round($_.Size/1GB,2)}},IsSystem,IsBoot,IsActive | "
                "Format-Table -AutoSize | Out-String -Width 180"
            )
            return _ok(result, action)

        # ── get_disk_info ─────────────────────────────────────────────────────
        elif action == "get_disk_info":
            if disk_number is None and not drive_letter:
                return _err("'disk_number' or 'partition_letter' is required.", action)
            if drive_letter:
                script = (
                    f"$vol = Get-Volume -DriveLetter '{drive_letter}' -ErrorAction SilentlyContinue; "
                    "if ($vol) { $vol | Format-List } else { 'Volume not found.' }"
                )
            else:
                script = (
                    f"Get-Disk -Number {disk_number} | Format-List; "
                    f"Get-Partition -DiskNumber {disk_number} | Format-Table DriveLetter,PartitionNumber,Type,"
                    "@{n='SizeGB';e={[math]::Round($_.Size/1GB,2)}} | Out-String"
                )
            result = _run_ps(script)
            return _ok(result, action)

        # ── get_smart_data ────────────────────────────────────────────────────
        elif action == "get_smart_data":
            result = _run_ps(
                "Get-PhysicalDisk | Select-Object FriendlyName,MediaType,HealthStatus,"
                "OperationalStatus,@{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}} | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            # Try SMART counters (requires Storage module)
            smart = _run_ps(
                "Get-PhysicalDisk | Get-StorageReliabilityCounter | "
                "Select-Object DeviceId,PowerOnHours,ReadErrorsTotal,WriteErrorsTotal,"
                "Temperature,Wear | Format-Table -AutoSize | Out-String"
            )
            if "error" not in smart.lower() and smart.strip():
                result += "\n\nSMART Reliability:\n" + smart
            return _ok(result, action)

        # ── get_volume_info ───────────────────────────────────────────────────
        elif action == "get_volume_info":
            result = _run_ps(
                "Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,"
                "@{n='SizeGB';e={[math]::Round($_.Size/1GB,2)}},@{n='FreeGB';e={[math]::Round($_.SizeRemaining/1GB,2)}},"
                "@{n='Used%';e={[math]::Round(($_.Size-$_.SizeRemaining)/$_.Size*100,1)}},HealthStatus | "
                "Sort-Object DriveLetter | Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result, action)

        # ── check_disk ────────────────────────────────────────────────────────
        elif action == "check_disk":
            if not drive_letter:
                return _err("'partition_letter' is required.", action)
            result = _run_ps(
                f"Repair-Volume -DriveLetter '{drive_letter}' -Scan", timeout=120)
            return _ok(f"Disk check on {drive_letter}:\n{result}", action)

        # ── optimize_drive ────────────────────────────────────────────────────
        elif action == "optimize_drive":
            if not drive_letter:
                return _err("'partition_letter' is required.", action)
            result = _run_ps(
                f"Optimize-Volume -DriveLetter '{drive_letter}' -Verbose", timeout=120)
            return _ok(f"Drive {drive_letter}: optimization result:\n{result}", action)

        # ── get_temp_files_size ───────────────────────────────────────────────
        elif action == "get_temp_files_size":
            import shutil
            temp_dirs = [
                os.environ.get("TEMP", ""),
                os.environ.get("TMP", ""),
                os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Temp"),
                os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp"),
            ]
            total = 0
            file_count = 0
            for d in temp_dirs:
                if d and os.path.isdir(d):
                    for root, dirs, files in os.walk(d):
                        for f in files:
                            try:
                                total += os.path.getsize(os.path.join(root, f))
                                file_count += 1
                            except (PermissionError, OSError):
                                pass
            size_mb = round(total / 1_048_576, 1)
            return _ok(f"Temporary files: {file_count} files, {size_mb} MB across {len(temp_dirs)} temp folders.", action)

        # ── clean_temp ────────────────────────────────────────────────────────
        elif action == "clean_temp":
            if not parameters.get("confirmed"):
                return _err("Delete temporary files? Set confirmed=true.", action)
            result = _run_ps(
                "Remove-Item -Path $env:TEMP\\* -Recurse -Force -ErrorAction SilentlyContinue; "
                "Remove-Item -Path 'C:\\Windows\\Temp\\*' -Recurse -Force -ErrorAction SilentlyContinue; "
                "Write-Output 'Temp files cleaned.'"
            )
            return _ok(result, action)

        # ── format_partition ──────────────────────────────────────────────────
        elif action == "format_partition":
            if not drive_letter:
                return _err("'partition_letter' is required.", action)
            # Triple confirmation for destructive operation
            if not parameters.get("confirmed"):
                return _err(f"FORMAT drive {drive_letter}: will DESTROY ALL DATA. Set confirmed=true.", action)
            if not parameters.get("confirmed_twice"):
                return _err(f"SECOND CONFIRMATION required. Set confirmed_twice=true AND confirmed=true.", action)
            if not parameters.get("confirmed_final"):
                return _err(f"FINAL CONFIRMATION required. Set confirmed_final=true to proceed with formatting {drive_letter}.", action)
            # Safety: never format C:
            if drive_letter.upper() == "C":
                return _err("Cannot format the system drive (C:).", action)
            label_arg = f"-NewFileSystemLabel '{label.replace(chr(39), chr(39)*2)}'" if label else ""
            result = _run_ps(
                f"Format-Volume -DriveLetter '{drive_letter}' -FileSystem {filesystem} "
                f"{label_arg} -Confirm:$false",
                timeout=300)
            return _ok(f"Drive {drive_letter}: formatted as {filesystem}.\n{result}", action)

        # ── set_volume_label ──────────────────────────────────────────────────
        elif action == "set_volume_label":
            if not drive_letter or not label:
                return _err("'partition_letter' and 'label' are required.", action)
            result = _run_ps(
                f"Set-Volume -DriveLetter '{drive_letter}' -NewFileSystemLabel '{label.replace(chr(39), chr(39)*2)}'"
            )
            return _ok(f"Drive {drive_letter}: label set to '{label}'.", action)

        # ── open_disk_management ──────────────────────────────────────────────
        elif action == "open_disk_management":
            import subprocess as sp
            sp.Popen(["diskmgmt.msc"])
            return _ok("Disk Management opened.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_disks, list_partitions, get_disk_info, "
                "get_smart_data, get_volume_info, check_disk, optimize_drive, "
                "get_temp_files_size, clean_temp, format_partition, set_volume_label, open_disk_management",
                action)

    except Exception as e:
        return _err(str(e), action)
