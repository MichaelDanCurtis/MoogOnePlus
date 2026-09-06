"""Direct UDP transport.

This is the primary path: used when running on the Moog One itself, talking
to las-sc on localhost. No network hops, no tunnel.

**Sends are paced, and that is not a nicety.** The instrument's LAN and its
internal link to the voice controller are two CDC-Ether functions of a single USB
gadget, and a microburst on either wedges it hard enough that the host cannot
recover it -- `usb 2-1: can't set config #1, error -71` -- so only a power cycle
clears it. Measured: 719 kB/s **paced** is untroubled, while 2000 datagrams sent
back to back (18 ms, ~145 MB/s instantaneous) kills it every time. See
`docs/MOOG-ONE-INTERNALS.md` section 8c.

The floor below is therefore a safety interlock on someone else's hardware rather
than a tuning parameter, and it is deliberately generous: it still permits several
times the rate any control or audio traffic here needs.
"""

import select
import socket
import time

from .base import Transport

MAX_PACKET = 65536

#: Smallest gap between datagrams, in seconds. 1 ms caps this transport at 1000
#: datagrams/s -- roughly 1.3 MB/s at OSC sizes, which is about three times what
#: streaming 48 kHz stereo needs and two orders of magnitude below the burst that
#: wedges the gadget.
MIN_SEND_INTERVAL = 0.001


class UdpTransport(Transport):
    def __init__(
        self, host: str, port: int, bind_port: int = 0, min_send_interval: float = MIN_SEND_INTERVAL
    ):
        self.host = host
        self.port = port
        self._bind_port = bind_port
        #: Set to 0.0 only when talking to something that is not the instrument.
        self.min_send_interval = max(0.0, min_send_interval)
        self._last_send = 0.0
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

        Sends are also spaced by at least `min_send_interval`. See the module
        docstring: back-to-back datagrams wedge the instrument's USB gadget beyond
        the host's ability to reset it.
        """
        self._pace()
        try:
            self._sock.sendto(data, (self.host, self.port))
        except OSError:
            if self._closed:
                raise
            self._reopen()
            self._sock.sendto(data, (self.host, self.port))

    def _pace(self) -> None:
        """Hold off until `min_send_interval` has passed since the last datagram.

        A monotonic clock, because a wall clock stepping backwards would hand out an
        unbounded sleep, and the point of this is to be unable to hurt the
        instrument -- including when the machine's clock is adjusted mid-session.
        """
        if self.min_send_interval <= 0.0:
            return
        now = time.monotonic()
        # Clamped to the interval itself: waiting longer than one gap is never
        # correct, and without the clamp a `_last_send` somehow ahead of now -- a
        # clock adjustment, or a future bug -- becomes an unbounded sleep that
        # looks exactly like the hang this code exists to prevent.
        wait = min(self._last_send + self.min_send_interval - now,
                   self.min_send_interval)
        if wait > 0:
            time.sleep(wait)
            now = time.monotonic()
        self._last_send = now

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
