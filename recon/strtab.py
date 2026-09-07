"""What is known about the controller firmware's compressed address table.

Not a decompressor. This is the analysis harness and the ground truth, written down
so the next attempt starts where this one stopped rather than at the beginning.

WHAT IS ESTABLISHED

1. The image is bit-reversed per byte. Undo that first or the table is invisible --
   `/hw/cvout/0` does not appear in the raw file and does at 0x2A2F7 decoded.

2. It is a back-reference scheme, not a dictionary and not front coding. The proof
   is that the output contains strings the input does not:

       "Not found"  and  "found"     appear ZERO times in the whole image
       "able"                        appears exactly ONCE, at 0x29DCE, and only as
                                     the tail of `note-enable`

   The controller answers `/status` queries with `404 Not found` and
   `503 Unavailable`, so both strings exist at runtime and must be built by copying
   from elsewhere in the table.

3. Three token markers, and their widths are settled. The byte after a marker is a
   marker only 0.5% of the time, so it is always an operand:

       0xAD   3 bytes (two operands)   404 occurrences
       0xB5   2 bytes (one operand)    554
       0xDF   2 bytes (one operand)    186

   43% of the region is printable; 73% if the high bit is stripped, but stripping
   does not yield text, so the high bit is not a simple terminator flag.

4. The ground truth, from the status table at 0x2A0BD. Each literal run stops short
   and a token completes it:

       "404\\0Not foun"        + AD 11 59  ->  "d\\0"
       "400\\0Malformed messag" + AD 10 5b  ->  "e\\0"
       "503\\0Unavail"          + AD 22 5b  ->  "able\\0"

   Completions of 2, 2 and 5 bytes with no consistent length field in the operands,
   which is the signature of copy-until-NUL rather than an explicit length.

WHAT IS NOT SOLVED

`AD` alone can be made to work: `dist = ((A & 0x1F) << 5) | (B >> 3)` with
copy-until-NUL reconstructs `404\\0Not found` exactly, and a nibble-packed short
match for the other two reconstructs `Malformed message`. **No single parameter set
has produced more than one of the three.** Recovering one ground-truth string under
one set and a different one under another is the shape of overfitting, not of a
solved format.

`B5` and `DF` are the open part. They are not back-references with small distances
-- that produces runaway repeats ("dhordhordhord", "yyyyyy"), which is what a
distance of 1 or 2 looks like. They are not front coding either, tested directly.
`B5` is the most common token, roughly one per entry, and its operand is below 0x20
in 391 of 554 cases.

WHY IT IS WORTH FINISHING

The table holds the 464 unmapped `/p` addresses, `/v2/nw`, and the rest of the
controller's namespace. And there is an oracle: any candidate address can be put to
the instrument, which answers `404 Not found` for one that does not exist and
something else for one that does. See `recon/cvout.py`.

    uv run python3 recon/strtab.py --image captures/harvest/xmosfw/app_las_v2.1.2.bin
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re

BITREV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
NIBSWAP = bytes(((i & 0x0F) << 4) | (i >> 4) for i in range(256))

#: Cluster A, where the status table and most of the `/hw/` leaves live.
CLUSTER_A = (0x298A0, 0x2ACE0)
MARKERS = (0xAD, 0xB5, 0xDF)

#: Strings the firmware demonstrably produces. The first two appear nowhere in the
#: image, so a decode that yields them is doing real work; the third's source is the
#: single occurrence of "able" at 0x29DCE.
GROUND_TRUTH = (b"Not found", b"Malformed message", b"Unavailable")


def load(path: pathlib.Path) -> bytes:
    raw = path.read_bytes()
    return raw.translate(NIBSWAP if "vx" in path.name else BITREV)


def report(data: bytes) -> None:
    lo, hi = CLUSTER_A
    region = data[lo:hi]
    print(f"image {len(data)} bytes; cluster A {hi - lo} bytes")

    printable = sum(1 for b in region if 0x20 <= b <= 0x7E)
    print(f"  printable {printable / len(region):.0%}")

    counts = collections.Counter(b for b in region if b in MARKERS)
    for m in MARKERS:
        follows = sum(1 for i, b in enumerate(region[:-1]) if b == m and region[i + 1] in MARKERS)
        print(f"  0x{m:02X}  {counts[m]:4d} occurrences, operand is a marker {follows} times")

    print("\n  strings the image does NOT contain (so they are built by reference):")
    for needle in (b"Not found", b"found", b"able\x00"):
        print(f"    {needle!r:16} {len(re.findall(re.escape(needle), data))} hits")
    print("  and the one it does, exactly once:")
    for m in re.finditer(rb"able", data):
        ctx = data[max(0, m.start() - 12) : m.start() + 6]
        print(f"    0x{m.start():06X}  ...{ctx.decode('ascii', 'replace')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", type=pathlib.Path,
                    default=pathlib.Path("captures/harvest/xmosfw/app_las_v2.1.2.bin"))
    args = ap.parse_args()
    report(load(args.image))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
