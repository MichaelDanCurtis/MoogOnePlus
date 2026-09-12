"""FM synthesis running inside the instrument's own engine.

The Moog One's effects run in a `scsynth` this toolkit can load synthdefs into,
so an FM voice can live *in* the instrument: out its own jacks, through its own
delay and reverb, played from its own keyboard. Nothing is plugged in.

Measured on the hardware before building any of it: the server idles at 55.2% of
one core running the instrument's own effects, and a two-operator voice costs
**0.50% of a core** at the margin. Sixty-four voices reached 87% with **zero
xruns and zero lateness** — scsynth runs `SCHED_FIFO` at priority -95, which is
why it holds. Budget on `VOICE_CPU_COST` rather than optimism.

**What this is not.** The analog ladder filters are *upstream*: the voice cards
feed scsynth's input buses, and nothing routes back the other way. FM synthesised
here cannot pass through them. It shares the instrument's outputs and effects, not
its filters, and any claim otherwise is wrong.

**What it can do that the instrument cannot.** scsynth *hears* the analog voices
on those input buses, so an operator can take a real Moog voice as its modulator —
cross-synthesis between the voice cards and a digital operator, inside the box.
`CROSS_DEF` is that; no external plugin can reach it, because the dry analog
signal never leaves the instrument.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

from .synthdef import compile_synthdef

#: The jacks. `Out.ar` writes consecutive buses, so the right channel needs its
#: own write.
#:
#: These were reversed until 2026-09-09 and everything this module played came
#: out channel-swapped. `synthdefs.scd:564-565` is the authority: `Out.ar(7,
#: main[0] * -1)` sends **left** to bus 7, and `Out.ar(0, main[1] * -1)` sends
#: **right** to bus 0. Moog also invert both. See `sampler.py` for the longer
#: note and docs/CORRECTIONS-2026-09-08.md.
# Re-exported from effect.py so the pair is defined once. It is 7 and 0, not
# 0 and 1, and this project has got that wrong in four separate files.
from .effect import MAIN_LEFT, MAIN_RIGHT  # noqa: E402

#: Input buses carrying the analog voices, pre-effects. Measured by playing while
#: recording each: 8/9 and 10/11 are stereo pairs, 12 is the loudest single feed,
#: and 13-15 are silent.
ANALOG_IN_BUSES = (8, 9, 10, 11, 12)
ANALOG_IN_DEFAULT = 12

#: Clear of the sampler's node range (91000+) so the two can run together.
FIRST_NODE = 93000
MAX_VOICES = 48

#: Fraction of one core per sounding voice, measured rather than guessed.
VOICE_CPU_COST = 0.005
#: What the instrument's own effects already cost, on an idle preset.
BASELINE_CPU = 0.552

FM_DEF = "voxFM"
CROSS_DEF = "voxFMCross"

#: Two operators. The modulator's peak deviation is `index * freq * ratio`, not
#: `index * freq`: the modulation index I is defined as deviation divided by
#: MODULATOR frequency, and getting that wrong puts the real index off by a factor
#: of `ratio` -- so the sidebands would stop matching `sidebands()` and the display
#: would quietly lie about the sound.
FM_GRAPH = (
    "|freq = 220, amp = 0.2, ratio = 2, index = 3, attack = 0.01, decay = 1.2, "
    "left = 0, right = 7| "
    "var env = EnvGen.kr(Env.perc(attack, decay), doneAction: 2); "
    "var mod = SinOsc.ar(freq * ratio, 0, index * freq * ratio); "
    "var car = SinOsc.ar(freq + mod) * amp * env; "
    "Out.ar(left, car); Out.ar(right, car)"
)

#: The same carrier, modulated by whatever the analog voice cards are playing.
CROSS_GRAPH = (
    "|freq = 220, amp = 0.2, index = 3, inbus = 12, attack = 0.01, decay = 1.2, "
    "left = 0, right = 7| "
    "var env = EnvGen.kr(Env.perc(attack, decay), doneAction: 2); "
    "var src = In.ar(inbus, 1); "
    "var car = SinOsc.ar(freq + (src * index * freq)) * amp * env; "
    "Out.ar(left, car); Out.ar(right, car)"
)

MODES = ("self", "analog")


class FMError(RuntimeError):
    """Something the engine was asked to do that it cannot."""


def bessel_j(n: int, x: float, terms: int = 60) -> float:
    """Bessel function of the first kind, by its power series.

    Present because the sidebands of an FM tone sit at `fc ± n*fm` with amplitude
    `Jn(index)` — so this is what lets the interface show *why* a setting sounds
    the way it does instead of leaving the index an opaque knob. scipy is not a
    dependency of this project and is not worth becoming one for a display.

    The series alternates, so it loses significance for large `x`; musical
    modulation indices are small enough that this does not bite, and
    `sidebands()` caps the index it will accept rather than returning quiet
    nonsense.
    """
    if n < 0:
        # J(-n) = (-1)^n J(n)
        return (-1.0) ** (-n) * bessel_j(-n, x, terms)
    total = 0.0
    half = x / 2.0
    for k in range(terms):
        try:
            term = (
                ((-1.0) ** k) * (half ** (2 * k + n)) / (math.factorial(k) * math.factorial(n + k))
            )
        except OverflowError:
            break
        total += term
        if abs(term) < 1e-18 and k > n:
            break
    return total


#: Above this the alternating series stops being trustworthy in float64, and a
#: display that shows confident wrong numbers is worse than one that declines.
MAX_INDEX = 25.0


@dataclass(frozen=True)
class Sideband:
    """One partial of an FM tone."""

    order: int  # n, the sideband number; 0 is the carrier
    ratio: float  # frequency as a multiple of the carrier's fundamental
    amplitude: float  # |Jn(index)|

    @property
    def is_reflected(self) -> bool:
        """A sideband whose frequency came out negative and folded back up.

        Not a curiosity: reflected partials land on top of others and change the
        timbre, and they are the usual reason a small ratio change sounds far
        bigger than it looks.
        """
        return self.ratio < 0


def sidebands(ratio: float, index: float, limit: int = 12, floor: float = 0.001) -> list[Sideband]:
    """The partials an FM tone will actually contain, loudest first.

    Frequencies are multiples of the carrier: `1 ± n*ratio`. Negative results are
    kept as negative ratios rather than silently folded, so a caller can see that
    reflection is happening; `Sideband.is_reflected` names it.
    """
    if index < 0:
        raise FMError("modulation index cannot be negative")
    if index > MAX_INDEX:
        raise FMError(f"modulation index above {MAX_INDEX:g} is not computed here")
    if ratio <= 0:
        raise FMError("ratio must be positive")

    out = []
    for n in range(limit + 1):
        amp = abs(bessel_j(n, index))
        if amp < floor:
            continue
        if n == 0:
            out.append(Sideband(0, 1.0, amp))
            continue
        out.append(Sideband(n, 1.0 + n * ratio, amp))
        out.append(Sideband(-n, 1.0 - n * ratio, amp))
    out.sort(key=lambda s: (-s.amplitude, abs(s.order)))
    return out


def cpu_estimate(voices: int) -> float:
    """Predicted scsynth load, 0-1, for this many sounding voices."""
    return BASELINE_CPU + max(0, voices) * VOICE_CPU_COST


@dataclass(frozen=True)
class Preset:
    """A named FM sound.

    Recalling one is a single action that lands on **both** surfaces: it configures
    the engine, and the instrument's own screen changes to match. That is the whole
    point of the type existing rather than the interface just setting four numbers
    — a feature that only appears in a browser tab does not feel like part of the
    instrument.
    """

    name: str
    ratio: float
    index: float
    attack: float
    decay: float
    mode: str = "self"
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ratio": self.ratio,
            "index": self.index,
            "attack": self.attack,
            "decay": self.decay,
            "mode": self.mode,
            "note": self.note,
        }


#: Ratios and indices chosen so each one demonstrates something different about
#: what the spectrum display is telling you, not just to sound pleasant.
PRESETS: tuple[Preset, ...] = (
    Preset(
        "E PIANO",
        1.0,
        2.5,
        0.002,
        1.4,
        note="integer ratio: harmonic, partials land on the overtone series",
    ),
    Preset(
        "BASS",
        1.0,
        1.2,
        0.004,
        0.55,
        note="low index keeps it near a sine; the spectrum barely spreads",
    ),
    Preset(
        "BELL",
        3.5,
        5.0,
        0.002,
        3.2,
        note="non-integer ratio: inharmonic, and the partials fall between overtones",
    ),
    Preset(
        "METAL",
        7.1,
        8.0,
        0.001,
        1.8,
        note="wide ratio and high index: dense, and heavily reflected",
    ),
    Preset(
        "WOOD",
        2.0,
        4.0,
        0.001,
        0.35,
        note="short decay makes the index audible as a click rather than a tone",
    ),
    Preset("GLASS", 5.0, 3.0, 0.02, 4.0, note="sparse high partials over a long tail"),
    Preset(
        "SUB REFLECT",
        0.5,
        6.0,
        0.005,
        2.0,
        note="ratio below 1 folds partials through zero - watch the blue",
    ),
    Preset(
        "MOOG CROSS",
        1.0,
        4.0,
        0.002,
        2.5,
        mode="analog",
        note="the Moog's own analog voice is the modulator - play the keys to hear it",
    ),
)


def preset(name: str) -> Preset:
    for p in PRESETS:
        if p.name.upper() == name.upper():
            return p
    raise FMError(f"no FM preset called {name!r}")


@dataclass(frozen=True)
class Voice:
    node: int
    note: int
    freq: float
    started: float
    mode: str


def note_to_freq(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


class FMEngine:
    """Plays FM voices inside the instrument.

    Voice ids cycle through a fixed range. A voice frees itself when its envelope
    ends, so a recycled id is usually already gone -- and freeing a node that has
    already ended draws a `/fail` nobody is waiting for, which then surfaces as the
    NEXT request's error. The expiry bookkeeping here exists to avoid sending
    those; see `docs/MOOG-ONE-INTERNALS.md` and `Sampler.note_on`, which had this
    exact bug.
    """

    def __init__(self, client, left: int = MAIN_LEFT, right: int = MAIN_RIGHT):
        self.client = client
        self.left = left
        self.right = right
        #: Group the voices are made in. 0 is the root group, which is where they
        #: belong when they go straight to the jacks. `moogone.effect` moves it, so
        #: that voices run BEFORE the effect that is meant to process them --
        #: nodes execute in creation order, and a voice made after the effect is
        #: heard dry with nothing reporting a problem.
        self.group = 0
        self.ratio = 2.0
        self.index = 3.0
        self.attack = 0.01
        self.decay = 1.2
        self.amp = 0.2
        self.mode = "self"
        self.inbus = ANALOG_IN_DEFAULT
        self.preset_name = ""
        self._voice = 0
        self._expiry: dict[int, float] = {}
        self._sounding: dict[int, Voice] = {}
        self._lock = threading.Lock()
        self._loaded = False

    def ensure_synthdefs(self) -> None:
        if self._loaded:
            return
        self.client.d_recv(compile_synthdef(FM_DEF, FM_GRAPH))
        self.client.d_recv(compile_synthdef(CROSS_DEF, CROSS_GRAPH))
        self._loaded = True

    def configure(self, **kw) -> None:
        """Set parameters. Editing any of them by hand clears the preset name.

        Leaving a stale name attached to changed values would put a label on the
        instrument's screen that no longer describes the sound coming out of it.
        """
        if kw and not kw.get("_from_recall"):
            self.preset_name = ""
        kw.pop("_from_recall", None)
        for key, value in kw.items():
            if key == "mode":
                if value not in MODES:
                    raise FMError(f"mode must be one of {MODES}, not {value!r}")
                self.mode = value
            elif key == "inbus":
                if int(value) not in ANALOG_IN_BUSES:
                    raise FMError(f"input bus must be one of {ANALOG_IN_BUSES}")
                self.inbus = int(value)
            elif key == "ratio":
                if float(value) <= 0:
                    raise FMError("ratio must be positive")
                self.ratio = float(value)
            elif key == "index":
                if not 0 <= float(value) <= MAX_INDEX:
                    raise FMError(f"index must be between 0 and {MAX_INDEX:g}")
                self.index = float(value)
            elif key in ("attack", "decay", "amp"):
                setattr(self, key, max(0.0, float(value)))
            else:
                raise FMError(f"unknown parameter {key!r}")

    def recall(self, name: str) -> Preset:
        """Load a preset. The caller is expected to update BOTH surfaces after."""
        p = preset(name)
        self.configure(
            ratio=p.ratio,
            index=p.index,
            attack=p.attack,
            decay=p.decay,
            mode=p.mode,
            _from_recall=True,
        )
        self.preset_name = p.name
        return p

    def note_on(self, note: int, velocity: int = 100) -> int:
        if not 0 <= note <= 127:
            raise FMError(f"note {note} outside 0-127")
        self.ensure_synthdefs()
        freq = note_to_freq(note)
        amp = self.amp * (max(1, min(127, velocity)) / 127.0)
        now = time.monotonic()
        life = self.attack + self.decay

        with self._lock:
            node = FIRST_NODE + self._voice
            self._voice = (self._voice + 1) % MAX_VOICES
            expiry = self._expiry.get(node)
            still_playing = expiry is not None and now < expiry
            self._expiry[node] = now + life
            self._sounding[node] = Voice(node, note, freq, now, self.mode)

        if still_playing:
            self.client.send("/n_free", node)

        if self.mode == "analog":
            self.client.send(
                "/s_new",
                CROSS_DEF,
                node,
                1,
                self.group,
                "freq",
                freq,
                "amp",
                amp,
                "index",
                self.index,
                "inbus",
                self.inbus,
                "attack",
                self.attack,
                "decay",
                self.decay,
                "left",
                self.left,
                "right",
                self.right,
            )
        else:
            self.client.send(
                "/s_new",
                FM_DEF,
                node,
                1,
                self.group,
                "freq",
                freq,
                "amp",
                amp,
                "ratio",
                self.ratio,
                "index",
                self.index,
                "attack",
                self.attack,
                "decay",
                self.decay,
                "left",
                self.left,
                "right",
                self.right,
            )
        return node

    def note_off(self, note: int) -> None:
        """Percussive envelopes run to their end; this only forgets the note.

        Freeing here would cut the tail the moment a key lifted.
        """
        with self._lock:
            for node, voice in list(self._sounding.items()):
                if voice.note == note:
                    self._sounding.pop(node, None)

    def active(self) -> list[Voice]:
        """Voices that should still be sounding, newest first."""
        now = time.monotonic()
        with self._lock:
            live = [v for n, v in self._sounding.items() if (self._expiry.get(n) or 0.0) > now]
        return sorted(live, key=lambda v: -v.started)

    def stop_all(self) -> None:
        now = time.monotonic()
        with self._lock:
            live = [n for n in self._sounding if (self._expiry.get(n) or 0.0) > now]
            self._sounding.clear()
            self._expiry.clear()
        for node in live:
            self.client.send("/n_free", node)

    def as_dict(self) -> dict:
        voices = self.active()
        return {
            "preset": self.preset_name,
            "presets": [p.as_dict() for p in PRESETS],
            "mode": self.mode,
            "ratio": self.ratio,
            "index": self.index,
            "attack": self.attack,
            "decay": self.decay,
            "amp": self.amp,
            "inbus": self.inbus,
            "buses": list(ANALOG_IN_BUSES),
            "voices": [
                {
                    "note": v.note,
                    "freq": round(v.freq, 2),
                    "mode": v.mode,
                    "age": round(time.monotonic() - v.started, 3),
                }
                for v in voices
            ],
            "cpu_estimate": round(cpu_estimate(len(voices)), 3),
            "spectrum": [
                {
                    "order": s.order,
                    "ratio": round(s.ratio, 4),
                    "amplitude": round(s.amplitude, 4),
                    "reflected": s.is_reflected,
                }
                for s in sidebands(self.ratio, self.index)
            ]
            if self.mode == "self"
            else [],
        }
