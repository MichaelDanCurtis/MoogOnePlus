"""SuperCollider server client.

Errors are raised, never swallowed. A silently ignored /fail during recon
would be worse than a crash — it would look like success.
"""

import time
from dataclasses import dataclass

from ..osc import OscBundle, OscMessage, decode
from ..transport.base import Transport
from .tree import GroupNode, parse_query_tree


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


@dataclass
class NodeInfo:
    node_id: int
    parent_id: int
    prev_id: int
    next_id: int
    is_group: bool


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

    def query_tree(
        self, group_id: int = 0, with_controls: bool = True, timeout: float = 2.0
    ) -> GroupNode:
        """Enumerate the live node graph below group_id.

        With with_controls=True the reply includes every control name and
        value, which is what makes this the most useful single recon call.
        """
        message = self.request(
            "/g_queryTree",
            group_id,
            int(with_controls),
            reply="/g_queryTree.reply",
            timeout=timeout,
        )
        return parse_query_tree(message.args)

    def n_set(self, node_id: int, **controls) -> None:
        """Set one or more controls on a live node. Fire and forget.

        scsynth does not acknowledge /n_set. To confirm a change took, query
        the node afterwards rather than assuming.

        Values must be numeric: each is coerced with float(), which raises
        ValueError for anything else. /n_set only ever takes numbers --
        mapping a control to a named control bus (e.g. "a0") is a
        different command, /n_map, which this toolkit does not implement.
        """
        args: list = [node_id]
        for name, value in controls.items():
            args.extend([name, float(value)])
        self.send("/n_set", *args)

    def n_query(self, node_id: int, timeout: float = 2.0) -> "NodeInfo":
        message = self.request("/n_query", node_id, reply="/n_info", timeout=timeout)
        node, parent, prev, nxt, is_group = message.args[:5]
        return NodeInfo(node, parent, prev, nxt, bool(is_group))

    def dump_osc(self, mode: int) -> None:
        """0 = off, 1 = parsed, 2 = hex, 3 = both.

        Mode 1 makes the server log every message it receives, which is how
        recon captures Moog's own OSC namespace by observation.
        """
        if mode not in (0, 1, 2, 3):
            raise ValueError(f"dumpOSC mode must be 0-3, got {mode}")
        self.send("/dumpOSC", mode)
