"""The instrument's own control vocabulary, as a catalogue you can pick from.

Every Moog One preset is a flat list of `/p/...` paths — 3,197 of them — which is
the `/p` namespace an earlier address sweep found and could not read. Read from a
preset, it is the complete control surface of the instrument, named by the
instrument. No manual required, and no guessing: these are the paths the firmware
itself uses.

What is here is the **panel**: the controls that exist as a physical knob, switch or
button. The full namespace also carries the sequencer, arpeggiator, effects and mod
matrix, which are screens rather than panel controls and are better browsed than
listed. `PANEL_PATH` is the shape those take:

    /p/part/t/<timbre>/p/<group>/<control>

with `<timbre>` 1-3, matching the instrument's three small displays.

Abbreviations are the firmware's, expanded here from the panel legend: `fa` is the
State Variable Filter, `fb` the Ladder Filter, `p` a cutoff or pitch, `r` resonance,
`eg_p` envelope amount, `lfo_p` LFO amount.
"""

from __future__ import annotations

from dataclasses import dataclass

PANEL_PATH = "/p/part/t/{timbre}/p/{group}/{control}"
TIMBRES = (1, 2, 3)


@dataclass(frozen=True)
class Control:
    """One physical control, and the path the firmware knows it by."""

    group: str  # e.g. "o1", "fa"
    control: str  # e.g. "oct", "1/lp"
    label: str  # what the panel calls it
    section: str  # the panel area it lives in
    kind: str = "knob"  # knob | switch | button

    def path(self, timbre: int = 1) -> str:
        if timbre not in TIMBRES:
            raise ValueError(f"timbre must be 1, 2 or 3, not {timbre}")
        # A few controls are leaves of the group itself -- `pan`, `pan-spread` -- with
        # no sub-name. Formatting those through the template leaves a trailing slash
        # and a path the instrument does not have.
        stem = f"/p/part/t/{timbre}/p/{self.group}"
        return f"{stem}/{self.control}" if self.control else stem

    def as_dict(self, timbre: int = 1) -> dict:
        return {
            "label": self.label,
            "section": self.section,
            "kind": self.kind,
            "group": self.group,
            "control": self.control,
            "path": self.path(timbre),
        }


def _osc(n: int) -> list[Control]:
    g = f"o{n}"
    s = f"Oscillator {n}"
    return [
        Control(g, "oct", "Octave", s, "switch"),
        Control(g, "fo", "Frequency", s),
        Control(g, "pt", "Beat Freq", s),
        Control(g, "d", "Wave Angle", s),
        Control(g, "m", "Pulse Width", s),
        Control(g, "po", "Wave", s),
        Control(g, "krst", "Key Reset", s, "switch"),
        Control(g, f"sync{n}", "Hard Sync", s, "switch"),
    ]


def _lfo(n: int) -> list[Control]:
    g = f"l{n}"
    s = f"LFO {n}"
    return [
        Control(g, "f", "Rate", s),
        Control(g, "w", "Wave", s),
        Control(g, "var", "Wave Variation", s),
        Control(g, "ph", "Phase", s),
        Control(g, "div", "Division", s, "switch"),
        Control(g, "sync", "Sync", s, "switch"),
        Control(g, "pol", "Polarity", s, "switch"),
        Control(g, "one_shot", "One Shot", s, "switch"),
        Control(g, "rst", "Reset", s, "button"),
    ]


def _env(n: int, name: str) -> list[Control]:
    g = f"e{n}"
    return [
        Control(g, "delay", "Delay", name),
        Control(g, "a", "Attack", name),
        Control(g, "h", "Hold", name),
        Control(g, "d", "Decay", name),
        Control(g, "s", "Sustain", name),
        Control(g, "r", "Release", name),
        Control(g, "velmod", "Velocity Mod", name),
        Control(g, "multi-trig", "Multi Trig", name, "switch"),
        Control(g, "loop", "Loop", name, "switch"),
        Control(g, "latch", "Latch", name, "switch"),
        Control(g, "sync", "Sync", name, "switch"),
    ]


