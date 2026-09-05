"""Tests for the performance protocol decoder.

The bytes in `REAL_*` were captured from the instrument while playing known notes,
so these are checks against the device's own output rather than against this
module's idea of it.
"""

from __future__ import annotations

import math
import struct

import pytest

from moogone.pcap import Datagram
from moogone.performance import (
    OP_NOTE,
    PERFORMANCE_PORT,
    Note,
    Unknown,
    Voices,
    decode,
    encode_note,
    encode_note_off,
    notes_in,
)

# Captured 2026-09-03 while sending MIDI note 60 at velocity 100.
REAL_NOTE_ON = bytes.fromhex(
    "2f000000" "2c69696669000000" "00000004" "0000003c" "3f499326" "00000000"
)
REAL_NOTE_OFF = bytes.fromhex(
    "2f000000" "2c69696669000000" "00000004" "0000003c" "80000000" "00000000"
)
REAL_OP8 = bytes.fromhex("2f000000" "2c696900" "00000008" "0000fff7")


class TestRealCapturedBytes:
    def test_note_on_60(self):
        m = decode(REAL_NOTE_ON)
        assert isinstance(m, Note)
        assert m.note == 60
        assert not m.is_note_off
        assert m.midi_velocity == 100, "velocity 100/127 normalises to 0.7874"

    def test_note_off_60(self):
        m = decode(REAL_NOTE_OFF)
        assert isinstance(m, Note)
        assert m.note == 60
        assert m.is_note_off

    def test_note_off_velocity_is_negative_zero_not_a_different_opcode(self):
        m = decode(REAL_NOTE_OFF)
        assert m.velocity == 0.0, "it really does equal zero"
        assert math.copysign(1.0, m.velocity) < 0, "and is told apart only by its sign"

    def test_comparing_velocity_to_zero_cannot_distinguish_them(self):
        # The trap this decoder exists to avoid, stated as a test. A naive
        # implementation asks `velocity == 0`, which gives the SAME answer for the
        # note-off's -0.0 as for a note-on at +0.0. Only the sign bit separates them.
        def naive_is_off(v: float) -> bool:
            return v == 0.0

        assert naive_is_off(-0.0) == naive_is_off(0.0), "a zero test cannot see the sign"
        assert Note(60, -0.0).is_note_off is True
        assert Note(60, 0.0).is_note_off is False, "and is_note_off can"
        assert decode(REAL_NOTE_ON).is_note_off is False
        assert decode(REAL_NOTE_OFF).is_note_off is True

    def test_op8_is_the_voice_mask(self):
        m = decode(REAL_OP8)
        assert isinstance(m, Voices)
        assert m.mask & 0xFFFF == 0xFFF7
        assert m.count == 15, "every voice but one"

    #: Captured 2026-09-05 while six notes were stacked one at a time over USB MIDI
    #: and released in the same order. The instrument emits one of these after every
    #: note event, so the sequence is the voice allocator's own account of itself.
    STACKED = (0x20, 0x60, 0xE0, 0x1E0, 0x3E0, 0x7E0)
    RELEASED = (0x7C0, 0x780, 0x700, 0x600, 0x400, 0x0)

    def test_popcount_tracks_the_notes_being_held(self):
        held = [Voices(m).count for m in self.STACKED]
        assert held == [1, 2, 3, 4, 5, 6], "one bit per note, going up"
        left = [Voices(m).count for m in self.RELEASED]
        assert left == [5, 4, 3, 2, 1, 0], "and one bit fewer per release"

    def test_a_release_clears_the_bit_its_note_on_set(self):
        # Notes went on 60 62 64 65 67 69 and came off in the same order, so the
        # first release must clear the first bit that was set, not the last.
        first_on = Voices(self.STACKED[0]).voices
        assert first_on == (5,)
        after_all_on = set(Voices(self.STACKED[-1]).voices)
        after_one_off = set(Voices(self.RELEASED[0]).voices)
        assert after_all_on - after_one_off == {5}

    def test_voices_lists_indices_lowest_first(self):
        assert Voices(0b1010_0000).voices == (5, 7)
        assert Voices(0).voices == ()
        assert Voices(0).count == 0


