"""Play your own audio from inside the instrument, triggered by its own keyboard.

Everything this needs was established separately and is only assembled here: audio
can be pushed to the device and read into a buffer, a compiled SynthDef can be loaded
over `/d_recv`, and the voice controller reports **every** note the instrument plays
on port 7772 — its own keys as much as anything sent over MIDI.

So: press a key on the Moog, hear your sample, out the Moog's own jacks, through its
own effects. Nothing is plugged in.

Two details are load-bearing and were both learned the hard way:

- **The main outputs are buses 0 and 7**, not 0 and 1, and `Out.ar` writes
  consecutive buses. A single stereo `Out.ar(0, ...)` sends the right channel to a bus
  that never reaches the jacks, which measures as a perfect stereo pair and *sounds*
  like a fault in one speaker.
- **This instrument ignores CC 123.** Notes end when a note-off arrives for them and
  not otherwise, which is why voices are tracked by note number rather than assumed.
"""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .synthdef import compile_synthdef

#: Main left and right, mapped by tone injection. See docs/MOOG-ONE-INTERNALS.md.
MAIN_LEFT = 0
MAIN_RIGHT = 7

#: Buffers and nodes live high, clear of the instrument's own graph (node ids in the
#: 1000s, and buffers the firmware may be using).
FIRST_BUFFER = 1100
FIRST_NODE = 91000
MAX_VOICES = 32

#: `doneAction: 2` frees the synth when the buffer runs out, so a one-shot cleans
#: itself up and nothing has to remember it. The envelope only removes the click at
#: the start; how a sample ends is the sample's business.
VOICE_GRAPH = (
    "|buf = 0, rate = 1, amp = 0.5, left = 0, right = 7| "
    "var sig = PlayBuf.ar(2, buf, rate, doneAction: 2) * amp; "
    "sig = sig * EnvGen.kr(Env([0, 1], [0.004])); "
    "Out.ar(left, sig[0]); Out.ar(right, sig[1])"
)
VOICE_DEF = "voxSample"


class SamplerError(RuntimeError):
    """A sample that cannot be loaded or played, and why."""


@dataclass(frozen=True)
class Sample:
    """One loaded sample, and the note it plays back at its recorded pitch."""

    name: str
    buffer: int
    root_note: int = 60
    frames: int = 0
    channels: int = 2

    def rate_for(self, note: int) -> float:
        """Playback rate to sound `note`, by equal temperament from the root.

        An octave up is twice the rate, which is also twice the speed — this is
        sampler transposition, not time-stretching, and it is what makes a sample
        played two octaves up sound like a sample played two octaves up.
        """
        return float(2.0 ** ((note - self.root_note) / 12.0))


@dataclass
class SampleMap:
    """Which sample a note plays.

    A sample assigned with `spread` covers the whole keyboard, transposed. Individual
    assignments override it, so a drum map and a pitched instrument can coexist.
    """

    spread: Sample | None = None
    by_note: dict[int, Sample] = field(default_factory=dict)

    def for_note(self, note: int) -> Sample | None:
        return self.by_note.get(note, self.spread)

    def assign(self, note: int, sample: Sample) -> None:
        if not 0 <= note <= 127:
            raise SamplerError(f"note {note} is outside 0-127")
        self.by_note[note] = sample

    def clear(self, note: int) -> None:
        self.by_note.pop(note, None)

    def as_dict(self) -> dict:
        return {
            "spread": self.spread.name if self.spread else None,
            "by_note": {str(n): s.name for n, s in sorted(self.by_note.items())},
        }


def velocity_to_amp(velocity: int, floor_db: float = -36.0) -> float:
    """MIDI velocity to a gain, shaped so quiet notes stay playable.

    Linear velocity puts everything below about 40 into inaudibility. Squaring it and
    lifting the bottom to `floor_db` keeps the whole range useful, which is what a
    velocity curve is for.
    """
    v = max(0, min(127, int(velocity))) / 127.0
    if v <= 0:
        return 0.0
    floor = 10.0 ** (floor_db / 20.0)
    return float(floor + (1.0 - floor) * v * v)


