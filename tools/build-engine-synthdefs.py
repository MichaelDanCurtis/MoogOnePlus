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
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
