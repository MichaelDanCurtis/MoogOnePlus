<!-- docs/arch/decompressor.md -->
# The XMOS string-table encoding

The controller and voice-card firmware images each carry their OSC address
table, their reply vocabulary and their calibration namespace in a compressed
byte stream. This file is the format specification as far as it is *proved*,
the evidence for each claim, and — because the format is not fully cracked —
an exact statement of what is still open and what the next attempt should do.

Tooling: `recon/strtab_decode.py`. Every claim below is reproduced by one of
its subcommands, from files in `captures/arch-harvest/` only. Nothing here
requires, or should be checked against, a powered instrument.

```sh
uv run python3 recon/strtab_decode.py --report     # regions, reference statistics
uv run python3 recon/strtab_decode.py --verify     # the format against ground truth
uv run python3 recon/strtab_decode.py --rosetta    # the cross-encoding laws
uv run python3 recon/strtab_decode.py --merge      # text one encoding spells, the other references
uv run python3 recon/strtab_decode.py --dump las-b # item-by-item listing
uv run python3 recon/strtab_decode.py --fragments  # every recoverable literal
```

---

## 0. Status

**Partially cracked.** Solved: the byte transforms, the framing, the token
widths, and — new in this pass — the **length field of the two-byte reference,
exactly, including both field widths and the base**, together with the law
that relates the controller's two encodings of the same table.

**Not solved: the reference field.** What a token points *at* is still unknown,
and this write-up ends with a proof that it is not what the obvious families of
guesses say it is. There is no decoder that reproduces a region. Do not read
§2 as if there were one.

The single most important new negative result is that **the low bits of the
operand are not a back-distance**, in any scaling. That kills the entire family
of "it's LZ77 with a (length, distance) pair packed into the operand"
hypotheses that both previous attempts, and the first two thirds of this one,
were working inside.

---

## 1. Where the streams are

| region | image | extent | contents |
|---|---|---|---|
| `las-a` | controller | 0x29800–0x2A800 | `/hw`, `/a`, `/in`, thermal, the status-code table |
| `las-b` | controller | 0x2AA00–0x2AD90 | USB descriptors, flash-access messages, `/info` |
| `las-c` | controller | 0x3C400–0x3DF00 | a **second copy** of the address table, plus the sorted dictionary |
| `las-d` | controller | 0x0DB80–0x0DF00 | front-panel / keybed calibration |
| `vx-a` | voice card | 0x1BAC0–0x1C600 | the voice card's entire command surface |

Extents are generous. The true start of each stream has not been located, so
the edges contain junk that tokenises into nonsense; `--report`'s tail markers
(0xF0, 0xFF, …) are that junk, not part of the alphabet.

Undo the per-byte transform first: **bit reversal** for `app_las_v2.1.2.bin`,
**nibble swap** `((i & 0x0F) << 4) | (i >> 4)` for `app_vx_10M_v2.1.0.bin`.

---

## 2. The format, as proved

### 2.1 Framing

```
byte <  0x80    literal, emitted verbatim   (all table text is 7-bit)
byte >= 0x80    reference
                  3 bytes total if the byte is < 0xB0
                  2 bytes total otherwise
```

The width rule fits every observation and is confirmed independently three
times: in `las-b`, `las-c` and `vx-a` the byte after a 2-byte reference is
printable text that continues a known string (`abcde` in the hex-digit tables),
which a 3-byte reading would swallow.

Marker bytes actually seen inside the streams: `0x9B 0xA3 0xA5 0xAD` (3-byte)
and `0xB5 0xB7 0xDF 0xE7 0xF6` (2-byte). Each region uses three or four of
them; the sets differ per region, which is the first sign that the marker
carries payload rather than being an opcode.

### 2.2 The two-byte reference carries an explicit length — SOLVED

```
len = (operand >> k) + 3        k = 4   for marker 0xB5
                                k = 5   for marker 0xE7
                                k = 4, base 2 for marker 0xDF  (provisional)
```

The length lives in the **high** bits of the single operand byte. The number of
bits it occupies depends on the marker; the remaining low bits are a second,
unsolved field.

**Evidence.** Four independent anchors, none of which assumes the others:

