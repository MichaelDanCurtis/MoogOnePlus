"""Read the Moog One voice-card bus with zero-argument OSC queries.

The voice bus lives on the device's internal USB network (``vc``, 203.0.113.2:7770)
and is unreachable from outside the instrument, so every query runs on-box. There
is no python, perl, or ``timeout(1)`` there — only busybox and ``nc``.

Why not ``vxping``: it sends a *blob* of random bytes and expects it echoed back.
Addresses holding a real value answer with the value instead, which is how the
address space was first mapped. But a blob arriving at a **setter** is not known
to be inert, and several of the most interesting addresses (``/hw/mute``,
``/seq/dest/port``, ``/testosc/freq``) are plausibly writable. A zero-argument
message carries no value to write and is the conventional OSC query form.

The split here is deliberate: everything that decides *what bytes go on the wire*
is a pure function, so it is testable without an instrument. Only
:func:`render_remote_command` and the CLI touch the device.
"""

from __future__ import annotations

from dataclasses import dataclass

from .osc import OscMessage, decode

VC_HOST = "203.0.113.2"
VC_PORT = 7770

#: Reply used by the firmware for an address that does not exist.
NOT_FOUND = (404, "Not found")

#: Reply used when an address exists but cannot answer right now. Observed from
#: per-card paths (``/vx/<n>/…``) answering a zero-argument query: the card is
#: reachable, but this form of the request gets nothing back.
UNAVAILABLE = (503, "Unavailable")


def build_query(address: str) -> bytes:
    """Encode a zero-argument OSC query for ``address``.

    Zero arguments is the whole point — there is no value in the packet that a
    setter could store.
    """
    if not address.startswith("/"):
        raise ValueError(f"OSC address must start with '/': {address!r}")
    return OscMessage(address, []).encode()


def as_printf_escape(payload: bytes) -> str:
    r"""Render bytes as a ``printf`` escape string, e.g. ``\x2f\x69\x6e``.

    ``base64`` is not present on the device, so this is how a packet gets there.
    """
    return "".join(f"\\x{b:02x}" for b in payload)


def render_remote_command(
    address: str,
    host: str = VC_HOST,
    port: int = VC_PORT,
    wait: int = 1,
    tmp: str = "/tmp/vxq.bin",
) -> str:
    """Build the shell command that sends one query and dumps the reply as hex.

    The netcat on this device is **GNU netcat 0.7.1**, not busybox nc, and on UDP
    it does not reliably exit — ``-w`` is documented as a timeout for "connects
    and final net reads", which a UDP socket never reaches. So the process is
    bounded the same way ``vxping`` has to be: capture the PID from ``$!`` and
    kill it.

    Three details are load-bearing:

    - **No ``-c``.** It closes the connection on EOF from stdin, and ``printf``
      reaches EOF immediately, so netcat tears the socket down before the reply
      arrives. Measured: ``nc -u`` and ``nc -u -w 1`` both return the 28-byte
      reply to ``/info/product``; ``nc -u -c`` and ``nc -u -c -w 1`` return zero
      bytes. This is indistinguishable from "the address does not exist".
    - Output goes to a **file**, not a pipe, so it survives the kill. Piping
      into ``od`` and then killing loses the reply.
    - The PID comes from ``$!``. Job control (``%1``) does not work in a
      non-interactive shell and silently produces empty output, which reads as
      "this address is silent" for every address queried.
    """
    esc = as_printf_escape(build_query(address))
    return (
        f"rm -f {tmp}; "
        f"printf '{esc}' | nc -u -w {wait} {host} {port} > {tmp} 2>/dev/null & "
        f"P=$!; sleep {wait}; kill $P 2>/dev/null; wait $P 2>/dev/null; "
        f"od -An -tx1 < {tmp} 2>/dev/null | tr -d ' \\n'"
    )


def parse_hexdump(text: str) -> bytes:
    """Decode the hex ``render_remote_command`` produces back into bytes.

    Tolerates whitespace and newlines; rejects anything that is not hex, because
    a shell error landing on stdout would otherwise decode as a plausible packet.
    """
    cleaned = "".join(text.split())
    if not cleaned:
        return b""
    if len(cleaned) % 2:
        raise ValueError(f"hexdump has odd length {len(cleaned)}: {cleaned[:64]!r}")
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise ValueError(f"not a hexdump: {cleaned[:64]!r}") from exc


