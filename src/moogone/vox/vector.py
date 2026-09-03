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


@dataclass
class VectorEngine:
    """Corners, a position, and an orbit. The bridge ticks it and writes what comes out."""

    corners: dict[str, dict[str, float]] = field(default_factory=lambda: {c: {} for c in CORNERS})
    x: float = 0.5
    y: float = 0.5
    orbit: Orbit = field(default_factory=Orbit)

    def set_corner(self, name: str, snapshot: dict[str, float]) -> None:
        if name not in CORNERS:
            raise ValueError(f"corner must be one of {', '.join(CORNERS)}; got {name!r}")
        self.corners[name] = {str(k): float(v) for k, v in snapshot.items()}

    def clear_corner(self, name: str) -> None:
        if name not in CORNERS:
            raise ValueError(f"corner must be one of {', '.join(CORNERS)}; got {name!r}")
        self.corners[name] = {}

    def move(self, x: float, y: float) -> None:
        self.x = min(1.0, max(0.0, float(x)))
        self.y = min(1.0, max(0.0, float(y)))

    def tick(self, t: float) -> tuple[float, float]:
        """Advance to time ``t``. Returns the position, moving it if the orbit is running."""
        if self.orbit.running:
            self.x, self.y = self.orbit.at(t)
        return (self.x, self.y)

    def values(self) -> dict[str, float]:
        return blend(self.corners, self.x, self.y)

    def paths(self) -> list[str]:
        """Every control any corner defines, sorted — what the surface can be drawn for."""
        seen: set[str] = set()
        for snap in self.corners.values():
            seen.update(snap)
        return sorted(seen)
