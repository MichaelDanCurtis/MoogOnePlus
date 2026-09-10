# Binary diff: v1.5.0 → v1.8.2

Static diff of the four binaries named in the brief — `las-sc`, `las-frontend`,
`lassvc`, `las-watchdog` — plus the two XMOS firmware images they load, at the
level of sections, symbols/strings, and (where it was decidable) individual
functions.

The instrument was not contacted. Everything below comes from files on local disk.

**Grades.** `[READ]` — taken directly out of a named file at a named offset.
`[INFERRED]` — reasoning from stated evidence. `[UNKNOWN]` — not determined.

**Sources**

| what | path |
|---|---|
| v1.5.0 tree | `captures/rootfs-1.5.0/` (`etc/version` = `las-v1.5.0`) **[READ]** |
| v1.8.2 tree | `captures/firmware-1.8.2/rootfs-1.8.2/` (`etc/version` = `las-v1.8.2`) **[READ]** |
| live v1.5.0 `/p` key dump | `captures/p-namespace-keys.txt` (3,197 lines) **[READ]** |
| harvested binaries | `captures/arch-harvest/` |

`captures/arch-harvest/las-sc`, `las-frontend`, `las-watchdog`, `las-dwm` and
`lasfwu` are **MD5-identical to the corresponding files in `rootfs-1.5.0/usr/bin/`**
**[READ]**, so the owner's instrument was running exactly this 1.5.0 build and the
1.5.0 tree can be treated as its firmware. `lassvc` is not present in the harvest.

Toolchain used: `llvm-objdump --triple=armv7-none-linux-gnueabihf` from
`/Applications/Xcode.app/…/XcodeDefault.xctoolchain/usr/bin`, plus a small ELF
section reader and an `.ARM.exidx` parser written for this pass. **No Moog binary
was executed.**

---

## 0. Headline

**Three of the four named binaries did not functionally change.** `las-watchdog` is
byte-identical; `las-sc` and `lassvc` differ only by build nondeterminism, which is
demonstrated below rather than asserted. Every Linux-side change in 1.8.2 that this
pass could find is in **`las-frontend`** (git tag 2.0.8 → 2.1.4), and the MIDI work
named in the release notes is overwhelmingly in the **XMOS** images
(`lasvc` 2.1.2 → 2.2.2, `lasvx` 2.1.0 → 2.2.1), which are compressed and therefore
not symbol-diffable with the tools to hand.

---

## 1. Version manifest

`etc/git-tags` **[READ]** — 1.5.0 (left) vs 1.8.2 (right):

| key | v1.5.0 | v1.8.2 | binary changed? |
|---|---|---|---|
| `LAS_FRONTEND_GIT_TAG` | `2.0.8` | **`2.1.4`** | yes — real code change |
| `LAS_VX_GIT_TAG` | `lasvx-v2.1.0` | **`lasvx-v2.2.1`** | yes (XMOS voice card) |
| `LAS_FW_GIT_TAG` | `lasvc-v2.1.2` | **`lasvc-v2.2.2`** | yes (XMOS voice controller) |
| `LAS_SC_GIT_TAG` | `1.1.0r2` | `1.1.0r2` | binary hash differs, code does not — §2 |
| `LAS_FX_GIT_TAG` | `v1.1.1r4` | `v1.1.1r4` | `usr/share/las-fx/` is byte-identical **[READ]** |
| `LAS_SC_UGENS_GIT_TAG` | `master` | `master` | — |
| `LAS_FWU_GIT_TAG` | `v0.9.1` | `v0.9.1` | `lasfwu` byte-identical |
| `LAS_WATCHDOG_GIT_TAG` | `v0.2.0` | `v0.2.0` | `las-watchdog` byte-identical |
| `LAS_DWM_GIT_TAG` | `v0.3.0` | `v0.3.0` | `las-dwm` byte-identical |
| `LAS_VX_DSP_GIT_TAG` | `vxdsp-v1.0.0rc1` | `vxdsp-v1.0.0rc1` | — |

`usr/share/xmosfw/app_las_gitinfo.json` **[READ]** dates and identifies the two XMOS
merges the images were cut from:

* 1.5.0 → `c38fe65079f0231e…` 2022-04-01, *"Merge branch 'dev/rick' — 1.5 Beta Bug fixes"*, `gitlab.com/moogmusic/las-fw!98`
* 1.8.2 → `d888eec913efd792…` 2025-09-11, ***"Merge branch 'fix-local-on-off' — Fix Local On/Off dumping held notes"*, `gitlab.inmusicbrands.com/moog/hardware/moog-one/las-fw!109`**

`app_vx_gitinfo.json` **[READ]**:

* 1.5.0 → `d309cf3beeb1ada9…` 2021-11-03, *"dev/luke/cvin/modw-pad"*, `vx-fw!42`
* 1.8.2 → `0261991033c1a532…` 2025-09-10, ***"Merge branch 'clamp-min-eg-release'"*, `vx-fw!45`**

