#!/usr/bin/env python3
"""
BACnet/IP device simulator - for testing Basil BACnet Explorer without real hardware.

Simulates one IP device plus (optionally) several devices behind a virtual
router network (like an MS/TP gateway), with live-changing values, priority
arrays, COV notifications and segmented responses.

    python bacnet_simulator.py                       # device 1001 on UDP 47809
    python bacnet_simulator.py --port 47808 --device 5000 --routed 3 --big

In Basil BACnet Explorer use "Add device by IP" with 127.0.0.1 and the port above,
or send Who-Is to 127.0.0.1:<port>.
"""
from __future__ import annotations

import argparse
import math
import random
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bacnet import constants as C
from bacnet import codec as X
from bacnet.codec import (NULL, BitString, CharacterString, Enumerated, ObjectId, Real,
                          Unsigned)

ROUTED_NET = 2001
EQUIPMENT_NET = 3000


class PropError(Exception):
    def __init__(self, cls: int, code: int):
        self.cls, self.code = cls, code


@dataclass
class SimObject:
    oid: ObjectId
    props: Dict[int, Any]
    priority_array: Optional[List[Any]] = None
    cov_increment: float = 0.5
    last_cov_value: Any = None

    @property
    def commandable(self) -> bool:
        return self.priority_array is not None

    def present_value(self) -> Any:
        if self.priority_array is not None:
            for v in self.priority_array:
                if not isinstance(v, X.Null):
                    return v
            return self.props[C.PROP_RELINQUISH_DEFAULT]
        return self.props[C.PROP_PRESENT_VALUE]

    def get(self, prop: int, idx: Optional[int]) -> Any:
        if prop == C.PROP_PRESENT_VALUE:
            val = self.present_value()
        elif prop == C.PROP_PRIORITY_ARRAY and self.priority_array is not None:
            val = list(self.priority_array)
        elif prop == C.PROP_PROPERTY_LIST:
            val = [Enumerated(p) for p in self.property_ids()
                   if p not in (75, 77, 79, C.PROP_PROPERTY_LIST)]
        elif prop in self.props:
            val = self.props[prop]
        else:
            raise PropError(2, 32)  # property / unknown-property
        if idx is not None:
            if not isinstance(val, list):
                raise PropError(2, 50)  # property-is-not-an-array
            if idx == 0:
                return Unsigned(len(val))
            if idx > len(val):
                raise PropError(2, 42)  # invalid-array-index
            return val[idx - 1]
        return val

    def property_ids(self) -> List[int]:
        ids = [75, 77, 79] + [p for p in self.props if p not in (75, 77, 79)]
        if C.PROP_PRESENT_VALUE not in ids and self.priority_array is not None:
            ids.append(C.PROP_PRESENT_VALUE)
        if self.priority_array is not None:
            ids.append(C.PROP_PRIORITY_ARRAY)
        ids.append(C.PROP_PROPERTY_LIST)
        return ids


@dataclass
class COVSub:
    address: Tuple[str, int]
    pid: int
    oid: ObjectId
    confirmed: bool
    expires: float
    route: Optional[Tuple[int, bytes]] = None   # (snet, sadr) to stamp on replies
    dnet: Optional[Tuple[int, bytes]] = None     # where the subscriber lives (if remote)


@dataclass
class SimDevice:
    instance: int
    name: str
    route: Optional[Tuple[int, bytes]] = None  # (net, mac) when behind the virtual router
    objects: Dict[ObjectId, SimObject] = field(default_factory=dict)
    covs: List[COVSub] = field(default_factory=list)
    max_apdu: int = 1476
    segmentation: int = 0
    rules: List[tuple] = field(default_factory=list)   # equipment behaviour

    @property
    def oid(self) -> ObjectId:
        return ObjectId(C.OBJ_DEVICE, self.instance)


def _status() -> BitString:
    return BitString([False, False, False, False])


