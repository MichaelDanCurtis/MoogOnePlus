"""The Moog One's performance protocol, as observed on the wire.

Port 7772, voice controller (`203.0.113.2`) to the i.MX6 (`203.0.113.1`). Silent
until a note sounds, which is what made it findable: an idle capture and a played
capture differ by exactly this traffic and nothing else.

The messages are OSC-shaped but carry no address — literally `"/"`, padded — so the
type tag and a leading integer opcode carry all the meaning. That is why a generic
OSC dump shows them as a wall of identical `/` entries and why they were missed by
every address-space sweep this project ran: there is no address to sweep for.

Decoded by playing known notes and reading them back:

    /  ,iifi   4  <note>  <velocity>  0     a note began or ended
    /  ,ii     8  <value>                   unidentified; see OP_UNKNOWN

**Note-off is signalled by negative zero velocity.** Not by a separate opcode, and
not by a zero-valued float — by the sign bit on a zero. `-0.0 == 0.0` is true in
every language worth using, so a decoder comparing velocity to zero sees note-off
and note-on as the same message. Use `math.copysign`, as `is_note_off` does.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

PERFORMANCE_PORT = 7772

#: A note began or ended.
OP_NOTE = 4

#: Seen as `,ii` alongside note traffic, values 0xffff and 0xfff7. A 16-bit field
#: with one bit clear invites reading it as a 16-voice allocation mask, and this
#: instrument does have 16 voices — but it did not reappear when notes were stacked
#: six deep, which a voice mask would have. It is recorded, not explained.
OP_UNKNOWN = 8

_ADDRESS = b"/\x00\x00\x00"


@dataclass(frozen=True)
class Note:
    note: int  # MIDI note number
    velocity: float  # 0.0-1.0; negative zero means the note ended

    @property
    def is_note_off(self) -> bool:
        # The sign bit, not the value: -0.0 == 0.0 is true, so a comparison against
        # zero cannot tell a note-off from a note-on at zero velocity.
        return math.copysign(1.0, self.velocity) < 0

    @property
    def midi_velocity(self) -> int:
        """Back to 0-127, the scale it arrived on before the instrument normalised it."""
        return 0 if self.is_note_off else round(abs(self.velocity) * 127)


@dataclass(frozen=True)
class Unknown:
    op: int
    value: int


def encode_note(note: int, velocity: float) -> bytes:
    """The bytes the voice controller itself emits for a note event.

    Provided for round-tripping tests and for replay experiments. Note that sending
    this *to* the instrument produced no sound in testing: 7772 is where the voice
    controller reports what it has already done, not where it is told to do it.
    """
    if not 0 <= note <= 127:
        raise ValueError(f"note {note} outside 0-127")
    return (
        _ADDRESS
        + b",iifi\x00\x00\x00"
        + struct.pack("!ii", OP_NOTE, note)
        + struct.pack("!f", velocity)
        + struct.pack("!i", 0)
    )


def encode_note_off(note: int) -> bytes:
    return encode_note(note, -0.0)


def decode(payload: bytes) -> Note | Unknown | None:
    """One performance message, or None if this is not one.

    None rather than an exception: this is fed from a live capture that also carries
    display framebuffers and panel polls, and non-performance traffic is the norm.
    """
    if len(payload) < 8 or payload[:4] != _ADDRESS:
        return None
    # The type tag string is NUL-terminated and padded to a 4-byte boundary, so its
    # block is 4 bytes for ",ii" and 8 for ",iifi". Hardcoding one offset silently
    # misreads the other -- the first draft read ",ii" four bytes late and produced
    # a plausible, wrong opcode.
    end = payload.index(b"\x00", 4)
    tag = payload[4:end]
    args = payload[4 + (((end - 4) + 4) & ~3) :]
    if tag == b",iifi" and len(args) >= 16:
        op, note = struct.unpack("!ii", args[0:8])
        (velocity,) = struct.unpack("!f", args[8:12])
        if op != OP_NOTE:
            return Unknown(op, note)
        return Note(note, velocity)
    if tag == b",ii" and len(args) >= 8:
        op, value = struct.unpack("!ii", args[0:8])
        return Unknown(op, value)
    return None


def notes_in(datagrams) -> list[Note]:
    """Every note event in a sequence of `moogone.pcap.Datagram`."""
    out = []
    for d in datagrams:
        if d.dst_port == PERFORMANCE_PORT or d.src_port == PERFORMANCE_PORT:
            m = decode(d.payload)
            if isinstance(m, Note):
                out.append(m)
    return out


class NoteStream:
    """A live feed of what the instrument is playing, over SSH.

    `tcpdump -w -` on the device, piped back through SSH, parsed as it arrives. The
    voice controller reports every note on port 7772, so this shows what the
    instrument is doing whether the notes came from its own keyboard, from MIDI, or
    from anywhere else — including notes this toolkit did not send.

    Read-only. It starts a capture and reads it; nothing is transmitted.
    """

    def __init__(self, host: str, on_note, on_error=None):
        self._host = host
        self._on_note = on_note
        self._on_error = on_error
        self._proc = None
        self._stop = False

    #: -U flushes each packet as it is written rather than at buffer boundaries.
    #: Without it the feed arrives in bursts of a few kilobytes, which for a note
    #: stream means nothing for seconds and then everything at once.
    COMMAND = (
        "export PATH=/usr/sbin:/sbin:/usr/bin:/bin; "
        "exec tcpdump -i usbint -n -s 0 -U -w - 'udp port 7772' 2>/dev/null"
    )

    def run(self) -> None:
        """Block, calling `on_note` per note. Returns when stopped or the pipe closes."""
        import subprocess

        from .pcap import iter_records, udp_of

        self._proc = subprocess.Popen(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "ConnectTimeout=15",
                "-o", "ServerAliveInterval=10",
                f"root@{self._host}",
                self.COMMAND,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ts, frame in iter_records(self._proc.stdout.read1):
                if self._stop:
                    break
                u = udp_of(frame)
                if u is None:
                    continue
                message = decode(u[4])
                if isinstance(message, Note):
                    self._on_note(message)
        except (OSError, ValueError) as exc:  # pragma: no cover - transport failures
            # OSError covers the pipe dying; ValueError covers PcapError, which is a
            # ValueError, for a stream that never became a pcap -- an ssh that failed
            # and wrote a message where the header should be.
            if self._on_error:
                self._on_error(exc)
        finally:
            self.stop()

    def stop(self) -> None:
        import subprocess

        self._stop = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
