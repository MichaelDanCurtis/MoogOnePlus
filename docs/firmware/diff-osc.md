# OSC namespace diff — `las-sc` 1.5.0 vs 1.8.2

Static comparison of `usr/bin/las-sc` from the owner's **v1.5.0** root filesystem
and from the decrypted **v1.8.2** root filesystem. Nothing in this document was
obtained from the instrument. Everything was read from local disk on macOS; no
ARM binary was executed.

**Every claim is graded.** `[READ]` = taken directly out of a file, with file and
offset. `[INFERRED]` = reasoning, with the evidence named. `[UNKNOWN]` = not
established.

---

## 0. Headline

**`las-sc`'s OSC namespace did not change at all between 1.5.0 and 1.8.2.** Not
one address was added, removed or renamed. The three address tables are
byte-identical, at identical file offsets, in both binaries. `las-sc` 1.8.2 is a
recompile of the same source; the entire 592-byte size difference and every one
of the 62,081 differing bytes in `.text` is accounted for by the build
directory's name being one character longer.

The 1.8.x work landed somewhere else:

* **`las-frontend`** gained **67 new `/p/…` keys** — the only real namespace
  change in the update. Four of them are `voice_rule`; twelve are
  `modmatrix/vars/cvout1…4`.
* **The XMOS firmware** was rebuilt from 2022 to 2025 sources: `app_las`
  2.1.2 → 2.2.2, `app_vx` 2.1.0 → 2.2.1. Since no MIDI byte reaches Linux, this
  is where every MIDI fix in the release notes must live.
* **The SuperCollider DSP tree is bit-identical.** `usr/share/las-fx` — all 210
  synthdefs, `synthdefs.scd`, `efx_server.scd`, the wavetables, `init_sc_*.scd`
  — does not differ by a single byte.

---

## 1. Binary identity

| | 1.5.0 | 1.8.2 |
|---|---|---|
| path | `rootfs-1.5.0/usr/bin/las-sc` | `firmware-1.8.2/rootfs-1.8.2/usr/bin/las-sc` |
| size | 2,498,948 | 2,499,540 (+592) |
| md5 | `7f5a3f21c21982e377c428330f633904` | `8de3f3334e332f1a732af1b71ac42589` |
| mtime | 2022-05-16 | 2025-09-15 |

`[READ]` `md5`/`stat` on both files.

**The 1.5.0 binary is genuine.** `rootfs-1.5.0/usr/bin/las-sc` is byte-identical
to `arch-harvest/las-sc`, which was pulled off the owner's own instrument
(`md5 7f5a3f21c21982e377c428330f633904` for both). `[READ]`

Both are `ELF 32-bit LSB executable, ARM, EABI5, dynamically linked, stripped`,
linking `libchicken.so.8`. `[READ]` `llvm-objdump --private-headers`.

### 1.1 Where the 592 bytes went

`[READ]` `llvm-objdump --section-headers` on both:

| section | 1.5.0 size | 1.8.2 size | Δ |
|---|---|---|---|
| `.text` | `0x1def3c` | `0x1def3c` | **0** |
| `.rodata` | `0x5e643` | `0x5e898` | **+0x255 (+597)** |
| `.data` | `0x22e20` | `0x22e20` | **0** |
| `.bss` | `0x4090` | `0x4090` | **0** |

Every section keeps its size except `.rodata`. `.text` is the same length to the
byte, and starts at the same VMA (`0x11650`) in both.

**The +597 bytes are entirely the build directory name.** `las-sc` is CHICKEN
Scheme compiled to C; every non-inlined call site carries a trace string of the
form `<source path>:<line>: <callee>`. The build temp directory was
`/tmp/temp87f.4721/` (18 chars) in 1.5.0 and `/tmp/temp113e.9287/` (19 chars) in
1.8.2. `[READ]` It occurs **597 times in each** binary's `.rodata`. 597 × 1 = 597.
`[READ]` — measured directly:

```
occurrences of build temp path: 1.5.0 = 597   1.8.2 = 597
predicted rodata growth = 597
actual  rodata growth = 597
```

Normalising both build paths to a common token makes the two `.rodata` sections
the **same length (382,448 bytes)**. `[READ]`

### 1.2 The `.text` difference is relocation drift, not code

62,081 bytes of `.text` differ — 31,425 aligned 32-bit words. `[READ]` Their
deltas:

