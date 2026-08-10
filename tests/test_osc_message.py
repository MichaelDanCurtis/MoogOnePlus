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
