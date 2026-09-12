#!/usr/bin/env python3
"""Compile the Engine catalogue into .scsyndef bytes for moogd to embed.

The instrument cannot compile these. Its `sclang` runs with `-a` against a
195-file class library that has no class for `FreeVerb2` or `GVerb`, so those
UGens -- though loaded, registered and idle in the running server -- cannot be
named from the machine itself. See
`docs/firmware/gap-sc-ugen-plugin-inventory.md` section 5.2.

`scsynth` resolves UGens by name string when it receives a definition, so a
SynthDef compiled anywhere works as long as the names match. This compiles them
with a real sclang here and checks the names in, because a build step the
instrument cannot run is a build step that has to be reproducible by hand:

    python3 tools/build-engine-synthdefs.py

Nothing here writes the binary format. sclang does; this only asks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from moogone.synthdef import SynthDefError, available, compile_synthdef

CATALOGUE = ROOT / "moogd" / "engine" / "catalogue.json"
OUT = ROOT / "moogd" / "engine"

#: Definitions moogd uses itself, which are not effects and never appear in the
#: catalogue. The meter exists because of docs/INCIDENT-2026-09-12-runaway.md: a
#: sound that would not stop was diagnosed through four theories, three of them
#: wrong, while the signal itself sat observable inside the server the whole
#: time. Every voice on this instrument passes through scsynth on its way out --
#: the analog ones arrive on bus 12 from the ADC -- so the main pair is the one
#: place that sees everything.
#:
#: Two time constants, deliberately. The fast one is a meter. The slow one has a
#: three-second release, so a level that is *growing* separates visibly from one
#: that is merely loud, which is the question that took an evening to answer.
INTERNAL = {
    # A recorder on the main pair. Note the two In.ar calls: the main outputs
    # are buses 7 and 0, which are NOT consecutive, so the older
    # `In.ar(bus, 2)` recorder in src/moogone/synthdef.py has always captured
    # main-right and SUB-right instead. Commit 9c62c1d fixed that same mistake
    # in three other modules and missed the recorder.
    "voxRecorder": (
        "|buf = 0, left = 7, right = 0| "
        "DiskOut.ar(buf, [In.ar(left, 1), In.ar(right, 1)])"
    ),
    # Meter SIXTEEN output buses at once. Buses 7 and 0 are the main pair, but
    # on 2026-09-13 the operator reported hearing "strong effects" while a meter
    # on that pair read -86 dB. Either the sound leaves by another output or the
    # main pair is not the whole story, and guessing which is how the last three
    # theories went wrong. This looks at all of them.
    "voxScan": (
        "|out = 14100| "
        "Out.kr(out, (0..15).collect { |i| Amplitude.kr(In.ar(i, 1), 0.01, 0.3) })"
    ),
    "voxMeter": (
        "|left = 7, right = 0, out = 14000| "
        "var l = In.ar(left, 1); var r = In.ar(right, 1); "
        "Out.kr(out, ["
        "Amplitude.kr(l, 0.01, 0.3), Amplitude.kr(r, 0.01, 0.3), "
        "Amplitude.kr(l, 0.01, 3.0), Amplitude.kr(r, 0.01, 3.0)])"
    ),
}


def main() -> int:
    if not available():
        print("no sclang found; install SuperCollider to rebuild these",
              file=sys.stderr)
        return 2
    cat = json.loads(CATALOGUE.read_text())
    failed = 0
    for e in cat["effects"]:
        name, graph = e["name"], e["graph"]
        try:
            blob = compile_synthdef(name, graph)
        except SynthDefError as exc:
            print(f"{name}: FAILED\n{exc}", file=sys.stderr)
            failed += 1
            continue
        # The server looks the UGen up by this exact string, so a definition
        # that does not contain it would fail on the instrument rather than
        # here -- check now, where the error is readable.
        if e["ugen"].encode() not in blob:
            print(f"{name}: compiled, but {e['ugen']!r} is not in the bytes",
                  file=sys.stderr)
            failed += 1
            continue
        path = OUT / f"{name}.scsyndef"
        path.write_bytes(blob)
        print(f"{name:16s} {len(blob):6d} bytes  -> {path.relative_to(ROOT)}")

    for name, graph in sorted(INTERNAL.items()):
        try:
            blob = compile_synthdef(name, graph)
        except SynthDefError as exc:
            print(f"{name}: FAILED\n{exc}", file=sys.stderr)
            failed += 1
            continue
        path = OUT / f"{name}.scsyndef"
        path.write_bytes(blob)
        print(f"{name:16s} {len(blob):6d} bytes  -> {path.relative_to(ROOT)}  (internal)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
