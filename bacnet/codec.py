"""
BACnet/IP encoding and decoding: BVLC, NPDU, APDU, tags and application data types.

Pure Python, no third-party dependencies.
"""
from __future__ import annotations

import datetime as _dt
import struct
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

from . import constants as C


class BACnetDecodeError(Exception):
    pass


# ==========================================================================
# Application data types
# ==========================================================================
class Null:
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "NULL"

    __str__ = __repr__


NULL = Null()


class Unsigned(int):
    """Application tag 2."""


class Signed(int):
    """Application tag 3."""


class Enumerated(int):
    """Application tag 9."""


class Real(float):
    """Application tag 4 (IEEE-754 single)."""


class Double(float):
    """Application tag 5 (IEEE-754 double)."""


class CharacterString(str):
    """Application tag 7."""


class OctetString(bytes):
    """Application tag 6."""


@dataclass(frozen=True, order=True)
class ObjectId:
    type: int
    instance: int

    def __str__(self):
        return f"{C.object_type_name(self.type)}:{self.instance}"

    @property
    def short(self) -> str:
        return f"{C.OBJECT_TYPE_SHORT.get(self.type, C.object_type_name(self.type))}{self.instance}"

    @staticmethod
    def parse(text: str) -> "ObjectId":
        if ":" in text:
            t, i = text.rsplit(":", 1)
        elif "," in text:
            t, i = text.rsplit(",", 1)
        else:
            raise ValueError("Object id must be 'type:instance', e.g. analog-value:1")
        return ObjectId(C.lookup_object_type(t), int(i))


@dataclass
class BitString:
    bits: List[bool] = field(default_factory=list)

    def __str__(self):
        return "{" + ",".join("T" if b else "F" for b in self.bits) + "}"


@dataclass
class Date:
    year: int  # full year, 255 = any
    month: int
    day: int
    dow: int

    def __str__(self):
        y = "*" if self.year == 255 else str(self.year)
        m = {13: "odd", 14: "even", 255: "*"}.get(self.month, f"{self.month:02d}")
        d = {32: "last", 33: "odd", 34: "even", 255: "*"}.get(self.day, f"{self.day:02d}")
        w = C.DAYS_OF_WEEK.get(self.dow, "*")
        return f"{y}-{m}-{d} ({w})"

    @staticmethod
    def today() -> "Date":
        t = _dt.date.today()
        return Date(t.year, t.month, t.day, t.isoweekday())


