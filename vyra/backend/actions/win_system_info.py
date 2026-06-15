"""
win_system_info.py — Deep hardware & system information for VYRA.
CPU temps, GPU, RAM slots, BIOS, motherboard, battery, NIC, USB via WMI + PowerShell.
"""
import json
import subprocess
import platform
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
        return out if out else (f"[stderr]: {err}" if err else "No output.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def win_system_info(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action = parameters.get("action", "").lower().strip()

    try:
        # ── full_summary ──────────────────────────────────────────────────────
        if action == "full_summary":
            import psutil
            cpu_count = psutil.cpu_count()
            cpu_freq  = psutil.cpu_freq()
            ram       = psutil.virtual_memory()
            boot_time = psutil.boot_time()
            import datetime
            uptime_sec = (datetime.datetime.now().timestamp() - boot_time)
            uptime_h, uptime_m = divmod(int(uptime_sec // 60), 60)

            # Windows version via registry
            win_ver = _run_ps(
                "(Get-ItemProperty 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion' "
                "| Select-Object ProductName,DisplayVersion,CurrentBuildNumber,UBR) | Format-List | Out-String"
            )

            lines = [
                "=== VYRA System Summary ===",
                f"OS:        {platform.system()} {platform.release()} {platform.version()}",
                f"Machine:   {platform.machine()}",
                f"Hostname:  {platform.node()}",
                f"CPU Cores: {cpu_count} logical, {psutil.cpu_count(logical=False)} physical",
                f"CPU Freq:  {round(cpu_freq.current, 0)} MHz (max {round(cpu_freq.max, 0)} MHz)" if cpu_freq else "",
                f"RAM:       {round(ram.total / 1e9, 1)} GB total, {round(ram.available / 1e9, 1)} GB free",
                f"RAM Used:  {ram.percent}%",
                f"Uptime:    {uptime_h}h {uptime_m}m",
                "",
                "Windows Version Details:",
                win_ver,
            ]
            return _ok("\n".join(l for l in lines if l is not None), action)

        # ── cpu_info ──────────────────────────────────────────────────────────
        elif action == "cpu_info":
            import psutil
            result = _run_ps(
                "Get-WmiObject Win32_Processor | Select-Object Name,Manufacturer,MaxClockSpeed,"
                "NumberOfCores,NumberOfLogicalProcessors,L2CacheSize,L3CacheSize,"
                "ProcessorId,SocketDesignation | Format-List | Out-String"
            )
            cpu_usage = psutil.cpu_percent(interval=1, percpu=True)
            per_core = "  ".join(f"Core{i}: {p}%" for i, p in enumerate(cpu_usage))
            return _ok(f"{result}\nPer-core usage:\n{per_core}", action)

        # ── gpu_info ──────────────────────────────────────────────────────────
        elif action == "gpu_info":
            result = _run_ps(
                "Get-WmiObject Win32_VideoController | Select-Object Name,AdapterRAM,"
                "CurrentHorizontalResolution,CurrentVerticalResolution,CurrentRefreshRate,"
                "DriverVersion,VideoProcessor,VideoModeDescription | Format-List | Out-String"
            )
            return _ok(result, action)

        # ── ram_info ──────────────────────────────────────────────────────────
        elif action == "ram_info":
            result = _run_ps(
                "Get-WmiObject Win32_PhysicalMemory | "
                "Select-Object BankLabel,DeviceLocator,@{n='SizeGB';e={[math]::Round($_.Capacity/1GB,1)}},"
                "Speed,Manufacturer,PartNumber,MemoryType | Format-Table -AutoSize | Out-String -Width 160"
            )
            total = _run_ps("(Get-WmiObject Win32_ComputerSystem).TotalPhysicalMemory / 1GB")
            return _ok(f"Total RAM: {total} GB\n{result}", action)

        # ── motherboard_info ──────────────────────────────────────────────────
        elif action == "motherboard_info":
            result = _run_ps(
                "Get-WmiObject Win32_BaseBoard | Select-Object Manufacturer,Product,SerialNumber,Version | Format-List; "
                "Get-WmiObject Win32_ComputerSystem | Select-Object Manufacturer,Model,SystemType | Format-List"
            )
            return _ok(result, action)

        # ── bios_info ─────────────────────────────────────────────────────────
        elif action == "bios_info":
            result = _run_ps(
                "Get-WmiObject Win32_BIOS | "
                "Select-Object Manufacturer,Name,Version,ReleaseDate,SMBIOSBIOSVersion | "
                "Format-List | Out-String"
            )
            return _ok(result, action)

        # ── temperature ───────────────────────────────────────────────────────
        elif action == "temperature":
            # Try OpenHardwareMonitor WMI (if installed)
            result = _run_ps(
                "$sensors = Get-WmiObject -Namespace root/OpenHardwareMonitor -Class Sensor "
                "-ErrorAction SilentlyContinue | Where-Object {$_.SensorType -eq 'Temperature'}; "
                "if ($sensors) { $sensors | Select-Object Name,Parent,Value | Format-Table | Out-String } "
                "else { 'OpenHardwareMonitor not running. Install it for temperature data.' }"
            )
            # Fallback: MSAcpi_ThermalZoneTemperature
            if "not running" in result or not result.strip():
                result = _run_ps(
                    "Get-WmiObject -Namespace root/WMI -Class MSAcpi_ThermalZoneTemperature "
                    "-ErrorAction SilentlyContinue | "
                    "Select-Object InstanceName,@{n='TempC';e={[math]::Round($_.CurrentTemperature/10 - 273.15, 1)}} | "
                    "Format-Table -AutoSize | Out-String"
                )
            return _ok(result if result.strip() else "Temperature sensors not accessible. Install OpenHardwareMonitor or HWiNFO.", action)

        # ── network_adapters ──────────────────────────────────────────────────
        elif action == "network_adapters":
            result = _run_ps(
                "Get-WmiObject Win32_NetworkAdapter | Where-Object {$_.NetEnabled -ne $null} | "
                "Select-Object Name,MACAddress,NetEnabled,Speed,Manufacturer | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result, action)

        # ── usb_devices ───────────────────────────────────────────────────────
        elif action == "usb_devices":
            result = _run_ps(
                "Get-WmiObject Win32_PnPEntity | Where-Object {$_.DeviceID -like 'USB*'} | "
                "Select-Object Name,DeviceID,Status | Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result, action)

        # ── storage_devices ───────────────────────────────────────────────────
        elif action == "storage_devices":
            result = _run_ps(
                "Get-WmiObject Win32_DiskDrive | "
                "Select-Object Model,Manufacturer,MediaType,@{n='SizeGB';e={[math]::Round($_.Size/1GB,1)}},InterfaceType,Status | "
                "Format-Table -AutoSize | Out-String"
            )
            return _ok(result, action)

        # ── installed_software ────────────────────────────────────────────────
        elif action == "installed_software":
            query = parameters.get("filter", "").strip()
            where = f" | Where-Object {{$_.DisplayName -like '*{query.replace(chr(39), chr(39)*2)}*'}}" if query else ""
            result = _run_ps(
                f"Get-ItemProperty HKLM:\\Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\* "
                f"{where} | Select-Object DisplayName,DisplayVersion,Publisher,InstallDate | "
                "Sort-Object DisplayName | Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result, action)

        # ── benchmark_quick ───────────────────────────────────────────────────
        elif action == "benchmark_quick":
            import psutil, time
            # CPU benchmark: count to N
            start = time.perf_counter()
            count = 0
            while time.perf_counter() - start < 1.0:
                count += 1
            cpu_score = count // 1000

            ram = psutil.virtual_memory()
            disk_usage = psutil.disk_usage("C:\\") if os.path.exists("C:\\") else None

            lines = [
                "=== Quick System Benchmark ===",
                f"CPU Score:    ~{cpu_score:,} (arbitrary unit, 1-second loop)",
                f"CPU Usage:    {psutil.cpu_percent(interval=0.5)}%",
                f"RAM Total:    {round(ram.total/1e9, 1)} GB",
                f"RAM Free:     {round(ram.available/1e9, 1)} GB ({100-ram.percent:.0f}% free)",
            ]
            if disk_usage:
                lines.append(f"Disk C: Free: {round(disk_usage.free/1e9, 1)} GB / {round(disk_usage.total/1e9, 1)} GB")
            return _ok("\n".join(lines), action)

        # ── open_device_manager ───────────────────────────────────────────────
        elif action == "open_device_manager":
            import subprocess as sp
            sp.Popen(["devmgmt.msc"])
            return _ok("Device Manager opened.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: full_summary, cpu_info, gpu_info, ram_info, "
                "motherboard_info, bios_info, temperature, network_adapters, usb_devices, "
                "storage_devices, installed_software, benchmark_quick, open_device_manager",
                action)

    except Exception as e:
        return _err(str(e), action)
