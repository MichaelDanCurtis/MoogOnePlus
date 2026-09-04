"""A live feed of the instrument's internal bus, over SSH.

`tcpdump -w -` on the device, piped back through SSH and parsed as it arrives, so
one capture serves every protocol on that bus at once: notes on 7772, the OLED
displays on 9876, the panel LEDs and inputs on 9100 and 9500.

Read-only. It starts a capture and reads it; nothing is transmitted to the synth.
"""

from __future__ import annotations

import subprocess
import threading

from .pcap import iter_records, udp_of

SSH_OPTIONS = [
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=10",
]


def tcpdump_command(ports: tuple[int, ...], interface: str = "usbint") -> str:
    """The remote command. `-U` matters more than it looks.

    Without it tcpdump flushes at buffer boundaries, which for a note stream means
    silence for several seconds and then everything at once. The PATH export is
    needed because a non-interactive SSH session gets only /usr/bin:/bin, and
    tcpdump lives in /usr/sbin.
    """
    if not ports:
        raise ValueError("at least one port is required")
    filt = " or ".join(f"port {int(p)}" for p in ports)
    return (
        "export PATH=/usr/sbin:/sbin:/usr/bin:/bin; "
        f"exec tcpdump -i {interface} -n -s 0 -U -w - 'udp and ({filt})' 2>/dev/null"
    )


class BusStream:
    """Runs the capture and hands each UDP datagram to `on_datagram`.

    `run()` blocks. `stop()` is safe from another thread and safe before `run()`.
    """

    def __init__(self, host: str, ports, on_datagram, on_error=None, interface="usbint"):
        self.host = host
        self.ports = tuple(int(p) for p in ports)
        self.interface = interface
        self._on_datagram = on_datagram
        self._on_error = on_error
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()

    @property
    def command(self) -> str:
        return tcpdump_command(self.ports, self.interface)

    def run(self) -> None:
        self._proc = subprocess.Popen(
            ["ssh", *SSH_OPTIONS, f"root@{self.host}", self.command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ts, frame in iter_records(self._proc.stdout.read1):
                if self._stop.is_set():
                    break
                parsed = udp_of(frame)
                if parsed is not None:
                    _src, sport, _dst, dport, payload = parsed
                    self._on_datagram(sport, dport, payload)
        except (OSError, ValueError) as exc:  # pragma: no cover - transport failures
            # ValueError covers PcapError, for a stream that never became a pcap --
            # an ssh that failed and wrote its message where the header should be.
            if self._on_error:
                self._on_error(exc)
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
