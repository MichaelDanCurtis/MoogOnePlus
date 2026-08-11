"""Tests for the SSH tunnel transport.

These stand up real local TCP listeners (never real ssh or socat -- those
are exercised indirectly through build_ssh_command and
build_remote_bridge_command, which are pure functions tested as such).
Server-side sockets get an explicit timeout so a bug in the code under
test makes a test fail fast instead of hanging a background thread for
the rest of the suite.
"""

import socket
import threading

import pytest

from moogone.transport.tunnel import (
    MAX_PACKET,
    TunnelTransport,
    build_remote_bridge_command,
    build_ssh_command,
)

# Bounds how long a background thread can block on a socket call. Generous
# relative to loopback timing, but keeps a bug in the code under test from
# hanging a daemon thread (and its socket) for the rest of the test run.
SAFETY_TIMEOUT = 5.0


def _tcp_listener() -> tuple[socket.socket, int]:
    """A TCP socket listening on an ephemeral port, for the transport to connect to."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(SAFETY_TIMEOUT)
    return listener, listener.getsockname()[1]


def test_ssh_command_forwards_tcp_to_the_bridge_port():
    cmd = build_ssh_command("192.168.0.204", local_port=9300, remote_port=9301)
    assert cmd[0] == "ssh"
    assert "-L" in cmd
    assert "9300:127.0.0.1:9301" in cmd
    assert "root@192.168.0.204" in cmd


def test_ssh_command_accepts_a_non_root_user():
    cmd = build_ssh_command("host", local_port=1, remote_port=2, user="pi")
    assert "pi@host" in cmd


def test_remote_bridge_listens_tcp_and_forwards_udp():
    cmd = build_remote_bridge_command(remote_port=9300, bridge_port=9301)
    assert "socat" in cmd
    assert "TCP-LISTEN:9301" in cmd
    assert "UDP:127.0.0.1:9300" in cmd


def test_tunnel_transport_talks_to_a_local_tcp_listener():
    # The tunnel's local end is a TCP socket; stand one up and check the
    # basic round trip. (The framing limitation gets its own tests below.)
    listener, port = _tcp_listener()
    received = []

    def serve():
        conn, _ = listener.accept()
        try:
            conn.settimeout(SAFETY_TIMEOUT)
            received.append(conn.recv(4096))
            conn.sendall(b"reply")
        finally:
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    try:
        with TunnelTransport(port) as t:
            t.send(b"hello")
            assert t.recv(timeout=2.0) == b"reply"
        thread.join(timeout=SAFETY_TIMEOUT)
        assert not thread.is_alive()
        assert received == [b"hello"]
    finally:
        listener.close()


def test_recv_returns_none_on_timeout():
    listener, port = _tcp_listener()
    try:
        with TunnelTransport(port) as t:
            assert t.recv(timeout=0.05) is None
    finally:
        listener.close()


def test_connecting_to_a_dead_port_raises_with_guidance():
    # Bind an ephemeral port and immediately release it, rather than assume
    # a fixed low port (e.g. 1) is unbound on every machine this suite runs
    # on. The instant after close(), nothing is listening on this port and
    # no other socket is mid-handshake with it, so the connection attempt
    # is refused deterministically -- this doesn't depend on port 1 being
    # conventionally free, or on this process lacking permission to bind
    # low ports, or on any firewall's treatment of a specific port number.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    dead_port = probe.getsockname()[1]
    probe.close()

    with pytest.raises(ConnectionError) as exc_info:
        TunnelTransport(dead_port)

    message = str(exc_info.value)
    # Three independent substring checks instead of one match= on "socat":
    # a message that merely name-drops "socat" somewhere would pass a
    # weaker check without being the actionable guidance the task called
    # for. Requiring the address *and* both likely causes (ssh forward,
    # socat) makes this test fail if any of that guidance goes missing.
    assert f"127.0.0.1:{dead_port}" in message
    assert "ssh" in message.lower()
    assert "socat" in message.lower()


def test_recv_raises_when_the_peer_closes_the_connection():
    # A TCP recv() returning b"" means the peer performed an orderly close
    # -- here, the ssh -L forward or the remote socat bridge died. That is
    # a different situation from "nothing has arrived yet" (a timeout) and
    # must surface differently, or a caller polling recv() can't tell a
    # dead tunnel from a quiet one.
    listener, port = _tcp_listener()

    def serve():
        conn, _ = listener.accept()
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    try:
        with TunnelTransport(port) as t, pytest.raises(ConnectionError, match="closed"):
            t.recv(timeout=2.0)
        thread.join(timeout=SAFETY_TIMEOUT)
        assert not thread.is_alive()
    finally:
        listener.close()


def test_recv_can_return_a_large_write_split_across_multiple_calls():
    # Demonstrates the framing limitation recorded in tunnel.py's module
    # docstring: TCP is a byte stream, not a sequence of messages, so a
    # single write from the far end is not guaranteed to come back from a
    # single recv() call. recv() here asks for at most MAX_PACKET bytes at
    # a time -- a hard cap on socket.recv() itself -- so sending more than
    # that in one write makes a split *guaranteed*, not just likely: the
    # first call cannot possibly contain the whole payload, regardless of
    # how the kernel or socat chose to chunk it in transit.
    #
    # The opposite case -- two small writes coalescing into one recv() --
    # is the same underlying limitation and is demonstrated informally by
    # this same fact (nothing reassembles messages for you), but isn't
    # asserted here: whether two independent writes land in the receive
    # buffer before the one recv() call depends on kernel/OS scheduling,
    # not a hard API guarantee, which makes it unreliable to assert on
    # without contorting the test (an earlier version of this test tried
    # exactly that and was flaky at roughly 1 run in 40).
    payload = b"x" * (MAX_PACKET + 4_464)
    listener, port = _tcp_listener()

    def serve():
        conn, _ = listener.accept()
        try:
            conn.settimeout(SAFETY_TIMEOUT)
            conn.sendall(payload)
        finally:
            conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    try:
        with TunnelTransport(port) as t:
            first = t.recv(timeout=2.0)
            assert first is not None
            assert len(first) <= MAX_PACKET
            assert len(first) < len(payload)  # could not have been the whole write

            received = first
            while len(received) < len(payload):
                chunk = t.recv(timeout=2.0)
                assert chunk is not None
                received += chunk
            assert received == payload
        thread.join(timeout=SAFETY_TIMEOUT)
        assert not thread.is_alive()
    finally:
        listener.close()
