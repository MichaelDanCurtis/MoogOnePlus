"""Source → destination routing: the patch bay behind the cables.

Sources are string keys with values in 0..1 (bend arrives −1..1 and is remapped by the
caller). Each route scales into ``[lo, hi]`` through a curve, optionally inverted and
slewed. :meth:`Router.tick` returns only the writes whose value **changed**, and never
more than one write per destination per ``min_interval`` — coalescing to the latest.
Without both rules a 200 Hz tick would hammer scsynth with identical ``/n_set``s.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

CURVES = {
    "lin": lambda x: x,
    "exp": lambda x: x * x * x,
    "log": lambda x: 1.0 - (1.0 - x) ** 3,
    "s": lambda x: x * x * (3.0 - 2.0 * x),
}

_NEG_INF = float("-inf")
_EPS = 1e-9


@dataclass
class Route:
    id: str
    src: str
    dst: str
    lo: float = 0.0
    hi: float = 1.0
    curve: str = "lin"
    slew: float = 0.0  # seconds to traverse the full [lo, hi] span; 0 = immediate
    invert: bool = False

    def __post_init__(self) -> None:
        if self.curve not in CURVES:
            raise ValueError(f"curve must be one of {', '.join(CURVES)}; got {self.curve!r}")


_ids = itertools.count(1)


class Router:
    def __init__(self, min_interval: float = 0.02):
        self.min_interval = min_interval
        self._routes: dict[str, Route] = {}
        self._slewed: dict[str, float] = {}  # route id -> last slewed output
        self._dst_last_time: dict[str, float] = {}
        self._dst_last_value: dict[str, float] = {}
        self._dst_pending: dict[str, float] = {}

    def add(self, route: Route) -> str:
        if not route.id:
            route.id = f"r{next(_ids)}"
        self._routes[route.id] = route
        return route.id

    def remove(self, route_id: str) -> bool:
        if route_id not in self._routes:
            return False
        del self._routes[route_id]
        self._slewed.pop(route_id, None)
        return True

    def routes(self) -> list[Route]:
        return list(self._routes.values())

    def tick(self, sources: dict[str, float], dt: float, now: float) -> list[tuple[str, float]]:
        targets: dict[str, float] = {}
        for rid, r in self._routes.items():
            if r.src not in sources:
                continue
            x = min(1.0, max(0.0, float(sources[r.src])))
            if r.invert:
                x = 1.0 - x
            y = r.lo + (r.hi - r.lo) * CURVES[r.curve](x)
            if r.slew > 0:
                current = self._slewed.get(rid, r.lo)  # a fresh slewed route starts at lo
                max_step = abs(r.hi - r.lo) * dt / r.slew
                y = current + max(-max_step, min(max_step, y - current))
                self._slewed[rid] = y
            targets[r.dst] = y

        writes: list[tuple[str, float]] = []
        for dst, y in targets.items():
            if now - self._dst_last_time.get(dst, _NEG_INF) < self.min_interval:
                self._dst_pending[dst] = y  # inside the window: hold, latest wins
                continue
            last = self._dst_last_value.get(dst)
            if last is not None and abs(y - last) < _EPS:
                self._dst_pending.pop(dst, None)
                continue
            self._emit(writes, dst, y, now)

        # Anything held earlier whose window has expired, and that this tick did not
        # re-target, still needs to land — otherwise the last gesture value is lost.
        for dst, y in list(self._dst_pending.items()):
            if dst in targets:
                continue
            if now - self._dst_last_time.get(dst, _NEG_INF) >= self.min_interval:
                self._emit(writes, dst, y, now)
        return writes

    def _emit(self, writes: list[tuple[str, float]], dst: str, y: float, now: float) -> None:
        writes.append((dst, y))
        self._dst_last_time[dst] = now
        self._dst_last_value[dst] = y
        self._dst_pending.pop(dst, None)