def build_device(instance: int, name: str, n_extra: int = 0,
                 route: Optional[Tuple[int, bytes]] = None) -> SimDevice:
    dev = SimDevice(instance, name, route)

    def add(t: int, i: int, nm: str, props: Dict[int, Any], commandable: bool = False,
            relinquish: Any = None):
        oid = ObjectId(t, i)
        p = {75: oid, 77: CharacterString(nm), 79: Enumerated(t),
             C.PROP_STATUS_FLAGS: _status(), C.PROP_EVENT_STATE: Enumerated(0),
             C.PROP_OUT_OF_SERVICE: False, C.PROP_RELIABILITY: Enumerated(0)}
        p.update(props)
        obj = SimObject(oid, p)
        if commandable:
            obj.priority_array = [NULL] * 16
            obj.props[C.PROP_RELINQUISH_DEFAULT] = relinquish
            obj.props.pop(C.PROP_PRESENT_VALUE, None)
        dev.objects[oid] = obj
        return obj

    add(0, 1, "Zone Temperature", {85: Real(22.0), 28: CharacterString("Room 101 temperature"),
                                   117: Enumerated(62), 22: Real(0.2), 65: Real(50.0),
                                   69: Real(-10.0), 106: Real(0.1)}).cov_increment = 0.2
    add(0, 2, "Outside Air Temperature", {85: Real(31.5), 28: CharacterString("OAT sensor"),
                                          117: Enumerated(62), 22: Real(0.5)})
    add(0, 3, "Zone Humidity", {85: Real(45.0), 28: CharacterString("Room 101 RH"),
                                117: Enumerated(29), 22: Real(1.0)})
    add(0, 4, "Supply Air Pressure", {85: Real(250.0), 117: Enumerated(53), 22: Real(5.0),
                                      28: CharacterString("Duct static pressure")})
    add(1, 1, "Cooling Valve", {28: CharacterString("Chilled water valve command"),
                                117: Enumerated(98), 22: Real(1.0)}, True, Real(0.0))
    add(2, 1, "Zone Setpoint", {28: CharacterString("Occupied cooling setpoint"),
                                117: Enumerated(62), 22: Real(0.1)}, True, Real(23.0))
    add(2, 2, "Fan Speed Command", {117: Enumerated(98), 22: Real(1.0),
                                    28: CharacterString("Supply fan VFD speed")}, True, Real(60.0))
    add(3, 1, "Filter Alarm", {85: Enumerated(0), 84: Enumerated(0),
                               4: CharacterString("Dirty"), 46: CharacterString("Clean"),
                               28: CharacterString("Filter differential pressure switch")})
    add(3, 2, "Occupancy Sensor", {85: Enumerated(1), 84: Enumerated(0),
                                   4: CharacterString("Occupied"),
                                   46: CharacterString("Unoccupied")})
    add(4, 1, "Supply Fan Start/Stop", {84: Enumerated(0), 4: CharacterString("On"),
                                        46: CharacterString("Off")}, True, Enumerated(0))
    add(5, 1, "System Enable", {4: CharacterString("Enabled"), 46: CharacterString("Disabled")},
        True, Enumerated(1))
    add(19, 1, "Operating Mode", {74: Unsigned(4),
                                  110: [CharacterString(s) for s in
                                        ("Off", "Heating", "Cooling", "Auto")]},
        True, Unsigned(4))
    add(13, 1, "Fan Status", {85: Unsigned(2), 74: Unsigned(3),
                              110: [CharacterString(s) for s in ("Off", "Running", "Fault")]})
    for k in range(n_extra):
        add(2, 100 + k, f"Spare Value {k + 1:03d}", {85: Real(round(random.uniform(0, 100), 2)),
                                                     117: Enumerated(95)})

    dev_props: Dict[int, Any] = {
        75: dev.oid, 77: CharacterString(name), 79: Enumerated(C.OBJ_DEVICE),
        112: Enumerated(0), 121: CharacterString("Python BACnet Simulator"),
        120: Unsigned(999), 70: CharacterString("SIM-DDC-1"), 44: CharacterString("1.0.0"),
        12: CharacterString("BACnetExplorer simulator 1.0"),
        58: CharacterString("Test lab"), 28: CharacterString("Simulated HVAC controller"),
        98: Unsigned(1), 139: Unsigned(14),
        97: BitString([i in (5, 12, 14, 15, 26, 32, 34) for i in range(40)]),
        96: BitString([i in (0, 1, 2, 3, 4, 5, 8, 13, 19) for i in range(60)]),
        62: Unsigned(dev.max_apdu), 107: Enumerated(dev.segmentation), 167: Unsigned(64),
        11: Unsigned(3000), 73: Unsigned(3), 155: Unsigned(1), 30: [],
        119: X.Signed(-180), 24: False,
    }
    dev.objects[dev.oid] = SimObject(dev.oid, dev_props)
    dev_props[C.PROP_OBJECT_LIST] = [dev.oid] + [o for o in dev.objects if o != dev.oid]
    return dev

# ==========================================================================
# Equipment devices - one per graphic template, with realistic point names
# ==========================================================================
BO, BI, BV, AO, AI, AV, MV = 4, 3, 5, 1, 0, 2, 19