@dataclass
class Time:
    hour: int
    minute: int
    second: int
    hundredths: int

    def __str__(self):
        def f(v):
            return "*" if v == 255 else f"{v:02d}"
        return f"{f(self.hour)}:{f(self.minute)}:{f(self.second)}.{f(self.hundredths)}"

    @staticmethod
    def now() -> "Time":
        t = _dt.datetime.now()
        return Time(t.hour, t.minute, t.second, t.microsecond // 10000)


@dataclass
class ContextValue:
    """A context-tagged primitive whose meaning depends on the enclosing structure."""
    tag: int
    data: bytes

    def as_unsigned(self) -> int:
        return int.from_bytes(self.data, "big") if self.data else 0

    def __str__(self):
        if len(self.data) <= 4:
            return f"[{self.tag}]{self.as_unsigned()}"
        return f"[{self.tag}]0x{self.data.hex()}"


@dataclass
class Constructed:
    """An opening/closing tag pair containing nested values."""
    tag: int
    items: List[Any]

    def __str__(self):
        return f"[{self.tag}]{{" + ", ".join(format_plain(i) for i in self.items) + "}"


# ==========================================================================
# Tag encoding
# ==========================================================================
def _enc_tag(tag: int, context: bool, length: int) -> bytes:
    b0 = 0x08 if context else 0x00
    ext = b""
    if tag <= 14:
        b0 |= tag << 4
    else:
        b0 |= 0xF0
        ext += bytes([tag])
    if length <= 4:
        b0 |= length
    else:
        b0 |= 5
        if length <= 253:
            ext += bytes([length])
        elif length <= 65535:
            ext += bytes([254]) + struct.pack(">H", length)
        else:
            ext += bytes([255]) + struct.pack(">I", length)
    return bytes([b0]) + ext


def opening_tag(tag: int) -> bytes:
    return bytes([(tag << 4) | 0x0E]) if tag <= 14 else bytes([0xFE, tag])


def closing_tag(tag: int) -> bytes:
    return bytes([(tag << 4) | 0x0F]) if tag <= 14 else bytes([0xFF, tag])


def _unsigned_bytes(n: int) -> bytes:
    if n < 0:
        raise ValueError("unsigned value cannot be negative")
    if n == 0:
        return b"\x00"
    return n.to_bytes((n.bit_length() + 7) // 8, "big")


def _signed_bytes(n: int) -> bytes:
    for size in (1, 2, 3, 4, 8):
        lo, hi = -(1 << (8 * size - 1)), (1 << (8 * size - 1)) - 1
        if lo <= n <= hi:
            return n.to_bytes(size, "big", signed=True)
    raise ValueError("signed value out of range")


def _objid_bytes(oid: ObjectId) -> bytes:
    return struct.pack(">I", ((oid.type & 0x3FF) << 22) | (oid.instance & 0x3FFFFF))


def _date_bytes(d: Date) -> bytes:
    y = 255 if d.year == 255 else d.year - 1900
    return bytes([y, d.month, d.day, d.dow])


def _time_bytes(t: Time) -> bytes:
    return bytes([t.hour, t.minute, t.second, t.hundredths])


def _bitstring_bytes(bs: BitString) -> bytes:
    nbytes = (len(bs.bits) + 7) // 8
    unused = nbytes * 8 - len(bs.bits)
    out = bytearray(nbytes)
    for i, b in enumerate(bs.bits):
        if b:
            out[i // 8] |= 0x80 >> (i % 8)
    return bytes([unused]) + bytes(out)


def _charstring_bytes(s: str) -> bytes:
    return b"\x00" + s.encode("utf-8")


def encode_application(value: Any) -> bytes:
    """Encode a Python/BACnet value with its application tag."""
    if value is None or isinstance(value, Null):
        return b"\x00"
    if isinstance(value, bool):
        return bytes([0x10 | (1 if value else 0)])
    if isinstance(value, Enumerated):
        d = _unsigned_bytes(int(value)); return _enc_tag(9, False, len(d)) + d
    if isinstance(value, Signed):
        d = _signed_bytes(int(value)); return _enc_tag(3, False, len(d)) + d
    if isinstance(value, int):  # Unsigned or plain int
        if value < 0:
            d = _signed_bytes(value); return _enc_tag(3, False, len(d)) + d
        d = _unsigned_bytes(value); return _enc_tag(2, False, len(d)) + d
    if isinstance(value, Double):
        return _enc_tag(5, False, 8) + struct.pack(">d", value)
    if isinstance(value, float):
        return _enc_tag(4, False, 4) + struct.pack(">f", value)
    if isinstance(value, (bytes, bytearray)):
        return _enc_tag(6, False, len(value)) + bytes(value)
    if isinstance(value, str):
        d = _charstring_bytes(value); return _enc_tag(7, False, len(d)) + d
    if isinstance(value, BitString):
        d = _bitstring_bytes(value); return _enc_tag(8, False, len(d)) + d
    if isinstance(value, Date):
        return _enc_tag(10, False, 4) + _date_bytes(value)
    if isinstance(value, Time):
        return _enc_tag(11, False, 4) + _time_bytes(value)
    if isinstance(value, ObjectId):
        return _enc_tag(12, False, 4) + _objid_bytes(value)
    if isinstance(value, Constructed):
        return opening_tag(value.tag) + b"".join(encode_application(v) for v in value.items) \
            + closing_tag(value.tag)
    if isinstance(value, ContextValue):
        return _enc_tag(value.tag, True, len(value.data)) + value.data
    if isinstance(value, (list, tuple)):
        return b"".join(encode_application(v) for v in value)
    raise TypeError(f"Cannot encode {type(value).__name__}")


def ctx_unsigned(tag: int, n: int) -> bytes:
    d = _unsigned_bytes(n); return _enc_tag(tag, True, len(d)) + d


def ctx_enumerated(tag: int, n: int) -> bytes:
    return ctx_unsigned(tag, n)


def ctx_boolean(tag: int, b: bool) -> bytes:
    return _enc_tag(tag, True, 1) + (b"\x01" if b else b"\x00")


def ctx_objid(tag: int, oid: ObjectId) -> bytes:
    return _enc_tag(tag, True, 4) + _objid_bytes(oid)


def ctx_charstring(tag: int, s: str) -> bytes:
    d = _charstring_bytes(s); return _enc_tag(tag, True, len(d)) + d


# ==========================================================================
# Tag decoding
# ==========================================================================
@dataclass
class Tag:
    number: int
    context: bool
    kind: str        # 'prim', 'open', 'close'
    lvt: int         # length (or boolean value for application boolean)
    data_offset: int

    @property
    def end(self) -> int:
        if self.kind != "prim" or (not self.context and self.number == 1):
            return self.data_offset
        return self.data_offset + self.lvt


def decode_tag(buf: bytes, off: int) -> Tag:
    if off >= len(buf):
        raise BACnetDecodeError("unexpected end of data")
    b0 = buf[off]; off += 1
    number = b0 >> 4
    context = bool(b0 & 0x08)
    lvt = b0 & 0x07
    if number == 15:
        number = buf[off]; off += 1
    if context and lvt == 6:
        return Tag(number, True, "open", 0, off)
    if context and lvt == 7:
        return Tag(number, True, "close", 0, off)
    if lvt == 5:
        n = buf[off]; off += 1
        if n == 254:
            lvt = struct.unpack_from(">H", buf, off)[0]; off += 2
        elif n == 255:
            lvt = struct.unpack_from(">I", buf, off)[0]; off += 4
        else:
            lvt = n
    t = Tag(number, context, "prim", lvt, off)
    if t.end > len(buf):
        raise BACnetDecodeError("tag length exceeds buffer")
    return t


def _decode_app_primitive(tagno: int, lvt: int, data: bytes) -> Any:
    if tagno == 0:
        return NULL
    if tagno == 1:
        return bool(lvt)
    if tagno == 2:
        return Unsigned(int.from_bytes(data, "big"))
    if tagno == 3:
        return Signed(int.from_bytes(data, "big", signed=True))
    if tagno == 4:
        return Real(struct.unpack(">f", data)[0])
    if tagno == 5:
        return Double(struct.unpack(">d", data)[0])
    if tagno == 6:
        return OctetString(data)
    if tagno == 7:
        return CharacterString(decode_charstring(data))
    if tagno == 8:
        if not data:
            return BitString([])
        unused = data[0]
        bits = []
        for i in range((len(data) - 1) * 8 - unused):
            bits.append(bool(data[1 + i // 8] & (0x80 >> (i % 8))))
        return BitString(bits)
    if tagno == 9:
        return Enumerated(int.from_bytes(data, "big"))
    if tagno == 10:
        return Date(255 if data[0] == 255 else data[0] + 1900, data[1], data[2], data[3])
    if tagno == 11:
        return Time(data[0], data[1], data[2], data[3])
    if tagno == 12:
        v = struct.unpack(">I", data)[0]
        return ObjectId(v >> 22, v & 0x3FFFFF)
    return OctetString(data)  # reserved tags


def decode_charstring(data: bytes) -> str:
    if not data:
        return ""
    cs, raw = data[0], data[1:]
    try:
        if cs == 0:
            return raw.decode("utf-8", errors="replace")
        if cs == 4:
            return raw.decode("utf-16-be", errors="replace")
        if cs == 3:
            return raw.decode("utf-32-be", errors="replace")
        return raw.decode("latin-1", errors="replace")
    except Exception:
        return raw.hex()


def decode_values(buf: bytes, off: int = 0, end: Optional[int] = None,
                  close_tag: Optional[int] = None) -> Tuple[List[Any], int]:
    """Decode a sequence of tagged values.

    Stops at `end`, or right after the closing tag `close_tag` (the returned offset points past
    the closing tag).
    """
    end = len(buf) if end is None else end
    out: List[Any] = []
    while off < end:
        t = decode_tag(buf, off)
        if t.kind == "close":
            if close_tag is None or t.number != close_tag:
                raise BACnetDecodeError(f"unexpected closing tag {t.number}")
            return out, t.data_offset
        if t.kind == "open":
            inner, off = decode_values(buf, t.data_offset, end, t.number)
            out.append(Constructed(t.number, inner))
            continue
        data = buf[t.data_offset:t.end]
        if t.context:
            out.append(ContextValue(t.number, data))
        else:
            out.append(_decode_app_primitive(t.number, t.lvt, data))
        off = t.end
    if close_tag is not None:
        raise BACnetDecodeError(f"missing closing tag {close_tag}")
    return out, off


def _expect_ctx(buf: bytes, off: int, tagno: int) -> Tuple[bytes, int]:
    t = decode_tag(buf, off)
    if not (t.context and t.kind == "prim" and t.number == tagno):
        raise BACnetDecodeError(f"expected context tag {tagno}")
    return buf[t.data_offset:t.end], t.end


def _peek(buf: bytes, off: int) -> Optional[Tag]:
    if off >= len(buf):
        return None
    return decode_tag(buf, off)


def _ctx_objid(data: bytes) -> ObjectId:
    v = struct.unpack(">I", data)[0]
    return ObjectId(v >> 22, v & 0x3FFFFF)


def _uint(data: bytes) -> int:
    return int.from_bytes(data, "big")


# ==========================================================================
# Addresses, BVLC and NPDU
# ==========================================================================
@dataclass(frozen=True)
class Address:
    """A BACnet address: IP/port of the next hop plus optional remote network/MAC."""
    ip: str
    port: int = C.BACNET_PORT
    net: Optional[int] = None
    mac: bytes = b""

    def __str__(self):
        s = f"{self.ip}:{self.port}"
        if self.net is not None:
            s += f" (net {self.net}, mac {self.mac.hex() if len(self.mac) != 1 else self.mac[0]})"
        return s

    @property
    def is_routed(self) -> bool:
        return self.net is not None and self.net != 0xFFFF


def encode_bvlc(function: int, payload: bytes) -> bytes:
    return struct.pack(">BBH", C.BVLC_TYPE, function, len(payload) + 4) + payload


def encode_npdu(expecting_reply: bool = False, dnet: Optional[int] = None, dadr: bytes = b"",
                hop_count: int = 255, priority: int = 0) -> bytes:
    control = priority & 0x03
    if expecting_reply:
        control |= 0x04
    out = bytearray([0x01, control])
    if dnet is not None:
        out[1] |= 0x20
        out += struct.pack(">HB", dnet, len(dadr)) + dadr
        out.append(hop_count)
    return bytes(out)


@dataclass
class Packet:
    bvlc_function: int
    src_ip: str
    src_port: int
    snet: Optional[int] = None
    sadr: bytes = b""
    dnet: Optional[int] = None
    network_message: Optional[int] = None
    expecting_reply: bool = False
    apdu: bytes = b""
    bvlc_payload: bytes = b""

    @property
    def source(self) -> Address:
        return Address(self.src_ip, self.src_port, self.snet, self.sadr)


def decode_packet(data: bytes, ip: str, port: int) -> Packet:
    if len(data) < 4 or data[0] != C.BVLC_TYPE:
        raise BACnetDecodeError("not a BACnet/IP packet")
    func = data[1]
    length = struct.unpack_from(">H", data, 2)[0]
    payload = data[4:length]
    pkt = Packet(func, ip, port, bvlc_payload=payload)
    if func == C.BVLC_FORWARDED_NPDU:
        if len(payload) < 6:
            raise BACnetDecodeError("short forwarded NPDU")
        pkt.src_ip = ".".join(str(b) for b in payload[0:4])
        pkt.src_port = struct.unpack_from(">H", payload, 4)[0]
        payload = payload[6:]
    elif func not in (C.BVLC_ORIGINAL_UNICAST, C.BVLC_ORIGINAL_BROADCAST,
                      C.BVLC_DISTRIBUTE_BROADCAST):
        return pkt  # BVLC control message (Result, BDT, FDT...)

    if len(payload) < 2 or payload[0] != 0x01:
        raise BACnetDecodeError("bad NPDU version")
    control = payload[1]
    off = 2
    if control & 0x20:
        pkt.dnet = struct.unpack_from(">H", payload, off)[0]
        dlen = payload[off + 2]
        off += 3 + dlen
    if control & 0x08:
        pkt.snet = struct.unpack_from(">H", payload, off)[0]
        slen = payload[off + 2]
        pkt.sadr = bytes(payload[off + 3:off + 3 + slen])
        off += 3 + slen
    if control & 0x20:
        off += 1  # hop count
    pkt.expecting_reply = bool(control & 0x04)
    if control & 0x80:
        pkt.network_message = payload[off]
        return pkt
    pkt.apdu = bytes(payload[off:])
    return pkt


# ==========================================================================
# APDU builders (client side)
# ==========================================================================
MAX_APDU_1476 = 5
MAX_SEGS_UNLIMITED = 7


def confirmed_header(invoke_id: int, service: int, segmented_accepted: bool = True) -> bytes:
    b0 = (C.PDU_CONFIRMED_REQUEST << 4) | (0x02 if segmented_accepted else 0)
    b1 = ((MAX_SEGS_UNLIMITED if segmented_accepted else 0) << 4) | MAX_APDU_1476
    return bytes([b0, b1, invoke_id & 0xFF, service])


def apdu_who_is(low: Optional[int] = None, high: Optional[int] = None) -> bytes:
    out = bytes([C.PDU_UNCONFIRMED_REQUEST << 4, C.SERVICE_WHO_IS])
    if low is not None and high is not None:
        out += ctx_unsigned(0, low) + ctx_unsigned(1, high)
    return out


def apdu_i_am(device: int, max_apdu: int = 1476, segmentation: int = 0,
              vendor: int = 999) -> bytes:
    return bytes([C.PDU_UNCONFIRMED_REQUEST << 4, C.SERVICE_I_AM]) + \
        encode_application(ObjectId(C.OBJ_DEVICE, device)) + \
        encode_application(Unsigned(max_apdu)) + \
        encode_application(Enumerated(segmentation)) + \
        encode_application(Unsigned(vendor))


def apdu_who_has(name: Optional[str] = None, oid: Optional[ObjectId] = None,
                 low: Optional[int] = None, high: Optional[int] = None) -> bytes:
    out = bytes([C.PDU_UNCONFIRMED_REQUEST << 4, C.SERVICE_WHO_HAS])
    if low is not None and high is not None:
        out += ctx_unsigned(0, low) + ctx_unsigned(1, high)
    if oid is not None:
        out += ctx_objid(2, oid)
    else:
        out += ctx_charstring(3, name or "")
    return out


def apdu_time_sync(utc: bool = False) -> bytes:
    if utc:
        now = _dt.datetime.now(_dt.timezone.utc)
        svc = C.SERVICE_UTC_TIME_SYNCHRONIZATION
    else:
        now = _dt.datetime.now()
        svc = C.SERVICE_TIME_SYNCHRONIZATION
    d = Date(now.year, now.month, now.day, now.isoweekday())
    t = Time(now.hour, now.minute, now.second, now.microsecond // 10000)
    return bytes([C.PDU_UNCONFIRMED_REQUEST << 4, svc]) + encode_application(d) + \
        encode_application(t)


def body_read_property(oid: ObjectId, prop: int, index: Optional[int] = None) -> bytes:
    out = ctx_objid(0, oid) + ctx_enumerated(1, prop)
    if index is not None:
        out += ctx_unsigned(2, index)
    return out


def body_read_property_multiple(requests: Sequence[Tuple[ObjectId, Sequence[Tuple[int, Optional[int]]]]]) -> bytes:
    out = bytearray()
    for oid, props in requests:
        out += ctx_objid(0, oid) + opening_tag(1)
        for prop, idx in props:
            out += ctx_enumerated(0, prop)
            if idx is not None:
                out += ctx_unsigned(1, idx)
        out += closing_tag(1)
    return bytes(out)


def body_write_property(oid: ObjectId, prop: int, value: Any, priority: Optional[int] = None,
                        index: Optional[int] = None) -> bytes:
    out = ctx_objid(0, oid) + ctx_enumerated(1, prop)
    if index is not None:
        out += ctx_unsigned(2, index)
    out += opening_tag(3) + encode_application(value) + closing_tag(3)
    if priority is not None:
        out += ctx_unsigned(4, priority)
    return out


def body_subscribe_cov(process_id: int, oid: ObjectId, confirmed: Optional[bool] = None,
                       lifetime: Optional[int] = None) -> bytes:
    """confirmed=None -> cancellation."""
    out = ctx_unsigned(0, process_id) + ctx_objid(1, oid)
    if confirmed is not None:
        out += ctx_boolean(2, confirmed)
        if lifetime is not None:
            out += ctx_unsigned(3, lifetime)
    return out


def body_reinitialize(state: int, password: Optional[str] = None) -> bytes:
    out = ctx_enumerated(0, state)
    if password:
        out += ctx_charstring(1, password)
    return out


def body_dcc(enable: int, duration_min: Optional[int] = None,
             password: Optional[str] = None) -> bytes:
    out = b""
    if duration_min:
        out += ctx_unsigned(0, duration_min)
    out += ctx_enumerated(1, enable)
    if password:
        out += ctx_charstring(2, password)
    return out


def apdu_segment_ack(invoke_id: int, seq: int, window: int, server: bool = False,
                     nak: bool = False) -> bytes:
    b0 = (C.PDU_SEGMENT_ACK << 4) | (0x02 if nak else 0) | (0x01 if server else 0)
    return bytes([b0, invoke_id, seq & 0xFF, window])


def apdu_simple_ack(invoke_id: int, service: int) -> bytes:
    return bytes([C.PDU_SIMPLE_ACK << 4, invoke_id, service])


def apdu_complex_ack(invoke_id: int, service: int, body: bytes) -> bytes:
    return bytes([C.PDU_COMPLEX_ACK << 4, invoke_id, service]) + body


def apdu_error(invoke_id: int, service: int, err_class: int, err_code: int) -> bytes:
    return bytes([C.PDU_ERROR << 4, invoke_id, service]) + \
        encode_application(Enumerated(err_class)) + encode_application(Enumerated(err_code))


def apdu_reject(invoke_id: int, reason: int) -> bytes:
    return bytes([C.PDU_REJECT << 4, invoke_id, reason])


def apdu_abort(invoke_id: int, reason: int, server: bool = True) -> bytes:
    return bytes([(C.PDU_ABORT << 4) | (1 if server else 0), invoke_id, reason])


# ==========================================================================
# APDU parsing
# ==========================================================================
@dataclass
class APDU:
    pdu_type: int
    invoke_id: Optional[int] = None
    service: Optional[int] = None
    data: bytes = b""
    segmented: bool = False
    more_follows: bool = False
    seq: int = 0
    window: int = 0
    segmented_accepted: bool = False
    max_apdu: int = 1476
    reason: Optional[int] = None
    server: bool = False
    nak: bool = False


def parse_apdu(apdu: bytes) -> APDU:
    if not apdu:
        raise BACnetDecodeError("empty APDU")
    t = apdu[0] >> 4
    if t == C.PDU_CONFIRMED_REQUEST:
        seg = bool(apdu[0] & 0x08)
        more = bool(apdu[0] & 0x04)
        sa = bool(apdu[0] & 0x02)
        max_apdu = C.MAX_APDU_CODES.get(apdu[1] & 0x0F, 1476)
        if seg:
            return APDU(t, apdu[2], apdu[5], apdu[6:], True, more, apdu[3], apdu[4], sa,
                        max_apdu)
        return APDU(t, apdu[2], apdu[3], apdu[4:], segmented_accepted=sa, max_apdu=max_apdu)
    if t == C.PDU_UNCONFIRMED_REQUEST:
        return APDU(t, service=apdu[1], data=apdu[2:])
    if t == C.PDU_SIMPLE_ACK:
        return APDU(t, apdu[1], apdu[2])
    if t == C.PDU_COMPLEX_ACK:
        seg = bool(apdu[0] & 0x08)
        more = bool(apdu[0] & 0x04)
        if seg:
            return APDU(t, apdu[1], apdu[4], apdu[5:], True, more, apdu[2], apdu[3])
        return APDU(t, apdu[1], apdu[2], apdu[3:])
    if t == C.PDU_SEGMENT_ACK:
        return APDU(t, apdu[1], data=apdu[2:], seq=apdu[2], window=apdu[3],
                    nak=bool(apdu[0] & 0x02), server=bool(apdu[0] & 0x01))
    if t == C.PDU_ERROR:
        return APDU(t, apdu[1], apdu[2], apdu[3:])
    if t == C.PDU_REJECT:
        return APDU(t, apdu[1], reason=apdu[2])
    if t == C.PDU_ABORT:
        return APDU(t, apdu[1], reason=apdu[2], server=bool(apdu[0] & 0x01))
    raise BACnetDecodeError(f"unknown PDU type {t}")


def parse_error(data: bytes) -> Tuple[int, int]:
    """Return (error_class, error_code). Handles plain and constructed error PDUs."""
    vals, _ = decode_values(data)
    flat: List[int] = []

    def walk(items):
        for v in items:
            if isinstance(v, Constructed):
                walk(v.items)
            elif isinstance(v, Enumerated):
                flat.append(int(v))
    walk(vals)
    if len(flat) >= 2:
        return flat[0], flat[1]
    return 0, 0


@dataclass
class IAm:
    device: int
    max_apdu: int
    segmentation: int
    vendor: int


def parse_i_am(data: bytes) -> IAm:
    vals, _ = decode_values(data)
    if len(vals) < 4 or not isinstance(vals[0], ObjectId):
        raise BACnetDecodeError("malformed I-Am")
    return IAm(vals[0].instance, int(vals[1]), int(vals[2]), int(vals[3]))


@dataclass
class IHave:
    device: int
    object_id: ObjectId
    object_name: str


def parse_i_have(data: bytes) -> IHave:
    vals, _ = decode_values(data)
    return IHave(vals[0].instance, vals[1], str(vals[2]))


@dataclass
class WhoIs:
    low: Optional[int]
    high: Optional[int]


def parse_who_is(data: bytes) -> WhoIs:
    if not data:
        return WhoIs(None, None)
    lo, off = _expect_ctx(data, 0, 0)
    hi, off = _expect_ctx(data, off, 1)
    return WhoIs(_uint(lo), _uint(hi))


def _value_from_list(vals: List[Any]) -> Any:
    return vals[0] if len(vals) == 1 else vals


def parse_read_property_ack(data: bytes) -> Tuple[ObjectId, int, Optional[int], Any]:
    d, off = _expect_ctx(data, 0, 0)
    oid = _ctx_objid(d)
    d, off = _expect_ctx(data, off, 1)
    prop = _uint(d)
    index = None
    t = _peek(data, off)
    if t and t.kind == "prim" and t.context and t.number == 2:
        d, off = _expect_ctx(data, off, 2)
        index = _uint(d)
    t = decode_tag(data, off)
    if t.kind != "open" or t.number != 3:
        raise BACnetDecodeError("expected opening tag 3")
    vals, off = decode_values(data, t.data_offset, close_tag=3)
    return oid, prop, index, _value_from_list(vals) if vals else []


@dataclass
class PropertyResult:
    prop: int
    index: Optional[int]
    value: Any = None
    error: Optional[Tuple[int, int]] = None


def parse_rpm_ack(data: bytes) -> List[Tuple[ObjectId, List[PropertyResult]]]:
    out = []
    off = 0
    while off < len(data):
        d, off = _expect_ctx(data, off, 0)
        oid = _ctx_objid(d)
        t = decode_tag(data, off)
        if t.kind != "open" or t.number != 1:
            raise BACnetDecodeError("expected opening tag 1")
        off = t.data_offset
        results: List[PropertyResult] = []
        while True:
            t = decode_tag(data, off)
            if t.kind == "close" and t.number == 1:
                off = t.data_offset
                break
            d, off = _expect_ctx(data, off, 2)
            prop = _uint(d)
            idx = None
            t = decode_tag(data, off)
            if t.kind == "prim" and t.context and t.number == 3:
                idx = _uint(data[t.data_offset:t.end])
                off = t.end
                t = decode_tag(data, off)
            if t.kind == "open" and t.number == 4:
                vals, off = decode_values(data, t.data_offset, close_tag=4)
                results.append(PropertyResult(prop, idx, _value_from_list(vals) if vals else []))
            elif t.kind == "open" and t.number == 5:
                vals, off = decode_values(data, t.data_offset, close_tag=5)
                ec = int(vals[0]) if len(vals) > 0 else 0
                cd = int(vals[1]) if len(vals) > 1 else 0
                results.append(PropertyResult(prop, idx, error=(ec, cd)))
            else:
                raise BACnetDecodeError("expected property value or error")
        out.append((oid, results))
    return out


@dataclass
class COVNotification:
    process_id: int
    device: ObjectId
    object_id: ObjectId
    time_remaining: int
    values: List[PropertyResult]


def parse_cov_notification(data: bytes) -> COVNotification:
    d, off = _expect_ctx(data, 0, 0); pid = _uint(d)
    d, off = _expect_ctx(data, off, 1); dev = _ctx_objid(d)
    d, off = _expect_ctx(data, off, 2); oid = _ctx_objid(d)
    d, off = _expect_ctx(data, off, 3); remaining = _uint(d)
    t = decode_tag(data, off)
    if t.kind != "open" or t.number != 4:
        raise BACnetDecodeError("expected list of values")
    off = t.data_offset
    values: List[PropertyResult] = []
    while True:
        t = decode_tag(data, off)
        if t.kind == "close" and t.number == 4:
            break
        d, off = _expect_ctx(data, off, 0); prop = _uint(d)
        idx = None
        t = decode_tag(data, off)
        if t.kind == "prim" and t.context and t.number == 1:
            idx = _uint(data[t.data_offset:t.end]); off = t.end
            t = decode_tag(data, off)
        if t.kind != "open" or t.number != 2:
            raise BACnetDecodeError("expected value")
        vals, off = decode_values(data, t.data_offset, close_tag=2)
        t = _peek(data, off)
        if t and t.kind == "prim" and t.context and t.number == 3:
            off = t.end  # priority
        values.append(PropertyResult(prop, idx, _value_from_list(vals) if vals else []))
    return COVNotification(pid, dev, oid, remaining, values)


# ---- server-side request parsing (used by the simulator) ----
def parse_read_property_request(data: bytes) -> Tuple[ObjectId, int, Optional[int]]:
    d, off = _expect_ctx(data, 0, 0); oid = _ctx_objid(d)
    d, off = _expect_ctx(data, off, 1); prop = _uint(d)
    idx = None
    if off < len(data):
        d, off = _expect_ctx(data, off, 2); idx = _uint(d)
    return oid, prop, idx


def parse_rpm_request(data: bytes) -> List[Tuple[ObjectId, List[Tuple[int, Optional[int]]]]]:
    out = []
    off = 0
    while off < len(data):
        d, off = _expect_ctx(data, off, 0); oid = _ctx_objid(d)
        t = decode_tag(data, off)
        if t.kind != "open" or t.number != 1:
            raise BACnetDecodeError("expected opening tag 1")
        off = t.data_offset
        props = []
        while True:
            t = decode_tag(data, off)
            if t.kind == "close":
                off = t.data_offset
                break
            d, off = _expect_ctx(data, off, 0); prop = _uint(d)
            idx = None
            t = _peek(data, off)
            if t and t.kind == "prim" and t.context and t.number == 1:
                idx = _uint(data[t.data_offset:t.end]); off = t.end
            props.append((prop, idx))
        out.append((oid, props))
    return out


def parse_write_property_request(data: bytes) -> Tuple[ObjectId, int, Optional[int], Any, Optional[int]]:
    d, off = _expect_ctx(data, 0, 0); oid = _ctx_objid(d)
    d, off = _expect_ctx(data, off, 1); prop = _uint(d)
    idx = None
    t = decode_tag(data, off)
    if t.kind == "prim" and t.context and t.number == 2:
        idx = _uint(data[t.data_offset:t.end]); off = t.end
        t = decode_tag(data, off)
    if t.kind != "open" or t.number != 3:
        raise BACnetDecodeError("expected value")
    vals, off = decode_values(data, t.data_offset, close_tag=3)
    prio = None
    if off < len(data):
        d, off = _expect_ctx(data, off, 4); prio = _uint(d)
    return oid, prop, idx, _value_from_list(vals) if vals else NULL, prio


def parse_subscribe_cov_request(data: bytes) -> Tuple[int, ObjectId, Optional[bool], Optional[int]]:
    d, off = _expect_ctx(data, 0, 0); pid = _uint(d)
    d, off = _expect_ctx(data, off, 1); oid = _ctx_objid(d)
    confirmed = lifetime = None
    if off < len(data):
        d, off = _expect_ctx(data, off, 2); confirmed = bool(d[0]) if d else False
    if off < len(data):
        d, off = _expect_ctx(data, off, 3); lifetime = _uint(d)
    return pid, oid, confirmed, lifetime


def body_cov_notification(pid: int, device: int, oid: ObjectId, remaining: int,
                          values: List[Tuple[int, Any]]) -> bytes:
    out = ctx_unsigned(0, pid) + ctx_objid(1, ObjectId(C.OBJ_DEVICE, device)) + \
        ctx_objid(2, oid) + ctx_unsigned(3, remaining) + opening_tag(4)
    for prop, val in values:
        out += ctx_enumerated(0, prop) + opening_tag(2) + encode_application(val) + closing_tag(2)
    return out + closing_tag(4)


def body_read_property_ack(oid: ObjectId, prop: int, idx: Optional[int], value: Any) -> bytes:
    out = ctx_objid(0, oid) + ctx_enumerated(1, prop)
    if idx is not None:
        out += ctx_unsigned(2, idx)
    return out + opening_tag(3) + encode_application(value) + closing_tag(3)


# ==========================================================================
# Pretty printing
# ==========================================================================
def format_plain(v: Any) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return f"{v:.6g}" if not isinstance(v, Double) else f"{v:.10g}"
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v).hex().upper() if v else "(empty)"
    if isinstance(v, list):
        return "{" + ", ".join(format_plain(i) for i in v) + "}"
    return str(v)


def format_value(v: Any, obj_type: int = -1, prop: int = -1) -> str:
    """Human friendly string for a property value."""
    if prop == C.PROP_PRIORITY_ARRAY and isinstance(v, list):
        parts = [f"{i + 1}: {format_value(x, obj_type, C.PROP_PRESENT_VALUE)}"
                 for i, x in enumerate(v) if not isinstance(x, Null)]
        return "{" + ", ".join(parts) + "}" if parts else "{all NULL}"
    if prop == C.PROP_PROPERTY_LIST and isinstance(v, list):
        return "{" + ", ".join(C.property_name(int(x)) for x in v
                               if isinstance(x, int) and not isinstance(x, bool)) + "}"
    if isinstance(v, list):
        if not v:
            return "{}"
        items = [format_value(x, obj_type, prop) for x in v]
        txt = ", ".join(items)
        return "{" + (txt if len(txt) < 4000 else txt[:4000] + " …") + "}"
    if isinstance(v, BitString):
        names = C.bitstring_names_for(prop)
        if names:
            on = [names[i] if i < len(names) else f"bit{i}" for i, b in enumerate(v.bits) if b]
            if prop == C.PROP_STATUS_FLAGS:
                return str(v) + ("  " + ", ".join(on) if on else "  normal")
            return "{" + ", ".join(on) + "}" if on else "{}"
        return str(v)
    if isinstance(v, Enumerated):
        table = C.enum_table_for(obj_type, prop)
        if table is not None:
            name = table.get(int(v))
            if name is None:
                return f"{int(v)} (proprietary)" if int(v) >= 256 else str(int(v))
            return name
        return str(int(v))
    if prop == C.PROP_PRESENT_VALUE and obj_type in C.BINARY_TYPES and isinstance(v, int) \
            and not isinstance(v, bool):
        return C.BINARY_PV.get(int(v), str(int(v)))
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return str(int(v))
    return format_plain(v)


def type_name_of(v: Any) -> str:
    if isinstance(v, Null): return "Null"
    if isinstance(v, bool): return "Boolean"
    if isinstance(v, Enumerated): return "Enumerated"
    if isinstance(v, Signed): return "Signed"
    if isinstance(v, int): return "Unsigned"
    if isinstance(v, Double): return "Double"
    if isinstance(v, float): return "Real"
    if isinstance(v, str): return "CharacterString"
    if isinstance(v, (bytes, bytearray)): return "OctetString"
    if isinstance(v, BitString): return "BitString"
    if isinstance(v, Date): return "Date"
    if isinstance(v, Time): return "Time"
    if isinstance(v, ObjectId): return "ObjectIdentifier"
    if isinstance(v, list): return "Array/List"
    if isinstance(v, Constructed): return "Constructed"
    if isinstance(v, ContextValue): return "Context"
    return type(v).__name__


WRITABLE_TYPES = ["Real", "Unsigned", "Signed", "Enumerated", "Boolean", "CharacterString",
                  "Double", "Null", "ObjectIdentifier", "BitString", "OctetString", "Date",
                  "Time"]


def parse_user_value(text: str, type_name: str) -> Any:
    """Convert user-entered text into a typed BACnet value."""
    s = text.strip()
    if type_name == "Null" or s.upper() == "NULL":
        return NULL
    if type_name == "Real":
        return Real(float(s))
    if type_name == "Double":
        return Double(float(s))
    if type_name == "Unsigned":
        n = int(s, 0)
        if n < 0:
            raise ValueError("Unsigned must be ≥ 0")
        return Unsigned(n)
    if type_name == "Signed":
        return Signed(int(s, 0))
    if type_name == "Enumerated":
        low = s.lower()
        if low in ("active", "on", "true"):
            return Enumerated(1)
        if low in ("inactive", "off", "false"):
            return Enumerated(0)
        return Enumerated(int(s.split()[0], 0))
    if type_name == "Boolean":
        if s.lower() in ("1", "true", "t", "yes", "on", "active"):
            return True
        if s.lower() in ("0", "false", "f", "no", "off", "inactive"):
            return False
        raise ValueError("Boolean must be true/false")
    if type_name == "CharacterString":
        return CharacterString(text)
    if type_name == "ObjectIdentifier":
        return ObjectId.parse(s)
    if type_name == "BitString":
        s = s.strip("{}[] ")
        bits = [c.upper() in ("1", "T") for c in s.replace(",", "").replace(" ", "")]
        return BitString(bits)
    if type_name == "OctetString":
        s = s[2:] if s.lower().startswith("0x") else s
        return OctetString(bytes.fromhex(s.replace(" ", "")))
    if type_name == "Date":
        d = _dt.date.fromisoformat(s)
        return Date(d.year, d.month, d.day, d.isoweekday())
    if type_name == "Time":
        parts = [int(p) for p in s.replace(".", ":").split(":")]
        while len(parts) < 4:
            parts.append(0)
        return Time(*parts[:4])
    raise ValueError(f"Unsupported type {type_name}")
