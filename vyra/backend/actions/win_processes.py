"""
win_processes.py — Advanced process management for VYRA Windows control.
Uses psutil for cross-platform ops + PowerShell for Windows-specific queries.
"""
import json
import subprocess
import psutil
import os

# ── Safety: never touch these system-critical processes ──────────────────────
_PROTECTED_NAMES = frozenset({
    "system", "system idle process", "smss.exe", "csrss.exe",
    "wininit.exe", "lsass.exe", "lsm.exe", "services.exe",
    "winlogon.exe", "fontdrvhost.exe", "dwm.exe"
})
_PROTECTED_PIDS = frozenset({0, 4})

_PRIORITY_MAP = {
    "idle":         psutil.IDLE_PRIORITY_CLASS,
    "below_normal": psutil.BELOW_NORMAL_PRIORITY_CLASS,
    "normal":       psutil.NORMAL_PRIORITY_CLASS,
    "above_normal": psutil.ABOVE_NORMAL_PRIORITY_CLASS,
    "high":         psutil.HIGH_PRIORITY_CLASS,
    "realtime":     psutil.REALTIME_PRIORITY_CLASS,
}


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
        return out if out else (f"[stderr]: {err}" if err else "No output.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def _is_protected(proc: psutil.Process) -> bool:
    try:
        return proc.pid in _PROTECTED_PIDS or proc.name().lower() in _PROTECTED_NAMES
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True


def _find_processes(name: str = "", pid: int = None) -> list:
    """Return matching Process objects by name (partial, case-insensitive) or PID."""
    results = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if pid is not None and p.pid == pid:
                results.append(p)
            elif name and name.lower() in p.info["name"].lower():
                results.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return results


def win_processes(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action       = parameters.get("action", "").lower().strip()
    proc_name    = parameters.get("process_name", "").strip()
    pid_param    = parameters.get("pid")
    pid          = int(pid_param) if pid_param is not None else None
    priority     = parameters.get("priority", "normal").lower()
    cpu_mask     = parameters.get("cpu_mask")
    sort_by      = parameters.get("sort_by", "cpu").lower()  # cpu|ram|name|pid
    limit        = int(parameters.get("limit", 30))

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            procs = []
            for p in psutil.process_iter(["pid", "name", "status", "cpu_percent", "memory_info"]):
                try:
                    mi = p.info["memory_info"]
                    procs.append({
                        "pid":    p.info["pid"],
                        "name":   p.info["name"],
                        "status": p.info["status"],
                        "cpu%":   round(p.info["cpu_percent"] or 0, 1),
                        "ram_mb": round((mi.rss if mi else 0) / 1_048_576, 1),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            sort_key = {"cpu": "cpu%", "ram": "ram_mb", "name": "name", "pid": "pid"}.get(sort_by, "cpu%")
            procs.sort(key=lambda x: x[sort_key], reverse=(sort_by in ("cpu", "ram")))
            procs = procs[:limit]

            lines = [f"{'PID':>6}  {'Name':<35}  {'Status':<10}  {'CPU%':>5}  {'RAM(MB)':>8}"]
            lines.append("-" * 72)
            for p in procs:
                lines.append(
                    f"{p['pid']:>6}  {p['name']:<35}  {p['status']:<10}  "
                    f"{p['cpu%']:>5}  {p['ram_mb']:>8}")
            return _ok("\n".join(lines), action)

        # ── list_by_resource ──────────────────────────────────────────────────
        elif action == "list_by_resource":
            """Top N processes by CPU or RAM."""
            resource = parameters.get("resource", "cpu").lower()
            top_n = int(parameters.get("top_n", 10))
            procs = []
            for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    mi = p.info["memory_info"]
                    procs.append({
                        "pid":    p.info["pid"],
                        "name":   p.info["name"],
                        "cpu%":   round(p.info["cpu_percent"] or 0, 1),
                        "ram_mb": round((mi.rss if mi else 0) / 1_048_576, 1),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            key = "cpu%" if resource == "cpu" else "ram_mb"
            procs.sort(key=lambda x: x[key], reverse=True)
            lines = [f"Top {top_n} by {resource.upper()}:"]
            for i, p in enumerate(procs[:top_n], 1):
                lines.append(f"  {i:>2}. PID {p['pid']:>6} | {p['name']:<35} | CPU {p['cpu%']:>5}% | RAM {p['ram_mb']:>7} MB")
            return _ok("\n".join(lines), action)

        # ── get_detail ────────────────────────────────────────────────────────
        elif action == "get_detail":
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name'.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)
            p = matches[0]
            try:
                with p.oneshot():
                    info = {
                        "pid":        p.pid,
                        "name":       p.name(),
                        "exe":        p.exe() if hasattr(p, "exe") else "N/A",
                        "status":     p.status(),
                        "cpu%":       p.cpu_percent(interval=0.5),
                        "ram_mb":     round(p.memory_info().rss / 1_048_576, 2),
                        "threads":    p.num_threads(),
                        "priority":   p.nice(),
                        "created":    p.create_time(),
                        "username":   p.username() if hasattr(p, "username") else "N/A",
                        "cmdline":    " ".join(p.cmdline()) if hasattr(p, "cmdline") else "N/A",
                        "open_files": len(p.open_files()) if hasattr(p, "open_files") else 0,
                        "connections": len(p.connections()) if hasattr(p, "connections") else 0,
                    }
                lines = [f"{k}: {v}" for k, v in info.items()]
                return _ok("\n".join(lines), action)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                return _err(str(e), action)

        # ── kill ──────────────────────────────────────────────────────────────
        elif action == "kill":
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name'.", action)
            if not parameters.get("confirmed"):
                return _err("Killing a process is irreversible. Set confirmed=true.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)
            killed = []
            protected = []
            for p in matches:
                if _is_protected(p):
                    protected.append(p.name())
                    continue
                try:
                    p.kill()
                    killed.append(f"{p.name()} (PID {p.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    protected.append(f"{p.name()}: {e}")
            parts = []
            if killed:
                parts.append(f"Killed: {', '.join(killed)}")
            if protected:
                parts.append(f"Protected/denied: {', '.join(protected)}")
            return _ok(" | ".join(parts) if parts else "No processes affected.", action)

        # ── kill_by_name ──────────────────────────────────────────────────────
        elif action == "kill_by_name":
            if not proc_name:
                return _err("'process_name' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Kill all '{proc_name}' instances? Set confirmed=true.", action)
            return win_processes({**parameters, "action": "kill"}, response, player, session_memory)

        # ── terminate ────────────────────────────────────────────────────────
        elif action == "terminate":
            """Graceful SIGTERM instead of hard SIGKILL."""
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name'.", action)
            if not parameters.get("confirmed"):
                return _err("Set confirmed=true to terminate.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)
            terminated = []
            for p in matches:
                if _is_protected(p):
                    continue
                try:
                    p.terminate()
                    terminated.append(f"{p.name()} (PID {p.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return _ok(f"Terminated: {', '.join(terminated)}" if terminated else "No processes terminated.", action)

        # ── set_priority ─────────────────────────────────────────────────────
        elif action == "set_priority":
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name'.", action)
            if priority not in _PRIORITY_MAP:
                return _err(f"Invalid priority '{priority}'. Use: {', '.join(_PRIORITY_MAP)}", action)
            # Block realtime — can freeze system
            if priority == "realtime":
                return _err("REALTIME priority can freeze your system. Use 'high' instead.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)
            updated = []
            for p in matches[:5]:  # Safety: limit to first 5 matches
                try:
                    p.nice(_PRIORITY_MAP[priority])
                    updated.append(f"{p.name()} (PID {p.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    pass
            return _ok(f"Priority set to '{priority}' for: {', '.join(updated)}" if updated else "Could not set priority.", action)

        # ── set_affinity ─────────────────────────────────────────────────────
        elif action == "set_affinity":
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name'.", action)
            if cpu_mask is None:
                return _err("'cpu_mask' required (bitmask, e.g. 3 = CPUs 0+1).", action)
            cpu_count = psutil.cpu_count()
            cpu_list = [i for i in range(cpu_count) if (int(cpu_mask) >> i) & 1]
            if not cpu_list:
                return _err("No CPUs selected in cpu_mask.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)
            updated = []
            for p in matches[:3]:
                try:
                    p.cpu_affinity(cpu_list)
                    updated.append(f"{p.name()} (PID {p.pid}) → CPUs {cpu_list}")
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    pass
            return _ok(f"Affinity set: {'; '.join(updated)}" if updated else "Could not set affinity.", action)

        # ── suspend / resume ──────────────────────────────────────────────────
        elif action in ("suspend", "resume"):
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name'.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)
            affected = []
            for p in matches[:5]:
                if _is_protected(p):
                    continue
                try:
                    if action == "suspend":
                        p.suspend()
                    else:
                        p.resume()
                    affected.append(f"{p.name()} (PID {p.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return _ok(f"{action.title()}d: {', '.join(affected)}" if affected else f"Could not {action}.", action)

        # ── process_tree ──────────────────────────────────────────────────────
        elif action == "process_tree":
            """Show process hierarchy: parent → children."""
            if pid is None and not proc_name:
                return _err("Provide 'pid' or 'process_name' as root.", action)
            matches = _find_processes(proc_name, pid)
            if not matches:
                return _err(f"Process not found: {proc_name or pid}", action)

            def _tree(p, indent=0):
                lines = []
                try:
                    lines.append("  " * indent + f"[{p.pid}] {p.name()} ({p.status()})")
                    for child in p.children(recursive=False):
                        lines.extend(_tree(child, indent + 1))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                return lines

            all_lines = []
            for p in matches[:3]:
                all_lines.extend(_tree(p))
            return _ok("\n".join(all_lines), action)

        # ── list_connections ──────────────────────────────────────────────────
        elif action == "list_connections":
            """List all active network connections with owning process."""
            lines = [f"{'PID':>6}  {'Process':<25}  {'Local Addr':<22}  {'Remote Addr':<22}  {'Status'}"]
            lines.append("-" * 90)
            for conn in psutil.net_connections(kind="inet"):
                try:
                    pname = psutil.Process(conn.pid).name() if conn.pid else "unknown"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pname = "unknown"
                laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else "-"
                raddr = f"{conn.raddr.ip}:{conn.raddr.port}" if conn.raddr else "-"
                lines.append(
                    f"{conn.pid or 0:>6}  {pname:<25}  {laddr:<22}  {raddr:<22}  {conn.status}")
            return _ok("\n".join(lines), action)

        # ── open_task_manager ─────────────────────────────────────────────────
        elif action == "open_task_manager":
            import subprocess
            subprocess.Popen(["taskmgr"])
            return _ok("Task Manager opened.", action)

        # ── system_summary ────────────────────────────────────────────────────
        elif action == "system_summary":
            cpu = psutil.cpu_percent(interval=1)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage("/")
            proc_count = len(psutil.pids())
            lines = [
                f"CPU Usage:      {cpu}%",
                f"RAM:            {ram.percent}% used ({round(ram.used/1e9,1)} GB / {round(ram.total/1e9,1)} GB)",
                f"Disk (C:):      {disk.percent}% used ({round(disk.used/1e9,1)} GB / {round(disk.total/1e9,1)} GB)",
                f"Processes:      {proc_count} running",
                f"CPU Count:      {psutil.cpu_count()} logical, {psutil.cpu_count(logical=False)} physical",
            ]
            return _ok("\n".join(lines), action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, list_by_resource, get_detail, kill, "
                "kill_by_name, terminate, set_priority, set_affinity, suspend, resume, "
                "process_tree, list_connections, open_task_manager, system_summary",
                action)

    except Exception as e:
        return _err(str(e), action)