# (type, instance, name, initial value, units, rule)
#   rule: None                      -> static (commandable outputs/values are writable)
#         ("follow", src)           -> binary follows another point (src > 0 => 1)
#         ("follow_ok", src, fault) -> follows src unless the fault point is active
#         ("sine", base, amp, period, gate) -> analog wave; 0/low when gate point is off
#         ("pulse", period, on_secs, phase) -> alarm that comes on for a few seconds
#         ("track", src, noise, gate)      -> analog tracks another analog
EQUIPMENT = {
    "ahu_sr": ("SIM-AHU-SR-01", [
        (BO, 1, "Supply Fan Command", 1, None, None),
        (BI, 1, "Supply Fan Status", 1, None, ("follow", (BO, 1))),
        (BO, 2, "Return Fan Command", 1, None, None),
        (BI, 2, "Return Fan Status", 1, None, ("follow", (BO, 2))),
        (BI, 3, "DPS Flow Supply", 1, None, ("follow", (BI, 1))),
        (BI, 4, "DPS Flow Return", 1, None, ("follow", (BI, 2))),
        (BI, 5, "Pre Filter DPS", 0, None, ("pulse", 90, 15, 30)),
        (BI, 6, "Bag Filter DPS", 0, None, ("pulse", 150, 10, 100)),
        (AO, 1, "Cooling Valve", 55.0, 98, None),
        (AO, 2, "Fresh Air Damper", 35.0, 98, None),
        (AO, 3, "Return Air Damper", 65.0, 98, None),
        (AO, 4, "Exhaust Air Damper", 30.0, 98, None),
        (AO, 5, "Supply Air Damper", 100.0, 98, None),
        (AI, 1, "DPT Air Sensor", 250.0, 53, ("sine", 250, 12, 7, (BI, 1))),
        (AI, 2, "CO2 Sensor", 800.0, 96, ("sine", 820, 320, 60, None)),
        (AI, 3, "Supply Air Temp", 13.0, 62, ("sine", 13.5, 1.2, 25, None)),
        (AI, 4, "Return Air Temp", 24.0, 62, ("sine", 24, 0.6, 40, None)),
    ]),
    "fcu": ("SIM-FCU-01", [
        (MV, 1, "Fan Speed", 3, None, None),
        (BI, 1, "Fan Status", 1, None, ("follow", (MV, 1), 1)),
        (AO, 1, "Cooling Valve", 45.0, 98, None),
        (AI, 1, "Room Temp", 23.5, 62, ("sine", 23.5, 0.6, 50, None)),
        (AV, 1, "Setpoint", 23.0, 62, None),
        (AI, 2, "Supply Air Temp", 14.5, 62, ("sine", 14.5, 1.0, 30, (BI, 1))),
        (BI, 2, "Filter Alarm", 0, None, ("pulse", 120, 12, 60)),
        (BV, 1, "Occupancy", 1, None, None),
        (BI, 3, "FCU Alarm", 0, None, None),
    ]),
    "exhaust_fan": ("SIM-EF-01", [
        (BO, 1, "Fan Command", 1, None, None),
        (BI, 3, "Fan Trip", 0, None, ("pulse", 120, 8, 100)),
        (BI, 1, "Fan Status", 1, None, ("follow_ok", (BO, 1), (BI, 3))),
        (BI, 2, "Air Flow DPS", 1, None, ("follow", (BI, 1))),
        (AO, 1, "VFD Speed", 80.0, 98, None),
        (AO, 2, "Motorized Damper", 100.0, 98, None),
    ]),
    "vav": ("SIM-VAV-01", [
        (AV, 1, "Air Flow Setpoint", 400.0, 87, None),
        (AI, 1, "Air Flow", 400.0, 87, ("track", (AV, 1), 8, None)),
        (AO, 1, "Damper Position", 60.0, 98, None),
        (AO, 2, "Reheat Valve", 0.0, 98, None),
        (AI, 2, "Room Temp", 23.2, 62, ("sine", 23.2, 0.5, 45, None)),
        (AV, 2, "Room Setpoint", 23.0, 62, None),
        (AI, 3, "Discharge Air Temp", 14.0, 62, ("sine", 14.2, 0.8, 30, None)),
        (BV, 1, "Occupancy", 1, None, None),
    ]),
    "chiller": ("SIM-CHILLER-PLANT", [
        (BO, 1, 'Chiller 1 Command', 1, None, None),
        (BI, 1, 'Chiller 1 Alarm', 0, None, ('pulse', 240, 8, 100)),
        (BI, 2, 'Chiller 1 Run Status', 1, None, ('follow_ok', (BO, 1), (BI, 1))),
        (BI, 3, 'Chiller 1 Flow Switch', 1, None, ('follow', (BI, 2))),
        (AI, 1, 'Chiller 1 Leaving Temp', 6.7, 62, ('sine', 6.7, 0.3, 32, (BI, 2))),
        (BO, 2, 'Chiller 2 Command', 1, None, None),
        (BI, 4, 'Chiller 2 Alarm', 0, None, ('pulse', 240, 8, 200)),
        (BI, 5, 'Chiller 2 Run Status', 1, None, ('follow_ok', (BO, 2), (BI, 4))),
        (BI, 6, 'Chiller 2 Flow Switch', 1, None, ('follow', (BI, 5))),
        (AI, 2, 'Chiller 2 Leaving Temp', 6.7, 62, ('sine', 6.7, 0.3, 39, (BI, 5))),
        (BO, 3, 'Primary Pump 1 Command', 1, None, None),
        (BI, 7, 'Primary Pump 1 Trip Status', 0, None, None),
        (BI, 8, 'Primary Pump 1 Run Status', 1, None, ('follow_ok', (BO, 3), (BI, 7))),
        (BI, 9, 'Primary Pump 1 Flow Switch', 1, None, ('follow', (BI, 8))),
        (BI, 10, 'Primary Pump 1 Hand Status', 0, None, None),
        (BI, 11, 'Primary Pump 1 Auto Status', 1, None, ('inverse', (BI, 10))),
        (BO, 4, 'Primary Pump 2 Command', 0, None, None),
        (BI, 12, 'Primary Pump 2 Trip Status', 0, None, None),
        (BI, 13, 'Primary Pump 2 Run Status', 1, None, ('follow_ok', (BO, 4), (BI, 12))),
        (BI, 14, 'Primary Pump 2 Flow Switch', 1, None, ('follow', (BI, 13))),
        (BI, 15, 'Primary Pump 2 Hand Status', 0, None, None),
        (BI, 16, 'Primary Pump 2 Auto Status', 1, None, ('inverse', (BI, 15))),
        (BO, 5, 'Secondary Pump 1 Command', 1, None, None),
        (BI, 17, 'Secondary Pump 1 Trip Status', 0, None, None),
        (BI, 18, 'Secondary Pump 1 Run Status', 1, None, ('follow_ok', (BO, 5), (BI, 17))),
        (BI, 19, 'Secondary Pump 1 Flow Switch', 1, None, ('follow', (BI, 18))),
        (BI, 20, 'Secondary Pump 1 Hand Status', 0, None, ('pulse', 120, 15, 40)),
        (BI, 21, 'Secondary Pump 1 Auto Status', 1, None, ('inverse', (BI, 20))),
        (BO, 6, 'Secondary Pump 2 Command', 1, None, None),
        (BI, 22, 'Secondary Pump 2 Trip Status', 0, None, ('pulse', 150, 6, 100)),
        (BI, 23, 'Secondary Pump 2 Run Status', 1, None, ('follow_ok', (BO, 6), (BI, 22))),
        (BI, 24, 'Secondary Pump 2 Flow Switch', 1, None, ('follow', (BI, 23))),
        (BI, 25, 'Secondary Pump 2 Hand Status', 0, None, None),
        (BI, 26, 'Secondary Pump 2 Auto Status', 1, None, ('inverse', (BI, 25))),
        (AI, 3, 'Main Supply Temp', 7.0, 62, ('sine', 7.0, 0.3, 30, None)),
        (AI, 4, 'Main Return Temp', 12.4, 62, ('sine', 12.4, 0.4, 35, None)),
        (AI, 5, 'Main DPT', 95.0, 54, ('sine', 95, 6, 9, None)),
        (AI, 6, 'Main Flow Meter', 84.0, 87, ('sine', 84, 6, 14, None)),
        (AI, 7, 'Building Load', 1100.0, 48, ('sine', 1100, 200, 40, None)),
    ]),
    "pump_set": ("SIM-PUMP-01", [
        (BO, 1, "Pump 1 Command", 1, None, None),
        (BI, 2, "Pump 1 Fault", 0, None, None),
        (BI, 1, "Pump 1 Status", 1, None, ("follow_ok", (BO, 1), (BI, 2))),
        (AO, 1, "Pump 1 Speed", 75.0, 98, None),
        (BO, 2, "Pump 2 Command", 0, None, None),
        (BI, 4, "Pump 2 Fault", 0, None, None),
        (BI, 3, "Pump 2 Status", 0, None, ("follow_ok", (BO, 2), (BI, 4))),
        (AO, 2, "Pump 2 Speed", 0.0, 98, None),
        (AV, 1, "DP Setpoint", 120.0, 54, None),
        (AI, 1, "Differential Pressure", 120.0, 54, ("sine", 120, 6, 9, ((BI, 1), (BI, 3)))),
        (AI, 2, "Flow Rate", 30.0, 87, ("sine", 30, 3, 12, ((BI, 1), (BI, 3)))),
    ]),
}


