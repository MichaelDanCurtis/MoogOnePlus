"""Learn the instrument's parameter ids by watching it be played.

The voice engine addresses its parameters by 16-bit id, and nothing on the machine
publishes what those ids mean. But `las-frontend` announces every change on the
voice bus as `/x`, so moving a control tells you its id — the instrument teaches you
its own numbering, and the alternative is typing out a table you would have to guess
at first.

The whole design problem here is that **a control is never the only thing moving**.
Turning a knob emits a stream of writes for that parameter, while a note tail, an
LFO or a meter may emit a handful for others in the same window. So a learn pass
does not take "the parameter that appeared"; it ranks candidates by how much they
moved and how often, requires the winner to clear a margin over the runner-up, and
refuses rather than guessing when nothing stands out.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Confirmed against a known control: MIDI CC 7 drives it, 0..1 mapping to 0..127.
KNOWN: dict[int, str] = {358: "master volume"}

#: A candidate must move at least this far, and be seen at least this many times,
#: before it can win. One stray write during the window is not a knob turn.
MIN_SPAN = 0.02
MIN_COUNT = 3

#: And it must beat the runner-up by this factor, or the pass is ambiguous. Two
#: controls moving together should be reported, not silently resolved by a hair.
MARGIN = 2.0

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _\-/().]{0,63}$")


class LearnError(ValueError):
    """A learn pass or a map entry that cannot be accepted, and why."""


@dataclass
class Candidate:
    """One parameter's activity during a learn window."""

    param: int
    count: int = 0
    lo: float = float("inf")
    hi: float = float("-inf")
    first: float = 0.0
    last: float = 0.0

    def feed(self, value: float, when: float) -> None:
        if self.count == 0:
            self.first = when
        self.count += 1
        self.lo = min(self.lo, value)
        self.hi = max(self.hi, value)
        self.last = when

    @property
    def span(self) -> float:
        return 0.0 if self.count == 0 else self.hi - self.lo

    @property
    def score(self) -> float:
        """How much it moved, times how often. A sweep beats a single jump.

        A parameter that flips 0 to 1 once has a full span but almost no count; a
        knob being turned has both. Multiplying is what separates them.
        """
        return self.span * self.count

    def as_dict(self) -> dict:
        return {
            "param": self.param,
            "count": self.count,
            "lo": self.lo if self.count else 0.0,
            "hi": self.hi if self.count else 0.0,
            "span": self.span,
            "score": self.score,
        }


@dataclass
class Result:
    """What a learn pass concluded, including why it might have concluded nothing."""

    param: int | None
    candidates: list[Candidate]
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.param is not None

    def as_dict(self) -> dict:
        return {
            "param": self.param,
            "reason": self.reason,
            "candidates": [c.as_dict() for c in sorted(
                self.candidates, key=lambda c: -c.score)[:8]],
        }


class Learner:
    """One learn pass: begin, feed everything that arrives, finish."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._candidates: dict[int, Candidate] = {}
        self.active = False
        self.label = ""

    def begin(self, label: str) -> None:
        if not _SAFE_NAME.match(label or ""):
            raise LearnError(
                f"{label!r} is not a usable name: letters, digits, spaces and "
                "-_/(). , starting with a letter or digit, up to 64 characters"
            )
        self._candidates = {}
        self.label = label
        self.active = True

    def feed(self, param: int, value: float) -> None:
        if not self.active:
            return
        c = self._candidates.get(param)
        if c is None:
            c = self._candidates[param] = Candidate(param)
        c.feed(float(value), self._clock())

    def finish(self) -> Result:
        """End the pass and report. A pass is consumed: calling this twice does not
        re-report the first result, and writes fed after it are not retained."""
        self.active = False
        ranked = sorted(self._candidates.values(), key=lambda c: -c.score)
        self._candidates = {}
        viable = [c for c in ranked if c.span >= MIN_SPAN and c.count >= MIN_COUNT]
        if not viable:
            moved = "nothing moved" if not ranked else (
                f"nothing moved enough — best was param {ranked[0].param} "
                f"({ranked[0].count} writes, span {ranked[0].span:.3f})"
            )
            return Result(None, ranked, moved)
        best = viable[0]
        runner = viable[1] if len(viable) > 1 else None
        if runner is not None and best.score < runner.score * MARGIN:
            return Result(
                None,
                ranked,
                f"ambiguous — params {best.param} and {runner.param} moved together; "
                "move one control on its own",
            )
        return Result(best.param, ranked, "")


@dataclass
class ParamMap:
    """Names for parameter ids, learned or known."""

    names: dict[int, str] = field(default_factory=lambda: dict(KNOWN))

    def name_for(self, param: int) -> str:
        return self.names.get(param, f"param {param}")

    def learn(self, param: int, name: str) -> None:
        if not _SAFE_NAME.match(name or ""):
            raise LearnError(f"{name!r} is not a usable name")
        clash = next((p for p, n in self.names.items() if n == name and p != param), None)
        if clash is not None:
            raise LearnError(f"{name!r} is already param {clash}; pick another name")
        self.names[param] = name

    def forget(self, param: int) -> None:
        self.names.pop(param, None)

    def as_dict(self) -> dict:
        return {str(p): n for p, n in sorted(self.names.items())}

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=1))
        return path

    @classmethod
    def load(cls, path: Path) -> ParamMap:
        """Load, falling back to the known ids when the file is absent.

        A malformed file raises rather than silently starting empty: losing a learned
        map without being told is worse than being stopped.
        """
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise LearnError(f"{path} is not readable JSON: {exc}") from exc
        if not isinstance(raw, dict):
            raise LearnError(f"{path} should hold an object of id -> name")
        names = dict(KNOWN)
        for key, value in raw.items():
            try:
                names[int(key)] = str(value)
            except (TypeError, ValueError) as exc:
                raise LearnError(f"{key!r} is not a parameter id") from exc
        return cls(names)
