#!/usr/bin/env python3
"""Predict the bytes the voice controller should receive for a given preset.

The matrix wire format was read off the link on 2026-09-10 (see
docs/arch/modmatrix-wire-format.md). A format that has been *read* can be used
to make a falsifiable prediction, which is a stronger test than decoding
whatever turns up: this renders a preset's stored matrix into the 16-byte slots
the XMOS should receive, so a capture taken while that preset loads either
matches or refutes it.

    python3 tools/predict-matrix-blob.py "SLOWLY DEPARTING FILM SCORE"
    python3 tools/predict-matrix-blob.py --list

Presets are read from the library database, not from .m1p files -- the
instrument keeps them in SQLite and has no .m1p on disk at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "captures" / "MOOG ONE.db"
SLOT_TOKENS = 7
SLOT_BYTES = 16
DEST_NONE = {137, 141}


def slots_of(data: str) -> dict[str, list[float]]:
    """Every matrix line in a preset, keyed by its address."""
    out: dict[str, list[float]] = {}
    for line in data.splitlines():
        if "matrix_expression_slots" not in line:
            continue
        sp = line.find(" ")
        if sp < 0:
            continue
        try:
            toks = json.loads(line[sp + 1 :].strip())
        except json.JSONDecodeError:
            continue
        # A malformed row count would silently reframe every later slot, so a
        # line that is not a whole number of rows is dropped rather than padded.
        if isinstance(toks, list) and toks and len(toks) % SLOT_TOKENS == 0:
            out[line[:sp]] = toks
    return out


def encode(tokens: list[float]) -> bytes:
    """Render the preset's token array as the voice controller receives it.

    Ids are single bytes; amounts are float32 **little-endian** inside what is
    otherwise a big-endian protocol. See the module docstring's reference.
    """
    out = bytearray()
    for i in range(0, len(tokens), SLOT_TOKENS):
        row = tokens[i : i + SLOT_TOKENS]
        for col in (0, 2, 4):
            out.append(int(row[col]) & 0xFF)
            out += struct.pack("<f", row[col + 1])
        out.append(int(row[6]) & 0xFF)
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("preset", nargs="?")
    ap.add_argument("--list", action="store_true", help="presets that carry a matrix")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()

    if not Path(args.db).exists():
        print(f"no library at {args.db} (it is gitignored)", file=sys.stderr)
        return 2
    db = sqlite3.connect(args.db)

    if args.list:
        found = []
        for name, data in db.execute("select name,data from presets"):
            s = slots_of(data)
            if s:
                found.append((max(len(v) // SLOT_TOKENS for v in s.values()), name))
        for n, name in sorted(found, reverse=True):
            print(f"{n:3d} slots  {name}")
        return 0

    if not args.preset:
        ap.error("name a preset, or pass --list")

    row = db.execute(
        "select data from presets where name = ?", (args.preset,)
    ).fetchone()
    if not row:
        print(f"no preset named {args.preset!r}", file=sys.stderr)
        return 1

    for addr, toks in sorted(slots_of(row[0]).items()):
        timbre = addr.split("/t/")[1].split("/")[0]
        blob = encode(toks)
        routed = sum(
            1
            for i in range(0, len(toks), SLOT_TOKENS)
            if int(toks[i + 6]) not in DEST_NONE
        )
        print(f"timbre {timbre} -> /g/{timbre}/t/e/s")
        print(f"  {len(blob)//SLOT_BYTES} slots, {routed} routed, {len(blob)} bytes")
        print(f"  md5 {hashlib.md5(blob).hexdigest()}")
        print(f"  head {blob[:SLOT_BYTES].hex()}")
        print(f"  tail {blob[-SLOT_BYTES:].hex()}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
