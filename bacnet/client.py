"""
BACnet/IP client: networking, transaction state machine (with segmentation of
responses), discovery and the high-level services used by the explorer.
"""
from __future__ import annotations

import ipaddress
import socket
import struct
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from . import constants as C
from . import codec as X
from .codec import Address, ObjectId


# ==========================================================================
# Exceptions
# ==========================================================================
class BACnetException(Exception):
    pass


class BACnetTimeout(BACnetException):
    pass


class BACnetError(BACnetException):
    def __init__(self, err_class: int, err_code: int):
        self.err_class, self.err_code = err_class, err_code
        super().__init__(f"Error: {C.ERROR_CLASS.get(err_class, err_class)} / "
                         f"{C.ERROR_CODE.get(err_code, err_code)}")


class BACnetReject(BACnetException):
    def __init__(self, reason: int):
        self.reason = reason
        super().__init__(f"Reject: {C.REJECT_REASON.get(reason, reason)}")


class BACnetAbort(BACnetException):
    def __init__(self, reason: int):
        self.reason = reason
        super().__init__(f"Abort: {C.ABORT_REASON.get(reason, reason)}")


# ==========================================================================
# Network interface discovery
# ==========================================================================
@dataclass
class Interface:
    name: str
    ip: str
    netmask: str
    broadcast: str

    def __str__(self):
        return f"{self.ip}  ({self.name})"


def list_interfaces() -> List[Interface]:
    result: List[Interface] = []
    try:
        import psutil  # optional
        for name, addrs in psutil.net_if_addrs().items():
            for a in addrs:
                if a.family == socket.AF_INET and a.address and not a.address.startswith("169.254"):
                    mask = a.netmask or "255.255.255.0"
                    net = ipaddress.IPv4Network(f"{a.address}/{mask}", strict=False)
                    result.append(Interface(name, a.address, mask, str(net.broadcast_address)))
    except Exception:
        pass
    if not result:
        ips = set()
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ips.add(info[4][0])
        except Exception:
            pass
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
            s.close()
        except Exception:
            pass
        ips.add("127.0.0.1")
        for ip in sorted(ips):
            net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
            result.append(Interface("auto (/24 assumed)", ip, "255.255.255.0",
                                    str(net.broadcast_address)))
    result.sort(key=lambda i: (i.ip.startswith("127."), i.ip))
    return result


# ==========================================================================
# Data model
# ==========================================================================
@dataclass
class DeviceInfo:
    instance: int
    address: Address
    max_apdu: int = 1476
    segmentation: int = 3
    vendor_id: int = 0
    name: str = ""
    vendor_name: str = ""
    model_name: str = ""
    last_seen: float = field(default_factory=time.time)
    objects: List[ObjectId] = field(default_factory=list)
    object_names: Dict[ObjectId, str] = field(default_factory=dict)
    supports_rpm: Optional[bool] = None

    @property
    def oid(self) -> ObjectId:
        return ObjectId(C.OBJ_DEVICE, self.instance)

    @property
    def can_receive_segments(self) -> bool:
        return self.segmentation in (0, 1)  # segmented-both / segmented-transmit


@dataclass
class Subscription:
    sub_id: int
    device: DeviceInfo
    object_id: ObjectId
    mode: str = "cov"              # 'cov' or 'poll'
    confirmed: bool = False
    lifetime: int = 300
    poll_interval: float = 5.0
    value: Any = None
    status_flags: Any = None
    last_update: float = 0.0
    subscribed_at: float = 0.0
    next_poll: float = 0.0
    state: str = "pending"
    history: List[Tuple[float, float]] = field(default_factory=list)
    graph: bool = True
    name: str = ""

    def record(self, value: Any):
        self.value = value
        self.last_update = time.time()
        num = None
        if isinstance(value, bool):
            num = 1.0 if value else 0.0
        elif isinstance(value, (int, float)):
            num = float(value)
        if num is not None:
            self.history.append((self.last_update, num))
            if len(self.history) > 5000:
                del self.history[:1000]


@dataclass
class _Transaction:
    invoke_id: int
    address: Address
    service: int
    event: threading.Event = field(default_factory=threading.Event)
    result: Optional[X.APDU] = None
    error: Optional[Exception] = None
    segments: List[bytes] = field(default_factory=list)
    expected_seq: int = 0
    last_activity: float = field(default_factory=time.time)


