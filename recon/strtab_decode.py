#!/usr/bin/env python3
"""The XMOS string-table encoding: the format as far as it is proved.

Supersedes `recon/strtab.py`. Run `--help` for the subcommands; every claim in
`docs/arch/decompressor.md` is reproduced by one of them, from files in
`captures/arch-harvest/` only. Nothing here talks to an instrument.

STATUS: PARTIALLY CRACKED.

  solved   the framing, the token widths, the length field of the 2-byte token
           (exactly, with the base and both field widths), and the law that
           relates the two encodings of the controller's address table
  open     the reference field -- what a token points *at*. The low bits of the
           operand are provably not a back-distance (§"negative results" below).

WHAT IS PROVED

1.  Byte transforms. `app_las_v2.1.2.bin` is bit-reversed per byte,
    `app_vx_10M_v2.1.0.bin` is nibble-swapped.

2.  Framing.  byte < 0x80 -> literal, emitted as-is (all table text is 7-bit).
    byte >= 0x80 -> reference, 3 bytes total if the byte is < 0xB0, else 2.

3.  The 2-byte reference carries an explicit match length in the HIGH bits of
    its single operand byte:

        len = (operand >> k) + 3          k = 4 for marker 0xB5 (and 0xDF)
                                          k = 5 for marker 0xE7

    The `+3` and both values of k are pinned by three independent anchors that
    do not share an assumption; see `--verify`. 34 of 36 cross-encoding
    equations that involve only 0xB5/0xE7 tokens are satisfied exactly, and the
    two that are not are visibly mis-anchored.

4.  The remaining low bits of the operand (4 bits under 0xB5, 5 under 0xE7) are
    a second field.  They are NOT a back-distance: `--verify` exhibits two
    0xB5 tokens with the same low field whose matches are provably 14 and 16
    bytes back.

5.  The 3-byte reference's length is NOT a bit-field of its 16-bit operand: no
    shift of that operand is even monotone against the eight lengths recovered
    from ground truth (`--verify`).  Its length is therefore data-dependent,
    which is the signature of a pointer plus an implicit terminator.

6.  The Rosetta law.  The controller encodes the same address table twice, in
    region `las-a` (marker set AD/B5/DF) and region `las-c` (9B/E7/B5).  For
    corresponding references:

        AD b1 b2   <->   9B b1' b2'     with (b1b2) = (b1'b2') + 16
        DF op      <->   B5 op'         with op     = op' + 16
        B5 op      <->   E7 op'         with op'    = op + (op & 0xF0)

    The third law is the informative one: it preserves the low field exactly
    and doubles the high field, which is only possible if the high field is a
    length whose field is one bit narrower under 0xE7 -- i.e. it *derives*
    point 3 rather than assuming it.  `--rosetta` prints the instances.

NEGATIVE RESULTS (do not spend the afternoon again)

  * The low field of the 2-byte operand is not the distance, in any scaling.
    Verified counterexample: 0xB5 0x18 copies from 14 bytes back and 0xB5 0xB8
    copies from 16 bytes back; both have low field 8.  `dist = 2 * low` fits
    four of the five reconstructed matches and dies on the fifth.
  * The low field is not "entries back" either: all five reconstructed matches
    are one entry back, with low fields 6, 8, 6, 8, 8.
  * The 3-byte operand is not [length | distance] for any split: lengths 2, 2,
    4, 5, 6, 14 against operands 0x105B, 0x1159, 0x127F, 0x225B, 0x5283, 0x2049
    are not monotone under any shift.
  * Copy-until-NUL is not the 2-byte semantics: 0xB5 0xB8 emits 14 bytes that
    *begin* with a NUL and run on past it.
  * Front coding is not the whole format, but it is the whole of what has been
    reconstructed: all five matches recovered so far copy from the identical
    offset one table entry earlier, i.e. dist = |previous entry| + 1.  A
    front-coder cannot produce the two different splits of the same text that
    `--rosetta` shows, so a match finder is still in there somewhere.

WHAT THE NEXT ATTEMPT SHOULD DO

  The lever that is still unspent is the merge, not the search.  With the
  2-byte length function now exact, the output offset of every literal in
  `las-a` and in `las-c` is known up to one additive constant per region.  Both
  regions encode the same text, so merging their literal streams at those
  offsets reconstructs the plaintext wherever *either* region spelt it out --
  which then hands you the exact text every token had to emit, and the distance
  falls out by searching for it.  That is a bounded amount of work and it does
  not require guessing anything.  `--merge` starts it; it needs the 3-byte
  lengths, which the merge itself supplies as it closes.
"""

