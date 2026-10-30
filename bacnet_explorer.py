#!/usr/bin/env python3
"""
Basil BACnet Explorer - a YABE-style BACnet/IP discovery and commissioning tool.

Features
  * BACnet/IP channel on any local interface, optional BBMD foreign-device registration
  * Who-Is discovery (ranges, local/global/directed), add device by IP, Who-Has
  * Routed devices (MS/TP behind routers / gateways) via DNET/DADR addressing
  * Address-space browser with object names; segmented responses supported
  * Property grid reading ALL properties (RPM -> Property_List -> default set)
  * WriteProperty with type selection, priority 1-16 and relinquish (NULL)
  * COV subscriptions (confirmed/unconfirmed, auto-renew) with automatic polling fallback
  * Live trend graph, communication log, packet trace
  * Time synchronization, ReinitializeDevice, DeviceCommunicationControl
  * Export of device points to CSV

Requires only the Python standard library (Tkinter). 'psutil' is optional and
improves network-interface detection.
"""
from __future__ import annotations

import csv
import datetime
import json
import os
import queue
import re
import subprocess
import sys
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
import threading
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any, Callable, Dict, List, Optional

from bacnet import constants as C
from bacnet import codec as X
from bacnet.client import (BACnetClient, BACnetError, BACnetException, DeviceInfo, Subscription,
                           list_interfaces)
from bacnet.codec import Address, ObjectId
import netconfig
from auth import Auth, LoginScreen
from graphics.panel import GraphicsPanel
from xlsx_export import Sheet, write_xlsx

APP_NAME = "Basil BACnet Explorer"
APP_VERSION = "1.6.1"
# When frozen into an .exe (PyInstaller), bundled files live in sys._MEIPASS.
BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(BASE_DIR, "assets")
SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".bacnet_explorer.json")

GRAPH_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#ff7f0e", "#9467bd", "#8c564b",
                "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"]

THEMES: Dict[str, Dict[str, str]] = {
    "light": {
        "bg": "#f3f5f7", "panel": "#ffffff", "fg": "#1f2a30", "muted": "#6b7780",
        "border": "#c9d2d8", "select": "#cfe5fb", "select_fg": "#0b2540", "header": "#ffffff",
        "heading": "#e8edf0", "button": "#e9edf0", "button_active": "#dbe2e7", "entry": "#ffffff",
        "accent": "#4caf32", "addr": "#c62828", "canvas": "#ffffff", "grid": "#eeeeee",
        "axis": "#555555", "frame": "#bbbbbb",
    },
    "dark": {
        "bg": "#1e2327", "panel": "#252b30", "fg": "#e3e8eb", "muted": "#9aa7b0",
        "border": "#3a434a", "select": "#2d5a88", "select_fg": "#ffffff", "header": "#161a1d",
        "heading": "#2c3338", "button": "#2f373d", "button_active": "#3b454c", "entry": "#2a3136",
        "accent": "#5cc93e", "addr": "#ff6b6b", "canvas": "#1e2227", "grid": "#2f363c",
        "axis": "#b0bec5", "frame": "#4a545b",
    },
}

LOG_COLORS_DARK = {"error": "#ff8a80", "warning": "#ffcc80", "info": "#e3e8eb",
                   "debug": "#9aa7b0", "trace": "#90caf9"}

LOG_COLORS = {"error": "#c62828", "warning": "#b26a00", "info": "#1a1a1a",
              "debug": "#6b6b6b", "trace": "#2e5c8a"}


# ==========================================================================
# Small helpers
# ==========================================================================
def load_settings() -> Dict[str, Any]:
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_settings(data: Dict[str, Any]):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def make_icon(root: tk.Misc, color: str, shape: str = "square", size: int = 14) -> tk.PhotoImage:
    """Draw a tiny icon pixel by pixel so no image files are needed."""
    img = tk.PhotoImage(master=root, width=size, height=size)
    c = (size - 1) / 2
    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            inside = False
            if shape == "circle":
                inside = (x - c) ** 2 + (y - c) ** 2 <= (c - 1) ** 2
            elif shape == "square":
                inside = 2 <= x <= size - 3 and 2 <= y <= size - 3
            elif shape == "diamond":
                inside = abs(x - c) + abs(y - c) <= c - 1
            elif shape == "folder":
                inside = (3 <= y <= size - 3 and 1 <= x <= size - 2) or (2 <= y <= 3 and 1 <= x <= 6)
            elif shape == "device":
                inside = 1 <= x <= size - 2 and 2 <= y <= size - 3 and not (
                    3 <= x <= size - 4 and 4 <= y <= size - 7)
            elif shape == "network":
                inside = (abs(y - c) <= 1 and 1 <= x <= size - 2) or (abs(x - c) <= 1 and 1 <= y <= size - 2) \
                    or (x - c) ** 2 + (y - c) ** 2 <= 6
            elif shape == "triangle":
                inside = y >= 2 and abs(x - c) <= (y - 1) / 2 and y <= size - 2
            row.append(color if inside else "")
        rows.append(row)
    for y, row in enumerate(rows):
        for x, col in enumerate(row):
            if col:
                img.put(col, (x, y))
    return img


def units_suffix(units: Any) -> str:
    if units is None:
        return ""
    u = int(units)
    if u == 95:
        return ""
    return " " + C.UNIT_SYMBOLS.get(u, C.ENGINEERING_UNITS.get(u, str(u)))


def center_on(win: tk.Toplevel, parent: tk.Misc):
    win.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{px + max(0, (pw - w) // 2)}+{py + max(0, (ph - h) // 3)}")
    except tk.TclError:
        pass


# ==========================================================================
# Dialogs
# ==========================================================================
class BaseDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, title: str):
        super().__init__(parent)
        self.withdraw()
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result: Any = None
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def add_buttons(self, ok_text: str = "OK", extra: Optional[List[tuple]] = None):
        bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="Cancel", command=self.cancel).pack(side="right")
        ttk.Button(bar, text=ok_text, command=self.ok, style="Accent.TButton").pack(
            side="right", padx=(0, 6))
        for text, cmd in extra or []:
            ttk.Button(bar, text=text, command=cmd).pack(side="left")
        self.bind("<Return>", lambda e: self.ok())

    def show(self):
        center_on(self, self.master)
        self.deiconify()
        try:
            self.wait_visibility()
            self.grab_set()
        except tk.TclError:
            pass
        self.focus_set()
        self.wait_window()
        return self.result

    def ok(self):
        try:
            self.result = self.validate()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e), parent=self)
            return
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()

    def validate(self) -> Any:
        return True

    def row(self, r: int, label: str, widget: tk.Widget, hint: str = ""):
        ttk.Label(self.body, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
        widget.grid(row=r, column=1, sticky="ew", pady=3)
        if hint:
            ttk.Label(self.body, text=hint, style="Hint.TLabel").grid(row=r, column=2, sticky="w",
                                                                    padx=(8, 0))


class ChannelDialog(BaseDialog):
    """Open a BACnet/IP channel (interface, port, BBMD)."""

    def __init__(self, parent, settings: Dict[str, Any]):
        super().__init__(parent, "Open BACnet/IP channel")
        self.ifaces = list_interfaces()
        choices = ["0.0.0.0  (all interfaces)"] + [str(i) for i in self.ifaces]
        self.iface = ttk.Combobox(self.body, values=choices, width=40, state="readonly")
        last_ip = settings.get("local_ip")
        idx = 0
        for k, i in enumerate(self.ifaces):
            if i.ip == last_ip:
                idx = k + 1
                break
        else:
            if self.ifaces:
                idx = 1
        self.iface.current(idx)
        self.iface.bind("<<ComboboxSelected>>", self._iface_changed)
        self.port = ttk.Entry(self.body, width=12)
        self.port.insert(0, str(settings.get("port", C.BACNET_PORT)))
        self.bcast = ttk.Entry(self.body, width=20)
        self.remote_port = ttk.Entry(self.body, width=12)
        self.remote_port.insert(0, str(settings.get("remote_port", C.BACNET_PORT)))
        self.timeout = ttk.Entry(self.body, width=8)
        self.timeout.insert(0, str(settings.get("timeout", 3.0)))
        self.retries = ttk.Entry(self.body, width=8)
        self.retries.insert(0, str(settings.get("retries", 2)))
        self.use_bbmd = tk.BooleanVar(value=bool(settings.get("use_bbmd", False)))
        self.bbmd = ttk.Entry(self.body, width=20)
        self.bbmd.insert(0, settings.get("bbmd", ""))
        self.ttl = ttk.Entry(self.body, width=8)
        self.ttl.insert(0, str(settings.get("ttl", 900)))
        self.discover = tk.BooleanVar(value=settings.get("discover_on_start", True))

        self.row(0, "Local interface", self.iface)
        self.row(1, "Local UDP port", self.port, "0xBAC0 = 47808; 0 = any free port")
        self.row(2, "Broadcast address", self.bcast)
        self.row(3, "Device UDP port", self.remote_port, "port used for broadcasts")
        self.row(4, "APDU timeout (s)", self.timeout)
        self.row(5, "Retries", self.retries)
        ttk.Separator(self.body).grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Checkbutton(self.body, text="Register as Foreign Device with BBMD",
                        variable=self.use_bbmd).grid(row=7, column=0, columnspan=3, sticky="w")
        self.row(8, "BBMD address", self.bbmd, "ip[:port]")
        self.row(9, "Time-to-live (s)", self.ttl)
        ttk.Checkbutton(self.body, text="Send Who-Is after start",
                        variable=self.discover).grid(row=10, column=0, columnspan=3, sticky="w",
                                                     pady=(8, 0))
        self.body.columnconfigure(1, weight=1)
        self._iface_changed(set_bcast=settings.get("broadcast"))
        self.add_buttons("Start")

    def _iface_changed(self, event=None, set_bcast=None):
        i = self.iface.current()
        bc = set_bcast or ("255.255.255.255" if i <= 0 else self.ifaces[i - 1].broadcast)
        self.bcast.delete(0, "end")
        self.bcast.insert(0, bc)

    def validate(self):
        i = self.iface.current()
        local_ip = "0.0.0.0" if i <= 0 else self.ifaces[i - 1].ip
        port = int(self.port.get())
        if not 0 <= port <= 65535:
            raise ValueError("Port must be 0..65535")
        bbmd_ip, bbmd_port = "", C.BACNET_PORT
        if self.use_bbmd.get():
            txt = self.bbmd.get().strip()
            if not txt:
                raise ValueError("Enter the BBMD IP address")
            bbmd_ip, _, p = txt.partition(":")
            bbmd_port = int(p) if p else C.BACNET_PORT
        return {
            "local_ip": local_ip, "port": port, "broadcast": self.bcast.get().strip(),
            "remote_port": int(self.remote_port.get()),
            "timeout": float(self.timeout.get()), "retries": int(self.retries.get()),
            "use_bbmd": self.use_bbmd.get(), "bbmd": self.bbmd.get().strip(),
            "bbmd_ip": bbmd_ip, "bbmd_port": bbmd_port, "ttl": int(self.ttl.get()),
            "discover_on_start": self.discover.get(),
        }


class WhoIsDialog(BaseDialog):
    def __init__(self, parent, settings: Dict[str, Any]):
        super().__init__(parent, "Who-Is")
        self.low = ttk.Entry(self.body, width=12)
        self.high = ttk.Entry(self.body, width=12)
        self.low.insert(0, settings.get("whois_low", ""))
        self.high.insert(0, settings.get("whois_high", ""))
        self.target = ttk.Entry(self.body, width=24)
        self.target.insert(0, settings.get("whois_target", ""))
        self.glob = tk.BooleanVar(value=settings.get("whois_global", True))
        self.row(0, "Low limit", self.low, "empty = all devices")
        self.row(1, "High limit", self.high)
        self.row(2, "Directed to", self.target, "empty = broadcast; ip[:port]")
        ttk.Checkbutton(self.body, text="Global broadcast (reach devices behind routers)",
                        variable=self.glob).grid(row=3, column=0, columnspan=3, sticky="w",
                                                 pady=(6, 0))
        self.add_buttons("Send")

    def validate(self):
        lo, hi = self.low.get().strip(), self.high.get().strip()
        if bool(lo) != bool(hi):
            raise ValueError("Enter both limits or neither")
        low = int(lo) if lo else None
        high = int(hi) if hi else None
        if low is not None and high is not None and not (0 <= low <= high <= 4194303):
            raise ValueError("Limits must satisfy 0 <= low <= high <= 4194303")
        target = None
        t = self.target.get().strip()
        if t:
            ip, _, p = t.partition(":")
            target = (ip, int(p) if p else C.BACNET_PORT)
        return {"low": low, "high": high, "target": target, "global": self.glob.get(),
                "raw": (lo, hi, t)}


class AddDeviceDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "Add device by address")
        self.ip = ttk.Entry(self.body, width=20)
        self.port = ttk.Entry(self.body, width=10)
        self.port.insert(0, str(C.BACNET_PORT))
        self.net = ttk.Entry(self.body, width=10)
        self.mac = ttk.Entry(self.body, width=20)
        self.row(0, "IP address", self.ip, "device or router IP")
        self.row(1, "UDP port", self.port)
        self.row(2, "Network number", self.net, "optional, for routed devices")
        self.row(3, "MAC address", self.mac, "e.g. 5 (MS/TP) or hex 0a0b")
        self.add_buttons("Add")
        self.ip.focus_set()

    def validate(self):
        ip = self.ip.get().strip()
        if not ip:
            raise ValueError("Enter an IP address")
        net_txt, mac_txt = self.net.get().strip(), self.mac.get().strip()
        net = int(net_txt) if net_txt else None
        mac = b""
        if mac_txt:
            mac = bytes([int(mac_txt)]) if mac_txt.isdigit() and int(mac_txt) < 256 \
                else bytes.fromhex(mac_txt.replace(":", "").replace(" ", ""))
        if (net is None) != (not mac):
            raise ValueError("Network number and MAC must be given together")
        return ip, int(self.port.get()), net, mac


