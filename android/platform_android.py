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


def network_info() -> Tuple[str, int, str]:
    """(local IPv4, prefix length, broadcast address) of the active Wi-Fi / Ethernet network."""
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
