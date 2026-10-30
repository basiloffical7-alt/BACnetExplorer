"""
Read and change the IPv4 settings (IP, subnet mask, gateway, DNS) of this computer's
network adapters.

Windows: reads with PowerShell (Get-NetIPConfiguration, locale independent) and writes
with `netsh`, elevated through a UAC prompt when the program is not run as administrator.
Linux: uses NetworkManager (`nmcli`) through `pkexec`. Other systems: commands are shown
so the user can run them manually.
"""
from __future__ import annotations

import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

IS_WINDOWS = sys.platform.startswith("win")
_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0  # CREATE_NO_WINDOW


@dataclass
class AdapterConfig:
    name: str
    index: int = 0
    status: str = ""
    description: str = ""
    mac: str = ""
    dhcp: bool = False
    ip: str = ""
    mask: str = ""
    gateway: str = ""
    dns: List[str] = field(default_factory=list)

    def __str__(self):
        st = f" [{self.status}]" if self.status else ""
        return f"{self.name}{st}"


# ------------------------------------------------------------------ helpers
def prefix_to_mask(prefix: int) -> str:
    return str(ipaddress.IPv4Network(f"0.0.0.0/{int(prefix)}").netmask)


def mask_to_prefix(mask: str) -> int:
    return ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen


def validate(ip: str, mask: str, gateway: str, dns: List[str]) -> List[str]:
    """Raise ValueError on invalid input; return a list of warnings."""
    warnings: List[str] = []
    try:
        addr = ipaddress.IPv4Address(ip.strip())
    except ValueError:
        raise ValueError(f"'{ip}' is not a valid IPv4 address")
    try:
        net = ipaddress.IPv4Network(f"{ip.strip()}/{mask.strip()}", strict=False)
    except ValueError:
        raise ValueError(f"'{mask}' is not a valid subnet mask")
    if net.prefixlen < 31 and addr in (net.network_address, net.broadcast_address):
        raise ValueError(f"{ip} is the network or broadcast address of {net}")
    if addr.is_loopback or addr.is_multicast or addr.is_unspecified:
        raise ValueError(f"{ip} cannot be assigned to an adapter")
    if gateway.strip():
        try:
            gw = ipaddress.IPv4Address(gateway.strip())
        except ValueError:
            raise ValueError(f"'{gateway}' is not a valid gateway address")
        if gw not in net:
            warnings.append(f"Gateway {gw} is outside the subnet {net}.")
        if gw == addr:
            raise ValueError("Gateway cannot be the same as the IP address")
    for d in dns:
        try:
            ipaddress.IPv4Address(d.strip())
        except ValueError:
            raise ValueError(f"'{d}' is not a valid DNS server address")
    return warnings


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0  # type: ignore[attr-defined]


# ------------------------------------------------------------------ reading
_PS_READ = r"""
$ErrorActionPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$out = @()
foreach ($a in Get-NetAdapter) {
  $cfg = Get-NetIPConfiguration -InterfaceIndex $a.ifIndex
  $ip4 = $cfg.IPv4Address | Select-Object -First 1
  if (-not $ip4) {  # disconnected adapters: show the configured (persistent) address
    $ip4 = Get-NetIPAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4 -PolicyStore PersistentStore | Select-Object -First 1
  }
  $if  = Get-NetIPInterface -InterfaceIndex $a.ifIndex -AddressFamily IPv4
  $dns = (Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4).ServerAddresses
  $out += [pscustomobject]@{
    Name = $a.Name; Index = $a.ifIndex; Status = [string]$a.Status
    Description = $a.InterfaceDescription; Mac = $a.MacAddress
    Dhcp = [string]$if.Dhcp; IP = $ip4.IPAddress; Prefix = $ip4.PrefixLength
    Gateway = ($cfg.IPv4DefaultGateway | Select-Object -First 1).NextHop
    Dns = @($dns)
  }
}
ConvertTo-Json -InputObject @($out) -Depth 3
"""


def parse_powershell_json(text: str) -> List[AdapterConfig]:
    data = json.loads(text) if text.strip() else []
    if isinstance(data, dict):
        data = [data]
    result = []
    for d in data:
        prefix = d.get("Prefix")
        dns = d.get("Dns") or []
        if isinstance(dns, str):
            dns = [dns]
        result.append(AdapterConfig(
            name=d.get("Name") or "", index=int(d.get("Index") or 0),
            status=d.get("Status") or "", description=d.get("Description") or "",
            mac=d.get("Mac") or "", dhcp=str(d.get("Dhcp", "")).lower() in ("enabled", "1", "true"),
            ip=d.get("IP") or "", mask=prefix_to_mask(prefix) if prefix not in (None, "") else "",
            gateway=d.get("Gateway") or "", dns=[x for x in dns if x]))
    result.sort(key=lambda a: (a.status.lower() != "up", a.name.lower()))
    return result


