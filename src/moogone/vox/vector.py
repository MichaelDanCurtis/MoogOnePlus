"""Vector synthesis: four corners, one position, and an orbit that moves it.

The Prophet VS / Wavestation idea, applied to whatever the instrument exposes. Four
corners each hold a snapshot of control values; a position on the square blends them
bilinearly. Move the position and every control crossfades at once.

The third dimension is the one you can actually see: pick a control and the blend becomes
a height field over the square — a landscape whose shape is set by what the four corners
hold for that control. The fourth is time, an LFO tracing a Lissajous orbit across the
surface, so the sound moves on its own.

Everything here is pure. The bridge owns the clock and the writes; this owns the maths.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: Corner order and their (x, y) positions on the unit square.
CORNERS = ("A", "B", "C", "D")
CORNER_XY = {"A": (0.0, 0.0), "B": (1.0, 0.0), "C": (1.0, 1.0), "D": (0.0, 1.0)}


def weights(x: float, y: float) -> dict[str, float]:
    """Bilinear corner weights at ``(x, y)``. Always sums to 1."""
    x = min(1.0, max(0.0, float(x)))
    y = min(1.0, max(0.0, float(y)))
    return {
        "A": (1.0 - x) * (1.0 - y),
        "B": x * (1.0 - y),
        "C": x * y,
        "D": (1.0 - x) * y,
    }


def blend(corners: dict[str, dict[str, float]], x: float, y: float) -> dict[str, float]:
    """Blend the four corner snapshots at ``(x, y)``.

    A corner need not carry every control. A path is blended over **only** the corners
    that define it, with their weights renormalised — so you can put one control in one
    corner and it still fades in as you approach, instead of being dragged toward zero by
    three corners that never mentioned it.
    """
    w = weights(x, y)
    numer: dict[str, float] = {}
    denom: dict[str, float] = {}
    for name in CORNERS:
        snap = corners.get(name) or {}
        cw = w[name]
        for path, value in snap.items():
            numer[path] = numer.get(path, 0.0) + cw * float(value)
            denom[path] = denom.get(path, 0.0) + cw
    return {p: numer[p] / denom[p] for p in numer if denom[p] > 1e-12}


def surface(
    corners: dict[str, dict[str, float]], path: str, n: int = 17
) -> list[list[float | None]]:
    """Sample one control's blended value over an ``n``×``n`` grid — the height field.

    Row 0 is ``y = 0``. A cell is ``None`` where no corner defines the path, which the
    renderer draws as a hole rather than as zero — a missing control is not a quiet one.
    """
    if n < 2:
        raise ValueError(f"grid must be at least 2x2, got {n}")
    grid: list[list[float | None]] = []
    for iy in range(n):
        row: list[float | None] = []
        for ix in range(n):
            values = blend(corners, ix / (n - 1), iy / (n - 1))
            row.append(values.get(path))
        grid.append(row)
    return grid


@dataclass
class Orbit:
    """A Lissajous path across the square — the LFO that moves the vector.

    ``rate_x``/``rate_y`` in Hz. Equal rates trace a line or a circle depending on phase;
    a small integer ratio traces the classic Lissajous figures, and an irrational-ish
    ratio never quite repeats, which is what makes a pad breathe.
    """

    rate_x: float = 0.10
    rate_y: float = 0.13
    phase_x: float = 0.0
    phase_y: float = 0.25  # quarter turn: a circle when the rates match
    depth: float = 1.0
    centre_x: float = 0.5
    centre_y: float = 0.5
    running: bool = False

    def at(self, t: float) -> tuple[float, float]:
        """Position at time ``t`` seconds. Always inside the unit square."""
        d = 0.5 * min(1.0, max(0.0, self.depth))
        x = self.centre_x + d * math.sin(2 * math.pi * (self.rate_x * t + self.phase_x))
        y = self.centre_y + d * math.sin(2 * math.pi * (self.rate_y * t + self.phase_y))
        return (min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))

    def trail(self, t: float, seconds: float = 8.0, n: int = 96) -> list[tuple[float, float]]:
        """The path over the last ``seconds``, oldest first — for drawing the orbit."""
        if n < 2:
            raise ValueError("trail needs at least 2 points")
        return [self.at(t - seconds + seconds * i / (n - 1)) for i in range(n)]


@dataclass(frozen=True)
class MotionPoint:
    """One knot on a recorded path. ``t`` is in *cycles*: 0 at the start, 1 at the end.

    Storing normalised time rather than seconds is what lets the same gesture play back
    free-running at one rate, tempo-synced at another, and retriggered per note without
    re-recording it.
    """

    t: float
    x: float
    y: float


@dataclass
class Motion:
    """A recorded or drawn path across the square — the vector *envelope*.

    This is the part the Prophet VS and the Wavestation had that a plain LFO does not: a
    path with knots you place yourself, so the movement is a gesture rather than a shape.
    ``loop`` decides what happens at the end.
    """

    points: list[MotionPoint] = field(default_factory=list)
    loop: str = "loop"  # "off" | "loop" | "pingpong"

    LOOPS = ("off", "loop", "pingpong")

    def __post_init__(self) -> None:
        if self.loop not in self.LOOPS:
            raise ValueError(f"loop must be one of {', '.join(self.LOOPS)}; got {self.loop!r}")

    def clear(self) -> None:
        self.points = []

    @property
    def empty(self) -> bool:
        return len(self.points) < 2

    def record(self, raw: list[tuple[float, float, float]]) -> None:
        """Take ``(seconds, x, y)`` samples and store them as a normalised path.

        The wall-clock span becomes the cycle, so a four-second gesture and a
        forty-second one both play back over whatever period you later ask for.
        """
        pts = sorted(raw, key=lambda p: p[0])
        # Two samples at the same instant are one knot, and the later one is the truer
        # position — arming the recorder seeds a knot at the current spot, and a drag
        # that begins in the same millisecond would otherwise be overruled by it.
        deduped: list[tuple[float, float, float]] = []
        for p in pts:
            if deduped and abs(p[0] - deduped[-1][0]) <= 1e-9:
                deduped[-1] = p
            else:
                deduped.append(p)
        pts = deduped
        if len(pts) < 2:
            self.points = []
            return
        t0, t1 = pts[0][0], pts[-1][0]
        span = t1 - t0
        if span <= 0:
            self.points = []
            return
        self.points = [
            MotionPoint((t - t0) / span, min(1.0, max(0.0, x)), min(1.0, max(0.0, y)))
            for t, x, y in pts
        ]

    def phase(self, cycles: float) -> float:
        """Map elapsed cycles to a position in 0..1, honouring the loop mode."""
        if self.loop == "off":
            return min(1.0, max(0.0, cycles))
        if self.loop == "loop":
            return cycles % 1.0
        wrapped = cycles % 2.0  # pingpong: out and back
        return wrapped if wrapped <= 1.0 else 2.0 - wrapped

    def at(self, cycles: float) -> tuple[float, float]:
        """Position at ``cycles`` elapsed. Linear between knots."""
        if not self.points:
            return (0.5, 0.5)
        if len(self.points) == 1:
            return (self.points[0].x, self.points[0].y)
        p = self.phase(cycles)
        pts = self.points
        if p <= pts[0].t:
            return (pts[0].x, pts[0].y)
        if p >= pts[-1].t:
            return (pts[-1].x, pts[-1].y)
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            if a.t <= p <= b.t:
                span = b.t - a.t
                f = 0.0 if span <= 1e-12 else (p - a.t) / span
                return (a.x + (b.x - a.x) * f, a.y + (b.y - a.y) * f)
        return (pts[-1].x, pts[-1].y)

    def as_dict(self) -> dict:
        return {
            "loop": self.loop,
            "points": [{"t": p.t, "x": p.x, "y": p.y} for p in self.points],
        }


@dataclass
class Clock:
    """What "one cycle" means: a free-running period, or a musical division of a tempo.

    ``tempo`` mode is what makes motion lock to a track — one cycle spans ``beats`` beats
    at ``bpm``, so a 4-beat path stays a bar long whatever the tempo. ``retrigger`` makes
    a note-on restart the path from its beginning, which is how a vector envelope behaves
    on a keyboard.
    """

    mode: str = "free"  # "free" | "tempo"
    period: float = 8.0  # seconds per cycle, free mode
    bpm: float = 120.0
    beats: float = 4.0  # beats per cycle, tempo mode
    retrigger: bool = False

    MODES = ("free", "tempo")

    def __post_init__(self) -> None:
        if self.mode not in self.MODES:
            raise ValueError(
                f"clock mode must be one of {', '.join(self.MODES)}; got {self.mode!r}"
            )

    @property
    def seconds_per_cycle(self) -> float:
        if self.mode == "tempo":
            return max(1e-6, self.beats * 60.0 / max(1e-6, self.bpm))
        return max(1e-6, self.period)

    def cycles(self, elapsed: float) -> float:
        return elapsed / self.seconds_per_cycle


@dataclass
class VectorEngine:
    """Corners, a position, and whatever is moving it.

    Three movement modes, all writing the same position:

    ``manual``    your hand on the pad
    ``orbit``     a Lissajous LFO — a shape
    ``motion``    a recorded or drawn path — a gesture, on a free or tempo-synced clock
    """

    corners: dict[str, dict[str, float]] = field(default_factory=lambda: {c: {} for c in CORNERS})
    x: float = 0.5
    y: float = 0.5
    orbit: Orbit = field(default_factory=Orbit)
    motion: Motion = field(default_factory=Motion)
    clock: Clock = field(default_factory=Clock)
    mode: str = "manual"  # "manual" | "orbit" | "motion"
    recording: bool = False
    _rec: list[tuple[float, float, float]] = field(default_factory=list)
    _origin: float = 0.0

    MODES = ("manual", "orbit", "motion")

    def set_corner(self, name: str, snapshot: dict[str, float]) -> None:
        if name not in CORNERS:
            raise ValueError(f"corner must be one of {', '.join(CORNERS)}; got {name!r}")
        self.corners[name] = {str(k): float(v) for k, v in snapshot.items()}

    def clear_corner(self, name: str) -> None:
        if name not in CORNERS:
            raise ValueError(f"corner must be one of {', '.join(CORNERS)}; got {name!r}")
        self.corners[name] = {}

    def set_mode(self, mode: str) -> None:
        if mode not in self.MODES:
            raise ValueError(f"mode must be one of {', '.join(self.MODES)}; got {mode!r}")
        self.mode = mode

    def move(self, x: float, y: float, t: float | None = None) -> None:
        """Put the position here. While recording, this is also a knot on the path."""
        self.x = min(1.0, max(0.0, float(x)))
        self.y = min(1.0, max(0.0, float(y)))
        if self.recording and t is not None:
            self._rec.append((float(t), self.x, self.y))

    def start_recording(self, t: float) -> None:
        """Arm the recorder. Every :meth:`move` from now becomes a knot."""
        self.recording = True
        self._rec = [(float(t), self.x, self.y)]

    def stop_recording(self) -> int:
        """Commit what was recorded. Returns the number of knots kept."""
        self.recording = False
        self.motion.record(self._rec)
        self._rec = []
        return len(self.motion.points)

    def trigger(self, t: float) -> None:
        """Restart the path — what a note-on does to a vector envelope."""
        self._origin = float(t)

    def tick(self, t: float) -> tuple[float, float]:
        """Advance to time ``t`` and return the position.

        ``manual`` leaves it where your hand put it. ``orbit`` runs the Lissajous shape.
        ``motion`` plays the recorded path on the clock — free-running or tempo-locked.
        """
        if self.mode == "orbit":
            self.x, self.y = self.orbit.at(t - self._origin)
        elif self.mode == "motion" and not self.motion.empty:
            self.x, self.y = self.motion.at(self.clock.cycles(t - self._origin))
        return (self.x, self.y)

    def moving(self) -> bool:
        """Whether :meth:`tick` will move on its own — what the bridge loop asks."""
        if self.mode == "orbit":
            return True
        return self.mode == "motion" and not self.motion.empty

    def values(self) -> dict[str, float]:
        return blend(self.corners, self.x, self.y)

    def paths(self) -> list[str]:
        """Every control any corner defines, sorted — what the surface can be drawn for."""
        seen: set[str] = set()
        for snap in self.corners.values():
            seen.update(snap)
        return sorted(seen)
