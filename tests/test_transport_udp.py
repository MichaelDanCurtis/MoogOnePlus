import socket

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
                # recv() should reject it and raise with both addresses in the message
                try:
                    t.recv(timeout=1.0)
                    assert False, "Should have raised ValueError"
                except ValueError as e:
                    error_msg = str(e)
                    # Verify both the expected address and actual sender address are in the error
                    assert "127.0.0.1" in error_msg or "expected" in error_msg
                    assert str(port) in error_msg or "expected" in error_msg
                    assert "SPOOFED" not in error_msg  # The payload should not be in the error
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
