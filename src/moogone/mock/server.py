"""A mock scsynth, answering enough of the SuperCollider server protocol
to develop against without hardware.

This is the linchpin of the pre-hardware plan: it makes every layer above
it testable, and it encodes our assumptions about las-sc explicitly. When
September's real server behaves differently, it shows up as a failing test
rather than a mystery.
"""

import socket
import threading
import time

from ..osc import Float64, OscMessage, decode
from ..sc.tree import SynthNode
from .tree import default_tree, serialise


class MockScsynth:
    def __init__(self, port: int = 0):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", port))
        self._sock.settimeout(0.1)
        self.port = self._sock.getsockname()[1]
        self.received: list[OscMessage] = []
        self.decode_errors: list[ValueError] = []
        self.silent = False
        self.notified = False
        self.sync_id_offset = 0
        self.node_tree = default_tree()
        self.dump_mode = 0
        self.dump_log: list[OscMessage] = []
        self.dropped_n_set_args: list = []
        self.loaded_synthdefs: list[bytes] = []
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sock.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def wait_for_message(self, address: str, timeout: float) -> OscMessage:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for message in self.received:
                    if message.address == address:
                        return message
            time.sleep(0.01)
        raise AssertionError(f"mock server never received {address}")

    def _serve(self) -> None:
        while self._running:
            try:
                data, addr = self._sock.recvfrom(65536)
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                message = decode(data)
            except ValueError as exc:
                # A malformed datagram must not kill this daemon thread — that
                # would silently stop the mock from answering anything, and
                # every later test failure would present as an unexplained
                # ScTimeout with no clue the mock itself had died. Record the
                # failure where a test can see it and keep serving.
                with self._lock:
                    self.decode_errors.append(exc)
                continue
            with self._lock:
                self.received.append(message)
                if self.dump_mode and message.address != "/dumpOSC":
                    self.dump_log.append(message)
            if self.silent:
                continue
            reply = self.handle(message)
            if reply is not None:
                self._sock.sendto(reply.encode(), addr)

    def handle(self, message: OscMessage) -> OscMessage | None:
        """Dispatch one message. Subclasses and later tasks extend this."""
        if message.address == "/status":
            return OscMessage(
                "/status.reply",
                [1, 0, 0, 1, 0, 0.02, 0.05, Float64(48000.0), Float64(48000.03)],
            )
        if message.address == "/sync":
            # A bare /sync with no id is malformed. message.args[0] would
            # raise IndexError inside this daemon thread and silently kill
            # it -- the same failure mode the decode() guard in _serve()
            # exists to prevent, one layer deeper. Reply /fail instead.
            if not message.args:
                return OscMessage("/fail", [message.address, "Wrong number of arguments"])
            return OscMessage("/synced", [message.args[0] + self.sync_id_offset])
        if message.address == "/notify":
            if not message.args:
                return OscMessage("/fail", [message.address, "Wrong number of arguments"])
            self.notified = bool(message.args[0])
            return OscMessage("/done", ["/notify", 0])
        if message.address == "/g_queryTree":
            # Only args[1] (the control-values flag) is read, and it is
            # already guarded by the length check below -- a bare
            # /g_queryTree with zero args is safe: with_controls just
            # defaults to False, no IndexError is possible here.
            with_controls = bool(message.args[1]) if len(message.args) > 1 else False
            return OscMessage("/g_queryTree.reply", serialise(self.node_tree, with_controls))
        if message.address == "/dumpOSC":
            # A bare /dumpOSC with no mode would raise IndexError below and
            # kill the daemon thread -- the same failure mode /sync and
            # /notify already guard against. Reply /fail instead.
            if not message.args:
                return OscMessage("/fail", [message.address, "Wrong number of arguments"])
            self.dump_mode = message.args[0]
            return None
        if message.address == "/n_set":
            # Same argless guard as above. Note this is about a malformed
            # *message*, not an unknown *node* -- an /n_set naming a node
            # that doesn't exist is a real scenario real scsynth handles by
            # logging and moving on, and _apply_n_set already does that
            # silently (see its docstring). This guard only stops a request
            # with no node id at all from crashing the thread.
            if not message.args:
                return OscMessage("/fail", [message.address, "Wrong number of arguments"])
            self._apply_n_set(message.args)
            return None
        if message.address == "/n_query":
            if not message.args:
                return OscMessage("/fail", [message.address, "Wrong number of arguments"])
            node = self._find_node(message.args[0])
            if node is None:
                return OscMessage("/fail", ["/n_query", "Node not found"])
            is_group = not isinstance(node, SynthNode)
            return OscMessage("/n_info", [node.node_id, 1, -1, -1, int(is_group)])
        if message.address == "/d_recv":
            # Same argless guard as /sync, /notify, /dumpOSC, /n_set, and
            # /n_query above: message.args[0] would raise IndexError and
            # silently kill the daemon thread otherwise.
            if not message.args:
                return OscMessage("/fail", [message.address, "Wrong number of arguments"])
            payload = message.args[0]
            if not payload.startswith(b"SCgf"):
                return OscMessage("/fail", ["/d_recv", "not a synthdef file"])
            self.loaded_synthdefs.append(payload)
            return OscMessage("/done", ["/d_recv"])
        if message.address in _NO_REPLY:
            return None
        return OscMessage("/fail", [message.address, "Command not found"])

    def _find_node(self, node_id: int):
        for node in self.node_tree.walk():
            if node.node_id == node_id:
                return node
        return None

    def _apply_n_set(self, args: list) -> None:
        """Apply /n_set args to node_tree so the change is observable by
        re-querying. Unknown node ids and group ids are silently ignored,
        matching real scsynth: it logs and moves on rather than failing.

        A well-formed /n_set is node_id followed by complete (name, value)
        pairs -- an odd-length args list. An even length means one
        dangling name has no paired value. We don't know what real
        scsynth does with that fragment, and inventing a /fail would be
        guessing in the direction of strictness it might not have, so it
        is dropped rather than applied or rejected. The drop itself is
        not silent, though: it's recorded here, mirroring decode_errors
        above, so a test -- or a human at the real hardware in September
        -- can see it happened instead of the value simply vanishing.
        """
        if len(args) % 2 == 0:
            self.dropped_n_set_args.append(args)
        node = self._find_node(args[0])
        if not isinstance(node, SynthNode):
            return
        for i in range(1, len(args) - 1, 2):
            node.controls[args[i]] = args[i + 1]


# Commands the real server accepts without replying. /n_set and /dumpOSC are
# also fire-and-forget, but each is dispatched by its own branch above (to
# apply its side effect) rather than falling through to this generic set.
#
# All of these are genuinely unacknowledged in scsynth -- this set models
# the real server, it is not a convenience list. It matters that it is
# accurate: anything NOT listed here gets a /fail, and since dump_osc()
# now follows /dumpOSC with a /sync, a /fail left unread in the socket by
# an earlier command surfaces at the next sync as an ScError naming that
# earlier address. That is correct behaviour (an unread /fail is exactly
# what CRITICAL 2 was about) but it means tests need real fire-and-forget
# addresses to probe with, not invented ones.
_NO_REPLY = {"/n_free", "/n_run", "/n_map"}
