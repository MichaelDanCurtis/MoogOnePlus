"""SSH-tunnelled transport, for development from off-box.

ssh -L forwards TCP. scsynth listens on UDP. A plain forward therefore
carries nothing, and this is the single easiest way to waste an afternoon
on this project. The working shape needs socat at both ends:

    Mac                          Moog One
    ---                          --------
    TunnelTransport  -- TCP -->  sshd -- TCP --> socat -- UDP --> las-sc
                                 (bridge_port)              (9300)

Set up, in two terminals:

    ssh root@<ip> 'socat TCP-LISTEN:9301,reuseaddr,fork UDP:127.0.0.1:9300'
    ssh -N -L 9300:127.0.0.1:9301 root@<ip>

If socat is absent from the device, do not fight this. Run on-box instead.

Message framing is not guaranteed. TCP is a byte stream, not a sequence of
messages: two OSC packets sent close together can arrive coalesced into a
single recv(), and one large packet can arrive split across two or more
recv() calls. socat's TCP<->UDP bridging can independently coalesce or
split traffic again on top of that. UdpTransport, the primary transport
used on-box, does not have this problem -- each of its recv() calls
returns exactly one UDP datagram, because that boundary is a property of
UDP itself, not something either transport implements.

This module deliberately does not add length-prefix framing to work
around it. We don't know whether las-sc's OSC-over-TCP framing (if it has
one at all -- its UDP listener certainly doesn't) matches whatever we'd
guess at here, and there is no way to verify a guess against real hardware
until then. This path is dev convenience, not the shipped transport, so an
occasional mangled reply is an annoyance, not a correctness bug. If it
bites you, the fix is to develop against UdpTransport on-box, not to chase
framing here. See
tests/test_transport_tunnel.py::test_recv_can_return_a_large_write_split_across_multiple_calls
for a runnable demonstration: it is the deterministic half of this
limitation (recv() has a hard 65536-byte cap per call, so a bigger write
cannot come back whole), unlike the coalescing case, which is real but
timing-dependent and not asserted on here for that reason.
"""

import select
import socket

from .base import Transport

MAX_PACKET = 65536


def build_ssh_command(
    host: str, local_port: int, remote_port: int, user: str = "root"
) -> list[str]:
    """The local SSH forward. remote_port is the bridge port, not scsynth's."""
    return ["ssh", "-N", "-L", f"{local_port}:127.0.0.1:{remote_port}", f"{user}@{host}"]


def build_remote_bridge_command(remote_port: int, bridge_port: int) -> str:
    """The socat bridge to run on the device. remote_port is scsynth's UDP port."""
    return f"socat TCP-LISTEN:{bridge_port},reuseaddr,fork UDP:127.0.0.1:{remote_port}"


class TunnelTransport(Transport):
    """Talks to the local end of an `ssh -L` forward over a connected TCP socket.

    See the module docstring for the required two-terminal setup and for
    the message-framing limitation inherent to running OSC over TCP.
    """

    def __init__(self, local_port: int, host: str = "127.0.0.1"):
        self.host = host
        self.local_port = local_port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._closed = False
        try:
            self._sock.connect((host, local_port))
        except OSError as exc:
            self._sock.close()
            self._closed = True
            raise ConnectionError(
                f"could not reach {host}:{local_port}. Is the ssh -L forward up, "
                f"and is socat running on the device? See this module's docstring."
            ) from exc

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return None
        # No sender-address check here, unlike UdpTransport.recv(). This
        # socket is connect()-ed, so the kernel only ever hands back bytes
        # that came from the peer named in that connect() call -- that's
        # what makes TCP "connected". A UDP socket has no such guarantee:
        # it's bound to a local port but not connected to a peer, so any
        # host can send it a datagram, which is exactly the exposure
        # UdpTransport.recv() checks for. There is nothing analogous to
        # spoof here, so replicating that check would just be dead code.
        data = self._sock.recv(MAX_PACKET)
        if not data:
            # recv() returning b"" on a TCP socket means the peer closed
            # the connection -- the ssh -L forward or the remote socat
            # bridge went away. That must not collapse into the same
            # `None` a timeout produces: "the tunnel died" and "nothing
            # has arrived yet" call for different responses from a
            # caller, so this is raised instead of returned.
            raise ConnectionError(
                f"{self.host}:{self.local_port} closed the connection. The ssh -L "
                f"forward or the remote socat bridge likely died. See this "
                f"module's docstring."
            )
        return data

    def close(self) -> None:
        if not self._closed:
            self._sock.close()
            self._closed = True
