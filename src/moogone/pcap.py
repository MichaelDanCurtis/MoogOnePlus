"""Dissect a pcap of the Moog One's internal voice/panel bus.

`tcpdump -i usbint` on the instrument captures the conversation between its two
computers. This turns that file into a map: who talks to whom, on which port, with
which OSC addresses and type tags, and how often.

Written because the throwaway version of this script produced the first wire-level
picture of the panel and display protocols, and that experiment needs repeating —
the interesting capture is the one taken *while a control is moved*, and a capture
you cannot re-run is a capture you have to get right first time.

Pure functions over bytes, so the parsing is testable without a network or a device.
"""

from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass

# pcap magic numbers. The two "swapped" spellings are the same format written by a
# host of the other endianness; the nanosecond variants differ only in the timestamp
# unit, which is why they are matched here rather than assumed.
_MAGIC_US = 0xA1B2C3D4
_MAGIC_NS = 0xA1B23C4D
_MAGIC_US_SWAPPED = 0xD4C3B2A1
_MAGIC_NS_SWAPPED = 0x4D3CB2A1

ETHERTYPE_IP = 0x0800
PROTO_UDP = 17

# Link types, from the pcap header's final field.
#
# `tcpdump -i usbint` writes Ethernet. **`tcpdump -i any` does not** — it writes
# Linux "cooked" frames, because a capture spanning several interfaces has no one
# link layer to report. The cooked header is 16 bytes with the protocol at offset
# 14, where Ethernet has 14 with the protocol at 12, so reading one as the other
# finds no IPv4 and silently yields zero datagrams. That is exactly what happened
# to the first panel capture.
LINKTYPE_EN10MB = 1
LINKTYPE_LINUX_SLL = 113

#: (header length, offset of the 16-bit protocol field) per link type.
_LINK_LAYOUT = {
    LINKTYPE_EN10MB: (14, 12),
    LINKTYPE_LINUX_SLL: (16, 14),
}


class PcapError(ValueError):
    """A file that is not a pcap this module can read, and why."""


@dataclass(frozen=True)
class Datagram:
    ts: float
    src: str
    src_port: int
    dst: str
    dst_port: int
    payload: bytes


@dataclass(frozen=True)
class OscMessage:
    address: str
    tags: str  # without the leading comma
    args: bytes  # raw, undecoded: the argument block after the type tag string


def _pad4(n: int) -> int:
    return (n + 3) & ~3


def read_pcap(data: bytes) -> list[tuple[float, bytes]]:
    """(timestamp, link-layer frame) for each record. Classic pcap only, not pcapng."""
    if len(data) < 24:
        raise PcapError("too short to be a pcap file")
    (magic,) = struct.unpack("<I", data[:4])
    if magic in (_MAGIC_US, _MAGIC_NS):
        endian = "<"
    elif magic in (_MAGIC_US_SWAPPED, _MAGIC_NS_SWAPPED):
        endian = ">"
    elif data[:4] == b"\x0a\x0d\x0d\x0a":
        raise PcapError("this is a pcapng file; capture with `tcpdump -w` for classic pcap")
    else:
        raise PcapError(f"not a pcap file (magic {magic:#010x})")
    nano = magic in (_MAGIC_NS, _MAGIC_NS_SWAPPED)

    out: list[tuple[float, bytes]] = []
    off = 24
    while off + 16 <= len(data):
        ts, frac, caplen, _wirelen = struct.unpack(endian + "IIII", data[off : off + 16])
        off += 16
        if caplen > len(data) - off:  # truncated final record: keep what came before
            break
        out.append((ts + frac / (1e9 if nano else 1e6), data[off : off + caplen]))
        off += caplen
    return out


def linktype_of(data: bytes) -> int:
    """The link type declared in a pcap file header."""
    (magic,) = struct.unpack("<I", data[:4])
    endian = "<" if magic in (_MAGIC_US, _MAGIC_NS) else ">"
    (link,) = struct.unpack(endian + "I", data[20:24])
    return link


def udp_of(
    frame: bytes, linktype: int = LINKTYPE_EN10MB
) -> tuple[str, int, str, int, bytes] | None:
    """Pull (src, sport, dst, dport, payload) out of a link-layer frame, or None.

    Defaults to Ethernet, which is what `-i usbint` and `-i lo` produce; pass
    LINKTYPE_LINUX_SLL for a capture taken with `-i any`.
    """
    hdr, proto_at = _LINK_LAYOUT.get(linktype, _LINK_LAYOUT[LINKTYPE_EN10MB])
    if len(frame) < hdr + 20:
        return None
    if struct.unpack("!H", frame[proto_at : proto_at + 2])[0] != ETHERTYPE_IP:
        return None
    ip = frame[hdr:]
    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0F) * 4
    if ip[9] != PROTO_UDP or len(ip) < ihl + 8:
        return None
    src = ".".join(str(b) for b in ip[12:16])
    dst = ".".join(str(b) for b in ip[16:20])
    udp = ip[ihl:]
    sport, dport, length = struct.unpack("!HHH", udp[:6])
    # `length` counts the 8-byte UDP header. A capture can be short; never slice past
    # what is actually present, or a truncated packet becomes a silent empty payload.
    end = min(max(length, 8), len(udp))
    return src, sport, dst, dport, udp[8:end]