def build_equipment_device(instance: int, kind: str, route: Tuple[int, bytes]) -> SimDevice:
    name, spec = EQUIPMENT[kind]
    dev = SimDevice(instance, name, route)
    for t, i, nm, init, units, rule in spec:
        oid = ObjectId(t, i)
        if t in (BO, BI, BV):
            val: Any = Enumerated(int(init))
        elif t == MV:
            val = Unsigned(int(init))
        else:
            val = Real(float(init))
        p: Dict[int, Any] = {75: oid, 77: CharacterString(nm), 79: Enumerated(t),
                             C.PROP_STATUS_FLAGS: _status(), C.PROP_EVENT_STATE: Enumerated(0),
                             C.PROP_OUT_OF_SERVICE: False, C.PROP_RELIABILITY: Enumerated(0),
                             28: CharacterString(f"{name} {nm}")}
        if units is not None:
            p[117] = Enumerated(units)
            p[22] = Real(0.1)
        if t in (BO, BI, BV):
            p[84] = Enumerated(0)
            p[4], p[46] = CharacterString("On"), CharacterString("Off")
        if t == MV:
            p[74] = Unsigned(4)
            p[110] = [CharacterString(x) for x in ("Off", "Low", "Medium", "High")]
        obj = SimObject(oid, p)
        if t in (BO, AO, AV, BV, MV):   # commandable
            obj.priority_array = [NULL] * 16
            obj.props[C.PROP_RELINQUISH_DEFAULT] = val
        else:
            obj.props[C.PROP_PRESENT_VALUE] = val
        obj.cov_increment = 0.5 if units not in (96, 53, 87) else 5.0
        dev.objects[oid] = obj
        if rule:
            dev.rules.append((oid, rule))
    dev_props: Dict[int, Any] = {
        75: dev.oid, 77: CharacterString(name), 79: Enumerated(C.OBJ_DEVICE), 112: Enumerated(0),
        121: CharacterString("Python BACnet Simulator"), 120: Unsigned(999),
        70: CharacterString(f"SIM-{kind.upper()}"), 44: CharacterString("1.0.0"),
        12: CharacterString("BACnetExplorer simulator 1.1"), 58: CharacterString("Plant room"),
        28: CharacterString(f"Simulated {kind}"), 98: Unsigned(1), 139: Unsigned(14),
        97: BitString([i in (5, 12, 14, 15, 26, 32, 34) for i in range(40)]),
        62: Unsigned(dev.max_apdu), 107: Enumerated(dev.segmentation), 11: Unsigned(3000),
        73: Unsigned(3),
    }
    dev.objects[dev.oid] = SimObject(dev.oid, dev_props)
    dev_props[C.PROP_OBJECT_LIST] = [dev.oid] + [o for o in dev.objects if o != dev.oid]
    return dev