| delta | words | meaning |
|---|---|---|
| in `[+1, +597]` | **31,415 (99.968%)** | pointers into `.rodata`, shifted by however many build-path strings precede them; `+592` (the `.data`/`.bss` shift) and `+597` (the full `.rodata` growth) dominate at 23,366 and 6,196 |
| outside that range | 10 | all point into `0x11810–0x11a08` |

`[READ]` The 10 outliers all target the CHICKEN trampoline stubs at the head of
`.text`. `[READ]` `llvm-objdump -d --triple=armv7-none-linux-gnueabihf
--start-address=0x11800 --stop-address=0x11a20` shows that region is a run of
**identical six-instruction stubs**, one every 0x1c bytes:

```
11810: e59fc010   ldr r12, [pc, #0x10]
11814: e5802004   str r2,  [r0, #0x4]
11818: e580c000   str r12, [r0]
1181c: e5912008   ldr r2,  [r1, #0x8]
11820: e5802008   str r2,  [r0, #0x8]
11824: e12fff1e   bx  lr
```

— and the same six instructions repeat verbatim at `1182c`, `11848`, `11864`,
`11880`, `1189c`, `118b8`, `118d4`, `118f0`, `1190c`, byte-for-byte identical in
both versions. `[READ]` So each of the 10 outliers points at a *different but
functionally identical* stub. `[INFERRED]` — the stub bodies are identical, so
which one a record points at cannot change behaviour.

**Conclusion: no instruction in `las-sc` changed.** `[INFERRED]` from: identical
`.text` size, identical `.data`/`.bss` sizes, 99.968% of differing words being
address constants inside the known shift range, and the remaining 10 pointing
into a block of interchangeable stubs.

---

## 2. The namespace itself — method

`las-sc` stores its OSC addresses as CHICKEN **length-prefixed literals**, not as
NUL-terminated C strings. `strings(1)` therefore mis-reports them (it merges
`\x0c/p/post-expr` into one run, and drops any literal preceded by a printable
byte).

The encoding is a 5-byte header — `0xFE`, then a 4-byte big-endian word whose top
byte is the type tag and whose low 24 bits are the length — followed by the body.
Type `0x42` = string, `0x01` = symbol. `[READ]` from `xxd -s 1977500`:

```
001e2d3c: 0000 0b2f 702f 7072 652d 6578 7072 fe03   .../p/pre-expr..
          ^^^^^^^  len 0x0b = 11        "/p/pre-expr" = 11 chars
```

and the `_m` twins are stored as a string/symbol pair:

```
001e2d8c: 0009 2f70 2f6f 312f 645f 6dfe 0300 0002   ../p/o1/d_m.....
001e2d9c: fe01 0000 036f 3164 feff 0efe 0300 0002   .....o1d........
                 ^^ len 3, symbol "o1d"
```

I wrote a decoder for that format and ran it over both whole binaries.

---

## 3. Result: the namespace is identical

### 3.1 Decoded literals

| | 1.5.0 | 1.8.2 |
|---|---|---|
| literal **strings** decoded | 1,433 (1,370 distinct) | 1,433 (1,370 distinct) |
| literal **symbols** decoded | 162 (149 distinct) | 162 (149 distinct) |
| strings present in one but not the other | **0** | **0** |
| strings with differing multiplicity | **0** | **0** |
| symbols present in one but not the other | **0** | **0** |

`[READ]` — decoder output over both files.

### 3.2 `/p…` addresses

| | 1.5.0 | 1.8.2 |
|---|---|---|
| distinct `/p…` literals in `.rodata` | **534** | **534** |
| of which end in `_m` | 115 | 115 |
| of which begin `/p/part/` | 79 | 79 |
| `/p/pre-expr`, `/p/post-expr` | present | present |
| **added** | — | **none** |
| **removed** | — | **none** |
| **renamed** | — | **none** |
| sitting at a *different file offset* | — | **none** |

`[READ]` Every one of the 534 lies at the **same file offset** in both binaries,
and the byte span `[offset, offset+len)` is identical in both — verified
byte-by-byte, 0 mismatches. Offsets span 1,969,172 – 1,994,192.

