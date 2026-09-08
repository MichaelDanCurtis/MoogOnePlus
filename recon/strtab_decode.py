#!/usr/bin/env python3
"""The XMOS string-table encoding: what it is, what is proved, what is still open.

This supersedes `recon/strtab.py`, which framed the problem around three magic
marker bytes in one region of one image. That framing was too narrow. The marker
bytes are not magic and there are more than three of them; the same encoding is
used in five separate regions across both firmware images, and one table is
encoded *twice* in the controller image, which is what finally pins the scheme
down as LZ77.

    uv run python3 recon/strtab_decode.py --report
    uv run python3 recon/strtab_decode.py --fragments
    uv run python3 recon/strtab_decode.py --rosetta
    uv run python3 recon/strtab_decode.py --search        # slow, still finds nothing

WHAT IS PROVED

1.  Byte transforms. `app_las_v2.1.2.bin` is bit-reversed per byte,
    `app_vx_10M_v2.1.0.bin` is nibble-swapped. Undo those first or none of this
    is visible.

2.  Image layout. Both files are xcore boot images sharing one header format:
    a magic/CRC preamble, a loader stub, then a segment table of
    (id, size_a, size_b) triples, then the first segment's code. The controller
    declares eight segments and the voice card two. The voice card carries its
    version at offset 0x14 as 0x020100FF; both carry a git-describe string
    (`lasvc-v2.1.2-0-gc38fe65`, `lasvx-v2.1.0-0-gd309cf3`).

3.  The framing of the compressed stream.

        byte <  0x80    literal, emitted as-is
        byte >= 0x80    back-reference; 2 or 3 bytes total

    Every marker byte observed so far is odd. The width rule that fits every
    observation is `3 bytes if b < 0xB0 else 2`, but only five marker values
    have actually been seen, so treat the boundary as a fit, not a fact.

4.  The marker byte is not an opcode. It changes between regions:

        region                     3-byte      2-byte
        LAS 0x29800..0x2A800       0xAD        0xB5  0xDF
        LAS 0x2AA00..0x2AD90       0xAD        0xB5  0xDF
        LAS 0x3C400..0x3DF00       0x9B        0xB5  0xE7
        VX  0x1BAC0..0x1C600       0xA3        0xB5  0xB7

    0xB5 is a 2-byte token in all four. 0xAD, 0x9B and 0xA3 are 3-byte in the
    regions where they appear and never appear in the others. So the marker
    carries payload bits, and the three-per-region clustering means the payload
    it carries is coarse -- a distance class or a length class, not a distance.

5.  It is LZ77, not a dictionary and not a trie. The controller image encodes
    the *same* address table twice, at 0x2A2C0 and at 0x3CAC8, with identical
    literal fragments in identical order but different literal/token splits:

        A: db/ [AD 52 83] [B5 18] xy/mode [B5 56] hold [DF 6F] O [DF 2F] tune/fba
        B: db/curv        [9B 15 A9] [E7 28] xy/mode [E7 A6] hold [B5 5F] O [B5 1F] tune/fba

    A split that depends on what the encoder had already emitted, rather than on
    the string being encoded, is the signature of a match finder. A dictionary or
    a trie would produce the same output twice.

6.  Ground truths, with the underlying text known independently. GROUND_TRUTH
    below carries these. The strongest are the ones where the plaintext is not a
    guess: the hex-digit tables ("0123456789ABCDEF" then "0123456789abcdef",
    present in all three regions), `/local/note-min` -> `/local/note-max`, and
    `/mix/main-en` -> `/mix/sub-en`.

WHAT IS NOT SOLVED

The bit layout inside the token. Every family below was tried and rejected:

  * length in the operand's low nibble, low 3 bits, high nibble, or high 3 bits,
    with the distance in the remaining bits of (marker & 0x7F) << 8 | operand;
  * the same with the marker's bits dropped and only the operands as payload;
  * length in the marker, distance in the operands;
  * copy-until-NUL with no explicit length (fits the 3-byte tokens in the status
    table, contradicts the 14-byte completion at `/local/note-min`);
  * every split point of the 15-bit and 23-bit payloads, both directions, bases
    1..3, run over ~700 candidate stream starts in each region (`--search`).

The failure mode is always the same. Parameter sets either die immediately on a
distance larger than the output produced so far, or survive by making every
distance tiny, which produces runaway repeats ("g/0/tgr/0g/0/tg/o1/tgr/0g/o...")
that score well on printability and mean nothing. Any future search MUST reject
low 6-gram diversity; printability alone is not a signal.

The most useful unexploited lever is the double encoding in point 5. Anchored on
shared literal runs it yields equations of the form
`sum(len of A's tokens) - sum(len of B's tokens) = |B's literals| - |A's literals|`
over a span where both encode the same text. `--rosetta` emits them. There are
not yet enough anchors to solve the system; lowering the anchor threshold below
five characters and aligning at the character level rather than the run level
would produce many more.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

BITREV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
NIBSWAP = bytes(((i & 0x0F) << 4) | (i >> 4) for i in range(256))

#: Where the encoded string tables live, after the byte transform is undone.
REGIONS = {
    "las-a": ("las", 0x29800, 0x2A800, "controller: /hw, /a, /in, status codes"),
    "las-b": ("las", 0x2AA00, 0x2AD90, "controller: USB descriptors, flash access, /info"),
    "las-c": ("las", 0x3C400, 0x3DF00, "controller: second copy of the address table + sorted dictionary"),
    "las-d": ("las", 0x0DB80, 0x0DF00, "controller: front-panel / keybed calibration table"),
    "vx-a": ("vx", 0x1BAC0, 0x1C600, "voice card: the whole command surface"),
}

#: Marker byte -> token width. Fits every observation; only five values seen.
def width(b: int) -> int:
    return 3 if b < 0xB0 else 2


#: (region, offset of the token(s), literal context, the text the token(s) must
#: emit, how we know). Anything marked `derived` is a guess from the namespace;
#: anything marked `plaintext` is a string whose content is not in doubt.
GROUND_TRUTH = (
    ("las-a", 0x2A0C9, b"404\x00Not foun", b"d\x00", "plaintext: the controller answers `s:404 s:\"Not found\"`"),
    ("las-a", 0x2A0E0, b"400\x00Malformed messag", b"e\x00", "plaintext"),
    ("las-a", 0x2A0EE, b"503\x00Unavail", b"able\x00", "plaintext: `s:503 s:\"Unavailable\"`"),
    ("las-a", 0x2A0A6, b"cc-filter-enabl", b"e\x00", "derived: /in/midi/cc-filter-enable"),
    ("las-b", 0x2AA63, b"123456789ABCDEF", b"\x000123456789", "plaintext: upper- then lower-case hex digit tables"),
    ("las-c", 0x3D27C, b"0123456789ABCDEF", b"\x000123456789", "plaintext, same pair, different split"),
    ("vx-a", 0x1C0A5, b"0123456789ABCDEF", b"\x000123456789", "plaintext, same pair again"),
    ("las-a", 0x2A3B2, b"-spread\x00/local/note-min", b"\x00/local/note-m", "derived: /in/local/note-min then note-max"),
    ("las-c", 0x3CBB0, b"-spread\x00/local/note-min", b"\x00/local/note-m", "derived, same span, encoded as TWO tokens"),
    ("las-c", 0x3C616, b"/mix/main-en", b"\x00/mix/", "derived: /mix/main-en then /mix/sub-en"),
)


def load(root: pathlib.Path) -> dict[str, bytes]:
    base = root / "captures" / "arch-harvest"
    return {
        "las": (base / "app_las_v2.1.2.bin").read_bytes().translate(BITREV),
        "vx": (base / "app_vx_10M_v2.1.0.bin").read_bytes().translate(NIBSWAP),
    }


def tokenize(data: bytes, lo: int, hi: int):
    """Split a region into ('L', byte, offset) and ('T', bytes, offset) items."""
    i = lo
    while i < hi:
        b = data[i]
        if b < 0x80:
            yield ("L", bytes([b]), i)
            i += 1
        else:
            w = width(b)
            yield ("T", bytes(data[i:i + w]), i)
            i += w


def report(images: dict[str, bytes]) -> None:
    for name, (img, lo, hi, what) in REGIONS.items():
        data = images[img]
        items = list(tokenize(data, lo, hi))
        toks = [v for k, v, _ in items if k == "T"]
        lits = sum(1 for k, _, _ in items if k == "L")
        markers = collections.Counter(t[0] for t in toks)
        print(f"\n{name}  {img} 0x{lo:06X}..0x{hi:06X}  -- {what}")
        print(f"  {hi - lo} bytes: {lits} literal, {len(toks)} tokens")
        for m, n in markers.most_common(6):
            ops = [t[-1] for t in toks if t[0] == m]
            even = sum(1 for o in ops if o % 2 == 0)
            print(f"    0x{m:02X}  width {width(m)}  n={n:4d}  "
                  f"last operand even {even}/{len(ops)}  distinct {len(set(ops))}")

    print("\nground truth (token bytes -> text the token must emit):")
    for region, off, before, after, how in GROUND_TRUTH:
        img = REGIONS[region][0]
        data = images[img]
        b = data[off]
        w = width(b)
        # a ground truth may span more than one token; walk until the next literal
        toks, i = [], off
        while i < len(data) and data[i] >= 0x80:
            toks.append(bytes(data[i:i + width(data[i])]))
            i += width(data[i])
        blob = " ".join(t.hex() for t in toks)
        print(f"  {region} 0x{off:06X}  [{blob}]  {before[-18:]!r} + {after!r}"
              f"  ({len(after)} bytes)  -- {how}")


def fragments(images: dict[str, bytes]) -> None:
    word = re.compile(rb"(?:[a-z]{4,}|/[a-z0-9]{2,}|[a-z]{2,}[-_][a-z]{2,}|[0-9]{3} [A-Z])")
    for name, (img, lo, hi, _) in REGIONS.items():
        print(f"\n### {name}")
        for m in re.finditer(rb"[ -~]{3,}", images[img][lo:hi]):
            if word.search(m.group()):
                print(f"{lo + m.start():06X}  {m.group().decode()}")


def rosetta(images: dict[str, bytes]) -> None:
    """Equations from the address table being encoded twice in the LAS image."""
    las = images["las"]
    a = list(tokenize(las, *REGIONS["las-a"][1:3]))
    b = list(tokenize(las, *REGIONS["las-c"][1:3]))

    def runs(items, minlen):
        out, cur, start = [], b"", None
        for k, (kind, v, _) in enumerate(items):
            if kind == "L":
                if not cur:
                    start = k
                cur += v
            else:
                if len(cur) >= minlen:
                    out.append((cur, start, k))
                cur = b""
        return out

    ra, rb = runs(a, 5), runs(b, 5)
    sa, sb = [x[0] for x in ra], [x[0] for x in rb]
    n, m = len(sa), len(sb)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            dp[i][j] = max(dp[i + 1][j], dp[i][j + 1],
                           dp[i + 1][j + 1] + 1 if sa[i] == sb[j] else 0)
    pairs, i, j = [], 0, 0
    while i < n and j < m:
        if sa[i] == sb[j] and dp[i][j] == dp[i + 1][j + 1] + 1:
            pairs.append((i, j)); i += 1; j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1

    print(f"{len(pairs)} shared anchors between las-a and las-c\n")
    for k in range(len(pairs) - 1):
        ia, ja = pairs[k]
        ib, jb = pairs[k + 1]
        seg_a = a[ra[ia][2]:ra[ib][1]]
        seg_b = b[rb[ja][2]:rb[jb][1]]
        ta = [v.hex() for kind, v, _ in seg_a if kind == "T"]
        tb = [v.hex() for kind, v, _ in seg_b if kind == "T"]
        la = b"".join(v for kind, v, _ in seg_a if kind == "L")
        lb = b"".join(v for kind, v, _ in seg_b if kind == "L")
        if len(ta) + len(tb) > 8:
            continue
        print(f"{sa[ia]!r} .. {sa[ib]!r}")
        print(f"   A {ta} + {la!r}")
        print(f"   B {tb} + {lb!r}")
        print(f"   => sum(len A) - sum(len B) = {len(lb) - len(la)}\n")


def search(images: dict[str, bytes]) -> None:
    """The parameter sweep. Documented so nobody repeats it; it finds nothing."""
    data = images["las"]
    lo, hi = REGIONS["las-c"][1], REGIONS["las-c"][2]

    def make(operands_only: bool, klen: int, base: int, len_low: bool):
        def f(tb: bytes):
            if operands_only:
                p, w = 0, 8 * (len(tb) - 1)
                for x in tb[1:]:
                    p = (p << 8) | x
            else:
                p, w = tb[0] & 0x7F, 7 + 8 * (len(tb) - 1)
                for x in tb[1:]:
                    p = (p << 8) | x
            if len_low:
                return (p & ((1 << klen) - 1)) + base, (p >> klen) + 1
            return (p >> (w - klen)) + base, (p & ((1 << (w - klen)) - 1)) + 1
        return f

    def run(start, f2, f3):
        out, i = bytearray(), start
        while i < hi:
            b = data[i]
            if b < 0x80:
                out.append(b); i += 1; continue
            w = width(b)
            if i + w > hi:
                break
            ln, dist = (f2 if w == 2 else f3)(bytes(data[i:i + w]))
            if not (1 <= dist <= len(out)) or not (1 <= ln <= 255):
                return None
            s = len(out) - dist
            for k in range(ln):
                out.append(out[s + k])
            i += w
            if len(out) > 200_000:
                return None
        return out

    starts = []
    cur, st = 0, None
    for i in range(lo, hi):
        if 32 <= data[i] < 127:
            if cur == 0:
                st = i
            cur += 1
        else:
            if cur >= 6:
                starts.append(st)
            cur = 0

    params = [(po, kl, ba, lw)
              for po in (False, True) for kl in range(2, 7)
              for ba in (1, 2, 3) for lw in (True, False)]
    survivors = 0
    for p2 in params:
        f2 = make(*p2)
        for p3 in params:
            f3 = make(*p3)
            for start in starts:
                out = run(start, f2, f3)
                if out is None or len(out) < (hi - start) * 1.1:
                    continue
                grams = {bytes(out[i:i + 6]) for i in range(len(out) - 6)}
                if len(grams) / max(1, len(out) - 6) < 0.35:
                    continue          # runaway repeats: the usual false positive
                survivors += 1
                print(f"SURVIVOR start=0x{start:06X} p2={p2} p3={p3} out={len(out)}")
    print(f"{survivors} survivors out of {len(params) ** 2 * len(starts)} decodes")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parent.parent)
    ap.add_argument("--report", action="store_true", help="region and token statistics")
    ap.add_argument("--fragments", action="store_true", help="recoverable literal text")
    ap.add_argument("--rosetta", action="store_true", help="cross-encoding length equations")
    ap.add_argument("--search", action="store_true", help="the parameter sweep (slow)")
    args = ap.parse_args()

    images = load(args.root)
    if args.fragments:
        fragments(images)
    elif args.rosetta:
        rosetta(images)
    elif args.search:
        search(images)
    else:
        report(images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