The *last commit in each XMOS repo before the release* is therefore a MIDI note-lifecycle
fix (`fix-local-on-off`, "dumping held notes") and an envelope-release clamp
(`clamp-min-eg-release`). Those titles map onto two of the claims in the brief —
hanging notes on port/channel change, and EG behaviour — **[INFERRED]**, from commit
titles, not from code.

Sizes and SHA-256 prefixes **[READ]**:

| file | v1.5.0 size / sha256[0:16] | v1.8.2 size / sha256[0:16] |
|---|---|---|
| `usr/bin/las-sc` | 2,498,948 `b550222efd4b576e` | 2,499,540 `11d24a64066e8323` |
| `usr/bin/lassvc` | 3,412,468 `c8cbad255704bf1b` | 3,412,468 `05d350382554ef23` |
| `usr/bin/las-frontend` | 145,070,812 `42670ca0c2b7dabf` | 145,033,524 `7b2ea057388c9155` |
| `usr/bin/las-watchdog` | 15,048 `08d8c27c43bb9420` | 15,048 `08d8c27c43bb9420` |
| `usr/bin/las_clock_demo` | 240,100 `1c9854f79e149d42` | 240,100 `fa84ccaf76b3f873` |
| `xmosfw/app_las_v2.*.bin` | 2,097,152 `ece76f084bbda035` | 2,097,152 `302e1edc0d47ee60` |
| `xmosfw/app_vx_10M_v2.*.bin` | 164,096 `1252d4583aa8ed8f` | 164,352 `55eb4f8c149b96a9` |

### The one launch-line change

`etc/init.d/S42sc` is the only init script that differs (the other 19 in `etc/init.d/` are byte-identical) **[READ]**. The whole diff is three tokens:

```
- --vxfw=/usr/share/xmosfw/app_vx_10M_v2.1.0.bin  --vcfw=…/app_las_v2.1.2.bin --vcfv=33620735
+ --vxfw=/usr/share/xmosfw/app_vx_10M_v2.2.1.bin  --vcfw=…/app_las_v2.2.2.bin --vcfv=33686271
```

`33620735 = 0x020102FF`, `33686271 = 0x020202FF` **[READ]** — the voice-controller
version `las-sc` expects, encoded `0xMM mm pp FF`, matching `lasvc-v2.1.2` and
`lasvc-v2.2.2` **[INFERRED]**. Same values in `usr/share/xmosfw/VERSIOND`.

---

## 2. `las-sc` — 592 bytes bigger, zero instructions changed

This is the strongest negative result in the pass, so the proof is given in full.

**Sections** (`.text` file offset 0x1650 in both) **[READ]**:

| section | v1.5.0 | v1.8.2 |
|---|---|---|
| `.text` | size **0x1DEF3C** @ VMA 0x11650 | size **0x1DEF3C** @ VMA 0x11650 |
| `.rodata` | 0x5E643 | **0x5E898** (+0x255 = +597) |
| `.data` | 0x22E20 @ 0x25EE38 | 0x22E20 @ **0x25F088** (+0x250) |
| `.bss` | 0x4090 @ 0x281C58 | 0x4090 @ **0x281EA8** |

`.text` is the same size at the same address and its MD5 differs. Diffed word by
word: **31,434 of 490,447 32-bit words differ** **[READ]**. Classifying each
differing word by what its *old* value pointed at:

| old value lands in | count |
|---|---|
| `.bss` | 21,911 |
| `.rodata` | 8,044 |
| `.data` | 1,458 |
| `.text` | 20 |
| `.got` | 1 |
| a small immediate / anything else | **0** |

Every single changed word is an address constant. **No opcode changed.** **[READ]**
The 20 `.text`-valued ones are literal-pool pointers into the identical 6-instruction
CHICKEN trampoline stubs at 0x11810/0x1182C/0x11848/… (verified by disassembly: the
stubs are byte-identical templates, and the change is a permutation of which one is
referenced) **[READ]**.

**Why `.rodata` grew by exactly 597 bytes.** `las-sc` is compiled CHICKEN Scheme and
its `.rodata` carries source-location strings baked with the compiler's temp
directory. That directory differs:

```
v1.5.0   /tmp/temp87f.4721/sc/fx.scm:126: set-insert!
v1.8.2   /tmp/temp113e.9287/sc/fx.scm:126: set-insert!
```

`grep -c` gives **597 strings containing the temp path in each build** **[READ]**,
and the new path is exactly one character longer. 597 strings × 1 byte = 597 bytes =
the entire `.rodata` growth. After normalising `/tmp/temp<hex>.<n>/` → `/tmp/TEMP/`,
the two `.rodata` string sets (14,120 strings each) are **identical — zero added,
zero removed** **[READ]**.

**`las-sc` v1.8.2 is v1.5.0 rebuilt in a directory with a longer name.** **[INFERRED]**,
from: identical git tag, identical `.text` size, all 31,434 deltas being address
relocations, and an identical normalised string set. Load-bearing: it means the
`/p` OSC surface and the `_m` semantics documented elsewhere in this repo are
unchanged in 1.8.2, and nothing in the MIDI fix list lives in `las-sc`.

`usr/bin/las_clock_demo` is the same story in miniature: **`.text` is byte-identical
(MD5 `1d632ac8…` in both)**, only `.rodata`/`.data` differ at identical sizes **[READ]**.