| anchor | what it pins |
|---|---|
| `las-a` 0x2A3B2 `B5 B8` emits `"\0/local/note-m"` — 14 bytes, plaintext (`/local/note-min` then `/local/note-max`) | `(0xB8 >> 4) + 3 = 14`. Rules out `k=3` (→ 26) and `k=5` (→ 8) at any base ≤ 9 |
| `las-c` 0x3CBB0 `E7 E8` + `E7 28` occupy the *same span* as that single `B5 B8` | `(7 + b) + (1 + b) = 14` ⇒ `b = 3`, and forces `k(E7) = 5` |
| `las-a` `B5 98` and `las-c` `E7 E8` are separated by exactly two literal characters over the same span | `len(B5 98) = 10 + 2 = 12 = (0x98 >> 4) + 3` |
| `las-a` 0x2A2CB `B5 18` and `las-c` 0x3CABC `E7 28` occupy the same span, which is `"/lc/"` | `1 + 3 = 4` on both sides |

**Falsification.** Over the aligned span of the two encodings, 40 of 49
segments containing only 2-byte references balance *exactly* under this model
(`--verify`). Every remaining failure involves `0xDF`, whose base is the
provisional one, or a span the character-level anchoring visibly mis-cut. No
failure involves only `0xB5` and `0xE7`. The only rival scoring as well,
`k(B5)=5, k(E7)=6, base=0`, is killed outright by `B5 B8` having to emit 14
bytes.

### 2.3 The three-byte reference has no length field — PROVED

The lengths recovered from ground truth are

```
operand 0x105B →  2      operand 0x225B →  5
operand 0x1159 →  2      operand 0x2049 → 14
operand 0x127F →  4      operand 0x5283 →  6
```

There is **no shift** of the 16-bit operand under which the length could be the
high field: `0x2049 → 14` and `0x225B → 5` are out of order at every shift, and
`0x105B → 2` versus `0x127F → 4` collide at every shift ≥ 12. `--verify` runs
the check.

So the 3-byte reference's emitted length is **data-dependent**. That is the
signature of a pointer plus an implicit terminator — "copy the NUL-terminated
string at X" — and three of the six ground truths (`"d\0"`, `"e\0"`,
`"able\0"`, and also `"oct\0"` and `"curve\0"`) do end at a NUL. But `"/lc/"`
and the many 2-byte emissions that begin with a NUL and run past it show the
2-byte form is definitely not copy-until-NUL, so if the format contains
copy-until-NUL it is one opcode of several.

### 2.4 The Rosetta laws — the new tool

The controller encodes the same address table twice: `las-a` uses the marker
set {AD, B5, DF}, `las-c` uses {9B, E7, B5}. Anchoring the two on their shared
literal text and keeping only spans where each side has exactly one reference
and no unmatched literal gives 34 one-for-one correspondences, 29 of them across the three families below. Both members of
a pair emit *identical bytes*. The differences in their operands are therefore
the whole of the region-dependent part, and they are startlingly regular:

```
AD b1 b2   <->   9B b1' b2'      (b1<<8|b2) = (b1'<<8|b2') + 16     12 of 13
DF op      <->   B5 op'          op         = op' + 16               5 of 5
B5 op      <->   E7 op'          op'        = op + (op & 0xF0)      11 of 11
```

The third law is the one that cracked the length field. It preserves the low
four bits of the operand exactly and **doubles the high nibble**. The only
field that can survive that transformation unchanged is one that sits in the
high bits and is one bit narrower under `0xE7` — which is precisely
`len = (op >> 4) + 3` versus `len = (op >> 5) + 3`. `--rosetta` prints the
instances with a `len == len` column; all eleven agree.

The first two laws say the same thing in the other direction: a constant offset
of 16 in the operand, with the low bits untouched, is what you see when two
encodings of the same text differ only by where that text sits.

### 2.5 What a reference actually points at — NOT SOLVED

Five matches have been reconstructed completely, source and all, by rebuilding
the plaintext around them:

| token | len | low field | emits | copies from | = |previous entry| + 1 |
|---|---|---|---|---|---|
| `B5 26` | 5 | 6 | `/lc/k` | 12 back | 12 |
| `B5 18` | 4 | 8 | `/lc/` | 14 back | 14 |
| `B5 56` | 8 | 6 | `\0/lc/xy/` | 12 back | 12 |
| `B5 B8` | 14 | 8 | `\0/local/note-m` | 16 back | 16 |
| `B5 58` | 8 | 8 | `\0/local/` | 16 back | 16 |

Two things fall out, and they point in opposite directions.

**(a) The low field is not the distance.** `B5 18` and `B5 B8` have the same
low field, 8, and copy from 14 and 16 bytes back respectively. Both distances
are forced by the plaintext: at 16 back, `B5 18`'s source reads `t\0/l`, which
cannot produce `/lc/`; at 14 back, `B5 B8`'s source reads `local/no`, which
cannot produce `\0/local/`. No scaling, base or unit rescues this. The
near-miss `dist = 2 × low` fits four of the five and dies on `B5 18`.

**(b) Every reconstructed match copies from the identical offset one table
entry earlier** — the distance is exactly `|previous entry| + 1` in all five
cases, i.e. the reference reproduces a prefix of the preceding entry. That is
front coding. It is also, on its own, incompatible with the two different
splits `--rosetta` shows for the same text, because a front-coder is
deterministic given the text. So there is a match finder in there, and the
five reconstructed matches are all short-range ones where the match finder and
a front-coder would agree.

The honest reading is that the low field selects *which* earlier position, from
some small set the decoder maintains — a recent-entry table, a node index in a
serialised tree, a rotating source cursor — and that five samples all landing
on "one entry back" is not enough to tell those apart.

---

## 3. Ground truth

`GROUND_TRUTH` in `recon/strtab_decode.py` carries thirteen entries; `--verify`
checks each against the model. The ones whose plaintext is not a guess:

| region | offset | token(s) | must emit | how we know |
|---|---|---|---|---|
| `las-a` | 0x2A0C9 | `AD 11 59` | `d\0` | the controller answers `404 "Not found"`; `"Not found"` appears nowhere in the image |
| `las-a` | 0x2A0E0 | `AD 10 5B` | `e\0` | `400 "Malformed message"` |
| `las-a` | 0x2A0EE | `AD 22 5B` | `able\0` | `503 "Unavailable"`; the only `able` in the image is the tail of `note-enable` at 0x29DCE |
| `las-a` | 0x2A3B2 | `B5 B8` | `\0/local/note-m` | `/local/note-min` then `/local/note-max` |
| `las-a` | 0x2A3B6 | `B5 58` | `\0/local/` | the entry after `/local/note-max` |
| `las-a` | 0x2A2C0 | `AD 12 7F` | `oct\0` | `las-c` spells `oct` out as a literal at the same output offset |
| `las-a` | 0x2A2C8 | `AD 52 83` | `curve\0` | `las-c` spells `curv` out as a literal |
| `las-c` | 0x3CAB9 | `9B 15 A9` | `e\0` | aligned against `las-a`'s `AD 52 83` |
| `las-c` | 0x3CABC | `E7 28` | `/lc/` | aligned against `las-a`'s `B5 18` |
| `las-c` | 0x3CBB0 | `E7 E8`,`E7 28` | 14 bytes | the same span as `las-a`'s single `B5 B8` |

The hex-digit tables (`0123456789ABCDEF` then `0123456789abcdef`) are present
in `las-b`, `las-c` and `vx-a` and were used as ground truth by the previous
attempt. **They should not be:** the three regions bridge the gap between
`…ABCDEF` and `abcde` with two references each, whose modelled lengths total
16, 14 and 22 bytes respectively. The tables are the same but what sits between
them is not, so the gap is not a fixed 11 bytes as was assumed and any parameter fit that
assumed it was, was fitting noise.

---

## 4. Negative results

Recorded so nobody spends the afternoon again. Everything in the previous
attempt's list still holds; these are new.

* **The low bits of the 2-byte operand are not a back-distance.** Counter-
  example in §2.5(a), with both distances forced by plaintext. This is the
  strongest negative result in this file: it invalidates every "(length,
  distance) packed into 15 bits" hypothesis, including all of the previous
  attempt's sweep.