def datagrams(data: bytes) -> list[Datagram]:
    link = linktype_of(data)
    out = []
    for ts, frame in read_pcap(data):
        u = udp_of(frame, link)
        if u is not None:
            out.append(Datagram(ts, u[0], u[1], u[2], u[3], u[4]))
    return out


def _string_at(b: bytes, i: int) -> tuple[str, int]:
    end = b.index(b"\x00", i)
    return b[i:end].decode("ascii", "replace"), i + _pad4(end + 1 - i)


def parse_osc(payload: bytes, _depth: int = 0) -> list[OscMessage]:
    """Every message in a packet — bundles flattened, malformed input dropped.

    Dropped rather than raised: a capture of a live bus will contain fragments and
    non-OSC traffic, and one bad packet must not lose the other ten thousand.
    """
    if not payload or _depth > 4:
        return []
    if payload[:8] == b"#bundle\x00":
        out: list[OscMessage] = []
        i = 16  # 8 bytes of "#bundle\0" plus a 64-bit time tag
        while i + 4 <= len(payload):
            (size,) = struct.unpack("!I", payload[i : i + 4])
            i += 4
            if size > len(payload) - i:
                break
            out.extend(parse_osc(payload[i : i + size], _depth + 1))
            i += size
        return out
    try:
        address, i = _string_at(payload, 0)
        tags = ""
        if i < len(payload) and payload[i : i + 1] == b",":
            tags, i = _string_at(payload, i)
            tags = tags[1:]
        return [OscMessage(address, tags, payload[i:])]
    except ValueError:
        return []


def summarise(data: bytes) -> tuple[Counter, Counter, dict]:
    """(flows, signatures, first-seen sample) — the three things a capture is read for.

    `flows` counts (src, dst, dst_port). `signatures` counts (dst_port, address, tags),
    which is the shape that distinguishes one protocol from another on a shared bus.
    """
    flows: Counter = Counter()
    signatures: Counter = Counter()
    sample: dict = {}
    for d in datagrams(data):
        for m in parse_osc(d.payload):
            flows[(d.src, d.dst, d.dst_port)] += 1
            key = (d.dst_port, m.address, m.tags)
            signatures[key] += 1
            sample.setdefault(key, (len(m.args), m.args[:24].hex()))
    return flows, signatures, sample


def render(data: bytes, top: int = 60) -> str:
    flows, signatures, sample = summarise(data)
    total = sum(flows.values())
    lines = [f"{total} OSC messages in {len(read_pcap(data))} packets", "", "flows:"]
    for (src, dst, port), n in flows.most_common():
        lines.append(f"  {src:>15} -> {dst}:{port:<6} {n:>8}")
    lines += ["", f"{len(signatures)} distinct (port, address, tags):"]
    for (port, address, tags), n in signatures.most_common(top):
        nbytes, head = sample[(port, address, tags)]
        lines.append(f"  :{port:<5} {address:<28} ,{tags:<10} n={n:<7} args={nbytes:<5} {head}")
    return "\n".join(lines)


def iter_records(read, *, chunk: int = 4096):
    """Yield (timestamp, frame) from a *live* pcap stream as records complete.

    `read(n)` is any blocking reader — a subprocess's stdout, a socket. This is what
    turns `tcpdump -w -` over SSH into a feed rather than a file: the global header
    arrives once, then each record is length-prefixed, so a partial record is held
    until the rest of it lands instead of being parsed as garbage.

    Stops when `read` returns empty, which is how a closed pipe presents itself.
    """
    buf = b""
    while len(buf) < 24:
        more = read(chunk)
        if not more:
            return
        buf += more
    (magic,) = struct.unpack("<I", buf[:4])
    if magic in (_MAGIC_US, _MAGIC_NS):
        endian = "<"
    elif magic in (_MAGIC_US_SWAPPED, _MAGIC_NS_SWAPPED):
        endian = ">"
    else:
        raise PcapError(f"stream does not start with a pcap header (magic {magic:#010x})")
    nano = magic in (_MAGIC_NS, _MAGIC_NS_SWAPPED)
    buf = buf[24:]

    while True:
        while len(buf) < 16:
            more = read(chunk)
            if not more:
                return
            buf += more
        ts, frac, caplen, _wire = struct.unpack(endian + "IIII", buf[:16])
        while len(buf) < 16 + caplen:
            more = read(chunk)
            if not more:
                return
            buf += more
        yield (ts + frac / (1e9 if nano else 1e6), buf[16 : 16 + caplen])
        buf = buf[16 + caplen :]
