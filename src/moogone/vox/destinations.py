"""Where a routed value can go, and how honestly each path is labelled.

Only :class:`ScParam` is ``live`` — the one path this session verified on hardware. MIDI
out from the Mac and raw OSC to ``las-sc`` are ``untested``: plausible, never run.
:class:`VoiceParam` is ``blocked``: the per-voice write address is unknown, and the
experiment that finds it is written into the badge so the UI can show it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from ..osc import OscMessage
from .protocol import BLOCKED, LIVE, UNTESTED, Badge

GO_NO_GO = (
    "Hold one note on the synth. Send the candidate per-voice write to move that one "
    "voice's filter cutoff. If exactly one voice in a held chord changes timbre, the "
    "per-voice path exists and this becomes one config value. Until then no per-voice "
    "write is sent."
)


class Destination(Protocol):
    badge: Badge

    def write(self, path: str, value: float) -> bool: ...


class ScParam:
    badge = LIVE

    def __init__(self, fx):
        self._fx = fx

    def write(self, path: str, value: float) -> bool:
        parts = path.split(".")
        if len(parts) != 3 or parts[0] != "sc":
            return False
        try:
            node = int(parts[1])
        except ValueError:
            return False
        self._fx.set(node, parts[2], float(value))
        return True


class _MidiBase:
    badge = UNTESTED(
        "MIDI from the Mac to the synth has not been proven. MIDI was only ever sent from "
        "the box's own ALSA. Cable check: Komplete Audio 6 DIN out -> Moog DIN in."
    )

    def __init__(self, port, channel: int = 0):
        self._port = port
        self._ch = channel & 0x0F


def _u7(value: float) -> int:
    return max(0, min(127, round(float(value) * 127)))


def _index(path: str, prefix: tuple[str, str]) -> int | None:
    parts = path.split(".")
    if len(parts) != 3 or tuple(parts[:2]) != prefix:
        return None
    try:
        n = int(parts[2])
    except ValueError:
        return None
    return n if 0 <= n <= 127 else None


class MidiCC(_MidiBase):
    def write(self, path: str, value: float) -> bool:
        cc = _index(path, ("midi", "cc"))
        if cc is None:
            return False
        self._port.send_message([0xB0 | self._ch, cc, _u7(value)])
        return True


class MidiNote(_MidiBase):
    def write(self, path: str, value: float) -> bool:
        note = _index(path, ("midi", "note"))
        if note is None:
            return False
        if float(value) >= 0.5:
            self._port.send_message([0x90 | self._ch, note, 100])
        else:
            self._port.send_message([0x80 | self._ch, note, 0])
        return True


class RawOsc:
    badge = UNTESTED(
        "Writes to las-sc / the voice bus were accepted but never audible this session. "
        "Sent as a single float argument."
    )

    def __init__(self, send: Callable[[bytes], None]):
        self._send = send

    def write(self, path: str, value: float) -> bool:
        if not path.startswith("osc."):
            return False
        address = "/" + path[4:].replace(".", "/")
        self._send(OscMessage(address, [float(value)]).encode())
        return True


class VoiceParam:
    badge = BLOCKED(GO_NO_GO)

    def write(self, path: str, value: float) -> bool:
        return False


class Dispatcher:
    def __init__(self):
        self._dests: list[tuple[str, Destination]] = []

    def register(self, prefix: str, dest: Destination) -> None:
        self._dests.append((prefix, dest))
        self._dests.sort(key=lambda p: -len(p[0]))  # longest prefix first

    def _find(self, path: str) -> Destination:
        for prefix, dest in self._dests:
            if path.startswith(prefix):
                return dest
        raise KeyError(f"no destination registered for {path!r}")

    def badge_for(self, path: str) -> Badge:
        return self._find(path).badge

    def write(self, path: str, value: float) -> tuple[bool, Badge]:
        dest = self._find(path)
        return dest.write(path, value), dest.badge
