"""
win_firewall.py — Windows Firewall management for VYRA.
Uses PowerShell NetFirewallRule cmdlets.
"""
import json
import subprocess


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
        return out if out else (f"[stderr]: {err}" if err else "Done.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def win_firewall(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action     = parameters.get("action", "").lower().strip()
    rule_name  = parameters.get("rule_name", "").strip()
    direction  = parameters.get("direction", "inbound").capitalize()
    protocol   = parameters.get("protocol", "TCP")
    local_port = str(parameters.get("local_port", "")).strip()
    remote_port = str(parameters.get("remote_port", "")).strip()
    app_path   = parameters.get("app_path", "").strip()
    fw_action  = parameters.get("fw_action", "Allow").capitalize()
    profile    = parameters.get("profile", "Any")
    remote_ip  = parameters.get("remote_ip", "Any").strip()
    enabled    = parameters.get("enabled", True)

    try:
        # ── get_status ────────────────────────────────────────────────────────
        if action == "get_status":
            result = _run_ps(
                "Get-NetFirewallProfile | Select-Object Name,Enabled,DefaultInboundAction,DefaultOutboundAction | "
                "Format-Table -AutoSize | Out-String -Width 120"
            )
            return _ok(result, action)

        # ── list_rules ────────────────────────────────────────────────────────
        elif action == "list_rules":
            filter_enabled = parameters.get("filter_enabled")
            filter_dir = parameters.get("filter_direction", "").capitalize()
            wheres = []
            if filter_enabled is not None:
                wheres.append(f"$_.Enabled -eq '{str(filter_enabled).capitalize()}'")
            if filter_dir in ("Inbound", "Outbound"):
                wheres.append(f"$_.Direction -eq '{filter_dir}'")
            rule_filter = parameters.get("rule_filter", "").strip()
            if rule_filter:
                safe = rule_filter.replace("'", "''")
                wheres.append(f"$_.DisplayName -like '*{safe}*'")

            where_str = " -and ".join(wheres)
            pipe = f" | Where-Object {{{where_str}}}" if where_str else ""
            script = (
                f"Get-NetFirewallRule{pipe} | "
                "Select-Object DisplayName,Direction,Action,Profile,Enabled | "
                "Sort-Object Direction,DisplayName | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            result = _run_ps(script, timeout=30)
            return _ok(result, action)

        # ── get_rule ──────────────────────────────────────────────────────────
        elif action == "get_rule":
            if not rule_name:
                return _err("'rule_name' is required.", action)
            safe = rule_name.replace("'", "''")
            script = (
                f"$r = Get-NetFirewallRule -DisplayName '{safe}' -ErrorAction SilentlyContinue; "
                "if ($r) { $r | Get-NetFirewallPortFilter | Format-List; $r | Format-List } "
                "else { 'Rule not found.' }"
            )
            result = _run_ps(script)
            return _ok(result, action)

        # ── add_rule ──────────────────────────────────────────────────────────
        elif action == "add_rule":
            if not rule_name:
                return _err("'rule_name' is required.", action)
            safe_name = rule_name.replace("'", "''")
            parts = [
                f"New-NetFirewallRule -DisplayName '{safe_name}'",
                f"-Direction {direction}",
                f"-Action {fw_action}",
                f"-Protocol {protocol}",
                f"-Profile {profile}",
                f"-Enabled {str(enabled).capitalize()}",
            ]
            if local_port:
                parts.append(f"-LocalPort {local_port}")
            if remote_port:
                parts.append(f"-RemotePort {remote_port}")
            if remote_ip != "Any":
                parts.append(f"-RemoteAddress '{remote_ip}'")
            if app_path:
                safe_app = app_path.replace("'", "''")
                parts.append(f"-Program '{safe_app}'")
            result = _run_ps(" ".join(parts), timeout=30)
            return _ok(f"Rule '{rule_name}' added.\n{result}", action)

        # ── remove_rule ───────────────────────────────────────────────────────
        elif action == "remove_rule":
            if not rule_name:
                return _err("'rule_name' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Delete firewall rule '{rule_name}'? Set confirmed=true.", action)
            safe = rule_name.replace("'", "''")
            result = _run_ps(f"Remove-NetFirewallRule -DisplayName '{safe}'")
            return _ok(f"Rule '{rule_name}' removed.", action)

        # ── enable_rule / disable_rule ────────────────────────────────────────
        elif action in ("enable_rule", "disable_rule"):
            if not rule_name:
                return _err("'rule_name' is required.", action)
            safe = rule_name.replace("'", "''")
            state = "True" if action == "enable_rule" else "False"
            result = _run_ps(f"Set-NetFirewallRule -DisplayName '{safe}' -Enabled {state}")
            return _ok(f"Rule '{rule_name}' {'enabled' if action == 'enable_rule' else 'disabled'}.", action)

        # ── block_app ─────────────────────────────────────────────────────────
        elif action == "block_app":
            if not app_path:
                return _err("'app_path' is required.", action)
            import os
            auto_name = rule_name or f"VYRA_Block_{os.path.basename(app_path)}"
            safe_name = auto_name.replace("'", "''")
            safe_app  = app_path.replace("'", "''")
            # Block both inbound and outbound
            for dirn in ("Inbound", "Outbound"):
                _run_ps(
                    f"New-NetFirewallRule -DisplayName '{safe_name}_{dirn}' "
                    f"-Direction {dirn} -Program '{safe_app}' -Action Block -Profile Any -Enabled True",
                    timeout=20)
            return _ok(f"Blocked all traffic for: {app_path}", action)

        # ── allow_app ─────────────────────────────────────────────────────────
        elif action == "allow_app":
            if not app_path:
                return _err("'app_path' is required.", action)
            import os
            auto_name = rule_name or f"VYRA_Allow_{os.path.basename(app_path)}"
            safe_name = auto_name.replace("'", "''")
            safe_app  = app_path.replace("'", "''")
            for dirn in ("Inbound", "Outbound"):
                _run_ps(
                    f"New-NetFirewallRule -DisplayName '{safe_name}_{dirn}' "
                    f"-Direction {dirn} -Program '{safe_app}' -Action Allow -Profile Any -Enabled True",
                    timeout=20)
            return _ok(f"Allowed all traffic for: {app_path}", action)

        # ── block_port ────────────────────────────────────────────────────────
        elif action == "block_port":
            if not local_port:
                return _err("'local_port' is required.", action)
            auto_name = rule_name or f"VYRA_Block_Port_{local_port}"
            safe_name = auto_name.replace("'", "''")
            result = _run_ps(
                f"New-NetFirewallRule -DisplayName '{safe_name}' "
                f"-Direction Inbound -LocalPort {local_port} -Protocol {protocol} "
                f"-Action Block -Profile Any -Enabled True"
            )
            return _ok(f"Port {local_port}/{protocol} blocked (inbound).", action)

        # ── enable_firewall / disable_firewall ────────────────────────────────
        elif action in ("enable_firewall", "disable_firewall"):
            if action == "disable_firewall" and not parameters.get("confirmed"):
                return _err("Disabling Windows Firewall is a security risk. Set confirmed=true.", action)
            state = "True" if action == "enable_firewall" else "False"
            result = _run_ps(f"Set-NetFirewallProfile -Profile Domain,Public,Private -Enabled {state}")
            return _ok(f"Firewall {'enabled' if action == 'enable_firewall' else 'DISABLED'}.", action)

        # ── export_rules ──────────────────────────────────────────────────────
        elif action == "export_rules":
            import os
            out_path = parameters.get("output_path",
                                      os.path.join(os.path.expanduser("~"), "Desktop", "firewall_rules.wfw"))
            result = _run_ps(f"netsh advfirewall export '{out_path}'", timeout=30)
            return _ok(f"Rules exported to: {out_path}\n{result}", action)

        # ── reset_rules ───────────────────────────────────────────────────────
        elif action == "reset_rules":
            if not parameters.get("confirmed"):
                return _err("Reset ALL firewall rules to defaults? Set confirmed=true.", action)
            result = _run_ps("netsh advfirewall reset")
            return _ok(f"Firewall rules reset to default.\n{result}", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: get_status, list_rules, get_rule, add_rule, "
                "remove_rule, enable_rule, disable_rule, block_app, allow_app, block_port, "
                "enable_firewall, disable_firewall, export_rules, reset_rules",
                action)

    except Exception as e:
        return _err(str(e), action)
