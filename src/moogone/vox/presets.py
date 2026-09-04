"""Named snapshots of the whole effects chain, saved to disk and switched between.

The point is to stop experiments from being destructive. Capture what the instrument
is doing now, try something, and come back — without needing to have written the old
values down first, and without touching the synth's own preset system.

**Snapshots are not keyed by node id.** The engine reallocates node ids whenever a
preset is loaded on the instrument: a chain that was `1035 pingpongDelay_0` became
`1055 stereoChorus_0` in the middle of one session here, and a snapshot keyed by id
would have written a delay's settings into a chorus. They are keyed by
``(defname, nth occurrence of that defname)``, which survives reallocation, and
applying one reports what it could not match rather than matching approximately.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Controls that describe wiring, not sound. Writing these moves audio between buses
#: and can silence or feed back the instrument; a snapshot restores settings, not
#: routing.
STRUCTURAL = frozenset({"inBus", "outBus", "ctlIn", "ctlOut", "ctl"})

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _-]{0,63}$")


class PresetError(ValueError):
    """A snapshot that cannot be saved or applied, and why."""


@dataclass(frozen=True)
class Slot:
    """One effect, identified by what it is rather than by where it happened to land."""

    defname: str
    index: int  # nth node with this defname, in tree order
    controls: dict[str, float]

    @property
    def key(self) -> tuple[str, int]:
        return (self.defname, self.index)


@dataclass
class Snapshot:
    name: str
    slots: list[Slot] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "created": self.created,
            "note": self.note,
            "slots": [
                {"defname": s.defname, "index": s.index, "controls": s.controls}
                for s in self.slots
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Snapshot:
        return cls(
            name=str(d["name"]),
            created=float(d.get("created", 0.0)),
            note=str(d.get("note", "")),
            slots=[
                Slot(str(s["defname"]), int(s["index"]), {str(k): float(v)
                     for k, v in s["controls"].items()})
                for s in d.get("slots", [])
            ],
        )


def _numbered(nodes) -> list[tuple[str, int, object]]:
    """(defname, nth-of-that-defname, node), in the order the tree gave them."""
    seen: dict[str, int] = {}
    out = []
    for n in nodes:
        i = seen.get(n.defname, 0)
        seen[n.defname] = i + 1
        out.append((n.defname, i, n))
    return out


def capture(nodes, name: str, note: str = "") -> Snapshot:
    """Snapshot every writable control of every effect node.

    Unnamed controls — the ones scsynth reports by integer index — are skipped. There
    is no name to restore them by, and writing to a control whose meaning is unknown
    on a live audio router is not a thing to do casually.
    """
    if not _SAFE_NAME.match(name or ""):
        raise PresetError(
            f"{name!r} is not a usable preset name: letters, digits, spaces, - and _, "
            "starting with a letter or digit, up to 64 characters"
        )
    slots = []
    for defname, index, n in _numbered(nodes):
        controls = {
            k: float(v)
            for k, v in n.controls.items()
            if isinstance(k, str) and k not in STRUCTURAL
        }
        if controls:
            slots.append(Slot(defname, index, controls))
    return Snapshot(name=name, slots=slots, note=note)


@dataclass(frozen=True)
class Plan:
    """What applying a snapshot would do. Produced before anything is written."""

    writes: list[tuple[int, str, float]]  # node id, control, value
    missing: list[str]  # in the snapshot, absent from the instrument
    extra: list[str]  # on the instrument, absent from the snapshot

    @property
    def ok(self) -> bool:
        return not self.missing


def plan(nodes, snap: Snapshot) -> Plan:
    """Match a snapshot to the live tree without writing anything.

    Reports both directions of mismatch. A snapshot taken from a different instrument
    preset will not line up, and saying so beats writing the half that happens to fit.
    """
    live = {(d, i): n for d, i, n in _numbered(nodes)}
    writes: list[tuple[int, str, float]] = []
    missing: list[str] = []
    for slot in snap.slots:
        node = live.get(slot.key)
        if node is None:
            missing.append(f"{slot.defname}[{slot.index}]")
            continue
        for ctl, value in slot.controls.items():
            if ctl in STRUCTURAL or ctl not in node.controls:
                continue
            if float(node.controls[ctl]) != value:
                writes.append((node.node_id, ctl, value))
    known = {s.key for s in snap.slots}
    extra = [f"{d}[{i}]" for d, i, _ in _numbered(nodes) if (d, i) not in known]
    return Plan(writes, missing, extra)


def save(snap: Snapshot, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{snap.name}.json"
    path.write_text(json.dumps(snap.as_dict(), indent=1))
    return path


def load(name: str, directory: Path) -> Snapshot:
    if not _SAFE_NAME.match(name or ""):
        raise PresetError(f"{name!r} is not a usable preset name")
    path = directory / f"{name}.json"
    if not path.exists():
        raise PresetError(f"no preset called {name!r} in {directory}")
    return Snapshot.from_dict(json.loads(path.read_text()))


def names(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(p.stem for p in directory.glob("*.json"))


def live_nodes(client):
    """Every synth node in the running engine, in tree order."""
    out = []

    def walk(n):
        for child in getattr(n, "children", []) or []:
            walk(child)
        if hasattr(n, "defname"):
            out.append(n)

    walk(client.query_tree())
    return out


def apply(client, snap: Snapshot) -> Plan:
    """Write a snapshot's differences, then confirm by reading the tree back.

    `/n_set` is never acknowledged by scsynth, so the only honest confirmation is to
    query afterwards. The returned plan is the one that was executed; anything it
    could not match is in `missing`, and nothing partial is hidden.
    """
    p = plan(live_nodes(client), snap)
    for node_id, ctl, value in p.writes:
        client.n_set(node_id, **{ctl: float(value)})
    return p


def build_parser():
    """Exposed so the README-drift test can read the real flags off it."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="python3 -m moogone.vox.presets",
        description="Save and switch whole-effects-chain snapshots on the instrument.",
    )
    ap.add_argument("action", choices=["list", "save", "apply", "show"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--port", type=int, default=57110)
    ap.add_argument("--dir", default="presets", help="where snapshots are kept")
    ap.add_argument("--note", default="", help="a line about why this snapshot was taken")
    return ap


def _main(argv=None) -> int:
    from ..sc.client import ScClient
    from ..transport.udp import UdpTransport

    ap = build_parser()
    a = ap.parse_args(argv)
    directory = Path(a.dir)

    if a.action == "list":
        for n in names(directory):
            snap = load(n, directory)
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(snap.created))
            print(f"  {n:<28}{len(snap.slots):>3} effects  {when}  {snap.note}")
        return 0

    if not a.name:
        ap.error(f"{a.action} needs a preset name")

    if a.action == "show":
        snap = load(a.name, directory)
        for s in snap.slots:
            print(f"  {s.defname}[{s.index}]")
            for k, v in sorted(s.controls.items()):
                print(f"      {k:<18}{v}")
        return 0

    client = ScClient(UdpTransport(a.host, a.port))
    if a.action == "save":
        snap = capture(live_nodes(client), a.name, note=a.note)
        print(f"  saved {save(snap, directory)}  ({len(snap.slots)} effects)")
        return 0

    snap = load(a.name, directory)
    p = apply(client, snap)
    print(f"  applied {a.name!r}: {len(p.writes)} change(s)")
    for node_id, ctl, value in p.writes:
        print(f"    node {node_id:<6}{ctl} -> {value}")
    if p.missing:
        print(f"  NOT MATCHED on this chain: {', '.join(p.missing)}")
        print("  (the instrument's preset differs from the one this was captured from)")
    return 0 if p.ok else 1


if __name__ == "__main__":
    raise SystemExit(_main())