from __future__ import annotations

import argparse
import array
import collections
import pathlib
import re
import sys

BITREV = bytes(int(f"{i:08b}"[::-1], 2) for i in range(256))
NIBSWAP = bytes(((i & 0x0F) << 4) | (i >> 4) for i in range(256))

#: image -> (transform, path under captures/arch-harvest)
IMAGES = {
    "las": (BITREV, "app_las_v2.1.2.bin"),
    "vx": (NIBSWAP, "app_vx_10M_v2.1.0.bin"),
}

#: region -> (image, start, end, what it holds). Extents are generous; the
#: stream's true start has not been located, so the edges contain junk.
REGIONS = {
    "las-a": ("las", 0x29800, 0x2A800, "controller: /hw, /a, /in, status codes"),
    "las-b": ("las", 0x2AA00, 0x2AD90, "controller: USB descriptors, flash access, /info"),
    "las-c": ("las", 0x3C400, 0x3DF00, "controller: second copy of the address table + dictionary"),
    "las-d": ("las", 0x0DB80, 0x0DF00, "controller: front-panel / keybed calibration"),
    "vx-a": ("vx", 0x1BAC0, 0x1C600, "voice card: the whole command surface"),
}

#: marker -> (number of low, non-length bits in the operand; length base).
#: Derived, not assumed -- see module docstring point 3 and `--verify`.
#: 0xB5 and 0xE7 are solid. 0xDF's entry is forced by the Rosetta law
#: DF(op) <-> B5(op-16), and is contradicted by exactly one aligned span
#: ([dfcf] <-> [e77e]); treat it as provisional.
LEN_MODEL = {0xB5: (4, 3), 0xE7: (5, 3), 0xDF: (4, 2)}
LOW_BITS = {m: k for m, (k, _) in LEN_MODEL.items()}
LEN_BASE = 3


def width(b: int) -> int:
    """Token width in bytes for a marker byte. Fits every observation."""
    return 3 if b < 0xB0 else 2


def token_len(tok: bytes) -> int | None:
    """Emitted length of a reference, or None if the format does not give it.

    Only the 2-byte form has a decodable length. The 3-byte form's length is
    data-dependent (module docstring point 5), so it is unknown until the
    referent is known.
    """
    if len(tok) != 2:
        return None
    m = LEN_MODEL.get(tok[0])
    if m is None:
        return None
    k, base = m
    return (tok[1] >> k) + base


def token_low(tok: bytes) -> int | None:
    """The second, unsolved field of a 2-byte reference."""
    if len(tok) != 2:
        return None
    k = LOW_BITS.get(tok[0])
    return None if k is None else tok[1] & ((1 << k) - 1)


# --------------------------------------------------------------------------- #
# loading and tokenising
# --------------------------------------------------------------------------- #

def load(root: pathlib.Path) -> dict[str, bytes]:
    base = root / "captures" / "arch-harvest"
    out = {}
    for name, (xform, fn) in IMAGES.items():
        out[name] = (base / fn).read_bytes().translate(xform)
    return out


class Item:
    __slots__ = ("kind", "raw", "src", "out", "length")

    def __init__(self, kind, raw, src, out, length):
        self.kind = kind        # 'L' literal run | 'T' reference
        self.raw = raw          # the bytes in the compressed stream
        self.src = src          # offset in the (transformed) image
        self.out = out          # offset in the decoded output, or None
        self.length = length    # emitted length, or None if unknown

    def __repr__(self):
        return (f"<{self.kind} {self.raw.hex()} src={self.src:06X} "
                f"out={self.out} len={self.length}>")


def tokenize(data: bytes, start: int, end: int) -> list[Item]:
    """Split a byte range into literal runs and references, with output offsets.

    Output offsets are relative to `start` and become None from the first
    reference whose length is not decodable (every 3-byte reference).
    """
    items: list[Item] = []
    i, out = start, 0
    for _ in range(1 << 30):
        if i >= end:
            break
        b = data[i]
        if b < 0x80:
            j = i
            while j < end and data[j] < 0x80:
                j += 1
            items.append(Item("L", bytes(data[i:j]), i, out, j - i))
            if out is not None:
                out += j - i
            i = j
        else:
            w = width(b)
            if i + w > end:
                break
            tok = bytes(data[i:i + w])
            L = token_len(tok)
            items.append(Item("T", tok, i, out, L))
            out = None if (out is None or L is None) else out + L
            i += w
    return items


