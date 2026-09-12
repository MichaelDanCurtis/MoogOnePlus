"""The main outputs are buses 7 and 0, and they are not adjacent.

`synthdefs.scd:564-565` writes:

    Out.ar(7, main[0] * -1);   // left
    Out.ar(0, main[1] * -1);   // right

so a single `In.ar(bus, 2)` reads buses 0 and 1 -- main-RIGHT and SUB-right --
and silently records or processes the wrong signal. This project has made that
exact mistake in four separate files: sampler.py, fm.py and makeup.py (fixed in
9c62c1d) and the recorder (fixed 2026-09-13, after every "main output"
recording ever taken turned out to be of the wrong pair).

These tests exist so there is not a fifth.
"""

from __future__ import annotations

import re
from pathlib import Path

from moogone.effect import MAIN_LEFT, MAIN_RIGHT
from moogone.synthdef import RECORDER

SRC = Path(__file__).resolve().parent.parent / "src" / "moogone"


def test_the_pair_is_seven_and_zero():
    assert (MAIN_LEFT, MAIN_RIGHT) == (7, 0)


def test_every_module_agrees_on_the_pair():
    """One definition, re-exported. Four copies is how the bug spread."""
    from moogone import fm, makeup, record, sampler

    for mod in (fm, sampler, makeup, record):
        assert mod.MAIN_LEFT == 7, f"{mod.__name__} disagrees about left"
        assert mod.MAIN_RIGHT == 0, f"{mod.__name__} disagrees about right"


def test_recorder_reads_both_buses_separately():
    """A single In.ar cannot express a non-adjacent pair."""
    assert "In.ar(left, 1)" in RECORDER
    assert "In.ar(right, 1)" in RECORDER
    assert "In.ar(bus, 2)" not in RECORDER


def test_no_graph_reads_a_MAIN_bus_as_a_consecutive_pair():
    """`In.ar(x, 2)` is only a bug when x is a MAIN bus.

    Reading two consecutive buses is correct and common -- the effect monitor
    reads 100/101 and 102/103, which really are adjacent. What is never correct
    is doing it to bus 7 or bus 0, because the main pair straddles the whole
    output block. So this checks the argument's DEFAULT in the graph's own
    parameter list, and only complains when a main bus is read two-wide.

    It walks the AST and looks at string literals assigned to a name -- the
    graphs. Comments and docstrings are skipped: several of them quote the
    broken form while explaining it, and a checker that cannot tell a bug from
    its own postmortem is one nobody keeps.
    """
    import ast

    read2 = re.compile(r"In\.ar\(\s*(\w+)\s*,\s*2\s*\)")
    offenders = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for sub in ast.walk(node.value):
                if not (isinstance(sub, ast.Constant) and isinstance(sub.value, str)):
                    continue
                graph = sub.value
                args = {}
                if (head := re.match(r"\s*\|([^|]*)\|", graph)) is not None:
                    for part in head.group(1).split(","):
                        if "=" in part:
                            k, v = part.split("=", 1)
                            args[k.strip()] = v.strip()
                for m in read2.finditer(graph):
                    if args.get(m.group(1)) in {"0", "7"}:
                        offenders.append(
                            f"{path.relative_to(SRC)}:{node.lineno}: "
                            f"{m.group(0)} with {m.group(1)} defaulting to "
                            f"{args[m.group(1)]}"
                        )
    assert not offenders, (
        "these read a MAIN bus as two consecutive channels; the pair is 7 and 0:\n  "
        + "\n  ".join(sorted(set(offenders)))
    )