def run_rules(dev: SimDevice, t: float):
    ob = dev.objects

    def pv(key) -> float:
        o = ob.get(ObjectId(*key))
        return float(o.present_value()) if o else 0.0

    def gate_on(g) -> bool:
        if g is None:
            return True
        if isinstance(g[0], tuple):
            return any(pv(x) > 0 for x in g)
        return pv(g) > 0

    for oid, rule in dev.rules:
        o = ob[oid]
        if o.props.get(C.PROP_OUT_OF_SERVICE) or o.commandable:
            continue
        kind = rule[0]
        if kind == "follow":
            thr = rule[2] if len(rule) > 2 else 0
            o.props[85] = Enumerated(1 if pv(rule[1]) > thr else 0)
        elif kind == "follow_ok":
            o.props[85] = Enumerated(1 if pv(rule[1]) > 0 and pv(rule[2]) == 0 else 0)
        elif kind == "pulse":
            period, on, phase = rule[1:]
            o.props[85] = Enumerated(1 if (t + phase) % period < on else 0)
        elif kind == "sine":
            base, amp, per, gate = rule[1:]
            v = base + amp * math.sin(t / per) + random.uniform(-amp, amp) * 0.05
            if not gate_on(gate):
                v = base * 0.05 if base > 50 else v
                if o.props.get(117) == Enumerated(98):
                    v = 0.0
            o.props[85] = Real(round(v, 2))
        elif kind == "inverse":
            o.props[85] = Enumerated(0 if pv(rule[1]) > 0 else 1)
        elif kind == "track":
            src, noise, _ = rule[1:]
            o.props[85] = Real(round(pv(src) + random.uniform(-noise, noise), 1))


