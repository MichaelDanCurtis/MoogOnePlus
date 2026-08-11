import pytest

from moogone.osc import OscMessage
from moogone.sc.client import ScError

# A real .scsyndef begins with the magic bytes "SCgf".
VALID_SYNTHDEF = b"SCgf\x00\x00\x00\x02" + b"\x00" * 32
INVALID_SYNTHDEF = b"NOPE" + b"\x00" * 32


def test_d_recv_loads_a_synthdef(client, mock_server):
    client.d_recv(VALID_SYNTHDEF)
    assert mock_server.loaded_synthdefs == [VALID_SYNTHDEF]


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
    # it doesn't have that blind spot. /sync is a barrier: the mock's
    # serve loop is single-threaded and strictly sequential (one
    # recvfrom() -> handle() cycle at a time), so by the time /synced
    # comes back, anything sent earlier on this socket has already been
    # appended to `received`.
    client.sync(sync_id=8080)
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