def list_adapters() -> List[AdapterConfig]:
    if IS_WINDOWS:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                                "-ExecutionPolicy", "Bypass", "-Command", _PS_READ],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=30, creationflags=_NO_WINDOW)
            adapters = parse_powershell_json(r.stdout)
            if adapters:
                return adapters
        except Exception:
            pass
    return _list_adapters_psutil()


def _list_adapters_psutil() -> List[AdapterConfig]:
    out: List[AdapterConfig] = []
    try:
        import psutil
        import socket
        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            a = AdapterConfig(name, status="Up" if stats.get(name) and stats[name].isup else "Down")
            for x in addrs:
                if x.family == socket.AF_INET and not a.ip:
                    a.ip, a.mask = x.address, x.netmask or ""
                elif getattr(psutil, "AF_LINK", None) == x.family:
                    a.mac = x.address
            if a.ip.startswith("127."):
                continue
            out.append(a)
    except Exception:
        pass
    if not out and not IS_WINDOWS and shutil.which("ip"):
        try:
            r = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, timeout=5)
            for d in json.loads(r.stdout):
                if d.get("ifname") == "lo":
                    continue
                a = AdapterConfig(d.get("ifname", ""), status=d.get("operstate", ""))
                for ai in d.get("addr_info", []):
                    a.ip, a.mask = ai.get("local", ""), prefix_to_mask(ai.get("prefixlen", 24))
                    break
                out.append(a)
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ writing
def _q(name: str) -> str:
    return '"' + name.replace('"', '') + '"'


def build_windows_commands(name: str, dhcp: bool, ip: str = "", mask: str = "", gateway: str = "",
                           dns: Optional[List[str]] = None, dns_auto: bool = True,
                           index: int = 0) -> List[str]:
    """netsh commands. The interface INDEX is used when known: it avoids problems with
    adapter names containing spaces or non-English characters."""
    n = str(index) if index else _q(name)
    cmds: List[str] = []
    if dhcp:
        cmds.append(f"netsh interface ipv4 set address name={n} source=dhcp")
    else:
        gw = gateway.strip() or "none"
        cmds.append(f"netsh interface ipv4 set address name={n} source=static "
                    f"address={ip.strip()} mask={mask.strip()} gateway={gw}")
    dns = [d.strip() for d in (dns or []) if d.strip()]
    if dns_auto and dhcp:
        cmds.append(f"netsh interface ipv4 set dnsservers name={n} source=dhcp")
    elif dns:
        cmds.append(f"netsh interface ipv4 set dnsservers name={n} source=static "
                    f"address={dns[0]} register=primary validate=no")
        for k, d in enumerate(dns[1:], start=2):
            cmds.append(f"netsh interface ipv4 add dnsservers name={n} address={d} index={k} validate=no")
    elif not dhcp:
        cmds.append(f"netsh interface ipv4 set dnsservers name={n} source=static address=none")
    return cmds