class TestDecode:
    @pytest.mark.parametrize("note", [0, 21, 60, 108, 127])
    def test_round_trip(self, note):
        m = decode(encode_note(note, 0.5))
        assert isinstance(m, Note) and m.note == note

    def test_round_trip_note_off(self):
        m = decode(encode_note_off(64))
        assert m.note == 64 and m.is_note_off

    def test_encode_matches_the_instruments_own_bytes(self):
        # velocity 100/127 as the device sends it
        assert encode_note(60, struct.unpack("!f", bytes.fromhex("3f499326"))[0]) == REAL_NOTE_ON
        assert encode_note_off(60) == REAL_NOTE_OFF

    def test_note_out_of_range_is_refused(self):
        with pytest.raises(ValueError, match="outside 0-127"):
            encode_note(128, 0.5)

    def test_non_performance_payload_is_none_not_an_error(self):
        assert decode(b"/lfoleds\x00\x00\x00\x00,b\x00\x00" + b"\x00" * 8) is None

    def test_truncated_payload_is_none(self):
        assert decode(REAL_NOTE_ON[:10]) is None

    def test_empty_payload_is_none(self):
        assert decode(b"") is None

    def test_an_iifi_with_an_unexpected_opcode_is_not_read_as_a_note(self):
        payload = (
            b"/\x00\x00\x00" + b",iifi\x00\x00\x00"
            + struct.pack("!ii", 99, 60) + struct.pack("!f", 0.5) + struct.pack("!i", 0)
        )
        m = decode(payload)
        assert isinstance(m, Unknown) and m.op == 99


class TestNotesIn:
    def test_filters_by_port_and_type(self):
        ds = [
            Datagram(1.0, "203.0.113.2", PERFORMANCE_PORT, "203.0.113.1", PERFORMANCE_PORT,
                     REAL_NOTE_ON),
            Datagram(1.1, "203.0.113.2", PERFORMANCE_PORT, "203.0.113.1", PERFORMANCE_PORT,
                     REAL_OP8),
            Datagram(1.2, "203.0.113.1", 38433, "203.0.113.2", 9100, b"/lfoleds\x00\x00\x00\x00"),
        ]
        assert [n.note for n in notes_in(ds)] == [60]

    def test_a_note_shaped_payload_on_another_port_is_ignored(self):
        ds = [Datagram(1.0, "203.0.113.2", 9100, "203.0.113.1", 9100, REAL_NOTE_ON)]
        assert notes_in(ds) == []

    def test_op_note_constant_matches_the_capture(self):
        assert OP_NOTE == 4


class TestNoteStream:
    """The parsing half of the live feed, without an instrument or an SSH connection."""

    def test_decodes_notes_out_of_a_pcap_stream(self):
        import struct as _s

        from moogone.pcap import iter_records, udp_of
        from moogone.performance import Note, decode

        def frame(payload):
            eth = b"\x02" * 12 + _s.pack("!H", 0x0800)
            udp = _s.pack("!HHHH", 7772, 7772, 8 + len(payload), 0) + payload
            ip = (_s.pack("!BBH", 0x45, 0, 20 + len(udp)) + _s.pack("!HHBBH", 0, 0, 64, 17, 0)
                  + bytes((203, 0, 113, 2)) + bytes((203, 0, 113, 1)))
            return eth + ip + udp

        frames = [frame(REAL_NOTE_ON), frame(REAL_OP8), frame(REAL_NOTE_OFF)]
        blob = _s.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 262144, 1)
        for i, f in enumerate(frames):
            blob += _s.pack("<IIII", i, 0, len(f), len(f)) + f

        pos = 0

        def read(_n):  # one byte at a time, the worst case for a live pipe
            nonlocal pos
            out = blob[pos : pos + 1]
            pos += len(out)
            return out

        notes = []
        for _ts, fr in iter_records(read, chunk=1):
            u = udp_of(fr)
            m = decode(u[4])
            if isinstance(m, Note):
                notes.append(m)

        assert [(n.note, n.is_note_off) for n in notes] == [(60, False), (60, True)]

    def test_command_captures_only_the_performance_port(self):
        from moogone.performance import NoteStream

        cmd = NoteStream("192.0.2.1", on_note=lambda n: None).COMMAND
        assert "7772" in cmd and "udp" in cmd
        assert "9876" not in cmd, "a note stream must not pull the display framebuffers too"
        assert " -U " in cmd, "unbuffered, or the feed arrives in bursts"
        assert "-i usbint" in cmd

    def test_stop_is_safe_before_run(self):
        from moogone.performance import NoteStream

        NoteStream("192.0.2.1", on_note=lambda n: None).stop()  # must not raise