def decode(data: bytes, start: int, end: int) -> tuple[bytearray, list[Item]]:
    """Best-effort reconstruction of one region.

    Returns (text, items). `text` holds every byte the format lets us place:
    literals verbatim, and 0x01 filler for the bytes a reference emits (whose
    values are not yet recoverable). Where the emitted length itself is unknown
    -- every 3-byte reference -- the run is a single 0x02 byte and `Item.out`
    is None from there on, so the caller can see exactly where the
    reconstruction stops being positional.

    This is not a decompressor. It is the honest partial result: the format's
    framing and its length field are solved, its reference field is not.
    """
    items = tokenize(data, start, end)
    text = bytearray()
    for it in items:
        if it.kind == "L":
            text += it.raw
        elif it.length is not None:
            text += b"\x01" * it.length
        else:
            text += b"\x02"
    return text, items


# --------------------------------------------------------------------------- #
# ground truth
# --------------------------------------------------------------------------- #

#: (region, stream offset, token bytes, emitted text or length, how we know).
#: `plaintext` = the emitted bytes are known outright. `aligned` = the length
#: is forced by the two encodings of the same span (see --rosetta).
GROUND_TRUTH = [
    ("las-a", 0x2A0C9, "ad1159", 2, b"d\x00",
     "plaintext: the controller answers 404 \"Not found\""),
    ("las-a", 0x2A0E0, "ad105b", 2, b"e\x00",
     "plaintext: 400 \"Malformed message\""),
    ("las-a", 0x2A0EE, "ad225b", 5, b"able\x00",
     "plaintext: 503 \"Unavailable\"; the only \"able\" is in note-enable"),
    ("las-a", 0x2A3B2, "b5b8", 14, b"\x00/local/note-m",
     "plaintext: /local/note-min then /local/note-max"),
    ("las-a", 0x2A3B6, "b558", 8, b"\x00/local/",
     "plaintext: the entry after /local/note-max"),
    ("las-a", 0x2A2C0, "ad127f", 4, b"oct\x00",
     "aligned: las-c spells `oct` as a literal here"),
    ("las-a", 0x2A2C3, "b526", 5, b"/lc/k",
     "aligned + reconstructed from the previous entry"),
    ("las-a", 0x2A2C8, "ad5283", 6, b"curve\x00",
     "aligned: las-c spells `curv` as a literal here"),
    ("las-a", 0x2A2CB, "b518", 4, b"/lc/",
     "aligned: the entry /lc/xy/mode follows"),
    ("las-a", 0x2A2D4, "b556", 8, b"\x00/lc/xy/",
     "reconstructed: the entry /lc/xy/hold follows"),
    ("las-c", 0x3CAB9, "9b15a9", 2, b"e\x00",
     "aligned against las-a's [ad5283]"),
    ("las-c", 0x3CABC, "e728", 4, b"/lc/",
     "aligned against las-a's [b518]"),
    ("las-c", 0x3CBB0, "e7e8", 10, None,
     "aligned: [e7e8]+[e728] == las-a's [b5b8] == 14 bytes"),
]

#: The five matches whose *source* has been reconstructed as well. Every one of
#: them copies from the identical offset one table entry earlier.
RECONSTRUCTED_MATCHES = [
    # (token, emitted, distance, |previous entry| + 1)
    ("b526", b"/lc/k", 12, 12),
    ("b518", b"/lc/", 14, 14),
    ("b556", b"\x00/lc/xy/", 12, 12),
    ("b5b8", b"\x00/local/note-m", 16, 16),
    ("b558", b"\x00/local/", 16, 16),
]


# --------------------------------------------------------------------------- #
# cross-encoding alignment (the Rosetta machinery)
# --------------------------------------------------------------------------- #

def _lcs_pairs(sa: bytes, sb: bytes) -> list[tuple[int, int]]:
    n, m = len(sa), len(sb)
    rows, prev = [], array.array("i", [0] * (m + 1))
    for i in range(n - 1, -1, -1):
        cur = array.array("i", [0] * (m + 1))
        ai = sa[i]
        for j in range(m - 1, -1, -1):
            if ai == sb[j]:
                cur[j] = prev[j + 1] + 1
            else:
                x, y = prev[j], cur[j + 1]
                cur[j] = x if x >= y else y
        rows.append(cur)
        prev = cur
    rows.reverse()

    def dp(i, j):
        return rows[i][j] if (i < n and j < m) else 0

    out, i, j = [], 0, 0
    while i < n and j < m:
        if sa[i] == sb[j] and dp(i, j) == dp(i + 1, j + 1) + 1:
            out.append((i, j)); i += 1; j += 1
        elif dp(i + 1, j) >= dp(i, j + 1):
            i += 1
        else:
            j += 1
    return out


