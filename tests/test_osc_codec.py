import pytest

from moogone.osc import codec


def test_pad_to_4_rounds_up_to_multiple_of_four():
    assert codec.pad_to_4(0) == 0
    assert codec.pad_to_4(1) == 4
    assert codec.pad_to_4(4) == 4
    assert codec.pad_to_4(5) == 8


def test_string_encodes_null_terminated_and_padded():
    # "abc" is 3 chars + 1 null = 4, already aligned
    assert codec.enc_string("abc") == b"abc\x00"
    # "test" is 4 chars + 1 null = 5, pads to 8
    assert codec.enc_string("test") == b"test\x00\x00\x00\x00"
    # empty string is just a null, padded to 4
    assert codec.enc_string("") == b"\x00\x00\x00\x00"


def test_string_round_trips_and_reports_offset():
    buf = codec.enc_string("test") + b"TAIL"
    value, off = codec.dec_string(buf, 0)
    assert value == "test"
    assert off == 8
    assert buf[off:] == b"TAIL"


def test_int32_is_big_endian_signed():
    assert codec.enc_int32(1) == b"\x00\x00\x00\x01"
    assert codec.enc_int32(-1) == b"\xff\xff\xff\xff"
    assert codec.dec_int32(b"\x00\x00\x00\x2a", 0) == (42, 4)


def test_float32_round_trips():
    encoded = codec.enc_float32(1.0)
    assert encoded == b"\x3f\x80\x00\x00"
    value, off = codec.dec_float32(encoded, 0)
    assert value == pytest.approx(1.0)
    assert off == 4


def test_float64_round_trips_with_eight_byte_width():
    encoded = codec.enc_float64(44100.0)
    assert len(encoded) == 8
    value, off = codec.dec_float64(encoded, 0)
    assert value == pytest.approx(44100.0)
    assert off == 8


def test_blob_is_size_prefixed_and_padded():
    # 3 bytes of payload pads to 4
    assert codec.enc_blob(b"\x01\x02\x03") == b"\x00\x00\x00\x03\x01\x02\x03\x00"
    value, off = codec.dec_blob(b"\x00\x00\x00\x03\x01\x02\x03\x00", 0)
    assert value == b"\x01\x02\x03"
    assert off == 8


def test_truncated_buffer_raises():
    with pytest.raises(ValueError):
        codec.dec_int32(b"\x00\x00", 0)
    with pytest.raises(ValueError):
        codec.dec_string(b"no-null-here", 0)