#: The panel, in the order the eye reads it: sources, then filters, then the
#: envelopes down the right-hand side.
CATALOG: tuple[Control, ...] = tuple(
    [c for n in (1, 2, 3) for c in _osc(n)]
    + [
        Control("noise", "mix", "Noise Level", "Noise"),
        Control("noise", "mode", "Noise Colour", "Noise", "switch"),
        # The mixer routes each source to either filter, which is what makes the two
        # filters series or parallel in practice.
        Control("mix", "o1/g", "Osc 1 Level", "Mixer"),
        Control("mix", "o2/g", "Osc 2 Level", "Mixer"),
        Control("mix", "o3/g", "Osc 3 Level", "Mixer"),
        Control("mix", "n/g", "Noise Level", "Mixer"),
        Control("mix", "rm/g", "Ring Mod Level", "Mixer"),
        Control("mix", "ext/g", "External Level", "Mixer"),
        Control("mix", "o1/fa", "Osc 1 to SVF", "Mixer", "switch"),
        Control("mix", "o1/fb", "Osc 1 to Ladder", "Mixer", "switch"),
        Control("mix", "o2/fa", "Osc 2 to SVF", "Mixer", "switch"),
        Control("mix", "o2/fb", "Osc 2 to Ladder", "Mixer", "switch"),
        Control("mix", "o3/fa", "Osc 3 to SVF", "Mixer", "switch"),
        Control("mix", "o3/fb", "Osc 3 to Ladder", "Mixer", "switch"),
        # fa: the State Variable Filter, with simultaneous low, band and high outputs.
        Control("fa", "p", "Cutoff", "State Variable Filter"),
        Control("fa", "r", "Resonance", "State Variable Filter"),
        Control("fa", "eg_p", "Envelope Amount", "State Variable Filter"),
        Control("fa", "lfo_p", "LFO Amount", "State Variable Filter"),
        Control("fa", "1/lp", "Low Pass", "State Variable Filter", "switch"),
        Control("fa", "1/bp", "Band Pass", "State Variable Filter", "switch"),
        Control("fa", "1/hp", "High Pass", "State Variable Filter", "switch"),
        Control("fa", "par", "Parallel", "State Variable Filter", "switch"),
        Control("fa", "fm/idx", "FM Amount", "State Variable Filter"),
        # fb: the Ladder.
        Control("fb", "p", "Cutoff", "Ladder Filter"),
        Control("fb", "r", "Resonance", "Ladder Filter"),
        Control("fb", "eg_p", "Envelope Amount", "Ladder Filter"),
        Control("fb", "lfo_p", "LFO Amount", "Ladder Filter"),
        Control("fb", "hp", "High Pass", "Ladder Filter"),
        Control("fb", "tap", "Ladder Tap", "Ladder Filter", "switch"),
        Control("fb", "fm/idx", "FM Amount", "Ladder Filter"),
    ]
    + _env(1, "Filter Envelope")
    + _env(2, "Amplifier Envelope")
    + _env(3, "Modulation Envelope")
    + [c for n in (1, 2, 3, 4) for c in _lfo(n)]
    + [
        Control("pan", "", "Pan", "Output"),
        Control("pan-spread", "", "Pan Spread", "Output"),
        Control("sus", "mode", "Sustain Mode", "Output", "switch"),
        Control("sus", "src", "Sustain Source", "Output", "switch"),
    ]
)


def sections() -> list[str]:
    """Panel sections in catalogue order, without duplicates."""
    seen: list[str] = []
    for c in CATALOG:
        if c.section not in seen:
            seen.append(c.section)
    return seen


def for_ui(timbre: int = 1) -> list[dict]:
    return [c.as_dict(timbre) for c in CATALOG]


def find(text: str) -> list[Control]:
    """Everything whose label, section or path contains `text`, case-insensitively."""
    needle = text.strip().lower()
    if not needle:
        return list(CATALOG)
    return [
        c
        for c in CATALOG
        if needle in c.label.lower()
        or needle in c.section.lower()
        or needle in f"{c.group}/{c.control}".lower()
    ]
