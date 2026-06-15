"""
win_network.py — Complete network configuration for VYRA Windows control.
Covers adapters, WiFi, IP/DNS, routing, diagnostics, and port scanning.
"""
import json
import subprocess
import socket
import os


def _ok(output: str, action: str = "") -> str:
    return json.dumps({"status": "ok", "action": action, "output": output})


def _err(msg: str, action: str = "") -> str:
    return json.dumps({"status": "error", "action": action, "error": msg})


def _run(cmd: list, timeout: int = 20) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
        out = r.stdout.strip()
        err = r.stderr.strip()
        return out if out else (f"[stderr]: {err}" if err else "No output.")
    except subprocess.TimeoutExpired:
        return f"Timed out after {timeout}s."
    except Exception as e:
        return f"Error: {e}"


def _run_ps(script: str, timeout: int = 20) -> str:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def _run_cmd(cmd: str, timeout: int = 20) -> str:
    return _run(["cmd", "/c", cmd], timeout)


def win_network(parameters: dict, response=None, player=None, session_memory=None) -> str:
    action    = parameters.get("action", "").lower().strip()
    adapter   = parameters.get("adapter", "").strip()
    ssid      = parameters.get("ssid", "").strip()
    password  = parameters.get("password", "").strip()
    ip        = parameters.get("ip", "").strip()
    subnet    = parameters.get("subnet", "24").strip()
    gateway   = parameters.get("gateway", "").strip()
    dns1      = parameters.get("dns_primary", "").strip()
    dns2      = parameters.get("dns_secondary", "").strip()
    host      = parameters.get("host", "").strip()
    port      = parameters.get("port")
    port_range = parameters.get("port_range", "1-1024")

    try:
        # ── list_adapters ─────────────────────────────────────────────────────
        if action == "list_adapters":
            result = _run_ps(
                "Get-NetAdapter | Select-Object Name,InterfaceDescription,Status,MacAddress,"
                "LinkSpeed,@{n='IP';e={(Get-NetIPAddress -InterfaceAlias $_.Name -ErrorAction SilentlyContinue).IPAddress -join ', '}} | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result, action)

        # ── list_wifi ─────────────────────────────────────────────────────────
        elif action == "list_wifi":
            result = _run_cmd("netsh wlan show networks mode=Bssid")
            return _ok(result, action)

        # ── get_wifi_status ───────────────────────────────────────────────────
        elif action == "get_wifi_status":
            result = _run_cmd("netsh wlan show interfaces")
            return _ok(result, action)

        # ── connect_wifi ──────────────────────────────────────────────────────
        elif action == "connect_wifi":
            if not ssid:
                return _err("'ssid' is required.", action)
            # Try connecting to saved profile first
            result = _run_cmd(f'netsh wlan connect name="{ssid}"')
            if "error" in result.lower() and password:
                # Create a new profile
                profile_xml = f"""<?xml version="1.0"?>
<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">
    <name>{ssid}</name>
    <SSIDConfig><SSID><name>{ssid}</name></SSID></SSIDConfig>
    <connectionType>ESS</connectionType>
    <connectionMode>auto</connectionMode>
    <MSM><security>
        <authEncryption><authentication>WPA2PSK</authentication><encryption>AES</encryption><useOneX>false</useOneX></authEncryption>
        <sharedKey><keyType>passPhrase</keyType><protected>false</protected><keyMaterial>{password}</keyMaterial></sharedKey>
    </security></MSM>
</WLANProfile>"""
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".xml", delete=False, encoding="utf-8") as f:
                    f.write(profile_xml)
                    tmp = f.name
                try:
                    _run_cmd(f'netsh wlan add profile filename="{tmp}"')
                    result = _run_cmd(f'netsh wlan connect name="{ssid}"')
                finally:
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            return _ok(result, action)

        # ── disconnect_wifi ───────────────────────────────────────────────────
        elif action == "disconnect_wifi":
            result = _run_cmd("netsh wlan disconnect")
            return _ok(result, action)

        # ── forget_wifi ───────────────────────────────────────────────────────
        elif action == "forget_wifi":
            if not ssid:
                return _err("'ssid' is required.", action)
            result = _run_cmd(f'netsh wlan delete profile name="{ssid}"')
            return _ok(result, action)

        # ── get_saved_wifi ────────────────────────────────────────────────────
        elif action == "get_saved_wifi":
            result = _run_cmd("netsh wlan show profiles")
            return _ok(result, action)

        # ── get_wifi_password ─────────────────────────────────────────────────
        elif action == "get_wifi_password":
            if not ssid:
                return _err("'ssid' is required.", action)
            result = _run_cmd(f'netsh wlan show profile name="{ssid}" key=clear')
            return _ok(result, action)

        # ── set_ip ────────────────────────────────────────────────────────────
        elif action == "set_ip":
            if not adapter or not ip or not gateway:
                return _err("'adapter', 'ip', and 'gateway' are required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Setting static IP on '{adapter}'. Set confirmed=true.", action)
            safe_adapter = adapter.replace("'", "''")
            prefix = subnet if subnet.isdigit() else "24"
            script = (
                f"$a = Get-NetAdapter -Name '{safe_adapter}' -ErrorAction SilentlyContinue; "
                "if (-not $a) { 'Adapter not found.'; exit }; "
                f"Remove-NetIPAddress -InterfaceAlias '{safe_adapter}' -Confirm:$false -ErrorAction SilentlyContinue; "
                f"Remove-NetRoute -InterfaceAlias '{safe_adapter}' -Confirm:$false -ErrorAction SilentlyContinue; "
                f"New-NetIPAddress -InterfaceAlias '{safe_adapter}' -IPAddress '{ip}' "
                f"-PrefixLength {prefix} -DefaultGateway '{gateway}'"
            )
            result = _run_ps(script, timeout=30)
            return _ok(f"Static IP set: {ip}/{prefix} gw {gateway}\n{result}", action)

        # ── set_dhcp ──────────────────────────────────────────────────────────
        elif action == "set_dhcp":
            if not adapter:
                return _err("'adapter' is required.", action)
            if not parameters.get("confirmed"):
                return _err(f"Switch '{adapter}' to DHCP? Set confirmed=true.", action)
            safe_adapter = adapter.replace("'", "''")
            result = _run_ps(
                f"Set-NetIPInterface -InterfaceAlias '{safe_adapter}' -Dhcp Enabled; "
                f"Set-DnsClientServerAddress -InterfaceAlias '{safe_adapter}' -ResetServerAddresses"
            )
            return _ok(f"'{adapter}' switched to DHCP.", action)

        # ── set_dns ───────────────────────────────────────────────────────────
        elif action == "set_dns":
            if not adapter or not dns1:
                return _err("'adapter' and 'dns_primary' are required.", action)
            safe_adapter = adapter.replace("'", "''")
            dns_list = f"'{dns1}'" + (f", '{dns2}'" if dns2 else "")
            result = _run_ps(
                f"Set-DnsClientServerAddress -InterfaceAlias '{safe_adapter}' -ServerAddresses @({dns_list})"
            )
            return _ok(f"DNS set on '{adapter}': {dns1}{', '+dns2 if dns2 else ''}", action)

        # ── flush_dns ─────────────────────────────────────────────────────────
        elif action == "flush_dns":
            result = _run_cmd("ipconfig /flushdns")
            return _ok(result, action)

        # ── enable_adapter / disable_adapter ──────────────────────────────────
        elif action in ("enable_adapter", "disable_adapter"):
            if not adapter:
                return _err("'adapter' is required.", action)
            if action == "disable_adapter" and not parameters.get("confirmed"):
                return _err(f"Disable adapter '{adapter}'? Set confirmed=true.", action)
            safe_adapter = adapter.replace("'", "''")
            cmd = "Enable" if action == "enable_adapter" else "Disable"
            result = _run_ps(f"{cmd}-NetAdapter -Name '{safe_adapter}' -Confirm:$false")
            return _ok(f"Adapter '{adapter}' {cmd.lower()}d.", action)

        # ── get_ip_info ───────────────────────────────────────────────────────
        elif action == "get_ip_info":
            result = _run_cmd("ipconfig /all")
            return _ok(result, action)

        # ── get_public_ip ─────────────────────────────────────────────────────
        elif action == "get_public_ip":
            result = _run_ps("(Invoke-RestMethod -Uri 'https://api.ipify.org?format=json').ip")
            return _ok(f"Public IP: {result}", action)

        # ── ping ──────────────────────────────────────────────────────────────
        elif action == "ping":
            if not host:
                return _err("'host' is required.", action)
            count = int(parameters.get("count", 4))
            result = _run_cmd(f"ping -n {count} {host}", timeout=30)
            return _ok(result, action)

        # ── traceroute ────────────────────────────────────────────────────────
        elif action == "traceroute":
            if not host:
                return _err("'host' is required.", action)
            result = _run_ps(f"Test-NetConnection -TraceRoute -ComputerName '{host}' | Format-List", timeout=60)
            return _ok(result, action)

        # ── check_connectivity ────────────────────────────────────────────────
        elif action == "check_connectivity":
            target = host or "8.8.8.8"
            p = int(port) if port else 53
            result = _run_ps(
                f"$r = Test-NetConnection -ComputerName '{target}' -Port {p}; "
                "$r | Select-Object ComputerName,RemoteAddress,RemotePort,PingSucceeded,TcpTestSucceeded | Format-List"
            )
            return _ok(result, action)

        # ── scan_ports ────────────────────────────────────────────────────────
        elif action == "scan_ports":
            if not host:
                return _err("'host' is required.", action)
            # Parse port_range: "80", "80-443", "22,80,443"
            ports_to_scan = []
            if port:
                ports_to_scan = [int(port)]
            elif "," in str(port_range):
                ports_to_scan = [int(p.strip()) for p in str(port_range).split(",")]
            elif "-" in str(port_range):
                start, end = str(port_range).split("-")
                ports_to_scan = list(range(int(start), min(int(end) + 1, int(start) + 200)))
            else:
                ports_to_scan = [int(port_range)]

            open_ports = []
            for p_num in ports_to_scan[:200]:  # Cap at 200
                try:
                    with socket.create_connection((host, p_num), timeout=0.5):
                        open_ports.append(str(p_num))
                except (socket.timeout, ConnectionRefusedError, OSError):
                    pass

            if open_ports:
                return _ok(f"Open ports on {host}: {', '.join(open_ports)}", action)
            return _ok(f"No open ports found on {host} in range {port_range}.", action)

        # ── list_connections ──────────────────────────────────────────────────
        elif action == "list_connections":
            result = _run_ps(
                "Get-NetTCPConnection | Where-Object {$_.State -ne 'Listen'} | "
                "Select-Object LocalAddress,LocalPort,RemoteAddress,RemotePort,State,"
                "@{n='Process';e={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).Name}} | "
                "Format-Table -AutoSize | Out-String -Width 160"
            )
            return _ok(result, action)

        # ── get_route_table ───────────────────────────────────────────────────
        elif action == "get_route_table":
            result = _run_cmd("route print")
            return _ok(result, action)

        # ── reset_network ─────────────────────────────────────────────────────
        elif action == "reset_network":
            if not parameters.get("confirmed"):
                return _err("Full network stack reset. Set confirmed=true.", action)
            cmds = [
                "netsh winsock reset", "netsh int ip reset",
                "ipconfig /release", "ipconfig /flushdns", "ipconfig /renew"
            ]
            results = []
            for cmd in cmds:
                results.append(f"[{cmd}]: " + _run_cmd(cmd))
            return _ok("\n".join(results), action)

        # ── enable_sharing ────────────────────────────────────────────────────
        elif action == "enable_sharing":
            """Enable network discovery and file sharing."""
            result = _run_ps(
                "Set-NetFirewallRule -DisplayGroup 'Network Discovery' -Enabled True; "
                "Set-NetFirewallRule -DisplayGroup 'File and Printer Sharing' -Enabled True"
            )
            return _ok("Network discovery and file sharing enabled.", action)

        else:
            return _err(
                f"Unknown action: '{action}'. Use: list_adapters, list_wifi, get_wifi_status, "
                "connect_wifi, disconnect_wifi, forget_wifi, get_saved_wifi, get_wifi_password, "
                "set_ip, set_dhcp, set_dns, flush_dns, enable_adapter, disable_adapter, "
                "get_ip_info, get_public_ip, ping, traceroute, check_connectivity, "
                "scan_ports, list_connections, get_route_table, reset_network, enable_sharing",
                action)

    except Exception as e:
        return _err(str(e), action)