---

## 3. `lassvc` — five bytes, and they are not code

Same size in both (3,412,468). Section sizes are identical throughout; `.text`,
`.rodata` and `.data` differ in content **[READ]**.

**`.text` is 2,747,556 bytes and exactly 5 of them differ** **[READ]**, in three
32-bit words:

| VMA | v1.5.0 word | v1.8.2 word |
|---|---|---|
| `0x0012C734` | `0x000116E4` | `0x00011700` |
| `0x0012CA88` | `0x00011700` | `0x00011738` |
| `0x0012CD1C` | `0x00011738` | `0x000116E4` |

That is a **3-cycle permutation of three pointers**, and all three targets are inside
the same block of byte-identical CHICKEN stub templates near the start of `.text`
(the same construct as in §2) **[READ]**, embedded in data words rather than
instructions — the surrounding words (`0x03000002`, `0x00336D80`, …) are CHICKEN
procedure-info records, not ARM encodings. **No instruction in `lassvc` changed.**

`.rodata` has 154,403 differing bytes and `.data` 33,170, but the *string multisets
are identical*: 17,661 `.rodata` strings and 3,592 `.data` strings in each build,
with **zero added and zero removed** after sorting **[READ]**. The differences are
CHICKEN gensym numbering — strings of the form `f_14115:lassvc_2escm`,
`f_50410:lassvc_2escm` — laid out in a different order between builds **[READ]**.