(A 535th apparent hit, the two bytes `2f 70` at file offset 414,752, is a false
positive inside an ARM instruction stream: the word at `0x65420` is `0xebfe702f`
— a `bl` whose 24-bit displacement happens to end in `2f 70`, preceded at
`0x6541c` by `0xe3a000ff` = `mov r0, #0xff`. `[READ]`)

### 3.3 The three address tables are inside a byte-identical region

The prior report `docs/firmware/las-sc-namespace.md` §4 locates `las-sc`'s three
address tables in the 1.8.2 binary. I checked whether those file offsets fall
inside the region that is identical between versions:

`[READ]` The first byte of `.rodata` (file offset 1,967,508) that differs between
the two binaries is at **1,998,219** — 30,711 bytes in — and it is the build
directory name:

```
1.5.0: ...sc/sc.scm:22: make-parameter\0/tmp/temp87f.4721/sc/timbre-tree.scm:570: append\0
1.8.2: ...sc/sc.scm:22: make-parameter\0/tmp/temp113e.9287/sc/timbre-tree.scm:570: append
```

| table | encoded blob at | inside the identical prefix? |
|---|---|---|
| **A** — 372 per-timbre parameter suffixes | 1,970,101 | **yes** |
| **C** — 117 `expression-nodes` (`/p/pre-expr`, `/p/post-expr`, 115 `_m`) | 1,977,648 | **yes** |
| **B** — 90 global / non-timbre addresses | 1,991,553 | **yes** |

`[READ]` All three, and the whole 1,968,166–1,994,192 span in which every `/p…`
literal lives, sit inside the first 30,711 identical bytes of `.rodata`.

**This is the strongest form the claim can take without running the binary:
`las-sc`'s entire OSC address space is the same sequence of bytes in the same
place in both firmware versions.**

### 3.4 Launch line — also unchanged in substance

`[READ]` `etc/init.d/S42sc` line 4, the only difference between the two files:

```
1.5.0: las-sc -t vc -f localhost:7775 -l localhost:9300 \
       --vxfw=…/app_vx_10M_v2.1.0.bin --vxdb=/var/tuning.vxtune \
       --vcfw=…/app_las_v2.1.2.bin --vcfv=33620735 --temp \
       --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 $1

1.8.2: las-sc -t vc -f localhost:7775 -l localhost:9300 \
       --vxfw=…/app_vx_10M_v2.2.1.bin --vxdb=/var/tuning.vxtune \
       --vcfw=…/app_las_v2.2.2.bin --vcfv=33686271 --temp \
       --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 $1
```

Same flags, same ports, same `--expr-syms` file. Only the XMOS image paths and
the `--vcfv` version integer moved. `[READ]` `33686271 − 33620735 = 65536 = 0x10000`
— one step in the middle 16-bit field, matching `2.1.x → 2.2.x`. `[INFERRED]`

`/usr/share/vx_ee.scm` is **byte-identical** in 1.5.0, 1.8.2 and `arch-harvest`
(13,134 bytes, `cmp` clean three ways). `[READ]` The expression-engine symbol
table did not change.

---

## 4. The specific things asked about

### 4.1 `modmatrix` — still absent from `las-sc`

`[READ]` The literal `modmatrix` occurs **0 times** in either `las-sc` binary.
Unchanged. Confirms the established architecture.

### 4.2 `/p/pre-expr` and `/p/post-expr` — unchanged, still one table entry each

`[READ]` `/p/pre-expr` is at file offset **1,977,663 in both binaries**;
`/p/post-expr` at **1,982,629 in both**. Both sit inside table C, which is inside
the identical prefix. `[READ]` The literal `expr` appears 6 times in each binary
— the same 6.

The prior report's finding that table C is dead code is therefore unaffected by
the update: `[INFERRED]` the table's bytes are unchanged and no instruction
changed, so whatever `las-sc` 1.5.0 did with `/p/pre-expr` (nothing), `las-sc`
1.8.2 does too.

### 4.3 The 115 `_m` twins — unchanged

`[READ]` 115 in both, identical strings at identical offsets, each still paired
with its symbol (`/p/o1/d_m` ↔ `o1d`, etc.).

### 4.4 `cv_output` / `voice_rule` — never in `las-sc`, in either version

`[READ]` occurrence counts across the whole binaries:

| token | `las-sc` 1.5.0 | `las-sc` 1.8.2 | `lassvc` 1.5.0 | `lassvc` 1.8.2 |
|---|---|---|---|---|
| `cv_settings` | 0 | 0 | 0 | 0 |
| `cv_output` | 0 | 0 | 0 | 0 |
| `voice_rule` | 0 | 0 | 0 | 0 |

