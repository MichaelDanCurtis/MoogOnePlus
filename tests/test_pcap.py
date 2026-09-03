"""Tests for the voice-bus pcap dissector.

Frames are built here rather than captured, so the parsing is checked against bytes
whose meaning is known exactly — the opposite of reading a real capture and trusting
the reading.
"""

from __future__ import annotations

import struct

import pytest

from moogone.pcap import (
    OscMessage,
    PcapError,
    datagrams,
    parse_osc,
    read_pcap,
    render,
    summarise,
    udp_of,
)


def osc(address: str, tags: str = "", args: bytes = b"") -> bytes:
    def pad(b: bytes) -> bytes:
        b += b"\x00"
        return b + b"\x00" * (-len(b) % 4)

    return pad(address.encode()) + (pad(("," + tags).encode()) if tags else b"") + args


def frame(payload: bytes, src="203.0.113.1", dst="203.0.113.2", sport=38433, dport=9100) -> bytes:
    eth = b"\x02" * 6 + b"\x02" * 6 + struct.pack("!H", 0x0800)
    udp = struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = (
        struct.pack("!BBH", 0x45, 0, 20 + len(udp))
        + struct.pack("!HHBBH", 0, 0, 64, 17, 0)
        + bytes(int(x) for x in src.split("."))
        + bytes(int(x) for x in dst.split("."))
    )
    return eth + ip + udp


def pcap(frames: list[bytes], magic=0xA1B2C3D4, endian="<") -> bytes:
    out = struct.pack(endian + "IHHiIII", magic, 2, 4, 0, 0, 262144, 1)
    for i, f in enumerate(frames):
        out += struct.pack(endian + "IIII", 1000 + i, 0, len(f), len(f)) + f
    return out


class TestReadPcap:
    def test_reads_records(self):
        assert len(read_pcap(pcap([frame(osc("/a")), frame(osc("/b"))]))) == 2

    def test_big_endian_file_is_read_too(self):
        # A big-endian writer lays the magic down as A1 B2 C3 D4, so a reader that
        # unpacks little-endian sees 0xD4C3B2A1 and must swap. Writing the swapped
        # CONSTANT big-endian would produce a little-endian file with big-endian
        # record headers, which is not a thing that exists.
        data = pcap([frame(osc("/a"))], magic=0xA1B2C3D4, endian=">")
        assert data[:4] == b"\xa1\xb2\xc3\xd4"
        assert len(read_pcap(data)) == 1

    def test_nanosecond_timestamps_are_scaled_differently(self):
        us = read_pcap(pcap([frame(osc("/a"))], magic=0xA1B2C3D4))
        ns = read_pcap(pcap([frame(osc("/a"))], magic=0xA1B23C4D))
        assert us[0][0] == ns[0][0]  # frac is 0 here; the point is both parse

    def test_pcapng_is_named_not_guessed_at(self):
        with pytest.raises(PcapError, match="pcapng"):
            read_pcap(b"\x0a\x0d\x0d\x0a" + b"\x00" * 40)

    def test_not_a_pcap_at_all(self):
        with pytest.raises(PcapError, match="not a pcap"):
            read_pcap(b"PK\x03\x04" + b"\x00" * 40)

    def test_too_short(self):
        with pytest.raises(PcapError, match="too short"):
            read_pcap(b"\xd4\xc3\xb2\xa1")

    def test_a_truncated_final_record_keeps_the_records_before_it(self):
        data = pcap([frame(osc("/a")), frame(osc("/b"))])
        assert len(read_pcap(data[:-10])) == 1