class WriteDialog(BaseDialog):
    def __init__(self, parent, oid: ObjectId, prop: int, current: Any,
                 state_text: Optional[List[str]] = None, commandable: bool = False,
                 index: Optional[int] = None, priority: Optional[int] = None):
        super().__init__(parent, "Write property")
        self.oid, self.prop = oid, prop
        ttk.Label(self.body, text=f"{oid}   ({oid.short})", style="Bold.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(self.body, text=f"Property: {C.property_name(prop)}").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 8))

        default_type = X.type_name_of(current)
        if default_type not in X.WRITABLE_TYPES:
            default_type = "Real" if oid.type in C.ANALOG_TYPES else "CharacterString"
        if isinstance(current, X.Null) and prop == C.PROP_PRESENT_VALUE:
            default_type = "Real" if oid.type in C.ANALOG_TYPES else \
                "Enumerated" if oid.type in C.BINARY_TYPES else "Unsigned"

        choices: List[str] = []
        table = C.enum_table_for(oid.type, prop)
        if table:
            choices = [f"{k} - {v}" for k, v in sorted(table.items())]
        elif state_text and prop in (C.PROP_PRESENT_VALUE, C.PROP_RELINQUISH_DEFAULT):
            choices = [f"{k + 1} - {s}" for k, s in enumerate(state_text)]
        elif isinstance(current, bool):
            choices = ["True", "False"]
        self.value = ttk.Combobox(self.body, values=choices, width=34)
        if isinstance(current, X.Null) or isinstance(current, list):
            init = ""
        elif table and isinstance(current, int):
            init = f"{int(current)} - {table.get(int(current), '')}"
        elif state_text and isinstance(current, int) and 0 < int(current) <= len(state_text):
            init = f"{int(current)} - {state_text[int(current) - 1]}"
        else:
            init = X.format_plain(current)
        self.value.set(init)
        self.vtype = ttk.Combobox(self.body, values=X.WRITABLE_TYPES, state="readonly", width=20)
        self.vtype.set(default_type)
        self.prio = ttk.Combobox(self.body, values=["(none)"] + [str(i) for i in range(1, 17)],
                                 state="readonly", width=10)
        if priority is not None:
            self.prio.set(str(priority))
        else:
            self.prio.set("8" if commandable and prop == C.PROP_PRESENT_VALUE else "(none)")
        self.index = ttk.Entry(self.body, width=10)
        if index is not None:
            self.index.insert(0, str(index))
        self.row(2, "Value", self.value)
        self.row(3, "Data type", self.vtype)
        self.row(4, "Priority", self.prio, "1 = highest, 16 = lowest")
        self.row(5, "Array index", self.index, "optional")
        self.body.columnconfigure(1, weight=1)
        self.add_buttons("Write", extra=[("Write NULL (relinquish)", self._relinquish)])
        self.value.focus_set()
        self.value.select_range(0, "end")

    def _relinquish(self):
        self.vtype.set("Null")
        self.value.set("NULL")
        self.ok()

    def validate(self):
        vt = self.vtype.get()
        txt = self.value.get()
        if vt != "Null" and " - " in txt and txt.split(" - ")[0].strip().lstrip("-").isdigit():
            txt = txt.split(" - ")[0]
        if vt not in ("CharacterString", "Null") and not txt.strip():
            raise ValueError("Enter a value")
        value = X.parse_user_value(txt, vt)
        p = self.prio.get()
        prio = int(p) if p.isdigit() else None
        idx_txt = self.index.get().strip()
        idx = int(idx_txt) if idx_txt else None
        return value, prio, idx


class SubscribeDialog(BaseDialog):
    def __init__(self, parent, settings: Dict[str, Any], count: int):
        super().__init__(parent, "Subscribe / monitor")
        ttk.Label(self.body, text=f"{count} object(s) selected").grid(row=0, column=0,
                                                                      columnspan=3, sticky="w")
        self.mode = tk.StringVar(value=settings.get("sub_mode", "cov"))
        f = ttk.Frame(self.body)
        ttk.Radiobutton(f, text="COV subscription", value="cov", variable=self.mode).pack(side="left")
        ttk.Radiobutton(f, text="Periodic polling", value="poll",
                        variable=self.mode).pack(side="left", padx=10)
        f.grid(row=1, column=0, columnspan=3, sticky="w", pady=6)
        self.confirmed = tk.BooleanVar(value=settings.get("sub_confirmed", False))
        self.lifetime = ttk.Entry(self.body, width=10)
        self.lifetime.insert(0, str(settings.get("sub_lifetime", 300)))
        self.interval = ttk.Entry(self.body, width=10)
        self.interval.insert(0, str(settings.get("poll_interval", 5)))
        self.fallback = tk.BooleanVar(value=settings.get("sub_fallback", True))
        ttk.Checkbutton(self.body, text="Confirmed notifications",
                        variable=self.confirmed).grid(row=2, column=0, columnspan=3, sticky="w")
        self.row(3, "Lifetime (s)", self.lifetime, "renewed automatically")
        self.row(4, "Poll interval (s)", self.interval)
        ttk.Checkbutton(self.body, text="Fall back to polling if COV is not supported",
                        variable=self.fallback).grid(row=5, column=0, columnspan=3, sticky="w")
        self.add_buttons("Subscribe")

    def validate(self):
        lifetime = int(self.lifetime.get())
        interval = float(self.interval.get())
        if lifetime < 10 or interval < 0.5:
            raise ValueError("Lifetime must be ≥ 10 s and interval ≥ 0.5 s")
        return {"sub_mode": self.mode.get(), "sub_confirmed": self.confirmed.get(),
                "sub_lifetime": lifetime, "poll_interval": interval,
                "sub_fallback": self.fallback.get()}


class ReadPropertyDialog(BaseDialog):
    def __init__(self, parent, oid: Optional[ObjectId]):
        super().__init__(parent, "Read property")
        self.obj = ttk.Entry(self.body, width=30)
        self.obj.insert(0, str(oid) if oid else "analog-value:1")
        self.prop = ttk.Combobox(self.body, width=30,
                                 values=sorted(C.PROPERTY_IDS.keys()))
        self.prop.set("present-value")
        self.index = ttk.Entry(self.body, width=10)
        self.row(0, "Object", self.obj, "type:instance")
        self.row(1, "Property", self.prop, "name or number")
        self.row(2, "Array index", self.index, "optional")
        self.add_buttons("Read")

    def validate(self):
        oid = ObjectId.parse(self.obj.get())
        prop = C.lookup_property(self.prop.get())
        idx = self.index.get().strip()
        return oid, prop, int(idx) if idx else None


class NetworkAdapterDialog(tk.Toplevel):
    """Change IP address, subnet mask, gateway and DNS of this computer's adapters."""

    def __init__(self, app: "ExplorerApp"):
        super().__init__(app.root)
        self.app = app
        self.title("Network adapter settings")
        self.transient(app.root)
        self.resizable(False, False)
        self.adapters: List[netconfig.AdapterConfig] = []
        self.applied = False
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        self.body = f

        ttk.Label(f, text="Adapter").grid(row=0, column=0, sticky="w")
        self.adapter = ttk.Combobox(f, state="readonly", width=44)
        self.adapter.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2)
        self.adapter.bind("<<ComboboxSelected>>", lambda e: self._show_adapter())
        ttk.Button(f, text="⟳", width=3, command=self._load).grid(row=0, column=3, padx=(4, 0))
        self.info = ttk.Label(f, text="Loading adapters…", foreground="#555555", justify="left")
        self.info.grid(row=1, column=0, columnspan=4, sticky="w", pady=(2, 8))

        prof = ttk.LabelFrame(f, text="Saved profiles", padding=6)
        prof.grid(row=2, column=0, columnspan=4, sticky="ew")
        self.profile = ttk.Combobox(prof, state="readonly", width=30)
        self.profile.pack(side="left")
        self.profile.bind("<<ComboboxSelected>>", lambda e: self._load_profile())
        ttk.Button(prof, text="Save as…", command=self._save_profile).pack(side="left", padx=4)
        ttk.Button(prof, text="Delete", command=self._delete_profile).pack(side="left")

        self.mode = tk.StringVar(value="static")
        mf = ttk.Frame(f)
        mf.grid(row=3, column=0, columnspan=4, sticky="w", pady=(8, 2))
        ttk.Radiobutton(mf, text="Use the following IP address (static)", value="static",
                        variable=self.mode, command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(mf, text="Obtain automatically (DHCP)", value="dhcp",
                        variable=self.mode, command=self._mode_changed).pack(side="left", padx=12)
        self.entries: Dict[str, ttk.Entry] = {}
        labels = [("ip", "IP address"), ("mask", "Subnet mask"), ("gateway", "Default gateway"),
                  ("dns1", "Preferred DNS"), ("dns2", "Alternate DNS")]
        for r, (k, lab) in enumerate(labels, start=4):
            ttk.Label(f, text=lab).grid(row=r, column=0, sticky="w", pady=2)
            e = ttk.Entry(f, width=22)
            e.grid(row=r, column=1, sticky="w", pady=2)
            e.bind("<KeyRelease>", lambda ev: self._preview())
            self.entries[k] = e
        ttk.Label(f, text="e.g. 255.255.255.0 or /24", foreground="#777777").grid(
            row=5, column=2, sticky="w", padx=6)
        ttk.Label(f, text="optional", foreground="#777777").grid(row=6, column=2, sticky="w", padx=6)
        self.calc = ttk.Label(f, text="", foreground="#2e5c8a")
        self.calc.grid(row=9, column=0, columnspan=4, sticky="w", pady=(4, 0))
        ttk.Label(f, text="Commands that will be executed:").grid(row=10, column=0, columnspan=4,
                                                                 sticky="w", pady=(8, 0))
        self.preview = tk.Text(f, height=4, width=70, font=("Consolas", 9) if
                               sys.platform.startswith("win") else ("Courier", 9),
                               background="#f5f5f5", relief="flat")
        self.preview.grid(row=11, column=0, columnspan=4, sticky="ew")
        note = ("Windows will ask for administrator permission (UAC) when you apply."
                if netconfig.IS_WINDOWS and not netconfig.is_admin() else "")
        ttk.Label(f, text=note, foreground="#b26a00").grid(row=12, column=0, columnspan=4, sticky="w")
        self.restart = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="Restart the BACnet/IP channel on the new address after applying",
                        variable=self.restart).grid(row=13, column=0, columnspan=4, sticky="w",
                                                    pady=(4, 0))
        bar = ttk.Frame(self, padding=(12, 0, 12, 12))
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.apply_btn = ttk.Button(bar, text="Apply", command=self._apply)
        self.apply_btn.pack(side="right", padx=6)
        self.status = ttk.Label(bar, text="")
        self.status.pack(side="left")
        self.bind("<Escape>", lambda e: self.destroy())
        self._refresh_profiles()
        center_on(self, app.root)
        self._load()

    # ---- adapters
    def _load(self):
        self.info.configure(text="Reading adapter configuration…")
        def work():
            res = netconfig.list_adapters()
            self.app.ui(lambda: self._loaded(res))
        threading.Thread(target=work, daemon=True).start()

    def _loaded(self, adapters: List[netconfig.AdapterConfig]):
        if not self.winfo_exists():
            return
        prev = self.adapter.get().split("  [")[0]
        self.adapters = adapters
        self.adapter.configure(values=[str(a) for a in adapters])
        if not adapters:
            self.info.configure(text="No network adapters found.")
            return
        idx = 0
        last = self.app.settings.get("net_adapter")
        for k, a in enumerate(adapters):
            if a.name in (prev, last):
                idx = k
                if a.name == prev:
                    break
        self.adapter.current(idx)
        self._show_adapter()

    def current_adapter(self) -> Optional[netconfig.AdapterConfig]:
        i = self.adapter.current()
        return self.adapters[i] if 0 <= i < len(self.adapters) else None

    def _show_adapter(self):
        a = self.current_adapter()
        if not a:
            return
        cur = (f"Current: {'DHCP' if a.dhcp else 'static'}   IP {a.ip or '-'}   mask {a.mask or '-'}"
               f"   gateway {a.gateway or '-'}   DNS {', '.join(a.dns) or '-'}")
        if a.description or a.mac:
            cur = f"{a.description}   MAC {a.mac}\n" + cur
        self.info.configure(text=cur)
        self.mode.set("dhcp" if a.dhcp else "static")
        for k, v in (("ip", a.ip), ("mask", a.mask), ("gateway", a.gateway),
                     ("dns1", a.dns[0] if a.dns else ""), ("dns2", a.dns[1] if len(a.dns) > 1 else "")):
            self.entries[k].delete(0, "end")
            self.entries[k].insert(0, v)
        self._mode_changed()

    def _mode_changed(self):
        st = "disabled" if self.mode.get() == "dhcp" else "normal"
        for k in ("ip", "mask", "gateway"):
            self.entries[k].configure(state=st)
        self._preview()

    def _values(self):
        mask = self.entries["mask"].get().strip()
        if mask.lstrip("/").isdigit():
            mask = netconfig.prefix_to_mask(int(mask.lstrip("/")))
        dns = [self.entries[k].get().strip() for k in ("dns1", "dns2") if self.entries[k].get().strip()]
        return (self.mode.get() == "dhcp", self.entries["ip"].get().strip(), mask,
                self.entries["gateway"].get().strip(), dns)

    def _preview(self):
        a = self.current_adapter()
        dhcp, ip, mask, gw, dns = self._values()
        txt, calc = "", ""
        if a:
            try:
                if not dhcp:
                    warn = netconfig.validate(ip, mask, gw, dns)
                    import ipaddress as _ip
                    net = _ip.IPv4Network(f"{ip}/{mask}", strict=False)
                    calc = f"Network {net}   broadcast {net.broadcast_address}   " \
                           f"{max(net.num_addresses - 2, 1)} hosts"
                    if warn:
                        calc += "   ⚠ " + " ".join(warn)
                txt = netconfig.command_preview(a.name, dhcp, ip, mask, gw, dns, not dns, a.index)
            except ValueError as e:
                calc = f"⚠ {e}"
        self.calc.configure(text=calc)
        self.preview.delete("1.0", "end")
        self.preview.insert("1.0", txt)

    # ---- profiles
    def _profiles(self) -> Dict[str, Any]:
        return self.app.settings.setdefault("net_profiles", {})

    def _refresh_profiles(self):
        self.profile.configure(values=sorted(self._profiles()))

    def _save_profile(self):
        name = simpledialog.askstring("Save profile", "Profile name (e.g. site or panel name):",
                                      parent=self)
        if not name:
            return
        dhcp, ip, mask, gw, dns = self._values()
        self._profiles()[name] = {"dhcp": dhcp, "ip": ip, "mask": mask, "gateway": gw, "dns": dns}
        self.app.save()
        self._refresh_profiles()
        self.profile.set(name)

    def _load_profile(self):
        p = self._profiles().get(self.profile.get())
        if not p:
            return
        self.mode.set("dhcp" if p.get("dhcp") else "static")
        dns = p.get("dns", [])
        for k, v in (("ip", p.get("ip", "")), ("mask", p.get("mask", "")),
                     ("gateway", p.get("gateway", "")), ("dns1", dns[0] if dns else ""),
                     ("dns2", dns[1] if len(dns) > 1 else "")):
            self.entries[k].configure(state="normal")
            self.entries[k].delete(0, "end")
            self.entries[k].insert(0, v)
        self._mode_changed()

    def _delete_profile(self):
        name = self.profile.get()
        if name and name in self._profiles():
            del self._profiles()[name]
            self.app.save()
            self.profile.set("")
            self._refresh_profiles()

    # ---- apply
    def _apply(self):
        a = self.current_adapter()
        if not a:
            return
        dhcp, ip, mask, gw, dns = self._values()
        if a.status.lower() == "disabled":
            messagebox.showerror("Adapter disabled", f"'{a.name}' is disabled in Windows.\n"
                                 "Enable it first (Control Panel ▸ Network Connections).", parent=self)
            return
        try:
            if not dhcp:
                warn = netconfig.validate(ip, mask, gw, dns)
                if warn and not messagebox.askyesno("Warning", "\n".join(warn) + "\n\nApply anyway?",
                                                    parent=self):
                    return
        except ValueError as e:
            messagebox.showerror("Invalid settings", str(e), parent=self)
            return
        summary = (f"Adapter: {a.name}\n\n" + ("Obtain IP automatically (DHCP)" if dhcp else
                   f"IP address: {ip}\nSubnet mask: {mask}\nGateway: {gw or '(none)'}") +
                   f"\nDNS: {', '.join(dns) if dns else ('automatic' if dhcp else '(none)')}\n\n"
                   "Network connections on this adapter will be interrupted briefly.")
        if not messagebox.askyesno("Apply network settings", summary, parent=self):
            return
        self.app.settings["net_adapter"] = a.name
        self.app.save()
        self.apply_btn.configure(state="disabled")
        self.status.configure(text="Applying…")
        self.app.log("info", f"Changing adapter '{a.name}': " +
                     ("DHCP" if dhcp else f"{ip} / {mask} gw {gw or '-'}"))

        def work():
            try:
                ok, out = netconfig.apply_settings(a.name, dhcp, ip, mask, gw, dns, not dns, a.index)
            except Exception as e:  # noqa
                ok, out = False, str(e)
            time.sleep(2.0 if ok else 0)  # let the adapter settle
            self.app.ui(lambda: self._applied(ok, out, ip if not dhcp else None))
        threading.Thread(target=work, daemon=True).start()

    def _show_details(self, title: str, text: str):
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        t = tk.Text(win, width=90, height=22, wrap="word", font=("Consolas", 9)
                    if sys.platform.startswith("win") else ("Courier", 9))
        t.insert("1.0", text)
        t.configure(state="disabled")
        t.pack(fill="both", expand=True, padx=8, pady=8)
        bar = ttk.Frame(win, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        ttk.Button(bar, text="Copy", command=lambda: (self.clipboard_clear(),
                                                      self.clipboard_append(text))).pack(side="right", padx=6)
        center_on(win, self)

    def _applied(self, ok: bool, out: str, new_ip: Optional[str]):
        self.app.log("info" if ok else "error", "Adapter change " + ("succeeded" if ok else "failed") +
                     (f": {out}" if out else ""))
        if not self.winfo_exists():
            return
        self.apply_btn.configure(state="normal")
        self.status.configure(text="Applied ✓" if ok else "Failed")
        if not ok:
            self._show_details("Could not change the IP address", out or "The change failed.")
            return
        self.applied = True
        self._load()
        if self.restart.get() and self.app.client is not None:
            if new_ip:
                self.app.settings["local_ip"] = new_ip
                self.app.settings.pop("broadcast", None)
            self.app.root.after(500, lambda: self.app.start_channel(force=True))


class ChangePasswordDialog(BaseDialog):
    def __init__(self, parent):
        super().__init__(parent, "Change password")
        self.old = ttk.Entry(self.body, width=26, show="•")
        self.new = ttk.Entry(self.body, width=26, show="•")
        self.new2 = ttk.Entry(self.body, width=26, show="•")
        self.row(0, "Current password", self.old)
        self.row(1, "New password", self.new)
        self.row(2, "Repeat new password", self.new2)
        ttk.Label(self.body, text="At least 8 characters, upper + lower case and a number.",
                  style="Hint.TLabel").grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.add_buttons("Change")
        self.old.focus_set()

    def validate(self):
        if self.new.get() != self.new2.get():
            raise ValueError("The new passwords do not match.")
        if not self.new.get():
            raise ValueError("Enter a new password.")
        return self.old.get(), self.new.get()


POINT_TYPES = {0, 1, 2, 3, 4, 5, 13, 14, 19, 23, 24, 40, 45, 46, 48, 54, 55}


def classify_point(vals: Dict[int, Any]) -> str:
    """Online / Out of service / Fault / No response from PV, status flags, reliability, OOS."""
    if C.PROP_PRESENT_VALUE not in vals:
        return "No response"
    flags = vals.get(C.PROP_STATUS_FLAGS)
    fault = isinstance(flags, X.BitString) and len(flags.bits) > 1 and flags.bits[1]
    rel = vals.get(C.PROP_RELIABILITY)
    try:
        rel_bad = rel is not None and int(rel) != 0
    except (TypeError, ValueError):
        rel_bad = False
    oos = bool(vals.get(C.PROP_OUT_OF_SERVICE)) or (
        isinstance(flags, X.BitString) and len(flags.bits) > 3 and flags.bits[3])
    if fault or rel_bad:
        return "Fault"
    return "Out of service" if oos else "Online"


class OnlineReport(tk.Toplevel):
    """Counts online / offline devices and points, exports everything to Excel."""
    STATUS_FILL = {"Online": "green", "Offline": "red", "Fault": "red", "No response": "red",
                   "Out of service": "amber", "Not checked": "grey"}

    def __init__(self, app: "ExplorerApp"):
        super().__init__(app.root)
        self.app = app
        self.title("Online devices & points")
        self.geometry("1100x640")
        self.minsize(820, 480)
        self.cancel = threading.Event()
        self.running = False
        self.devices: Dict[int, Dict[str, Any]] = {}
        self.points: List[Dict[str, Any]] = []
        self.scanned_at = ""
        self.scan_kind = ""

        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        self.cards: Dict[str, ttk.Label] = {}
        for k, title in (("dev_total", "Devices found"), ("dev_on", "Devices online"),
                         ("dev_off", "Devices offline"), ("pt_total", "Points"),
                         ("pt_on", "Points online"), ("pt_bad", "Points fault / no response")):
            f = ttk.Frame(top, padding=(12, 4))
            f.pack(side="left", padx=4)
            ttk.Label(f, text=title, style="Hint.TLabel").pack(anchor="w")
            lbl = ttk.Label(f, text="–", font=("Segoe UI", 18, "bold"))
            lbl.pack(anchor="w")
            self.cards[k] = lbl

        bar = ttk.Frame(self, padding=(10, 0, 10, 6))
        bar.pack(fill="x")
        self.whois = tk.BooleanVar(master=self, value=True)
        ttk.Checkbutton(bar, text="Send Who-Is first (find new devices)",
                        variable=self.whois).pack(side="left")
        self.btn_dev = ttk.Button(bar, text="Count online devices", command=lambda: self.start(False))
        self.btn_dev.pack(side="left", padx=(12, 4))
        self.btn_pts = ttk.Button(bar, text="Count online devices + points",
                                  command=lambda: self.start(True))
        self.btn_pts.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(bar, text="Stop", command=self.cancel.set, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        ttk.Button(bar, text="Export to Excel…", command=self.export).pack(side="right")
        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10)
        self.status = ttk.Label(self, text="Press a button to start counting.", style="Hint.TLabel",
                                padding=(10, 2))
        self.status.pack(fill="x")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        dcols = ("inst", "name", "addr", "status", "ms", "vendor", "model", "points", "ok", "oos",
                 "bad")
        dhead = ("Instance", "Name", "Address", "Status", "Resp. ms", "Vendor", "Model", "Points",
                 "Online", "Out of service", "Fault / no resp.")
        dwid = (80, 200, 160, 80, 70, 140, 120, 60, 60, 90, 100)
        self.dtree = self._table(nb, dcols, dhead, dwid)
        nb.add(self.dtree.master, text="Devices")  # type: ignore[arg-type]
        pcols = ("dev", "obj", "name", "value", "status", "rel")
        phead = ("Device", "Object", "Name", "Present value", "Status", "Reliability")
        pwid = (80, 120, 300, 140, 100, 160)
        self.ptree = self._table(nb, pcols, phead, pwid)
        nb.add(self.ptree.master, text="Points")  # type: ignore[arg-type]
        for t in (self.dtree, self.ptree):
            t.tag_configure("good", foreground="#2e7d32")
            t.tag_configure("bad", foreground="#e53935")
            t.tag_configure("warn", foreground="#ef6c00")
        self.protocol("WM_DELETE_WINDOW", self.close)
        center_on(self, app.root)
        self._fill_from_known()

    def _table(self, parent, cols, heads, widths):
        frame = ttk.Frame(parent)
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        for c, h, w in zip(cols, heads, widths):
            tree.heading(c, text=h, command=lambda c=c, t=tree: self._sort(t, c))
            tree.column(c, width=w, stretch=c in ("name", "model", "vendor"))
        ys = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=ys.set)
        tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def _sort(self, tree, col):
        rows = [(tree.set(i, col), i) for i in tree.get_children("")]
        def key(r):
            try:
                return (0, float(r[0]))
            except ValueError:
                return (1, r[0].lower())
        desc = getattr(tree, "_sort_desc", {}).get(col, False)
        rows.sort(key=key, reverse=desc)
        for n, (_, i) in enumerate(rows):
            tree.move(i, "", n)
        tree._sort_desc = {col: not desc}  # type: ignore[attr-defined]

    def _fill_from_known(self):
        cl = self.app.client
        if not cl:
            return
        for d in cl.devices.values():
            self.devices[d.instance] = self._dev_row(d, "Not checked")
        self._refresh_tables()

    @staticmethod
    def _dev_row(d: DeviceInfo, status: str) -> Dict[str, Any]:
        return {"inst": d.instance, "name": d.name, "addr": str(d.address), "status": status,
                "ms": "", "vendor": d.vendor_name or (d.vendor_id or ""), "model": d.model_name,
                "points": "", "ok": "", "oos": "", "bad": ""}

    # ---- scanning
    def start(self, with_points: bool):
        if self.running:
            return
        cl = self.app.client
        if cl is None or not cl.running:
            messagebox.showinfo(APP_NAME, "Open a BACnet/IP channel first.", parent=self)
            return
        self.running = True
        self.cancel.clear()
        self.scan_kind = "devices + points" if with_points else "devices"
        for b in (self.btn_dev, self.btn_pts):
            b.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.points = []
        threading.Thread(target=self._scan, args=(cl, with_points, self.whois.get()),
                         daemon=True).start()

    def _ui(self, fn):
        self.app.ui(lambda: fn() if self.winfo_exists() else None)

    def _set_status(self, text: str, done: int = -1, total: int = 0):
        def f():
            self.status.configure(text=text)
            if done >= 0:
                self.progress.configure(maximum=max(total, 1), value=done)
        self._ui(f)

    def _scan(self, cl: BACnetClient, with_points: bool, whois: bool):
        try:
            if whois:
                self._set_status("Sending Who-Is and waiting 4 s for I-Am replies…")
                self.app.ui(self.app.quick_whois)
                for _ in range(40):
                    if self.cancel.is_set():
                        break
                    time.sleep(0.1)
            devs = sorted(cl.devices.values(), key=lambda d: d.instance)
            total = len(devs)
            done = [0]
            lock = threading.Lock()

            def check(d: DeviceInfo):
                if self.cancel.is_set():
                    return
                row = self._dev_row(d, "Offline")
                t0 = time.time()
                try:
                    ack = cl.request(d.address, C.SERVICE_READ_PROPERTY,
                                     X.body_read_property(d.oid, C.PROP_OBJECT_NAME),
                                     timeout=2.5, retries=1)
                    name = X.parse_read_property_ack(ack.data)[3]
                    row["ms"] = int((time.time() - t0) * 1000)
                    row["status"] = "Online"
                    if not d.name:
                        d.name = str(name)
                    row["name"] = d.name
                except BACnetException:
                    pass
                pts: List[Dict[str, Any]] = []
                if with_points and row["status"] == "Online" and not self.cancel.is_set():
                    pts = self._scan_points(cl, d)
                    row["points"] = len(pts)
                    row["ok"] = sum(p["status"] in ("Online", "Out of service") for p in pts)
                    row["oos"] = sum(p["status"] == "Out of service" for p in pts)
                    row["bad"] = sum(p["status"] in ("Fault", "No response") for p in pts)
                with lock:
                    self.devices[d.instance] = row
                    self.points.extend(pts)
                    done[0] += 1
                    n = done[0]
                self._set_status(f"Checked {n} of {total} devices…", n, total)
                self._ui(self._refresh_tables)

            with ThreadPoolExecutor(max_workers=6 if not with_points else 3) as ex:
                list(ex.map(check, devs))
            self.scanned_at = time.strftime("%Y-%m-%d %H:%M:%S")
            msg = "Stopped." if self.cancel.is_set() else f"Finished at {self.scanned_at}."
            self._set_status(msg, total if not self.cancel.is_set() else -1, total)
        except Exception as e:  # never leave the dialog stuck
            self._set_status(f"Error: {e}")
        finally:
            def done_ui():
                self.running = False
                for b in (self.btn_dev, self.btn_pts):
                    b.configure(state="normal")
                self.btn_stop.configure(state="disabled")
                self._refresh_tables()
                self.app.log("info", f"Online report: {self._summary_text()}")
            self._ui(done_ui)

    def _scan_points(self, cl: BACnetClient, d: DeviceInfo) -> List[Dict[str, Any]]:
        try:
            objs = d.objects or cl.read_object_list(d)
        except BACnetException:
            return []
        objs = [o for o in objs if o.type in POINT_TYPES]
        props = [C.PROP_OBJECT_NAME, C.PROP_PRESENT_VALUE, C.PROP_STATUS_FLAGS,
                 C.PROP_RELIABILITY, C.PROP_OUT_OF_SERVICE]
        vals: Dict[ObjectId, Dict[int, Any]] = {o: {} for o in objs}
        chunk = 20 if (d.max_apdu >= 1024 or d.can_receive_segments) else 4
        k = 0
        while k < len(objs) and not self.cancel.is_set():
            part = objs[k:k + chunk]
            if d.supports_rpm is not False:
                try:
                    res = cl.read_property_multiple(d.address, [(o, [(p, None) for p in props])
                                                                for o in part])
                    for o, results in res:
                        for r in results:
                            if r.error is None:
                                vals.setdefault(o, {})[r.prop] = r.value
                    k += len(part)
                    continue
                except BACnetException as e:
                    if getattr(e, "reason", None) in (1, 4, 11) and chunk > 1:
                        chunk = max(1, chunk // 2)
                        continue
                    if not isinstance(e, BACnetError):
                        d.supports_rpm = False
            for o in part:                                  # simple devices: one by one
                for p in (C.PROP_PRESENT_VALUE, C.PROP_STATUS_FLAGS):
                    try:
                        vals[o][p] = cl.read_property(d.address, o, p, timeout=2.0)
                    except BACnetException:
                        break
            k += len(part)
        out = []
        for o in objs:
            v = vals.get(o, {})
            status = classify_point(v)
            rel = v.get(C.PROP_RELIABILITY)
            out.append({"dev": d.instance, "devname": d.name, "obj": o.short,
                        "objfull": str(o), "name": str(v.get(C.PROP_OBJECT_NAME,
                                                             d.object_names.get(o, ""))),
                        "value": X.format_value(v[C.PROP_PRESENT_VALUE], o.type, C.PROP_PRESENT_VALUE)
                        if C.PROP_PRESENT_VALUE in v else "",
                        "status": status,
                        "rel": X.format_value(rel, o.type, C.PROP_RELIABILITY) if rel is not None else ""})
        return out

    # ---- display
    def _counts(self) -> Dict[str, int]:
        devs = list(self.devices.values())
        return {
            "dev_total": len(devs),
            "dev_on": sum(d["status"] == "Online" for d in devs),
            "dev_off": sum(d["status"] == "Offline" for d in devs),
            "pt_total": len(self.points),
            "pt_on": sum(p["status"] in ("Online", "Out of service") for p in self.points),
            "pt_ok": sum(p["status"] == "Online" for p in self.points),
            "pt_oos": sum(p["status"] == "Out of service" for p in self.points),
            "pt_fault": sum(p["status"] == "Fault" for p in self.points),
            "pt_noresp": sum(p["status"] == "No response" for p in self.points),
            "pt_bad": sum(p["status"] in ("Fault", "No response") for p in self.points),
        }

    def _summary_text(self) -> str:
        c = self._counts()
        txt = f"{c['dev_on']} of {c['dev_total']} devices online"
        if self.points:
            txt += f", {c['pt_on']} of {c['pt_total']} points online"
        return txt

    def _refresh_tables(self):
        c = self._counts()
        checked = any(d["status"] != "Not checked" for d in self.devices.values())
        for k, lbl in self.cards.items():
            if k in ("dev_on", "dev_off") and not checked:
                lbl.configure(text="–")
            elif k.startswith("pt") and not self.points:
                lbl.configure(text="–")
            else:
                pct = ""
                if k == "dev_on" and c["dev_total"]:
                    pct = f"  ({100 * c['dev_on'] // c['dev_total']}%)"
                if k == "pt_on" and c["pt_total"]:
                    pct = f"  ({100 * c['pt_on'] // c['pt_total']}%)"
                lbl.configure(text=f"{c[k]}{pct}",
                              foreground="#2e7d32" if k in ("dev_on", "pt_on") else
                              ("#e53935" if k in ("dev_off", "pt_bad") and c[k] else ""))
        self.dtree.delete(*self.dtree.get_children())
        for d in sorted(self.devices.values(), key=lambda r: r["inst"]):
            tag = {"Online": "good", "Offline": "bad"}.get(d["status"], "")
            self.dtree.insert("", "end", values=tuple(d[k] for k in (
                "inst", "name", "addr", "status", "ms", "vendor", "model", "points", "ok", "oos",
                "bad")), tags=(tag,) if tag else ())
        self.ptree.delete(*self.ptree.get_children())
        for p in sorted(self.points, key=lambda r: (r["dev"], r["objfull"])):
            tag = {"Online": "good", "Fault": "bad", "No response": "bad",
                   "Out of service": "warn"}.get(p["status"], "")
            self.ptree.insert("", "end", values=(p["dev"], p["obj"], p["name"], p["value"],
                                                 p["status"], p["rel"]), tags=(tag,))

    # ---- Excel
    def export(self):
        if not self.devices:
            messagebox.showinfo(APP_NAME, "Nothing to export yet - count the devices first.",
                                parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=".xlsx",
            initialfile=f"BACnet_online_report_{datetime.date.today():%Y%m%d}.xlsx",
            filetypes=[("Excel workbook", "*.xlsx")])
        if not path:
            return
        c = self._counts()
        summ = Sheet("Summary", ["Item", "Value"], [34, 40])
        cl = self.app.client
        for k, v in (("Report", "Online devices & points"),
                     ("Generated by", f"{APP_NAME} {APP_VERSION}"),
                     ("Scan time", self.scanned_at or time.strftime("%Y-%m-%d %H:%M:%S")),
                     ("Scan type", self.scan_kind or "-"),
                     ("BACnet interface", f"{cl.local_ip}:{cl.port}" if cl else "-"),
                     ("", ""),
                     ("Devices found", c["dev_total"]), ("Devices online", c["dev_on"]),
                     ("Devices offline", c["dev_off"]),
                     ("Devices online %", round(100 * c["dev_on"] / c["dev_total"], 1)
                      if c["dev_total"] else 0)):
            summ.add([k, v], {1: "green"} if k == "Devices online" else
                     ({1: "red"} if k == "Devices offline" and v else None))
        if self.points:
            for k, v in (("", ""), ("Points", c["pt_total"]), ("Points online", c["pt_on"]),
                         ("  - normal", c["pt_ok"]), ("  - out of service", c["pt_oos"]),
                         ("Points in fault", c["pt_fault"]), ("Points not responding", c["pt_noresp"]),
                         ("Points online %", round(100 * c["pt_on"] / c["pt_total"], 1)
                          if c["pt_total"] else 0)):
                summ.add([k, v], {1: "green"} if k == "Points online" else
                         ({1: "red"} if k in ("Points in fault", "Points not responding") and v
                          else None))
        devs = Sheet("Devices", ["Instance", "Name", "Address", "Status", "Response ms", "Vendor",
                                 "Model", "Points", "Points online", "Out of service",
                                 "Fault / no response"],
                     [11, 30, 26, 12, 12, 24, 20, 9, 13, 14, 18])
        for d in sorted(self.devices.values(), key=lambda r: r["inst"]):
            devs.add([d[k] if d[k] != "" else None for k in ("inst", "name", "addr", "status", "ms",
                                                              "vendor", "model", "points", "ok",
                                                              "oos", "bad")],
                     {3: self.STATUS_FILL.get(d["status"], "grey")})
        sheets = [summ, devs]
        if self.points:
            pts = Sheet("Points", ["Device", "Device name", "Object", "Object type:instance", "Name",
                                   "Present value", "Status", "Reliability"],
                        [10, 26, 10, 22, 36, 16, 15, 22])
            for p in sorted(self.points, key=lambda r: (r["dev"], r["objfull"])):
                pts.add([p["dev"], p["devname"], p["obj"], p["objfull"], p["name"], p["value"],
                         p["status"], p["rel"]], {6: self.STATUS_FILL.get(p["status"], "grey")})
            sheets.append(pts)
        try:
            write_xlsx(path, sheets, title="BACnet online report", author=APP_NAME)
        except OSError as e:
            messagebox.showerror(APP_NAME, f"Could not save the file:\n{e}\n\n"
                                 "Is it open in Excel?", parent=self)
            return
        self.app.log("info", f"Online report exported to {path}")
        self.status.configure(text=f"Exported to {path}")
        if sys.platform.startswith("win") and messagebox.askyesno(
                APP_NAME, "Report saved. Open it now?", parent=self):
            try:
                os.startfile(path)  # type: ignore[attr-defined]
            except OSError:
                pass

    def close(self):
        self.cancel.set()
        self.destroy()


# ==========================================================================
# Trend graph
# ==========================================================================
class TrendGraph(ttk.Frame):
    def __init__(self, parent, app: "ExplorerApp"):
        super().__init__(parent)
        self.app = app
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(2, 2))
        ttk.Label(bar, text="Time span:").pack(side="left", padx=(4, 4))
        self.span = ttk.Combobox(bar, values=["1 min", "5 min", "15 min", "30 min", "60 min"],
                                 state="readonly", width=8)
        self.span.set("5 min")
        self.span.pack(side="left")
        self.span.bind("<<ComboboxSelected>>", lambda e: self.redraw())
        self.paused = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Pause", variable=self.paused).pack(side="left", padx=8)
        ttk.Button(bar, text="Clear history", command=self.clear).pack(side="left")
        ttk.Button(bar, text="Save as PostScript…", command=self.save).pack(side="left", padx=4)
        self.canvas = tk.Canvas(self, background=app.colors["canvas"], highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())

    def clear(self):
        for s in self.app.client_subs():
            s.history.clear()
        self.redraw()

    def save(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".ps",
                                            filetypes=[("PostScript", "*.ps")])
        if path:
            self.canvas.postscript(file=path, colormode="color")

    def redraw(self):
        if self.paused.get():
            return
        cv = self.canvas
        cv.delete("all")
        w, h = cv.winfo_width(), cv.winfo_height()
        if w < 50 or h < 50:
            return
        try:
            span = int(self.span.get().split()[0]) * 60
        except (ValueError, IndexError):
            span = 300
        now = time.time()
        t0 = now - span
        series = [(s, [(t, v) for t, v in s.history if t >= t0])
                  for s in self.app.client_subs() if s.graph]
        series = [(s, pts) for s, pts in series if pts]
        left, right, top, bottom = 60, 12, 12, 46 + 16 * ((len(series) + 2) // 3)
        pw, ph = w - left - right, h - top - bottom
        if pw < 20 or ph < 20:
            return
        tc = self.app.colors
        cv.create_rectangle(left, top, left + pw, top + ph, outline=tc["frame"])
        if not series:
            cv.create_text(left + pw / 2, top + ph / 2, fill=tc["muted"],
                           text="Subscribe to objects (COV or polling) to see their values here")
            return
        vals = [v for _, pts in series for _, v in pts]
        vmin, vmax = min(vals), max(vals)
        if vmax - vmin < 1e-9:
            vmin, vmax = vmin - 1, vmax + 1
        pad = (vmax - vmin) * 0.08
        vmin, vmax = vmin - pad, vmax + pad

        def X_(t):
            return left + (t - t0) / span * pw

        def Y_(v):
            return top + ph - (v - vmin) / (vmax - vmin) * ph

        for k in range(6):
            v = vmin + (vmax - vmin) * k / 5
            y = Y_(v)
            cv.create_line(left, y, left + pw, y, fill=tc["grid"])
            cv.create_text(left - 6, y, text=f"{v:.4g}", anchor="e", fill=tc["axis"],
                           font=("TkDefaultFont", 8))
        for k in range(7):
            t = t0 + span * k / 6
            x = X_(t)
            cv.create_line(x, top, x, top + ph, fill=tc["grid"])
            cv.create_text(x, top + ph + 10, text=time.strftime("%H:%M:%S", time.localtime(t)),
                           fill=tc["axis"], font=("TkDefaultFont", 8))
        for n, (s, pts) in enumerate(series):
            col = GRAPH_COLORS[(s.sub_id - 1) % len(GRAPH_COLORS)]
            coords: List[float] = []
            for i, (t, v) in enumerate(pts):
                if i > 0:  # step plot - BACnet values are held until changed
                    coords += [X_(t), Y_(pts[i - 1][1])]
                coords += [X_(t), Y_(v)]
            coords += [X_(now), Y_(pts[-1][1])]
            if len(coords) >= 4:
                cv.create_line(*coords, fill=col, width=2)
            lx = left + (n % 3) * (pw / 3)
            ly = top + ph + 30 + 16 * (n // 3)
            cv.create_rectangle(lx, ly - 5, lx + 10, ly + 5, fill=col, outline=col)
            label = f"{s.device.instance} {s.object_id.short} {s.name}"[:42]
            cv.create_text(lx + 14, ly, text=label, anchor="w", fill=tc["fg"],
                           font=("TkDefaultFont", 8))


# ==========================================================================
# Device list: names on the left, Address / MAC (red) in a synced pane
# ==========================================================================
class DeviceTree:
    """Two Treeviews scrolled, opened and selected together. ttk.Treeview cannot colour a
    single cell, so the address columns live in their own pane where every row is red."""

    def __init__(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        # names | addresses side by side in a PanedWindow: the edge between "Device" and
        # "Address" is a real divider that can be dragged (it was a fixed grid edge before)
        self.pw = ttk.PanedWindow(frame, orient="horizontal")
        self.main = ttk.Treeview(self.pw, show="tree headings", selectmode="browse")
        self.main.heading("#0", text="Device")
        self.main.column("#0", width=210, minwidth=60, stretch=True)
        self.addr = ttk.Treeview(self.pw, columns=("addr", "mac"), show="headings",
                                 selectmode="browse")
        self.addr.heading("addr", text="Address")
        self.addr.heading("mac", text="MAC")
        self.addr.column("addr", width=125, minwidth=80, stretch=False)
        self.addr.column("mac", width=105, minwidth=60, stretch=False)
        self.ys = ttk.Scrollbar(frame, orient="vertical", command=self._yview)
        self.main.configure(yscrollcommand=self._ysync(self.main))
        self.addr.configure(yscrollcommand=self._ysync(self.addr))
        self.pw.add(self.main, weight=3)
        self.pw.add(self.addr, weight=1)
        self.pw.grid(row=0, column=0, sticky="nsew")
        self.ys.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._syncing = False
        self._drag_edge = False
        self._addr_shown = True
        # dragging the right edge of the "Device" header moves the divider too
        self.main.bind("<ButtonPress-1>", self._edge_press, add="+")
        self.main.bind("<B1-Motion>", self._edge_motion, add="+")
        self.main.bind("<ButtonRelease-1>", self._edge_release, add="+")
        self.main.bind("<Motion>", self._edge_cursor, add="+")
        self.main.bind("<<TreeviewSelect>>", self._main_selected, add="+")
        self.addr.bind("<<TreeviewSelect>>", self._addr_selected, add="+")
        for ev in ("<<TreeviewOpen>>", "<<TreeviewClose>>"):
            self.main.bind(ev, lambda e: self.main.after_idle(self._sync_open), add="+")

    # ---- scrolling / selection / open-state sync
    def _yview(self, *args):
        self.main.yview(*args)
        self.addr.yview(*args)

    def _ysync(self, src):
        def f(first, last):
            self.ys.set(first, last)
            if self._syncing:
                return
            self._syncing = True
            try:
                other = self.addr if src is self.main else self.main
                other.yview_moveto(first)
            finally:
                self._syncing = False
        return f

    def _main_selected(self, event=None):
        sel = self.main.selection()
        if tuple(self.addr.selection()) != tuple(sel):
            self.addr.selection_set(sel)

    def _addr_selected(self, event=None):
        sel = self.addr.selection()
        if sel and tuple(self.main.selection()) != tuple(sel):
            self.main.selection_set(sel)
            self.main.focus(sel[0])

    def _sync_open(self):
        def walk(parent):
            for i in self.main.get_children(parent):
                if self.addr.exists(i):
                    self.addr.item(i, open=bool(self.main.item(i, "open")))
                walk(i)
        walk("")

    # ---- Treeview-like API used by the application
    def insert(self, parent, index, text="", values=(), **kw):
        iid = self.main.insert(parent, index, text=text, **kw)
        self.addr.insert(parent, index, iid=iid, values=tuple(values) + ("",) * (2 - len(values)),
                         open=bool(kw.get("open", False)), tags=("addr",))
        return iid

    def item(self, iid, option=None, **kw):
        if "values" in kw:
            v = tuple(kw.pop("values"))
            self.addr.item(iid, values=v + ("",) * (2 - len(v)))
        if "open" in kw:
            self.addr.item(iid, open=kw["open"])
        if option is not None:
            return self.main.item(iid, option)
        if kw:
            return self.main.item(iid, **kw)
        return self.main.item(iid)

    def set(self, iid, column=None, value=None):
        if value is None:
            return self.addr.set(iid, column)
        return self.addr.set(iid, column, value)

    def move(self, iid, parent, index):
        self.main.move(iid, parent, index)
        self.addr.move(iid, parent, index)

    def delete(self, *iids):
        self.main.delete(*iids)
        self.addr.delete(*iids)

    def selection_set(self, *items):
        self.main.selection_set(*items)
        self.addr.selection_set(*items)

    def see(self, iid):
        self.main.see(iid)
        self.addr.see(iid)

    def bind(self, sequence, func, add=None):
        self.main.bind(sequence, func, add)
        if sequence.startswith("<Button") or sequence.startswith("<Control-Button"):
            self.addr.bind(sequence, func, add)

    def _near_edge(self, event) -> bool:
        if self.main.identify_region(event.x, event.y) != "heading" and event.y > 26:
            return False
        return self.main.winfo_width() - event.x <= 8

    def _edge_cursor(self, event):
        self.main.configure(cursor="sb_h_double_arrow" if self._near_edge(event) else "")

    def _edge_press(self, event):
        if self._addr_shown and self._near_edge(event):
            self._drag_edge = True
            return "break"
        return None

    def _edge_motion(self, event):
        if self._drag_edge:
            try:
                self.pw.sashpos(0, max(60, event.x))
            except tk.TclError:
                pass
            return "break"
        return None

    def _edge_release(self, event):
        if self._drag_edge:
            self._drag_edge = False
            return "break"
        return None

    def show_columns(self, addr: bool, mac: bool):
        """Hide the Address and/or MAC column; hide the whole pane when both are off."""
        cols = [c for c, on in (("addr", addr), ("mac", mac)) if on]
        panes = [str(p) for p in self.pw.panes()]
        if cols:
            self.addr.configure(displaycolumns=cols)
            self.addr.column("addr", width=125)
            if str(self.addr) not in panes:
                self.pw.add(self.addr, weight=1)
            self._addr_shown = True
            w = self.pw.winfo_width()
            if w > 150:   # give the address pane just the width its columns need
                need = (125 if addr else 0) + (105 if mac else 0) + 4
                self.pw.after_idle(lambda: self._safe_sash(max(60, w - need)))
        else:
            if str(self.addr) in panes:
                self.pw.forget(self.addr)
            self._addr_shown = False

    def _safe_sash(self, x: int):
        try:
            self.pw.sashpos(0, x)
        except tk.TclError:
            pass

    def owns(self, widget) -> bool:
        return widget is self.main or widget is self.addr

    def __getattr__(self, name):          # exists, parent, get_children, selection, identify_row…
        return getattr(self.main, name)


# ==========================================================================
# Main application
# ==========================================================================
class ExplorerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.client: Optional[BACnetClient] = None
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ui-worker")
        self.ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self.dev_nodes: Dict[str, int] = {}        # tree iid -> device instance
        self.dev_iid: Dict[int, str] = {}
        self.net_iid: Dict[str, str] = {}
        self.obj_nodes: Dict[str, ObjectId] = {}   # address-space iid -> object id
        self.prop_rows: Dict[str, X.PropertyResult] = {}
        self.current_dev: Optional[DeviceInfo] = None
        self.current_obj: Optional[ObjectId] = None
        self.current_props: Dict[int, Any] = {}
        self.units_cache: Dict[tuple, Any] = {}
        self.busy = 0
        self._load_token = 0
        self._prop_refreshing = False
        self._prop_refreshed = 0.0
        self.theme = self.settings.get("theme", "light") if self.settings.get("theme") in THEMES \
            else "light"
        self._flash: Dict[int, float] = {}          # subscription id -> flash end time
        self._flash_labels: Dict[int, tk.Label] = {}
        self._last_sub_val: Dict[int, str] = {}

        root.title(f"{APP_NAME} {APP_VERSION}")
        self.show_addr_var = tk.BooleanVar(master=root, value=self.settings.get("show_address", True))
        self.show_mac_var = tk.BooleanVar(master=root, value=self.settings.get("show_mac", True))
        self._load_logo()
        self.auth = Auth(self.settings)
        self._normal_geom = ""
        self._restore_geometry()
        self._setup_style()
        self._make_icons()
        self._build_menu()
        self._build_header()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()
        self.apply_theme(self.theme, save=False)
        root.protocol("WM_DELETE_WINDOW", self.on_exit)
        root.after(50, self._process_queue)
        root.after(1000, self._tick)
        self.log("info", f"{APP_NAME} {APP_VERSION} ready. Use 'Start' to open a BACnet/IP channel.")

    # ------------------------------------------------------------------ look & feel
    def _setup_style(self):
        self.style = ttk.Style(self.root)
        self.native_theme = next((t for t in ("vista", "aqua") if t in self.style.theme_names()),
                                 "clam")

    @property
    def dark(self) -> bool:
        return self.theme == "dark"

    @property
    def colors(self) -> Dict[str, str]:
        return THEMES[self.theme]

    def toggle_theme(self):
        self.apply_theme("light" if self.dark else "dark")

    def apply_theme(self, mode: str, save: bool = True):
        """Switch the whole window between the light and dark view."""
        self.theme = mode if mode in THEMES else "light"
        c = self.colors
        st = self.style
        # light: the native Windows look; dark: 'clam' (the only theme that takes custom colours)
        st.theme_use("clam" if self.dark else self.native_theme)
        if self.dark or self.native_theme == "clam":
            st.configure(".", background=c["bg"], foreground=c["fg"], fieldbackground=c["entry"],
                         bordercolor=c["border"], lightcolor=c["bg"], darkcolor=c["bg"],
                         troughcolor=c["panel"], selectbackground=c["select"],
                         selectforeground=c["select_fg"], insertcolor=c["fg"], arrowcolor=c["fg"],
                         focuscolor=c["select"])
            st.map(".", background=[("disabled", c["bg"]), ("active", c["button_active"])],
                   foreground=[("disabled", c["muted"])])
            st.configure("TButton", background=c["button"], foreground=c["fg"],
                         bordercolor=c["border"])
            st.map("TButton", background=[("pressed", c["select"]), ("active", c["button_active"])])
            st.configure("TEntry", fieldbackground=c["entry"], foreground=c["fg"])
            st.configure("TCombobox", fieldbackground=c["entry"], foreground=c["fg"],
                         background=c["button"])
            st.map("TCombobox", fieldbackground=[("readonly", c["entry"])],
                   foreground=[("readonly", c["fg"])], selectbackground=[("readonly", c["entry"])],
                   selectforeground=[("readonly", c["fg"])])
            st.configure("TSpinbox", fieldbackground=c["entry"], foreground=c["fg"],
                         background=c["button"])
            st.configure("TNotebook", background=c["bg"], bordercolor=c["border"])
            st.configure("TNotebook.Tab", background=c["button"], foreground=c["fg"],
                         padding=(10, 3))
            st.map("TNotebook.Tab", background=[("selected", c["panel"])],
                   foreground=[("selected", c["fg"])])
            st.configure("TLabelframe", background=c["bg"], bordercolor=c["border"])
            st.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
            for w in ("TCheckbutton", "TRadiobutton"):
                st.configure(w, background=c["bg"], foreground=c["fg"],
                             indicatorbackground=c["entry"], indicatorforeground=c["fg"],
                             upperbordercolor=c["border"], lowerbordercolor=c["border"])
                st.map(w, indicatorbackground=[("selected", c["accent"]), ("pressed", c["select"]),
                                               ("!selected", c["entry"])],
                       indicatorforeground=[("selected", "#ffffff")],
                       background=[("active", c["bg"])])
            st.configure("TScrollbar", background=c["button"], troughcolor=c["panel"],
                         bordercolor=c["border"], arrowcolor=c["fg"])
            st.configure("TProgressbar", background=c["accent"], troughcolor=c["panel"])
            st.configure("TPanedwindow", background=c["bg"])
            st.configure("Sash", background=c["border"])
            st.configure("Treeview", background=c["panel"], fieldbackground=c["panel"],
                         foreground=c["fg"], bordercolor=c["border"])
            st.map("Treeview", background=[("selected", c["select"])],
                   foreground=[("selected", c["select_fg"])])
            st.configure("Treeview.Heading", background=c["heading"], foreground=c["fg"],
                         bordercolor=c["border"])
            st.map("Treeview.Heading", background=[("active", c["button_active"])])
        st.configure("Treeview", rowheight=22)
        st.configure("Hint.TLabel", foreground=c["muted"])
        st.configure("Bold.TLabel", font=("TkDefaultFont", 10, "bold"))
        st.configure("Accent.TButton")
        st.configure("Toolbar.TButton", padding=(8, 3))
        st.configure("Status.TLabel", padding=(6, 2))
        st.configure("Header.TFrame", background=c["header"])
        st.configure("Header.TLabel", background=c["header"], foreground=c["fg"])
        st.configure("Brand.TLabel", background=c["header"], foreground=c["fg"],
                     font=("Segoe UI", 15, "bold"))
        st.configure("Sub.TLabel", background=c["header"], foreground=c["muted"],
                     font=("Segoe UI", 9))
        st.configure("Header.TButton", padding=(8, 3))
        # classic Tk widgets and pop-up menus
        self.root.configure(background=c["bg"])
        for opt, val in (("*Menu.background", c["panel"]), ("*Menu.foreground", c["fg"]),
                         ("*Menu.activeBackground", c["select"]),
                         ("*Menu.activeForeground", c["select_fg"]),
                         ("*TCombobox*Listbox.background", c["entry"]),
                         ("*TCombobox*Listbox.foreground", c["fg"]),
                         ("*TCombobox*Listbox.selectBackground", c["select"]),
                         ("*TCombobox*Listbox.selectForeground", c["select_fg"]),
                         ("*Toplevel.background", c["bg"])):
            self.root.option_add(opt, val)
        self._apply_widget_theme()
        self._windows_title_bar()
        if save:
            self.settings["theme"] = self.theme
            self.save()

    def _apply_widget_theme(self):
        c = self.colors
        if hasattr(self, "theme_btn"):
            self.theme_btn.configure(text="☀  Light view" if self.dark else "☾  Dark view")
            self.theme_var.set(self.theme)
        if hasattr(self, "menubar"):
            try:
                self.menubar.configure(background=c["panel"], foreground=c["fg"])
            except tk.TclError:
                pass
        if hasattr(self, "log_text"):
            self.log_text.configure(background=c["panel"], foreground=c["fg"],
                                    insertbackground=c["fg"], selectbackground=c["select"])
            for lvl, col in (LOG_COLORS_DARK if self.dark else LOG_COLORS).items():
                self.log_text.tag_configure(lvl, foreground=col)
        if hasattr(self, "prop_tree"):
            self._setup_property_styles()
            self.prop_tree.tag_configure("error", foreground=c["muted"])
        if hasattr(self, "dev_tree"):
            self.dev_tree.addr.tag_configure("addr", foreground=c["addr"])
        if hasattr(self, "sub_tree"):
            self.sub_tree.tag_configure("alarm", foreground="#ff6b6b" if self.dark else "#c62828")
            self.sub_tree.tag_configure("hidden", foreground=c["muted"])
        if hasattr(self, "obj_tree"):
            fl = self.FLASH_COLORS["dark" if self.dark else "light"]
            self.obj_tree.tag_configure("goto_a", background=fl[0][0], foreground=fl[0][1])
            self.obj_tree.tag_configure("goto_b", background=fl[1][0], foreground=fl[1][1])
        if hasattr(self, "graph"):
            self.graph.canvas.configure(background=c["canvas"])
            self.graph.redraw()
        if hasattr(self, "graphics"):
            self.graphics.apply_theme()

    def _windows_title_bar(self):
        """Dark window title bar on Windows 10 (20H1+) / 11."""
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())  # type: ignore[attr-defined]
            val = ctypes.c_int(1 if self.dark else 0)
            for attr in (20, 19):          # DWMWA_USE_IMMERSIVE_DARK_MODE (new / old builds)
                if ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
                        hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                    break
        except Exception:
            pass

    def _load_logo(self):
        """Window / taskbar icon and the logo images used in the toolbar and About box."""
        self.logo_toolbar: Optional[tk.PhotoImage] = None
        self.logo_about: Optional[tk.PhotoImage] = None
        self.logo_header: Optional[tk.PhotoImage] = None
        ico = os.path.join(ASSETS, "logo.ico")
        try:
            if sys.platform.startswith("win") and os.path.exists(ico):
                self.root.iconbitmap(default=ico)
            imgs = [tk.PhotoImage(master=self.root, file=os.path.join(ASSETS, n))
                    for n in ("logo_256.png", "logo_64.png", "logo_32.png")
                    if os.path.exists(os.path.join(ASSETS, n))]
            if imgs:
                self.root.iconphoto(True, *imgs)
                self._logo_refs = imgs
            if os.path.exists(os.path.join(ASSETS, "logo_toolbar.png")):
                self.logo_toolbar = tk.PhotoImage(master=self.root,
                                                  file=os.path.join(ASSETS, "logo_toolbar.png"))
            if os.path.exists(os.path.join(ASSETS, "logo_header.png")):
                self.logo_header = tk.PhotoImage(master=self.root,
                                                 file=os.path.join(ASSETS, "logo_header.png"))
            if os.path.exists(os.path.join(ASSETS, "logo_about.png")):
                self.logo_about = tk.PhotoImage(master=self.root,
                                                file=os.path.join(ASSETS, "logo_about.png"))
        except tk.TclError as e:
            print(f"logo: {e}")

    def _show_graphics(self):
        self.top_nb.select(self.graphics)

    def toggle_full_view(self):
        """Give the Graphics tab the whole window (hide device panes and bottom tabs)."""
        main, left, right, nb = self._panes
        self.full_view = not self.full_view
        if self.full_view:
            self._show_graphics()
            main.forget(left)
            right.forget(nb)
        else:
            if self.devices_visible:
                main.insert(0, left, weight=1)
            right.add(nb, weight=2)
        self.graphics.full_btn.configure(text="Exit full view" if self.full_view else "Full view")

    def _make_icons(self):
        r = self.root
        self.icons = {
            "net": make_icon(r, "#7b4fa3", "network"),
            "folder": make_icon(r, "#e0b030", "folder"),
            "device": make_icon(r, "#455a64", "device"),
            "device_off": make_icon(r, "#b0bec5", "device"),
            "analog": make_icon(r, "#1e88e5", "circle"),
            "binary": make_icon(r, "#43a047", "square"),
            "multistate": make_icon(r, "#fb8c00", "diamond"),
            "other": make_icon(r, "#8d6e63", "triangle"),
            "prop": make_icon(r, "#90a4ae", "square", 10),
            "error": make_icon(r, "#e53935", "circle", 10),
        }

    def _icon_for(self, oid: ObjectId) -> tk.PhotoImage:
        fam = C.object_family(oid.type)
        return self.icons.get(fam if fam != "device" else "device", self.icons["other"])

    # ------------------------------------------------------------------ menus
    def _build_menu(self):
        m = tk.Menu(self.root)
        self.menubar = m
        f = tk.Menu(m, tearoff=False)
        f.add_command(label="Start BACnet/IP channel…", command=self.start_channel, accelerator="F2")
        f.add_command(label="Stop channel", command=self.stop_channel)
        f.add_separator()
        f.add_command(label="Export device points to CSV…", command=self.export_csv)
        f.add_command(label="Save log…", command=self.save_log)
        f.add_separator()
        f.add_command(label="Restart software", command=self.restart_app, accelerator="Ctrl+Shift+R")
        f.add_command(label="Change password…", command=self.change_password)
        self.autologin_var = tk.BooleanVar(master=self.root, value=self.auth.autologin_ok())
        f.add_checkbutton(label="Auto login on this computer", variable=self.autologin_var,
                          command=self._autologin_changed)
        f.add_command(label="Log out", command=self.log_out)
        f.add_separator()
        f.add_command(label="Exit", command=self.on_exit)
        m.add_cascade(label="File", menu=f)

        fn = tk.Menu(m, tearoff=False)
        fn.add_command(label="Who-Is (discover)", command=self.quick_whois, accelerator="F5")
        fn.add_command(label="Who-Is with options…", command=self.whois_dialog)
        fn.add_command(label="Add device by IP…", command=self.add_device)
        fn.add_command(label="Who-Has object…", command=self.who_has)
        fn.add_separator()
        fn.add_command(label="Read property…", command=self.read_property_dialog)
        fn.add_command(label="Write property…", command=self.write_selected, accelerator="F4")
        qp = tk.Menu(fn, tearoff=False)
        self.inline_prio_var = tk.IntVar(master=self.root, value=int(self.settings.get(
            "inline_priority", 8)) if str(self.settings.get("inline_priority", 8)).isdigit() else 8)
        for k in range(1, 17):
            qp.add_radiobutton(label=f"{k} - {C.PRIORITY_NAMES[k - 1]}", value=k,
                               variable=self.inline_prio_var, command=self._inline_prio_changed)
        fn.add_cascade(label="Double-click write priority", menu=qp)
        fn.add_command(label="Subscribe / monitor selected objects…", command=self.subscribe_selected,
                       accelerator="F6")
        fn.add_separator()
        fn.add_command(label="Time synchronization (broadcast)", command=lambda: self.time_sync(False, None))
        fn.add_command(label="UTC time synchronization (broadcast)", command=lambda: self.time_sync(True, None))
        m.add_cascade(label="Functions", menu=fn)

        tl = tk.Menu(m, tearoff=False)
        tl.add_command(label="Network adapter settings (IP / mask / gateway)…",
                       command=self.network_settings, accelerator="F8")
        tl.add_command(label="Online devices & points report…", command=self.online_report)
        tl.add_separator()
        tl.add_command(label="Graphics: new page…", command=lambda: (self._show_graphics(),
                                                                      self.graphics.new_page()))
        tl.add_command(label="Show graphics", command=self._show_graphics, accelerator="F9")
        m.add_cascade(label="Tools", menu=tl)

        v = tk.Menu(m, tearoff=False)
        self.trace_var = tk.BooleanVar(value=False)
        self.debug_var = tk.BooleanVar(value=self.settings.get("debug_log", False))
        v.add_checkbutton(label="Show debug messages", variable=self.debug_var)
        v.add_checkbutton(label="Packet trace (hex)", variable=self.trace_var,
                          command=self._toggle_trace)
        v.add_separator()
        self.devices_var = tk.BooleanVar(master=self.root, value=True)
        v.add_checkbutton(label="Devices panel", variable=self.devices_var,
                          command=lambda: self.toggle_devices(self.devices_var.get()),
                          accelerator="Ctrl+B")
        v.add_command(label="Reset window layout", command=self.reset_layout)
        v.add_checkbutton(label="Device Address column", variable=self.show_addr_var,
                          command=self._device_columns_changed)
        v.add_checkbutton(label="Device MAC column", variable=self.show_mac_var,
                          command=self._device_columns_changed)
        v.add_separator()
        self.theme_var = tk.StringVar(value=self.theme)
        v.add_radiobutton(label="Light view", value="light", variable=self.theme_var,
                          command=lambda: self.apply_theme("light"))
        v.add_radiobutton(label="Dark view", value="dark", variable=self.theme_var,
                          command=lambda: self.apply_theme("dark"), accelerator="Ctrl+D")
        v.add_separator()
        v.add_command(label="Clear log", command=lambda: self.log_text.delete("1.0", "end"))
        v.add_command(label="Expand all devices", command=lambda: self._expand_all(True))
        v.add_command(label="Collapse all devices", command=lambda: self._expand_all(False))
        m.add_cascade(label="View", menu=v)

        h = tk.Menu(m, tearoff=False)
        h.add_command(label="Quick help", command=self.show_help)
        h.add_command(label="About", command=self.show_about)
        m.add_cascade(label="Help", menu=h)
        self.root.config(menu=m)
        self.root.bind("<F2>", lambda e: self.start_channel())
        self.root.bind("<F5>", lambda e: self.quick_whois())
        self.root.bind("<F4>", lambda e: self.write_selected())
        self.root.bind("<F6>", lambda e: self.subscribe_selected())
        self.root.bind("<F8>", lambda e: self.network_settings())
        self.root.bind("<F9>", lambda e: self._show_graphics())
        self.root.bind("<F11>", lambda e: self.toggle_full_view())
        self.root.bind("<Control-b>", lambda e: self.toggle_devices())
        self.root.bind("<Control-B>", lambda e: self.toggle_devices())
        self.root.bind("<Control-Shift-R>", lambda e: self.restart_app())
        self.root.bind("<Control-d>", lambda e: self.toggle_theme())
        self.root.bind("<Control-D>", lambda e: self.toggle_theme())

    def _build_header(self):
        """Brand bar at the top of the main window: logo, name, theme switch."""
        hb = ttk.Frame(self.root, style="Header.TFrame", padding=(10, 6))
        hb.pack(side="top", fill="x")
        if self.logo_header is not None:
            ttk.Label(hb, image=self.logo_header, style="Header.TLabel").pack(side="left",
                                                                              padx=(0, 10))
        names = ttk.Frame(hb, style="Header.TFrame")
        names.pack(side="left")
        ttk.Label(names, text=APP_NAME, style="Brand.TLabel").pack(anchor="w")
        ttk.Label(names, text=f"BACnet/IP discovery & commissioning  ·  version {APP_VERSION}",
                  style="Sub.TLabel").pack(anchor="w")
        self.theme_btn = ttk.Button(hb, text="☾  Dark view", command=self.toggle_theme,
                                    style="Header.TButton")
        self.theme_btn.pack(side="right")
        ttk.Separator(self.root, orient="horizontal").pack(side="top", fill="x")

    def _build_toolbar(self):
        tb = ttk.Frame(self.root, padding=(4, 4))
        tb.pack(side="top", fill="x")
        self.dev_btn = ttk.Button(tb, text="◂ Devices", command=self.toggle_devices,
                                  style="Toolbar.TButton")
        self.dev_btn.pack(side="left", padx=(1, 4))
        buttons = [
            ("▶ Start", self.start_channel), ("■ Stop", self.stop_channel), None,
            ("Discover", self.quick_whois), ("Who-Is…", self.whois_dialog),
            ("＋ Add device", self.add_device), None,
            ("⟳ Refresh", self.refresh_selected), ("✎ Write", self.write_selected),
            ("◉ Subscribe", self.subscribe_selected), None,
            ("Time sync", lambda: self.time_sync(False, None)),
            ("⇩ Export CSV", self.export_csv), None,
            ("Laptop IP…", self.network_settings),
            ("Graphics", self._show_graphics),
            ("Online report", self.online_report),
        ]
        for b in buttons:
            if b is None:
                ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
            else:
                ttk.Button(tb, text=b[0], command=b[1], style="Toolbar.TButton").pack(
                    side="left", padx=1)
        self.chan_label = ttk.Label(tb, text="● Offline", foreground="#c62828")
        self.auto_var = tk.BooleanVar(value=self.settings.get("auto_refresh", True))
        self.interval_box = ttk.Combobox(tb, values=["1 s", "2 s", "5 s", "10 s"], width=5,
                                         state="readonly")
        self.interval_box.set(f"{int(self.settings.get('refresh_interval', 1))} s")
        self.interval_box.bind("<<ComboboxSelected>>", lambda e: self._refresh_settings_changed())
        self.chan_label.pack(side="right", padx=8)
        self.interval_box.pack(side="right")
        ttk.Checkbutton(tb, text="Auto refresh every", variable=self.auto_var,
                        command=self._refresh_settings_changed).pack(side="right", padx=(12, 4))

    def _build_body(self):
        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        # ---- left: devices + address space
        left = ttk.PanedWindow(main, orient="vertical")
        main.add(left, weight=1)
        devf = ttk.LabelFrame(left, text="Devices", padding=2)
        cbar = ttk.Frame(devf)
        cbar.pack(fill="x")
        ttk.Label(cbar, text="Show:", style="Hint.TLabel").pack(side="left", padx=(2, 4))
        ttk.Checkbutton(cbar, text="Address", variable=self.show_addr_var,
                        command=self._device_columns_changed).pack(side="left")
        ttk.Checkbutton(cbar, text="MAC", variable=self.show_mac_var,
                        command=self._device_columns_changed).pack(side="left", padx=(6, 0))
        ttk.Button(cbar, text="◂ Hide panel", command=lambda: self.toggle_devices(False)).pack(
            side="right")
        self.dev_tree = DeviceTree(devf)
        self.dev_tree.show_columns(self.show_addr_var.get(), self.show_mac_var.get())
        left.add(devf, weight=1)

        objf = ttk.LabelFrame(left, text="Address space", padding=2)
        filt = ttk.Frame(objf)
        filt.pack(fill="x")
        ttk.Label(filt, text="Filter:").pack(side="left", padx=(2, 4))
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._populate_objects())
        ttk.Entry(filt, textvariable=self.filter_var).pack(side="left", fill="x", expand=True)
        self.group_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(filt, text="Group", variable=self.group_var,
                        command=self._populate_objects).pack(side="left", padx=4)
        self.obj_tree = ttk.Treeview(objf, show="tree", selectmode="extended")
        self.obj_tree.column("#0", width=380)
        self._with_scroll(objf, self.obj_tree)
        left.add(objf, weight=2)

        # ---- right: properties + bottom notebook
        right = ttk.PanedWindow(main, orient="vertical")
        main.add(right, weight=3)
        self.top_nb = ttk.Notebook(right)
        right.add(self.top_nb, weight=3)
        propf = ttk.Frame(self.top_nb, padding=2)
        self.top_nb.add(propf, text="Properties")
        self.prop_title = ttk.Label(propf, text="Select an object", style="Bold.TLabel")
        self.prop_title.pack(fill="x", padx=4, pady=(0, 2))
        self.prop_tree = ttk.Treeview(propf, columns=("value", "type"), show="tree headings",
                                      selectmode="browse")
        self.prop_tree.heading("#0", text="Property")
        self.prop_tree.heading("value", text="Value")
        self.prop_tree.heading("type", text="Type")
        self.prop_tree.column("#0", width=230, stretch=False)
        self.prop_tree.column("value", width=480)
        self.prop_tree.column("type", width=110, stretch=False)
        self.prop_tree.tag_configure("error", foreground="#9e9e9e")
        self._setup_property_styles()
        self._with_scroll(propf, self.prop_tree)
        self.graphics = GraphicsPanel(self.top_nb, self)
        self.top_nb.add(self.graphics, text="Graphics")

        nb = ttk.Notebook(right)
        right.add(nb, weight=2)
        self._panes = (main, left, right, nb)
        self.full_view = False
        self.devices_visible = True
        self.notebook = nb

        subf = ttk.Frame(nb)
        cols = ("device", "object", "name", "value", "flags", "time", "mode", "state")
        self.sub_tree = ttk.Treeview(subf, columns=cols, show="headings", selectmode="extended")
        widths = (70, 130, 200, 120, 120, 80, 60, 140)
        for c, w in zip(cols, widths):
            self.sub_tree.heading(c, text=c.capitalize())
            self.sub_tree.column(c, width=w, stretch=c in ("name", "state"))
        self.sub_tree.tag_configure("alarm", foreground="#c62828")
        self.sub_tree.tag_configure("hidden", foreground="#9e9e9e")
        self._with_scroll(subf, self.sub_tree)
        nb.add(subf, text="Subscriptions")

        self.graph = TrendGraph(nb, self)
        nb.add(self.graph, text="Trend graph")

        logf = ttk.Frame(nb)
        self.log_text = tk.Text(logf, height=8, wrap="none", font=("Consolas", 9)
                                if sys.platform.startswith("win") else ("Courier", 10))
        for lvl, col in LOG_COLORS.items():
            self.log_text.tag_configure(lvl, foreground=col)
        self._with_scroll(logf, self.log_text, horizontal=True)
        nb.add(logf, text="Log")

        # bindings
        self.dev_tree.bind("<<TreeviewSelect>>", self.on_device_select)
        self.dev_tree.bind("<Button-3>", self.on_device_menu)
        self.dev_tree.bind("<Button-2>" if sys.platform == "darwin" else "<Control-Button-1>",
                           self.on_device_menu)
        self.obj_tree.bind("<<TreeviewSelect>>", self.on_object_select)
        self.obj_tree.bind("<Button-3>", self.on_object_menu)
        self.obj_tree.bind("<Return>", lambda e: self.subscribe_selected())
        self.obj_tree.bind("<ButtonPress-1>", self._drag_start, add="+")
        self.obj_tree.bind("<B1-Motion>", self._drag_motion, add="+")
        self.obj_tree.bind("<ButtonRelease-1>", self._drag_end, add="+")
        self.prop_tree.bind("<Double-1>", lambda e: self.write_selected())
        self.prop_tree.bind("<Button-3>", self.on_prop_menu)
        self.sub_tree.bind("<Button-3>", self.on_sub_menu)
        self.sub_tree.bind("<Delete>", lambda e: self.remove_subscriptions())
        self.sub_tree.bind("<Double-1>", self.on_sub_double)

    def _with_scroll(self, parent, widget, horizontal: bool = False):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        ys = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        widget.configure(yscrollcommand=ys.set)
        widget.grid(row=0, column=0, sticky="nsew", in_=frame)
        ys.grid(row=0, column=1, sticky="ns")
        if horizontal:
            xs = ttk.Scrollbar(frame, orient="horizontal", command=widget.xview)
            widget.configure(xscrollcommand=xs.set)
            xs.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        widget.lift(frame)

    def _build_statusbar(self):
        sb = ttk.Frame(self.root)
        sb.pack(side="bottom", fill="x")
        self.status = ttk.Label(sb, text="Ready", style="Status.TLabel", anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(sb, length=180, mode="determinate")
        self.progress.pack(side="right", padx=6, pady=2)
        self.dev_count = ttk.Label(sb, text="0 devices", style="Status.TLabel")
        self.dev_count.pack(side="right")

    # ------------------------------------------------------------------ infrastructure
    def ui(self, fn: Callable[[], None]):
        """Run fn on the Tk thread (safe to call from any thread)."""
        self.ui_queue.put(fn)

    def _process_queue(self):
        try:
            for _ in range(500):
                fn = self.ui_queue.get_nowait()
                try:
                    fn()
                except Exception as e:  # keep the UI alive
                    self._append_log("error", f"UI error: {e!r}")
        except queue.Empty:
            pass
        self.root.after(50, self._process_queue)

    def bg(self, work: Callable[[], Any], done: Optional[Callable[[Any], Any]] = None,
           what: str = "", quiet_errors: bool = True):
        """Run blocking network work in a worker thread; deliver result on the UI thread."""
        self.busy += 1
        self._set_status(what + "…" if what else "Working…")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        def runner():
            try:
                res = work()
                err = None
            except Exception as e:  # noqa
                res, err = None, e

            def finish():
                self.busy -= 1
                if self.busy <= 0:
                    self.busy = 0
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                if err is not None:
                    self.log("error", f"{what or 'Operation'} failed: {err}")
                    self._set_status(f"{what or 'Operation'} failed: {err}")
                    if not quiet_errors:
                        messagebox.showerror(APP_NAME, f"{what} failed:\n{err}", parent=self.root)
                else:
                    if self.busy == 0:
                        self._set_status("Ready")
                    if done:
                        done(res)
            self.ui(finish)
        self.pool.submit(runner)

    def progress_cb(self, label: str):
        def cb(i: int, n: int):
            def upd():
                self.progress.stop()
                self.progress.configure(mode="determinate", maximum=max(n, 1), value=i)
                self._set_status(f"{label} {i}/{n}")
            self.ui(upd)
        return cb

    def _set_status(self, text: str):
        self.status.configure(text=text)

    def log(self, level: str, msg: str):
        if level == "debug" and not self.debug_var.get():
            return
        self.ui(lambda: self._append_log(level, msg))

    def _append_log(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert("end", f"{ts}  {level.upper():<7} {msg}\n", level)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 5000:
            self.log_text.delete("1.0", f"{lines - 4000}.0")
        self.log_text.see("end")

    def require_client(self) -> Optional[BACnetClient]:
        if self.client is None or not self.client.running:
            if messagebox.askyesno(APP_NAME, "No BACnet/IP channel is open.\nOpen one now?",
                                   parent=self.root):
                self.start_channel()
        return self.client if self.client and self.client.running else None

    def client_subs(self) -> List[Subscription]:
        return list(self.client.subscriptions.values()) if self.client else []

    def refresh_interval(self) -> float:
        try:
            return float(self.interval_box.get().split()[0])
        except (ValueError, IndexError):
            return 1.0

    def _refresh_settings_changed(self):
        self.settings["auto_refresh"] = bool(self.auto_var.get())
        self.settings["refresh_interval"] = self.refresh_interval()
        self.save()
        if self.client:
            self.client.auto_refresh = bool(self.auto_var.get())
            self.client.refresh_interval = self.refresh_interval()
        self._set_status("Auto refresh " + (f"every {self.refresh_interval():g} s"
                                            if self.auto_var.get() else "off"))

    def _auto_refresh_properties(self):
        """Re-read the displayed object and update the grid in place."""
        dev, oid, cl = self.current_dev, self.current_obj, self.client
        if not (self.auto_var.get() and dev and oid is not None and cl and cl.running):
            return
        if self._prop_refreshing or self.busy:
            return
        if time.time() - self._prop_refreshed < self.refresh_interval() - 0.05:
            return
        self._prop_refreshing = True

        def work():
            try:
                if dev.supports_rpm is False:  # keep simple devices light: dynamic props only
                    res = []
                    for p in (C.PROP_PRESENT_VALUE, C.PROP_STATUS_FLAGS, C.PROP_EVENT_STATE,
                              C.PROP_OUT_OF_SERVICE, C.PROP_RELIABILITY):
                        if p in self.current_props:
                            try:
                                res.append(X.PropertyResult(p, None, cl.read_property(dev.address, oid, p,
                                                                                       timeout=2.0)))
                            except BACnetException:
                                pass
                else:
                    res = cl.read_all_properties(dev, oid)
            except Exception:
                res = None

            def done():
                self._prop_refreshing = False
                self._prop_refreshed = time.time()
                if res and self.current_obj == oid and self.current_dev is dev:
                    self._update_properties_inplace(oid, res)
            self.ui(done)
        self.pool.submit(work)

    def _update_properties_inplace(self, oid: ObjectId, results: List[X.PropertyResult]):
        rows = {(r.prop, r.index): iid for iid, r in self.prop_rows.items()}
        partial = len(results) < len(rows) / 2
        shown = {(r.prop, r.index) for r in results if not (r.error and r.error[1] == 32)}
        if not partial and shown != set(rows):
            sel = self.prop_tree.selection()
            keep = self.prop_rows[sel[0]].prop if sel and sel[0] in self.prop_rows else None
            self._fill_properties(oid, results, keep)
            return
        units = self.current_props.get(C.PROP_UNITS)
        tree = self.prop_tree
        for r in results:
            iid = rows.get((r.prop, r.index))
            if iid is None or r.error is not None:
                continue
            self.prop_rows[iid] = r
            self.current_props[r.prop] = r.value
            val = self._prop_display(oid, r, units)
            if tree.set(iid, "value") != val:
                tree.set(iid, "value", val)
            if r.prop in (C.PROP_RELIABILITY,):
                tree.item(iid, tags=self._row_tags(r.prop, r.value))
            kids = tree.get_children(iid)
            if r.prop == C.PROP_PRIORITY_ARRAY and isinstance(r.value, list) and len(kids) == len(r.value):
                self._priority_rows(iid, oid, r.value, units, create=False)
            elif isinstance(r.value, list) and len(kids) == len(r.value):
                sub_prop = C.PROP_PRESENT_VALUE if r.prop == C.PROP_PRIORITY_ARRAY else r.prop
                for kid, item in zip(kids, r.value):
                    v = X.format_value(item, oid.type, sub_prop)
                    if tree.set(kid, "value") != v:
                        tree.set(kid, "value", v)

    def _tick(self):
        try:
            self._flash_tick()
            self._auto_refresh_properties()
            self.graph.redraw()
            if self.client:
                now = time.time()
                for s in self.client.subscriptions.values():
                    if str(s.sub_id) in self.sub_tree.get_children():
                        age = int(now - s.last_update) if s.last_update else None
                        self.sub_tree.set(str(s.sub_id), "time",
                                          time.strftime("%H:%M:%S", time.localtime(s.last_update))
                                          if age is not None else "-")
        finally:
            self.root.after(250, self._tick)

    # ------------------------------------------------------------------ channel
    def start_channel(self, force: bool = False):
        if self.client and self.client.running:
            if not force and not messagebox.askyesno(APP_NAME, "A channel is already open. Restart it?",
                                                     parent=self.root):
                return
            self.stop_channel()
        cfg = ChannelDialog(self.root, self.settings).show()
        if not cfg:
            return
        self.settings.update(cfg)
        save_settings(self.settings)
        cl = BACnetClient(cfg["local_ip"], cfg["port"], cfg["broadcast"], cfg["timeout"],
                          cfg["retries"])
        cl.remote_port = cfg["remote_port"]
        cl.on_log = self.log
        cl.on_device = lambda d, new: self.ui(lambda: self._device_seen(d, new))
        cl.on_subscription = lambda s: self.ui(lambda: self._update_sub_row(s))
        cl.on_i_have = lambda ih, a: self.ui(lambda: self._set_status(
            f"I-Have: device {ih.device} has {ih.object_id} '{ih.object_name}'"))
        cl.trace_packets = self.trace_var.get()
        cl.auto_refresh = bool(self.auto_var.get())
        cl.refresh_interval = self.refresh_interval()
        try:
            cl.start()
        except BACnetException as e:
            messagebox.showerror(APP_NAME, str(e), parent=self.root)
            return
        self.client = cl
        addr = f"{cfg['local_ip']}:{cl.port}"
        self.chan_label.configure(text=f"● Online  {addr}", foreground="#2e7d32")
        if cfg["use_bbmd"]:
            cl.register_foreign_device(cfg["bbmd_ip"], cfg["bbmd_port"], cfg["ttl"])
        if cfg["discover_on_start"]:
            self.root.after(300 if cfg["use_bbmd"] else 50, self.quick_whois)

    def stop_channel(self):
        if not self.client:
            return
        cl = self.client
        self.client = None
        self.pool.submit(cl.stop)
        self.chan_label.configure(text="● Offline", foreground="#c62828")
        self.sub_tree.delete(*self.sub_tree.get_children())

    def _toggle_trace(self):
        if self.client:
            self.client.trace_packets = self.trace_var.get()
        if self.trace_var.get():
            self.notebook.select(2)

    # ------------------------------------------------------------------ discovery
    def quick_whois(self):
        cl = self.require_client()
        if not cl:
            return
        tgt = self.settings.get("whois_target_tuple")
        try:
            cl.who_is(target=tuple(tgt) if tgt else None,
                      global_broadcast=self.settings.get("whois_global", True))
            self._set_status("Who-Is sent - waiting for I-Am replies")
        except OSError as e:
            self.log("error", f"Who-Is failed: {e}")

    def whois_dialog(self):
        cl = self.require_client()
        if not cl:
            return
        res = WhoIsDialog(self.root, self.settings).show()
        if not res:
            return
        lo, hi, t = res["raw"]
        self.settings.update({"whois_low": lo, "whois_high": hi, "whois_target": t,
                              "whois_global": res["global"],
                              "whois_target_tuple": list(res["target"]) if res["target"] else None})
        save_settings(self.settings)
        try:
            cl.who_is(res["low"], res["high"], res["target"], res["global"])
        except OSError as e:
            self.log("error", f"Who-Is failed: {e}")

    def add_device(self):
        cl = self.require_client()
        if not cl:
            return
        res = AddDeviceDialog(self.root).show()
        if not res:
            return
        ip, port, net, mac = res
        self.bg(lambda: cl.add_device_manual(ip, port, net, mac),
                lambda d: self._select_device(d.instance), f"Contacting {ip}:{port}",
                quiet_errors=False)

    def who_has(self):
        cl = self.require_client()
        if not cl:
            return
        txt = simpledialog.askstring("Who-Has", "Object name, or object id (e.g. analog-input:1):",
                                     parent=self.root)
        if not txt:
            return
        try:
            oid = ObjectId.parse(txt) if ":" in txt and txt.split(":")[-1].strip().isdigit() else None
        except ValueError:
            oid = None
        cl.who_has(None if oid else txt, oid)

    def _network_key(self, d: DeviceInfo) -> str:
        if d.address.net is not None:
            return f"Network {d.address.net}  (via {d.address.ip}:{d.address.port})"
        return "BACnet/IP"

    def _device_seen(self, d: DeviceInfo, new: bool):
        key = self._network_key(d)
        if key not in self.net_iid:
            self.net_iid[key] = self.dev_tree.insert("", "end", text=key, open=True,
                                                     image=self.icons["net"])
        parent = self.net_iid[key]
        label = self._device_label(d)
        addr, mac = self._addr_mac(d)
        iid = self.dev_iid.get(d.instance)
        if iid and self.dev_tree.exists(iid):
            if self.dev_tree.parent(iid) != parent:
                self.dev_tree.move(iid, parent, "end")
            self.dev_tree.item(iid, text=label, values=(addr, mac))
        else:
            # keep devices sorted by instance within each network
            siblings = self.dev_tree.get_children(parent)
            pos = "end"
            for k, s in enumerate(siblings):
                if self.dev_nodes.get(s, 1 << 30) > d.instance:
                    pos = k
                    break
            iid = self.dev_tree.insert(parent, pos, text=label, values=(addr, mac),
                                       image=self.icons["device"])
            self.dev_nodes[iid] = d.instance
            self.dev_iid[d.instance] = iid
            if self.client and not d.name:
                cl = self.client
                self.pool.submit(self._fetch_name, cl, d)
        self.dev_count.configure(text=f"{len(self.dev_iid)} devices")

    def _device_columns_changed(self):
        a, m = bool(self.show_addr_var.get()), bool(self.show_mac_var.get())
        self.dev_tree.show_columns(a, m)
        self.settings["show_address"], self.settings["show_mac"] = a, m
        self.save()

    @staticmethod
    def _addr_mac(d: DeviceInfo):
        """(Address, MAC) columns. BACnet/IP MAC = 4-byte IP + 2-byte port, shown in hex;
        MS/TP and other routed devices show their own MAC (decimal if one byte)."""
        a = d.address
        if a.net is None:
            try:
                raw = bytes(int(x) for x in a.ip.split(".")) + a.port.to_bytes(2, "big")
                mac = raw.hex().upper()
                mac = "-".join(mac[k:k + 2] for k in range(0, 12, 2))
            except ValueError:
                mac = ""
            return f"{a.ip}:{a.port}", mac
        m = a.mac[0] if len(a.mac) == 1 else a.mac.hex().upper()
        return f"{a.net} via {a.ip}", str(m)

    def _fetch_name(self, cl: BACnetClient, d: DeviceInfo):
        try:
            cl.read_device_info(d)
            self.ui(lambda: self._device_seen(d, False))
        except BACnetException as e:
            self.log("debug", f"Device {d.instance} name: {e}")

    def _device_label(self, d: DeviceInfo) -> str:
        return f"{d.name}  [{d.instance}]" if d.name else f"Device {d.instance}"

    def _select_device(self, instance: int):
        iid = self.dev_iid.get(instance)
        if iid:
            self.dev_tree.selection_set(iid)
            self.dev_tree.see(iid)

    def _expand_all(self, open_: bool):
        for n in self.dev_tree.get_children():
            self.dev_tree.item(n, open=open_)

    # ------------------------------------------------------------------ address space
    def selected_device(self) -> Optional[DeviceInfo]:
        sel = self.dev_tree.selection()
        if not sel or not self.client:
            return None
        inst = self.dev_nodes.get(sel[0])
        return self.client.devices.get(inst) if inst is not None else None

    def on_device_select(self, event=None):
        dev = self.selected_device()
        if dev is None:
            return
        self.current_dev = dev
        self.current_obj = None
        if dev.objects:
            self._populate_objects()
            self._show_object(dev.oid)
        else:
            self.load_address_space(dev)

    def load_address_space(self, dev: DeviceInfo):
        cl = self.client
        if not cl:
            return
        self._load_token += 1
        token = self._load_token
        self.obj_tree.delete(*self.obj_tree.get_children())
        self.obj_nodes.clear()

        def work():
            if not dev.name:
                try:
                    cl.read_device_info(dev)
                except BACnetException:
                    pass
            objs = cl.read_object_list(dev, self.progress_cb("Reading object list"))
            cl.read_object_names(dev, objs, self.progress_cb("Reading object names"))
            return objs

        def done(objs):
            self._device_seen(dev, False)
            self.log("info", f"Device {dev.instance}: {len(objs)} objects")
            if token == self._load_token and self.current_dev is dev:
                self._populate_objects()
                self._show_object(dev.oid)
        self.bg(work, done, f"Loading device {dev.instance}")

    def _populate_objects(self):
        dev = self.current_dev
        tree = self.obj_tree
        tree.delete(*tree.get_children())
        self.obj_nodes.clear()
        if dev is None:
            return
        flt = self.filter_var.get().strip().lower()
        objs = sorted(dev.objects, key=lambda o: (o.type != C.OBJ_DEVICE, o.type, o.instance))
        groups: Dict[int, str] = {}
        shown = 0
        for o in objs:
            name = dev.object_names.get(o, "")
            text = f"{o.short}  {name}" if name else str(o)
            if flt and flt not in text.lower() and flt not in str(o).lower():
                continue
            parent = ""
            if self.group_var.get() and o.type != C.OBJ_DEVICE:
                if o.type not in groups:
                    groups[o.type] = tree.insert("", "end", text=C.object_type_name(o.type),
                                                 image=self.icons["folder"], open=bool(flt))
                parent = groups[o.type]
            iid = tree.insert(parent, "end", text=text, image=self._icon_for(o))
            self.obj_nodes[iid] = o
            shown += 1
        for t, g in groups.items():
            n = len(tree.get_children(g))
            tree.item(g, text=f"{C.object_type_name(t)}  ({n})")
        self._set_status(f"Device {dev.instance}: {shown} of {len(objs)} objects shown")
        if getattr(self, "_pending_goto", None):
            self.root.after_idle(self._finish_goto)

    def selected_objects(self) -> List[ObjectId]:
        out = []
        for iid in self.obj_tree.selection():
            if iid in self.obj_nodes:
                out.append(self.obj_nodes[iid])
            else:  # a group folder - take its children
                out += [self.obj_nodes[c] for c in self.obj_tree.get_children(iid)
                        if c in self.obj_nodes]
        return out

    def on_object_select(self, event=None):
        if getattr(self, "_goto_selecting", False):    # properties are already shown
            self._goto_selecting = False
            return
        sel = self.obj_tree.selection()
        if len(sel) == 1 and sel[0] in self.obj_nodes:
            self._show_object(self.obj_nodes[sel[0]])

    # ------------------------------------------------------------------ properties
    def _show_object(self, oid: ObjectId, keep_selection: Optional[int] = None):
        dev, cl = self.current_dev, self.client
        if dev is None or cl is None:
            return
        self.current_obj = oid
        name = dev.object_names.get(oid, dev.name if oid == dev.oid else "")
        self.prop_title.configure(text=f"{oid}   {name}   —   device {dev.instance}")
        self._load_token += 1
        token = self._load_token

        def done(results: List[X.PropertyResult]):
            if token != self._load_token or self.current_obj != oid:
                return
            self._fill_properties(oid, results, keep_selection)
        self.bg(lambda: cl.read_all_properties(dev, oid), done, f"Reading {oid}")

    def _fill_properties(self, oid: ObjectId, results: List[X.PropertyResult],
                         keep_selection: Optional[int] = None):
        tree = self.prop_tree
        tree.delete(*tree.get_children())
        self.prop_rows.clear()
        self.current_props = {}
        hide_unknown = True
        order = {75: 0, 77: 1, 79: 2, 85: 3}
        results = sorted(results, key=lambda r: (order.get(r.prop, 10), C.property_name(r.prop)
                                                 if r.prop < 512 else f"~{r.prop:06d}"))
        units = next((r.value for r in results if r.prop == C.PROP_UNITS and r.error is None), None)
        for r in results:
            if r.error is not None:
                if hide_unknown and r.error[1] == 32:
                    continue
                txt = f"{C.ERROR_CLASS.get(r.error[0], r.error[0])}: " \
                      f"{C.ERROR_CODE.get(r.error[1], r.error[1])}" if r.error[0] >= 0 else "no response"
                iid = tree.insert("", "end", text=C.property_name(r.prop), values=(txt, "error"),
                                  image=self.icons["error"], tags=("error",))
            else:
                self.current_props[r.prop] = r.value
                val = self._prop_display(oid, r, units)
                is_pa = r.prop == C.PROP_PRIORITY_ARRAY and isinstance(r.value, list)
                iid = tree.insert("", "end", text=C.property_name(r.prop) +
                                  (f"[{r.index}]" if r.index is not None else ""),
                                  values=(val, f"Array[{len(r.value)}]" if is_pa
                                          else X.type_name_of(r.value)),
                                  image=self.icons["prop"], open=is_pa,
                                  tags=("pa_head",) if is_pa else self._row_tags(r.prop, r.value))
                if is_pa:
                    self._priority_rows(iid, oid, r.value, units, create=True)
                elif isinstance(r.value, list) and 0 < len(r.value) <= 512 and \
                        r.prop not in (C.PROP_PROPERTY_LIST,):
                    for k, item in enumerate(r.value):
                        sub_prop = C.PROP_PRESENT_VALUE if r.prop == C.PROP_PRIORITY_ARRAY else r.prop
                        tree.insert(iid, "end", text=f"[{k + 1}]",
                                    values=(X.format_value(item, oid.type, sub_prop),
                                            X.type_name_of(item)))
            self.prop_rows[iid] = r
        if self.current_dev:
            self.units_cache[(self.current_dev.instance, oid)] = units
            nm = self.current_props.get(C.PROP_OBJECT_NAME)
            if nm is not None:
                self.current_dev.object_names[oid] = str(nm)
        if keep_selection is not None:
            for iid, r in self.prop_rows.items():
                if r.prop == keep_selection:
                    tree.selection_set(iid)
                    tree.see(iid)
        self._set_status(f"{oid}: {len(self.prop_rows)} properties")

    # ---- property grid styling ------------------------------------------------
    PROP_COLORS = {
        "light": {
            "pv": ("#0d47a1", "#e3f2fd"),       # present value - bold blue on light blue
            "maxpv": ("#d84315", ""),           # max-pres-value - deep orange
            "minpv": ("#00838f", ""),           # min-pres-value - teal
            "oid": ("#6a1b9a", ""),             # object-identifier - purple
            "polarity": ("#ad1457", ""),        # polarity - magenta
            "rel_ok": ("#2e7d32", ""),          # reliability: no fault - green
            "rel_bad": ("#c62828", "#ffebee"),  # reliability: any fault - red
            "pa_empty": ("#5f6b73", ""), "pa_set": ("#1565c0", ""),
            "pa_active": ("#1b5e20", "#e8f5e9"),
        },
        "dark": {
            "pv": ("#90caf9", "#13324d"), "maxpv": ("#ffab91", ""), "minpv": ("#80deea", ""),
            "oid": ("#ce93d8", ""), "polarity": ("#f48fb1", ""), "rel_ok": ("#a5d6a7", ""),
            "rel_bad": ("#ef9a9a", "#4a1f24"), "pa_empty": ("#8a979f", ""),
            "pa_set": ("#90caf9", ""), "pa_active": ("#a5d6a7", "#1f3a24"),
        },
    }

    def _setup_property_styles(self):
        tree = self.prop_tree
        bold: Any = ("TkDefaultFont", 9, "bold")
        big: Any = ("TkDefaultFont", 10, "bold")
        try:
            import tkinter.font as tkfont
            base = tkfont.nametofont("TkDefaultFont")
            size = int(base.cget("size"))
            bold = base.copy()
            bold.configure(weight="bold")
            big = base.copy()
            big.configure(weight="bold", size=size + 1 if size > 0 else size - 1)
            self._prop_fonts = (bold, big)   # keep references alive
        except Exception:
            pass
        pal = self.PROP_COLORS["dark" if self.dark else "light"]
        panel = self.colors["panel"]
        for tag in ("pv", "maxpv", "minpv", "oid", "polarity", "rel_ok", "rel_bad", "pa_empty",
                    "pa_set", "pa_active"):
            fg, bg = pal[tag]
            font = big if tag == "pv" else (None if tag == "pa_empty" else bold)
            kw: Dict[str, Any] = {"foreground": fg, "background": bg or panel}
            if font is not None:
                kw["font"] = font
            tree.tag_configure(tag, **kw)
        tree.tag_configure("pa_head", font=bold)

    def _row_tags(self, prop: int, value: Any) -> tuple:
        if prop == C.PROP_PRESENT_VALUE:
            return ("pv",)
        if prop == 65:   # max-pres-value
            return ("maxpv",)
        if prop == 69:   # min-pres-value
            return ("minpv",)
        if prop == C.PROP_OBJECT_IDENTIFIER:
            return ("oid",)
        if prop == 84:   # polarity
            return ("polarity",)
        if prop == C.PROP_RELIABILITY:
            try:
                return ("rel_ok",) if int(value) == 0 else ("rel_bad",)
            except (TypeError, ValueError):
                return ("rel_ok",)
        return ()

    def _pv_text(self, oid: ObjectId, value: Any, units: Any) -> str:
        txt = X.format_value(value, oid.type, C.PROP_PRESENT_VALUE)
        if units is not None and not isinstance(value, X.Null):
            txt += units_suffix(units)
        return txt

    def _prop_display(self, oid: ObjectId, r: X.PropertyResult, units: Any) -> str:
        if r.prop == C.PROP_PRIORITY_ARRAY and isinstance(r.value, list):
            for k, v in enumerate(r.value):
                if not isinstance(v, X.Null):
                    name = C.PRIORITY_NAMES[k] if k < 16 else f"Level {k + 1}"
                    return f"In control: {k + 1} - {name} = {self._pv_text(oid, v, units)}"
            return "All levels released (NULL) - Relinquish Default in control"
        if r.prop in (C.PROP_PRESENT_VALUE, 65, 69, C.PROP_RELINQUISH_DEFAULT, 22, 25, 45, 59, 106):
            if units is not None and isinstance(r.value, (int, float)) and not isinstance(r.value, bool) \
                    and oid.type in C.ANALOG_TYPES:
                return X.format_value(r.value, oid.type, r.prop) + units_suffix(units)
        return X.format_value(r.value, oid.type, r.prop)

    def _priority_rows(self, parent: str, oid: ObjectId, values: List[Any], units: Any,
                       create: bool):
        """Priority array children, named like the BACnet standard (YABE style)."""
        tree = self.prop_tree
        active = next((k for k, v in enumerate(values) if not isinstance(v, X.Null)), None)
        kids = tree.get_children(parent)
        for k, v in enumerate(values):
            empty = isinstance(v, X.Null)
            txt = "" if empty else self._pv_text(oid, v, units)
            tag = "pa_empty" if empty else ("pa_active" if k == active else "pa_set")
            name = C.PRIORITY_NAMES[k] if k < 16 else f"Level {k + 1}"
            if k == active:
                txt += "    ◀ in control"
            if create:
                tree.insert(parent, "end", text=f"{name}", values=(txt, f"Priority {k + 1}"),
                            tags=(tag,))
            elif k < len(kids):
                if tree.set(kids[k], "value") != txt:
                    tree.set(kids[k], "value", txt)
                tree.item(kids[k], tags=(tag,))

    def refresh_selected(self):
        focus = self.root.focus_get()
        if self.dev_tree.owns(focus):
            dev = self.selected_device()
            if dev:
                dev.objects = []
                dev.object_names.clear()
                self.load_address_space(dev)
            return
        if self.current_obj is not None:
            self._show_object(self.current_obj)
        elif self.selected_device():
            self.on_device_select()

    # ------------------------------------------------------------------ write
    def write_selected(self):
        cl = self.client
        dev, oid = self.current_dev, self.current_obj
        if cl is None or dev is None or oid is None:
            messagebox.showinfo(APP_NAME, "Select an object and a property first.", parent=self.root)
            return
        sel = self.prop_tree.selection()
        prop, idx, current = C.PROP_PRESENT_VALUE, None, self.current_props.get(C.PROP_PRESENT_VALUE)
        if sel:
            iid = sel[0]
            parent = self.prop_tree.parent(iid)
            row = self.prop_rows.get(parent or iid)
            if row is None:
                return
            prop = row.prop
            current = row.value
            if parent:  # array element
                idx = self.prop_tree.index(iid) + 1
                if isinstance(row.value, list) and idx <= len(row.value):
                    current = row.value[idx - 1]
            if prop == C.PROP_PRIORITY_ARRAY:
                # writing a priority slot means commanding the present value at that priority
                pv = self.current_props.get(C.PROP_PRESENT_VALUE)
                slot = current if parent and not isinstance(current, X.Null) else pv
                res = WriteDialog(self.root, oid, C.PROP_PRESENT_VALUE, slot, None, True,
                                  priority=idx).show()
                if res:
                    value, prio, _ = res
                    self._do_write(dev, oid, C.PROP_PRESENT_VALUE, value, prio or idx, None)
                return
        state_text = self.current_props.get(C.PROP_STATE_TEXT)
        st = [str(s) for s in state_text] if isinstance(state_text, list) else None
        commandable = C.PROP_PRIORITY_ARRAY in self.current_props
        res = WriteDialog(self.root, oid, prop, current, st, commandable, idx).show()
        if res:
            value, prio, index = res
            self._do_write(dev, oid, prop, value, prio, index)

    def _do_write(self, dev: DeviceInfo, oid: ObjectId, prop: int, value: Any,
                  prio: Optional[int], index: Optional[int]):
        cl = self.client
        if not cl:
            return

        def done(_):
            self._set_status(f"Write {oid} {C.property_name(prop)} OK")
            if self.current_obj == oid:
                self._show_object(oid, keep_selection=prop)

        self.bg(lambda: cl.write_property(dev.address, oid, prop, value, prio, index), done,
                f"Writing {oid} {C.property_name(prop)}", quiet_errors=False)

    # ------------------------------------------------------------------ manual read
    def read_property_dialog(self):
        cl = self.require_client()
        dev = self.current_dev
        if not cl:
            return
        if dev is None:
            messagebox.showinfo(APP_NAME, "Select a device first.", parent=self.root)
            return
        res = ReadPropertyDialog(self.root, self.current_obj).show()
        if not res:
            return
        oid, prop, idx = res

        def done(v):
            txt = X.format_value(v, oid.type, prop)
            self.log("info", f"ReadProperty {oid} {C.property_name(prop)}"
                             f"{f'[{idx}]' if idx is not None else ''} = {txt}")
            messagebox.showinfo("Read property", f"{oid}\n{C.property_name(prop)}"
                                f"{f'[{idx}]' if idx is not None else ''}\n\n{txt[:2000]}",
                                parent=self.root)
        self.bg(lambda: cl.read_property(dev.address, oid, prop, idx), done,
                "Reading property", quiet_errors=False)

    # ------------------------------------------------------------------ subscriptions
    def subscribe_selected(self):
        cl = self.client
        dev = self.current_dev
        objs = self.selected_objects()
        if not objs and self.current_obj is not None:
            objs = [self.current_obj]
        if cl is None or dev is None or not objs:
            messagebox.showinfo(APP_NAME, "Select one or more objects in the address space.",
                                parent=self.root)
            return
        objs = [o for o in objs if o.type != C.OBJ_DEVICE]
        if not objs:
            return
        opts = SubscribeDialog(self.root, self.settings, len(objs)).show()
        if not opts:
            return
        self.settings.update(opts)
        save_settings(self.settings)
        self.notebook.select(0)
        for o in objs:
            name = dev.object_names.get(o, "")
            self._subscribe_one(cl, dev, o, name, opts)

    def _subscribe_one(self, cl: BACnetClient, dev: DeviceInfo, oid: ObjectId, name: str,
                       opts: Dict[str, Any]):
        def work():
            if (dev.instance, oid) not in self.units_cache and oid.type in C.ANALOG_TYPES:
                try:
                    self.units_cache[(dev.instance, oid)] = cl.read_property(dev.address, oid,
                                                                             C.PROP_UNITS)
                except BACnetException:
                    self.units_cache[(dev.instance, oid)] = None
            sub = cl.add_subscription(dev, oid, opts["sub_confirmed"], opts["sub_lifetime"],
                                      opts["sub_fallback"], opts["poll_interval"],
                                      force_poll=opts["sub_mode"] == "poll", name=name)
            if sub.mode == "poll":
                sub.next_poll = 0
            return sub
        self.bg(work, lambda s: self._update_sub_row(s), f"Subscribing {oid}")

    def _update_sub_row(self, s: Subscription):
        if not self.client or s.sub_id not in self.client.subscriptions:
            return
        iid = str(s.sub_id)
        units = self.units_cache.get((s.device.instance, s.object_id))
        val = "-" if s.value is None else \
            X.format_value(s.value, s.object_id.type, C.PROP_PRESENT_VALUE) + units_suffix(units)
        flags = "-"
        alarm = False
        if isinstance(s.status_flags, X.BitString):
            on = [C.STATUS_FLAGS_BITS[i] for i, b in enumerate(s.status_flags.bits[:4]) if b]
            flags = ", ".join(on) if on else "normal"
            alarm = bool(on)
        values = (s.device.instance, s.object_id.short, s.name, val, flags,
                  time.strftime("%H:%M:%S", time.localtime(s.last_update)) if s.last_update else "-",
                  s.mode.upper() + ("" if s.mode == "poll" else (" C" if s.confirmed else " U")),
                  s.state)
        tags = self._sub_tags(s)
        prev = self._last_sub_val.get(s.sub_id)
        self._last_sub_val[s.sub_id] = val
        if prev is not None and prev != "-" and prev != val:
            self._flash[s.sub_id] = time.time() + 3.0       # value changed: flash for 3 s
        if self.sub_tree.exists(iid):
            self.sub_tree.item(iid, values=values, tags=tags)
        else:
            self.sub_tree.insert("", "end", iid=iid, values=values, tags=tags)
        if s.sub_id in self._flash:
            self._flash_draw(s.sub_id)

    @staticmethod
    def _sub_tags(s: Subscription) -> tuple:
        alarm = isinstance(s.status_flags, X.BitString) and any(s.status_flags.bits[:4])
        return ("alarm",) if alarm else (() if s.graph else ("hidden",))

    # ---- flashing present value (only the Value cell, not the whole row) --------------
    FLASH_COLORS = {"light": (("#ffd600", "#000000"), ("#fff59d", "#5d4037")),
                    "dark": (("#c9a400", "#000000"), ("#4d4100", "#ffe082"))}

    def _flash_draw(self, sid: int):
        """Place / update a blinking label exactly over the Value cell of this row.
        (ttk.Treeview can only colour whole rows, so the cell is covered by a Label.)"""
        iid = str(sid)
        lbl = self._flash_labels.get(sid)
        try:
            bbox = self.sub_tree.bbox(iid, "value") if self.sub_tree.exists(iid) else ""
        except tk.TclError:
            bbox = ""
        if not bbox:                       # row scrolled out of view / tab hidden
            if lbl is not None:
                lbl.place_forget()
            return
        x, y, w, h = bbox
        if lbl is None:
            lbl = tk.Label(self.sub_tree, anchor="w", padx=4, borderwidth=0,
                           font=("TkDefaultFont", 9, "bold"))
            lbl.bind("<Button-1>", lambda e, i=iid: (self.sub_tree.selection_set(i),
                                                     self.sub_tree.focus(i)))
            lbl.bind("<Double-1>", lambda e, i=iid: (self.sub_tree.selection_set(i),
                                                     self.on_sub_double(None, "value")))
            lbl.bind("<Button-3>", lambda e, i=iid: (self.sub_tree.selection_set(i),
                                                     self.on_sub_menu(e)))
            self._flash_labels[sid] = lbl
        on = int(time.time() * 4) % 2 == 0          # blink twice a second
        bg, fg = self.FLASH_COLORS["dark" if self.dark else "light"][0 if on else 1]
        lbl.configure(text=self.sub_tree.set(iid, "value"), background=bg, foreground=fg)
        lbl.place(x=x, y=y, width=w, height=h)

    def _flash_stop(self, sid: int):
        self._flash.pop(sid, None)
        lbl = self._flash_labels.pop(sid, None)
        if lbl is not None:
            try:
                lbl.destroy()
            except tk.TclError:
                pass

    def _flash_tick(self):
        """Blink the Value cell of subscriptions whose present value changed < 3 s ago."""
        if not self._flash:
            return
        now = time.time()
        for sid, until in list(self._flash.items()):
            if not self.client or sid not in self.client.subscriptions \
                    or not self.sub_tree.exists(str(sid)) or now >= until:
                self._flash_stop(sid)
            else:
                self._flash_draw(sid)

    def selected_subs(self) -> List[Subscription]:
        if not self.client:
            return []
        return [self.client.subscriptions[int(i)] for i in self.sub_tree.selection()
                if int(i) in self.client.subscriptions]

    def remove_subscriptions(self):
        cl = self.client
        subs = self.selected_subs()
        if not cl or not subs:
            return
        for s in subs:
            self._flash_stop(s.sub_id)
            self.sub_tree.delete(str(s.sub_id))
            self.pool.submit(cl.remove_subscription, s.sub_id)

    def toggle_graph(self):
        for s in self.selected_subs():
            s.graph = not s.graph
            self._update_sub_row(s)
        self.graph.redraw()

    def on_sub_double(self, event, column: Optional[str] = None):
        """Double-click: Value column -> write in place; any other column -> go to the point."""
        if event is not None and column is None:
            iid = self.sub_tree.identify_row(event.y)
            if iid:
                self.sub_tree.selection_set(iid)
            col = self.sub_tree.identify_column(event.x)
            try:
                column = self.sub_tree["columns"][int(col[1:]) - 1] if col.startswith("#") \
                    and col != "#0" else None
            except (ValueError, IndexError):
                column = None
        subs = self.selected_subs()
        if not subs or not self.client:
            return
        s = subs[0]
        if column == "value":
            self.inline_write(self.sub_tree, str(s.sub_id), "value", s.device, s.object_id, s.value)
            return "break"
        self.goto_object(s.device.instance, s.object_id)
        return "break"

    # ---- go to a point in the address space and highlight it for 3 s ----------------
    def goto_object(self, inst: int, oid: ObjectId):
        cl = self.client
        dev = cl.devices.get(inst) if cl else None
        if dev is None:
            self._set_status(f"Device {inst} is not in the device list (not discovered yet)")
            return
        if self.full_view:
            self.toggle_full_view()
        if not self.devices_visible:
            self.toggle_devices(True)
        self.top_nb.select(0)                      # Properties tab
        self._pending_goto = (inst, oid)
        if self.current_dev is dev and dev.objects and self.obj_nodes:
            self._finish_goto()
            return
        iid = self.dev_iid.get(inst)
        if iid:
            self.dev_tree.selection_set(iid)
            self.dev_tree.see(iid)
        self.current_dev = dev
        self.current_obj = None
        if dev.objects:
            self._populate_objects()               # calls _finish_goto at the end
        else:
            self.load_address_space(dev)           # _finish_goto runs when loading is done

    def _finish_goto(self):
        pend = getattr(self, "_pending_goto", None)
        if not pend or self.current_dev is None or self.current_dev.instance != pend[0]:
            return
        oid = pend[1]
        target = next((i for i, o in self.obj_nodes.items() if o == oid), None)
        if target is None and self.filter_var.get():
            self.filter_var.set("")               # the filter hid it - clear and retry
            return
        self._pending_goto = None
        if target is None:
            self._set_status(f"{oid} is not in the object list of device {pend[0]}")
            return
        parent = self.obj_tree.parent(target)
        if parent:
            self.obj_tree.item(parent, open=True)
        # don't select yet: the blue selection colour would hide the yellow highlight
        self.obj_tree.selection_set(())
        self.obj_tree.focus(target)
        self.obj_tree.see(target)
        self._show_object(oid)
        self._highlight_until = time.time() + 3.0
        self._highlight_iid = target
        self._highlight_tick()

    def _highlight_tick(self):
        iid = getattr(self, "_highlight_iid", None)
        if not iid or not self.obj_tree.exists(iid):
            return
        tags = [t for t in self.obj_tree.item(iid, "tags") if t not in ("goto_a", "goto_b")]
        if time.time() < self._highlight_until:
            tags.append("goto_a" if int(time.time() * 4) % 2 == 0 else "goto_b")
            self.obj_tree.item(iid, tags=tags)
            self.root.after(125, self._highlight_tick)
        else:
            self.obj_tree.item(iid, tags=tags)
            self._highlight_iid = None
            if not self.obj_tree.selection():
                self._goto_selecting = True
                self.obj_tree.selection_set(iid)       # now mark it as the selected point

    # ---- write a value in place (double-click on a Value cell) -----------------------
    def inline_write(self, tree: ttk.Treeview, iid: str, column: str, dev: DeviceInfo,
                     oid: ObjectId, current: Any):
        if self.client is None or not self.client.running:
            messagebox.showinfo(APP_NAME, "Open a BACnet/IP channel first.", parent=self.root)
            return
        try:
            bbox = tree.bbox(iid, column)
        except tk.TclError:
            bbox = ""
        if not bbox:
            return
        old = getattr(self, "_inline_editor", None)
        if old is not None:
            try:
                old.destroy()
            except tk.TclError:
                pass
        x, y, w, h = bbox
        st = self.units_cache.get((dev.instance, oid, "st"))
        choices: List[str] = []
        if oid.type in C.BINARY_TYPES:
            choices = ["0 - inactive", "1 - active"]
        elif oid.type in C.MULTISTATE_TYPES:
            n = len(st) if st else 4
            choices = [f"{k + 1} - {st[k]}" if st else str(k + 1) for k in range(n)]
        if current is None or isinstance(current, X.Null):
            text = ""
        elif oid.type in C.BINARY_TYPES or oid.type in C.MULTISTATE_TYPES:
            try:
                n = int(current)
                text = next((c for c in choices if c.split(" ")[0] == str(n)), str(n))
            except (TypeError, ValueError):
                text = str(current)
        elif isinstance(current, float):
            text = f"{current:.6g}"
        else:
            text = X.format_plain(current)
        prio = self.inline_priority()
        if choices:
            ed: Any = ttk.Combobox(tree, values=choices + ["NULL (relinquish)"])
            ed.set(text)
        else:
            ed = ttk.Entry(tree)
            ed.insert(0, text)
        ed.place(x=x, y=y, width=max(w, 130), height=h)
        self._inline_editor = ed
        ed.focus_set()
        try:
            ed.select_range(0, "end")
        except tk.TclError:
            pass
        self._set_status(f"Type the new value of {oid} and press Enter (Esc = cancel)"
                         + (f" - priority {prio}" if oid.type in C.COMMANDABLE_TYPES else ""))
        done = {"v": False}

        def close():
            if not done["v"]:
                done["v"] = True
                try:
                    ed.destroy()
                except tk.TclError:
                    pass
                self._inline_editor = None

        def commit(event=None):
            if done["v"]:
                return "break"
            txt = ed.get().strip()
            close()
            if not txt:
                return "break"
            try:
                value = self._parse_inline(oid, txt, current)
            except ValueError as e:
                messagebox.showerror("Invalid value", str(e), parent=self.root)
                return "break"
            p = prio if oid.type in C.COMMANDABLE_TYPES else None
            self._do_write(dev, oid, C.PROP_PRESENT_VALUE, value, p, None)
            return "break"

        ed.bind("<Return>", commit)
        ed.bind("<KP_Enter>", commit)
        ed.bind("<Escape>", lambda e: (close(), "break")[1])
        if choices:
            ed.bind("<<ComboboxSelected>>", commit)
        ed.bind("<FocusOut>", lambda e: self.root.after(150, lambda: (
            None if done["v"] or str(self.root.focus_get() or "").startswith(str(ed)) else close())))

    @staticmethod
    def _parse_inline(oid: ObjectId, txt: str, current: Any) -> Any:
        low = txt.lower()
        if low.startswith("null") or low.startswith("relinquish"):
            return X.NULL
        first = txt.split(" - ")[0].strip()
        if oid.type in C.BINARY_TYPES:
            if low in ("active", "on", "true", "1", "1 - active"):
                return X.Enumerated(1)
            if low in ("inactive", "off", "false", "0", "0 - inactive"):
                return X.Enumerated(0)
            raise ValueError("Enter active / inactive (or 1 / 0)")
        if oid.type in C.MULTISTATE_TYPES:
            try:
                n = int(first)
            except ValueError:
                raise ValueError("Enter the state number (1, 2, 3 ...)")
            if n < 1:
                raise ValueError("Multi-state values start at 1")
            return X.Unsigned(n)
        num = re.match(r"^\s*([-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)", txt)
        if oid.type in C.ANALOG_TYPES:
            if not num:
                raise ValueError("Enter a number")
            return X.Real(float(num.group(1).replace(",", ".")))
        if oid.type == 45:      # integer-value
            return X.Signed(int(float(num.group(1)))) if num else X.Signed(int(txt))
        if oid.type == 48:      # positive-integer-value
            return X.Unsigned(int(float(num.group(1)))) if num else X.Unsigned(int(txt))
        if oid.type == 40:      # characterstring-value
            return X.CharacterString(txt)
        tn = X.type_name_of(current)
        if tn in X.WRITABLE_TYPES and tn != "Null":
            return X.parse_user_value(txt, tn)
        if num:
            return X.Real(float(num.group(1).replace(",", ".")))
        return X.CharacterString(txt)

    def _inline_prio_changed(self):
        self.settings["inline_priority"] = int(self.inline_prio_var.get())
        self.save()

    def inline_priority(self) -> int:
        try:
            return max(1, min(16, int(self.settings.get("inline_priority", 8))))
        except (TypeError, ValueError):
            return 8

    # ------------------------------------------------------------------ device functions
    def time_sync(self, utc: bool, dev: Optional[DeviceInfo]):
        cl = self.require_client()
        if not cl:
            return
        try:
            cl.time_sync(dev.address if dev else None, utc)
            self._set_status(f"{'UTC ' if utc else ''}time synchronization sent")
        except OSError as e:
            self.log("error", f"Time sync failed: {e}")

    def reinitialize(self, dev: DeviceInfo, state: int):
        cl = self.client
        if not cl:
            return
        what = {0: "COLD START", 1: "WARM START"}[state]
        if not messagebox.askyesno(APP_NAME, f"Send ReinitializeDevice ({what}) to device "
                                   f"{dev.instance} '{dev.name}'?\n\nThe controller will restart.",
                                   icon="warning", parent=self.root):
            return
        pwd = simpledialog.askstring("Password", "Device password (leave empty if none):",
                                     show="*", parent=self.root) or ""
        self.bg(lambda: cl.reinitialize_device(dev.address, state, pwd),
                lambda _: self.log("info", f"ReinitializeDevice {what} accepted by {dev.instance}"),
                "Reinitialize device", quiet_errors=False)

    def comm_control(self, dev: DeviceInfo, enable: int):
        cl = self.client
        if not cl:
            return
        names = {0: "ENABLE", 1: "DISABLE", 2: "DISABLE INITIATION"}
        dur = 0
        if enable != 0:
            d = simpledialog.askinteger("Duration", "Duration in minutes (0 = indefinite):",
                                        parent=self.root, minvalue=0, initialvalue=10)
            if d is None:
                return
            dur = d
        pwd = simpledialog.askstring("Password", "Device password (leave empty if none):",
                                     show="*", parent=self.root) or ""
        self.bg(lambda: cl.device_communication_control(dev.address, enable, dur, pwd),
                lambda _: self.log("info", f"DeviceCommunicationControl {names[enable]} "
                                           f"accepted by {dev.instance}"),
                "Device communication control", quiet_errors=False)

    def remove_device(self, dev: DeviceInfo):
        if not self.client:
            return
        self.client.devices.pop(dev.instance, None)
        iid = self.dev_iid.pop(dev.instance, None)
        if iid:
            self.dev_nodes.pop(iid, None)
            if self.dev_tree.exists(iid):
                parent = self.dev_tree.parent(iid)
                self.dev_tree.delete(iid)
                if parent and not self.dev_tree.get_children(parent):
                    self.dev_tree.delete(parent)
                    for k, v in list(self.net_iid.items()):
                        if v == parent:
                            del self.net_iid[k]
        if self.current_dev is dev:
            self.current_dev = None
            self.current_obj = None
            self.obj_tree.delete(*self.obj_tree.get_children())
            self.prop_tree.delete(*self.prop_tree.get_children())
        self.dev_count.configure(text=f"{len(self.dev_iid)} devices")

    # ------------------------------------------------------------------ context menus
    def _popup(self, event, items: List[Optional[tuple]]):
        m = tk.Menu(self.root, tearoff=False)
        for it in items:
            if it is None:
                m.add_separator()
            else:
                m.add_command(label=it[0], command=it[1])
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def on_device_menu(self, event):
        iid = self.dev_tree.identify_row(event.y)
        if not iid or iid not in self.dev_nodes:
            return
        self.dev_tree.selection_set(iid)
        dev = self.selected_device()
        if not dev:
            return

        def reload():
            dev.objects = []
            dev.object_names.clear()
            self.load_address_space(dev)
        self._popup(event, [
            ("Refresh address space", reload),
            ("Show device properties", lambda: self._show_object(dev.oid)),
            None,
            ("Time synchronize", lambda: self.time_sync(False, dev)),
            ("UTC time synchronize", lambda: self.time_sync(True, dev)),
            None,
            ("Communication control: Enable", lambda: self.comm_control(dev, 0)),
            ("Communication control: Disable…", lambda: self.comm_control(dev, 1)),
            ("Reinitialize: Warm start…", lambda: self.reinitialize(dev, 1)),
            ("Reinitialize: Cold start…", lambda: self.reinitialize(dev, 0)),
            None,
            ("Export points to CSV…", lambda: self.export_csv(dev)),
            ("Copy address", lambda: self._copy(str(dev.address))),
            ("Remove from list", lambda: self.remove_device(dev)),
        ])

    def on_object_menu(self, event):
        iid = self.obj_tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.obj_tree.selection():
            self.obj_tree.selection_set(iid)
        oid = self.obj_nodes.get(iid)
        items: List[Optional[tuple]] = [
            ("Subscribe / monitor…", self.subscribe_selected),
        ]
        if oid is not None and oid.type != C.OBJ_DEVICE and self.current_dev is not None:
            dev = self.current_dev
            items.insert(0, ("Write present value…", lambda: self.open_write_dialog(
                dev, oid, self.current_props.get(C.PROP_PRESENT_VALUE)
                if self.current_obj == oid else None)))
        if oid is not None:
            items += [("Read all properties", lambda: self._show_object(oid)),
                      ("Read property…", self.read_property_dialog),
                      None,
                      ("Copy object id", lambda: self._copy(str(oid)))]
        self._popup(event, items)

    def on_prop_menu(self, event):
        iid = self.prop_tree.identify_row(event.y)
        if not iid:
            return
        self.prop_tree.selection_set(iid)
        val = self.prop_tree.set(iid, "value")
        self._popup(event, [
            ("Write…", self.write_selected),
            ("Refresh", lambda: self.current_obj and self._show_object(self.current_obj)),
            None,
            ("Copy value", lambda: self._copy(val)),
            ("Copy all properties", self._copy_all_props),
        ])

    def on_sub_menu(self, event):
        iid = self.sub_tree.identify_row(event.y)
        if not iid:
            return
        if iid not in self.sub_tree.selection():
            self.sub_tree.selection_set(iid)
        self._popup(event, [
            ("Write value…", self.write_subscription),
            ("Go to point in address space", lambda: self.on_sub_double(None, "name")),
            None,
            ("Show in graph / hide", self.toggle_graph),
            ("Go to object", lambda: self.on_sub_double(None)),
            None,
            ("Remove subscription", self.remove_subscriptions),
        ])

    def _copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._set_status("Copied to clipboard")

    def _copy_all_props(self):
        lines = []
        for iid in self.prop_tree.get_children():
            lines.append(f"{self.prop_tree.item(iid, 'text')}\t{self.prop_tree.set(iid, 'value')}")
        self._copy("\n".join(lines))

    # ------------------------------------------------------------------ export
    def export_csv(self, dev: Optional[DeviceInfo] = None):
        dev = dev or self.current_dev or self.selected_device()
        cl = self.client
        if cl is None or dev is None:
            messagebox.showinfo(APP_NAME, "Select a device first.", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".csv",
            initialfile=f"device_{dev.instance}_points.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        props = [C.PROP_OBJECT_NAME, C.PROP_PRESENT_VALUE, C.PROP_UNITS, C.PROP_DESCRIPTION,
                 C.PROP_STATUS_FLAGS, C.PROP_OUT_OF_SERVICE, C.PROP_RELIABILITY]

        def work():
            objs = dev.objects or cl.read_object_list(dev, self.progress_cb("Reading object list"))
            rows = []
            prog = self.progress_cb("Exporting")
            batch = 10 if dev.max_apdu >= 1024 or dev.can_receive_segments else 2
            for k in range(0, len(objs), batch):
                chunk = objs[k:k + batch]
                vals: Dict[ObjectId, Dict[int, Any]] = {o: {} for o in chunk}
                try:
                    if dev.supports_rpm is False:
                        raise BACnetException("no RPM")
                    for o, results in cl.read_property_multiple(
                            dev.address, [(o, [(p, None) for p in props]) for o in chunk]):
                        for r in results:
                            if r.error is None:
                                vals[o][r.prop] = r.value
                except BACnetException:
                    for o in chunk:
                        for p in props:
                            try:
                                vals[o][p] = cl.read_property(dev.address, o, p)
                            except BACnetException:
                                pass
                for o in chunk:
                    v = vals[o]
                    rows.append([
                        dev.instance, C.object_type_name(o.type), o.instance,
                        str(v.get(C.PROP_OBJECT_NAME, "")),
                        X.format_value(v[C.PROP_PRESENT_VALUE], o.type, C.PROP_PRESENT_VALUE)
                        if C.PROP_PRESENT_VALUE in v else "",
                        X.format_value(v[C.PROP_UNITS], o.type, C.PROP_UNITS) if C.PROP_UNITS in v else "",
                        str(v.get(C.PROP_DESCRIPTION, "")),
                        X.format_value(v[C.PROP_STATUS_FLAGS], o.type, C.PROP_STATUS_FLAGS).split("  ")[-1]
                        if C.PROP_STATUS_FLAGS in v else "",
                        str(v.get(C.PROP_OUT_OF_SERVICE, "")),
                        X.format_value(v[C.PROP_RELIABILITY], o.type, C.PROP_RELIABILITY)
                        if C.PROP_RELIABILITY in v else "",
                    ])
                prog(min(k + batch, len(objs)), len(objs))
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["Device", "Object type", "Instance", "Name", "Present value", "Units",
                            "Description", "Status flags", "Out of service", "Reliability"])
                w.writerows(rows)
            return len(rows)
        self.bg(work, lambda n: (self.log("info", f"Exported {n} objects to {path}"),
                                 self._set_status(f"Exported {n} objects to {path}")),
                f"Exporting device {dev.instance}", quiet_errors=False)

    def save_log(self):
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".txt",
                                            initialfile="bacnet_explorer_log.txt",
                                            filetypes=[("Text", "*.txt")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_text.get("1.0", "end"))

    # ------------------------------------------------------------------ help
    def show_help(self):
        messagebox.showinfo("Quick help", (
            "1. File ▸ Start (F2) opens a BACnet/IP channel on a network interface.\n"
            "2. Discover (F5) broadcasts Who-Is; devices appear in the Devices tree.\n"
            "   Use 'Add device' for devices that don't answer broadcasts (other subnets).\n"
            "3. Select a device to load its address space (objects and names).\n"
            "4. Select an object to read all its properties.\n"
            "5. Double-click a property (or F4) to write it - choose priority for commandable\n"
            "   objects, or 'Write NULL' to relinquish.\n"
            "6. Select objects and press Subscribe (F6 / Enter) for COV monitoring;\n"
            "   values are plotted in the Trend graph tab.\n\n"
            "Tip: only one program can normally own UDP 47808 per network card. Close other\n"
            "BACnet tools, or use port 0 and send Who-Is directed to the device."),
            parent=self.root)

    def show_about(self):
        win = tk.Toplevel(self.root)
        win.title("About")
        win.transient(self.root)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=18)
        f.pack(fill="both", expand=True)
        if self.logo_about is not None:
            ttk.Label(f, image=self.logo_about).grid(row=0, column=0, rowspan=2, padx=(0, 16), sticky="n")
        ttk.Label(f, text=f"{APP_NAME} {APP_VERSION}", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=1, sticky="w")
        ttk.Label(f, justify="left", text=(
            "BACnet/IP discovery & commissioning tool\n"
            "Pure Python + Tkinter, inspired by YABE.\n\n"
            "ASHRAE 135 services: Who-Is/I-Am, Who-Has/I-Have, ReadProperty,\n"
            "ReadPropertyMultiple, WriteProperty, SubscribeCOV, TimeSynchronization,\n"
            "ReinitializeDevice, DeviceCommunicationControl.\n\n"
            "Animated equipment graphics linked to live BACnet points.")).grid(row=1, column=1, sticky="w")
        ttk.Button(f, text="OK", command=win.destroy).grid(row=2, column=1, sticky="e", pady=(12, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        center_on(win, self.root)

    # ------------------------------------------------------------------ helpers for panels
    def save(self):
        save_settings(self.settings)

    def network_settings(self):
        NetworkAdapterDialog(self)

    def open_write_dialog(self, dev: DeviceInfo, oid: ObjectId, current: Any = None):
        if self.client is None or not self.client.running:
            messagebox.showinfo(APP_NAME, "Open a BACnet/IP channel first.", parent=self.root)
            return
        commandable = oid.type in C.COMMANDABLE_TYPES
        st = self.units_cache.get((dev.instance, oid, "st"))
        res = WriteDialog(self.root, oid, C.PROP_PRESENT_VALUE,
                          X.NULL if current is None else current, st, commandable).show()
        if res:
            value, prio, index = res
            self._do_write(dev, oid, C.PROP_PRESENT_VALUE, value, prio, index)

    # ---- drag an object from the address space onto a graphic
    def _drag_start(self, event):
        iid = self.obj_tree.identify_row(event.y)
        self._drag = {"oid": self.obj_nodes.get(iid), "x": event.x_root, "y": event.y_root,
                      "active": False}

    def _drag_motion(self, event):
        d = getattr(self, "_drag", None)
        if not d or d["oid"] is None:
            return
        if not d["active"] and abs(event.x_root - d["x"]) + abs(event.y_root - d["y"]) > 12:
            d["active"] = True
            self.obj_tree.configure(cursor="plus")
            self._set_status(f"Drop {d['oid']} on a graphic element to link it")

    def _drag_end(self, event):
        d = getattr(self, "_drag", None)
        self._drag = None
        self.obj_tree.configure(cursor="")
        if d and d["active"] and d["oid"] is not None:
            if not self.graphics.drop_object(event.x_root, event.y_root, d["oid"]):
                self._set_status("Drop the object on an element of the graphic (or its point list)")

    # ------------------------------------------------------------------ window size / layout
    def _restore_geometry(self):
        """Restore the last window size, but always keep it inside the screen
        (a size saved while maximized or on a bigger monitor made the window wider than the
        screen, hiding the minimize / maximize buttons)."""
        root = self.root
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        g = str(self.settings.get("geometry_normal") or self.settings.get("geometry") or "")
        m = re.match(r"(\d+)x(\d+)\+?(-?\d+)?\+?(-?\d+)?", g)
        w, h = (int(m.group(1)), int(m.group(2))) if m else (1280, 800)
        w, h = max(800, min(w, sw - 16)), max(520, min(h, sh - 72))
        x = int(m.group(3)) if m and m.group(3) else (sw - w) // 2
        y = int(m.group(4)) if m and m.group(4) else max(0, (sh - h) // 3)
        x, y = max(0, min(x, sw - w)), max(0, min(y, sh - h - 48))
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(min(800, sw - 40), min(520, sh - 80))
        self._normal_geom = f"{w}x{h}+{x}+{y}"
        root.bind("<Configure>", self._on_root_configure, add="+")
        if self.settings.get("zoomed"):
            root.after(100, self._maximize)
        root.after(400, self._restore_sash)

    def _maximize(self):
        try:
            self.root.state("zoomed")            # Windows / macOS
        except tk.TclError:
            try:
                self.root.attributes("-zoomed", True)   # Linux
            except tk.TclError:
                pass

    def _is_zoomed(self) -> bool:
        try:
            if self.root.state() == "zoomed":
                return True
            return bool(self.root.attributes("-zoomed"))
        except tk.TclError:
            return False

    def _on_root_configure(self, event):
        if event.widget is self.root and self.root.state() == "normal" and not self._is_zoomed():
            self._normal_geom = self.root.geometry()

    def _restore_sash(self):
        main = self._panes[0]
        w = main.winfo_width()
        if w < 300:
            return
        frac = self.settings.get("sash_main_frac")
        frac = float(frac) if isinstance(frac, (int, float)) and 0.1 <= frac <= 0.7 else 0.30
        try:
            main.sashpos(0, int(w * frac))
        except tk.TclError:
            pass

    def _save_layout(self):
        self.settings.pop("geometry", None)
        self.settings["geometry_normal"] = self._normal_geom or self.root.geometry()
        self.settings["zoomed"] = self._is_zoomed()
        main = self._panes[0]
        try:
            if self.devices_visible and not self.full_view and main.winfo_width() > 300:
                self.settings["sash_main_frac"] = round(main.sashpos(0) / main.winfo_width(), 3)
        except tk.TclError:
            pass

    def toggle_devices(self, show: Optional[bool] = None):
        """Hide / show the Devices + Address space panel (Ctrl+B)."""
        main, left, _right, _nb = self._panes
        if self.full_view:
            self.toggle_full_view()
        show = (not self.devices_visible) if show is None else bool(show)
        visible = str(left) in [str(p) for p in main.panes()]
        if show and not visible:
            main.insert(0, left, weight=1)
            self.root.after(50, self._restore_sash)
        elif not show and visible:
            self._save_layout()
            main.forget(left)
        self.devices_visible = show
        self.devices_var.set(show)
        self.dev_btn.configure(text="◂ Devices" if show else "▸ Devices")

    def reset_layout(self):
        if self.full_view:
            self.toggle_full_view()
        self.toggle_devices(True)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        try:
            self.root.state("normal")
        except tk.TclError:
            pass
        w, h = min(1280, sw - 16), min(800, sh - 72)
        self.root.geometry(f"{w}x{h}+{(sw - w) // 2}+{max(0, (sh - h) // 3)}")
        self.settings.pop("sash_main_frac", None)
        self.root.after(200, self._restore_sash)

    # ------------------------------------------------------------------ restart / account
    def restart_app(self):
        if not messagebox.askyesno(APP_NAME, "Restart Basil BACnet Explorer now?", parent=self.root):
            return
        self._restart(keep_login=True)

    def _restart(self, keep_login: bool):
        env = dict(os.environ)
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"     # let a one-file .exe start a fresh copy
        env.pop("BASIL_RESTART_TOKEN", None)
        if keep_login:
            env["BASIL_RESTART_TOKEN"] = self.auth.make_restart_token()
        if getattr(sys, "frozen", False):
            cmd = [sys.executable] + sys.argv[1:]
        else:
            cmd = [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
        self.on_exit()                                  # saves settings, frees the UDP port
        kw: Dict[str, Any] = {"env": env, "close_fds": True}
        if sys.platform.startswith("win"):
            kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        try:
            subprocess.Popen(cmd, **kw)
        except OSError as e:
            print(f"restart failed: {e}")

    def change_password(self):
        res = ChangePasswordDialog(self.root).show()
        if not res:
            return
        err = self.auth.change_password(*res)
        if err:
            messagebox.showerror("Change password", err, parent=self.root)
            return
        self.autologin_var.set(False)
        self.save()
        messagebox.showinfo("Change password", "Password changed.\nAuto login was turned off - "
                            "tick 'Remember me' at the next login to turn it on again.",
                            parent=self.root)

    def _autologin_changed(self):
        if self.autologin_var.get():
            self.auth.enable_autologin()
        else:
            self.auth.disable_autologin()
        self.save()

    def log_out(self):
        if not messagebox.askyesno(APP_NAME, "Log out? Auto login is turned off and the login "
                                   "screen is shown.", parent=self.root):
            return
        self.auth.disable_autologin()
        self._restart(keep_login=False)

    # ------------------------------------------------------------------ write from lists
    def write_subscription(self):
        subs = self.selected_subs()
        if not subs:
            return
        s = subs[0]
        self.open_write_dialog(s.device, s.object_id, s.value)

    # ------------------------------------------------------------------ online report
    def online_report(self):
        if self.require_client() is None:
            return
        if getattr(self, "_report", None) is not None and self._report.winfo_exists():
            self._report.deiconify()
            self._report.lift()
            return
        self._report = OnlineReport(self)

    # ------------------------------------------------------------------ exit
    def on_exit(self):
        self._save_layout()
        self.settings["debug_log"] = self.debug_var.get()
        save_settings(self.settings)
        if self.client:
            try:
                self.client.stop()
            except Exception:
                pass
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # Python 3.8
            self.pool.shutdown(wait=False)
        self.root.destroy()


def main():
    if sys.platform.startswith("win"):
        try:  # crisp text on high-DPI displays
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:  # own taskbar group so Windows shows our logo instead of Python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(  # type: ignore[attr-defined]
                "Basil.BACnetExplorer")
        except Exception:
            pass
    root = tk.Tk()
    if not login(root):
        return
    ExplorerApp(root)
    root.mainloop()


def login(root: tk.Tk) -> bool:
    """Show the login screen unless auto login (or a restart) applies. False = user quit."""
    settings = load_settings()
    auth = Auth(settings)
    auth.record()                                   # creates the default account on first run
    restart_tok = os.environ.pop("BASIL_RESTART_TOKEN", None)
    if auth.use_restart_token(restart_tok) or auth.autologin_ok():
        save_settings(settings)
        return True
    try:
        for n in ("logo_256.png", "logo_64.png", "logo_32.png"):
            pth = os.path.join(ASSETS, n)
            if os.path.exists(pth):
                root.iconphoto(True, tk.PhotoImage(master=root, file=pth))
                break
    except tk.TclError:
        pass
    theme = str(settings.get("theme")) if settings.get("theme") in THEMES else "light"
    colors = dict(THEMES[theme])
    colors["dark"] = "1" if theme == "dark" else "0"
    screen = LoginScreen(root, auth, APP_NAME, APP_VERSION, os.path.join(ASSETS, "logo_64.png"),
                         colors)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    try:
        root.wait_variable(screen.result)
    except tk.TclError:
        return False
    try:
        if not root.winfo_exists() or not screen.result.get():
            return False
    except tk.TclError:
        return False
    save_settings(settings)
    screen.destroy()
    return True


if __name__ == "__main__":
    main()
