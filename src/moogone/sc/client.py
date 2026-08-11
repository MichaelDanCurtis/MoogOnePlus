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
    """The server refused, or could not honor, a request.

    Two shapes, both meaning "do not trust that this worked":

    - the server replied /fail (the common case), or
    - the server replied successfully but the reply contradicts the
      request -- e.g. a /g_queryTree.reply whose control-values flag
      says 0 when we asked for 1. That is not a /fail, but it is still
      the server telling us it did something other than what was asked,
      and returning the reply's contents as if they answered the
      question would report "this effect exposes no controls" for an
      effect whose controls were simply never sent.
    """


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

    def status(self, timeout: float = 2.0) -> ServerStatus:
        message = self.request("/status", reply="/status.reply", timeout=timeout)
        # This is the FIRST thing we ever say to the real las-sc, and the
        # spec explicitly allows for a server whose /status.reply is
        # trimmed or extended relative to stock scsynth. A bare tuple
        # unpack fails with "too many values to unpack (expected 9)" --
        # loud, which is right, but it names neither the message nor what
        # actually arrived, and the observed args are the single most
        # useful thing a first-contact failure could tell us. Discarding
        # them here means a second trip to the hardware to learn what the
        # server actually sent.
        if len(message.args) != 9:
            raise ScError(
                f"/status.reply carried {len(message.args)} arguments, expected 9 "
                f"(_, ugens, synths, groups, defs, avg_cpu, peak_cpu, sample_rate, "
                f"actual_sample_rate). This server's /status.reply does not match "
                f"stock scsynth. Observed args: {message.args!r}"
            )
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
                raise ScTimeout(f"no /synced for id {sync_id} within {timeout:.1f}s")
            try:
                message = self._await_reply("/synced", remaining)
            except ScTimeout:
                # _await_reply's own deadline always expires a hair before
                # the `remaining <= 0` check above can fire, so its message
                # -- built from the SHRUNK remaining it was handed, not the
                # caller's budget -- is the one that used to reach the
                # operator: "no /synced within 1.9999996250262484s" for a
                # 2.0s request. Restate it in the caller's own terms, and
                # name the sync id, which _await_reply has no way to know.
                # /sync gates both /d_recv and `moogone set`, so this is a
                # message that gets read in front of hardware.
                raise ScTimeout(
                    f"no /synced for id {sync_id} within {timeout:.1f}s"
                ) from None
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
        # args[0] is the server's echo of the control-values flag, and it
        # governs how the REST of the reply is framed: with it set, each
        # synth entry carries num_controls followed by that many
        # (name, value) pairs; without it, the entry stops at the defname.
        # parse_query_tree reads the flag to know which layout to expect
        # and then discards it -- so a server that answers 0 to a
        # with_controls=1 request parses cleanly into a tree where every
        # synth has controls={}, with no warning anywhere.
        #
        # That is indistinguishable, on the page, from an effect that
        # genuinely exposes no controls -- and capturing every control
        # name is this call's entire purpose (harness/README.md calls the
        # capture "the source of truth" for the FX SynthDef's control
        # names). Compare what we asked for against what came back, and
        # refuse rather than hand back a plausible empty answer.
        if not message.args:
            raise ScError(
                "/g_queryTree.reply carried no arguments at all; expected at least "
                "the control-values flag followed by the flattened node walk"
            )
        reply_with_controls = bool(message.args[0])
        if reply_with_controls != bool(with_controls):
            raise ScError(
                f"/g_queryTree.reply's control-values flag is "
                f"{int(reply_with_controls)}, but the request asked for "
                f"{int(bool(with_controls))}. The reply is framed WITHOUT control "
                f"names/values, so parsing it would report every synth as having no "
                f"controls -- which reads identically to an effect that genuinely "
                f"exposes none. Re-query, or call parse_query_tree directly if a "
                f"structure-only walk is what you actually want."
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

    def d_recv(self, synthdef: bytes, timeout: float = 5.0) -> None:
        """Load a compiled SynthDef into the running server.

        This is runtime data, not firmware — nothing signed is touched and
        nothing survives a reboot unless deliberately arranged.
        """
        if not synthdef:
            raise ValueError("cannot send an empty synthdef")
        self.request("/d_recv", synthdef, reply="/done", timeout=timeout)

    def dump_osc(self, mode: int, timeout: float = 2.0) -> None:
        """0 = off, 1 = parsed, 2 = hex, 3 = both.

        Mode 1 makes the server log every message it receives, which is how
        recon captures Moog's own OSC namespace by observation.

        /dumpOSC itself is fire-and-forget -- the server never acknowledges
        it -- so this follows the send with a /sync. That is not belt and
        braces: without it, a server that does not implement /dumpOSC at
        all replies /fail, the /fail sits unread in the socket buffer, and
        this method returns normally. The operator then spends their one
        30-second front-panel knob sweep -- the highest-value artifact in
        the entire project, and the thing that turns guesswork about Moog's
        OSC namespace into observed fact -- against an engine that is not
        logging anything. There is no second attempt in September.

        /sync closes that: _await_reply raises ScError on any /fail it sees
        while waiting for /synced, so a rejected /dumpOSC surfaces as
        "server rejected /dumpOSC: Command not found" instead of silence.
        It also makes `moogone dump`'s --timeout mean something.
        """
        if mode not in (0, 1, 2, 3):
            raise ValueError(f"dumpOSC mode must be 0-3, got {mode}")
        self.send("/dumpOSC", mode)
        self.sync(timeout=timeout)