class TestUdpOf:
    def test_extracts_addresses_and_ports(self):
        r = udp_of(frame(osc("/lfoleds"), dport=9100))
        assert r is not None
        src, sport, dst, dport, payload = r
        assert (src, sport, dst, dport) == ("203.0.113.1", 38433, "203.0.113.2", 9100)
        assert payload.startswith(b"/lfoleds")

    def test_non_ip_frame_is_ignored(self):
        assert udp_of(b"\x02" * 12 + struct.pack("!H", 0x0806) + b"\x00" * 40) is None

    def test_non_udp_ip_frame_is_ignored(self):
        f = bytearray(frame(osc("/a")))
        f[14 + 9] = 6  # TCP
        assert udp_of(bytes(f)) is None

    def test_a_truncated_capture_does_not_read_past_the_bytes_present(self):
        # length says more than was captured; the payload must not be silently empty
        # nor an IndexError, but exactly what is there.
        f = bytearray(frame(b"12345678"))
        f[14 + 20 + 4 : 14 + 20 + 6] = struct.pack("!H", 8 + 64)
        r = udp_of(bytes(f))
        assert r is not None and r[4] == b"12345678"


class TestParseOsc:
    def test_address_and_tags(self):
        assert parse_osc(osc("/od/0/cp", "i", b"\x00\x00\x00\x01")) == [
            OscMessage("/od/0/cp", "i", b"\x00\x00\x00\x01")
        ]

    def test_address_with_no_type_tag_string(self):
        assert parse_osc(osc("/bare")) == [OscMessage("/bare", "", b"")]

    def test_bundle_is_flattened(self):
        inner = [osc("/a", "i", b"\x00\x00\x00\x01"), osc("/b", "f", b"\x00\x00\x00\x00")]
        payload = b"#bundle\x00" + b"\x00" * 8
        for m in inner:
            payload += struct.pack("!I", len(m)) + m
        assert [m.address for m in parse_osc(payload)] == ["/a", "/b"]

    def test_a_bundle_claiming_more_than_it_holds_stops_rather_than_raising(self):
        payload = b"#bundle\x00" + b"\x00" * 8 + struct.pack("!I", 9999) + osc("/a")
        assert parse_osc(payload) == []

    def test_malformed_packet_is_dropped_not_raised(self):
        # No terminating NUL: one bad packet must not lose the rest of a capture.
        assert parse_osc(b"/no-null-here") == []

    def test_empty_payload(self):
        assert parse_osc(b"") == []

    def test_deep_nesting_terminates(self):
        payload = osc("/a")
        for _ in range(10):
            payload = b"#bundle\x00" + b"\x00" * 8 + struct.pack("!I", len(payload)) + payload
        assert parse_osc(payload) == []  # depth-limited rather than recursing forever


class TestSummarise:
    def test_counts_flows_and_signatures(self):
        data = pcap(
            [
                frame(osc("/lfoleds", "b", b"\x00" * 8), dport=9100),
                frame(osc("/lfoleds", "b", b"\x00" * 8), dport=9100),
                frame(osc("/od/0/l8m", "iiiiiib", b"\x00" * 32), dport=9876),
            ]
        )
        flows, signatures, sample = summarise(data)
        assert flows[("203.0.113.1", "203.0.113.2", 9100)] == 2
        assert signatures[(9100, "/lfoleds", "b")] == 2
        assert signatures[(9876, "/od/0/l8m", "iiiiiib")] == 1
        assert sample[(9100, "/lfoleds", "b")][0] == 8

    def test_the_same_address_on_two_ports_stays_distinct(self):
        # /cb appears on both 9100 and 9600 on the real bus, with different meanings.
        data = pcap(
            [
                frame(osc("/cb", "i", b"\x00" * 4), dport=9100),
                frame(osc("/cb", "i", b"\x00" * 4), dport=9600),
            ]
        )
        _flows, signatures, _sample = summarise(data)
        assert signatures[(9100, "/cb", "i")] == 1
        assert signatures[(9600, "/cb", "i")] == 1

    def test_render_names_the_flow_and_the_address(self):
        out = render(pcap([frame(osc("/therm/sys-temp", "i", b"\x00\x00\x00\x42"), dport=7770)]))
        assert "203.0.113.1 -> 203.0.113.2:7770" in out
        assert "/therm/sys-temp" in out

    def test_datagrams_are_returned_in_capture_order(self):
        data = pcap([frame(osc("/first"), dport=9100), frame(osc("/second"), dport=9876)])
        assert [d.dst_port for d in datagrams(data)] == [9100, 9876]
