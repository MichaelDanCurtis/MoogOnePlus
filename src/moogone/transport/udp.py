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
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", bind_port))
        self._closed = False

    @property
    def local_port(self) -> int:
        return self._sock.getsockname()[1]

    def send(self, data: bytes) -> None:
        self._sock.sendto(data, (self.host, self.port))

    def recv(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return None
        data, _ = self._sock.recvfrom(MAX_PACKET)
        return data

    def close(self) -> None:
        if not self._closed:
            self._sock.close()
            self._closed = True