# ==========================================================================
# Client
# ==========================================================================
class BACnetClient:
    def __init__(self, local_ip: str = "0.0.0.0", port: int = C.BACNET_PORT,
                 broadcast_ip: str = "255.255.255.255", timeout: float = 3.0, retries: int = 2):
        self.local_ip = local_ip
        self.port = port
        self.broadcast_ip = broadcast_ip
        self.timeout = timeout
        self.retries = retries
        self.remote_port = C.BACNET_PORT   # UDP port that broadcasts are sent to
        self.refresh_interval = 1.0        # seconds between value refreshes
        self.auto_refresh = True           # poll every subscription (COV ones too)
        self._polling: set = set()         # device instances with a batch poll in flight
        self.sock: Optional[socket.socket] = None
        self.running = False
        self._rx_thread: Optional[threading.Thread] = None
        self._maint_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._transactions: Dict[int, _Transaction] = {}
        self._next_invoke = 1
        self._local_addrs: set = set()

        self.devices: Dict[int, DeviceInfo] = {}
        self.subscriptions: Dict[int, Subscription] = {}
        self._next_sub_id = 1
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bacnet-poll")

        # foreign device registration
        self.bbmd: Optional[Tuple[str, int]] = None
        self.bbmd_ttl = 900
        self._bbmd_next = 0.0

        # callbacks
        self.on_log: Callable[[str, str], None] = lambda level, msg: None
        self.on_device: Callable[[DeviceInfo, bool], None] = lambda dev, new: None
        self.on_i_have: Callable[[X.IHave, Address], None] = lambda ih, addr: None
        self.on_subscription: Callable[[Subscription], None] = lambda sub: None
        self.trace_packets = False

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        bind_ip = self.local_ip or "0.0.0.0"
        # On Linux/macOS binding to a unicast address prevents receiving broadcasts,
        # so bind to all interfaces there. Windows delivers broadcasts to bound sockets.
        if not sys.platform.startswith("win"):
            bind_ip = "0.0.0.0"
        try:
            s.bind((bind_ip, self.port))
        except OSError as e:
            s.close()
            raise BACnetException(f"Cannot bind UDP {bind_ip}:{self.port} - {e}. "
                                  "Is another BACnet tool running? Try another port.") from e
        s.settimeout(0.5)
        self.sock = s
        self.port = s.getsockname()[1]
        self._local_addrs = {(self.local_ip, self.port), ("127.0.0.1", self.port)}
        self.running = True
        self._rx_thread = threading.Thread(target=self._rx_loop, name="bacnet-rx", daemon=True)
        self._rx_thread.start()
        self._maint_thread = threading.Thread(target=self._maintenance_loop,
                                              name="bacnet-maint", daemon=True)
        self._maint_thread.start()
        self.on_log("info", f"BACnet/IP started on {bind_ip}:{self.port} "
                            f"(local {self.local_ip}, broadcast {self.broadcast_ip})")

    def stop(self):
        self.running = False
        for sub in list(self.subscriptions.values()):
            if sub.mode == "cov" and sub.state == "active":
                try:
                    self.cancel_cov(sub.device.address, sub.sub_id, sub.object_id, timeout=1.0)
                except Exception:
                    pass
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None
        with self._lock:
            for tx in self._transactions.values():
                tx.error = BACnetException("network stopped")
                tx.event.set()
            self._transactions.clear()
        self.on_log("info", "BACnet/IP stopped")

    # ------------------------------------------------------------------ sending
    def _sendto(self, data: bytes, ip: str, port: int):
        if not self.sock:
            raise BACnetException("Network not started")
        if self.trace_packets:
            self.on_log("trace", f"TX {ip}:{port}  {data.hex(' ')}")
        self.sock.sendto(data, (ip, port))

    def send_apdu(self, address: Address, apdu: bytes, expecting_reply: bool = False):
        if address.net is not None:
            npdu = X.encode_npdu(expecting_reply, address.net, address.mac)
        else:
            npdu = X.encode_npdu(expecting_reply)
        self._sendto(X.encode_bvlc(C.BVLC_ORIGINAL_UNICAST, npdu + apdu), address.ip, address.port)

    def broadcast_apdu(self, apdu: bytes, global_broadcast: bool = True,
                       target: Optional[Tuple[str, int]] = None):
        npdu = X.encode_npdu(False, 0xFFFF if global_broadcast else None, b"")
        payload = npdu + apdu
        if self.bbmd:
            self._sendto(X.encode_bvlc(C.BVLC_DISTRIBUTE_BROADCAST, payload), *self.bbmd)
        ip, port = target or (self.broadcast_ip, self.remote_port)
        self._sendto(X.encode_bvlc(C.BVLC_ORIGINAL_BROADCAST, payload), ip, port)

    # ------------------------------------------------------------------ foreign device
    def register_foreign_device(self, bbmd_ip: str, bbmd_port: int = C.BACNET_PORT,
                                ttl: int = 900):
        self.bbmd = (bbmd_ip, bbmd_port)
        self.bbmd_ttl = ttl
        self._send_fd_registration()

    def _send_fd_registration(self):
        if not self.bbmd:
            return
        self._sendto(X.encode_bvlc(C.BVLC_REGISTER_FOREIGN_DEVICE, struct.pack(">H", self.bbmd_ttl)),
                     *self.bbmd)
        self._bbmd_next = time.time() + max(30, self.bbmd_ttl * 0.8)
        self.on_log("info", f"Register-Foreign-Device sent to {self.bbmd[0]}:{self.bbmd[1]} "
                            f"(TTL {self.bbmd_ttl}s)")

    # ------------------------------------------------------------------ transactions
    def _alloc_invoke(self) -> int:
        with self._lock:
            for _ in range(256):
                iid = self._next_invoke
                self._next_invoke = (self._next_invoke + 1) % 256
                if iid not in self._transactions:
                    return iid
        raise BACnetException("No free invoke IDs (too many outstanding requests)")

    def request(self, address: Address, service: int, body: bytes,
                timeout: Optional[float] = None, retries: Optional[int] = None) -> X.APDU:
        """Send a confirmed request and wait for its acknowledgement."""
        timeout = self.timeout if timeout is None else timeout
        retries = self.retries if retries is None else retries
        iid = self._alloc_invoke()
        tx = _Transaction(iid, address, service)
        with self._lock:
            self._transactions[iid] = tx
        try:
            apdu = X.confirmed_header(iid, service) + body
            for attempt in range(retries + 1):
                tx.last_activity = time.time()
                self.send_apdu(address, apdu, expecting_reply=True)
                # wait, extending the deadline while segments keep arriving
                while True:
                    remaining = tx.last_activity + timeout - time.time()
                    if remaining <= 0 or tx.event.wait(remaining):
                        break
                if tx.event.is_set():
                    break
                if tx.segments:
                    break  # segmented transfer stalled - don't resend the request
                if attempt < retries:
                    self.on_log("debug", f"Retry {attempt + 1} invoke {iid} to {address}")
            if not tx.event.is_set():
                raise BACnetTimeout(f"No response from {address} "
                                    f"({C.CONFIRMED_SERVICE_NAMES.get(service, service)})")
            if tx.error:
                raise tx.error
            assert tx.result is not None
            return tx.result
        finally:
            with self._lock:
                self._transactions.pop(iid, None)

    # ------------------------------------------------------------------ receiving
    def _rx_loop(self):
        while self.running:
            try:
                assert self.sock is not None
                data, (ip, port) = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    time.sleep(0.1)
                continue
            if self.trace_packets:
                self.on_log("trace", f"RX {ip}:{port}  {data.hex(' ')}")
            try:
                self._handle_datagram(data, ip, port)
            except X.BACnetDecodeError as e:
                self.on_log("debug", f"Decode error from {ip}:{port}: {e}")
            except Exception as e:  # never kill the receive thread
                self.on_log("error", f"Error handling packet from {ip}:{port}: {e!r}")

    def _handle_datagram(self, data: bytes, ip: str, port: int):
        pkt = X.decode_packet(data, ip, port)
        if pkt.bvlc_function == C.BVLC_RESULT:
            code = struct.unpack(">H", pkt.bvlc_payload[:2])[0] if len(pkt.bvlc_payload) >= 2 else 0
            level = "info" if code == 0 else "warning"
            self.on_log(level, f"BVLC-Result from {ip}:{port}: "
                               f"{C.BVLC_RESULT_CODES.get(code, hex(code))}")
            return
        if pkt.network_message is not None or not pkt.apdu:
            return
        src = pkt.source
        apdu = X.parse_apdu(pkt.apdu)

        if apdu.pdu_type == C.PDU_UNCONFIRMED_REQUEST:
            self._handle_unconfirmed(apdu, src)
            return
        if apdu.pdu_type == C.PDU_CONFIRMED_REQUEST:
            self._handle_confirmed(apdu, src)
            return

        with self._lock:
            tx = self._transactions.get(apdu.invoke_id) if apdu.invoke_id is not None else None
        if tx is None or tx.event.is_set():
            return
        tx.last_activity = time.time()
        if apdu.pdu_type == C.PDU_COMPLEX_ACK and apdu.segmented:
            self._handle_segment(tx, apdu, src)
            return
        if apdu.pdu_type in (C.PDU_SIMPLE_ACK, C.PDU_COMPLEX_ACK):
            tx.result = apdu
        elif apdu.pdu_type == C.PDU_ERROR:
            tx.error = BACnetError(*X.parse_error(apdu.data))
        elif apdu.pdu_type == C.PDU_REJECT:
            tx.error = BACnetReject(apdu.reason or 0)
        elif apdu.pdu_type == C.PDU_ABORT:
            tx.error = BACnetAbort(apdu.reason or 0)
        else:
            return
        tx.event.set()

    def _handle_segment(self, tx: _Transaction, apdu: X.APDU, src: Address):
        if apdu.seq == tx.expected_seq:
            tx.segments.append(apdu.data)
            tx.expected_seq = (tx.expected_seq + 1) % 256
            self.send_apdu(src, X.apdu_segment_ack(apdu.invoke_id or 0, apdu.seq, 1))
            if not apdu.more_follows:
                tx.result = X.APDU(C.PDU_COMPLEX_ACK, apdu.invoke_id, apdu.service,
                                   b"".join(tx.segments))
                tx.event.set()
        else:
            # duplicate or out of order: re-acknowledge last good segment (NAK)
            last = (tx.expected_seq - 1) % 256
            self.send_apdu(src, X.apdu_segment_ack(apdu.invoke_id or 0, last, 1, nak=True))

    def _handle_unconfirmed(self, apdu: X.APDU, src: Address):
        if apdu.service == C.SERVICE_I_AM:
            iam = X.parse_i_am(apdu.data)
            with self._lock:
                dev = self.devices.get(iam.device)
                new = dev is None
                if new:
                    dev = DeviceInfo(iam.device, src, iam.max_apdu, iam.segmentation, iam.vendor)
                    self.devices[iam.device] = dev
                else:
                    assert dev is not None
                    dev.address, dev.max_apdu = src, iam.max_apdu
                    dev.segmentation, dev.vendor_id = iam.segmentation, iam.vendor
                    dev.last_seen = time.time()
            if new:
                self.on_log("info", f"I-Am device {iam.device} from {src} "
                                    f"(vendor {iam.vendor}, max APDU {iam.max_apdu}, "
                                    f"{C.SEGMENTATION.get(iam.segmentation, iam.segmentation)})")
            self.on_device(dev, new)
        elif apdu.service == C.SERVICE_I_HAVE:
            ih = X.parse_i_have(apdu.data)
            self.on_log("info", f"I-Have: device {ih.device} has {ih.object_id} "
                                f"'{ih.object_name}'")
            self.on_i_have(ih, src)
        elif apdu.service == C.SERVICE_UNCONFIRMED_COV_NOTIFICATION:
            self._handle_cov(X.parse_cov_notification(apdu.data))

    def _handle_confirmed(self, apdu: X.APDU, src: Address):
        if apdu.service == C.SERVICE_CONFIRMED_COV_NOTIFICATION and not apdu.segmented:
            note = X.parse_cov_notification(apdu.data)
            self.send_apdu(src, X.apdu_simple_ack(apdu.invoke_id or 0, apdu.service or 0))
            self._handle_cov(note)
        else:
            # We are a client only - reject everything else politely.
            self.send_apdu(src, X.apdu_reject(apdu.invoke_id or 0, 9))

    def _handle_cov(self, note: X.COVNotification):
        sub = self.subscriptions.get(note.process_id)
        if sub is None or sub.object_id != note.object_id:
            self.on_log("debug", f"COV notification for unknown subscription {note.process_id}")
            return
        for pv in note.values:
            if pv.prop == C.PROP_PRESENT_VALUE:
                sub.record(pv.value)
            elif pv.prop == C.PROP_STATUS_FLAGS:
                sub.status_flags = pv.value
        sub.state = "active"
        self.on_subscription(sub)

    # ------------------------------------------------------------------ maintenance
    def _maintenance_loop(self):
        while self.running:
            now = time.time()
            try:
                if self.bbmd and now >= self._bbmd_next:
                    self._send_fd_registration()
                due: Dict[int, List[Subscription]] = {}
                for sub in list(self.subscriptions.values()):
                    if sub.mode == "cov" and sub.state not in ("stopped",) \
                            and sub.subscribed_at and now - sub.subscribed_at > sub.lifetime * 0.75:
                        sub.subscribed_at = now  # avoid duplicate renewals
                        self._pool.submit(self._renew, sub)
                    polled = sub.mode == "poll" or self.auto_refresh
                    if polled and now >= sub.next_poll and sub.state != "stopped":
                        interval = self.refresh_interval if self.auto_refresh else sub.poll_interval
                        sub.next_poll = now + max(0.2, interval)
                        due.setdefault(sub.device.instance, []).append(sub)
                for inst, subs in due.items():
                    with self._lock:
                        if inst in self._polling:
                            continue  # previous poll of this device still running
                        self._polling.add(inst)
                    self._pool.submit(self._poll_batch, subs)
            except Exception as e:
                self.on_log("error", f"maintenance: {e!r}")
            time.sleep(0.1)

    def _renew(self, sub: Subscription):
        try:
            self.subscribe_cov(sub.device.address, sub.sub_id, sub.object_id, sub.confirmed,
                               sub.lifetime)
            sub.subscribed_at = time.time()
            self.on_log("debug", f"Renewed COV subscription {sub.sub_id} on {sub.object_id}")
        except Exception as e:
            sub.state = f"renew failed: {e}"
            self.on_subscription(sub)

    def _poll_batch(self, subs: List[Subscription]):
        """Read Present_Value + Status_Flags of many objects of one device in few requests."""
        dev = subs[0].device
        try:
            k = 0
            chunk = 20 if (dev.max_apdu >= 1024 or dev.can_receive_segments) else 4
            while k < len(subs):
                part = subs[k:k + chunk]
                k += len(part)
                if dev.supports_rpm is not False:
                    try:
                        res = self.read_property_multiple(
                            dev.address, [(s.object_id, [(C.PROP_PRESENT_VALUE, None),
                                                         (C.PROP_STATUS_FLAGS, None)]) for s in part])
                        by_oid: Dict[ObjectId, List[X.PropertyResult]] = {o: r for o, r in res}
                        for s in part:
                            for pr in by_oid.get(s.object_id, []):
                                if pr.error is None and pr.prop == C.PROP_PRESENT_VALUE:
                                    s.record(pr.value)
                                elif pr.error is None and pr.prop == C.PROP_STATUS_FLAGS:
                                    s.status_flags = pr.value
                            self._poll_ok(s)
                        continue
                    except BACnetReject:
                        dev.supports_rpm = False
                    except BACnetAbort as e:
                        if e.reason in (1, 4, 11) and chunk > 1:
                            chunk = max(1, chunk // 2)
                            k -= len(part)
                            continue
                    except BACnetException as e:
                        for s in part:
                            s.state = f"poll error: {e}"
                            self.on_subscription(s)
                        continue
                for s in part:
                    self._poll(s)
        finally:
            with self._lock:
                self._polling.discard(dev.instance)

    def _poll_ok(self, sub: Subscription):
        if sub.mode == "poll":
            sub.state = "polling"
        elif not sub.state.startswith("active"):
            sub.state = "active"
        self.on_subscription(sub)

    def _poll(self, sub: Subscription):
        try:
            res = self.read_property_multiple(
                sub.device.address,
                [(sub.object_id, [(C.PROP_PRESENT_VALUE, None), (C.PROP_STATUS_FLAGS, None)])]) \
                if sub.device.supports_rpm is not False else None
            if res:
                for pr in res[0][1]:
                    if pr.error is None and pr.prop == C.PROP_PRESENT_VALUE:
                        sub.record(pr.value)
                    elif pr.error is None and pr.prop == C.PROP_STATUS_FLAGS:
                        sub.status_flags = pr.value
            else:
                sub.record(self.read_property(sub.device.address, sub.object_id,
                                              C.PROP_PRESENT_VALUE))
            self._poll_ok(sub)
            return
        except Exception as e:
            sub.state = f"poll error: {e}"
        self.on_subscription(sub)

    # ------------------------------------------------------------------ services
    def who_is(self, low: Optional[int] = None, high: Optional[int] = None,
               target: Optional[Tuple[str, int]] = None, global_broadcast: bool = True):
        apdu = X.apdu_who_is(low, high)
        if target and not _is_broadcast(target[0]):
            npdu = X.encode_npdu(False, 0xFFFF if global_broadcast else None, b"")
            self._sendto(X.encode_bvlc(C.BVLC_ORIGINAL_UNICAST, npdu + apdu), *target)
        else:
            self.broadcast_apdu(apdu, global_broadcast, target)
        rng = f" {low}-{high}" if low is not None else ""
        self.on_log("info", f"Who-Is{rng} sent to {target[0] + ':' + str(target[1]) if target else self.broadcast_ip}")

    def who_has(self, name: Optional[str] = None, oid: Optional[ObjectId] = None):
        self.broadcast_apdu(X.apdu_who_has(name, oid))
        self.on_log("info", f"Who-Has {oid or name!r} sent")

    def time_sync(self, address: Optional[Address] = None, utc: bool = False):
        apdu = X.apdu_time_sync(utc)
        if address is None:
            self.broadcast_apdu(apdu)
        else:
            self.send_apdu(address, apdu)
        self.on_log("info", f"{'UTC-' if utc else ''}TimeSynchronization sent to "
                            f"{address or 'broadcast'}")

    def read_property(self, address: Address, oid: ObjectId, prop: int,
                      index: Optional[int] = None, timeout: Optional[float] = None) -> Any:
        ack = self.request(address, C.SERVICE_READ_PROPERTY,
                           X.body_read_property(oid, prop, index), timeout=timeout)
        return X.parse_read_property_ack(ack.data)[3]

    def read_property_multiple(self, address: Address,
                               requests: Sequence[Tuple[ObjectId, Sequence[Tuple[int, Optional[int]]]]],
                               timeout: Optional[float] = None
                               ) -> List[Tuple[ObjectId, List[X.PropertyResult]]]:
        ack = self.request(address, C.SERVICE_READ_PROPERTY_MULTIPLE,
                           X.body_read_property_multiple(requests), timeout=timeout)
        return X.parse_rpm_ack(ack.data)

    def write_property(self, address: Address, oid: ObjectId, prop: int, value: Any,
                       priority: Optional[int] = None, index: Optional[int] = None):
        self.request(address, C.SERVICE_WRITE_PROPERTY,
                     X.body_write_property(oid, prop, value, priority, index))
        self.on_log("info", f"WriteProperty {oid} {C.property_name(prop)} = "
                            f"{X.format_value(value, oid.type, prop)}"
                            f"{f' @ priority {priority}' if priority else ''} OK")

    def subscribe_cov(self, address: Address, process_id: int, oid: ObjectId,
                      confirmed: bool = False, lifetime: int = 300):
        self.request(address, C.SERVICE_SUBSCRIBE_COV,
                     X.body_subscribe_cov(process_id, oid, confirmed, lifetime))

    def cancel_cov(self, address: Address, process_id: int, oid: ObjectId,
                   timeout: Optional[float] = None):
        self.request(address, C.SERVICE_SUBSCRIBE_COV,
                     X.body_subscribe_cov(process_id, oid, None, None), timeout=timeout, retries=0)

    def reinitialize_device(self, address: Address, state: int, password: str = ""):
        self.request(address, C.SERVICE_REINITIALIZE_DEVICE,
                     X.body_reinitialize(state, password or None))

    def device_communication_control(self, address: Address, enable: int,
                                     duration: int = 0, password: str = ""):
        self.request(address, C.SERVICE_DEVICE_COMMUNICATION_CONTROL,
                     X.body_dcc(enable, duration or None, password or None))

    # ------------------------------------------------------------------ high-level
    def add_device_manual(self, ip: str, port: int = C.BACNET_PORT, net: Optional[int] = None,
                          mac: bytes = b"") -> DeviceInfo:
        """Find the device instance at an address without needing a broadcast I-Am."""
        addr = Address(ip, port, net, mac)
        # Wildcard device instance 4194303 is answered by any device (Clause 15.5)
        val = self.read_property(addr, ObjectId(C.OBJ_DEVICE, 4194303), C.PROP_OBJECT_IDENTIFIER)
        if not isinstance(val, ObjectId):
            raise BACnetException("Unexpected Object_Identifier reply")
        dev = self.devices.get(val.instance)
        new = dev is None
        if dev is None:
            dev = DeviceInfo(val.instance, addr)
            self.devices[val.instance] = dev
        dev.address = addr
        for prop, attr in ((C.PROP_MAX_APDU, "max_apdu"),
                           (C.PROP_SEGMENTATION_SUPPORTED, "segmentation"),
                           (C.PROP_VENDOR_ID, "vendor_id")):
            try:
                setattr(dev, attr, int(self.read_property(addr, dev.oid, prop)))
            except Exception:
                pass
        self.on_device(dev, new)
        return dev

    def read_device_info(self, dev: DeviceInfo):
        props = [(C.PROP_OBJECT_NAME, None), (C.PROP_VENDOR_NAME, None),
                 (C.PROP_MODEL_NAME, None), (C.PROP_PROTOCOL_SERVICES_SUPPORTED, None)]
        values: Dict[int, Any] = {}
        try:
            res = self.read_property_multiple(dev.address, [(dev.oid, props)])
            dev.supports_rpm = True
            for pr in res[0][1]:
                if pr.error is None:
                    values[pr.prop] = pr.value
        except (BACnetReject, BACnetError, BACnetAbort):
            dev.supports_rpm = False
            for prop, _ in props:
                try:
                    values[prop] = self.read_property(dev.address, dev.oid, prop)
                except BACnetException:
                    pass
        dev.name = str(values.get(C.PROP_OBJECT_NAME, dev.name))
        dev.vendor_name = str(values.get(C.PROP_VENDOR_NAME, ""))
        dev.model_name = str(values.get(C.PROP_MODEL_NAME, ""))
        svc = values.get(C.PROP_PROTOCOL_SERVICES_SUPPORTED)
        if isinstance(svc, X.BitString) and len(svc.bits) > 14:
            dev.supports_rpm = svc.bits[14]

    def read_object_list(self, dev: DeviceInfo,
                         progress: Optional[Callable[[int, int], None]] = None) -> List[ObjectId]:
        objs: List[ObjectId] = []
        try:
            val = self.read_property(dev.address, dev.oid, C.PROP_OBJECT_LIST, timeout=self.timeout * 2)
            objs = [v for v in (val if isinstance(val, list) else [val]) if isinstance(v, ObjectId)]
        except (BACnetAbort, BACnetError, BACnetReject, BACnetTimeout) as e:
            self.on_log("info", f"Object_List of device {dev.instance} not readable at once "
                                f"({e}); reading element by element")
            count = int(self.read_property(dev.address, dev.oid, C.PROP_OBJECT_LIST, 0))
            batch = 20 if dev.max_apdu >= 480 else 5
            i = 1
            while i <= count:
                idxs = list(range(i, min(count, i + batch - 1) + 1))
                got = False
                if dev.supports_rpm is not False:
                    try:
                        res = self.read_property_multiple(
                            dev.address, [(dev.oid, [(C.PROP_OBJECT_LIST, k) for k in idxs])])
                        for pr in res[0][1]:
                            if pr.error is None and isinstance(pr.value, ObjectId):
                                objs.append(pr.value)
                        got = True
                    except (BACnetReject, BACnetError, BACnetAbort):
                        dev.supports_rpm = False
                if not got:
                    for k in idxs:
                        v = self.read_property(dev.address, dev.oid, C.PROP_OBJECT_LIST, k)
                        if isinstance(v, ObjectId):
                            objs.append(v)
                i += len(idxs)
                if progress:
                    progress(min(i - 1, count), count)
        dev.objects = objs
        return objs

    def read_object_names(self, dev: DeviceInfo, objects: List[ObjectId],
                          progress: Optional[Callable[[int, int], None]] = None
                          ) -> Dict[ObjectId, str]:
        names: Dict[ObjectId, str] = {}
        batch = 25 if (dev.max_apdu >= 1024 or dev.can_receive_segments) else \
            (8 if dev.max_apdu >= 480 else 2)
        i = 0
        while i < len(objects):
            chunk = objects[i:i + batch]
            done = False
            if dev.supports_rpm is not False:
                try:
                    res = self.read_property_multiple(
                        dev.address, [(o, [(C.PROP_OBJECT_NAME, None)]) for o in chunk])
                    for oid, results in res:
                        for pr in results:
                            if pr.error is None:
                                names[oid] = str(pr.value)
                    done = True
                except BACnetAbort as e:
                    if batch > 1 and e.reason in (4, 11, 1):  # too big - shrink
                        batch = max(1, batch // 2)
                        continue
                    dev.supports_rpm = False
                except (BACnetReject, BACnetError):
                    dev.supports_rpm = False
            if not done:
                for o in chunk:
                    try:
                        names[o] = str(self.read_property(dev.address, o, C.PROP_OBJECT_NAME))
                    except BACnetException:
                        names[o] = ""
            i += len(chunk)
            if progress:
                progress(i, len(objects))
        dev.object_names.update(names)
        return names

    def read_all_properties(self, dev: DeviceInfo, oid: ObjectId) -> List[X.PropertyResult]:
        """Read every property of an object: RPM(ALL) -> Property_List -> default set."""
        if dev.supports_rpm is not False:
            try:
                res = self.read_property_multiple(dev.address, [(oid, [(C.PROP_ALL, None)])],
                                                  timeout=self.timeout * 2)
                if res and res[0][1]:
                    return res[0][1]
            except BACnetReject:
                dev.supports_rpm = False
            except (BACnetError, BACnetAbort) as e:
                self.on_log("debug", f"RPM(ALL) on {oid} failed: {e}")

        props: List[int] = []
        try:
            pl = self.read_property(dev.address, oid, C.PROP_PROPERTY_LIST)
            props = [int(p) for p in (pl if isinstance(pl, list) else [pl])]
            props = [75, 77, 79] + [p for p in props if p not in (75, 77, 79)]
        except BACnetException:
            props = list(C.DEFAULT_PROPS[C.object_family(oid.type)])

        results: List[X.PropertyResult] = []
        if dev.supports_rpm is not False:
            try:
                for k in range(0, len(props), 16):
                    res = self.read_property_multiple(
                        dev.address, [(oid, [(p, None) for p in props[k:k + 16]])])
                    results.extend(res[0][1])
                return results
            except BACnetException:
                results = []
        for p in props:
            try:
                results.append(X.PropertyResult(p, None, self.read_property(dev.address, oid, p)))
            except BACnetError as e:
                if e.err_code != 32:  # hide unknown-property in fallback mode
                    results.append(X.PropertyResult(p, None, error=(e.err_class, e.err_code)))
            except BACnetException as e:
                results.append(X.PropertyResult(p, None, error=(-1, -1)))
                self.on_log("debug", f"Read {oid} {C.property_name(p)}: {e}")
        return results

    # ------------------------------------------------------------------ subscriptions
    def add_subscription(self, dev: DeviceInfo, oid: ObjectId, confirmed: bool = False,
                         lifetime: int = 300, allow_poll_fallback: bool = True,
                         poll_interval: float = 5.0, force_poll: bool = False,
                         name: str = "") -> Subscription:
        with self._lock:
            sid = self._next_sub_id
            self._next_sub_id += 1
        sub = Subscription(sid, dev, oid, confirmed=confirmed, lifetime=lifetime,
                           poll_interval=poll_interval, name=name)
        self.subscriptions[sid] = sub
        if not force_poll:
            try:
                self.subscribe_cov(dev.address, sid, oid, confirmed, lifetime)
                sub.subscribed_at = time.time()
                sub.state = "active"
                self.on_log("info", f"SubscribeCOV {oid} on device {dev.instance} OK "
                                    f"({'confirmed' if confirmed else 'unconfirmed'}, {lifetime}s)")
                return sub
            except BACnetException as e:
                if not allow_poll_fallback:
                    del self.subscriptions[sid]
                    raise
                self.on_log("warning", f"SubscribeCOV {oid} failed ({e}); falling back to "
                                       f"polling every {poll_interval:g}s")
        sub.mode = "poll"
        sub.state = "polling"
        sub.next_poll = 0
        return sub

    def remove_subscription(self, sub_id: int):
        sub = self.subscriptions.pop(sub_id, None)
        if sub is None:
            return
        sub.state = "stopped"
        if sub.mode == "cov":
            try:
                self.cancel_cov(sub.device.address, sub.sub_id, sub.object_id, timeout=1.5)
            except BACnetException as e:
                self.on_log("debug", f"Cancel COV {sub.sub_id}: {e}")


def _is_broadcast(ip: str) -> bool:
    return ip == "255.255.255.255" or ip.endswith(".255")
