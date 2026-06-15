"""
win_packages.py — Software package management for VYRA Windows control.
Primary: winget (built into Windows 11/10). Fallback: Chocolatey (choco).
"""
import json
import subprocess


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run(cmd: list, timeout: int = 120) -> tuple[str, bool]:
    """Returns (output, success)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = (r.stdout + "\n" + r.stderr).strip()
        return out, r.returncode == 0
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s.", False
    except FileNotFoundError as e:
        return f"Command not found: {e}", False
    except Exception as e:
        return str(e), False


def _has_winget() -> bool:
    out, ok = _run(["winget", "--version"])
    return ok


def _has_choco() -> bool:
    out, ok = _run(["choco", "--version"])
    return ok


def win_packages(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action  = parameters.get("action", "").lower().strip()
    package = parameters.get("package", "").strip()
    source  = parameters.get("source", "winget").lower().strip()
    version = parameters.get("version", "").strip()
    scope   = parameters.get("scope", "").strip()  # user | machine

    try:
        # ── install ───────────────────────────────────────────────────────────
        if action == "install":
            if not package:
                return _err("'package' is required.", action)

            if source == "choco":
                if not _has_choco():
                    return _err("Chocolatey not installed. Ask me to install it first.", action)
                cmd = ["choco", "install", package, "-y", "--no-progress"]
                if version:
                    cmd += ["--version", version]
                out, ok = _run(cmd, timeout=180)
                return _ok(out, action) if ok else _err(out, action)
            else:
                if not _has_winget():
                    return _err("winget not found. Ensure Windows App Installer is installed.", action)
                cmd = ["winget", "install", "--id", package,
                       "--silent", "--accept-package-agreements",
                       "--accept-source-agreements", "--disable-interactivity"]
                if version:
                    cmd += ["--version", version]
                if scope:
                    cmd += ["--scope", scope]
                out, ok = _run(cmd, timeout=180)
                return _ok(out, action)

        # ── uninstall ─────────────────────────────────────────────────────────
        elif action == "uninstall":
            if not package:
                return _err("'package' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Uninstall '{package}'? Set confirmed=true.", action)

            if source == "choco":
                cmd = ["choco", "uninstall", package, "-y", "--no-progress"]
                out, ok = _run(cmd, timeout=120)
                return _ok(out, action)
            else:
                cmd = ["winget", "uninstall", "--id", package,
                       "--silent", "--disable-interactivity"]
                out, ok = _run(cmd, timeout=120)
                return _ok(out, action)

        # ── search ────────────────────────────────────────────────────────────
        elif action == "search":
            if not package:
                return _err("'package' (search query) is required.", action)

            if source == "choco":
                cmd = ["choco", "search", package, "--no-progress", "--limit-output"]
                out, ok = _run(cmd, timeout=30)
            else:
                cmd = ["winget", "search", "--query", package,
                       "--accept-source-agreements", "--disable-interactivity"]
                out, ok = _run(cmd, timeout=30)
            return _ok(out, action)

        # ── list_installed ────────────────────────────────────────────────────
        elif action == "list_installed":
            query = package  # optional filter
            if source == "choco":
                cmd = ["choco", "list", "--local-only", "--no-progress"]
                out, ok = _run(cmd, timeout=30)
            else:
                cmd = ["winget", "list", "--accept-source-agreements", "--disable-interactivity"]
                if query:
                    cmd += ["--query", query]
                out, ok = _run(cmd, timeout=30)
            return _ok(out, action)

        # ── upgrade ───────────────────────────────────────────────────────────
        elif action == "upgrade":
            if not package:
                return _err("'package' is required.", action)
            cmd = ["winget", "upgrade", "--id", package,
                   "--silent", "--accept-package-agreements",
                   "--accept-source-agreements", "--disable-interactivity"]
            out, ok = _run(cmd, timeout=180)
            return _ok(out, action)

        # ── upgrade_all ───────────────────────────────────────────────────────
        elif action == "upgrade_all":
            if not parameters.get("confirmed"):
                return _err("Upgrade ALL installed packages? Set confirmed=true.", action)
            cmd = ["winget", "upgrade", "--all", "--silent",
                   "--accept-package-agreements", "--accept-source-agreements",
                   "--disable-interactivity"]
            out, ok = _run(cmd, timeout=600)
            return _ok(out, action)

        # ── list_upgradable ───────────────────────────────────────────────────
        elif action == "list_upgradable":
            cmd = ["winget", "upgrade", "--accept-source-agreements", "--disable-interactivity"]
            out, ok = _run(cmd, timeout=60)
            return _ok(out, action)

        # ── show_info ─────────────────────────────────────────────────────────
        elif action == "show_info":
            if not package:
                return _err("'package' is required.", action)
            cmd = ["winget", "show", "--id", package,
                   "--accept-source-agreements", "--disable-interactivity"]
            out, ok = _run(cmd, timeout=30)
            return _ok(out, action)

        # ── install_choco ─────────────────────────────────────────────────────
        elif action == "install_choco":
            """Bootstrap Chocolatey if not present."""
            if _has_choco():
                return _ok("Chocolatey is already installed.", action)
            ps_script = (
                "Set-ExecutionPolicy Bypass -Scope Process -Force; "
                "[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072; "
                "iex ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))"
            )
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script]
            out, ok = _run(cmd, timeout=120)
            return _ok(out, action)

        # ── export_list ───────────────────────────────────────────────────────
        elif action == "export_list":
            """Export installed packages to a JSON file."""
            import os
            out_path = parameters.get("output_path",
                                      os.path.join(os.path.expanduser("~"), "Desktop", "installed_packages.json"))
            cmd = ["winget", "export", "--output", out_path,
                   "--accept-source-agreements", "--disable-interactivity"]
            out, ok = _run(cmd, timeout=60)
            return _ok(f"Exported to: {out_path}\n{out}", action)

        # ── import_list ───────────────────────────────────────────────────────
        elif action == "import_list":
            """Import and install packages from a winget JSON export file."""
            import_path = parameters.get("import_path", "").strip()
            if not import_path:
                return _err("'import_path' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Install all packages from '{import_path}'? Set confirmed=true.", action)
            cmd = ["winget", "import", "--import-file", import_path,
                   "--accept-package-agreements", "--accept-source-agreements",
                   "--disable-interactivity"]
            out, ok = _run(cmd, timeout=600)
            return _ok(out, action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: install, uninstall, search, list_installed, "
                "upgrade, upgrade_all, list_upgradable, show_info, install_choco, export_list, import_list",
                action)

    except Exception as e:
        return _err(str(e), action)