**The CV-output namespace is not an `las-sc` endpoint and never was.** It lives
entirely in `las-frontend`: `[READ]` `/p/part/cv_settings` occurs 21,460 times in
`las-frontend` 1.5.0 and 21,464 times in 1.8.2.

This resolves the `voice_rule` puzzle. It is not that 1.5.0's `las-sc` lacks an
address 1.8.2's has — neither has it. `voice_rule` is a **`las-frontend` preset
key**, and 1.5.0's `las-frontend` does not implement it.

### 4.5 MIDI — nothing in `las-sc`, everything in XMOS

`[READ]` The literal `midi` occurs 21 times in each `las-sc` binary — the same 21.
`las-sc`'s only MIDI-shaped addresses are:

```
/p/part/midi/din-out/in
/p/part/rseq/0/in/midi/ch
/p/part/rseq/0/in/midi/en
/p/part/rseq/0/in/midi/note-max
/p/part/rseq/0/in/midi/note-min
/p/part/rseq/0/in/cv/0/en
/p/part/rseq/0/in/cv/1/en
/p/part/rseq/0/in/local/en
/p/part/rseq/0/in/usb
```

`[READ]` — identical set in both versions.

The MIDI work is in the XMOS images. `[READ]` `usr/share/xmosfw/`:

| | 1.5.0 | 1.8.2 |
|---|---|---|
| `app_las` | `v2.1.2.bin` | `v2.2.2.bin` |
| `app_vx` | `10M_v2.1.0.bin` | `10M_v2.2.1.bin` |
| `VERSIOND` | `33620735` | `33686271` |

`[READ]` `app_las_gitinfo.json`, the shipped commit metadata:

* 1.5.0: `c38fe650`, 2022-04-01, *"Merge branch 'dev/rick' … 1.5 Beta Bug fixes"*,
  `gitlab.com/moogmusic/las-fw!98`
* 1.8.2: `d888eec9`, **2025-09-11**, *"Merge branch 'fix-local-on-off' … Fix Local
  On/Off dumping held notes"*, `gitlab.inmusicbrands.com/moog/hardware/moog-one/las-fw!109`

`[READ]` `app_vx_gitinfo.json`:

* 1.5.0: `d309cf3b`, 2021-11-03, *"dev/luke/cvin/modw-pad"*, `vx-fw!42`
* 1.8.2: `02619910`, **2025-09-10**, *"Clamp min eg release"*, `vx-fw!45`

The XMOS `.bin` images are not analysable by `strings` — 294 and 291 "strings"
respectively, all high-entropy garbage, with no overlap. `[READ]` `[INFERRED]`
they are compressed or encrypted; their content was not read.

---

## 5. Where the namespace *did* change: `las-frontend`

`las-frontend` is the only component whose size changed meaningfully:
145,070,812 → 145,033,524 bytes (−37,288). `[READ]`

I extracted every distinct `/p/…` token from both binaries.

| | 1.5.0 | 1.8.2 |
|---|---|---|
| distinct `/p/…` tokens | 33,086 | 33,153 |
| **removed** | — | **0** |
| **added** | — | **67** |

`[READ]` The 67, in full — purely additive, nothing renamed:

| group | count | addresses |
|---|---|---|
| CV output voice rule | 4 | `/p/part/cv_settings/cv_output/{1,2,3,4}/voice_rule` |
| **CV outs as matrix variables** | 12 | `/p/part/t/{1,2,3}/p/modmatrix/vars/cvout{1,2,3,4}` |
| oscillator hard sync | 9 | `/p/part/t/{1,2,3}/p/o{1,2,3}/hardsync` |
| EG attack/decay/release sync | 27 | `/p/part/t/{1,2,3}/p/e{1,2,3}/{async,dsync,rsync}` |
| LFO rate sync | 12 | `/p/part/t/{1,2,3}/p/l{1,2,3,4}/fsync` |
| filter mode | 3 | `/p/part/t/{1,2,3}/p/fa/mode` |

These are **additions beside existing keys**, not renames. `[READ]` the per-module
key sets, timbre 1:

