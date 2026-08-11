import ast
import socket
import time

import pytest

from moogone.mock.server import MockScsynth
from moogone.osc import OscMessage
from moogone.sc.client import ScClient, ScError
from moogone.transport.udp import UdpTransport


def test_status_returns_parsed_server_state(client):
    status = client.status()
    assert status.num_synths == 0
    assert status.sample_rate == pytest.approx(48000.0)
    assert status.actual_sample_rate == pytest.approx(48000.0, rel=1e-3)


def test_status_reply_wraps_sample_rates_as_osc_doubles(mock_server):
    # decode() erases the wire-level float/double distinction (both become
    # Python `float`), so this checks the pre-encode message directly: the
    # last two /status.reply args must be Float64-wrapped, or the real
    # server's doubles will decode as garbage (see module docstring intent).
    from moogone.osc import Float64

    reply = mock_server.handle(OscMessage("/status", []))
    assert isinstance(reply.args[-2], Float64)
    assert isinstance(reply.args[-1], Float64)


def test_server_records_what_it_received(client, mock_server):
    client.status()
    assert [m.address for m in mock_server.received] == ["/status"]


def test_unknown_command_raises_sc_error(client):
    from moogone.sc.client import ScError

    with pytest.raises(ScError, match="/nonsense"):
        client.request("/nonsense", reply="/never", timeout=1.0)


def test_request_times_out_when_no_reply_arrives(client, mock_server):
    from moogone.sc.client import ScTimeout

    mock_server.silent = True
    with pytest.raises(ScTimeout):
        client.request("/status", reply="/status.reply", timeout=0.2)


def test_send_is_fire_and_forget(client, mock_server):
    client.send("/n_free", 1000)
    # give the server a moment to log it
    mock_server.wait_for_message("/n_free", timeout=1.0)
    assert mock_server.received[-1] == OscMessage("/n_free", [1000])


def test_mock_survives_malformed_datagram_and_keeps_serving(client, mock_server):
    """A malformed datagram must not kill the mock's serve thread.

    Regression test for the bug folded into Task 5: decode() was unguarded
    in the serve loop, so one malformed packet raised inside the daemon
    thread and silently ended it. The mock then stopped answering anything,
    and every later failure in the same run would present as an unexplained
    ScTimeout with no sign the mock itself had died.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # No null byte anywhere in this payload, so dec_string's address
        # parse never finds a terminator and decode() raises ValueError.
        sock.sendto(b"not a valid osc packet", ("127.0.0.1", mock_server.port))

        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            with mock_server._lock:
                if mock_server.decode_errors:
                    break
            time.sleep(0.01)
        else:
            raise AssertionError("mock did not record the malformed datagram")
        assert len(mock_server.decode_errors) == 1
        assert isinstance(mock_server.decode_errors[0], ValueError)
    finally:
        sock.close()

    # Proves the serve thread is still alive: this would raise ScTimeout if
    # the malformed packet above had killed it.
    client.sync(sync_id=99)


def test_handle_replies_fail_for_sync_without_args(mock_server):
    """A /sync with no sync_id is malformed and must not raise.

    Regression test for a bug found during Task 5 review and fixed in
    Task 6: handle()'s /sync branch indexed message.args[0]
    unconditionally. ScClient.sync() always sends a sync_id, so this path
    is unreachable through the client today -- but any other sender that
    omits it would previously hit IndexError inside handle(), and since
    _serve() does not wrap that call in a try/except, the exception would
    propagate out and permanently end the daemon thread, exactly like the
    pre-guard decode() bug above, one layer deeper.
    """
    reply = mock_server.handle(OscMessage("/sync", []))
    assert reply == OscMessage("/fail", ["/sync", "Wrong number of arguments"])


def test_handle_replies_fail_for_notify_without_args(mock_server):
    """/notify with no enable flag must reply /fail, not raise IndexError."""
    reply = mock_server.handle(OscMessage("/notify", []))
    assert reply == OscMessage("/fail", ["/notify", "Wrong number of arguments"])


def test_handle_g_query_tree_without_args_does_not_raise(mock_server):
    """/g_queryTree with zero args must not raise.

    Its only args[] access (the control-values flag at index 1) is guarded
    by a length check, so a bare request falls back to
    with_controls=False rather than raising IndexError.
    """
    reply = mock_server.handle(OscMessage("/g_queryTree", []))
    assert reply.address == "/g_queryTree.reply"
    assert reply.args[0] == 0


def test_bare_sync_over_the_wire_does_not_kill_the_mock(client, mock_server):
    """A /sync with no arguments, sent as a real datagram, must not kill
    the mock's serve thread.

    Unlike the direct handle() test above, this exercises the real
    socket + _serve() loop, which does not wrap its call to handle() in a
    try/except -- so if the guard inside handle() were removed, the
    IndexError it used to raise would propagate out of _serve() and
    permanently end the daemon thread, the same way an undecodable
    datagram did before the Task 5 decode guard.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(OscMessage("/sync", []).encode(), ("127.0.0.1", mock_server.port))
    finally:
        sock.close()

    # Wait until the mock has actually logged the argless /sync before
    # racing a follow-up request against it: .received is appended to
    # before handle() runs, and _serve() is single-threaded, so the
    # handle() call for this message -- crash or not -- is guaranteed to
    # finish before the next recvfrom(). The sync() below can therefore
    # only succeed if the thread survived it.
    mock_server.wait_for_message("/sync", timeout=1.0)

    client.sync(sync_id=17)


