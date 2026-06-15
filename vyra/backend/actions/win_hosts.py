"""
win_hosts.py — Windows hosts file management for VYRA.
Read, add, remove, block/unblock entries in C:\\Windows\\System32\\drivers\\etc\\hosts.
"""
import json
import os
import re

_HOSTS_PATH = r"C:\Windows\System32\drivers\etc\hosts"
_VYRA_TAG   = "# Added by VYRA"


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _read_hosts() -> list[str]:
    try:
        with open(_HOSTS_PATH, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    except PermissionError:
        raise PermissionError("Cannot read hosts file. Run VYRA as Administrator.")


def _write_hosts(lines: list[str]):
    try:
        with open(_HOSTS_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except PermissionError:
        raise PermissionError("Cannot write hosts file. Run VYRA as Administrator.")


def win_hosts(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action  = parameters.get("action", "").lower().strip()
    domain  = parameters.get("domain", "").strip().lower()
    ip      = parameters.get("ip", "127.0.0.1").strip()
    comment = parameters.get("comment", _VYRA_TAG).strip()

    try:
        # ── list ──────────────────────────────────────────────────────────────
        if action == "list":
            lines = _read_hosts()
            active = [l.strip() for l in lines
                      if l.strip() and not l.strip().startswith("#")]
            comments = [l.strip() for l in lines
                        if l.strip().startswith("#")]
            result = f"=== Active entries ({len(active)}) ===\n"
            result += "\n".join(active) if active else "(none)"
            if parameters.get("show_comments"):
                result += f"\n\n=== Comments ({len(comments)}) ===\n" + "\n".join(comments)
            return _ok(result, action)

        # ── add ───────────────────────────────────────────────────────────────
        elif action == "add":
            if not domain:
                return _err("'domain' is required.", action)
            if not re.match(r"^[a-zA-Z0-9._\-]+$", domain):
                return _err("Invalid domain name.", action)
            lines = _read_hosts()
            # Check if already exists
            for line in lines:
                if not line.strip().startswith("#") and domain.lower() in line.lower():
                    return _ok(f"Entry for '{domain}' already exists.", action)
            new_entry = f"{ip}\t{domain}\t{comment}\n"
            lines.append(new_entry)
            _write_hosts(lines)
            return _ok(f"Added: {ip} → {domain}", action)

        # ── remove ────────────────────────────────────────────────────────────
        elif action == "remove":
            if not domain:
                return _err("'domain' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Remove '{domain}' from hosts? Set confirmed=true.", action)
            lines = _read_hosts()
            new_lines = [l for l in lines
                         if domain.lower() not in l.lower() or l.strip().startswith("#")]
            removed = len(lines) - len(new_lines)
            if removed == 0:
                return _ok(f"No active entry for '{domain}' found.", action)
            _write_hosts(new_lines)
            return _ok(f"Removed {removed} entry/entries for '{domain}'.", action)

        # ── block_domain ──────────────────────────────────────────────────────
        elif action == "block_domain":
            if not domain:
                return _err("'domain' is required.", action)
            domains = [domain] if isinstance(domain, str) else domain
            for d in domains:
                if not re.match(r"^[a-zA-Z0-9._\-]+$", d):
                    continue
                lines = _read_hosts()
                if not any(d.lower() in l.lower() and not l.strip().startswith("#") for l in lines):
                    lines.append(f"127.0.0.1\t{d}\t# Blocked by VYRA\n")
                    lines.append(f"127.0.0.1\twww.{d}\t# Blocked by VYRA\n")
                    _write_hosts(lines)
            return _ok(f"Domain(s) blocked: {domain}", action)

        # ── unblock_domain ────────────────────────────────────────────────────
        elif action == "unblock_domain":
            if not domain:
                return _err("'domain' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Unblock '{domain}'? Set confirmed=true.", action)
            lines = _read_hosts()
            new_lines = [l for l in lines
                         if domain.lower() not in l.lower() or l.strip().startswith("# ") and "Blocked" not in l]
            # More precise: remove lines containing domain AND Blocked tag
            new_lines = [l for l in lines
                         if not (domain.lower() in l.lower() and "Blocked by VYRA" in l)]
            _write_hosts(new_lines)
            return _ok(f"Domain '{domain}' unblocked.", action)

        # ── block_list ────────────────────────────────────────────────────────
        elif action == "block_list":
            """Block a list of domains from parameters."""
            domains = parameters.get("domains", [])
            if not domains:
                return _err("'domains' list is required.", action)
            lines = _read_hosts()
            added = []
            for d in domains:
                d = d.strip().lower()
                if not re.match(r"^[a-zA-Z0-9._\-]+$", d):
                    continue
                if not any(d in l.lower() and not l.strip().startswith("#") for l in lines):
                    lines.append(f"127.0.0.1\t{d}\t# Blocked by VYRA\n")
                    added.append(d)
            _write_hosts(lines)
            return _ok(f"Blocked {len(added)} domain(s): {', '.join(added[:10])}", action)

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            if not domain:
                return _err("'domain' (search term) is required.", action)
            lines = _read_hosts()
            matches = [l.strip() for l in lines if domain.lower() in l.lower()]
            return _ok("\n".join(matches) if matches else f"No entries matching '{domain}'.", action)

        # ── flush_dns ─────────────────────────────────────────────────────────
        elif action == "flush_dns":
            import subprocess
            result = subprocess.run(["ipconfig", "/flushdns"],
                                    capture_output=True, text=True, timeout=10)
            return _ok(result.stdout.strip() or "DNS cache flushed.", action)

        # ── open_file ─────────────────────────────────────────────────────────
        elif action == "open_file":
            import subprocess as sp
            sp.Popen(["notepad", _HOSTS_PATH])
            return _ok(f"Opened hosts file in Notepad: {_HOSTS_PATH}", action)

        # ── backup ────────────────────────────────────────────────────────────
        elif action == "backup":
            import shutil, datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(os.path.expanduser("~"), "Desktop", f"hosts_backup_{ts}.txt")
            shutil.copy2(_HOSTS_PATH, dest)
            return _ok(f"Hosts file backed up to: {dest}", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list, add, remove, block_domain, "
                "unblock_domain, block_list, search, flush_dns, open_file, backup",
                action)

    except PermissionError as e:
        return _err(str(e), action)
    except Exception as e:
        return _err(str(e), action)