def _ps_str(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def build_windows_script(index: int, dhcp: bool, ip: str, mask: str, gateway: str,
                         dns: List[str], log_path: str) -> str:
    """PowerShell script run elevated: netsh first, verify, fall back to the NetTCPIP
    cmdlets, verify again, and report the final state."""
    prefix = mask_to_prefix(mask) if (not dhcp and mask) else 0
    netsh = build_windows_commands("", dhcp, ip, mask, gateway, dns, not dns, index)
    netsh_ps = "\n".join(f"Run-Netsh {_ps_str(c[len('netsh '):])}" for c in netsh)
    dns_ps = "@(" + ",".join(_ps_str(d) for d in dns) + ")"
    return f"""
$ErrorActionPreference = 'Continue'
$log = {_ps_str(log_path)}
function Log([string]$m) {{ Add-Content -LiteralPath $log -Value $m -Encoding UTF8 }}
$idx = {int(index)}
$dhcp = ${'true' if dhcp else 'false'}
$ip = {_ps_str(ip)}; $prefix = {prefix}; $gw = {_ps_str(gateway)}; $dns = {dns_ps}

function Run-Netsh([string]$a) {{
  Log ("> netsh " + $a)
  $o = & netsh.exe ($a -split ' ') 2>&1 | Out-String
  Log ($o.Trim()); Log ("  exit code " + $LASTEXITCODE)
}}
function Get-State {{
  $if = Get-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue
  $a = @(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue) +
       @(Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -PolicyStore PersistentStore -ErrorAction SilentlyContinue)
  $r = @(Get-NetRoute -InterfaceIndex $idx -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue) +
       @(Get-NetRoute -InterfaceIndex $idx -DestinationPrefix '0.0.0.0/0' -PolicyStore PersistentStore -ErrorAction SilentlyContinue)
  [pscustomobject]@{{ Dhcp = [string]$if.Dhcp
    IPs = @($a | ForEach-Object {{ "$($_.IPAddress)/$($_.PrefixLength)" }} | Select-Object -Unique)
    Gateways = @($r | ForEach-Object {{ [string]$_.NextHop }} | Select-Object -Unique) }}
}}
function Test-Done($s) {{
  if ($dhcp) {{ return ($s.Dhcp -eq 'Enabled') }}
  $okIp = $s.IPs -contains "$ip/$prefix"
  $okGw = (-not $gw) -or ($s.Gateways -contains $gw)
  return (($s.Dhcp -ne 'Enabled') -and $okIp -and $okGw)
}}
function Step([string]$what, [scriptblock]$b) {{
  try {{ & $b; Log ("ok: " + $what) }} catch {{ Log ("ERROR " + $what + ": " + $_.Exception.Message) }}
}}

Log ("Adapter index " + $idx + " (" + (Get-NetAdapter -InterfaceIndex $idx -ErrorAction SilentlyContinue).Name + ")")
Log "== Method 1: netsh"
{netsh_ps}
Start-Sleep -Milliseconds 800
$s = Get-State
if (-not (Test-Done $s)) {{
  Log "== Method 2: PowerShell NetTCPIP"
  if ($dhcp) {{
    Step 'remove static gateway' {{ Get-NetRoute -InterfaceIndex $idx -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction Stop }}
    Step 'enable DHCP' {{ Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp Enabled -ErrorAction Stop }}
    Step 'DNS automatic' {{ Set-DnsClientServerAddress -InterfaceIndex $idx -ResetServerAddresses -ErrorAction Stop }}
  }} else {{
    Step 'disable DHCP' {{ Set-NetIPInterface -InterfaceIndex $idx -AddressFamily IPv4 -Dhcp Disabled -ErrorAction Stop }}
    Step 'remove old addresses' {{ Get-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false -ErrorAction Stop }}
    Step 'remove old gateway' {{ Get-NetRoute -InterfaceIndex $idx -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction Stop }}
    Step 'remove old gateway (persistent)' {{ Get-NetRoute -InterfaceIndex $idx -DestinationPrefix '0.0.0.0/0' -PolicyStore PersistentStore -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false -ErrorAction Stop }}
    if ($gw) {{
      Step 'set address + gateway' {{ New-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -IPAddress $ip -PrefixLength $prefix -DefaultGateway $gw -ErrorAction Stop | Out-Null }}
    }} else {{
      Step 'set address' {{ New-NetIPAddress -InterfaceIndex $idx -AddressFamily IPv4 -IPAddress $ip -PrefixLength $prefix -ErrorAction Stop | Out-Null }}
    }}
    if ($dns.Count -gt 0) {{ Step 'set DNS' {{ Set-DnsClientServerAddress -InterfaceIndex $idx -ServerAddresses $dns -ErrorAction Stop }} }}
    else {{ Step 'clear DNS' {{ Set-DnsClientServerAddress -InterfaceIndex $idx -ResetServerAddresses -ErrorAction Stop }} }}
  }}
  Start-Sleep -Milliseconds 800
  $s = Get-State
}}
Log ("STATE=" + ($s | ConvertTo-Json -Compress))
if (Test-Done $s) {{ Log "RESULT=OK" }} else {{ Log "RESULT=FAIL" }}
"""


def build_linux_commands(name: str, dhcp: bool, ip: str = "", mask: str = "", gateway: str = "",
                         dns: Optional[List[str]] = None, dns_auto: bool = True) -> List[List[str]]:
    con = name
    if dhcp:
        return [["nmcli", "con", "mod", con, "ipv4.method", "auto", "ipv4.addresses", "",
                 "ipv4.gateway", "", "ipv4.dns", ""],
                ["nmcli", "con", "up", con]]
    prefix = mask_to_prefix(mask)
    return [["nmcli", "con", "mod", con, "ipv4.method", "manual",
             "ipv4.addresses", f"{ip}/{prefix}", "ipv4.gateway", gateway or "",
             "ipv4.dns", " ".join(dns or [])],
            ["nmcli", "con", "up", con]]


def apply_settings(name: str, dhcp: bool, ip: str = "", mask: str = "", gateway: str = "",
                   dns: Optional[List[str]] = None, dns_auto: bool = True,
                   index: int = 0) -> Tuple[bool, str]:
    """Apply the configuration. Returns (success, output text)."""
    if IS_WINDOWS:
        return _apply_windows(index, name, dhcp, ip, mask, gateway, dns or [])
    if shutil.which("nmcli"):
        out = []
        for cmd in build_linux_commands(name, dhcp, ip, mask, gateway, dns, dns_auto):
            full = cmd if is_admin() or not shutil.which("pkexec") else ["pkexec"] + cmd
            r = subprocess.run(full, capture_output=True, text=True, timeout=60)
            out.append("$ " + " ".join(cmd) + "\n" + r.stdout + r.stderr)
            if r.returncode != 0:
                return False, "\n".join(out)
        return True, "\n".join(out)
    return False, ("Automatic configuration is only supported on Windows and on Linux with "
                   "NetworkManager. Configure the adapter manually.")


def _encoded(script: str) -> str:
    import base64
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _apply_windows(index: int, name: str, dhcp: bool, ip: str, mask: str, gateway: str,
                   dns: List[str]) -> Tuple[bool, str]:
    if not index:
        return False, f"Could not determine the interface index of adapter '{name}'. Press ⟳ and retry."
    tmp = tempfile.mkdtemp(prefix="bacnet_ip_")
    log = os.path.join(tmp, "apply.log")
    enc = _encoded(build_windows_script(index, dhcp, ip, mask, gateway, dns, log))
    base = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
    if is_admin():
        subprocess.run(base + ["-EncodedCommand", enc], capture_output=True, timeout=180,
                       creationflags=_NO_WINDOW)
    else:
        # Elevate through UAC (one prompt) and wait. -EncodedCommand avoids quoting,
        # file-encoding and execution-policy problems.
        outer = ("try { $p = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru "
                 "-WindowStyle Hidden -ArgumentList @('-NoProfile','-NonInteractive',"
                 f"'-ExecutionPolicy','Bypass','-EncodedCommand','{enc}'); exit 0 }} "
                 "catch { exit 1223 }")
        r = subprocess.run(base + ["-Command", outer], capture_output=True, timeout=240,
                           creationflags=_NO_WINDOW)
        if r.returncode == 1223:
            return False, "Administrator permission was refused (UAC) - nothing was changed."
    try:
        with open(log, "r", encoding="utf-8-sig", errors="replace") as f:
            text = f.read()
    except OSError:
        return False, ("The configuration script did not run (no log was produced). "
                       "Try starting BACnet Explorer with 'Run as administrator'.")
    ok = "RESULT=OK" in text
    lines = [l for l in text.splitlines() if not l.startswith(("RESULT=",))]
    detail = "\n".join(lines).strip()
    if not ok:
        errs = [l for l in lines if l.startswith("ERROR") or "exit code 1" in l or "rror" in l]
        hint = ""
        low = detail.lower()
        if "already exists" in low:
            hint = "\n\nHint: this IP address may already be configured on another adapter."
        elif "media" in low or "disconnected" in low:
            hint = "\n\nHint: the adapter is disconnected; plug in the cable and retry."
        elif "access is denied" in low or "requires elevation" in low:
            hint = "\n\nHint: run BACnet Explorer as administrator."
        detail = ("The adapter did not take the new settings.\n\n" +
                  ("\n".join(errs[-6:]) + "\n\n" if errs else "") + "Full log:\n" + detail + hint)
    return ok, detail


def command_preview(name: str, dhcp: bool, ip: str = "", mask: str = "", gateway: str = "",
                    dns: Optional[List[str]] = None, dns_auto: bool = True, index: int = 0) -> str:
    if IS_WINDOWS or not shutil.which("nmcli"):
        return "\n".join(build_windows_commands(name, dhcp, ip, mask, gateway, dns, dns_auto, index))
    return "\n".join(" ".join(repr(p) if (" " in p or not p) else p for p in c)
                     for c in build_linux_commands(name, dhcp, ip, mask, gateway, dns, dns_auto))
