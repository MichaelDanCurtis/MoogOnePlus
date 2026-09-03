"""MPE and polyphonic-aftertouch decoding into per-voice events.

Two input dialects, one output:

- **Poly aftertouch** (``0xA0 note pressure``) is keyed by note number. Cleanest for a
  hammer-action keybed with per-key pressure, which is what the S88 provides.
- **MPE** spreads notes across member channels. Pressure (``0xD0``), slide (CC 74) and bend
  (``0xE0``) arrive on the member channel of the note they belong to. The **master**
  channel addresses every note in the zone at once.

Voice tracking is ours: this is the "take over" branch of the per-voice-pressure spec's
Phase 3. Note-on allocates the lowest free voice; when all are busy the oldest is stolen
and an ``off`` is emitted for the victim so downstream state never dangles.
"""

from __future__ import annotations

from dataclasses import dataclass, field

KINDS = ("on", "off", "pressure", "slide", "bend")


@dataclass(frozen=True)
class ZoneConfig:
    zone: str = "lower"  # "lower" | "upper"
    members: int = 15
    bend_range: float = 48.0  # semitones, MPE member default

    @property
    def master(self) -> int:
        return 0 if self.zone == "lower" else 15

    @property
    def member_channels(self) -> frozenset[int]:
        if self.zone == "lower":
            return frozenset(range(1, 1 + self.members))
        return frozenset(range(15 - self.members, 15))


@dataclass(frozen=True)
class NoteEvent:
    kind: str
    voice: int
    note: int
    value: float  # velocity/pressure/slide 0..1; bend -1..1; off 0
    channel: int


@dataclass
class VoiceTracker:
    n_voices: int = 16
    _voice_note: dict[int, int] = field(default_factory=dict)  # voice -> note
    _order: list[int] = field(default_factory=list)  # voices, oldest first

    def voice_for(self, note: int) -> int | None:
        for v, n in self._voice_note.items():
            if n == note:
                return v
        return None

    def oldest(self) -> int | None:
        """The voice that would be stolen next."""
        return self._order[0] if self._order else None

    def allocate(self, note: int) -> int:
        existing = self.voice_for(note)
        if existing is not None:
            return existing
        free = [v for v in range(self.n_voices) if v not in self._voice_note]
        v = free[0] if free else self._order.pop(0)
        self._voice_note[v] = note
        if v in self._order:
            self._order.remove(v)
        self._order.append(v)
        return v

    def release(self, note: int) -> int | None:
        v = self.voice_for(note)
        if v is None:
            return None
        del self._voice_note[v]
        self._order.remove(v)
        return v

    def active(self) -> dict[int, int]:
        return dict(self._voice_note)


class MpeDecoder:
    def __init__(self, zone: ZoneConfig | None = None, n_voices: int = 16):
        self.zone = zone or ZoneConfig()
        self.tracker = VoiceTracker(n_voices)
        self._channel_note: dict[int, int] = {}  # member channel -> note on it

    def feed(self, data: bytes | list[int]) -> list[NoteEvent]:
        b = list(data)
        if not b:
            return []
        status = b[0]
        if status >= 0xF0:
            return []
        kind, ch = status & 0xF0, status & 0x0F
        if kind in (0x90, 0x80, 0xA0, 0xB0, 0xE0) and len(b) < 3:
            return []
        if kind == 0xD0 and len(b) < 2:
            return []

        if kind == 0x90 and b[2] > 0:
            return self._note_on(ch, b[1], b[2] / 127.0)
        if kind == 0x80 or (kind == 0x90 and b[2] == 0):
            return self._note_off(ch, b[1])
        if kind == 0xA0:
            v = self.tracker.voice_for(b[1])
            return [] if v is None else [NoteEvent("pressure", v, b[1], b[2] / 127.0, ch)]
        if kind == 0xD0:
            return self._per_channel("pressure", ch, b[1] / 127.0)
        if kind == 0xB0 and b[1] == 74:
            return self._per_channel("slide", ch, b[2] / 127.0)
        if kind == 0xE0:
            raw = (b[2] << 7) | b[1]
            value = (raw - 8192) / 8191.0 if raw > 8192 else (raw - 8192) / 8192.0
            return self._per_channel("bend", ch, value)
        return []

    # -- helpers ------------------------------------------------------------

    def _note_on(self, ch: int, note: int, vel: float) -> list[NoteEvent]:
        out: list[NoteEvent] = []
        victim: int | None = None
        if (
            self.tracker.voice_for(note) is None
            and len(self.tracker.active()) >= self.tracker.n_voices
        ):
            victim = self.tracker.active()[self.tracker.oldest()]
        v = self.tracker.allocate(note)
        if victim is not None:
            out.append(NoteEvent("off", v, victim, 0.0, self._channel_of(victim, ch)))
            self._forget_channel(victim)
        self._channel_note[ch] = note
        out.append(NoteEvent("on", v, note, vel, ch))
        return out

    def _note_off(self, ch: int, note: int) -> list[NoteEvent]:
        v = self.tracker.release(note)
        self._forget_channel(note)
        return [] if v is None else [NoteEvent("off", v, note, 0.0, ch)]

    def _per_channel(self, kind: str, ch: int, value: float) -> list[NoteEvent]:
        if ch == self.zone.master:
            return [
                NoteEvent(kind, v, n, value, ch) for v, n in sorted(self.tracker.active().items())
            ]
        if ch not in self.zone.member_channels:
            return []
        note = self._channel_note.get(ch)
        if note is None:
            return []
        v = self.tracker.voice_for(note)
        return [] if v is None else [NoteEvent(kind, v, note, value, ch)]

    def _channel_of(self, note: int, default: int) -> int:
        for c, n in self._channel_note.items():
            if n == note:
                return c
        return default

    def _forget_channel(self, note: int) -> None:
        for c, n in list(self._channel_note.items()):
            if n == note:
                del self._channel_note[c]
