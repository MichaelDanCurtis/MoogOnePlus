"""Tests for the /x parameter protocol.

`REAL_*` are bytes captured from the instrument while sweeping MIDI CC 7 through
known values, so these check against the device's own output.
"""

from __future__ import annotations

import struct

import pytest

from moogone.voicebus import (
    PARAM_MASTER_VOLUME,
    ParamWrite,
    decode,
    encode,
)

# Captured 2026-09-03. CC7 = 0, 32, 100 and 127 respectively.
REAL = {
    0: bytes.fromhex("2f780000" "2c620000" "00000008" "66010000" "00000000"),
    32: bytes.fromhex("2f780000" "2c620000" "00000008" "66010000" "0402813e"),
    100: bytes.fromhex("2f780000" "2c620000" "00000008" "66010000" "2693493f"),
    127: bytes.fromhex("2f780000" "2c620000" "00000008" "66010000" "0000803f"),
}


class TestRealBytes:
    @pytest.mark.parametrize("cc", [0, 32, 100, 127])
    def test_master_volume_decodes_to_the_value_that_was_sent(self, cc):
        m = decode(REAL[cc])
        assert m.param == PARAM_MASTER_VOLUME == 358
        assert m.as_midi == cc

    def test_the_payload_is_little_endian(self):
        # Read big-endian, CC127's 0x0000803f is a denormal near 1e-41 -- garbage that
        # looks like noise rather than like a wrong guess. This is the trap.
        blob = REAL[127][12:]
        assert struct.unpack("<f", blob[4:8])[0] == 1.0
        assert struct.unpack(">f", blob[4:8])[0] < 1e-40

    def test_full_scale_is_one(self):
        assert decode(REAL[127]).value == 1.0

    def test_zero_is_zero(self):
        assert decode(REAL[0]).value == 0.0


class TestRoundTrip:
    @pytest.mark.parametrize("value", [0.0, 0.00787, 0.25197, 0.5, 0.7874, 1.0])
    def test_encode_decode(self, value):
        m = decode(encode(PARAM_MASTER_VOLUME, value))
        assert m.param == PARAM_MASTER_VOLUME
        assert m.value == pytest.approx(value, abs=1e-6)

    def test_encode_matches_the_instrument_byte_for_byte(self):
        assert encode(PARAM_MASTER_VOLUME, 1.0) == REAL[127]
        assert encode(PARAM_MASTER_VOLUME, 0.0) == REAL[0]

    def test_param_must_fit_in_16_bits(self):
        with pytest.raises(ValueError, match="16 bits"):
            encode(70000, 0.5)


class TestDecodeRejects:
    def test_a_note_message(self):
        assert decode(b"/\x00\x00\x00,iifi\x00\x00\x00" + bytes(16)) is None

    def test_a_display_tile(self):
        assert decode(b"/od/0/l8m\x00\x00\x00,iiiiiib\x00\x00\x00" + bytes(28)) is None

    def test_truncated(self):
        assert decode(REAL[127][:10]) is None
        assert decode(b"") is None

    def test_a_blob_shorter_than_it_claims(self):
        bad = b"/x\x00\x00,b\x00\x00" + struct.pack("!I", 8) + b"\x00\x00"
        assert decode(bad) is None

    def test_wrong_type_tag(self):
        bad = b"/x\x00\x00" + b",i\x00\x00" + struct.pack("!I", 8) + bytes(8)
        assert decode(bad) is None


def test_as_midi_rounds_the_way_the_instrument_scales():
    assert ParamWrite(358, 100 / 127).as_midi == 100
    assert ParamWrite(358, 0.0).as_midi == 0
    assert ParamWrite(358, 1.0).as_midi == 127