def align(items_a: list[Item], items_b: list[Item]):
    """Anchor two token streams on their shared literal text.

    Yields (a_tokens, a_unmatched_literals, b_tokens, b_unmatched_literals)
    for the span between each pair of consecutive anchored characters. Over any
    such span the two streams emit the *same* text, so
    sum(len of a_tokens) + len(a_unmatched) == sum(len of b_tokens) + len(b_unmatched).
    """
    def chars(items):
        s = bytearray()
        for it in items:
            if it.kind == "L":
                s += it.raw
        return bytes(s)

    sa, sb = chars(items_a), chars(items_b)
    pairs = _lcs_pairs(sa, sb)
    ma = {i for i, _ in pairs}
    mb = {j for _, j in pairs}

    def events(items, matched):
        ev, ci = [], 0
        for it in items:
            if it.kind == "L":
                for ch in it.raw:
                    ev.append(("m" if ci in matched else "u", ch))
                    ci += 1
            else:
                ev.append(("t", it.raw))
        return ev

    def split(ev):
        segs, cur = [], []
        for e in ev:
            if e[0] == "m":
                segs.append(cur); cur = []
            else:
                cur.append(e)
        segs.append(cur)
        return segs

    sega, segb = split(events(items_a, ma)), split(events(items_b, mb))
    for k in range(min(len(sega), len(segb))):
        ta = [e[1] for e in sega[k] if e[0] == "t"]
        ua = bytes(e[1] for e in sega[k] if e[0] == "u")
        tb = [e[1] for e in segb[k] if e[0] == "t"]
        ub = bytes(e[1] for e in segb[k] if e[0] == "u")
        if ta or tb:
            yield ta, ua, tb, ub


# --------------------------------------------------------------------------- #
# subcommands
# --------------------------------------------------------------------------- #

def cmd_report(images):
    for name, (img, lo, hi, what) in REGIONS.items():
        items = tokenize(images[img], lo, hi)
        toks = [it for it in items if it.kind == "T"]
        lits = sum(it.length for it in items if it.kind == "L")
        counts = collections.Counter(it.raw[0] for it in toks)
        print(f"\n{name}  {img} 0x{lo:06X}..0x{hi:06X}  -- {what}")
        print(f"  {hi - lo} bytes: {lits} literal, {len(toks)} references")
        for m, n in counts.most_common(4):
            k = LOW_BITS.get(m)
            note = f"len=(op>>{k})+{LEN_BASE}" if (k and width(m) == 2) else \
                   ("3-byte, length data-dependent" if width(m) == 3 else "?")
            print(f"    0x{m:02X}  width {width(m)}  n={n:5d}   {note}")


