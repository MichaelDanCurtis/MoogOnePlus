"""The UGen palette the patcher offers, as data.

Curated rather than exhaustive: everything here is a unit generator that earns its place
in an effects graph for an analog polysynth, described precisely enough that the UI can
draw its ports and the code generator can emit correct SuperCollider without either of
them knowing anything specific about it.

Ports carry defaults. A port with a default may be left unconnected and the default is
written into the generated source; a port without one **must** be connected, and the
validator refuses a graph that leaves it dangling. That is what stops the patcher from
emitting SuperCollider that only fails once it reaches a server.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Rates, in the order SuperCollider ranks them. A UGen may not run slower than a signal
#: it consumes — an audio-rate input into a control-rate UGen is an error, not a coercion.
RATES = ("scalar", "control", "audio")
RATE_SUFFIX = {"scalar": "ir", "control": "kr", "audio": "ar"}


@dataclass(frozen=True)
class Port:
    name: str
    default: float | None = None  # None -> a connection is required
    doc: str = ""

    @property
    def required(self) -> bool:
        return self.default is None


@dataclass(frozen=True)
class UGenSpec:
    name: str  # the SuperCollider class name, written verbatim
    category: str
    inputs: tuple[Port, ...] = ()
    outputs: int = 1
    rates: tuple[str, ...] = ("audio", "control")
    doc: str = ""

    def port(self, name: str) -> Port | None:
        return next((p for p in self.inputs if p.name == name), None)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "outputs": self.outputs,
            "rates": list(self.rates),
            "doc": self.doc,
            "inputs": [
                {"name": p.name, "default": p.default, "required": p.required, "doc": p.doc}
                for p in self.inputs
            ],
        }


def _u(name, category, inputs, *, outputs=1, rates=("audio", "control"), doc=""):
    return UGenSpec(name, category, tuple(inputs), outputs, tuple(rates), doc)


P = Port

CATALOG: dict[str, UGenSpec] = {
    s.name: s
    for s in [
        # ── sources ──────────────────────────────────────────────────────────
        _u("SinOsc", "source", [P("freq", 440.0), P("phase", 0.0)], doc="sine oscillator"),
        _u("Saw", "source", [P("freq", 440.0)], doc="band-limited sawtooth"),
        _u("Pulse", "source", [P("freq", 440.0), P("width", 0.5)], doc="band-limited pulse"),
        _u(
            "LFSaw",
            "source",
            [P("freq", 1.0), P("iphase", 0.0)],
            doc="non-band-limited saw; good LFO",
        ),
        _u("LFTri", "source", [P("freq", 1.0), P("iphase", 0.0)], doc="triangle LFO"),
        _u(
            "LFPulse",
            "source",
            [P("freq", 1.0), P("iphase", 0.0), P("width", 0.5)],
            doc="pulse LFO",
        ),
        _u("LFNoise1", "source", [P("freq", 4.0)], doc="ramped random — smooth wander"),
        _u("LFNoise2", "source", [P("freq", 4.0)], doc="quadratic random — smoother still"),
        _u("WhiteNoise", "source", [], doc="white noise"),
        _u("PinkNoise", "source", [], doc="pink noise"),
        _u("Dust", "source", [P("density", 4.0)], doc="random impulses"),
        _u("Impulse", "source", [P("freq", 1.0), P("phase", 0.0)], doc="steady impulses"),
        # ── filters ──────────────────────────────────────────────────────────
        _u("LPF", "filter", [P("in"), P("freq", 1200.0)], doc="12 dB low pass"),
        _u("HPF", "filter", [P("in"), P("freq", 200.0)], doc="12 dB high pass"),
        _u("BPF", "filter", [P("in"), P("freq", 800.0), P("rq", 1.0)], doc="band pass"),
        _u("BRF", "filter", [P("in"), P("freq", 800.0), P("rq", 1.0)], doc="band reject"),
        _u("RLPF", "filter", [P("in"), P("freq", 1200.0), P("rq", 0.5)], doc="resonant low pass"),
        _u("RHPF", "filter", [P("in"), P("freq", 400.0), P("rq", 0.5)], doc="resonant high pass"),
        _u("Resonz", "filter", [P("in"), P("freq", 800.0), P("bwr", 0.2)], doc="resonant body"),
        _u(
            "MoogFF",
            "filter",
            [P("in"), P("freq", 800.0), P("gain", 2.0), P("reset", 0.0)],
            doc="Moog ladder emulation — the obvious one to reach for here",
        ),
        _u("OnePole", "filter", [P("in"), P("coef", 0.5)], doc="one-pole smoothing"),
        _u("LeakDC", "filter", [P("in"), P("coef", 0.995)], doc="removes DC offset"),
        _u("Integrator", "filter", [P("in"), P("coef", 0.999)], doc="leaky integrator"),
        # ── time ─────────────────────────────────────────────────────────────
        _u(
            "DelayC",
            "time",
            [P("in"), P("maxdelaytime", 2.0), P("delaytime", 0.2)],
            doc="interpolating delay, no feedback",
        ),
        _u(
            "CombC",
            "time",
            [P("in"), P("maxdelaytime", 2.0), P("delaytime", 0.2), P("decaytime", 3.0)],
            doc="comb delay with feedback — echoes",
        ),
        _u(
            "AllpassC",
            "time",
            [P("in"), P("maxdelaytime", 1.0), P("delaytime", 0.05), P("decaytime", 2.0)],
            doc="allpass — diffusion, the guts of a reverb",
        ),
        _u(
            "FreeVerb",
            "time",
            [P("in"), P("mix", 0.33), P("room", 0.5), P("damp", 0.5)],
            doc="simple reverb",
        ),
        _u(
            "Decay2",
            "time",
            [P("in"), P("attackTime", 0.01), P("decayTime", 1.0)],
            doc="percussive envelope follower",
        ),
        # ── shaping ──────────────────────────────────────────────────────────
        _u(
            "Amplitude",
            "shape",
            [P("in"), P("attackTime", 0.01), P("releaseTime", 0.1)],
            doc="envelope follower",
        ),
        _u("Lag", "shape", [P("in"), P("lagTime", 0.1)], doc="smooths a control signal"),
        _u("Slew", "shape", [P("in"), P("up", 1.0), P("dn", 1.0)], doc="rate limiter"),
        _u("Limiter", "shape", [P("in"), P("level", 0.95), P("dur", 0.01)], doc="hard ceiling"),
        _u("SoftClip", "shape", [P("in")], doc="gentle saturation"),
        _u("Clip", "shape", [P("in"), P("lo", -1.0), P("hi", 1.0)], doc="hard clip"),
        # ── routing ──────────────────────────────────────────────────────────
        _u(
            "Pan2",
            "routing",
            [P("in"), P("pos", 0.0), P("level", 1.0)],
            outputs=2,
            doc="mono to stereo",
        ),
        _u(
            "Balance2",
            "routing",
            [P("left"), P("right"), P("pos", 0.0), P("level", 1.0)],
            outputs=2,
            doc="stereo balance",
        ),
        _u(
            "XFade2",
            "routing",
            [P("inA"), P("inB"), P("pan", 0.0), P("level", 1.0)],
            doc="equal-power crossfade",
        ),
        _u("LinXFade2", "routing", [P("inA"), P("inB"), P("pan", 0.0)], doc="linear crossfade"),
        _u("In", "routing", [P("bus", 0.0)], rates=("audio", "control"), doc="read an audio bus"),
        _u(
            "Out",
            "routing",
            [P("bus", 0.0), P("channelsArray")],
            outputs=0,
            doc="write an audio bus",
        ),
    ]
}

#: Arithmetic between signals. Written infix in the generated source rather than as a
#: named UGen, because `a * b` reads better than BinaryOpUGen and compiles to the same
#: thing.
BINARY_OPS: dict[str, str] = {"add": "+", "sub": "-", "mul": "*", "div": "/"}

BINOP_SPECS: dict[str, UGenSpec] = {
    f"op.{key}": UGenSpec(
        name=f"op.{key}",
        category="math",
        inputs=(P("a", 0.0), P("b", 0.0)),
        outputs=1,
        rates=("audio", "control"),
        doc=f"a {sym} b",
    )
    for key, sym in BINARY_OPS.items()
}

#: A named control the running synth can set with /n_set — a knob on the finished effect.
CONTROL_SPEC = UGenSpec(
    name="control",
    category="io",
    inputs=(),
    outputs=1,
    rates=("control",),
    doc="a named parameter, settable at runtime with /n_set",
)

ALL: dict[str, UGenSpec] = {**CATALOG, **BINOP_SPECS, CONTROL_SPEC.name: CONTROL_SPEC}


def spec(kind: str) -> UGenSpec:
    try:
        return ALL[kind]
    except KeyError:
        raise KeyError(f"unknown UGen {kind!r}; known: {', '.join(sorted(ALL))}") from None


def catalog_for_ui() -> list[dict]:
    """Everything the palette needs, grouped and ordered for display."""
    order = {
        c: i for i, c in enumerate(["io", "source", "filter", "time", "shape", "math", "routing"])
    }
    items = [s.as_dict() for s in ALL.values()]
    items.sort(key=lambda d: (order.get(d["category"], 99), d["name"]))
    return items
