"""Direct UDP transport.

This is the primary path: used when running on the Moog One itself, talking
to las-sc on localhost. No network hops, no tunnel.
"""

import select
import socket

from .base import Transport

MAX_PACKET = 65536


class UdpTransport(Transport):
    def __init__(self, host: str, port: int, bind_port: int = 0):
        self.host = host
        self.port = port
        self._bind_port = bind_port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", bind_port))
        self._closed = False
        # Resolve host to IP once at init time for comparison in recv().
        # This avoids comparing hostnames against IP literals from recvfrom().
        try:
            self._resolved_host = socket.gethostbyname(host)
        except socket.gaierror as e:
            self._sock.close()
            self._closed = True
            raise ValueError(f"Cannot resolve host {host}: {e}") from e

    @property
    def local_port(self) -> int:
        return self._sock.getsockname()[1]

    def send(self, data: bytes) -> None:
        """Send, reopening the socket once if the OS has soured it.

        A UDP socket that meets an unreachable host keeps returning EHOSTUNREACH long
        after the host comes back -- the error is cached against the socket, not
        re-tested. On a device that gets power-cycled as often as an instrument, that
        turns one reboot into a bridge that is dead until someone restarts it, with
        every request answering "No route to host" while a freshly made client works
        perfectly.

        So a failed send gets one new socket and one retry. A second failure is real
        and is raised.
        """
        try:
            self._sock.sendto(data, (self.host, self.port))
        except OSError:
            if self._closed:
                raise
            self._reopen()
            self._sock.sendto(data, (self.host, self.port))

    def _reopen(self) -> None:
        """Replace the socket, keeping the bind port so replies still have somewhere
        to land."""
        try:
            self._sock.close()
        except OSError:
            pass
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", self._bind_port))
        self._sock = sock

    def recv(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return None
        data, addr = self._sock.recvfrom(MAX_PACKET)
        # Validate that the datagram came from the configured peer.
        # addr is (ip, port) tuple from recvfrom().
        sender_ip, sender_port = addr
        if sender_ip != self._resolved_host or sender_port != self.port:
            raise ValueError(
                f"Datagram from unexpected sender: got {sender_ip}:{sender_port}, "
                f"expected {self._resolved_host}:{self.port}"
            )
        return data

    def close(self) -> None:
        if not self._closed:
            self._sock.close()
            self._closed = True