# --- IMPORTANT 9: a /status.reply of the wrong shape ------------------------


class _OddShapeScsynth(MockScsynth):
    """Answers /status with a reply of a different arity. The spec says
    las-sc's /status.reply may be trimmed or extended relative to stock
    scsynth, and /status is the FIRST thing this toolkit ever says to it.
    """

    def __init__(self, args, port=0):
        super().__init__(port)
        self._status_args = args

    def handle(self, message):
        if message.address == "/status":
            return OscMessage("/status.reply", list(self._status_args))
        return super().handle(message)


@pytest.mark.parametrize(
    "args",
    [
        pytest.param([1, 0, 0, 1, 0, 0.02, 0.05], id="seven-args-trimmed"),
        pytest.param([1, 0, 0, 1, 0, 0.02, 0.05, 48000.0, 48000.0, 7.0], id="ten-args-extended"),
    ],
)
def test_status_names_the_message_and_echoes_what_arrived(args):
    """A bare tuple unpack fails with "too many values to unpack (expected
    9)": loud, which is right, but it names neither /status.reply nor what
    the server actually sent -- and on a one-shot hardware window the
    observed payload is the single most useful thing a first-contact
    failure could hand back. Losing it means a second trip.

    Mutation-checked: remove the len(message.args) check from
    ScClient.status and this test fails -- the raised error is a bare
    ValueError whose message contains neither "/status.reply" nor the
    observed args.
    """
    with _OddShapeScsynth(args) as server:
        transport = UdpTransport("127.0.0.1", server.port)
        try:
            client = ScClient(transport)
            with pytest.raises(ScError) as excinfo:
                client.status()
            text = str(excinfo.value)
            assert "/status.reply" in text, "the failure never names the message"
            assert f"{len(args)} arguments" in text
            # Every observed value must be recoverable from the message --
            # this is the whole point: what the server sent IS the finding,
            # and a second trip to the hardware is the cost of losing it.
            # Parsed back out rather than substring-matched: `repr(0.02) in
            # text` would fail against a perfectly good message, because
            # 0.02 crosses the wire as a float32 and comes back as
            # 0.019999999552965164. Echoing the wire value rather than the
            # value we hoped for is the honest thing to do; the test has to
            # match that.
            echoed = text.split("Observed args: ", 1)[1]
            parsed = ast.literal_eval(echoed)
            assert parsed == pytest.approx(args, rel=1e-6), (
                f"observed args were not echoed faithfully: {parsed!r} vs {args!r}"
            )
        finally:
            transport.close()


def test_status_still_parses_a_well_formed_nine_arg_reply(client):
    """The guard must not reject a correct reply -- without this, `raise
    unconditionally` would satisfy the test above.
    """
    status = client.status()
    assert status.num_synths == 0
    assert status.sample_rate == pytest.approx(48000.0)
