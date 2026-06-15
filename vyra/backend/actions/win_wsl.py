"""
win_wsl.py — Windows Subsystem for Linux (WSL) management for VYRA.
List, install, start, stop distros; run commands inside WSL.
"""
import json
import subprocess


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run(cmd: list, timeout: int = 60, input_data: str = None) -> tuple[str, bool]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, input=input_data)
        out = (r.stdout + "\n" + r.stderr).strip()
        return out, r.returncode == 0
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s.", False
    except FileNotFoundError:
        return "WSL not found. Install WSL from Microsoft Store or run: wsl --install", False
    except Exception as e:
        return str(e), False


def _run_ps(script: str, timeout: int = 30) -> str:
    out, _ = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)
    return out


def win_wsl(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action  = parameters.get("action", "").lower().strip()
    distro  = parameters.get("distro", "").strip()
    command = parameters.get("command", "").strip()
    user    = parameters.get("user", "").strip()

    try:
        # ── list_distros ──────────────────────────────────────────────────────
        if action == "list_distros":
            out, ok = _run(["wsl", "--list", "--verbose"])
            return _ok(out, action)

        # ── get_status ────────────────────────────────────────────────────────
        elif action == "get_status":
            out, ok = _run(["wsl", "--status"])
            return _ok(out, action)

        # ── list_online ───────────────────────────────────────────────────────
        elif action == "list_online":
            out, ok = _run(["wsl", "--list", "--online"])
            return _ok(out, action)

        # ── install ───────────────────────────────────────────────────────────
        elif action == "install":
            if not distro:
                # Install WSL itself
                out, ok = _run(["wsl", "--install"], timeout=300)
                return _ok(out, action)
            else:
                out, ok = _run(["wsl", "--install", "-d", distro], timeout=600)
                return _ok(f"Installing {distro}:\n{out}", action)

        # ── unregister ────────────────────────────────────────────────────────
        elif action == "unregister":
            if not distro:
                return _err("'distro' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Unregister '{distro}'? This DELETES all its data. Set confirmed=true.", action)
            out, ok = _run(["wsl", "--unregister", distro])
            return _ok(f"Distro '{distro}' unregistered.\n{out}", action)

        # ── set_default ───────────────────────────────────────────────────────
        elif action == "set_default":
            if not distro:
                return _err("'distro' is required.", action)
            out, ok = _run(["wsl", "--set-default", distro])
            return _ok(f"Default distro set to '{distro}'.\n{out}", action)

        # ── set_version ───────────────────────────────────────────────────────
        elif action == "set_version":
            if not distro:
                return _err("'distro' is required.", action)
            version = int(parameters.get("version", 2))
            out, ok = _run(["wsl", "--set-version", distro, str(version)], timeout=120)
            return _ok(f"WSL version set to {version} for '{distro}'.\n{out}", action)

        # ── run_command ───────────────────────────────────────────────────────
        elif action == "run_command":
            if not command:
                return _err("'command' is required.", action)
            cmd = ["wsl"]
            if distro:
                cmd += ["-d", distro]
            if user:
                cmd += ["-u", user]
            cmd += ["--", "bash", "-c", command]
            out, ok = _run(cmd, timeout=60)
            return _ok(out, action)

        # ── run_script ────────────────────────────────────────────────────────
        elif action == "run_script":
            script_path = parameters.get("script_path", "").strip()
            if not script_path:
                return _err("'script_path' (Linux path like /home/user/script.sh) is required.", action)
            cmd = ["wsl"]
            if distro:
                cmd += ["-d", distro]
            cmd += ["--", "bash", script_path]
            out, ok = _run(cmd, timeout=120)
            return _ok(out, action)

        # ── open_terminal ─────────────────────────────────────────────────────
        elif action == "open_terminal":
            cmd = ["wsl"]
            if distro:
                cmd += ["-d", distro]
            subprocess.Popen(cmd)
            return _ok(f"WSL terminal opened{' for ' + distro if distro else ''}.", action)

        # ── shutdown ──────────────────────────────────────────────────────────
        elif action == "shutdown":
            out, ok = _run(["wsl", "--shutdown"])
            return _ok(f"All WSL distros shut down.\n{out}", action)

        # ── terminate ─────────────────────────────────────────────────────────
        elif action == "terminate":
            if not distro:
                return _err("'distro' is required to terminate a specific distro.", action)
            out, ok = _run(["wsl", "--terminate", distro])
            return _ok(f"Distro '{distro}' terminated.\n{out}", action)

        # ── import_distro ─────────────────────────────────────────────────────
        elif action == "import_distro":
            tarball  = parameters.get("tarball_path", "").strip()
            install_dir = parameters.get("install_dir", "").strip()
            if not distro or not tarball or not install_dir:
                return _err("'distro', 'tarball_path', 'install_dir' are required.", action)
            out, ok = _run(["wsl", "--import", distro, install_dir, tarball], timeout=300)
            return _ok(f"Distro imported as '{distro}'.\n{out}", action)

        # ── export_distro ─────────────────────────────────────────────────────
        elif action == "export_distro":
            if not distro:
                return _err("'distro' is required.", action)
            import os
            out_path = parameters.get("output_path",
                                      os.path.join(os.path.expanduser("~"), "Desktop", f"{distro}.tar"))
            out, ok = _run(["wsl", "--export", distro, out_path], timeout=600)
            return _ok(f"Distro '{distro}' exported to: {out_path}\n{out}", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_distros, get_status, list_online, "
                "install, unregister, set_default, set_version, run_command, run_script, "
                "open_terminal, shutdown, terminate, import_distro, export_distro",
                action)

    except Exception as e:
        return _err(str(e), action)