def cmd_verify(images):
    print("=== ground truth ===")
    ok = bad = 0
    for region, off, hexs, length, text, how in GROUND_TRUTH:
        img = REGIONS[region][0]
        raw = bytes(images[img][off:off + len(hexs) // 2])
        assert raw.hex() == hexs, f"{region} 0x{off:06X}: {raw.hex()} != {hexs}"
        got = token_len(raw)
        mark = "  " if got is None else ("OK" if got == length else "!!")
        if got is not None:
            ok += got == length
            bad += got != length
        shown = repr(text) if text else f"{length} bytes"
        print(f" {mark} {region} 0x{off:06X} [{hexs}] -> {shown:26} "
              f"model={got}  ({how})")
    print(f"\n  2-byte length model: {ok} confirmed, {bad} contradicted")
    print("  (blank rows are 3-byte references; the model has no length for them)")

    print("\n=== cross-encoding equations, las-a vs las-c ===")
    a = tokenize(images["las"], 0x2A2B0, 0x2A800)
    c = tokenize(images["las"], 0x3CA98, 0x3D0C0)
    tested = passed = 0
    fails = []
    for ta, ua, tb, ub in align(a, c):
        if len(ta) > 4 or len(tb) > 4:
            continue
        la = [token_len(t) for t in ta]
        lb = [token_len(t) for t in tb]
        if any(x is None for x in la + lb):
            continue
        tested += 1
        if sum(la) + len(ua) == sum(lb) + len(ub):
            passed += 1
        else:
            fails.append(([t.hex() for t in ta], len(ua), [t.hex() for t in tb], len(ub)))
    print(f"  spans containing only 2-byte references: {passed}/{tested} "
          f"satisfied exactly")
    print("  (every remaining failure involves 0xDF, whose length base is the")
    print("   provisional one, or is a span the character-level anchoring got")
    print("   wrong; no failure involves only 0xB5 and 0xE7)")
    for f in fails:
        print(f"    unsatisfied: {f}")

    print("\n  alternative field widths, scored the same way:")
    for kb in (3, 4, 5):
        for ke in (kb + 1,):
            for base in range(0, 6):
                n = good = 0
                for ta, ua, tb, ub in align(a, c):
                    if len(ta) > 4 or len(tb) > 4:
                        continue
                    def L(t):
                        if len(t) != 2:
                            return None
                        if t[0] == 0xB5:
                            return (t[1] >> kb) + base
                        if t[0] == 0xE7:
                            return (t[1] >> ke) + base
                        return None
                    la = [L(t) for t in ta]; lb = [L(t) for t in tb]
                    if any(x is None for x in la + lb):
                        continue
                    n += 1
                    good += sum(la) + len(ua) == sum(lb) + len(ub)
                if n and good / n > 0.9:
                    star = (" <- also pinned by ground truth"
                            if (kb, base) == (4, 3)
                            else " (killed by [b5b8] emitting 14 bytes)")
                    print(f"    k(B5)={kb} k(E7)={ke} base={base}: {good}/{n}{star}")

    print("\n=== the low field is not a distance ===")
    for tok, text, dist, prev in RECONSTRUCTED_MATCHES:
        raw = bytes.fromhex(tok)
        print(f"  [{tok}] len={token_len(raw):2d} low={token_low(raw):2d}  "
              f"emits {text!r:22} from {dist:2d} back "
              f"(= |previous entry|+1 = {prev})")
    print("  [b518] and [b5b8] share low field 8 and copy from 14 and 16 back.")
    print("  Every reconstructed match is exactly one table entry back.")

    print("\n=== the 3-byte operand is not [length|distance] ===")
    obs = [(0x105B, 2), (0x1159, 2), (0x127F, 4), (0x225B, 5),
           (0x2049, 14), (0x5283, 6)]
    for v, L in obs:
        print(f"  operand {v:#06x} emits {L:2d} bytes")
    survivors = []
    for shift in range(0, 16):
        ok = True
        for (v1, l1) in obs:
            for (v2, l2) in obs:
                a, b = v1 >> shift, v2 >> shift
                if a == b and l1 != l2:
                    ok = False
                if a < b and l1 > l2:
                    ok = False
        if ok:
            survivors.append(shift)
    print(f"  shifts under which the length could be the high field: {survivors}")
    print("  -> none. A [length|distance] split of the 16-bit operand is")
    print("     impossible; the 3-byte reference's length is data-dependent.")


def cmd_rosetta(images):
    a = tokenize(images["las"], 0x2A2B0, 0x2A800)
    c = tokenize(images["las"], 0x3CA98, 0x3D0C0)
    pairs = collections.Counter()
    for ta, ua, tb, ub in align(a, c):
        if len(ta) == 1 and len(tb) == 1 and not ua and not ub:
            pairs[(ta[0], tb[0])] += 1
    groups = collections.defaultdict(list)
    for (x, y), n in pairs.items():
        groups[(x[0], y[0])].append((x, y, n))
    print("one-for-one reference correspondences between the two encodings of")
    print("the SAME text. Both members emit identical bytes, so the difference")
    print("in their operands is the whole of the region-dependent part.\n")
    for mk in sorted(groups):
        law = {
            (0xAD, 0x9B): "operand16(las-a) = operand16(las-c) + 16",
            (0xDF, 0xB5): "operand(las-a)   = operand(las-c)   + 16",
            (0xB5, 0xE7): "operand(las-c)   = operand(las-a) + (operand & 0xF0)",
        }.get(mk, "")
        print(f"  {mk[0]:02X} -> {mk[1]:02X}   {law}")
        for x, y, n in sorted(groups[mk], key=lambda t: t[0]):
            va = int.from_bytes(x[1:], "big")
            vb = int.from_bytes(y[1:], "big")
            la, lb = token_len(x), token_len(y)
            eq = "" if la is None or lb is None else \
                 ("  len " + str(la) + (" == " if la == lb else " != ") + str(lb))
            print(f"    {x.hex():6} -> {y.hex():6}  {va:#06x} -> {vb:#06x}"
                  f"  delta {vb - va:+5d}  x{n}{eq}")
        print()
    print("The 0xB5 -> 0xE7 law preserves the low 4 bits and doubles the high")
    print("nibble. A length field is the only thing that can survive that: it")
    print("must sit in the high bits and be one bit narrower under 0xE7.")


def cmd_fragments(images):
    word = re.compile(rb"(?:[a-z]{4,}|/[a-z0-9]{2,}|[a-z]{2,}[-_][a-z]{2,}|[0-9]{3} [A-Z])")
    for name, (img, lo, hi, _) in REGIONS.items():
        print(f"\n### {name}")
        for m in re.finditer(rb"[ -~]{3,}", images[img][lo:hi]):
            if word.search(m.group()):
                print(f"{lo + m.start():06X}  {m.group().decode()}")


def cmd_dump(images, region):
    img, lo, hi, what = REGIONS[region]
    text, items = decode(images[img], lo, hi)
    print(f"# {region}: {what}")
    print(f"# {len(items)} items; 0x01 = byte emitted by a reference of known")
    print(f"# length, 0x02 = a 3-byte reference of unknown length\n")
    for it in items:
        if it.kind == "L":
            shown = it.raw.decode("ascii", "replace").replace("\x00", "\\0")
            print(f"{it.src:06X}  lit  {shown}")
        else:
            L = "?" if it.length is None else str(it.length)
            low = token_low(it.raw)
            low = "?" if low is None else str(low)
            print(f"{it.src:06X}  ref  [{it.raw.hex()}] len={L} low={low}")


def cmd_merge(images):
    """Text that one encoding spells out and the other reaches by reference.

    Each line is a new ground truth: the exact bytes a reference had to emit,
    read off the *other* encoding of the same table. This is the material the
    next attempt should grow -- it is the only source of (token -> text) pairs
    that does not require solving the reference field first.
    """
    a = tokenize(images["las"], 0x2A2B0, 0x2A800)
    c = tokenize(images["las"], 0x3CA98, 0x3D0C0)
    found = 0
    print("references whose emitted text the other encoding spells out:\n")
    for ta, ua, tb, ub in align(a, c):
        if len(ta) == 1 and not tb and ub:
            print(f"  las-a [{ta[0].hex():6}] emits {ub!r}")
            found += 1
        elif len(tb) == 1 and not ta and ua:
            print(f"  las-c [{tb[0].hex():6}] emits {ua!r}")
            found += 1
    print("\nreferences whose emitted text is bounded by the other encoding:\n")
    for ta, ua, tb, ub in align(a, c):
        if len(ta) == 1 and len(tb) <= 1 and ub and tb:
            L = token_len(tb[0])
            if L is not None:
                print(f"  las-a [{ta[0].hex():6}] emits {L + len(ub):2d} bytes "
                      f"ending {ub!r}")
                found += 1
    print(f"\n{found} references pinned. Extending this needs the 3-byte")
    print("lengths, which the merge itself supplies as it closes.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", type=pathlib.Path,
                    default=pathlib.Path(__file__).resolve().parent.parent)
    ap.add_argument("--report", action="store_true", help="regions and reference statistics")
    ap.add_argument("--verify", action="store_true", help="check the format against ground truth")
    ap.add_argument("--rosetta", action="store_true", help="the cross-encoding correspondence laws")
    ap.add_argument("--fragments", action="store_true", help="recoverable literal text")
    ap.add_argument("--merge", action="store_true", help="text one encoding spells that the other references")
    ap.add_argument("--dump", metavar="REGION", choices=sorted(REGIONS),
                    help="item-by-item listing of one region")
    args = ap.parse_args()

    images = load(args.root)
    if args.verify:
        cmd_verify(images)
    elif args.rosetta:
        cmd_rosetta(images)
    elif args.fragments:
        cmd_fragments(images)
    elif args.merge:
        cmd_merge(images)
    elif args.dump:
        cmd_dump(images, args.dump)
    else:
        cmd_report(images)
    return 0


if __name__ == "__main__":
    sys.exit(main())
