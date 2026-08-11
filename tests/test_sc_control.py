import time

import pytest

from moogone.osc import OscMessage


def _reverb(root):
    return next(n for n in root.walk() if getattr(n, "defname", None) == "moog_fx_reverb")


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def test_n_set_changes_a_control(client):
    node = _reverb(client.query_tree())
    client.n_set(node.node_id, in_trim=2.5)
    assert _reverb(client.query_tree()).controls["in_trim"] == pytest.approx(2.5)


def test_n_set_accepts_multiple_controls(client):
    node = _reverb(client.query_tree())
    client.n_set(node.node_id, in_trim=0.5, mix=0.9)
    controls = _reverb(client.query_tree()).controls
    assert controls["in_trim"] == pytest.approx(0.5)
    assert controls["mix"] == pytest.approx(0.9)


def test_n_set_rejects_non_numeric_values(client):
    # /n_set only ever takes numeric control values. Mapping a control to
    # a named control bus (e.g. "a0") is a different command, /n_map,
    # which this toolkit doesn't implement -- so a non-numeric value must
    # be rejected client-side, not sent as something scsynth might parse
    # differently than intended.
    with pytest.raises(ValueError, match="could not convert string to float"):
        client.n_set(1001, in_trim="a0")


def test_n_set_on_unknown_node_is_silently_ignored_by_server(client, mock_server):
    # Real scsynth logs and moves on; we assert we don't crash and it's recorded.
    client.n_set(999999, in_trim=1.0)
    mock_server.wait_for_message("/n_set", timeout=1.0)
    # wait_for_message only proves the datagram was recorded in `received` --
    # that append happens in _serve() *before* handle() is even called, so
    # it would still succeed even if the dispatch to _apply_n_set() below
    # raised and silently killed the daemon thread afterwards (the same
    # failure mode the /sync and /notify argless guards exist to prevent).
    # Drive a second, unrelated round trip through the server to prove it
    # is still alive and actually processed the unknown-node /n_set as a
    # no-op rather than crashing on it.
    client.sync(sync_id=4242)


def test_n_set_on_unknown_node_does_not_reply_fail(mock_server):
    # Calls handle() directly (bypassing the wire and the daemon thread) to
    # pin down, synchronously, that an unknown node id is not treated as an
    # error -- matching real scsynth, which logs and moves on rather than
    # replying /fail.
    reply = mock_server.handle(OscMessage("/n_set", [999999, "in_trim", 1.0]))
    assert reply is None


def test_n_set_drops_dangling_trailing_argument_but_records_it(mock_server):
    """An odd trailing name with no paired value can't be safely applied --
    we don't know what real scsynth would do with a malformed pair, and
    inventing a /fail would be guessing in the direction of strictness it
    might not have. So it's dropped rather than applied. But the drop must
    be observable, not silent: this proves the complete pair before it
    still lands, and the dangling name is recorded (mirroring
    decode_errors) rather than vanishing with no trace anywhere.
    """
    node = _reverb(mock_server.node_tree)
    args = [node.node_id, "in_trim", 9.0, "mix"]
    reply = mock_server.handle(OscMessage("/n_set", args))
    assert reply is None
    assert node.controls["in_trim"] == pytest.approx(9.0)
    assert args in mock_server.dropped_n_set_args


def test_n_query_returns_node_info(client):
    node = _reverb(client.query_tree())
    info = client.n_query(node.node_id)
    assert info.node_id == node.node_id
    assert info.is_group is False


def test_dump_osc_sets_server_mode(client, mock_server):
    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)
    assert mock_server.dump_mode == 1


def test_dump_osc_log_captures_subsequent_messages(client, mock_server):
    # Sent before dump mode is enabled, with an address distinct from
    # anything sent later. If dump_log merely mirrored `received` --
    # capturing everything the mock has ever seen instead of only what
    # arrives after /dumpOSC -- this would incorrectly turn up below.
    client.send("/probe_before", 1)
    mock_server.wait_for_message("/probe_before", timeout=1.0)

    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)
    client.send("/n_free", 1234)
    mock_server.wait_for_message("/n_free", timeout=1.0)

    addresses = [m.address for m in mock_server.dump_log]
    assert any(m.address == "/n_free" for m in mock_server.dump_log)
    # Only what arrived after enabling belongs in the log: neither the
    # earlier probe nor the /dumpOSC message that enabled logging itself.
    assert "/probe_before" not in addresses
    assert "/dumpOSC" not in addresses


def test_dump_osc_mode_switch_excludes_the_switch_message_itself(client, mock_server):
    """On the *first* /dumpOSC, dump_mode is still 0 when the recording
    hook in _serve() sees it, so the `if self.dump_mode` gate alone
    already excludes it from the log -- a test that only covers the first
    enable can't tell whether the separate `message.address != "/dumpOSC"`
    check does anything at all. Only a *second* /dumpOSC, sent while
    dumping is already active, exercises it: dump_mode is already nonzero
    by the time this one arrives, so the mode gate alone would let it
    through and only the address check keeps it out.
    """
    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)

    client.send("/probe_one", 1)
    mock_server.wait_for_message("/probe_one", timeout=1.0)

    client.dump_osc(2)  # mode switch while dumping is already active
    _wait_until(lambda: mock_server.dump_mode == 2, timeout=1.0)

    client.send("/probe_two", 2)
    mock_server.wait_for_message("/probe_two", timeout=1.0)

    addresses = [m.address for m in mock_server.dump_log]
    assert "/probe_one" in addresses
    assert "/probe_two" in addresses
    assert "/dumpOSC" not in addresses


def test_dump_osc_rejects_invalid_mode(client):
    # Mode validation belongs client-side: 0/1/2/3 are the only valid
    # values, and an invalid mode must never reach the wire.
    with pytest.raises(ValueError, match="dumpOSC mode must be 0-3"):
        client.dump_osc(4)


def test_handle_replies_fail_for_dump_osc_without_args(mock_server):
    """A bare /dumpOSC with no mode must reply /fail, not raise IndexError
    and silently kill the daemon thread -- same class of bug the /sync and
    /notify argless guards already cover.
    """
    reply = mock_server.handle(OscMessage("/dumpOSC", []))
    assert reply == OscMessage("/fail", ["/dumpOSC", "Wrong number of arguments"])


def test_handle_replies_fail_for_n_set_without_args(mock_server):
    """A bare /n_set with no node id must reply /fail, not raise IndexError."""
    reply = mock_server.handle(OscMessage("/n_set", []))
    assert reply == OscMessage("/fail", ["/n_set", "Wrong number of arguments"])


def test_handle_replies_fail_for_n_query_without_args(mock_server):
    """A bare /n_query with no node id must reply /fail, not raise IndexError."""
    reply = mock_server.handle(OscMessage("/n_query", []))
    assert reply == OscMessage("/fail", ["/n_query", "Wrong number of arguments"])
