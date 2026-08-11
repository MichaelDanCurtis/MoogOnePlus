import pytest

from moogone.osc.message import Float64, OscBundle, OscMessage, decode


def test_message_with_no_args_encodes_address_and_empty_typetag():
    encoded = OscMessage("/status", []).encode()
    assert encoded == b"/status\x00" + b",\x00\x00\x00"


def test_message_infers_types_from_python_values():
    encoded = OscMessage("/n_set", [1000, "amp", 0.5]).encode()
    decoded = decode(encoded)
    assert decoded.address == "/n_set"
    assert decoded.args[0] == 1000
    assert decoded.args[1] == "amp"
    assert decoded.args[2] == pytest.approx(0.5)


def test_float64_wrapper_forces_double_typetag():
    encoded = OscMessage("/x", [Float64(44100.0)]).encode()
    # typetag string is ",d" padded to 4
    assert b",d\x00\x00" in encoded
    decoded = decode(encoded)
    assert decoded.args[0] == pytest.approx(44100.0)


def test_blob_arg_round_trips():
    decoded = decode(OscMessage("/d_recv", [b"\x01\x02\x03"]).encode())
    assert decoded.args[0] == b"\x01\x02\x03"


def test_bundle_round_trips_with_nested_messages():
    bundle = OscBundle(1, [OscMessage("/a", [1]), OscMessage("/b", [2])])
    decoded = decode(bundle.encode())
    assert isinstance(decoded, OscBundle)
    assert decoded.timetag == 1
    assert [e.address for e in decoded.elements] == ["/a", "/b"]
    assert decoded.elements[1].args == [2]


def test_unknown_typetag_raises():
    # ",Q" is not a type tag we support
    bad = b"/x\x00\x00" + b",Q\x00\x00"
    with pytest.raises(ValueError, match="unsupported OSC type tag"):
        decode(bad)


def test_unencodable_arg_type_raises():
    with pytest.raises(TypeError, match="cannot encode"):
        OscMessage("/x", [{"not": "encodable"}]).encode()


def test_bundle_truncated_before_timetag_raises():
    """Bundle prefix exists but no timetag bytes: should raise, not decode as timetag=0."""
    bad = b"#bundle\x00"  # 8 bytes prefix, no timetag
    with pytest.raises(ValueError, match="truncated bundle timetag"):
        decode(bad)


def test_bundle_truncated_mid_timetag_raises():
    """Bundle prefix + 6 of 8 timetag bytes: should raise, not decode as partial int."""
    bad = b"#bundle\x00" + b"\x00" * 6  # prefix + 6 bytes, short of 8
    with pytest.raises(ValueError, match="truncated bundle timetag"):
        decode(bad)


def test_bundle_inflated_element_size_with_trailing_element_raises():
    """Inflated element size that fits in buffer but swallows next element: should raise.

    This is the core bug: an element declares size=24 bytes (msg_a + msg_b),
    but decoding msg_a only consumes 12 bytes. The remaining 12 bytes of msg_b
    vanish inside the first element's declared region, never parsed.
    """
    msg_a = OscMessage("/a", [1]).encode()
    msg_b = OscMessage("/b", [2]).encode()
    from moogone.osc import codec
    from moogone.osc.message import BUNDLE_PREFIX

    timetag = 1
    # Inflate the first element's size to claim both messages
    # (exactly what's left in the buffer, no overrun)
    inflated_size = len(msg_a) + len(msg_b)

    bad_bundle = (
        BUNDLE_PREFIX
        + timetag.to_bytes(8, "big")
        + codec.enc_int32(inflated_size)
        + msg_a
        + msg_b
    )

    # Should raise because element size doesn't match bytes actually consumed
    with pytest.raises(ValueError, match="declared but only .* bytes consumed"):
        decode(bad_bundle)


def test_bundle_element_size_truly_overruns_buffer_raises():
    """Element size claims more bytes than buffer has: should raise.

    This is a separate case from the swallowing bug: when size goes
    genuinely past the buffer end (not just past what gets consumed).
    """
    msg_a = OscMessage("/a", [1]).encode()
    msg_b = OscMessage("/b", [2]).encode()
    from moogone.osc import codec
    from moogone.osc.message import BUNDLE_PREFIX

    timetag = 1
    # Inflate the size to go BEYOND the buffer entirely
    inflated_size = len(msg_a) + len(msg_b) + 100

    bad_bundle = (
        BUNDLE_PREFIX
        + timetag.to_bytes(8, "big")
        + codec.enc_int32(inflated_size)
        + msg_a
        + msg_b
    )

    with pytest.raises(ValueError, match="overruns buffer"):
        decode(bad_bundle)


def test_bundle_negative_element_size_raises():
    """Negative element size should raise, not wrap via Python's negative indexing."""
    from moogone.osc import codec
    from moogone.osc.message import BUNDLE_PREFIX

    timetag = 1
    negative_size = -100

    bad_bundle = (
        BUNDLE_PREFIX
        + timetag.to_bytes(8, "big")
        + codec.enc_int32(negative_size)
        + b"junk data"
    )

    with pytest.raises(ValueError, match="cannot be negative"):
        decode(bad_bundle)


def test_decode_is_lenient_about_trailing_bytes_on_plain_message():
    """decode() must stay lenient: trailing bytes on a whole packet are acceptable.

    This is the design decision: we're strict about element sizes inside bundles
    (explicit framing), but lenient about trailing data in top-level packets
    (which may be benign padding from the server).
    """
    msg = OscMessage("/x", [1]).encode()
    # Add arbitrary trailing junk
    padded = msg + b"\x00" * 50

    decoded = decode(padded)
    assert decoded.address == "/x"
    assert decoded.args == [1]


def test_bundle_with_nested_bundle_round_trips():
    """Nested bundles must work and verify element consumption correctly."""
    inner_bundle = OscBundle(2, [OscMessage("/inner", [99])])
    outer_bundle = OscBundle(1, [OscMessage("/outer", [42]), inner_bundle])

    encoded = outer_bundle.encode()
    decoded = decode(encoded)

    assert isinstance(decoded, OscBundle)
    assert decoded.timetag == 1
    assert len(decoded.elements) == 2
    assert decoded.elements[0].address == "/outer"
    assert decoded.elements[1].timetag == 2
    assert decoded.elements[1].elements[0].address == "/inner"