**`lassvc` v1.8.2 is functionally identical to v1.5.0.** **[INFERRED]** This resolves
the `[UNKNOWN]` recorded at `docs/firmware/diff-files.md:396` ("187,578 differing
bytes at identical total size … Not individually explained").

---

## 4. `las-watchdog`, and the rest of the "unchanged" set

`usr/bin/las-watchdog` is **byte-identical** — MD5 `84d6cb7edc4adb7386976f9c5e4a49f4`,
SHA-256 `08d8c27c43bb9420…`, 15,048 bytes in both trees **[READ]**. So are
`las-dwm`, `las-fb-config`, `las-frontpanel-poll` and `lasfwu`, and the whole of
`usr/share/las-fx/` (SuperCollider sources, all 104 `.scsyndef` synthdefs, LADSPA
plugins, `init_sc_*.scd`) **[READ]**.

**Caution about "removed in 1.8.2".** A whole-tree MD5 comparison lists
`etc/init.d/S99moogd`, `usr/lib/ladspa/eventide_spring.so`, `etc/random-seed`,
`etc/dhcpcd.duid`, `etc/dropbear/dropbear_ecdsa_host_key`, `var/run/utmp` and
`sched_rt_runtime_us` as present only in 1.5.0. **`S99moogd` is this project's own
USB-workbench autostart script** — its header says so verbatim ("This is the only
file added to the root filesystem") **[READ]** — and
`captures/arch-harvest/CAVEAT-runtime-state.md` names `S99moogd` and
`eventide_spring.so` as project artifacts since removed **[READ]**. None of these
are Moog removals. The remaining `usr/lib/ladspa/*.so` (blackhole, hall, plate,
room, shimmer) are byte-identical in both trees **[READ]**.

---

## 5. `las-frontend` — where the Linux-side change is

Build stamps **[READ]** (strings present in one binary and absent in the other):

| | v1.5.0 | v1.8.2 |
|---|---|---|
| version | `2.0.8` | `2.1.4` |
| build date | `May 16 2022` `11:19:17` `051622-1116` | `Sep 15 2025` `14:57:57` `091525-1457` |
| git short id | `f77b0d82f` | `9144962cb` |

**Sections** **[READ]**: `.text` 0xA2B454 → **0xA2BBD4 (+1,920 bytes)**;
`.rodata` 0x7F45ADA → 0x7F3C122 (**−39,352**); `.ARM.extab` +124; `.ARM.exidx`
0x17870 → 0x17880 (**12,046 → 12,048 unwind entries**).

The binary is stripped (no `.symtab`), so functions were recovered from
`.ARM.exidx` — each entry's prel31 gives a function start, so consecutive entries
give function sizes — and named by the `.rodata` string pointers found in each
function's literal pools. All addresses below are virtual addresses in the
respective binary.

Whole-binary string diff: **286 strings added, 122 removed** (of 214k unique)
**[READ]**. After discarding binary noise, everything meaningful is listed in this
section.

### 5.1 New C++ class

```
*N12_GLOBAL__N_124GlideOnOffTriggerUpdaterE      (typeinfo name, 1.8.2 only)
```

**[READ]** — demangles to `(anonymous namespace)::GlideOnOffTriggerUpdater`. 1.5.0
already contains `(anonymous namespace)::GlideOnOffUpdater` **[READ]**; 1.8.2 has
both. No other class name was added or removed anywhere in the binary **[READ]**.

### 5.2 The MIDI-mappable destination table gained GLIDE ON and GLIDE RATE

The function at `0x0018AED0` (v1.5.0, 5,196 bytes) → `0x0018B280` (v1.8.2,
**5,328 bytes, +132**) builds the list of human-readable MIDI-map destination names
(`"LFO 1 RATE"`, `"OSCILLATOR 1 HARD SYNC"`, `"MIXER OSC 2 SVF"`, …). Extracting
every `.rodata` string it references: **165 names in 1.5.0, 167 in 1.8.2**, and the
sorted set difference is exactly two **[READ]**:

```
+ GLIDE ON
+ GLIDE RATE
  (nothing removed)
```

`"GLIDE ON"` is one of the 286 new strings in the binary; `"GLIDE RATE"` already
existed elsewhere in 1.5.0 but was not in this table **[READ]**.

### 5.3 The printed MIDI CC implementation chart gained a GLIDE section

The function at `0x008BFCFC` (9,724 B) → `0x008C0378` (**9,904 B, +180**) emits the
CC chart whose header row is
`"                  SYNTH 1         SYNTH 2         SYNTH 3           OPTIONS or CONTINUOUS"`
**[READ]**. Its referenced-string list goes 104 → 107 entries; the diff is **[READ]**:

```
+ GLIDE
+ On                
+  : OFF (0-8191) - ON (8192-16383)
+ Rate              
```

`"On                "` and `"Rate              "` (column-padded exactly like the
existing `"Waveform          "` / `"Rate Free         "` rows) are among the 286
new strings **[READ]**.

**Reading:** 1.8.x added GLIDE ON (a switch, split at 8192 of a 14-bit value) and
GLIDE RATE as MIDI-assignable destinations, with `GlideOnOffTriggerUpdater` as the
class that drives the switch. **[INFERRED]**, from the three independent pieces
above. This is *not* one of the release-note items in the brief.

### 5.4 New parameter-tree leaves: `hardsync`, `async`, `dsync`, `rsync`, `fsync`

Only three new leaf-name strings were interned in the whole 145 MB binary, adjacent
in the literal pool at file offsets 132,395,919 / 132,395,967 / 132,395,973 **[READ]**:

```
hardsync   async   rsync
```

`dsync` is the linker's tail-merge of `hardsync` (`"dsync\0"` occurs at
132,395,922 = `hardsync`+3, and nowhere else) **[READ]**. `fsync` reuses the
existing libc symbol name at offset 19,596 **[READ]**.

Following the 32-bit literal-pool references from `.text` to those strings and
mapping the referencing address back through `.ARM.exidx` puts each one in a
specific parameter-tree builder **[READ]**:

| v1.5.0 function | v1.8.2 function | referenced leaf names | what it builds |
|---|---|---|---|
| `0x00123F48` (1,776 B) | `0x00123784` (**1,856 B**) | `knobs scsrc pbup pbdn sync1 sync2 sync3 krst` **+ `hardsync`** | oscillator |
| `0x00123650` (2,296 B) | `0x00123EC4` (**2,596 B**) | `knobs multi-trig sync loop latch delay velmod tscale` **+ `async` `dsync` `rsync`** | envelope |
| `0x00124638` (4,036 B) | `0x001248E8` (**4,132 B**) | `knobs slow high fmul pulse var_* sync none trig rsts note tfin tfout one_shot` **+ `fsync`** | LFO |
| `0x00122C7C` (1,116 B) | `0x001232C4` (**1,216 B**) | `p_fp eg_p lfo_p` **+ `mode`** | filter-A / `fa` |

Note that `loop` and `latch` are **already present in the 1.5.0 envelope builder**
**[READ]** — EG LOOP and LATCH are not new parameters in 1.8.x, so any 1.8.x LOOP/LATCH
fix is a behaviour change behind an existing parameter, not a new one.

### 5.5 Two functions appeared and one vanished in the arpeggiator translation unit

The `.ARM.exidx` size sequence immediately preceding the function that contains the
`"ArpeggiatorTests"` / `"Pendulum mode"` / `"Up pattern [default mode]"` string block
**[READ]**:

```
v1.5.0  … 196, 184, 164,      140, 696, 952, [ArpeggiatorTests 3908]
v1.8.2  … 196,      164, 200, 188, 140, 696, 952, [ArpeggiatorTests 3912]
```

A 184-byte function was removed and two functions of 200 and 188 bytes were added,
net +204 bytes, immediately adjacent in link order to the arpeggiator test fixture
**[READ]**. Neither new function references any string, so they cannot be named.
That they belong to the arpeggiator module is **[INFERRED]** from link adjacency
only. This is the closest thing to the release notes' "ARP echo" that this pass
found, and it is not proof.

### 5.6 Complete list of the 43 changed functions

Recovered by diffing the `.ARM.exidx` function-size sequences with a
`difflib.SequenceMatcher` **[READ]**. The largest and the identifiable ones:

| v1.5.0 → v1.8.2 | size | identified by |
|---|---|---|
| `0x00103D44` → `0x00103D44` | 19,344 → **19,544** | `"RESERVED"`, `"CC 0"` … `"CC 127"`, `"SVF/LADDER MIX"`, `"MULTI TRIG"`, `"LOOP"`, `"LATCH"` — the MIDI-CC destination table constructor |
| `0x008BFCFC` → `0x008C0378` | 9,724 → **9,904** | MIDI CC chart printer (§5.3) |
| `0x0018AED0` → `0x0018B280` | 5,196 → **5,328** | MIDI destination-name table (§5.2) |
| `0x00611B7C` → `0x00612164` | 8,816 → **8,940** | no strings |
| `0x0046AB3C` → `0x0046B124` | 10,160 → **10,176** | `"PITCH BEND UP"`, `"LEGATO GLIDE"`, `"GLIDE TYPE"`, `"GATED GLIDE"`, `"GLISSANDO"`, `"X/Y HOLD"` — the keyboard/glide settings panel |
| `0x001BA968` → `0x001BAD98` | 2,668 → **2,796** | no strings |
| `0x001F074C` → `0x001F0CC8` | 3,908 → **3,912** | `"ArpeggiatorTests"` |
| `0x008C2CE4` → `0x008C34B0…` | 1,752 → 516+156+1,392 | no strings; split into three |
| — → `0x008C5F08` | new, 996 B | `" LASFrontEndApplication timerUIEvents"` |
| — → `0x0013D9DC`, `0x0013DA84`, `0x0013DABC`, `0x0013DAF4` | new: 168, 56, 56, 24 | no strings |

The 19 KB CC-destination-table constructor at `0x00103D44` grew by 200 bytes while
its referenced-string set stayed **identical (194 strings in each)** **[READ]**. So
it gained code but no new label. Instruction-level diffing of that function (with
branch and PC-relative-load immediates masked) shows insertions scattered across
`0x105950`–`0x108600` rather than one contiguous block **[READ]**; attributing them
to a specific CC destination was not achieved. **[UNKNOWN]**

---

## 6. The embedded INIT preset: `/p/version 6` → `/p/version 14`

`las-frontend` carries a factory INIT preset as one NUL-terminated OSC-dump blob
**[READ]**:

| | v1.5.0 | v1.8.2 |
|---|---|---|
| file offset | 143,838,219 | 143,840,307 |
| length | 155,569 B / 3,387 lines | 116,054 B / 3,260 lines |
| first field | `/meta/name "INIT"` | `/meta/name "INIT"` |
| `/p/version` | **6** | **14** |

Two things changed at once. Float formatting went from fixed 20-decimal to
shortest-round-trip (`120.00000000000000000000` → `120.0`;
`0.50000762939453125000` → `0.5000076293945312`) **[READ]**, which is essentially
all of the −39,352 `.rodata` shrink; and the field set changed.

### 6.1 Do not read the INIT-blob diff as a 1.8.x feature list

The 1.5.0 blob is **stale relative to its own runtime**. Checked against the live
v1.5.0 `/p` key dump (`captures/p-namespace-keys.txt`) **[READ]**:

| leaf | 1.5.0 INIT blob | **live 1.5.0 tree** | 1.8.2 INIT blob |
|---|---|---|---|
| `…/in/midi/en`, `…/in/midi/ch` | present | **0 occurrences** | absent |
| `…/in/din0/note-enable`, `…/in/usb0/note-enable` | absent | **6** (2 ports × 3 timbres) | present |
| `…/p/c/0` … `/p/c/127` | present (384 lines) | **0** | absent |
| `…/modmatrix/expressions` | present (`"mw c1 * l1po sto"`) | **0** | absent |
| `…/modmatrix/matrix_expression_slots` | absent | **3** | present, array form |
| `…/p/pan-spread`, `…/mix/ngate/gain`, `…/las-fx/spread` | absent | **3 / 3 / 1** | present |
| `stereoChorus`, `stereoFlanger` FX types | absent | **66 / 66** | present |
| `…/l1/knobs/r`, `…/arp/knobs/r`, `…/seq/knobs/r` | absent | **3 / 3 / 3** | present |

So the `/p/c/*` removal, the `midi/*` → `din0`+`usb0` split, the RPN-string →
`matrix_expression_slots` move, `pan-spread`, `ngate`, `stereoChorus`/`stereoFlanger`
and `knobs/r` were **already live on v1.5.0**. They appear in the INIT-blob diff only
because Moog regenerated the blob from a current tree in 2.1.4. **[INFERRED]**, from
the live dump above. Anyone diffing the two blobs naively will produce a wrong
1.8.x changelog; this is the trap in this dataset.

(`usr/share/las-fx/synthdefs/` already contains `stereoChorus_0..3.scsyndef` and
`stereoFlanger_0..3.scsyndef` in **both** trees, byte-identical **[READ]** — the DSP
for those effects is not new either.)

### 6.2 What is genuinely new in 1.8.2

Absent from the 1.5.0 binary **and** absent from the live 1.5.0 tree **[READ]**:

```
/p/part/t/{1,2,3}/p/o{1,2,3}/hardsync          false
/p/part/t/{1,2,3}/p/e{1,2,3}/async             false
/p/part/t/{1,2,3}/p/e{1,2,3}/dsync             false
/p/part/t/{1,2,3}/p/e{1,2,3}/rsync             false
/p/part/t/{1,2,3}/p/l{1,2,3,4}/fsync           false
/p/part/t/{1,2,3}/p/fa/mode                    false
/p/part/t/{1,2,3}/p/modmatrix/vars/cvout{1..4} 0.0
/p/part/cv_settings/cv_output/{1..4}/voice_rule "o"
```

(`vars/var0`…`var9` exist live on 1.5.0 — 3 each — so only the four `cvout` vars are
new **[READ]**.)

**`hardsync` is the strongest single hit on the release-note list.** The destination
name `"OSCILLATOR 1 HARD SYNC"` is in the MIDI destination table of **both**
versions **[READ]**, but the parameter node `hardsync` exists only in 1.8.2 and the
oscillator tree builder that creates it grew by 80 bytes. That the 1.5.0 UI offered
a CC destination with no `/p` leaf behind it, and 1.8.2 added the leaf, is a
plausible mechanism for "OSC hard sync via CC" — **[INFERRED]**, and worth stating
as a hypothesis rather than a finding.

Present in the live 1.5.0 tree but **absent from the 1.8.2 INIT blob**: `…/p/sus/mode`
and `…/p/sus/src` (3 each live) **[READ]**. Whether they were dropped from the tree
or only from preset serialisation is **[UNKNOWN]** without a live 1.8.2 dump.

### 6.3 Two defaults flipped

```
v1.5.0   /p/part/t/1/in/midi_out/din0/en false      /p/part/t/1/in/midi_out/usb0/en false
v1.8.2   /p/part/t/1/in/midi_out/din0/en true       /p/part/t/1/in/midi_out/usb0/en true
```

**[READ]**, in the INIT blob, for all three timbres. MIDI OUT is on by default in the
1.8.2 INIT preset on both ports. Relevant to "ARP echo" **[INFERRED]** — an
arpeggiator that echoes to MIDI OUT only becomes visible once MIDI OUT is on — but
this is a default value, not the echo logic.

---

## 7. XMOS: `app_las` 2.1.2 → 2.2.2 and `app_vx` 2.1.0 → 2.2.1

This is where the release notes' MIDI work has to be, given §§2–4, and it is the
part this pass could least resolve.

**Both images are compressed.** Shannon entropy over the non-zero extent: `app_las`
7.369 / 7.370 bits per byte, `app_vx` 7.189 / 7.170 **[READ]**. `strings` on either
image raw yields no readable text at all — zero occurrences of `Moog`, `XMOS` or
`One`, and no UTF-16LE runs anywhere **[READ]**.

**Structure of `app_las`** (2 MB flash image, non-zero content 253,552 B in 2.1.2 and
254,160 B in 2.2.2) **[READ]**:

| region | status |
|---|---|
| `0x000000`–`0x0000FF` | header; differs from offset 9 (word at `0x08` is `0x00C0FB00` vs `0x00C08700`) |
| `0x000100`–`0x0050FF` | **byte-identical at the same offsets** (~20 KB) — the boot stub / decompressor **[INFERRED]** |
| `0x005100` onward | compressed payload; no aligned block matches |

Bit-reversing every byte (per `docs/CORRECTIONS-2026-09-08.md` §1, which reported
descriptor strings "bit-reversed" at ~0x11c26) makes literal runs readable **[READ]**.
Confirmed by recovering the build stamps, which match `app_las_gitinfo.json` exactly:

```
app_las 2.1.2, bit-reversed, offset 175,246:  -v2.1.2-0-gc38fe65
app_las 2.2.2, bit-reversed, offset 175,245:  -0-gd888eec9        (the "2.2." is a back-reference)
```

`app_vx` yields **no** readable text even bit-reversed **[READ]** — but 1,341 of
2,563 sampled 32-byte windows of `app_vx` 2.1.0 occur verbatim somewhere in 2.2.1
**[READ]**, so it is packed, not encrypted. (For `app_las`, 1,401 of 3,956.)

### 7.1 The USB descriptors did not change

At bit-reversed offset `0x11B90` (2.1.2) and `0x11B98` (2.2.2) sits the USB
descriptor block **[READ]**:

```
0x11C10  "0200"  |  "A41163B0FFFE"  |  "LAS internal"  |  "Moog"
0x11CA0  12 01 00 02 EF 02 01 40  62 26  0D 80  00 00  01 05 00 01
         └ bLength 0x12, DEVICE, bcdUSB 0x0200, class EF/02/01 (IAD),
           EP0 64, idVendor 0x2662, idProduct 0x800D, bcdDevice 0x0000,
           iManufacturer 1, iProduct 5, iSerial 0, bNumConfigurations 1
0x11CB1  09 02 85 00 04 01 00 C0 00
         └ CONFIGURATION, wTotalLength 133, 4 interfaces, self-powered
```

The whole run **`0x00E10C`–`0x017809` in 2.1.2 equals `0x00E114`–`0x017811` in
2.2.2 — 38,653 consecutive identical bytes at a constant +8 offset** **[READ]**,
and the descriptor block above sits inside it.

**The enumerated USB descriptors for the `2662:800D` "LAS internal" device are
unchanged between `lasvc` 2.1.2 and 2.2.2.** **[INFERRED]** — the compressed bytes,
their LZ escapes, and the preceding 26 KB of match-window are all identical, so the
decompressed output for that stretch must be too.

**Caveat, and it matters for the release-note claim.** No descriptor set carrying
the product string `"Moog One"` was found in either image — `grep -c 'One'` is 0 in
all four images, raw and bit-reversed **[READ]**. The rear USB-B port that a computer
sees as "Moog One" therefore either has its descriptors elsewhere (a region that
does differ), or builds them at runtime. **[UNKNOWN]** So this does **not** refute
the release note's Windows-descriptor fix; it only shows the fix is not in the
internal-link descriptor block.

### 7.2 What is legible in the XMOS payload

Recovering literal runs from the bit-reversed images gives fragments of what looks
like the XMOS-side OSC/control vocabulary, present in **both** versions **[READ]**:
`note-enable`, `panic`, `transpose`, `local`, `thru`, `source`, `load-timbre`,
`set-group`, `voices`, `steal`, `chord`, `unison`, `stack`, `pitch-spread`,
`cc-filter-enable`, `sync-port`, `loopback`, `force-error`, `fan-duty`,
`therm/vx-temp-max`, `multi-trig`, `velmod`, `tscale`, `one_shot`, `fsync`, `delay`,
`flink`, `#bundle`, `Not found`, `Malformed message`, `Unavail…`,
`200 Read from flash`, `Write to flash complete`, `Moog Music, Inc.`,
`Internal Clock` / `MIDI` / `Clock Selector`.

`panic`, `note-enable`, `local`, `thru` and `cc-filter-enable` all exist in the
**2.1.2** image already **[READ]** — the MIDI PANIC and Local On/Off mechanisms are
not new in 1.8.x, consistent with the release notes describing them as *fixes*.

**No further XMOS conclusions are available from this material.** The literal runs
break at LZ match boundaries that differ between builds (2.1.2 uses escape bytes
`0xAD`/`0xB5`/`0xDF` in the late payload where 2.2.2 uses `0xDF`/`0xE7`/`0xB5`
**[READ]**), so apparent added/removed fragments in that region are compression
artifacts, not content. Diffing XMOS symbols requires decompressing the payload, and
`llvm-objdump` has no xcore target. **[UNKNOWN]**

---

## 8. Scorecard against the release-note claims in the brief

| claim | where the evidence points | grade |
|---|---|---|
| USB descriptor for Windows | **Not** in the `2662:800D` "LAS internal" descriptor block, which is byte-identical (§7.1). Descriptors for the rear "Moog One" port not located in either image. | `[INFERRED]` / `[UNKNOWN]` |
| Crashes on large MIDI input | Nothing found. Not in any Linux binary (§§2–4). Buffer sizes are inside the compressed XMOS payload. | `[UNKNOWN]` |
| OSC hard sync via CC | `hardsync` is a **new** `/p` leaf in the 1.8.2 oscillator tree builder (`0x00123784`, +80 B) and is absent from both the 1.5.0 binary and the live 1.5.0 tree, while the destination name `"OSCILLATOR 1 HARD SYNC"` existed in 1.5.0. | leaf `[READ]`, causal story `[INFERRED]` |
| Hanging notes on port/channel change | The last `las-fw` commit before the release is literally *"Fix Local On/Off dumping held notes"* (`!109`, 2025-09-11). The per-port `note-enable` leaves already existed on 1.5.0, so the fix is behavioural, inside XMOS. | commit `[READ]`, attribution `[INFERRED]` |
| MIDI PANIC triggering A5 | A `panic` token exists in **both** XMOS images. No Linux-side change. | `[UNKNOWN]` |
| EG LOOP / LATCH | `loop` and `latch` are in the **1.5.0** envelope builder — not new. 1.8.2 adds `async`/`dsync`/`rsync` to the same function (+300 B). `app_vx`'s last commit is *"clamp-min-eg-release"*. | leaves `[READ]`, link to the claim `[INFERRED]` |
| ARP echo | One 184-byte function removed and two (200 B, 188 B) added, in link order immediately before `ArpeggiatorTests`; and `midi_out/{din0,usb0}/en` default flips false → true. Neither new function references a string. | sizes and defaults `[READ]`, module identity `[INFERRED]` |
| *(not in the brief)* GLIDE ON / GLIDE RATE became MIDI-mappable | Three independent traces: `+2` entries in the destination table, a new `GLIDE` block in the CC chart, and the new class `GlideOnOffTriggerUpdater`. | `[READ]` |

---

## 9. Conflicts with existing docs

1. **`docs/firmware/diff-files.md:396`** records `usr/bin/lassvc` as `[UNKNOWN]` —
   "187,578 differing bytes at identical total size … Not individually explained".
   §3 explains it: 5 differing `.text` bytes forming a 3-cycle of stub pointers, and
   `.rodata`/`.data` differences that are CHICKEN gensym renumbering with an
   identical string multiset. Not a contradiction; a resolution.

2. **`docs/CORRECTIONS-2026-09-08.md` §4** says the RPN `expressions` form is "true
   only for `/p/version ≤ 12`" and that version 14 is "this instrument". The
   instrument runs **v1.5.0**, whose `las-frontend` embeds an INIT preset stamped
   `/p/version 6` **[READ]**. Both statements can be true — the *live tree* on 1.5.0
   already uses `matrix_expression_slots` and has zero `/expressions`
   (`p-namespace-keys.txt`) **[READ]** — but "version 14 — this instrument" is
   loose: 14 is what the **1.8.2** binary's INIT blob is stamped with, and the
   version the owner's instrument actually writes was not determined here.
   The blob version and the runtime schema are different things (§6.1).

3. **Task brief** states `las-sc` owns "~536 `/p` addresses".
   `docs/firmware/diff-files.md:414` counts 497 in both versions. This pass did not
   recount, but confirms the count cannot differ *between* versions, since `las-sc`'s
   `.rodata` string set is identical (§2).

4. A whole-tree diff that does not filter project artifacts will report
   `etc/init.d/S99moogd` and `usr/lib/ladspa/eventide_spring.so` as "removed by
   Moog in 1.8.2". Both are this project's own additions to the 1.5.0 tree (§4).

---

## 10. Validation plan — READ-ONLY, for a human to run

None of these were run. All are read-only; none writes, calibrates or resets.
Nos. 1–3 confirm this report against the owner's current (v1.5.0) instrument;
nos. 4–6 are only meaningful after an update to 1.8.x.

```sh
# 1. confirm the instrument's build matches captures/rootfs-1.5.0
cat /etc/version; cat /etc/git-tags
md5sum /usr/bin/las-sc /usr/bin/lassvc /usr/bin/las-watchdog /usr/bin/las-frontend
#    expect las-sc 7f5a3f21c21982e377c428330f633904
#           las-watchdog 84d6cb7edc4adb7386976f9c5e4a49f4

# 2. confirm the XMOS images and the version las-sc is told to expect
cat /usr/share/xmosfw/VERSIOND            # expect 33620735 on v1.5.0
cat /usr/share/xmosfw/app_las_gitinfo.json
grep -n vcfv /etc/init.d/S42sc

# 3. confirm §6.2 on v1.5.0: these leaves must NOT exist yet.
#    Run from the host over OSC to las-frontend, read-only query only:
oscsend localhost 7770 /p/part/t/1/p/o1/hardsync      # expect no such address
oscsend localhost 7770 /p/part/t/1/p/e1/async         # expect no such address
#    or, better, re-dump the whole namespace the way p-namespace-keys.txt was made
#    and grep it offline.

# ---- after an update to 1.8.x only ----
# 4. the new leaves should now resolve
#    grep a fresh namespace dump for: hardsync async dsync rsync fsync fa/mode
#                                     modmatrix/vars/cvout1 cv_output/1/voice_rule
# 5. do /p/part/t/N/p/sus/mode and /sus/src still exist?  (§6.2, currently UNKNOWN)
# 6. in SETTINGS ▸ MIDI map, look for GLIDE ON and GLIDE RATE as assignable
#    destinations (§5.2/§5.3) — UI observation, no command needed.
```

To reproduce the binary work itself, nothing needs the instrument:

```sh
# section-level compare
python3 elfsec.py list captures/rootfs-1.5.0/usr/bin/las-sc
python3 elfsec.py list captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/las-sc

# the las-sc no-op proof
strings -a captures/rootfs-1.5.0/usr/bin/las-sc | sed -E 's#/tmp/temp[0-9a-f]+\.[0-9]+/#/tmp/TEMP/#g' | sort -u > a
strings -a captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/las-sc | sed -E 's#/tmp/temp[0-9a-f]+\.[0-9]+/#/tmp/TEMP/#g' | sort -u > b
diff a b        # expect empty

# the XMOS descriptor block
python3 -c "
t=bytes(int('{:08b}'.format(i)[::-1],2) for i in range(256))
open('las18.rev','wb').write(open('captures/firmware-1.8.2/rootfs-1.8.2/usr/share/xmosfw/app_las_v2.2.2.bin','rb').read().translate(t))"
xxd -s 0x11b98 -l 464 las18.rev
```

---

## 11. Not done

* The 200 added bytes inside the MIDI-CC destination-table constructor at
  `0x00103D44` are located but not explained (§5.6).
* The 43 changed `las-frontend` functions are enumerated; only 6 are named. Vtable
  and typeinfo chasing would name more.
* `app_las` / `app_vx` were not decompressed. That is the single highest-value
  remaining step: it would turn every `[UNKNOWN]` in §8 into a real answer. The
  ~20 KB byte-identical stub at `0x000100`–`0x0050FF` in `app_las` is the
  decompressor and is the place to start; `docs/arch/decompressor.md` may already
  cover it.
* Where the rear USB-B "Moog One" descriptors live was not found (§7.1).
* `boot/uImage` differs between versions (both report `Linux-4.1.15-rt18`); the
  kernel was not diffed here — see `docs/firmware/kernel.md`.
* `/p/part/t/N/p/sus/{mode,src}`: present live on 1.5.0, absent from the 1.8.2 INIT
  blob; removed from the tree or only from serialisation is undetermined.
