"""
Android-specific helpers (Wi-Fi address, multicast lock, Downloads, sharing).
Every function falls back gracefully on a PC so the app can also be run on the desktop.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
import socket
from typing import Optional, Tuple

try:
    from kivy.utils import platform as _kv_platform
except Exception:  # pragma: no cover
    _kv_platform = "unknown"

IS_ANDROID = _kv_platform == "android"
_lock = None


def _activity():
    from jnius import autoclass  # type: ignore
    return autoclass("org.kivy.android.PythonActivity").mActivity


def acquire_multicast_lock() -> bool:
    """Android drops incoming broadcast packets (I-Am replies!) unless a MulticastLock is held."""
    global _lock
    if not IS_ANDROID:
        return True
    try:
        from jnius import autoclass  # type: ignore
        Context = autoclass("android.content.Context")
        wifi = _activity().getApplicationContext().getSystemService(Context.WIFI_SERVICE)
        if _lock is None:
            _lock = wifi.createMulticastLock("basil_bacnet")
            _lock.setReferenceCounted(False)
        if not _lock.isHeld():
            _lock.acquire()
        return True
    except Exception as e:
        print("multicast lock:", e)
        return False


def release_multicast_lock():
    try:
        if _lock is not None and _lock.isHeld():
            _lock.release()
    except Exception:
        pass


def _fallback_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "0.0.0.0"


def network_info(adapter: str = "") -> Tuple[str, int, str]:
    """(local IPv4, prefix length, broadcast address) of the chosen adapter, or of the active network."""
    if adapter:
        a = find_adapter(adapter)
        if a:
            return a["ip"], a["prefix"], a["broadcast"]
    ip, prefix = "", 24
    if IS_ANDROID:
        try:
            from jnius import autoclass, cast  # type: ignore
            Context = autoclass("android.content.Context")
            cm = _activity().getSystemService(Context.CONNECTIVITY_SERVICE)
            lp = cm.getLinkProperties(cm.getActiveNetwork())
            addrs = lp.getLinkAddresses()
            for i in range(addrs.size()):
                la = addrs.get(i)
                host = la.getAddress().getHostAddress()
                if host and "." in host and ":" not in host:
                    ip, prefix = host, int(la.getPrefixLength())
                    break
        except Exception as e:
            print("network info:", e)
    if not ip:
        ip = _fallback_ip()
        try:
            import psutil  # type: ignore
            for _n, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if a.family == socket.AF_INET and a.address == ip and a.netmask:
                        prefix = ipaddress.IPv4Network(f"0.0.0.0/{a.netmask}").prefixlen
        except Exception:
            pass
    try:
        bc = str(ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False).broadcast_address)
    except ValueError:
        bc = "255.255.255.255"
    return ip, prefix, bc


# ---------------------------------------------------------------- network adapters
KIND_NAMES = {0: "Mobile data", 1: "Wi-Fi", 2: "Bluetooth", 3: "Ethernet", 4: "VPN", 8: "USB"}
_bound = None          # interface name the app is currently bound to ("" = automatic)


def _bc(ip: str, prefix: int) -> str:
    try:
        return str(ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False).broadcast_address)
    except ValueError:
        return "255.255.255.255"


def _android_networks():
    """[(java Network, info dict)] for every connected network that has an IPv4 address."""
    from jnius import autoclass  # type: ignore
    Context = autoclass("android.content.Context")
    cm = _activity().getSystemService(Context.CONNECTIVITY_SERVICE)
    out = []
    for net in cm.getAllNetworks():
        try:
            caps = cm.getNetworkCapabilities(net)
            lp = cm.getLinkProperties(net)
            if caps is None or lp is None:
                continue
            kind = next((name for t, name in ((3, "Ethernet"), (8, "USB"), (1, "Wi-Fi"), (0, "Mobile data"),
                                              (4, "VPN"), (2, "Bluetooth")) if caps.hasTransport(t)), "Network")
            iface = str(lp.getInterfaceName() or "")
            addrs = lp.getLinkAddresses()
            for i in range(addrs.size()):
                la = addrs.get(i)
                host = str(la.getAddress().getHostAddress() or "")
                if host and "." in host and ":" not in host:
                    prefix = int(la.getPrefixLength())
                    out.append((net, {"name": iface, "kind": kind, "ip": host, "prefix": prefix,
                                      "broadcast": _bc(host, prefix)}))
                    break
        except Exception as e:
            print("adapter:", e)
    return out


def list_adapters() -> list:
    """Network adapters with an IPv4 address: [{name, kind, ip, prefix, broadcast}].
    On a phone this lists Wi-Fi, a USB-C Ethernet adapter, mobile data ..."""
    if IS_ANDROID:
        try:
            return [info for _n, info in _android_networks()]
        except Exception as e:
            print("adapters:", e)
            return []
    out = []
    try:
        import psutil  # type: ignore
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and a.netmask and not a.address.startswith("127."):
                    prefix = ipaddress.IPv4Network(f"0.0.0.0/{a.netmask}").prefixlen
                    kind = "Wi-Fi" if name.lower().startswith(("wl", "wi")) else "Ethernet"
                    out.append({"name": name, "kind": kind, "ip": a.address, "prefix": prefix,
                                "broadcast": _bc(a.address, prefix)})
    except Exception:
        ip = _fallback_ip()
        if ip != "0.0.0.0":
            out.append({"name": "default", "kind": "Network", "ip": ip, "prefix": 24, "broadcast": _bc(ip, 24)})
    return out


def adapter_label(a: dict) -> str:
    return f"{a['kind']} ({a['name']})  {a['ip']}/{a['prefix']}"


def find_adapter(name: str) -> Optional[dict]:
    return next((a for a in list_adapters() if a["name"] == name), None) if name else None


def bind_to_adapter(name: str) -> bool:
    """Send/receive ALL of the app's traffic through one adapter (e.g. the USB-C Ethernet "eth0")
    even while Wi-Fi or mobile data is also connected. "" = automatic (Android's default network).
    Returns False if that adapter is not connected."""
    global _bound
    if not IS_ANDROID:
        _bound = name
        return not name or find_adapter(name) is not None
    try:
        from jnius import autoclass  # type: ignore
        Context = autoclass("android.content.Context")
        cm = _activity().getSystemService(Context.CONNECTIVITY_SERVICE)
        if not name:
            cm.bindProcessToNetwork(None)
            _bound = ""
            return True
        for net, info in _android_networks():
            if info["name"] == name:
                ok = bool(cm.bindProcessToNetwork(net))
                _bound = name if ok else ""
                return ok
        cm.bindProcessToNetwork(None)
        _bound = ""
        return False
    except Exception as e:
        print("bind adapter:", e)
        return False


def device_id() -> str:
    """Stable per-phone id (ANDROID_ID) used to bind the auto-login token to this phone."""
    if not IS_ANDROID:
        return ""
    try:
        from jnius import autoclass  # type: ignore
        Secure = autoclass("android.provider.Settings$Secure")
        return str(Secure.getString(_activity().getContentResolver(), Secure.ANDROID_ID))
    except Exception:
        return ""


def save_to_downloads(path: str, mime: str = "application/vnd.openxmlformats-officedocument."
                                              "spreadsheetml.sheet") -> Tuple[str, Optional[object]]:
    """Copy a file to the phone's shared storage (Downloads). Returns (where, uri-or-None)."""
    if IS_ANDROID:
        try:
            from androidstorage4kivy import SharedStorage  # type: ignore
            uri = SharedStorage().copy_to_shared(path, collection=None)
            return "Downloads / Documents (shared storage)", uri
        except Exception as e:
            print("shared storage:", e)
            return path, None
    dest_dir = os.path.join(os.path.expanduser("~"), "Downloads")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(path))
    shutil.copyfile(path, dest)
    return dest, None


def share(uri_or_path) -> bool:
    """Open Android's share sheet (WhatsApp, e-mail, Drive ...)."""
    if not IS_ANDROID:
        return False
    try:
        from androidstorage4kivy import ShareSheet  # type: ignore
        ShareSheet().share_file(uri_or_path)
        return True
    except Exception as e:
        print("share:", e)
        return False
