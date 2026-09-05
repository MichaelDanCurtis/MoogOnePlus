"""Read the instrument's preset library.

Every preset in a Moog One user space is a flat list of `/p/...` paths and values —
the `/p` namespace an earlier address sweep found and could not read. A factory bank
holds 398 of them, up to about 900 KB each, tagged and arranged into sets.

This reads that library **read-only**, over a copy. Nothing here writes to a database
the instrument is using, and nothing here reproduces preset content: it reads what
you own so you can search it, compare two patches, and see what a sound is actually
made of.

The value format is the firmware's own: a path, a space, then a number, a bare
`true`/`false`, or a quoted string.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

#: `/p/part/t/1/p/fa/p 0.5` — path, space, value. Values are numbers, booleans or
#: quoted strings; anything else is left as text rather than guessed at.
_LINE = re.compile(r"^(/[^\s]+)\s+(.*)$")


class LibraryError(RuntimeError):
    """A library that cannot be read, and why."""


@dataclass(frozen=True)
class PresetInfo:
    name: str
    comment: str
    synths: tuple[str, str, str]
    size: int
    tags: tuple[str, ...] = ()

    @property
    def is_multi(self) -> bool:
        """Whether it uses more than one timbre — a layered or split sound."""
        return sum(1 for s in self.synths if s) > 1


def parse_value(text: str):
    """One value, in the firmware's own spelling."""
    t = text.strip()
    if t == "true":
        return True
    if t == "false":
        return False
    if t == "null":
        return None
    if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
        return t[1:-1]
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        return t


def parse_preset(data: str) -> dict[str, object]:
    """The whole flat parameter list, as a dict of path to value.

    Lines that do not match are skipped rather than raising: a library is 398 presets
    written by several firmware versions, and one unfamiliar line should not cost the
    other three thousand.
    """
    out: dict[str, object] = {}
    for line in data.splitlines():
        m = _LINE.match(line.strip())
        if m:
            out[m.group(1)] = parse_value(m.group(2))
    return out


class Library:
    """A preset database, opened read-only."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise LibraryError(f"no such library: {self.path}")
        try:
            # Immutable, not merely read-only: this may be a copy of a file the
            # instrument still has open, and we must never write a journal beside it.
            self._db = sqlite3.connect(f"file:{self.path}?immutable=1", uri=True)
        except sqlite3.Error as exc:
            raise LibraryError(f"{self.path.name} will not open: {exc}") from exc
        self._db.row_factory = sqlite3.Row

    def close(self) -> None:
        self._db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def names(self) -> list[str]:
        return [r["name"] for r in self._db.execute(
            "select name from presets order by name collate nocase")]

    def tags_for(self) -> dict[str, list[str]]:
        """Preset name to its tag names, for the whole library in one pass."""
        out: dict[str, list[str]] = {}
        try:
            rows = self._db.execute(
                "select p.name as preset, t.name as tag from preset_tags pt "
                "join presets p on p.id = pt.presetId join tags t on t.id = pt.tagId"
            )
        except sqlite3.Error:
            return out
        for r in rows:
            out.setdefault(r["preset"], []).append(r["tag"])
        return out

    def catalogue(self) -> list[PresetInfo]:
        tags = self.tags_for()
        rows = self._db.execute(
            "select name, comment, synth1Name, synth2Name, synth3Name, length(data) as n "
            "from presets order by name collate nocase"
        )
        return [
            PresetInfo(
                name=r["name"] or "",
                comment=r["comment"] or "",
                synths=(r["synth1Name"] or "", r["synth2Name"] or "", r["synth3Name"] or ""),
                size=int(r["n"] or 0),
                tags=tuple(sorted(tags.get(r["name"], ()))),
            )
            for r in rows
        ]

    def parameters(self, name: str) -> dict[str, object]:
        row = self._db.execute(
            "select data from presets where name = ?", (name,)).fetchone()
        if row is None:
            raise LibraryError(f"no preset called {name!r} in {self.path.name}")
        return parse_preset(row["data"])


def diff(a: dict[str, object], b: dict[str, object]) -> dict[str, tuple[object, object]]:
    """Paths where two presets disagree, each mapped to (a's value, b's value).

    A path present in only one side appears with `None` for the other, so a preset
    from a different firmware version reads as additions rather than as an error.
    """
    out: dict[str, tuple[object, object]] = {}
    for key in set(a) | set(b):
        left, right = a.get(key), b.get(key)
        if left != right:
            out[key] = (left, right)
    return out


def summarise(params: dict[str, object], timbre: int = 1) -> dict[str, object]:
    """The handful of values that say what a sound is, for a listing.

    Chosen from the panel catalogue rather than at random: the two filter cutoffs,
    their resonances, and the amplifier envelope, which between them account for most
    of what a patch sounds like before anything is played.
    """
    prefix = f"/p/part/t/{timbre}/p"
    wanted = {
        "svf cutoff": f"{prefix}/fa/p", "svf resonance": f"{prefix}/fa/r",
        "ladder cutoff": f"{prefix}/fb/p", "ladder resonance": f"{prefix}/fb/r",
        "amp attack": f"{prefix}/e2/a", "amp decay": f"{prefix}/e2/d",
        "amp sustain": f"{prefix}/e2/s", "amp release": f"{prefix}/e2/r",
    }
    return {label: params.get(path) for label, path in wanted.items()
            if path in params}
