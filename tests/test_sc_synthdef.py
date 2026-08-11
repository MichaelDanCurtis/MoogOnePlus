import pytest

from moogone.osc import OscMessage
from moogone.sc.client import ScError, ScTimeout

# A real .scsyndef begins with the magic bytes "SCgf".
VALID_SYNTHDEF = b"SCgf\x00\x00\x00\x02" + b"\x00" * 32
INVALID_SYNTHDEF = b"NOPE" + b"\x00" * 32


def test_d_recv_loads_a_synthdef(client, mock_server):
    client.d_recv(VALID_SYNTHDEF)
    assert mock_server.loaded_synthdefs == [VALID_SYNTHDEF]


def test_d_recv_sends_the_payload_as_bytes_on_the_wire(client, mock_server):
    """A codec-level check alone (building an OscMessage by hand and
    asserting its 'b' type tag) doesn't prove d_recv() itself sends
    bytes -- it would stay green even if d_recv() decoded the payload to
    a str before ever reaching request()/encode(), since it never calls
    d_recv() at all. This test exercises the real call site instead and
    inspects what the mock actually decoded off the wire: an OSC blob
    ('b') decodes back to Python bytes, an OSC string ('s') decodes to
    str, so the argument's Python type here reflects the wire type tag
    directly. (The codec's own bytes round trip is already covered by
    test_blob_arg_round_trips in test_osc_message.py -- this test's job
    is the call site, not the codec.)

    The timeout is short and deliberate: if the payload regressed to
    str, the mock would decode it as "SCgf" (truncated at the first
    embedded null -- SCgf's own magic bytes contain one), and
    payload.startswith(b"SCgf") inside handle() would then raise
    TypeError, silently killing the mock's daemon thread before any
    reply is sent -- d_recv() would otherwise hang for its full 5s
    default timeout with no direct signal of why. `received` is
    populated before handle() runs, so the message is still visible even
    when handle() goes on to crash from it.
    """
    try:
        client.d_recv(VALID_SYNTHDEF, timeout=0.3)
    except ScTimeout:
        pass
    reply = mock_server.wait_for_message("/d_recv", timeout=0.5)
    assert isinstance(reply.args[0], bytes)


def test_d_recv_rejects_malformed_synthdef(client):
    # match pins to the SCgf check's own rejection reason, not just "some
    # /fail happened while handling /d_recv" -- a bare match="/d_recv"
    # would also match the generic "Command not found" fallback /fail
    # (e.g. if the mock's whole /d_recv branch went missing), without ever
    # exercising the magic-bytes check this test claims to cover.
    with pytest.raises(ScError, match=r"/d_recv.*not a synthdef file"):
        client.d_recv(INVALID_SYNTHDEF)


def test_d_recv_rejects_empty_payload_before_sending(client, mock_server):
    with pytest.raises(ValueError, match="empty"):
        client.d_recv(b"")
    # loaded_synthdefs alone can't prove *ordering*: an empty payload also
    # fails the mock's own SCgf check, so it would end up empty even if
    # the client sent it first and raised afterwards -- both paths
    # converge on the same empty list. `received` is populated the moment
    # a datagram arrives, before any /d_recv-specific validation runs, so
    # it doesn't have that blind spot.
    #
    # The barrier below is wait_for_message, not client.sync(): sync()
    # reads its reply back over the client socket via _await_reply, which
    # raises ScError on *any* /fail it sees -- including a stale one left
    # over from a wrongly-sent /d_recv -- so it would abort before the
    # assertions below ever ran, masking the very bug this test exists to
    # catch. wait_for_message instead polls the mock's own `received` list
    # directly and never touches the client socket, so it can't be
    # pre-empted that way. The mock's serve loop is single-threaded and
    # strictly sequential (one recvfrom() -> handle() cycle at a time), so
    # once the probe below shows up in `received`, anything sent earlier
    # on this socket is already there too.
    client.send("/probe_after_empty_d_recv", 1)
    mock_server.wait_for_message("/probe_after_empty_d_recv", timeout=1.0)
    assert not any(m.address == "/d_recv" for m in mock_server.received)
    assert mock_server.loaded_synthdefs == []


def test_handle_replies_fail_for_d_recv_without_args(mock_server):
    """A bare /d_recv with no payload must reply /fail, not raise
    IndexError and silently kill the daemon thread -- same class of bug
    the other argless guards (/sync, /notify, /dumpOSC, /n_set, /n_query)
    already cover.
    """
    reply = mock_server.handle(OscMessage("/d_recv", []))
    assert reply == OscMessage("/fail", ["/d_recv", "Wrong number of arguments"])