```
o1/  1.5.0: a a1 a2 b d fo knobs/po krst m m1…m8 oct pbdn pbup po pt scsrc sync1 sync2 sync3 tr
     1.8.2: … + hardsync                       (sync1/2/3 retained)
e1/  1.5.0: a ak d delay dk h knobs/… latch loop multi-trig r rk rst s sync tscale velmod
     1.8.2: … + async, dsync, rsync            (sync retained)
l1/  1.5.0: div f fmul knobs/… one_shot ph pno pol r rst rsts sm sync td tfin tfout tim var… w
     1.8.2: … + fsync                          (sync retained)
fa/  1.5.0: 1/bp 1/hp 1/lp 1/p 2/bp 2/hp 2/lp 2/p eg_p fm/idx fm/src lfo_p p p_fp par r
     1.8.2: … + mode
```

Corroboration that these names are genuinely new, not merely newly-spelled:
`[READ]` whole-binary occurrence counts in `las-frontend`,

| token | 1.5.0 | 1.8.2 |
|---|---|---|
| `hardsync` | **0** | 10 |
| `dsync` | **0** | 19 |
| `rsync` | **0** | 10 |
| `async` | 1 | 11 |
| `fa/mode` | **0** | 3 |
| `cvout1` | 1 | 4 |
| `voice_rule` | 1 | 5 |

The single 1.5.0 occurrences of `voice_rule`, `cvout1` and `async` are all in one
interned key-name list, not in any preset or code path. `[READ]` — context at
offset 132,394,690 in `las-frontend` 1.5.0:
`…cvin_2.expr_in_1.expr_in_2.sustain.cv_output.voice_rule./p/version …` (dots are
NULs). So 1.5.0 *knew the name* and did nothing with it.

### 5.1 The embedded INIT preset was migrated, version 6 → 14

`[READ]` `las-frontend` embeds exactly one `/meta/name "INIT"` preset blob:

| | 1.5.0 | 1.8.2 |
|---|---|---|
| offset | 143,838,219 | 143,840,307 |
| `/p/version` | **6** | **14** |

and the whole-binary distribution of `/p/version N` literals shifts by exactly one
blob: `{6: 370, 14: 75, …}` → `{6: 369, 14: 76, …}`. `[READ]`

All 67 new tokens occur **exactly once each**, inside that one migrated blob.
`[READ]` The 580 other embedded preset blobs (which carry
`/p/part/cv_settings/cv_output/1/max` and use the long `0.000000000000000000` float
serialisation) are unchanged and still carry **no** `voice_rule`. `[READ]`

`[INFERRED]` The 67 tokens are new preset-tree keys, and their presence in the
binary is evidence of the schema, not proof of a live OSC endpoint — `las-frontend`
is a WebKit application and builds most addresses by string concatenation, so
absence of a full literal path would not have proved absence of an endpoint either.
The zero-occurrence counts for `hardsync`/`dsync`/`rsync`/`fa/mode` in 1.5.0 are
the load-bearing evidence, not the preset blob.

### 5.2 The owner's live namespace confirms this from the other side

`[READ]` `captures/p-namespace-keys.txt` — the namespace dump taken from the
owner's own 1.5.0 instrument, 3,197 keys:

* `voice_rule`: **0 occurrences**
* `cvout`: **0 occurrences**
* `hardsync` / `dsync` / `fsync` / `rsync` / `/async`: **0 occurrences**
* `/p/part/cv_settings/cv_output/{1..4}/` — exactly four leaves each
  (`max`, `min`, `source`, `synth`), **16 total, no `voice_rule`**
* `/p/part/t/{1,2,3}/p/modmatrix/vars/var0…var9` — **30 total, no `cvout1…4`**

`[INFERRED]` After updating, that dump should grow to 3,264 keys (3,197 + 67),
with 5 leaves per CV output and 14 vars per timbre. This is a prediction, offered
for validation (§8).

### 5.3 …and the owner's presets already carry the 1.8.2 keys

`[READ]` `captures/MOOG ONE.db` (101.9 MB):

| pattern | count |
|---|---|
| `/p/part/cv_settings/cv_output/1/max` | 421 |
| `/p/part/cv_settings/cv_output/1/voice_rule` | **29** |
| `/p/part/t/1/p/modmatrix/vars/cvout1` | **29** (and 29 each for timbres 2 and 3) |
| `/p/version` distribution | `{6: 368, 8: 17, 10: 6, 14: 48}` |

