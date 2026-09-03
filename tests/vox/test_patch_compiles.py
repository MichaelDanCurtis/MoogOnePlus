"""Compile the patcher's output with a real SuperCollider.

Every other test in this repository checks that the generated source is what we
*intended* to generate. This one checks it is SuperCollider — the difference the
project has been unable to test since the patcher was written, because there was no
compiler on the machine to check against.

Skipped, not failed, where sclang is absent: CI should not need SuperCollider
installed, and a skip that says why is honest where a silent pass is not.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from moogone.vox.patch import ALL_CHANNELS, Cable, Node, Patch, to_source, validate

_MAC = Path("/Applications/SuperCollider.app/Contents/MacOS/sclang")
SCLANG = str(_MAC) if _MAC.exists() else shutil.which("sclang")

needs_sclang = pytest.mark.skipif(SCLANG is None, reason="no sclang on this machine")


def compile_with_sclang(source: str, timeout: float = 90.0) -> int:
    """Build the SynthDef in sclang and return its compiled size in bytes.

    `.add` only registers a definition; `.asBytes` forces the graph to be built, which
    is where a rate error, a bad input or a wrong arity actually surfaces.
    """
    body = re.sub(r"^//.*$", "", source, flags=re.MULTILINE).strip().replace(").add;", ");")
    script = (
        "(\nvar def, bytes;\ntry {\n    def = "
        + body
        + '\n    bytes = def.asBytes;\n    ("VOX_OK " ++ bytes.size).postln;\n'
        + '} { |e| ("VOX_FAIL " ++ e.errorString).postln };\n0.exit;\n)\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        scd = Path(tmp) / "probe.scd"
        scd.write_text(script)
        try:
            out = subprocess.run(
                [SCLANG, str(scd)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,  # a rejected SynthDef is a result to read, not a crash
            ).stdout
        except subprocess.TimeoutExpired:  # pragma: no cover - a hung interpreter
            pytest.fail("sclang did not exit; the generated source may not parse")
    ok = re.search(r"VOX_OK (\d+)", out)
    if ok:
        return int(ok.group(1))
    fail = re.search(r"VOX_FAIL (.*)", out)
    raise AssertionError(f"sclang rejected the generated source: {fail.group(1) if fail else out}")


def ladder_patch() -> Patch:
    """The patcher's own example: the graph the UI's 'Load example' button builds."""
    return Patch(
        name="voxLadderSpace",
        nodes=[
            Node("cut", "control", rate="control", name="cutoff", default=900.0),
            Node("lfo", "LFNoise1", rate="control", params={"freq": 0.3}),
            Node("dep", "op.mul", rate="control", params={"b": 400.0}),
            Node("sum", "op.add", rate="control"),
            Node("o1", "Saw", params={"freq": 55.0}),
            Node("o2", "Saw", params={"freq": 110.0}),
            Node("mix", "op.add"),
            Node("filt", "MoogFF", params={"gain": 2.2}),
            Node("dly", "CombC", params={"delaytime": 0.375, "decaytime": 3.0}),
            Node("wet", "op.add"),
            Node("pan", "Pan2", params={"pos": 0.0}),
            Node("out", "Out", params={"bus": 0.0}),
        ],
        cables=[
            Cable("lfo", "dep", "a"),
            Cable("dep", "sum", "a"),
            Cable("cut", "sum", "b"),
            Cable("o1", "mix", "a"),
            Cable("o2", "mix", "b"),
            Cable("mix", "filt", "in"),
            Cable("sum", "filt", "freq"),
            Cable("filt", "dly", "in"),
            Cable("filt", "wet", "a"),
            Cable("dly", "wet", "b"),
            Cable("wet", "pan", "in"),
            Cable("pan", "out", "channelsArray", outlet=ALL_CHANNELS),
        ],
    )


@needs_sclang
def test_the_example_patch_compiles():
    p = ladder_patch()
    assert validate(p) == []
    assert compile_with_sclang(to_source(p)) > 0


@needs_sclang
def test_a_control_rate_only_graph_compiles():
    # kr throughout, into a control bus: the rate rules have to hold on their own.
    p = Patch(
        name="voxKrOnly",
        nodes=[
            Node("l", "LFTri", rate="control", params={"freq": 0.5}),
            Node("g", "op.mul", rate="control", params={"b": 0.25}),
            Node("o", "Out", rate="control", params={"bus": 0.0}),
        ],
        cables=[Cable("l", "g", "a"), Cable("g", "o", "channelsArray")],
    )
    assert validate(p) == []
    assert compile_with_sclang(to_source(p)) > 0


@needs_sclang
@pytest.mark.parametrize("kind", ["SinOsc", "Saw", "Pulse", "WhiteNoise", "LFNoise1", "Dust"])
def test_every_source_ugen_compiles_into_out(kind):
    """Each catalogue source, wired for real. A wrong port name only shows up here."""
    p = Patch(
        name="voxSrc",
        nodes=[Node("s", kind), Node("p", "Pan2"), Node("o", "Out")],
        cables=[
            Cable("s", "p", "in"),
            Cable("p", "o", "channelsArray", outlet=ALL_CHANNELS),
        ],
    )
    assert validate(p) == []
    assert compile_with_sclang(to_source(p)) > 0