class Sampler:
    """Loads samples into the instrument and plays them.

    Voice ids cycle through a fixed range rather than growing without bound; a synth
    frees itself when its buffer ends, so a recycled id is almost always already gone,
    and freeing it again is harmless.
    """

    def __init__(self, client, left: int = MAIN_LEFT, right: int = MAIN_RIGHT):
        self.client = client
        self.left = left
        self.right = right
        self.map = SampleMap()
        self.samples: dict[str, Sample] = {}
        self._next_buffer = FIRST_BUFFER
        self._voice = 0
        self._sounding: dict[int, int] = {}      # note -> node id
        self._lock = threading.Lock()
        self._loaded = False

    # -- setup ---------------------------------------------------------------
    def ensure_synthdef(self) -> None:
        if not self._loaded:
            self.client.d_recv(compile_synthdef(VOICE_DEF, VOICE_GRAPH))
            self._loaded = True

    def push(self, local_path: str | Path, host: str, remote_dir: str = "/tmp") -> str:
        """Copy a local audio file to the instrument. Returns the remote path."""
        local = Path(local_path)
        if not local.is_file():
            raise SamplerError(f"no such file: {local}")
        remote = f"{remote_dir}/vox-{local.name}"
        result = subprocess.run(
            ["scp", "-O", "-q",
             "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
             str(local), f"root@{host}:{remote}"],
            capture_output=True, text=True, timeout=300, check=False,
        )
        if result.returncode != 0:
            raise SamplerError(f"could not copy {local.name}: {result.stderr.strip()}")
        return remote

    def load(self, name: str, remote_path: str, root_note: int = 60) -> Sample:
        """Read a file on the instrument into a buffer."""
        self.ensure_synthdef()
        buf = self._next_buffer
        self._next_buffer += 1
        self.client.send("/b_allocRead", buf, remote_path, 0, 0)
        self.client.sync()
        info = self.client.request("/b_query", buf, reply="/b_info", timeout=4.0)
        frames = int(info.args[1]) if len(info.args) > 1 else 0
        channels = int(info.args[2]) if len(info.args) > 2 else 0
        if frames <= 0:
            raise SamplerError(f"{remote_path} loaded as an empty buffer")
        if channels != 2:
            raise SamplerError(
                f"{remote_path} has {channels} channel(s); the voice reads 2. "
                "Convert to stereo first."
            )
        sample = Sample(name, buf, root_note, frames, channels)
        self.samples[name] = sample
        return sample

    # -- playing -------------------------------------------------------------
    def note_on(self, note: int, velocity: int = 100) -> int | None:
        """Start a voice for `note`. Returns its node id, or None if nothing is mapped."""
        sample = self.map.for_note(note)
        if sample is None:
            return None
        with self._lock:
            node = FIRST_NODE + self._voice
            self._voice = (self._voice + 1) % MAX_VOICES
            previous = self._sounding.get(note)
            self._sounding[note] = node
        if previous is not None:
            self.client.send("/n_free", previous)
        self.client.send(
            "/s_new", VOICE_DEF, node, 1, 0,
            "buf", sample.buffer,
            "rate", sample.rate_for(note),
            "amp", velocity_to_amp(velocity),
            "left", self.left, "right", self.right,
        )
        return node

    def note_off(self, note: int) -> None:
        """One-shots run to their end; this only forgets the note.

        Freeing the synth here would cut a sample off the moment a key lifted, which
        is wrong for percussion and for anything with a tail. `doneAction: 2` ends it.
        """
        with self._lock:
            self._sounding.pop(note, None)

    def stop_all(self) -> None:
        with self._lock:
            nodes = list(self._sounding.values())
            self._sounding.clear()
        for node in nodes:
            self.client.send("/n_free", node)


class LiveSampler:
    """Trigger the sampler from the instrument's own note stream.

    The voice controller announces every note on port 7772 regardless of where it came
    from, so this responds to the Moog's own keyboard exactly as it responds to MIDI.
    Nothing is plugged in and nothing is intercepted — it listens to a report the
    instrument is already broadcasting.

    A note therefore does two things at once: it sounds the instrument's own voice
    **and** it triggers the sample. Turning the analog voice down is a job for the
    panel; this layers rather than replaces.
    """

    def __init__(self, sampler: Sampler, host: str, on_note=None):
        from .performance import PERFORMANCE_PORT
        from .stream import BusStream

        self.sampler = sampler
        self.on_note = on_note
        self._stream = BusStream(host, (PERFORMANCE_PORT,), self._feed)

    def _feed(self, _sport: int, _dport: int, payload: bytes) -> None:
        from .performance import Note, decode

        message = decode(payload)
        if not isinstance(message, Note):
            return
        if message.is_note_off:
            self.sampler.note_off(message.note)
        else:
            self.sampler.note_on(message.note, message.midi_velocity)
        if self.on_note:
            self.on_note(message)

    def run(self) -> None:
        """Block, triggering samples, until stopped or the capture ends."""
        self._stream.run()

    def stop(self) -> None:
        self._stream.stop()
        self.sampler.stop_all()
