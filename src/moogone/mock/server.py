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
            return OscMessage("/synced", [message.args[0] + self.sync_id_offset])
        if message.address == "/notify":
            self.notified = bool(message.args[0])
            return OscMessage("/done", ["/notify", 0])
        if message.address in _NO_REPLY:
            return None
        return OscMessage("/fail", [message.address, "Command not found"])


# Commands the real server accepts without replying.
_NO_REPLY = {"/n_free", "/n_set", "/dumpOSC"}
