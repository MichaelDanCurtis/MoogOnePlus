"""SuperCollider server client.

Errors are raised, never swallowed. A silently ignored /fail during recon
would be worse than a crash — it would look like success.
"""

import time
from dataclasses import dataclass

from ..osc import OscBundle, OscMessage, decode
from ..transport.base import Transport


class ScError(RuntimeError):
    """The server replied /fail."""


class ScTimeout(TimeoutError):
    """The expected reply did not arrive in time."""


@dataclass
class ServerStatus:
    num_ugens: int
    num_synths: int
    num_groups: int
    num_synthdefs: int
    avg_cpu: float
    peak_cpu: float
    sample_rate: float
    actual_sample_rate: float


class ScClient:
    def __init__(self, transport: Transport):
        self.transport = transport

    def send(self, address: str, *args) -> None:
        """Fire and forget."""
        self.transport.send(OscMessage(address, list(args)).encode())

    def request(self, address: str, *args, reply: str, timeout: float = 2.0) -> OscMessage:
        """Send a command and wait for a specific reply address.

        Raises ScError on /fail, ScTimeout if the reply never arrives.
        Unrelated messages arriving in the meantime are discarded.
        """
        self.send(address, *args)
        return self._await_reply(reply, timeout)

    def _await_reply(self, reply: str, timeout: float) -> OscMessage:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScTimeout(f"no {reply} within {timeout}s")
            data = self.transport.recv(timeout=remaining)
            if data is None:
                continue
            message = decode(data)
            if isinstance(message, OscBundle):
                continue
            if message.address == "/fail":
                raise ScError(f"server rejected {message.args[0]}: {message.args[1]}")
            if message.address == reply:
                return message

    def status(self) -> ServerStatus:
        message = self.request("/status", reply="/status.reply")
        _, ugens, synths, groups, defs, avg, peak, sr, actual_sr = message.args
        return ServerStatus(ugens, synths, groups, defs, avg, peak, sr, actual_sr)

    def sync(self, sync_id: int = 1, timeout: float = 2.0) -> None:
        """Block until the server has processed all prior async commands.

        The server echoes sync_id back; a reply carrying a different id
        belongs to someone else's sync and is ignored.
        """
        self.send("/sync", sync_id)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScTimeout(f"no /synced for id {sync_id} within {timeout}s")
            message = self._await_reply("/synced", remaining)
            if message.args and message.args[0] == sync_id:
                return

    def notify(self, enable: bool = True, timeout: float = 2.0) -> None:
        """Subscribe to (or unsubscribe from) node lifecycle notifications."""
        self.request("/notify", int(enable), reply="/done", timeout=timeout)
