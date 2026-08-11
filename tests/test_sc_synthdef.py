import pytest

from moogone.osc import OscMessage
from moogone.sc.client import ScError

# A real .scsyndef begins with the magic bytes "SCgf".
VALID_SYNTHDEF = b"SCgf\x00\x00\x00\x02" + b"\x00" * 32
INVALID_SYNTHDEF = b"NOPE" + b"\x00" * 32


def test_d_recv_loads_a_synthdef(client, mock_server):
    client.d_recv(VALID_SYNTHDEF)
    assert mock_server.loaded_synthdefs == [VALID_SYNTHDEF]


def test_d_recv_payload_encodes_as_a_blob():
    """A str synthdef would silently encode as OSC type tag 's' (and get
    truncated at the first embedded null byte) instead of 'b' -- that
    would otherwise only surface later as a confusing five-second
    ScTimeout plus a background-thread decode-failure warning. Assert the
    type tag directly so a bytes-to-str regression fails fast and legibly.
    """
    encoded = OscMessage("/d_recv", [VALID_SYNTHDEF]).encode()
    # typetag string is ",b" padded to 4 -- same pattern as the existing
    # Float64 typetag check in test_osc_message.py.
    assert b",b\x00\x00" in encoded


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