class Simulator:
    def __init__(self, port: int, instance: int, routed: int, big: int, equipment: bool = True):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", port))
        self.port = port
        self.devices: List[SimDevice] = [build_device(instance, f"SIM-AHU-{instance}", big)]
        if equipment:
            for k, kind in enumerate(EQUIPMENT):
                self.devices.append(build_equipment_device(3001 + k, kind,
                                                           (EQUIPMENT_NET, bytes([k + 1]))))
        for k in range(routed):
            mac = bytes([10 + k])
            self.devices.append(build_device(instance + 1 + k, f"SIM-VAV-{instance + 1 + k}", 0,
                                             (ROUTED_NET, mac)))
        self.lock = threading.Lock()
        self.invoke = 0
        # segmented transmissions in progress: key (addr, invoke) -> state
        self.seg_tx: Dict[Tuple[Tuple[str, int], int], dict] = {}
        self.t0 = time.time()

    # ---------------------------------------------------------------- send helpers
    def _npdu(self, route: Optional[Tuple[int, bytes]], dest: Optional[Tuple[int, bytes]] = None,
              expecting_reply: bool = False) -> bytes:
        control = 0x04 if expecting_reply else 0
        out = bytearray([0x01, control])
        if dest is not None:
            out[1] |= 0x20
            out += struct.pack(">HB", dest[0], len(dest[1])) + dest[1]
        if route is not None:
            out[1] |= 0x08
            out += struct.pack(">HB", route[0], len(route[1])) + route[1]
        if dest is not None:
            out.append(255)
        return bytes(out)

    def send(self, addr: Tuple[str, int], apdu: bytes, route=None, dest=None,
             broadcast: bool = False, expecting_reply: bool = False):
        func = C.BVLC_ORIGINAL_BROADCAST if broadcast else C.BVLC_ORIGINAL_UNICAST
        self.sock.sendto(X.encode_bvlc(func, self._npdu(route, dest, expecting_reply) + apdu), addr)

    # ---------------------------------------------------------------- main loop
    def run(self):
        threading.Thread(target=self._update_loop, daemon=True).start()
        print(f"BACnet simulator listening on UDP {self.port}")
        for d in self.devices:
            where = f"net {d.route[0]} mac {d.route[1][0]}" if d.route else "local"
            print(f"  device {d.instance:<7} '{d.name}'  {len(d.objects)} objects  ({where})")
        while True:
            data, addr = self.sock.recvfrom(65535)
            try:
                with self.lock:
                    self.handle(data, addr)
            except Exception as e:
                print(f"error handling packet from {addr}: {e!r}")

    def handle(self, data: bytes, addr: Tuple[str, int]):
        pkt = X.decode_packet(data, addr[0], addr[1])
        if not pkt.apdu:
            return
        reply_addr = (pkt.src_ip, pkt.src_port)
        remote_src = (pkt.snet, pkt.sadr) if pkt.snet is not None else None
        # Which device(s) is this for?
        npdu = pkt.bvlc_payload[6:] if pkt.bvlc_function == C.BVLC_FORWARDED_NPDU else pkt.bvlc_payload
        dnet, dadr = None, b""
        if len(npdu) > 2 and npdu[1] & 0x20:
            dnet = struct.unpack_from(">H", npdu, 2)[0]
            dadr = bytes(npdu[5:5 + npdu[4]])
        if dnet is None:
            targets = [self.devices[0]]
        elif dnet == 0xFFFF:
            targets = self.devices
        else:
            targets = [d for d in self.devices if d.route and d.route[0] == dnet
                       and (not dadr or d.route[1] == dadr)]
        apdu = X.parse_apdu(pkt.apdu)
        for dev in targets:
            self.handle_apdu(dev, apdu, reply_addr, remote_src)

    def handle_apdu(self, dev: SimDevice, apdu: X.APDU, addr, remote_src):
        def reply(raw: bytes):
            self.send(addr, raw, dev.route, remote_src)

        if apdu.pdu_type == C.PDU_UNCONFIRMED_REQUEST:
            if apdu.service == C.SERVICE_WHO_IS:
                w = X.parse_who_is(apdu.data)
                if w.low is None or (w.low <= dev.instance <= (w.high or 0)):
                    reply(X.apdu_i_am(dev.instance, dev.max_apdu, dev.segmentation, 999))
            elif apdu.service in (C.SERVICE_TIME_SYNCHRONIZATION,
                                  C.SERVICE_UTC_TIME_SYNCHRONIZATION):
                vals, _ = X.decode_values(apdu.data)
                print(f"device {dev.instance}: time sync -> {vals[0]} {vals[1]}")
            elif apdu.service == C.SERVICE_WHO_HAS:
                vals, _ = X.decode_values(apdu.data)
                for v in vals:
                    if isinstance(v, X.ContextValue) and v.tag == 3:
                        name = X.decode_charstring(v.data)
                        for o in dev.objects.values():
                            if str(o.props.get(77)) == name:
                                reply(bytes([0x10, C.SERVICE_I_HAVE]) +
                                      X.encode_application(dev.oid) +
                                      X.encode_application(o.oid) +
                                      X.encode_application(CharacterString(name)))
            return
        if apdu.pdu_type == C.PDU_SEGMENT_ACK:
            self._continue_segments(dev, addr, remote_src, apdu)
            return
        if apdu.pdu_type != C.PDU_CONFIRMED_REQUEST:
            return
        iid, svc = apdu.invoke_id or 0, apdu.service or 0
        try:
            if svc == C.SERVICE_READ_PROPERTY:
                oid, prop, idx = X.parse_read_property_request(apdu.data)
                obj = self._obj(dev, oid)
                body = X.body_read_property_ack(obj.oid, prop, idx, obj.get(prop, idx))
                self._send_ack(dev, addr, remote_src, apdu, body)
            elif svc == C.SERVICE_READ_PROPERTY_MULTIPLE:
                reqs = X.parse_rpm_request(apdu.data)
                body = bytearray()
                for oid, props in reqs:
                    obj = self._obj(dev, oid)
                    body += X.ctx_objid(0, obj.oid) + X.opening_tag(1)
                    if any(p in (8, 80, 105) for p, _ in props):
                        props = [(p, None) for p in obj.property_ids()]
                    for prop, idx in props:
                        body += X.ctx_enumerated(2, prop)
                        if idx is not None:
                            body += X.ctx_unsigned(3, idx)
                        try:
                            v = obj.get(prop, idx)
                            body += X.opening_tag(4) + X.encode_application(v) + X.closing_tag(4)
                        except PropError as pe:
                            body += X.opening_tag(5) + X.encode_application(Enumerated(pe.cls)) + \
                                X.encode_application(Enumerated(pe.code)) + X.closing_tag(5)
                    body += X.closing_tag(1)
                self._send_ack(dev, addr, remote_src, apdu, bytes(body))
            elif svc == C.SERVICE_WRITE_PROPERTY:
                oid, prop, idx, value, prio = X.parse_write_property_request(apdu.data)
                self._write(self._obj(dev, oid), prop, value, prio)
                reply(X.apdu_simple_ack(iid, svc))
                self._check_cov(dev, force_oid=oid)
            elif svc == C.SERVICE_SUBSCRIBE_COV:
                pid, oid, confirmed, lifetime = X.parse_subscribe_cov_request(apdu.data)
                obj = self._obj(dev, oid)
                dev.covs = [c for c in dev.covs if not (c.address == addr and c.pid == pid
                                                        and c.oid == oid)]
                if confirmed is not None:
                    dev.covs.append(COVSub(addr, pid, oid, confirmed,
                                           time.time() + (lifetime or 10 ** 9), dev.route,
                                           remote_src))
                reply(X.apdu_simple_ack(iid, svc))
                if confirmed is not None:
                    self._notify(dev, dev.covs[-1], obj)
            elif svc == C.SERVICE_REINITIALIZE_DEVICE:
                reply(X.apdu_simple_ack(iid, svc))
            else:
                reply(X.apdu_reject(iid, 9))
        except PropError as e:
            reply(X.apdu_error(iid, svc, e.cls, e.code))
        except X.BACnetDecodeError:
            reply(X.apdu_reject(iid, 4))

    # ---------------------------------------------------------------- segmentation
    def _send_ack(self, dev: SimDevice, addr, remote_src, req: X.APDU, body: bytes):
        iid, svc = req.invoke_id or 0, req.service or 0
        max_len = min(req.max_apdu, dev.max_apdu)
        if len(body) + 3 <= max_len:
            self.send(addr, X.apdu_complex_ack(iid, svc, body), dev.route, remote_src)
            return
        if not req.segmented_accepted:
            self.send(addr, X.apdu_abort(iid, 4), dev.route, remote_src)
            return
        size = max_len - 5
        segs = [body[i:i + size] for i in range(0, len(body), size)]
        self.seg_tx[(addr, iid)] = {"segs": segs, "svc": svc}
        self._send_segment(dev, addr, remote_src, iid, 0)

    def _send_segment(self, dev, addr, remote_src, iid, seq):
        st = self.seg_tx.get((addr, iid))
        if not st or seq >= len(st["segs"]):
            return
        more = seq < len(st["segs"]) - 1
        b0 = (C.PDU_COMPLEX_ACK << 4) | 0x08 | (0x04 if more else 0)
        raw = bytes([b0, iid, seq, 4, st["svc"]]) + st["segs"][seq]
        self.send(addr, raw, dev.route, remote_src)
        if not more:
            self.seg_tx.pop((addr, iid), None)

    def _continue_segments(self, dev, addr, remote_src, ack: X.APDU):
        st = self.seg_tx.get((addr, ack.invoke_id or 0))
        if st:
            nxt = ack.seq + 1 if not ack.nak else ack.seq + 1
            self._send_segment(dev, addr, remote_src, ack.invoke_id, nxt)

    # ---------------------------------------------------------------- objects
    def _obj(self, dev: SimDevice, oid: ObjectId) -> SimObject:
        if oid.type == C.OBJ_DEVICE and oid.instance == 4194303:
            oid = dev.oid
        obj = dev.objects.get(oid)
        if obj is None:
            raise PropError(1, 31)  # object / unknown-object
        return obj

    def _write(self, obj: SimObject, prop: int, value: Any, prio: Optional[int]):
        if prop == C.PROP_PRESENT_VALUE:
            if obj.commandable:
                p = (prio or 16) - 1
                if not 0 <= p < 16 or p == 5:
                    raise PropError(2, 37)
                assert obj.priority_array is not None
                obj.priority_array[p] = NULL if isinstance(value, X.Null) else value
                return
            if not obj.props.get(C.PROP_OUT_OF_SERVICE) and obj.oid.type in (0, 3, 13):
                raise PropError(2, 40)  # write-access-denied (inputs need OOS)
            if isinstance(value, X.Null):
                raise PropError(2, 9)
            obj.props[C.PROP_PRESENT_VALUE] = value
            return
        if prop in (77, 28, 81, 22, 117, 104, 65, 69, 4, 46, 58):
            if prop == C.PROP_OUT_OF_SERVICE:
                obj.props[prop] = bool(value)
                flags = obj.props[C.PROP_STATUS_FLAGS]
                flags.bits[3] = bool(value)
                return
            obj.props[prop] = value
            return
        if prop in obj.props or prop in (75, 79, 87, 111, 371):
            raise PropError(2, 40)
        raise PropError(2, 32)

    # ---------------------------------------------------------------- dynamics / COV
    def _update_loop(self):
        while True:
            time.sleep(1.0)
            t = time.time() - self.t0
            with self.lock:
                for dev in self.devices:
                    if dev.rules:
                        run_rules(dev, t)
                        self._check_cov(dev)
                        continue
                    off = dev.instance % 7
                    ob = dev.objects
                    def setpv(oid, v):
                        o = ob.get(oid)
                        if o and not o.props.get(C.PROP_OUT_OF_SERVICE) and not o.commandable:
                            o.props[C.PROP_PRESENT_VALUE] = v
                    setpv(ObjectId(0, 1), Real(round(22 + 1.5 * math.sin((t + off) / 20), 2)))
                    setpv(ObjectId(0, 2), Real(round(31 + 3 * math.sin((t + off) / 90), 2)))
                    setpv(ObjectId(0, 3), Real(round(45 + 5 * math.sin((t + off) / 35)
                                                     + random.uniform(-0.3, 0.3), 1)))
                    setpv(ObjectId(0, 4), Real(round(250 + random.uniform(-8, 8), 1)))
                    setpv(ObjectId(3, 1), Enumerated(1 if int(t / 30) % 2 else 0))
                    self._check_cov(dev)
                    now = time.time()
                    dev.covs = [c for c in dev.covs if c.expires > now]

    def _check_cov(self, dev: SimDevice, force_oid: Optional[ObjectId] = None):
        for obj in dev.objects.values():
            pv = obj.present_value() if C.PROP_PRESENT_VALUE in obj.props or obj.commandable else None
            if pv is None:
                continue
            last = obj.last_cov_value
            changed = obj.oid == force_oid or last is None
            if not changed:
                if isinstance(pv, float) and isinstance(last, float):
                    changed = abs(pv - last) >= obj.cov_increment
                else:
                    changed = pv != last
            if changed:
                obj.last_cov_value = pv
                for sub in dev.covs:
                    if sub.oid == obj.oid:
                        self._notify(dev, sub, obj)

    def _notify(self, dev: SimDevice, sub: COVSub, obj: SimObject):
        remaining = max(0, int(sub.expires - time.time())) if sub.expires < 10 ** 9 else 0
        body = X.body_cov_notification(sub.pid, dev.instance, obj.oid, remaining,
                                       [(C.PROP_PRESENT_VALUE, obj.present_value()),
                                        (C.PROP_STATUS_FLAGS, obj.props[C.PROP_STATUS_FLAGS])])
        if sub.confirmed:
            self.invoke = (self.invoke + 1) % 256
            apdu = X.confirmed_header(self.invoke, C.SERVICE_CONFIRMED_COV_NOTIFICATION, False) + body
            self.send(sub.address, apdu, dev.route, sub.dnet, expecting_reply=True)
        else:
            apdu = bytes([0x10, C.SERVICE_UNCONFIRMED_COV_NOTIFICATION]) + body
            self.send(sub.address, apdu, dev.route, sub.dnet)


def main():
    ap = argparse.ArgumentParser(description="BACnet/IP device simulator")
    ap.add_argument("--port", type=int, default=47809, help="UDP port (default 47809)")
    ap.add_argument("--device", type=int, default=1001, help="device instance (default 1001)")
    ap.add_argument("--routed", type=int, default=2,
                    help=f"number of virtual devices behind router network {ROUTED_NET} (default 2)")
    ap.add_argument("--no-equipment", action="store_true",
                    help=f"don't simulate the equipment devices 3001-3006 on network {EQUIPMENT_NET}")
    ap.add_argument("--big", type=int, default=150,
                    help="extra AV objects on the main device, forces segmentation (default 150)")
    args = ap.parse_args()
    Simulator(args.port, args.device, args.routed, args.big, not args.no_equipment).run()


if __name__ == "__main__":
    main()
