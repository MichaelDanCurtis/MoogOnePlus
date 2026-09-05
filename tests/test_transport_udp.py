import socket

import pytest

from moogone.transport.udp import UdpTransport


def _echo_socket() -> tuple[socket.socket, int]:
    """A UDP socket bound to an ephemeral port, for the transport to talk to."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def test_send_reaches_the_target():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            t.send(b"hello")
            peer.settimeout(1.0)
            data, _ = peer.recvfrom(4096)
            assert data == b"hello"
    finally:
        peer.close()


def test_recv_returns_reply():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            t.send(b"ping")
            peer.settimeout(1.0)
            _, addr = peer.recvfrom(4096)
            peer.sendto(b"pong", addr)
            assert t.recv(timeout=1.0) == b"pong"
    finally:
        peer.close()


def test_recv_returns_none_on_timeout():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            assert t.recv(timeout=0.05) is None
    finally:
        peer.close()


def test_close_is_idempotent():
    peer, port = _echo_socket()
    try:
        t = UdpTransport("127.0.0.1", port)
        t.close()
        t.close()
    finally:
        peer.close()


def test_recv_rejects_datagram_from_wrong_sender():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            # Create a spoofed datagram from a different socket
            spoofed_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                spoofed_sender.sendto(b"SPOOFED-NOT-THE-SYNTH", ("127.0.0.1", t.local_port))
                # Capture the kernel-assigned port of the spoofed sender
                spoofed_port = spoofed_sender.getsockname()[1]
                # recv() should reject it and raise with both addresses in the message
                try:
                    t.recv(timeout=1.0)
                    assert False, "Should have raised ValueError"
                except ValueError as e:
                    error_msg = str(e)
                    # The two ports must differ, or the assertions below can't discriminate.
                    assert spoofed_port != port, (
                        "test setup degenerate: spoofed and peer ports collided"
                    )
                    assert f"got 127.0.0.1:{spoofed_port}" in error_msg
                    assert f"expected 127.0.0.1:{port}" in error_msg
                    # The rejected datagram's PAYLOAD must not be echoed into
                    # the exception. This is a separate regression class from
                    # the address assertions above: a message built as
                    # f"...unexpected sender ... {data!r}" would satisfy both
                    # of those and still leak attacker-controlled bytes into
                    # an error string that gets pasted into notes, logs, and
                    # bug reports. The address is the diagnostic; the payload
                    # is not.
                    assert "SPOOFED" not in error_msg
            finally:
                spoofed_sender.close()
    finally:
        peer.close()


def test_recv_accepts_reply_from_configured_peer():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            # Send a message so the peer gets our address
            t.send(b"ping")
            peer.settimeout(1.0)
            _, addr = peer.recvfrom(4096)
            # Send reply from the peer to the transport's address
            peer.sendto(b"pong", addr)
            # This should be accepted (not rejected as from wrong sender)
            result = t.recv(timeout=1.0)
            assert result == b"pong"
    finally:
        peer.close()


class TestRecoveryFromASouredSocket:
    """A UDP socket that meets an unreachable host caches EHOSTUNREACH and keeps
    returning it after the host is back. On an instrument that gets power-cycled,
    that turns one reboot into a bridge that is dead until someone restarts it."""

    def test_a_failed_send_is_retried_on_a_new_socket(self):
        import socket as _s

        t = UdpTransport("127.0.0.1", 9999)
        first = t._sock
        calls = []

        class Sour:
            def __init__(self, real):
                self.real = real
                self.used = 0

            def sendto(self, data, addr):
                self.used += 1
                calls.append(addr)
                raise OSError(65, "No route to host")

            def close(self):
                pass

            def getsockname(self):
                return self.real.getsockname()

        t._sock = Sour(first)
        # The replacement socket is real, so the retry actually goes out.
        t.send(b"hello")
        assert t._sock is not first
        assert isinstance(t._sock, _s.socket)
        t.close()

    def test_a_second_failure_is_raised_not_swallowed(self, monkeypatch):
        t = UdpTransport("127.0.0.1", 9999)

        class AlwaysSour:
            def sendto(self, data, addr):
                raise OSError(65, "No route to host")

            def close(self):
                pass

        t._sock = AlwaysSour()
        monkeypatch.setattr(t, "_reopen", lambda: setattr(t, "_sock", AlwaysSour()))
        with pytest.raises(OSError):
            t.send(b"hello")

    def test_the_bind_port_survives_a_reopen(self):
        t = UdpTransport("127.0.0.1", 9999, bind_port=0)
        t._reopen()
        assert t.local_port > 0
        t.close()

    def test_a_closed_transport_does_not_resurrect_itself(self):
        t = UdpTransport("127.0.0.1", 9999)
        t.close()
        with pytest.raises(OSError):
            t.send(b"hello")