* **`dist = 2 × low`** fits `B5 26`, `B5 56`, `B5 B8`, `B5 58` and fails
  `B5 18`. It is the most seductive wrong answer available; check it against
  `B5 18` before believing it.
* **The low field is not "entries back"** either. All five reconstructed
  matches are exactly one entry back, and their low fields are 6, 8, 6, 8, 8.
* **The 3-byte operand is not `[length | distance]`** for any split (§2.3).
* **The marker is not a length class.** `B5` alone takes lengths 3 through 18
  in `las-a`, and the mapping is the smooth `(op >> 4) + 3`.
* **The marker is not the high bits of a distance either**, in the simple form:
  `las-a` uses `B5` for 412 of its 1066 references and `las-c` uses `E7` for
  1236 of 2206, and the two are each other's counterparts for the *same* text.
  A distance-high-bits field would have to take the same value for the same
  match.
* **The hex-digit tables are not usable ground truth** (§3).
* **A global positional decode does not close.** Laying `las-a` and `las-c`
  out with the 2-byte lengths and searching for the constant shift that makes
  their literals agree finds no shift with more agreements than conflicts —
  because the 3-byte lengths are unknown and every 3-byte reference desyncs
  the two coordinate systems.

---

## 5. What the next attempt should do

Not another parameter sweep. The lever that is still unspent is the **merge**.

With the 2-byte length function now exact, the output offset of every literal
in `las-a` and in `las-c` is known up to one additive constant per region *and*
one unknown per 3-byte reference. Both regions encode the same text. So:

1. Take the character-level alignment of the two literal streams (`align()` in
   the module). Between consecutive anchors it yields an equation
   `Σ len(A's refs) + |A's literals| = Σ len(B's refs) + |B's literals|`.
2. All the 2-byte lengths are known constants, so each equation is linear in
   the unknown 3-byte lengths. Seed it with the six 3-byte lengths in §3 and
   solve. The previous run of this closed 29 of 190 unknowns from `las-a`/
   `las-c` alone; adding `las-b`, `las-d` and `vx-a` pairs, and tightening the
   anchoring so that mis-cut spans do not poison the system, should close most
   of it.
3. Once the 3-byte lengths are known, both streams lay out positionally.
   Merge their literals: wherever *either* encoding spelt a byte out, the byte
   is known. That reconstructs most of the plaintext.
4. Then every reference's emitted text is known, and its source can be found by
   searching the reconstructed text. Correlate `(token bytes) → (source
   position)` over a few hundred references and the reference field will be
   readable off the table rather than guessed.

`--merge` is step 4 done by hand on the three spans that already close. It
produces new ground truths directly:

```
las-a [ad25f7] emits b'max-s'
las-a [b598  ] emits 12 bytes ending b's/'
las-a [b586  ] emits 11 bytes ending b'r'
```

Two smaller things worth doing on the way:

* **Find the true start of each stream.** Every offset in `REGIONS` is a
  guess. A stream that starts in the right place makes output offsets absolute,
  which is what you need if the 3-byte reference turns out to be an absolute
  pointer rather than a distance.
* **Settle `0xDF`.** Its length base is derived only from the `DF ↔ B5` law and
  is contradicted by exactly one aligned span (`DF CF` against `E7 7E`, 14
  against 6). Either the span is mis-cut or `0xDF` is a third token type. It
  is the cheapest remaining discrepancy to resolve.

---

## 6. The content that is recoverable today

Without a decoder, the literal runs are still readable, and they are most of
what matters — `--fragments` prints all of them, 292 lines across the five
regions. The command namespace they establish is written up in
[`xmos-firmware.md` §3](xmos-firmware.md), which is unchanged by this pass:
the controller-only addresses (`/v2/nw`, `force-error`, `_test`, `loopback`,
`panic`, `/fan-duty`, `/mix/main-en`…), the voice card's full command surface,
and the reply vocabulary.

**The complete address tables are not recovered.** The literal fragments give
the vocabulary but not the entries. In `las-a` the literals are 1577 bytes and
the 2-byte references alone account for another 2892 — references produce more
than half the output, and every entry in the table is a mix of the two. Anyone who
needs the exact list should finish §5 rather than trust a reconstruction
assembled from fragments.
