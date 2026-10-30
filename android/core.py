"""
Basil BACnet (Android) - application logic, independent of the user interface.

Everything that talks BACnet or keeps state lives here so it can be tested on a PC
(against bacnet_simulator.py) and reused by the Kivy screens in main.py.
All blocking work runs in worker threads; results are delivered through `post(fn)`,
which the UI sets to "run fn on the UI thread" (Kivy: Clock.schedule_once).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from bacnet import codec as X
from bacnet import constants as C
from bacnet.client import (BACnetClient, BACnetError, BACnetException, DeviceInfo, Subscription)
from bacnet.codec import ObjectId

from authcore import Auth
from xlsx_export import Sheet, write_xlsx

APP_NAME = "Basil BACnet"
APP_VERSION = "1.0.0"

POINT_TYPES = {0, 1, 2, 3, 4, 5, 13, 14, 19, 23, 24, 40, 45, 46, 48, 54, 55}
UNIT_SHORT = {62: "°C", 64: "°F", 98: "%", 29: "%RH", 53: "Pa", 54: "kPa", 55: "bar", 58: "inH2O",
              56: "psi", 84: "cfm", 85: "m³/s", 87: "l/s", 88: "l/min", 89: "gpm", 96: "ppm",
              104: "rpm", 27: "Hz", 47: "W", 48: "kW", 19: "kWh", 5: "V", 3: "A", 63: "K"}
TYPE_FILTERS = [("All", None), ("Analog", C.ANALOG_TYPES), ("Binary", C.BINARY_TYPES),
                ("Multi-state", C.MULTISTATE_TYPES), ("AI", {0}), ("AO", {1}), ("AV", {2}),
                ("BI", {3}), ("BO", {4}), ("BV", {5}), ("MSV", {19})]


def units_text(units: Any) -> str:
    try:
        u = int(units)
    except (TypeError, ValueError):
        return ""
    return "" if u == 95 else UNIT_SHORT.get(u, C.ENGINEERING_UNITS.get(u, ""))


def value_text(value: Any, oid: ObjectId, units: Any = None,
               state_text: Optional[List[str]] = None) -> str:
    if value is None:
        return "-"
    if isinstance(value, X.Null):
        return "NULL"
    if oid.type in C.MULTISTATE_TYPES and isinstance(value, int) and state_text \
            and 0 < int(value) <= len(state_text):
        return f"{state_text[int(value) - 1]} ({int(value)})"
    txt = X.format_value(value, oid.type, C.PROP_PRESENT_VALUE)
    if isinstance(value, float):
        if abs(value) >= 1e6:
            txt = f"{value:.4g}"
        else:
            txt = f"{value:.1f}" if abs(value) >= 100 else f"{value:.2f}".rstrip("0").rstrip(".")
    u = units_text(units)
    return f"{txt} {u}" if u and isinstance(value, (int, float)) and not isinstance(value, bool) \
        and oid.type not in C.BINARY_TYPES else txt


def parse_value(oid: ObjectId, txt: str, current: Any = None) -> Any:
    """User text -> typed BACnet value for writing the present value."""
    t = txt.strip()
    low = t.lower()
    if low in ("null", "release", "relinquish") or low.startswith("null"):
        return X.NULL
    first = t.split(" ")[0].split("(")[0].strip()
    if oid.type in C.BINARY_TYPES:
        if low in ("active", "on", "true", "1", "start"):
            return X.Enumerated(1)
        if low in ("inactive", "off", "false", "0", "stop"):
            return X.Enumerated(0)
        raise ValueError("Use ACTIVE or INACTIVE")
    if oid.type in C.MULTISTATE_TYPES:
        try:
            n = int(first)
        except ValueError:
            raise ValueError("Enter the state number (1, 2, 3 ...)")
        if n < 1:
            raise ValueError("Multi-state values start at 1")
        return X.Unsigned(n)
    num = re.match(r"^\s*([-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?)", t)
    if oid.type in C.ANALOG_TYPES:
        if not num:
            raise ValueError("Enter a number")
        return X.Real(float(num.group(1).replace(",", ".")))
    if oid.type == 45:
        return X.Signed(int(float(num.group(1)))) if num else X.Signed(int(t))
    if oid.type == 48:
        return X.Unsigned(int(float(num.group(1)))) if num else X.Unsigned(int(t))
    if oid.type == 40:
        return X.CharacterString(txt)
    tn = X.type_name_of(current)
    if tn in X.WRITABLE_TYPES and tn != "Null":
        return X.parse_user_value(t, tn)
    if num:
        return X.Real(float(num.group(1).replace(",", ".")))
    return X.CharacterString(txt)


def classify_point(vals: Dict[int, Any]) -> str:
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


class PointInfo:
    """What the object list shows for one object."""
    __slots__ = ("oid", "name", "value", "units", "flags", "state_text")

    def __init__(self, oid: ObjectId, name: str = ""):
        self.oid = oid
        self.name = name
        self.value: Any = None
        self.units: Any = None
        self.flags: Any = None
        self.state_text: Optional[List[str]] = None

    def text(self) -> str:
        return value_text(self.value, self.oid, self.units, self.state_text)


class WatchItem:
    """A point on the Watch list (live value, flashes 3 s when it changes)."""

    def __init__(self, dev: int, oid: ObjectId, name: str):
        self.dev, self.oid, self.name = dev, oid, name
        self.sub_id: Optional[int] = None
        self.value: Any = None
        self.text = "-"
        self.flags: Any = None
        self.flash_until = 0.0
        self.state = "waiting"

    @property
    def key(self) -> Tuple[int, int, int]:
        return self.dev, self.oid.type, self.oid.instance

    @property
    def flashing(self) -> bool:
        return time.time() < self.flash_until


class Core:
    def __init__(self, data_dir: str, post: Optional[Callable[[Callable[[], None]], None]] = None):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.settings_path = os.path.join(data_dir, "settings.json")
        self.settings: Dict[str, Any] = self._load()
        self.auth = Auth(self.settings)
        self.auth.record()
        self.post = post or (lambda fn: fn())
        self.client: Optional[BACnetClient] = None
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="core")
        self.points: Dict[int, Dict[ObjectId, PointInfo]] = {}      # device -> objects
        self.watch: List[WatchItem] = []
        self.log_lines: List[str] = []
        self.units_cache: Dict[tuple, Any] = {}
        # UI callbacks
        self.on_devices: Callable[[], None] = lambda: None
        self.on_watch: Callable[[], None] = lambda: None
        self.on_status: Callable[[str], None] = lambda text: None
        self.on_log: Callable[[str, str], None] = lambda level, msg: None
        for d in self.settings.get("watch", []):
            try:
                self.watch.append(WatchItem(int(d["dev"]), ObjectId(int(d["type"]), int(d["inst"])),
                                            str(d.get("name", ""))))
            except (KeyError, TypeError, ValueError):
                pass

    # ------------------------------------------------------------------ settings
    def _load(self) -> Dict[str, Any]:
        try:
            with open(self.settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self):
        self.settings["watch"] = [{"dev": w.dev, "type": w.oid.type, "inst": w.oid.instance,
                                   "name": w.name} for w in self.watch]
        tmp = self.settings_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=1)
            os.replace(tmp, self.settings_path)
        except OSError:
            pass

    def setting(self, key: str, default: Any) -> Any:
        return self.settings.get(key, default)

    @property
    def priority(self) -> int:
        try:
            return max(1, min(16, int(self.settings.get("priority", 8))))
        except (TypeError, ValueError):
            return 8

    @property
    def refresh(self) -> float:
        try:
            return max(1.0, float(self.settings.get("refresh", 1)))
        except (TypeError, ValueError):
            return 1.0

    # ------------------------------------------------------------------ helpers
    def _bg(self, work: Callable[[], Any], done: Optional[Callable[[Any], None]] = None,
            error: Optional[Callable[[Exception], None]] = None):
        def run():
            try:
                res = work()
            except Exception as e:  # noqa
                if error:
                    self.post(lambda: error(e))
                else:
                    self.log("error", str(e))
                return
            if done:
                self.post(lambda: done(res))
        self.pool.submit(run)

    def log(self, level: str, msg: str):
        line = f"{time.strftime('%H:%M:%S')} {level.upper():<7} {msg}"
        self.log_lines.append(line)
        del self.log_lines[:-500]
        self.post(lambda: self.on_log(level, msg))

    # ------------------------------------------------------------------ network
    @property
    def online(self) -> bool:
        return bool(self.client and self.client.running)

    def connect(self, local_ip: str, broadcast: str, port: int = 47808, remote_port: int = 47808,
                bbmd: str = "", bbmd_port: int = 47808, ttl: int = 900) -> Optional[str]:
        """Start the BACnet/IP channel. Returns an error message or None."""
        self.disconnect()
        cl = BACnetClient(local_ip or "0.0.0.0", port, broadcast or "255.255.255.255",
                          timeout=float(self.settings.get("timeout", 3.0)), retries=2)
        cl.remote_port = remote_port
        cl.auto_refresh = True
        cl.refresh_interval = self.refresh
        cl.on_log = lambda level, msg: self.log(level, msg) if level in ("info", "warning", "error") \
            else None
        cl.on_device = lambda d, new: self.post(self._device_seen)
        cl.on_subscription = self._sub_update
        try:
            cl.start()
        except BACnetException as e:
            return str(e)
        self.client = cl
        if bbmd:
            try:
                cl.register_foreign_device(bbmd, bbmd_port, ttl)
            except OSError as e:
                self.log("warning", f"BBMD: {e}")
        return None

    def disconnect(self):
        cl, self.client = self.client, None
        if cl:
            try:
                cl.stop()
            except Exception:
                pass
        for w in self.watch:
            w.sub_id = None
            w.state = "waiting"

    def discover(self, target: Optional[Tuple[str, int]] = None):
        if not self.client:
            return
        try:
            self.client.who_is(target=target, global_broadcast=True)
            self.on_status("Who-Is sent - waiting for devices")
        except OSError as e:
            self.log("error", f"Who-Is failed: {e}")

    def add_device_by_ip(self, ip: str, port: int, done: Callable[[Any], None],
                         error: Callable[[Exception], None]):
        cl = self.client
        if not cl:
            return
        self._bg(lambda: cl.add_device_manual(ip, port), done, error)

    def devices(self) -> List[DeviceInfo]:
        return sorted(self.client.devices.values(), key=lambda d: d.instance) if self.client else []

    def device(self, inst: int) -> Optional[DeviceInfo]:
        return self.client.devices.get(inst) if self.client else None

    def _device_seen(self):
        cl = self.client
        if not cl:
            return
        for d in list(cl.devices.values()):
            if not d.name and not getattr(d, "_name_asked", False):
                d._name_asked = True  # type: ignore[attr-defined]
                self._bg(lambda d=d: cl.read_device_info(d), lambda _r: self.on_devices())
        self._restore_watch()
        self.on_devices()

    # ------------------------------------------------------------------ objects
    def load_objects(self, dev: DeviceInfo, progress: Callable[[str], None],
                     done: Callable[[List[PointInfo]], None], error: Callable[[Exception], None],
                     reload: bool = False):
        cl = self.client
        if not cl:
            return

        def work():
            if reload or not dev.objects:
                if not dev.name:
                    try:
                        cl.read_device_info(dev)
                    except BACnetException:
                        pass
                self.post(lambda: progress("Reading object list…"))
                cl.read_object_list(dev, lambda i, n: self.post(
                    lambda: progress(f"Reading object list {i}/{n}")))
            objs = [o for o in dev.objects if o.type != C.OBJ_DEVICE]
            infos = self.points.setdefault(dev.instance, {})
            for o in objs:
                infos.setdefault(o, PointInfo(o, dev.object_names.get(o, "")))
            self._read_values(dev, [infos[o] for o in objs], with_static=True,
                              progress=lambda i, n: self.post(lambda: progress(f"Reading values {i}/{n}")))
            return [infos[o] for o in objs]
        self._bg(work, done, error)

    def _read_values(self, dev: DeviceInfo, infos: Sequence[PointInfo], with_static: bool = False,
                     progress: Optional[Callable[[int, int], None]] = None):
        cl = self.client
        if not cl or not infos:
            return
        props = [C.PROP_PRESENT_VALUE, C.PROP_STATUS_FLAGS]
        if with_static:
            props = [C.PROP_OBJECT_NAME, C.PROP_UNITS] + props
        chunk = 20 if (dev.max_apdu >= 1024 or dev.can_receive_segments) else 4
        k = 0
        while k < len(infos):
            part = list(infos[k:k + chunk])
            ok = False
            if dev.supports_rpm is not False:
                try:
                    res = cl.read_property_multiple(dev.address, [(p.oid, [(q, None) for q in props
                                                                           if q != C.PROP_UNITS or p.oid.type in C.ANALOG_TYPES])
                                                                  for p in part])
                    by = {o: r for o, r in res}
                    for p in part:
                        for r in by.get(p.oid, []):
                            if r.error is not None:
                                continue
                            if r.prop == C.PROP_PRESENT_VALUE:
                                p.value = r.value
                            elif r.prop == C.PROP_STATUS_FLAGS:
                                p.flags = r.value
                            elif r.prop == C.PROP_OBJECT_NAME:
                                p.name = str(r.value)
                                dev.object_names[p.oid] = p.name
                            elif r.prop == C.PROP_UNITS:
                                p.units = r.value
                                self.units_cache[(dev.instance, p.oid)] = r.value
                    ok = True
                except BACnetException as e:
                    if getattr(e, "reason", None) in (1, 4, 11) and chunk > 1:
                        chunk = max(1, chunk // 2)
                        continue
                    if not isinstance(e, BACnetError):
                        dev.supports_rpm = False
            if not ok:
                for p in part:
                    for q in props:
                        try:
                            v = cl.read_property(dev.address, p.oid, q, timeout=2.0)
                        except BACnetException:
                            continue
                        if q == C.PROP_PRESENT_VALUE:
                            p.value = v
                        elif q == C.PROP_OBJECT_NAME:
                            p.name = str(v)
                        elif q == C.PROP_UNITS:
                            p.units = v
            k += len(part)
            if progress:
                progress(k, len(infos))
        for p in infos:
            if p.oid.type in C.MULTISTATE_TYPES and p.state_text is None:
                p.state_text = self.state_text(dev, p.oid)

    def refresh_values(self, dev: DeviceInfo, infos: Sequence[PointInfo], done: Callable[[Any], None]):
        self._bg(lambda: self._read_values(dev, infos), done, lambda e: None)

    def state_text(self, dev: DeviceInfo, oid: ObjectId) -> Optional[List[str]]:
        key = (dev.instance, oid, "st")
        if key not in self.units_cache:
            try:
                v = self.client.read_property(dev.address, oid, C.PROP_STATE_TEXT) if self.client else None
                self.units_cache[key] = [str(x) for x in v] if isinstance(v, list) else None
            except BACnetException:
                self.units_cache[key] = None
        return self.units_cache[key]

    # ------------------------------------------------------------------ one point
    def read_point(self, dev: DeviceInfo, oid: ObjectId, done: Callable[[List[X.PropertyResult]], None],
                   error: Callable[[Exception], None]):
        cl = self.client
        if not cl:
            return

        def work():
            res = cl.read_all_properties(dev, oid)
            for r in res:
                if r.prop == C.PROP_UNITS and r.error is None:
                    self.units_cache[(dev.instance, oid)] = r.value
                if r.prop == C.PROP_STATE_TEXT and r.error is None and isinstance(r.value, list):
                    self.units_cache[(dev.instance, oid, "st")] = [str(x) for x in r.value]
            return res
        self._bg(work, done, error)

    def write(self, dev: DeviceInfo, oid: ObjectId, value: Any, priority: Optional[int],
              done: Callable[[Any], None], error: Callable[[Exception], None],
              prop: int = C.PROP_PRESENT_VALUE):
        cl = self.client
        if not cl:
            error(BACnetException("Not connected"))
            return
        prio = priority if oid.type in C.COMMANDABLE_TYPES and prop == C.PROP_PRESENT_VALUE else None

        def work():
            cl.write_property(dev.address, oid, prop, value, prio)
            # read back so the screen shows the real result immediately
            try:
                return cl.read_property(dev.address, oid, C.PROP_PRESENT_VALUE, timeout=2.0)
            except BACnetException:
                return None

        def ok(v):
            for w in self.watch:
                if w.key == (dev.instance, oid.type, oid.instance) and v is not None:
                    self._set_watch_value(w, v)
            info = self.points.get(dev.instance, {}).get(oid)
            if info is not None and v is not None:
                info.value = v
            done(v)
        self._bg(work, ok, error)

    # ------------------------------------------------------------------ watch list
    def in_watch(self, dev: int, oid: ObjectId) -> bool:
        return any(w.key == (dev, oid.type, oid.instance) for w in self.watch)

    def add_watch(self, dev: DeviceInfo, oid: ObjectId, name: str):
        if self.in_watch(dev.instance, oid):
            return
        self.watch.append(WatchItem(dev.instance, oid, name or str(oid)))
        self.save()
        self._restore_watch()
        self.on_watch()

    def remove_watch(self, item: WatchItem):
        if item in self.watch:
            self.watch.remove(item)
            if self.client and item.sub_id is not None:
                cl, sid = self.client, item.sub_id
                self.pool.submit(cl.remove_subscription, sid)
            self.save()
            self.on_watch()

    def _restore_watch(self):
        cl = self.client
        if not cl:
            return
        for w in self.watch:
            if w.sub_id is not None or getattr(w, "_pending", False):
                continue
            dev = cl.devices.get(w.dev)
            if dev is None:
                continue
            w._pending = True  # type: ignore[attr-defined]

            def work(w=w, dev=dev):
                if (dev.instance, w.oid) not in self.units_cache and w.oid.type in C.ANALOG_TYPES:
                    try:
                        self.units_cache[(dev.instance, w.oid)] = cl.read_property(
                            dev.address, w.oid, C.PROP_UNITS)
                    except BACnetException:
                        self.units_cache[(dev.instance, w.oid)] = None
                if w.oid.type in C.MULTISTATE_TYPES:
                    self.state_text(dev, w.oid)
                return cl.add_subscription(dev, w.oid, False, 300, True, cl.refresh_interval,
                                           name=w.name)

            def done(sub, w=w):
                w._pending = False  # type: ignore[attr-defined]
                w.sub_id = sub.sub_id
                w.state = sub.mode
                self.on_watch()

            def err(e, w=w):
                w._pending = False  # type: ignore[attr-defined]
                w.state = f"error: {e}"
                self.on_watch()
            self._bg(work, done, err)

    def _sub_update(self, sub: Subscription):
        def apply():
            for w in self.watch:
                if w.sub_id == sub.sub_id:
                    w.flags = sub.status_flags
                    if sub.value is not None:
                        self._set_watch_value(w, sub.value)
            self.on_watch()
        self.post(apply)

    def _set_watch_value(self, w: WatchItem, value: Any):
        text = value_text(value, w.oid, self.units_cache.get((w.dev, w.oid)),
                          self.units_cache.get((w.dev, w.oid, "st")))
        if w.text not in ("-", "") and text != w.text:
            w.flash_until = time.time() + 3.0
        w.value, w.text = value, text
        w.state = "live"

    def set_refresh(self, seconds: float):
        self.settings["refresh"] = seconds
        if self.client:
            self.client.refresh_interval = seconds
        self.save()

    # ------------------------------------------------------------------ online report
    def scan(self, with_points: bool, whois: bool, progress: Callable[[str, int, int], None],
             done: Callable[[Dict[str, Any]], None], cancel: threading.Event):
        cl = self.client
        if not cl:
            return

        def work():
            if whois:
                self.post(lambda: progress("Sending Who-Is, waiting 4 s…", 0, 1))
                cl.who_is(global_broadcast=True)
                for _ in range(40):
                    if cancel.is_set():
                        break
                    time.sleep(0.1)
            devs = sorted(cl.devices.values(), key=lambda d: d.instance)
            rows: Dict[int, Dict[str, Any]] = {}
            pts: List[Dict[str, Any]] = []
            lock = threading.Lock()
            count = [0]

            def check(d: DeviceInfo):
                if cancel.is_set():
                    return
                row = {"inst": d.instance, "name": d.name, "addr": str(d.address),
                       "status": "Offline", "ms": "", "vendor": d.vendor_name or d.vendor_id,
                       "model": d.model_name, "points": "", "ok": "", "oos": "", "bad": ""}
                t0 = time.time()
                try:
                    ack = cl.request(d.address, C.SERVICE_READ_PROPERTY,
                                     X.body_read_property(d.oid, C.PROP_OBJECT_NAME), timeout=2.5,
                                     retries=1)
                    nm = X.parse_read_property_ack(ack.data)[3]
                    row["status"], row["ms"] = "Online", int((time.time() - t0) * 1000)
                    if not d.name:
                        d.name = str(nm)
                    row["name"] = d.name
                except BACnetException:
                    pass
                mine: List[Dict[str, Any]] = []
                if with_points and row["status"] == "Online" and not cancel.is_set():
                    mine = self._scan_points(d, cancel)
                    row["points"] = len(mine)
                    row["ok"] = sum(p["status"] in ("Online", "Out of service") for p in mine)
                    row["oos"] = sum(p["status"] == "Out of service" for p in mine)
                    row["bad"] = sum(p["status"] in ("Fault", "No response") for p in mine)
                with lock:
                    rows[d.instance] = row
                    pts.extend(mine)
                    count[0] += 1
                    n = count[0]
                self.post(lambda: progress(f"Checked {n} of {len(devs)} devices", n, len(devs)))

            with ThreadPoolExecutor(max_workers=3 if with_points else 6) as ex:
                list(ex.map(check, devs))
            return {"devices": rows, "points": pts, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "kind": "devices + points" if with_points else "devices",
                    "cancelled": cancel.is_set()}
        self._bg(work, done, lambda e: done({"devices": {}, "points": [], "error": str(e)}))

    def _scan_points(self, d: DeviceInfo, cancel: threading.Event) -> List[Dict[str, Any]]:
        cl = self.client
        if not cl:
            return []
        try:
            objs = d.objects or cl.read_object_list(d)
        except BACnetException:
            return []
        objs = [o for o in objs if o.type in POINT_TYPES]
        props = [C.PROP_OBJECT_NAME, C.PROP_PRESENT_VALUE, C.PROP_STATUS_FLAGS, C.PROP_RELIABILITY,
                 C.PROP_OUT_OF_SERVICE]
        vals: Dict[ObjectId, Dict[int, Any]] = {o: {} for o in objs}
        chunk = 20 if (d.max_apdu >= 1024 or d.can_receive_segments) else 4
        k = 0
        while k < len(objs) and not cancel.is_set():
            part = objs[k:k + chunk]
            if d.supports_rpm is not False:
                try:
                    for o, results in cl.read_property_multiple(
                            d.address, [(o, [(p, None) for p in props]) for o in part]):
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
            for o in part:
                for p in (C.PROP_PRESENT_VALUE, C.PROP_STATUS_FLAGS):
                    try:
                        vals[o][p] = cl.read_property(d.address, o, p, timeout=2.0)
                    except BACnetException:
                        break
            k += len(part)
        out = []
        for o in objs:
            v = vals.get(o, {})
            rel = v.get(C.PROP_RELIABILITY)
            out.append({"dev": d.instance, "devname": d.name, "obj": o.short, "objfull": str(o),
                        "name": str(v.get(C.PROP_OBJECT_NAME, d.object_names.get(o, ""))),
                        "value": X.format_value(v[C.PROP_PRESENT_VALUE], o.type, C.PROP_PRESENT_VALUE)
                        if C.PROP_PRESENT_VALUE in v else "",
                        "status": classify_point(v),
                        "rel": X.format_value(rel, o.type, C.PROP_RELIABILITY) if rel is not None else ""})
        return out

    @staticmethod
    def report_counts(rep: Dict[str, Any]) -> Dict[str, int]:
        devs = list(rep.get("devices", {}).values())
        pts = rep.get("points", [])
        return {"dev_total": len(devs), "dev_on": sum(d["status"] == "Online" for d in devs),
                "dev_off": sum(d["status"] == "Offline" for d in devs), "pt_total": len(pts),
                "pt_on": sum(p["status"] in ("Online", "Out of service") for p in pts),
                "pt_ok": sum(p["status"] == "Online" for p in pts),
                "pt_oos": sum(p["status"] == "Out of service" for p in pts),
                "pt_fault": sum(p["status"] == "Fault" for p in pts),
                "pt_noresp": sum(p["status"] == "No response" for p in pts)}

    def export_report(self, rep: Dict[str, Any], path: str):
        c = self.report_counts(rep)
        fill = {"Online": "green", "Offline": "red", "Fault": "red", "No response": "red",
                "Out of service": "amber"}
        summ = Sheet("Summary", ["Item", "Value"], [32, 36])
        for k, v in (("Report", "Online devices & points"), ("Generated by", f"{APP_NAME} {APP_VERSION} (Android)"),
                     ("Scan time", rep.get("time", "")), ("Scan type", rep.get("kind", "")), ("", ""),
                     ("Devices found", c["dev_total"]), ("Devices online", c["dev_on"]),
                     ("Devices offline", c["dev_off"])):
            summ.add([k, v], {1: "green"} if k == "Devices online" else ({1: "red"} if k == "Devices offline" and v else None))
        if rep.get("points"):
            for k, v in (("", ""), ("Points", c["pt_total"]), ("Points online", c["pt_on"]),
                         ("  - out of service", c["pt_oos"]), ("Points in fault", c["pt_fault"]),
                         ("Points not responding", c["pt_noresp"])):
                summ.add([k, v], {1: "green"} if k == "Points online" else None)
        devs = Sheet("Devices", ["Instance", "Name", "Address", "Status", "Response ms", "Vendor", "Model",
                                 "Points", "Points online", "Out of service", "Fault / no response"],
                     [11, 30, 26, 12, 12, 24, 20, 9, 13, 14, 18])
        for d in sorted(rep["devices"].values(), key=lambda r: r["inst"]):
            devs.add([d[k] if d[k] != "" else None for k in ("inst", "name", "addr", "status", "ms",
                                                              "vendor", "model", "points", "ok", "oos", "bad")],
                     {3: fill.get(d["status"], "grey")})
        sheets = [summ, devs]
        if rep.get("points"):
            pts = Sheet("Points", ["Device", "Device name", "Object", "Object type:instance", "Name",
                                   "Present value", "Status", "Reliability"], [10, 26, 10, 22, 36, 16, 15, 22])
            for p in sorted(rep["points"], key=lambda r: (r["dev"], r["objfull"])):
                pts.add([p["dev"], p["devname"], p["obj"], p["objfull"], p["name"], p["value"],
                         p["status"], p["rel"]], {6: fill.get(p["status"], "grey")})
            sheets.append(pts)
        write_xlsx(path, sheets, title="BACnet online report", author=APP_NAME)

    # ------------------------------------------------------------------ shutdown
    def close(self):
        self.save()
        self.disconnect()
        try:
            self.pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            self.pool.shutdown(wait=False)