@dataclass(frozen=True)
class VxReply:
    """One answer from the voice bus.

    ``kind`` is the distinction that matters when reading a sweep:

    ``value``
        The address exists and returned data. ``args`` holds it.
    ``ack``
        The address exists and answered with **no arguments**. On this firmware
        this is overwhelmingly the common reply: of 303 addresses swept, 121
        existed but only **7** returned data. A bare acknowledgement proves the
        handler is there; it does not read the value out. Collapsing this into
        ``value`` makes an empty answer look like a measurement.
    ``unavailable``
        503. The address exists but cannot answer this form of request — seen
        from per-card ``/vx/<n>/…`` paths, which do answer a blob query.
    ``not_found``
        404. The address is absent *on this firmware*.
    ``silent``
        Nothing came back. This is **not** proof of absence — the bus drops
        replies under load, and a one-second window is not generous.
    """

    address: str
    kind: str
    args: tuple = ()
    raw: bytes = b""

    @property
    def is_value(self) -> bool:
        """True only when data came back. An ``ack`` is not a value."""
        return self.kind == "value"

    @property
    def exists(self) -> bool:
        """The handler is present, whether or not it gave us anything."""
        return self.kind in ("value", "ack", "unavailable")

    def __str__(self) -> str:
        if self.kind == "silent":
            return f"SILENT       {self.address}"
        if self.kind == "not_found":
            return f"404          {self.address}"
        if self.kind == "unavailable":
            return f"503          {self.address}"
        if self.kind == "ack":
            return f"ACK          {self.address}"
        rendered = " ".join(_render_arg(a) for a in self.args)
        return f"VALUE        {self.address}   {rendered}"


def _render_arg(a: object) -> str:
    if isinstance(a, str):
        return f"s:{a}"
    if isinstance(a, bool):
        return f"i:{int(a)}"
    if isinstance(a, int):
        return f"i:{a}"
    if isinstance(a, float):
        return f"f:{a:g}"
    if isinstance(a, (bytes, bytearray)):
        return f"b:<{len(a)} bytes>"
    return repr(a)


def interpret(address: str, raw: bytes) -> VxReply:
    """Turn raw reply bytes into a :class:`VxReply`.

    Five outcomes, in order: no bytes is ``silent``; ``404 Not found`` is
    ``not_found``; ``503 Unavailable`` is ``unavailable``; a reply carrying no
    arguments is ``ack``; anything else is a ``value``.

    A reply whose address does not match the query raises, because silently
    accepting it would attribute one address's data to another.
    """
    if not raw:
        return VxReply(address, "silent")

    msg = decode(raw)
    if not isinstance(msg, OscMessage):
        raise TypeError(f"expected a message for {address}, got a bundle")
    if msg.address != address:
        raise ValueError(f"reply address mismatch: queried {address!r}, got {msg.address!r}")

    args = tuple(msg.args)
    if _is_status(args, NOT_FOUND):
        return VxReply(address, "not_found", args, raw)
    if _is_status(args, UNAVAILABLE):
        return VxReply(address, "unavailable", args, raw)
    if not args:
        return VxReply(address, "ack", args, raw)
    return VxReply(address, "value", args, raw)


def _is_status(args: tuple, status: tuple) -> bool:
    """Recognise one of the firmware's status replies.

    They arrive as **two strings** — ``s:404 s:"Not found"``, ``s:503
    s:"Unavailable"`` — not int + string, so the comparison must be textual.
    Both forms are accepted: the string form is what the instrument sends, the
    numeric form is what one would assume.

    Requiring *both* fields to match matters — an address legitimately holding
    the number 404 is a value, not an absence.
    """
    if len(args) < 2:
        return False
    code = str(args[0]).strip().strip('"')
    text = str(args[1]).strip().strip('"')
    return code == str(status[0]) and text.lower() == status[1].lower()


def card_address(card: int, path: str) -> str:
    """Scope ``path`` to one voice card: ``/vx/<card>/<path>``.

    Bare addresses reach the controller board (``lasvc``); this form reaches an
    individual voice card (``vx``). Both answer on the same bus.
    """
    if not 0 <= card <= 15:
        raise ValueError(f"voice card must be 0-15, got {card}")
    if not path.startswith("/"):
        raise ValueError(f"path must start with '/': {path!r}")
    return f"/vx/{card}{path}"