`[READ]` `captures/SINGULARITY VOL 1 - GEOSYNTHS.db`: 6 presets with
`cv_output/1/voice_rule`, 18 with `cvout1`.

`[INFERRED]` **29 presets in the owner's library already carry `voice_rule` and
the four `cvout` matrix variables, and his 1.5.0 firmware has no code for either.**
Those fields are being stored and round-tripped but not acted upon.

---

## 6. Everything else in the two root filesystems

`[READ]` Manifest comparison, 6,036 vs 6,035 files:

* **Only two files change size meaningfully:** `las-frontend` (−37,288) and
  `las-sc` (+592). Every other size delta is between +8 and +64 bytes — the
  signature of a whole-distribution rebuild with slightly different build paths
  (`lsblk +16`, `udevd +24`, `Xorg +8`, `gdb +16`, `jsc +16`, `scsynth +16`, …).
* **`lassvc` is the same size (3,412,468) with a different md5.** Its string table
  is *identical* — 21,358 distinct strings in each, zero exclusive to either,
  including all 10,058 internal `f_<n>:lassvc_2escm` CHICKEN procedure names.
  `[READ]` The 187,578 differing bytes are the same content emitted in a
  different order. `[INFERRED]` `lassvc` 1.8.2 is a rebuild of identical source.
* **`usr/share/las-fx` and `usr/share/SuperCollider` are bit-identical.**
  `diff -rq` reports no differences. `[READ]` The synth graph, effects server,
  wavetables and all 210 synthdefs are unchanged.
* Byte-identical binaries: `las-dwm`, `las-watchdog`, `lasfwu`,
  `las-frontpanel-poll`. `[READ]`
* Files only in 1.8.2's `xmosfw`: `app_las_v2.2.2.bin`, `app_vx_10M_v2.2.1.bin`.
  Files only in 1.5.0's: the 2.1.x pair. `[READ]`
* `init.d`: only `S42sc` differs (§3.4). `[READ]`
* `init_sc_1.scd` is identical in 1.5.0, 1.8.2 and `arch-harvest`
  (`md5 d1cd672f039cc5116c5fc3adee09f302`). `[READ]` It still reads
  `options.blockSize = 128` / `hardwareBufferSize = 128` (lines 9–10) and
  `numWireBufs = 128` (line 13) in **1.8.2**. `[READ]` The stock block size is
  128 in the new firmware too.

---

## 7. Vendor release notes (for cross-checking, not as evidence)

`[READ]` from `captures/firmware-1.8.2/Moog One Firmware Update v1.8.2.pdf`
(text extracted from the PDF's own content streams). These are Moog's claims; I
report them because several map one-to-one onto what I measured.

> "Firmware v1.8.2 is a hot fix for v1.8.1 which focuses on bug fixes and
> improvements to Moog One's MIDI support."

v1.8.0's list, with the binary evidence beside it:

| release-note item | matches |
|---|---|
| "Fixed EG ATTACK SYNC, DECAY SYNC, and RELEASE SYNC not being MIDI mappable" | new `e{1,2,3}/{async,dsync,rsync}` |
| "Fixed LFO RATE SYNC not being MIDI mappable" | new `l{1..4}/fsync` |
| "Fixed changing OSC HARD SYNC through MIDI CC causing panel lag and crashes" | new `o{1,2,3}/hardsync` |
| "Fixed changing SVF filter mode via MIDI not being represented in the UI" | new `fa/mode` |
| "Improved INIT patch by setting all OSCs TRI by default to 0%…" | INIT blob migrated `/p/version` 6 → 14 |
| "Fixed USB descriptor to improve MIDI compatibility with Windows"; "Fixed crashes when receiving large amounts of MIDI data"; ARP/MIDI-out, MIDI PANIC, hanging notes | XMOS `app_las` 2.1.2 → 2.2.2 |

v1.8.1: "Fixed regression where some presets with oscillator hard sync enabled
were not loading correctly." v1.8.2: envelope-never-silent regression, and
KEYBOARD CONTROL ON stopping other synths' voices.

`[INFERRED]` Nothing in the release notes claims a new `las-sc` capability, and
nothing in the binaries contradicts them.

---

## 8. Validation plan — READ-ONLY, for a human to run on the instrument

Nothing below writes. Run **before** updating to capture the baseline, and again
after.

```sh
# 1. Confirm the running las-sc matches the on-disk 1.5.0 binary.
ssh moog 'md5sum /usr/bin/las-sc /usr/bin/lassvc /usr/bin/las-frontend'
#   expect 1.5.0: las-sc 7f5a3f21c21982e377c428330f633904
#   expect 1.8.2: las-sc 8de3f3334e332f1a732af1b71ac42589

# 2. Re-dump the live namespace and count the keys this report predicts.
#    (use the project's existing dumper, whatever produced p-namespace-keys.txt)
#    then, on the captured file:
grep -c .                      dump.txt     # 1.5.0: 3197   predicted 1.8.2: 3264
grep -c voice_rule             dump.txt     # 1.5.0: 0      predicted 1.8.2: 4
grep -c 'modmatrix/vars/cvout' dump.txt     # 1.5.0: 0      predicted 1.8.2: 12
grep -c hardsync               dump.txt     # 1.5.0: 0      predicted 1.8.2: 9
grep -cE '/(a|d|r)sync$'       dump.txt     # 1.5.0: 0      predicted 1.8.2: 27
grep -c 'fsync$'               dump.txt     # 1.5.0: 0      predicted 1.8.2: 12
grep -c 'fa/mode$'             dump.txt     # 1.5.0: 0      predicted 1.8.2: 3

# 3. Confirm the las-sc launch line and the XMOS images actually in use.
ssh moog 'cat /etc/init.d/S42sc | sed -n 4p; ls -l /usr/share/xmosfw/'

# 4. Confirm the stock block size on the updated instrument.
ssh moog 'sed -n "9,13p" /usr/share/las-fx/init_sc_1.scd'
#   expect blockSize = 128, hardwareBufferSize = 128, numWireBufs = 128

# 5. Confirm the XMOS versions the instrument reports (SETTINGS > UTILITIES),
#    or read them without touching anything:
ssh moog 'cat /usr/share/xmosfw/VERSIOND'      # 1.5.0: 33620735  1.8.2: 33686271
```

**Not proposed:** sending anything to `las-sc`. Nothing in this report requires a
write to establish it.

---

## 9. Conflicts with existing documentation

1. **`docs/arch/*` and `docs/firmware/las-sc-namespace.md` describe "the `las-sc`
   namespace" without a version qualifier.** That is now safe: it is the same
   namespace in 1.5.0 and 1.8.2. But the reverse inference is *not* safe —
   several of those documents were written from the 1.8.2 binary and cite 1.8.2
   file offsets, which are up to 597 bytes higher than the 1.5.0 offsets for
   anything past `.rodata+30711`. Offsets below that are common to both.

2. **The brief states "an 80-address `/p/part` slice".** I count **79** literals
   beginning `/p/part/`, and neither `/p/part` nor `/p` exists as a bare literal.
   `[READ]` (Note the 79 already includes `/p/part/t/`, which is a construction
   prefix rather than an address, so the count of real `/p/part` *addresses* is
   78 by the strictest reading.) `[UNKNOWN]` where the 80 comes from. Minor, but
   the number in circulation should be reconciled. The figure is identical in
   both firmware versions either way, which is what this report is about.

3. **The brief states "~536 `/p` addresses".** The authoritative figure is
   **534** distinct `/p…` literals in `.rodata`. `[READ]` A naïve `strings` pass
   yields 500 lines / 498 unique (the length-prefixed encoding hides some and
   merges others), and adding the false `/p` at offset 414,752 gives 535.
   `docs/firmware/las-sc-namespace.md` §4 already flags this and gives the
   correct authoritative counts as the decoded tables: 372 / 90 / 117.

4. **The brief states `voice_rule` "appears in 25 factory presets".** I count
   **29** records in `MOOG ONE.db` carrying
   `/p/part/cv_settings/cv_output/1/voice_rule`, plus 6 in
   `SINGULARITY VOL 1 - GEOSYNTHS.db`. `[READ]` The 25 may count a different set
   (factory-only, excluding user or downloaded content). Worth reconciling before
   the number is published.

5. **`captures/rootfs-1.5.0` has been written to by this project and is not a
   pristine 1.5.0 tree.** `[READ]` Five files carry 2026 mtimes:
   `etc/init.d/S99moogd` (2026-09-08 12:39 — this project's USB workbench
   launcher, and its own header says so), `sched_rt_runtime_us` (12:11),
   `etc/random-seed` (12:11), `etc/dropbear/dropbear_ecdsa_host_key`
   (2026-09-01), and `usr/share/las-fx/init_sc_1.scd` (12:49 — the re-harvested
   factory copy described in `arch-harvest/CAVEAT-runtime-state.md`).
   `usr/lib/ladspa/eventide_spring.so` is present in the 1.5.0 tree and absent in
   1.8.2; the caveat file names it as one of this project's additions, but its
   mtime is 2022-05-16. `[UNKNOWN]` whether it is stock.
   **None of this touches the conclusions here:** `las-sc` and `las-frontend`
   both carry 2022 mtimes, and `las-sc` is byte-identical to the live harvest.

6. **`firmware-1.8.2/rootfs-1.8.2` has also been written to today.** `[READ]`
   `mig150.asm` (124,719 bytes, 2026-09-08 21:35) is an `llvm-objdump` of
   `rootfs-1.5.0/usr/bin/las-frontend` left at the root of the 1.8.2 tree, and
   `.omc/state/**` are this tooling's session files. Neither is firmware. Anyone
   diffing the trees mechanically will see them as "new in 1.8.2"; they are not.

---

## 10. Should the owner update?

This section is judgement, and is graded as such.

**What the update does not change.** `[READ]` The `las-sc` OSC namespace — not
one address. The SuperCollider synth graph and every synthdef. The expression
symbol table `vx_ee.scm`. The block size (still 128). The `las-sc` launch line,
ports and flags. `lassvc`'s behaviour. `[INFERRED]` Any tool this project has
built against `las-sc`'s namespace, `/p/pre-expr`'s dead-endness, the `_m`
twins' read-only nature, and the flat-vs-hierarchical split will all behave
identically after the update.

**What it does change.** `[READ]` 67 new `las-frontend` preset keys — CV outputs
gain a `voice_rule` and become four addressable modulation-matrix variables
(`cvout1…4`) per timbre; EG attack/decay/release sync, LFO rate sync, oscillator
hard sync and filter mode become individually addressable. Three years of XMOS
firmware, whose changelog is dominated by MIDI fixes, in the one processor that
actually terminates MIDI.

**The specific argument for updating.** `[INFERRED]` 29 presets in the owner's own
library already carry `voice_rule` and `cvout1…4`; his firmware stores those
fields and ignores them. The `cvout` variables are the more interesting half —
they make the four CV outputs first-class destinations of the expression
language, which is squarely this project's subject matter and is not reachable on
1.5.0 at all.

**The specific risks.** `[UNKNOWN]` I have not established whether 1.8.2 rewrites
`/p/version 6` presets on load or on save, nor whether a v14 preset written by
1.8.2 can be read back by 1.5.0 — no migration code was located (searches for
`migrateTo*`, `PRESET_VERSION`, `CURRENT_VERSION` found nothing in either
binary). The owner's library is 368 × v6, 17 × v8, 6 × v10, 48 × v14. **Back up
`MOOG ONE.db` before updating**, and treat the update as one-way until the
downgrade path is tested. `[UNKNOWN]` I have not read the XMOS images, so their
2.1.x → 2.2.x delta is taken on the vendor's word.

**Recommendation.** `[INFERRED]` Update — but take the preset backup first. The
control surface this project reverse-engineers is untouched, so nothing built on
it breaks; the gain is a strictly larger namespace and three years of MIDI fixes
in the only place MIDI is handled.

---

## 11. Unexplored

* The XMOS `app_las` / `app_vx` images. Compressed or encrypted; not read. All
  MIDI-behaviour claims about the update rest on the vendor changelog, not on
  the binaries.
* Preset migration: where the v6 → v14 upgrade happens in `las-frontend`, whether
  it is destructive, and whether a downgrade to 1.5.0 is possible afterwards.
* The remaining `las-frontend` delta. I diffed its `/p/…` token set and the INIT
  blob; the other ~37 KB of size change (JS, UI, resources) was not examined.
* Whether the 67 new keys are live OSC endpoints or preset-file fields only.
  Distinguishing them requires a namespace dump from an updated instrument (§8).
* `scsynth` (+16 bytes) and `sclang` — assumed build noise from the size delta;
  not string-diffed.
* `usr/lib/ladspa/eventide_spring.so`'s provenance.
