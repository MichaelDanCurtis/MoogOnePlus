# Where new features can physically go

An honest map of this instrument's extension surface: every place a new capability
can be added, what it costs while the instrument is playing, whether it survives a
power cycle, whether it survives a firmware update, and what happens when it goes
wrong.

**The owner's instrument is stock.** It was restored to stock on 2026-09-07 and it
may be worth keeping that way. Several surfaces below are free — they write nothing
to the machine at all — and several require modifying a root filesystem that Moog's
own updater will overwrite. That distinction is the spine of this document, so it is
in every table.

## How to read the evidence grades

* **[TESTED]** — someone ran it on this instrument and observed the result.
* **[READ]** — read directly out of a file, a binary or a database on disk, with the
  path and line/offset given.
* **[INFERRED]** — reasoning from graded facts. Say so and stop.
* **[UNVERIFIED]** — asserted by an earlier document or by the assignment brief, with
  no primary source on this disk. Kept because it is probably right and because
  hiding it would be worse, but not to be built on without checking.

Nothing in this document was learned by touching the instrument. Everything is from
`captures/**`, the preset databases, the firmware package, and the ten prior arch
reports.

---

## 0. The summary table

Ranked by **value per unit of risk** — see §15 for the reasoning behind the order.

The first column is a **rank**, not a section number; the section is in the second.

| rank | Surface | What can go there | Runtime cost | Survives reboot | Survives firmware update | Worst case / recovery |
|---|---|---|---|---|---|---|
| 1 | **Presets** (`.m1p` text / SQLite) — §2 | Any value at any of 3,197 `/p` addresses, per preset | none | yes | **yes** — `/var` is a separate partition | one bad preset; delete it |
| 2 | **Modulation matrix / expression engine** — §3 | 20 rows/timbre over a 48-source × 44-transform × 141-destination space, on the XMOS | **zero i.MX6 cost** | yes | yes | one bad preset; delete it |
| 3 | **The back panel** — §8 | EXT INPUT, 4 insert jacks, 4 CV out, 2 CV in, 2 expression, MIDI | zero — analog | yes | yes | unplug the cable |
| 4 | **`/p` OSC live** — §7 | External control surface, sequencing, automation | negligible | n/a (live) | yes | stop sending |
| 5 | **Effect presets** (169 factory rows) — §2 | Named parameter sets + 2 panel-knob assignments per effect type | none | yes | yes | delete the row |
| 6 | **USB drive + one init file** — §9 | Any static ARM binary, any web UI, any data | cpu0 only | yes | **no** — one rootfs file | delete `/etc/init.d/S99moogd` |
| 7 | **`/fxN "<sclang>"`** — §5.1 | Arbitrary SuperCollider in the live audio engine | as written | **no** | n/a | crashes `scsynth`; `S42sc restart` |
| 8 | **New `.scsyndef` files / sclang classes** — §5.2 | New effect algorithms, loaded at boot | cpu1, budgeted | yes | **no** | slot fails silently; delete the file |
| 9 | **New LADSPA `.so`** — §6 | Native DSP, callable from a SynthDef | cpu1, budgeted | yes | **no** | plugin not found → SynthDef fails |
| 10 | **Editing `/usr/share/las-fx/*.scd`** — §5, §11 | Anything in the engine, at boot | as written | yes | **no** | a syntax error boots an instrument with **no effects at all** |
| 11 | **`las-frontend --script=`** — §10 | JavaScript with OLED, panel, LED and OSC access | cpu0 | no (flag) / yes (edit `S43gui`) | **no** | **has a calibration-write API** |
| 12 | **A signed firmware package** — §12 | Everything | — | yes | it *is* the update | bricks a slot; fall back to `p2` |

---

## 1. The layer map, and why it decides everything

Three processors, three completely different extension economics.

```
  XMOS voice controller + 16 voice cards      the modulation expression engine
  (203.0.113.2, own flash, ANALOG voices)     ── free at i.MX6 runtime
            │  ESAI/TDM audio (XMOS is clock master)
            │  USB gadget: control only
            ▼
  i.MX6 DualLite, 2 cores, 512 MB
     cpu0  las-frontend, X, las-dwm, las-sc   ── shared core: UI, control, web
     cpu1  scsynth audio thread, FIFO 99      ── isolcpus=1; DO NOT put work here
            │
            ▼
  8 DAC channels → main / sub / aux1-4        the analog back panel
```

**The single most important budgeting fact.** `cpu1` is not spare. `isolcpus=1`
reserves it and Moog's patched `SC_AlsaDriver` pins the audio thread there at
`SCHED_FIFO` 99 (`docs/CLAIMS-AUDIT.md`, "Wrong, and retracted"). Anything that
touches `scsynth` — a new SynthDef, a LADSPA plugin, an `interpret`ed expression —
spends cpu1. Anything else spends cpu0, where it competes with the UI and the panel
but not with the DSP.

**And the cheapest place in the whole machine to add behaviour is not on the i.MX6
at all.** The modulation expression language runs on the XMOS. See §3.

---

## 2. Presets — the surface with no cost and no footprint

**[READ]** A preset is a plain-text file of `<osc-address> <value>` lines.
`captures/firmware-1.8.2/corpus/Moog One v1.8.2/Past Preset Packs/CLASSICS/SWEET DREAMS.m1p`
is `ASCII text`, 4,081 lines, 183,645 bytes, beginning:

```
/meta/name "SWEET DREAMS"
/meta/comment "BASS, BRASS ARP & LEAD.\n\nPRESS C3 TO START..."
/meta/type "SPLIT"
/meta/category "CLASSIC"
/meta/mood "NOSTALGIC"
/meta/group "CLASSICS"
/meta/synth1name "E - LEAD LINE"
/meta/synth2name "E - BRASS ARP"
/meta/synth3name "E - BASS"
/p/version 8
/p/clk/rate 125.00000000000000000000
...
```

**[READ]** The library is a stock SQLite 3 database. `captures/MOOG ONE.db`
(101,920,768 bytes) and `captures/SINGULARITY VOL 1 - GEOSYNTHS.db` both carry the
same eleven tables:

| table | rows in `MOOG ONE.db` | shape |
|---|---|---|
| `presets` | 398 | `id, timestamp, name, comment, synth1Name, synth2Name, synth3Name, data TEXT` |
| `effects_presets` | 169 | `id, timestamp, type, name, data TEXT`, unique on `(type, name)` |
| `snapshots` | 31 | `presetId → presets(id) ON DELETE CASCADE, type, comment, data` |
| `sets` | 64 | `setNumber, bankNumber, presetNumber, presetId` |
| `global` | 1 | one row, key `settings`, 127,710 bytes of `/m/settings/...` |
| `mod_matrix_presets` | **0** | `name, comment, data` — the table exists, nothing uses it |
| `midi_map_presets` | **0** | same |
| `sequence_presets` | **0** | same |
| `tags`, `preset_tags`, `set_descriptions` | — | |

`data` in every one of these is the same `<address> <value>` text. The `INIT` preset's
`data` is 114,427 bytes / **3,197 lines** — which is exactly the line count of
`captures/p-namespace-keys.txt`, confirming that file's provenance as a preset dump.

**[READ]** Address distribution inside one preset:

| prefix | lines |
|---|---|
| `/p/part/t` (three timbres) | 2,362 |
| `/p/part/las-fx` (the two bus effects) | 611 |
| `/p/part/tuning` | 132 |
| `/p/part/cv_settings` | 37 |
| `/p/part/midi_io` | 17 |
| `/p/lc/kbd` (left-hand controller) | 19 |
| everything else | 19 |

### (a) What can be added

Any value at any of the 3,197 addresses, and the mapping is total: everything the
panel can do, a preset file can say. Three empty tables — `mod_matrix_presets`,
`midi_map_presets`, `sequence_presets` — are declared, indexed and unused by the
entire factory library, which means the firmware has UI paths for saving named
mod-matrix, MIDI-map and sequence presets that nobody has ever populated.

### (b) Runtime cost

None. A preset is data the instrument already loads.

### (c) Survives a reboot

Yes.

### (d) Survives a firmware update

**Yes.** `captures/arch-harvest/fstab` puts `/var` on `/dev/mmcblk2p6`, a partition
of its own, and `docs/DANGER.md` records the preset databases at `/var/las-frontend`
(~280 MB). The updater (`captures/arch-harvest/lasfwu`) `dd`s an image onto
`/dev/mmcblk2p2` or `p3` only. `/var` is never written.

### (e) What breaks, and recovery

One preset. Delete the row or the file. The only sharp edge is the `sets` table's
`ON DELETE CASCADE` on `presetId` — deleting a preset silently unbinds it from every
set/bank/program-change slot that referenced it.

**Caveat, [UNVERIFIED]:** the import path (USB → instrument) has not been exercised
by this project for a hand-authored `.m1p`. The firmware release notes for 1.8.2
describe the USB drive being read for firmware; preset import over USB is documented
in the manual and is how the factory packs ship, but no one here has written a file
and watched it load.

---

## 3. The modulation expression engine — the cheapest place in the machine

This runs on the XMOS voice controller. It costs the i.MX6 nothing, it is carried
inside presets, and it therefore inherits every persistence property of §2: survives
reboot, survives firmware update, removable by deleting one preset.

**It is also the surface where this project's understanding was most incomplete, and
one framing has to be corrected before anything else.**

### 3.1 `expressions` is a legacy field. The current schema is compiled slots.

**[READ]** Every preset carries `/p/version`. Splitting all three corpora by it:

| corpus | versions | carries |
|---|---|---|
| 222 factory `.m1p` (1.8.2) | v7×18, v8×29, v10×45, v11×1, v12×29, **v14×100** | v≤12 → `expressions`; v14 → `matrix_expression_slots` |
| `captures/MOOG ONE.db` (398) | v6×368, v8×1, **v14×29** | same |
| `captures/SINGULARITY…db` (129) | v10×126, **v14×3** | same |

**No preset in any corpus carries both**, and `grep -c "/expressions$" captures/p-namespace-keys.txt` returns **0** — the live host tree has `matrix_expression_slots`, `seq_expression_slots`, `vars/var0..var9`, `entry/N/*`, `name`, `comment`, and **no `expressions` leaf**. `las-frontend` carries no `"expressions"` code literal at all: of 1,517 byte occurrences, 1,515 are inside embedded legacy preset text and two are SQLite's own error strings. `las-sc` has none.

**So `/p/part/t/N/p/modmatrix/expressions` is a legacy preset-file field (schema ≤ 12),
not a live address on current firmware.** The RPN text remains the best window onto
what the engine can do — it is the same engine — but a preset written today is
written in slots.

**[READ] The compiled slot record is a flat array of 7-token groups:**

```
[ src_id, src_a, ctl_id, ctl_a, tr_id, tr_a, dst_id ]
```

verified by aligning `entry/0` against the array in
`captures/firmware-1.8.2/corpus/…/TRANSFORMERS/NIGHT PASSAGE.m1p`:
`[3, 0.5527684688568115, 48, 1.0, 43, 0.0, 27]` ↔ `src "VELOCITY"`,
`src_a 0.5527684688568115`, `ctl ""`, `ctl_a 1.0`, `tr ""`, `tr_a 0.0`,
`dst "/p/part/t/1/p/e1/d"`.

The live engine-side endpoints on the voice controller are `/p/pre-expr`,
`/p/post-expr` and `/p/c` (`captures/sysmap/addrs-p.txt:1, 460-461`;
`captures/sysmap/osc-namespace.txt:725-726` **[READ]**). Whether any of the three
accepts a program is **unknown**.

### 3.2 The symbol table, recovered

`/usr/share/vx_ee.scm` — 13,134 bytes, `-rw-r--r--`, read directly out of
`captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz` **[READ]**. It is loaded at
boot by `/etc/init.d/S42sc:4` via `las-sc --expr-syms=/usr/share/vx_ee.scm`. Its own
header:

> The mod sources variables, m0..m63, are intended for external controls. MIDI
> controllers can be mapped to these. […] parms contains the c0..c31 variables,
> "expression constants" intended for adjustable modulation amounts, and intended for
> saving with presets. […] vars contains the general-purpose variables v0..v63. They
> are intended for state storage, as needed by SPFs, LFOs, the LFSRs, etc. They are
> **not saved in presets**.  — `/usr/share/vx_ee.scm`, (c) 2018 Moog Music Inc.

⚠ **The prose and the declarations disagree. Trust the declarations.** The file
actually declares:

| section | declaration | meaning |
|---|---|---|
| `args` | `(m (array 16))` + 30 named symbols | **46 read-only sources** |
| `parms` | `(c (array 128))` | **128 constant registers**, saved with presets |
| `vars` | `(v (array 16))` | **16 general-purpose variables**, *not* saved in presets |
| `results` | 126 named symbols | **126 destinations** |

This settles the register-file question. The brief's inference — "43 registers used and
`c64` appears, so the file is at least 65 wide" — is right in direction and short in
magnitude. **It is 128.** Corroborated independently at
`docs/INTERNAL-DO-NOT-DISTRIBUTE.md:117`, recorded from an earlier on-device read.

**The 46 sources.** `m0…m15` (the 16 external/MIDI-mappable slots), then
`gate`, `v` (velocity), `p` (base pitch), `mw`, `pw`, `padx`, `pady`, `a`
(aftertouch), `padz`, `padg`, `cvin1`, `cvin2`, `expr1`, `expr2`, `sus`,
`l1`–`l4`, `e1`–`e3`, `en`, `rnd`, `rndb`, `pp` (processed pitch),
`ktc` (key-track centre), `pnt` (key track normalised, `(pp-ktc)/120`),
`pto` (key track in octaves, `(pp-ktc)/12`), `vspr` (voice spread).

Two of these are worth pulling out:

* **`cvin1`, `cvin2`, `expr1`, `expr2`, `sus` are first-class expression sources**, and
  the file states their scaling explicitly: *"CV quantities are the actual measured
  voltages divided by 5"* — which independently confirms the **±5 V** range derived
  from the calibration panels in §8.4.
* **`m0…m15` are unused by the entire factory library** and are documented as the
  MIDI-mappable general-purpose inputs. Sixteen free modulation inputs.

**The 126 destinations**, by family: 4 LFOs × 6 (`lNf, lNpno, lNv, lNdm, lNfim,
lNfom`) = 24; 3 EGs × 7 (`eNdlm, eNam, eNhm, eNdm, eNs, eNrm, eNtm`) = 21; noise
envelope × 4; global pitch `oct, po, pno, l1po, e3po, l3od, l3pd` = 7; `ofm` (the FM
macro route) = 1; 3 oscillators × 10 (`oNpno, oNo, oNpo, oNfo, oNd, oNtr, oNang, pNd,
oNbal, oNfm`) = 30; `nsbal`; the mixer `mixo1 mixo2 mixo3 mixrm mixn` **`mixext`** = 6;
five filter blocks × 3 (`pn, r, fm`) = 15; `fbal`; five EG→cutoff (`fegpn faegpn
fa1egpn fa2egpn fbegpn`) = 5; five LFO→cutoff (`flpn falpn fa1lpn fa2lpn fblpn`) = 5;
**`fxb1s`, `fxb2s` (bus effect sends 1 and 2)** = 2; `vca`; `main`, `pan`; `sustain`.

**The factory library uses 71 of those 126.** Fifty-five destinations exist that no
factory preset has ever touched — including `mixext` (external input level, §8.2) and
`fxb1s`/`fxb2s`, which put the two digital effect sends under modulation control at
zero i.MX6 cost.

Note the compiled-in table inside `las-sc` is **not** the authority: between
`/p/pre-expr` and `/p/post-expr` it holds 115 `(token, /p/…_m address)` pairs with 105
unique tokens **[READ]**, and **14 tokens the factory presets actually use are absent
from the binary entirely** (`e1tm e2tm ensam ensrm l1pno l2pno l3pno l4pno nsbal
o1pno o2pno o3pno ofm pno` — `o1pno` is used 24 times in factory content). The runtime
`.scm` file is the symbol table; the binary's table is a subset used for the `_m`
OSC bridge.

### 3.3 The measured caps — reproduced across three independent corpora

**[READ]**, and this is the strongest part of the evidence because the numbers
reproduce:

| quantity | 222 `.m1p` | `MOOG ONE.db` (398) | agree? |
|---|---|---|---|
| max `entry/N` index | **19** → 20 rows | **19** → 20 rows | ✔ |
| max `sto` in one expression | **14** | **14** | ✔ |
| highest constant register | **`c64`** | **`c64`** | ✔ |
| max `matrix_expression_slots` length | **119** = 17 × 7 | **119** = 17 × 7 | ✔ |
| longest `expressions` string | **414 chars / 104 tokens** | 379 chars | — |
| max simulated stack depth | 16 | — | — |
| `seq_expression_slots` non-empty | **0** | **0** (four `null`s, no arrays) | ✔ |

**20 rows is the row cap, and 17 is the compiled-slot cap** — muted or empty rows do
not compile. Nothing in `las-frontend` states a row cap as a string; mod-matrix entry
nodes are created dynamically (`ModMatrixPanel::createNewEntry`,
`::deleteFocusedEntry` at `0x7e45ca1`–`0x7e45e8a` **[READ]**), which is also why
`captures/p-namespace-keys.txt` shows only `entry/0` and `entry/1` — that dump was
taken with two rows instantiated, not because two is the limit.

**Why `c64` is the ceiling in practice, and why that is not the register file.**
The compiler allocates **three constant registers per matrix row** — `c1`, then
`c5, c8, c11, c14, …` (`5 + 3k`) as the amount register **[INFERRED, from the
allocation pattern across 981 expressions]**. Twenty rows × 3 ≈ 60, and `c64` is the
highest ever seen. The observed maximum is a consequence of the 20-row cap, not of
the register file, which is 128.

**Maximum expression length and maximum statement count: unknown.** `strings` on
`las-sc` for `too many|too long|overflow|limit|max` returns nothing
expression-related **[READ, negative]**. The 414-character / 14-`sto` figures are the
largest anyone has *observed*, not a proven cap.

**Evaluation rate: unknown.** Nothing in `las-sc`, `las-frontend`, `docs/arch/xmos-firmware.md`
or either XMOS image yields a number, and both images were de-obfuscated (controller =
bit-reversed per byte, voice card = nibble-swapped) and searched with zero hits for
`expr`, `sto`, `rcl` **[READ, negative]**. The 375 Hz figure in the internals document
is `48000/128`, the **SuperCollider** block rate on the i.MX6, and does not apply here.
Do not reuse it.

### 3.4 The verbs, and the expressive ceiling of the text form

Tokenising every `expressions` string in all three corpora **[READ]**:

```
*  7648    sto 5789    +  1101    -  391    min 49
rcl  32    rnd   26    max  13    *** 11    **  10    rndb 4
```

No twelfth verb appears anywhere. Numeric literals: exactly three spellings, all
value 1. Arity, from context **[INFERRED]**: `* + - min max` binary; `**` (square) and
`***` (cube) unary postfix; `rnd`/`rndb` nullary pushes; `sto` consumes value and
destination; `rcl` unary — and in all 33 occurrences across every corpus its operand
is literally `c64` (`c64 rcl e2dm sto`, `captures/firmware-1.8.2/corpus/…/KING/AEROBICS.m1p:3732`),
which is how the panel's `ctl "CONSTANT"` compiles.

**The RPN text form can only express four of the twelve panel transforms**, and this
is a hard finding, not a guess. Splitting the corpus by schema **[READ]**:

| schema | `tr` values ever used |
|---|---|
| v ≤ 12 (RPN text) | `SQUARED`, `CUBED`, `LIMIT HIGH`, `LIMIT LOW` — **and nothing else** |
| v14 (compiled slots) | `SLEW`, `SLEW UP`, `SLEW DOWN`, `S&H`, `BOUNCE`, `HIPASS`, `LOPASS`, `FUNCTION`, plus the four above |

with the mapping `SQUARED → **`, `CUBED → ***`, `LIMIT HIGH → min`,
`LIMIT LOW → max`. **Every stateful or filtered transform is absent from the RPN
corpus entirely.** **[INFERRED]** the RPN form is stateless arithmetic only; the
stateful transforms are a v14-era feature carried in the slot form.

### 3.5 The transform, source and destination id spaces

**[READ]** for the name lists, which are contiguous literal runs in `las-frontend`;
**[INFERRED]** for the id assignments, which were recovered by aligning 987 `entry/N`
records against their compiled 7-tuples.

**Transforms — 42 names, `0x7e42005`–`0x7e421a4`, ids 0-42 with 43 = none:**

```
 0 LIMIT LOW     11 FUNCTION        22 S AND C           33 CV+S
 1 LIMIT HIGH    12 S+C             23 S OR C            34 (C+1)V+S
 2 SQUARED       13 S/C             24 QUANTIZE S BY C   35 V+C(V+S)
 3 CUBED         14 S/(1-C)         25 SAMPLE S ON C     36 C|V|+S
 4 LOPASS        15 (S+C)^2         26 SAMPLE S ON ~C    37 DIODE(S-C)
 5 HIPASS        16 SIN(S+C)        27 TRACK S WHILE C   38 DIODE(S-C+0.5)
 6 SLEW          17 TRI(S+C)        28 TRACK S WHILE ~C  39 DIODE(S-C-0.5)
 7 SLEW UP       18 SAW(S+C)        29 SLEW S OVER C     40 DIODE(S-C+0.25)
 8 SLEW DOWN     19 |S+C|           30 LOPASS S OVER C   41 DIODE(S-C-0.25)
 9 S&H           20 MIN(S,C)        31 HIPASS S OVER C
10 BOUNCE        21 MAX(S,C)        32 C(S-V)
```

Ids 0-10 are confirmed directly; 11-41 are extrapolated from memory order anchored on
those eleven.

**A finding that changes how `FUNCTION` is used:** when `tr = "FUNCTION"`, `tr_a` is an
**integer index, not a continuous amount**. Observed `tr_a` ∈ {3, 12, 14, 17, 19}
compile to slot ids {14, 23, 25, 28, 30} — exactly `id = 11 + tr_a` **[READ for the
numbers, INFERRED for the interpretation]**. Every other transform uses `tr_a` as a
float. So the thirty `S`/`C`/`V` operators at ids 12-41 are reachable from the panel
today, through `FUNCTION` plus an integer.

⚠ This contradicts `docs/arch/capability-survey.md:47`'s "36 shaping operators" and
its list at `:116-126`, which omits `S&H` and does not note the `FUNCTION`/`tr_a`
relationship. The correct figures are **42 names in a 44-value id space**.

**Sources — 27 names at `0x7e421a5`–`0x7e422bd` plus `VAR 1`…`VAR 10` at
`0x7e41f98`–`0x7e41fce`; id space 0-47 with 48 = none.** Recovered ids include
`0 KB GATE, 3 VELOCITY, 4 VEL RELEASE, 6 MOD WHEEL, 7 PITCH WHEEL, 8 PAD X, 9 PAD Y,
10 AFTERTOUCH, 11 PAD PRESSURE, 18-21 LFO 1-4, 22 FILTER EG, 23 AMPLIFIER EG,
24 MODULATION EG, 25 NOISE EG, 28-30 RANDOM KEYED 1-3, 33 KEY PITCH, 36 CONSTANT,
37-46 VAR 1-VAR 10`.

**Destinations — id space 0-140 with 141 = none.** 66 distinct ids observed;
`var0 = 126` implies `var0..var9 = 126…135` and `CV OUT 1…4 = 136…139`
**[INFERRED]**. Note this space is *larger* than `vx_ee.scm`'s 126 `results`, because
it also covers host-side destinations — the ten `varN` and the four CV outs — that the
VX expression engine does not itself store to.

### 3.6 What this means as an extension point

* **(a) What can be added.** Twenty modulation rows per timbre, drawn from a 48-slot
  source space and a 141-slot destination space, with a 44-slot transform space of
  which the panel's `FUNCTION` entry reaches thirty operators via an integer
  argument. Sixteen unused `m0…m15` external inputs. 128 constant registers, of which
  the factory never uses more than 43 distinct. Ten `varN` destinations that no
  factory preset writes, and sixteen `v0…v15` engine-side variables that are
  explicitly *not* saved in presets — i.e. per-note state, which is what an LFSR or a
  software LFO would need.
* **(b) Runtime cost.** Zero on the i.MX6. The rate at which the XMOS evaluates it is
  **unknown**, so the cost *there* is unquantified — budget it by measurement, not by
  arithmetic.
* **(c)/(d) Persistence.** Identical to §2: it is preset data on `/var`.
* **(e) Failure.** One preset's modulation is wrong. `dst` being a free-text OSC
  address means a wrong address is a silent no-op, indistinguishable from success.

**The one thing that would move this from "mapped" to "usable":** establishing whether
`matrix_expression_slots` is *settable* over OSC or merely derived, and whether
`/p/pre-expr` / `/p/post-expr` accept a program. Both are **unknown**, and the safest
probe is loading a hand-written preset — not hand-sending to the voice controller on
`:7770` (`docs/arch/capability-survey.md:135-142`).

---


## 4. The effects rack over `/fx` — what is fixed at boot and what is not

### The shape

**[READ]** `captures/arch-harvest/init_sc_1.scd:47-60` builds it:

```supercollider
~insertGroup = Group.new(Server.named.at(\server_main));
~busGroup    = Group.new(Server.named.at(\server_main));

5.do{arg i;
    ~efxServer[\initUnit].valueEnvir(unitNum:i);
    if(i < 3,{
        ~efxGroups = ~efxGroups.add(Group.new(~insertGroup, \addToTail));
        ~efxServer[\initEffect].valueEnvir(effect: \none_1, unitNum:i);
    } , {
        ~efxGroups = ~efxGroups.add(Group.new(~busGroup, \addToTail));
        ~efxServer[\initEffect].valueEnvir(effect: \none_1, unitNum:i);
    });
};
```

Then `~dspInputWrapper` / `~dspOutputWrapper` (`:65-66`), then `~eventideGroup` and
ten Eventide synths, each created and immediately `.run(false)` (`:73-104`).

### Addressable at runtime

Every one of these is an OSC handler in `captures/arch-harvest/efx_server.scd`,
listening on **UDP 7775**, opened directly by `thisProcess.openUDPPort(7775)` at
`efx_server.scd:3` **[READ]**. `netstat` on the live unit shows `0.0.0.0:7775`
**[READ, `captures/arch-harvest/runtime-state.txt`]** — so this is reachable from
anything on the LAN, not just from `las-sc`.

| address | line | effect |
|---|---|---|
| `/fxN` | 322-653 | load an effect by name; or, with one string argument, **execute SuperCollider** |
| `/fxN/p/0` … `/fxN/p/14` | 195-215 | 15 parameter handlers per slot |
| `/fxN/en` | 657 | enable — but see the trap below |
| `/fxN/mix`, `/g-in`, `/g-out`, `/ctl`, `/pan` | 698-765 | |
| `/fxN/in`, `/out`, `/sends`, `/par`, `/dry`, `/dig-dry` | 805-958 | bus and matrix routing |
| `/fxN/pl`, `/fxN/ph` | 964-989 | parameter list / help |
| `/fx/send1Gain` … `/fx/sendGainFactorMin` | 18-51 | the send noise gate |
| `/fx/bus-mode` | 132 | dual-mono ↔ stereo for the two bus effects |
| `/fx/hw-rev` | 147 | digital dry gain: 1.9 (old boards) or 0.9 (new) |
| `/fx/spread` | 167 | `StereoSpread` amount on main and sub |
| `/fx/start`, `/fx/state`, `/fx/run` | 55-127, 769 | the state-machine thread |

### Fixed at boot, and only changeable by editing `init_sc_1.scd`

* **Five slots.** `5.do` at `init_sc_1.scd:51`.
* **Which group each slot lives in.** Slots 0-2 are children of `~insertGroup`, 3-4 of
  `~busGroup`. The `category` field in a `/fxN` message (`efx_server.scd:236, 515`)
  changes which *code path* runs, not which group the synth is in.
* **The ten Eventide instances**, created once and parked.
* **The server options** — block size 128, 8 out / 9 in, 128 wire bufs, 100 MB
  real-time memory (`init_sc_1.scd:9-18`).
* **The set of loaded SynthDefs** — `loadDirectory("/usr/share/las-fx/synthdefs/")`
  at `init_sc_1.scd:36`, once.

### The parameter ceiling for a new effect

**[READ]** `efx_server.scd:195-215` creates fifteen handlers, `p` = 0…14, each
setting `controlNames[p + num_generic_params]` where `num_generic_params = 11`
(`:201`). For `delay_0` the argument list is
`enable, inBus, outBus, ctlIn, ctlOut, ctl, g_in, g_out, wet, dry, pan, mix,
feedback, time, gain` (`synthdefs.scd:644-660`), so index 11 is `mix` and `/fx0/p/0`
sets it.

So a new effect SynthDef gets **`mix` plus up to fourteen effect-specific
parameters** addressable live. The preset path is narrower: the `12.do` loops at
`efx_server.scd:391` and `:540` read at most twelve `(index, value)` pairs from one
message, gated by `pindex < psize` where `psize = controlNames.size - 11`.

The `/p` namespace agrees, with one discrepancy worth recording: `captures/p-namespace-keys.txt`
shows `/p/part/las-fx/1/p/0…11` (12 slots) while `captures/sysmap/addrs-p.txt:387-402`
shows `/p/part/las-fx/1/p/0…15` (16). Two harvests, two answers; the engine-side cap
is 15.

### Insert slots and bus slots do not offer the same effects

**[READ]**, by enumerating `types/` under each in `captures/p-namespace-keys.txt`:

* **Insert (per timbre, `/p/part/t/N/p/fx/ins/`): 19 types** — `bbdDelay bitcrusher
  chorus delay dualChorus ensemble flanger phaser12stage phaser6stage pingpongDelay
  resonator stereoChorus stereoDelay stereoFlanger tapeDelay timePhaser vocoder10
  vocoder16 vocoder21`
* **Bus (`/p/part/las-fx/{1,2}/`): 24 types** — the same 19 **plus** `et_blackhole
  et_hall et_plate et_room et_shimmer`.

**The Eventides are bus-only as far as the panel is concerned.** They are not
bus-only as far as the engine is concerned: `~initEffect` calls
`Synth(effect, target: ~efxGroups[unitNum])` with no validation
(`efx_server.scd:239, 265`), so any loaded name can be pushed into any slot by OSC.
Whether an Eventide placed in slot 0 sounds right is **[INFERRED]** as "probably not"
— the eventide branch of `~initEffect` is in the `else` arm, keyed on
`category != \ins`, and slot 0's group is a child of `~insertGroup` which sits before
`~busGroup` in the execution order.

### The three traps

1. **`enable` is not a mute.** Every native effect and both routers carry
   `EnvGen.kr(Env.asr(...), enable, doneAction: 2)` — 26 occurrences in
   `synthdefs.scd` **[READ]**. Writing `enable = 0` **frees the node**. Only the six
   `et_*` families use `doneAction: 1` (pause): `synthdefs.scd:3407, 3492, 3576,
   3657, 3735, 3817`. Treat `enable` as read-only.
2. **`/n_free` on a LADSPA node terminates `scsynth`.** Confirmed 2/2
   (`docs/CLAIMS-AUDIT.md`). Moog's design never frees them, so their code never hits
   it.
3. **Two `/fxN` messages to one slot inside ~250 ms** leave the `Routine` at
   `efx_server.scd:489-637` spinning forever (`docs/DANGER.md`).

### Could a sixth slot be added?

**[INFERRED], and there is a real mechanism.** `~fxStateThread` sizes its loop from
`~efxServer[\efx_active].size` (`efx_server.scd:1047`), and `~initUnit` appends to
that list and registers all the OSC handlers for the new index (`:289-994`). So
running `~efxGroups = ~efxGroups.add(Group.new(~busGroup, \addToTail));
~efxServer[\initUnit].value(5)` through the `interpret` door in §5 would produce a
working sixth slot with a full `/fx5/*` namespace.

**Do not.** `docs/CLAIMS-AUDIT.md`: "Adding a sixth effect is what caused the
dropouts that then motivated the block-size change." The five slots the instrument
ships with are already inside its budget; a sixth is not.

---

## 5. The SuperCollider layer — the real ceiling

### 5.1 The `interpret` door: arbitrary sclang over UDP

**[READ]** `efx_server.scd:338-345`:

```supercollider
//if incoming message at that fx slot has no bus information then it must be a string to be compiled.
if(  msg[2].isNil == true,{
    ...
    msg[1].asString.interpret;
```

A `/fx0` message whose second argument is absent has its first argument compiled and
run as SuperCollider, as root, in the process that owns the audio graph. Already
recorded at `docs/DANGER.md:167`, `docs/arch/effects-engine.md:960` and
`docs/arch/capability-survey.md` §B2; repeated here because it is the *only* way to
add DSP to a running instrument without touching a file.

* **(a) What can go there:** anything sclang can do — new `SynthDef`s, new `Group`s,
  new buses, `Buffer.alloc`, `systemCmd`, mutation of any `~` variable in the
  effects environment.
* **(b) Cost:** whatever you write. It lands on cpu1 with the rest of the graph.
* **(c) Survives a reboot:** **no.** Nothing is written. That is its best property
  and its worst one.
* **(d) Survives a firmware update:** n/a.
* **(e) Failure:** a bad expression can free nodes, wedge the state thread, or take
  `scsynth` down. Recovery is `/etc/init.d/S42sc restart` — **never `/sbin/reboot`,
  which wedges the USB gadget and needs power removed** (`docs/DANGER.md`).

### 5.2 New SynthDefs, loaded at boot

**[READ]** `init_sc_1.scd:36`:
`Server.named.at(\server_main).loadDirectory("/usr/share/las-fx/synthdefs/");`
followed by `SynthDescLib.global.read;` at `:37`.

`loadDirectory` loads **everything in the directory**, whether or not the current
`synthdefs.scd` still defines it. The proof is already on the device: of the 104
names in `captures/arch-harvest/synthdef-names.txt`, **seven have no SynthDef in
`synthdefs.scd` at all** — `bitcrusher2`, `echo_0`, `echo_1`, `echo_2`,
`spaceFlanger`, `spacePhaser`, `timeEnsemble` — and one SynthDef in the source,
`et_spring`, is inside a `/* … */` block spanning `synthdefs.scd:3629-3700` and so
was never `.store`d **[READ, independently recomputed for this report; matches
`docs/arch/audio-graph.md:870-885`]**.

So: **drop a `.scsyndef` into `/usr/share/las-fx/synthdefs/` and it is live after the
next `S42sc restart`.** That is the boot-time equivalent of §5.1.

* **(a)** Any SynthDef. To be selectable it needs a name the frontend will send, or
  it has to be reached by OSC directly (`/fxN <name> ...`).
* **(b)** cpu1. Budget against the measured baseline: a freshly booted instrument is
  496 ugens and **16.6 %** of the audio thread at block size 128; an Eventide is
  23-33 % of a core; the `SCHED_FIFO` throttle is 95 % (`docs/CLAIMS-AUDIT.md`,
  `docs/ARCHITECTURE.md`).
* **(c)** Yes.
* **(d)** **No.** `/usr/share/las-fx/**` is on the root partition — see §11.
* **(e)** A `.scsyndef` from the wrong SuperCollider version fails to load and the
  slot silently keeps what it had. Delete the file.

**Authoring one is easier than it looks, because Moog left the tools on the device.**
**[READ]**, from the rootfs image, `/usr/share/las-fx/` contains:

```
-rwxr-xr-x      63  compile-synthdefs        <- the build script
-rw-r--r--  113367  synthdefs.scd            <- the source
drwxr-xr-x    9216  synthdefs/               <- 104 .scsyndef + 104 .txarcmeta
drwxr-xr-x    1024  SCClassLibrary/          <- 200+ .sc class files
-rwxr-xr-x    1345  assign-pids
-rw-r--r--     581  README.md
```

`sclang` is on the device (`captures/moog-recon/06-toolchain.txt` **[READ]**),
`SynthDef.synthDefDir` already points at `synthdefs/` (`init_sc_1.scd:24`), and
`synthdefs.scd` builds every definition with `.store`. So the supported path is:
edit `synthdefs.scd`, run `compile-synthdefs`, restart with `S42sc`.

**The `synthdefs/` directory holds 208 files, not 104** — each `.scsyndef` has a
matching `.txarcmeta`, a plain-text SC archive of the per-parameter metadata (name,
description, unit, type) that `SynthDescLib` and the frontend's parameter list read.
A new effect needs both.

**And `/usr/share/las-fx/SCClassLibrary/` is itself an extension point.**
`sclang_config.yaml` declares `includePaths: - SCClassLibrary` relative to
`/usr/share/las-fx`, so a `.sc` file dropped in that tree becomes a class available to
`init_sc_1.scd` at boot. Four of the five "custom Moog UGens" turn out to live there
as **plain sclang classes, not server plugins** **[READ]**:

| name | what it actually is |
|---|---|
| `StereoSpread` | `SCClassLibrary/Effects/StereoSpread.sc`, 342 bytes — mid/side arithmetic, no primitive |
| `Flanger` | `SCClassLibrary/Effects/Flanger.sc`, 1,942 bytes — `DelayN`/`DelayL`/`LFCub`/`LPF`/`FbNode` |
| `DualChorus` | `SCClassLibrary/Effects/DualChorus.sc`, 3,567 bytes |
| `Phaser6Stage` | `SCClassLibrary/Effects/Phaser6Stage.sc`, 1,943 bytes |
| `Decimator` | the only real compiled UGen — `/usr/lib/SuperCollider/plugins/DistortionUGens.so` |

**That is good news for extension.** Four of the five are composites resolved at
SynthDef-compile time in sclang, so changing or extending their behaviour is a text
edit and a recompile, not a cross-compiled `.so`.

⚠ Four Moog-built UGen `.so` files also sit in that directory — `M_Delay.so` (17,008),
`M_Phaser4.so` (12,896), `M_Vocoder.so` (7,048), `SIMDBPF.so` (5,696), beside a
`Makefile` hardcoded to `/Users/gregsurges/…` that builds macOS `.scx` bundles
**[READ]**. `SC_PLUGIN_PATH` is set nowhere on the filesystem, no `.scsyndef` and no
line of `synthdefs.scd` references any of the four, and they are not in the plugin
directory. **[INFERRED]** they are leftovers from a developer checkout and are not
loaded.

### 5.3 Bus, buffer and memory headroom

**[READ]** the live command line, `captures/arch-harvest/runtime-state.txt`:

```
scsynth -u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

⚠ **`-z 256` in that snapshot is this project's own edit, not stock.** The stock value
is 128 (`init_sc_1.scd:9-10`) and the instrument has been restored to it; three arch
documents read the 256 as factory and are wrong. `docs/arch/doc-audit.md` §0.1
settles it. `runtime-state.txt` was captured while the modification was in place.

Everything else in that line is stock:

| flag | value | meaning | headroom |
|---|---|---|---|
| `-a 129` | 129 audio buses | 8 out + 9 in + **112 private** (SC's default `numPrivateAudioBusChannels`) | private buses start at 17; the stock graph uses only **50-63**, so **98 private buses are free** |
| `-i 9` | 9 ADC channels | mapped to buses 8-16; the graph reads only ADC 2,3,4,5,6 | **ADC 0, 1, 7 and 8 are unused** — buses 8, 9, 15, 16 |
| `-b 1026` | sample buffers | SC's default | essentially all free; `init_sc_1.scd` allocates none |
| `-m 100000` | 100 MB real-time memory | out of 508 MB total, 11 MB free, 96 MB available at capture time | tight; measure before assuming |
| `-w 128` | wire buffers | set explicitly at `init_sc_1.scd:13` | raising it needs a restart |
| `-l 1` | max logins | **only one client may `/notify`** | commands still work un-notified |
| `-C 0`, `-R 0` | | Rendezvous off; `-C` meaning **unknown** | |

The 98 free private buses and 4 free ADC channels are the concrete answer to "how
much room is there in the graph". Bus and buffer counts, however, are **fixed at
`scsynth` start** — enlarging them means editing `init_sc_1.scd`, i.e. §11.

**[READ]** the only literal private buses anywhere in `synthdefs.scd` are 50/51,
52/53, 54/55 (insert returns), 56/57, 58/59 (inputRouter → bus effects) and 60/61,
62/63 (bus-effect returns). Verified by enumerating every `In.ar`/`Out.ar`/`SoundIn.ar`
with a literal argument.

### 5.4 The routing matrices nobody writes to

`outputRouter` (`synthdefs.scd:401-593`) carries two independent 6-column matrices
— `insert1_r`/`insert2_r`/`insert3_r` and `master1_r`/`master2_r` — over
`main, sub, aux1, aux2, aux3, aux4`, plus four separate 4-column matrices
`dry_dir1_r`…`dry_dir4_r` for the per-timbre analog dry feeds. `master1_r`/`master2_r`
have **no writer anywhere** and only index `[0]` is live (`docs/ROADMAP.md:149`).

Every one of these is a `Synth.set` away from being changed at runtime, through
either §5.1 or the `/fxN/out` handler. This is the "routing matrix the front panel
barely exposes" from `docs/CLAIMS-AUDIT.md`, and it costs nothing — the ugens are
already in the graph.

---

## 6. LADSPA

### What is actually there

**[READ]** `captures/arch-harvest/table-and-ladspa-listing.txt` lists six plugins:
`eventide_blackhole.so`, `eventide_hall.so`, `eventide_plate.so`, `eventide_room.so`,
`eventide_shimmer.so`, `eventide_spring.so`.

**[READ]** They are called by unique ID from `synthdefs.scd`:

| ID | plugin | called from |
|---|---|---|
| 29150 | blackhole | `:3417, :3419` |
| 29151 | hall | `:3584, :3586` |
| 29152 | room | `:3501, :3503` |
| 29153 | **spring** | `:3662` — **inside the commented-out block** |
| 29154 | plate | `:3742, :3744` |
| 29155 | shimmer | `:3827, :3829` |

The call shape is `LADSPA.ar(2, <id>, <10 control ports>, mix, inL, inR)`.

So the **spring is a paid-for algorithm sitting unused on the disk**: the `.so` ships,
its SynthDef source ships, and the SynthDef is commented out so it was never compiled
and never appears in `synthdef-names.txt`. `docs/arch/doc-audit.md` §2.6 and §1.4
settle the history and warn that the obvious patch mis-orders its ports.

### (a) Could a new `.so` be dropped in?

**[INFERRED], with one unresolved dependency.** The mechanism exists — `LADSPA.ar` is
in the SynthDef vocabulary and takes a unique ID — but *how the server finds the
directory* is not established:

* `init_sc_1.scd:23` runs `("export LADSPA_PATH=/usr/share/las-fx/ladspa").systemCmd;`
  — `systemCmd` spawns a subshell, so **the export cannot reach `sclang` or
  `scsynth`** **[READ, and already flagged at `docs/arch/effects-engine.md:71`]**.
* `LADSPA.ladspalist_path` is set in `init.scd:23` — but `init.scd` is not the boot
  path; `launch-sc-1` runs `init_sc_1.scd` (`captures/arch-harvest/launch-sc-1:23`
  **[READ]**), and that variable is client-side anyway, used by `LADSPA.listPlugins`.
* The scsynth `-U <ugen-plugins-path>` and `-P <restricted-path>` flags are **absent**
  from the command line, so both are at their defaults.

`docs/arch/effects-engine.md:993` has had this as an open question. **The rootfs image
now answers most of it [READ]:**

* The UGen plugin directory is **`/usr/lib/SuperCollider/plugins`**, 96 `.so` files.
  It is the only real plugin directory on the image; `/usr/share/SuperCollider/Extensions/SC3plugins`
  holds sources and help only, zero `.so`.
* **`LadspaUGen.so` (6,668 bytes) is present** there, and it is the only file in that
  directory containing the string `LADSPA_PATH`.
* **`LADSPA_PATH` is set nowhere durably.** A grep of the entire `/etc` tree returns
  **zero** hits — `/etc/environment` does not exist, and `/etc/profile` (444 bytes)
  sets only `PATH`, `PS1`, `PAGER`, `EDITOR`, `TERMINFO`. The only two assignments on
  the whole filesystem are the `.systemCmd` subshell exports in `init_sc_1.scd:23`
  and `init_sc_2.scd:44`, neither of which can reach the already-running `scsynth`.
* **`/usr/lib/ladspa` exists and holds a *different build* of the same plugins:**

  | plugin | `/usr/share/las-fx/ladspa` | `/usr/lib/ladspa` | identical? |
  |---|---|---|---|
  | blackhole | 399,692 | 569,304 | no |
  | hall | 389,944 | 597,832 | no |
  | plate | 420,456 | 446,552 | no |
  | room | 397,832 | 601,128 | no |
  | shimmer | 402,480 | 425,536 | no |
  | spring | 412,704 | 412,704 | **yes** |

  Only the spring is byte-identical. `/usr/local/lib/ladspa` does not exist.

**[INFERRED]** With `LADSPA_PATH` unset in the `scsynth` process, `LadspaUGen.so` falls
back to its compiled-in default — which on a stock sc3-plugins build is
`/usr/lib/ladspa:/usr/local/lib/ladspa`, i.e. **the `/usr/lib/ladspa` copies are
probably the ones actually loaded, not the ones in `las-fx`**. That would also explain
why two divergent sets exist. This is the last unresolved step and it is one
`strings` of `LadspaUGen.so` away — **establish which directory is live before
replacing anything in either.**

⚠ This also means an earlier finding needs re-dating: `docs/arch/doc-audit.md:282`
warns that the `/usr/lib/ladspa` listing may be contaminated by this project's own
copy of `eventide_spring.so` into that directory. The image was taken 2026-09-07,
after that copy and possibly after its removal. The five non-spring plugins in
`/usr/lib/ladspa` differ in size from the `las-fx` set, so they are Moog's, not ours
— but the spring being byte-identical is exactly what a hand-copy looks like.

### (b) Cost, (c) reboot, (d) update, (e) failure

Cost is cpu1, and Eventide-class reverbs measure 23-33 % of a core on an idle engine.
Survives a reboot. **Does not survive a firmware update** — it lives on the root
partition. Failure mode is benign at the plugin level (`LADSPA: plugin not found`,
SynthDef fails to build) and catastrophic at the node level (`/n_free` on a LADSPA
node terminates `scsynth`).

### The build constraint, which is the real cost

**[READ]** `tools/README-scsynth-jack.md`, written after six failed attempts:

* the device is **glibc 2.21**; build on Debian **jessie** (2.19), not anything newer
* use **gcc-4.8**, not 4.9 — 4.9 emits `GLIBCXX_3.4.20` and the device's
  `libstdc++.so.6` stops at **3.4.19**, so the binary links in the container and
  fails on the target
* verify before it goes near the instrument:
  ```
  objdump -T x.so | grep -o 'GLIBC_[0-9.]*'   | sort -uV | tail -1   # <= 2.21
  objdump -T x.so | grep -o 'GLIBCXX_[0-9.]*' | sort -uV | tail -1   # <= 3.4.19
  ```

A LADSPA plugin is a much smaller build than `scsynth` — it is a single `.so` with a
C ABI and no SuperCollider dependency at all — so the toolchain is the whole cost,
and the toolchain recipe already exists and is proven.

---

## 7. The `/p` namespace as an external control surface

### The shape

**[READ]** 3,197 addresses, enumerated in `captures/p-namespace-keys.txt` (which is a
dump of the `INIT` preset — see §2). Six top-level branches: `/p/version`, `/p/clk`,
`/p/lc` (left-hand controller), `/p/mix`, `/p/panel_focus`, `/p/part`. Under
`/p/part`: `t` (2,362 — three timbres), `las-fx` (611), `tuning` (132),
`cv_settings` (37), `midi_io` (17), `mix` (2).

A second, richer harvest exists at `captures/sysmap/addrs-p.txt` and disagrees with
the preset dump in places — e.g. it lists `/p/part/las-fx/N/{byp,dry,wet,g-in,g-out}`
and `p/0…15`, none of which appear in the preset dump. Two views of the same tree;
neither is complete.

### (a) What can be added

Anything the panel can do, from outside, live — plus things the panel cannot do, of
which the mod-matrix `dst` free-text OSC address is the sharpest
(`docs/arch/capability-survey.md` §A2).

### (b) Runtime cost

Negligible; `las-sc` is on cpu0. The known cost is *latency*, not CPU: a measured
115 ms OSC round trip over SSH, and 105-165 ms for any audio path over the network
(`docs/ROADMAP.md:146`).

### (c)/(d) Persistence

Live control persists nothing. What you *write into a preset* persists per §2.

### (e) What breaks

Nothing structural. Two operational traps:

* **`scsynth` answers from the wrong address.** The instrument has two IPv4 addresses
  on `ethext` (`192.168.1.136` and a secondary `.138`, `runtime-state.txt` **[READ]**);
  `scsynth` binds `0.0.0.0:57110` and replies from the *secondary*, so a client that
  validates the sender times out.
* **The whole `/hw/` namespace 404s except `/hw/mute`**, and a zero-argument message
  to a setter is inert (`docs/CLAIMS-AUDIT.md`).

### The CV outputs, specifically

**[READ]** `captures/p-namespace-keys.txt:58-73`:
`/p/part/cv_settings/cv_output/{1,2,3,4}/{source,min,max,synth}`, plus a fifth leaf
the key dump misses — `voice_rule`, present in **27 of 527** presets across both
databases, always `"o"`.

| field | what, and how well it is known |
|---|---|
| `source` | **≥ 20 values**; the v1.5.0 additions are a contiguous 14-entry block in `las-frontend` at `0x7e80529`–`0x7e80615` — `CV 1 INPUT`, `CV 2 INPUT`, `PEDAL 1 INPUT (EXP 1)`, `PEDAL 2 INPUT (EXP 2)`, `SUSTAIN PEDAL INPUT`, `SEQUENCE PITCH (U)`, `SEQUENCE PITCH (B)`, `SEQUENCE GATE`, `SEQUENCER RTZ`, **`MODULATION OUTPUT`**, `MIDI CC 2/4/11/74` **[READ]**. The pre-1.5.0 base set (`PITCH CV`, `GATE`, `PITCH WHEEL`, `MOD WHEEL`, `PITCH (B)`, `NONE`) is deduplicated elsewhere in the string pool and could not be enumerated. **Full enum: unknown.** |
| `min` / `max` | integers, and every factory preset uses one of two patterns: `0/1000` for bipolar sources, `500/1000` for unipolar. **[INFERRED]** per-mille of the −5…+5 V span. |
| `synth` | observed values `0`, `1`, `6` only. **[INFERRED]** an enum over synth selection (`0` = Synth 1, `6` = All), because `las-frontend` carries exactly `SYNTH 1 & 2`, `SYNTH 1 & 3`, `SYNTH 2 & 3` in the same option pool. A bitmask reading puts `MASTER VOLUME` on synths 2+3, which is nonsense. |
| `voice_rule` | always `"o"`; settings label `VOICE RULE` at `0x7e802db`. Meaning **unknown**. |

**Voltage range: ±5 V [READ].** `las-frontend`'s `CVOutCalibrationPanel` instructs
"USE A MULTIMETER TO MONITOR THE DC VOLTAGE OUTPUT OF EACH CV OUT… BY ADJUSTING THE
CORRESPONDING DAC VALUE", with the two endpoints written literally as `+5V` and
`-5V` (`0x7e64e17` region).

**Update rate: unknown.** The CV outs are on the voice-controller/interface board,
not in `scsynth`, so the 375 Hz block rate does *not* apply. Do not reuse that number.

**`CV OUT 1`–`CV OUT 4` are mod-matrix destinations** (`las-frontend` `0x7e41fd5`,
`0x7e41fde`, `0x7e41fe7`, `0x7e41ff0` **[READ]**), sitting beside `EXT LEVEL`,
`VAR 1`–`VAR 10`, `MASTER VOLUME` and `HEADPHONES`. Combined with `MODULATION OUTPUT`
as a legal `source`, that is **a four-channel programmable CV generator driven by the
expression language of §3, at zero i.MX6 cost**. No factory preset uses
`MODULATION OUTPUT`.

Assignment is per-preset (`/p/part/cv_settings/…`, present in 527/527 presets);
calibration and the global min/max/voice-rule page are global settings. **[INFERRED]**
from the split between the settings key list and the preset key list.

---

## 8. The back panel — real, analog, zero-latency, and previously overlooked

This is the surface that two features in this project reimplemented in software
before anyone read the panel (`docs/ROADMAP.md:147, 156-158`). It deserves the weight.

### 8.1 What is actually there

| jack group | count | evidence |
|---|---|---|
| MAIN L/R | 1 pair | `las-frontend` OUTPUT MATRIX, `0x7e6fb51`–`0x7e6fb7d` **[READ]** |
| SUB L/R | 1 pair | same |
| **INSERT 1-4** | **four** | same — the matrix enumerates the analog output jacks exhaustively and contains exactly `MAIN L/R`, `SUB L/R`, `INSERT 1`, `INSERT 2`, `INSERT 3`, `INSERT 4` |
| EXT INPUT | **two** — "COMBO" and "LINE" | `VoiceCardCalibrationPanel` at `0x7e97036`: `PLEASE CONNECT COMBO AND LINE INS TO SUB L AND SUB R OUTS.` **[READ]**; mixer source enum `MIC/LINE`, `MIC/LINE + LINE` at `0x7e70987` **[READ]** |
| CV OUT 1-4 | four | `/p/part/cv_settings/cv_output/{1..4}` **[READ]** |
| CV IN 1-2 | two | `cv_input/cvin_{1,2}` **[READ]** |
| EXPR IN 1-2, SUS IN | three | `cv_input/{expr_in_1,expr_in_2,sustain}`; panel labels `EXPR IN 1`, `EXPR IN 2`, `SUS IN` at `0x7e74654` **[READ]** |
| MIDI IN, MIDI OUT 1, MIDI OUT 2 | three DIN | interface-board silkscreen, `docs/arch/hardware-external.md:524-530` [TECH, from photographs] |
| USB-A host, USB-B client, RJ45 | one each | same |
| Headphones | one | `JA_HP`, same |

**Two brief assertions did not survive checking, and should stop being repeated:**

* **"Neutrik combi XLR/TRS"** appears in this repo only at `docs/ROADMAP.md:147`,
  which cites nothing. The firmware's own word is **`COMBO`**. The connector type is
  a manual spec and **there is no manual in this repository**. [UNVERIFIED]
* **"TRIM −9 to +65 dB"** is **not in this repo at all** — grepped `docs/`,
  `README.md`, `recon/`, `moogd/`, and both `las-*` binaries for
  `trim|combi|neutrik|65 dB`. [UNVERIFIED]
* **"tip = send, ring = return, stereo-normalled pairs"** for the INSERT jacks is
  likewise **[UNVERIFIED]** — `las-frontend` has no `TIP`/`RING`/`normalled` string
  describing them. (It does have `CONNECT TIP TO CV IN 1 AND RING TO CV IN 2`, for
  headphone calibration, which is a different jack.)

Those three are probably right. They are not established here, and the correct move
is to put the owner's manual into `captures/` rather than to keep citing the roadmap.

### 8.2 EXT INPUT — where it goes

**[READ]** Per timbre, `captures/p-namespace-keys.txt:1298-1302` (timbre 1; timbre 2
at `:2090-2094`, timbre 3 at `:2874-2878`):

```
/p/part/t/N/p/mix/ext/ext0   bool   ext source 0 enable
/p/part/t/N/p/mix/ext/ext1   bool   ext source 1 enable
/p/part/t/N/p/mix/ext/fa     bool   route ext → filter A (state variable)
/p/part/t/N/p/mix/ext/fb     bool   route ext → filter B (ladder)
/p/part/t/N/p/mix/ext/g      float  EXT. INPUT LEVEL
```

The ext channel is **the sixth channel of each voice's 6-channel mixer** (3 osc, ring
mod, noise, ext in), ahead of the filters and the VCA
(`docs/arch/hardware-external.md:113-114`, from the manual's spec page). `las-sc`
carries `/mix/ext/{ext0,ext1,g,fa,fb}` plus a modulation twin `/mix/ext/g_m`
**[READ]**, and `EXT LEVEL` is a mod-matrix destination (`las-frontend` `0x7e41f83`
**[READ]**). The ext gain stage is calibrated: `las-sc` carries `checking for extin
cal data`, `/cal/extin`, `external input gain` **[READ]**.

**Direct to the jacks, bypassing the voices:** `captures/p-namespace-keys.txt:702-703`
**[READ]**

```
/p/part/mix/ext-dir3      ← INSERT 3 - EXT MIC   (las-frontend 0x7e6fa31)
/p/part/mix/ext-dir4      ← INSERT 4 - EXT LINE  (las-frontend 0x7e6f9e4)
```

There is no `ext-dir1` or `ext-dir2`. That is a complete-enumeration negative, not an
inference: **raw EXT audio can reach INSERT jacks 3 and 4 only.**

**Into the digital effects:** only by going through a timbre first. **[INFERRED from
three READ facts]** — DSP insert slots 1-3 read hardware ADC 4/5/6, which are the
per-timbre analog dry sums; bus slots 4-5 read private buses 56-59, which
`inputRouter` fills from `SoundIn.ar(2)`/`SoundIn.ar(3)` = the two analog effect
sends, whose per-timbre levels are `/p/part/t/N/mix/aux1` and `/aux2`. So
EXT → `ext/g` → that timbre's filters and VCA → dry tap and sends → the rack.

**The caveat:** the ext channel sits *before* the VCA, so ext audio on this path is
gated by the voice envelope — it needs a held note. There is a global `gate_gain`
setting whose behaviour is **unknown** and which is the likely answer.

**Factory usage: essentially zero.** Across all 527 presets in both databases (1,581
timbre instances) **[READ]**: `ext0` false ×1581, `ext1` false ×1581, `fa` false
×1581, `fb` true ×**1**, `ext-dir3` false ×527, `ext-dir4` true ×**1**. Empty road —
and no worked example to copy.

### 8.3 The INSERT jacks and the digital rack

**[READ]** Per timbre, `captures/p-namespace-keys.txt:769-774`:
`/p/part/t/N/mix/{dir1,dir2,dir3,dir4,main-en,sub-en}`. Master trims,
`:28-32`: `/p/mix/{aux1-db,aux2-db,aux3-db,aux4-db,sub-db}`.

The four INSERT jack sends **are** `scsynth`'s four aux hardware outputs — DAC 5, 6,
3, 4 (`docs/arch/audio-graph.md:283-289`). So `outputRouter`'s `insert1_r`…`insert3_r`
matrices route each DSP insert slot's return to any of the four jacks.

Three hazards on that path, all already documented and all worth restating because
this is where new work will land:

1. **Aux-routed inserts are +6 dB** relative to main/sub — a double-summing bug that
   every factory preset's aux level was voiced around
   (`docs/arch/audio-graph.md:645-664`).
2. **Routing bus-effect slot 4 to any aux injects full-scale DC** via `dry_dir4_r`
   (`docs/arch/audio-graph.md:590-615`).
3. **Bus/master effects cannot reach the INSERT jacks at all** — `master1_r`/
   `master2_r` have no writer and only index `[0]` (main) is live.

**Phase:** main L *and* main R are inverted (`Out.ar(7, main[0] * -1)`,
`Out.ar(0, main[1] * -1)` — `synthdefs.scd:564-565` **[READ]**); sub and all four aux
are not. Summing a main output against a sub or INSERT output partially cancels.

Factory usage **[READ, 1,581 timbre instances]**: `dir1` true ×365, `dir2` ×279,
`dir3` ×278, `dir4` ×**0**. `aux1-db`…`aux4-db` only ever `0` or `12`; `sub-db` only
`0` or `22`.

### 8.4 CV and pedal inputs — the strongest input-side hook

**Five** analog inputs, not two: `cvin_1`, `cvin_2`, `expr_in_1`, `expr_in_2`,
`sustain` (`captures/p-namespace-keys.txt:37-57` **[READ]**). `sustain` uniquely
carries `type`, `"norm"`/`"inv"` — the pedal-polarity switch.

A second, finer per-timbre scaling layer exists:
`/p/part/t/N/in/cv/{cv1,cv2,exp1,exp2,sus}/{dest,en,in-min,in-max,out-min,out-max}`
(`:721-750` **[READ]**).

**All four of CV IN 1/2 and EXP 1/2 are first-class mod-matrix sources** — they appear
in `las-frontend`'s mod-matrix source name table at `0x7e421f9` beside `KEY PITCH`,
`AFTERTOUCH`, `PAD X/Y`, the EGs and the randoms **[READ]**.

**Range ±5 V [INFERRED, strong]:** `CVInCalibrationPanel` calibrates the CV inputs
*against the CV outputs* — "CONNECT CV OUT 1 TO CV IN 1 AND CV OUT 2 TO CV IN 2" — and
`PedalIn CALIBRATION` does the same for `EXPR IN 1/2` and `SUS IN` **[READ]**. So the
two expression jacks and the sustain jack are ±5 V CV-range ADCs, not merely
potentiometer or switch inputs. That is a useful and non-obvious extension fact.

**So the complete external loop is:** CV/expression in → mod-matrix source → the
expression language of §3 → any `/p` destination → `CV OUT 1-4` out. Entirely on the
XMOS, entirely inside a preset, zero i.MX6 cost, survives everything.

### 8.5 MIDI and the unexplored port

**[READ]** `captures/p-namespace-keys.txt:685-701`:
`/p/part/midi_io/{midi_in_ports, midi_out_ports, midi_in_route, midi_out_route,
midi_{in,out}_channel_{all,synth1,synth2,synth3}, merge_din_in, merge_usb_in,
merge_avb_in, seq_midi_out, arp_midi_out}`. Port options: `DIN`, `PER SYNTH`,
`DIN & USB` (`las-frontend` `0x7e80839`).

Per timbre the routing model has **exactly one DIN and one USB port**
(`/p/part/t/N/in/{din0,usb0}/…`, `:751-766`).

**`merge_avb_in` is the single most interesting unexplored thing on the back panel.**
It is the only trace of MIDI over the RJ45. It exists as a preset key and nothing
else — no AVB string in `las-sc`, no AVB daemon in the process table. **Whether it
functions is unknown.**

**"MIDI THRU" is not substantiated**: the silkscreen reads `MIDI OUT 1` / `MIDI OUT 2`
and `THRU` appears in `las-frontend` only inside a preset name. Whether OUT 2 is
switchable to THRU is **unknown**.

USB MIDI out from the keys **[TESTED]** — this project drove a sampler from the Moog's
keyboard over the USB client port, 44 notes, every one triggering (repo commit
`da9c962`).

---

## 9. The USB drive — the right shape for anything large

### The drive-mount path

**[READ]** From the live unit (`captures/arch-harvest/runtime-state.txt`):

```
/dev/sda1 on /var/local/media/sda1 type vfat
  (rw,relatime,gid=100,fmask=0002,dmask=0002,codepage=437,
   iocharset=iso8859-1,shortname=mixed,utf8,errors=remount-ro)
```

`fmask=0002` leaves files mode 0775 — **so an executable on the drive is executable**,
which is why `moogd` can run from it at all. Everything on the instrument refers to
the drive as `/media/thumbdrive`; how that name reaches `/var/local/media/sda1` is
**unknown** — no udev rule is in the harvest, and `S14fs:28-31` only does
`mkdir /var/local/media; ln -s /media /var/local/media`.

`las-frontend` is started with `--usb-path=/media/thumbdrive` (`S43gui:21` **[READ]**),
so the drive is a first-class path for the UI: firmware update, preset import/export,
calibration export.

**The drive must be FAT32/MBR.** exFAT is invisible to this 4.1 kernel — which also
rules out formatting the drive on an iPad (`usb/README.md`).

### The `k` file: what the drive can switch on

**[READ]** Two boot scripts test the same file. `captures/arch-harvest/init.d/S50dropbear:29-42`:

```sh
if [ -e /media/thumbdrive/k ]; then
    keyval=`hexdump /media/thumbdrive/k | awk '{print $3 $2}'`
    if [ $keyval = 23051934 ]; then
        echo "`date` : DROPBEAR : You have a key! Aren't you special!" >> /var/log/messages
        start-stop-daemon -S -q -p /var/run/dropbear.pid --exec /usr/sbin/dropbear -- $DROPBEAR_ARGS
        exit;
    fi;
fi;
```

`captures/arch-harvest/init.d/S99final:31-44` tests the identical value, and when it
matches:

```sh
        killall las-watchdog;
        exit;
    fi;
fi;
#no key or hot key press was found so kill xterms, dwm, and mount root RO
killall xterm;
killall las-dwm;
mount -f -o remount,ro /
```

So one file on the drive does **three** things at once:

1. **Starts SSH.**
2. **Leaves the root filesystem mounted read-write** — without `k`, root is remounted
   read-only at the end of boot, which is why nothing can be written to it on a stock
   machine.
3. **Kills `las-watchdog`** — which is also the thing that restarts the audio and GUI
   stack when the voice controller stops answering. `docs/DANGER.md:230-238`: "the
   drive that makes this instrument hackable also disarms every automatic recovery it
   has."

That third consequence is the one to remember. **The unlocked instrument is the
un-protected instrument.**

### Drive-resident code vs rootfs-resident code

`moogd` is the worked example: a static ARM Go binary (`CGO_ENABLED=0`, no libc,
~6 MB) that runs from the vfat drive and serves a web UI, reading `/proc`, `/sys`,
`/dev/fb0` and talking to `scsynth` over localhost UDP (`moogd/README.md`).

**Boot-time execution still has to live on the root filesystem** — there is no generic
USB autorun hook to borrow. `usb/S99moogd` is the minimum footprint: one new file in
`/etc/init.d/`, nothing existing modified, and deleting it undoes everything. It
copies the `k` convention exactly — an opt-in marker (`moogd.autostart`) separates
*carrying* the binary from *running* it.

| | drive-resident | rootfs-resident |
|---|---|---|
| (a) what can go there | anything: static binaries, UIs, data, 234 GB of it | one shell script, ~148 MB of headroom total |
| (b) runtime cost | cpu0 (`taskset -c 0`); `moogd` measured 5.4 MB resident | nil for the script |
| (c) survives reboot | yes, but only if the rootfs script exists | yes |
| (d) survives firmware update | **yes** — it is not on the instrument | **no** |
| (e) failure | none; unplug the drive | must `exit 0` and must not block, or it can stall boot |

`S99moogd` is fail-safe by construction: doubly backgrounded, a bounded 30-second
wait for the hotplug mount, and `exit 0` unconditionally. **[TESTED]** cold boot from
power-on: `ppid=1`, UI served, `scsynth` reachable.

⚠ **A documentation conflict to be aware of, not fixed here.** The header comment in
`captures/arch-harvest/init.d/S99moogd:18-19` still reads "It runs on cpu1, which
`isolcpus=1` reserves and nothing else uses" while line 61 correctly does
`taskset -c 0`. `moogd/README.md`'s "What is proven" section likewise still says
"pinned to the isolated core, confirmed `mask=2 last-cpu=1`". Both are the
pre-correction wording; `docs/CLAIMS-AUDIT.md` retracts it. **cpu1 is the audio core.**

---

## 10. `las-frontend --script=` — a JavaScript sandbox with hardware access

**[READ]**, from `docs/arch/capability-survey.md` §B5, which read it out of the binary:
`las-frontend --script=<path>` runs JavaScript through JUCE's engine with five host
objects bound — `Console`, `Display` (including `showOled`, `setOledColour`),
`OSC`/`OSCSender` (`sendMsg`), `Panel` (`waitForChange`, `setLED`, `sendLEDs`,
`monitor`, `readValue`…), and `Utils.sleep`. Six factory test scripts are compiled in
as JUCE binary resources.

* **(a)** Panel automation, OLED drawing, LED control, OSC generation — the whole
  front-panel surface, scriptable.
* **(b)** cpu0, one process. No audio-thread impact.
* **(c)** **No** as a command-line flag — you would have to restart `las-frontend`
  by hand. Yes only if you edit `/etc/init.d/S43gui:21` to add the flag, which moves
  this into §11 and onto the Red list.
* **(d)** No.
* **(e)** ⚠ **`Panel` also exposes `calLoad`, `calSave`, `calDefaults`, `calSetLow`,
  `calSetMid`, `calSetHigh`, `calSetXYUpperLeft`, `calSetXYLowerRight`.** These are
  **calibration writes** — `docs/DANGER.md` Tier 1, the one category of damage that
  no backup in this repo covers if it lands on a voice card rather than `vxcal.db`.
  Any script harness must be treated as Tier-1-adjacent and must never call `cal*`.

That single fact is why this sits low in the ranking despite being, on paper, one of
the most capable surfaces on the machine.

---

## 11. Rootfs assets that are read at runtime and can be replaced

Everything in this section shares the same four answers: **(b)** no runtime cost of
its own, **(c)** survives a reboot, **(d)** **does not survive a firmware update**
(§12), **(e)** `docs/DANGER.md` puts most of it on the **Red** list — "reflash if
damaged", with `mmcblk2p2` (`las-v1.4.0`) as the fallback. So the table below covers
only **(a)**, what can be put there.

### The budget

**[READ]**, from the ext4 superblock of `captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz`:

```
s_block_size        1024
s_blocks_count      654331   = 670,034,944 bytes  (639.0 MiB)
s_free_blocks_count 189171   = 193,711,104 bytes  (184.7 MiB free)
s_inodes_count      8320     free 609
feat incompat 0x46 (filetype|recover|extents)   last_mounted "/"
```

**184.7 MiB of free data blocks and 609 free inodes.** The block size is 1 KiB, so
small files cost a 1 KiB minimum — and **609 inodes is the harder ceiling** for
anything that wants to add many files. (`docs/CLAIMS-AUDIT.md`'s "148 MB free on the
rootfs" is the same figure measured differently and at a different time.)

Root is mounted `rw,noauto,noatime` per `/etc/fstab`, but `S99final:44` remounts it
read-only at the end of boot **unless `/media/thumbdrive/k` is present** (§9).

### The inventory

| asset | size | read by | what it is |
|---|---|---|---|
| `/usr/share/las-fx/synthdefs/*.scsyndef` | 104 files, 450,964 B | `loadDirectory`, `init_sc_1.scd:36` | the effect algorithms (§5.2) |
| `/usr/share/las-fx/synthdefs/*.txarcmeta` | 104 files | `SynthDescLib`, the frontend's parameter list | per-parameter metadata |
| `/usr/share/las-fx/*.scd` | 6 files, 166,781 B | `sclang` at boot | the engine itself (§5, §11 warning below) |
| `/usr/share/las-fx/SCClassLibrary/**` | 201 files, 1,134,042 B | `sclang_config.yaml` `includePaths` | sclang classes, incl. 4 of the 5 "custom UGens" |
| `/usr/share/las-fx/ladspa/*.so` | 6 files, 2,423,108 B | `LadspaUGen.so` — *if* it looks there (§6) | the Eventide algorithms |
| `/usr/lib/ladspa/*.so` | 6 files, a **different build** | probably the live path (§6) | ditto |
| `/usr/lib/SuperCollider/plugins/*.so` | 96 files | `scsynth` at start | the UGen set |
| `/usr/share/las-fx/tables/coefsEnvir` | **5,426,278 B** | `tables/load_tables.scd` | the wavetable / coefficient store — **loaded by `init.scd`, which is not the boot path**; `init_sc_1.scd` comments the load out at `:28`. So on the shipping configuration this 5.4 MB file appears to be **unused**. [INFERRED] |
| `/usr/share/vx_ee.scm` | 13,134 B | `las-sc --expr-syms` (`S42sc:4`) | the expression symbol table (§3.2) |
| `/usr/share/xmosfw/app_las_v2.1.2.bin` | 2,097,152 B | `las-sc --vcfw` | voice-controller firmware — **Red, Tier 1** |
| `/usr/share/xmosfw/app_vx_10M_v2.1.0.bin` | 164,096 B | `las-sc --vxfw` | voice-card firmware — **Red, Tier 1** |
| `/boot/moog_splash.fb` | 16,716,544 B | `dd` in `S12splash:21` | the boot splash, raw framebuffer for the 832×5022×32 fb1 |
| `/boot/moog_splash.bmp`, `_ver.bmp`, `_version.bmp`, `moog_logo.fb` | 1.1–16.7 MB each | — | the same artwork in other forms |
| `/etc/cgconfig.conf` | 597 B | `cgconfigparser`, `S43gui:8` | **CPU placement policy** — see below |
| `/etc/X11/xorg.conf` | 1,085 B | `X :0` from `S12splash:19` | `Driver "vivante"`, `fbdev /dev/fb0`, `Virtual 832 480` |
| `/usr/share/fonts/liberation/*.ttf` | 12 files, ~301–388 KB | fontconfig / Qt | the UI's scalable fonts |
| `/usr/share/fonts/X11/misc/*.pcf.gz` | 337 files | X core fonts | the `10x20` the xterms use (`S43gui:11`) |
| `/etc/init.d/S*` | 20 files | `rcS` | the boot sequence (§9) |
| `/etc/vxtune/{cal-limits.scm, mod-cal-limits.scm}` | 4,026 / 1,791 B | tuning | calibration bounds — **do not touch** |
| `/etc/git-tags` | 377 B | — | component versions: `LAS_FRONTEND 2.0.8`, `LAS_SC 1.1.0r2`, `LAS_FX v1.1.1r4`, `LAS_FW lasvc-v2.1.2`, `LAS_VX lasvx-v2.1.0`, `LAS_DWM v0.3.0`, `LAS_WATCHDOG v0.2.0`, `LAS_FWU v0.9.1`, `LAS_BUILDROOT v1.5.0` |
| `/etc/version`, `/etc/versionb` | 11 / 8 B | `lasfwu` slot comparison | `las-v1.5.0` |

### `/etc/cgconfig.conf` — the CPU placement policy, in one editable file

**[READ]** in full:

```
mount { cpuacct = /cgroup/cpuacct; cpuset = /cgroup/cpuset;
        cpu = /cgroup/cpu; memory = /cgroup/memory; }
group dsp      { cpuset { cpuset.cpus = 1; cpuset.mems = 0; }
                 cpu { cpu.shares = 100; } }
group frontend { cpuset { cpuset.cpus = 0; cpuset.mems = 0;
                          cpuset.sched_load_balance = 0; }
                 cpu { cpu.shares = 25; }
                 memory { memory.soft_limit_in_bytes = 16756736; } }
group sc       { cpuset { cpuset.cpus = 0; cpuset.mems = 0;
                          cpuset.sched_load_balance = 0; }
                 cpu { cpu.shares = 25; } }
```

Parsed by `cgconfigparser` at `S43gui:8`, and processes are placed into the groups by
`/usr/share/las-fx/assign-pids` (1,345 bytes), which `launch-sc-1:14` runs once the
`scsynth.cookie` appears. **This is the machine's whole CPU-affinity policy in 597
bytes** — `dsp` on cpu1, `frontend` and `sc` on cpu0 with a 16 MB memory soft limit on
the frontend. Anything reasoning about where work goes should read this file first.

### The splash screen, as the one genuinely low-stakes rootfs edit

`/boot/moog_splash.fb` is a raw framebuffer dump `dd`'d straight to `/dev/fb1` at
`S12splash:21`, after `fbset --geometry 832 480 832 5022 32` — hence the 16,716,544
byte size (832 × 5022 × 4). Replacing it changes what the instrument shows while it
boots and nothing else. It is on the Red partition, so a firmware update reverts it,
which for this particular file is a feature.

### The warning that belongs on every line above

`docs/DANGER.md:256`: **"A syntax error in `init_sc_1.scd` yields an instrument that
boots normally with no effects at all."** No error is shown, the panel behaves, and
the rack is simply silent. That failure mode — silent, complete, and easy to
misattribute — is why the `.scd` files rank so low in §14 despite being the most
capable rootfs surface.

---

## 12. The firmware package, and what a firmware update does to everything above

### The partition layout

**[READ]** `captures/arch-harvest/fstab`:

| device | mount | notes |
|---|---|---|
| `/dev/mmcblk2p2` | `/mnt/u1` `ro,noauto` | **firmware slot A** — currently `las-v1.4.0`, pristine |
| `/dev/mmcblk2p3` | `/` (via `root=` on the cmdline) | **firmware slot B** — currently `las-v1.5.0`, live |
| `/dev/mmcblk2p4` | `/var/lib/sys` `vfat` | the boot selector — U-Boot-readable |
| `/dev/mmcblk2p6` | `/var` | **presets, calibration, tuning — survives everything** |
| `/dev/mmcblk2p7` | `/mnt/fwu` | update staging; **wiped every boot** by `S14fs:51` |

### What the updater does

**[READ]** `captures/arch-harvest/lasfwu`:

1. Reads the currently booted partition from `/proc/cmdline` (`:465`), mounts both
   slots, compares `/etc/versionb`, and picks the **older, non-running** one as
   `$replacepart` (`:469-537`).
2. Unpacks the `.zip`/tar to a tmpfs, reads `MANIFEST` (json) for `image` and `sig`.
3. **Imports the GPG secret key out of `/etc/bob.bmp`** (`:637-638`):
   `( str /etc/bob.bmp 4 > "$MOUNTDIR/mmepk" ) ; gpg --import ... "$MOUNTDIR/mmepk"`
4. Decrypts `rootfs` with `--passphrase bob` (`:642`), then verifies `IMAGE-SIG`
   against the decrypted ext4 with `--always-trust` (`:686`).
5. Deletes the secret key (`:729`), then `dd`s the image onto
   `/dev/mmcblk2p$replacepart` (`:742`).
6. Writes the boot selector: `echo $replacepart > "/var/lib/sys/bootme"` (`:809`),
   plus `sentinelu$part` and `bootversion`.

The package on disk matches: `captures/firmware-1.8.2/pkg/` holds `MANIFEST`,
`MOOGFW`, `rootfs` (156,599,799 bytes packed → 670,012,416 unpacked), `IMAGE-SIG` and
`MANIFEST-SIG` **[READ]**.

### (d) — the answer for every surface above

**An update writes the *other* slot and then boots it.** So a modification made to
the live root filesystem is not erased by the next update — it is *orphaned*: still
sitting on the now-inactive slot, absent from the running system, and destroyed by
the update after that. In practice: **anything you put on the rootfs is gone on the
next update.** Anything on `/var` or on the USB drive is not.

That is the single most important sentence in this document for an owner who wants to
stay updatable.

### Could you build your own package?

**[READ]** the mechanism, **[INFERRED]** the conclusion. The keypair used to *sign*
the image is the same one shipped on every instrument at `/etc/bob.bmp`, imported
with both its secret and public halves, with the passphrase `bob` written into the
script, and the verification runs `--always-trust`. Nothing in `lasfwu` checks the
key's identity beyond `encrypt@moogmusic.com` at delete time.

**This project has not extracted that key and should not without the owner's explicit
go-ahead** (see the swarm brief's "currently blocked"). It is recorded here because
"a custom firmware package is impossible" would be a false entry on the closed-doors
list, and because it explains why the encrypted `pkg/rootfs` for 1.8.2 is decryptable
in principle from material already on the instrument.

**Value per risk: worst on the board.** It writes a whole partition. Everything a
custom package could do, §5, §9 and §11 can do with a file.

### Recovery, which is better than it looks

**[READ]** `docs/DANGER.md`: `mmcblk2p2` holds `las-v1.4.0`, complete and pristine —
no `S99moogd`, factory `blockSize = 128`. A damaged live rootfs is not a service
call; the fallback is already on the device. `captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz`
is an image of the live slot, and `captures/backup/README.md` carries the restore
procedure.

**What neither slot protects:** `/var/cal/*` and `/var/tuning.vxtune` — this unit's
own analog calibration, unique to its hardware, not regenerable without factory
equipment. `captures/backup/calibration-20260907-222301.tar.gz`, 66 of 66 files
verified. And nothing anywhere protects the sixteen voice cards' own flash or the
voice controller's flash.

---
## 13. The budgets, in one place

Every number here is cited above. This is the table to check before proposing
anything.

| resource | total | in use | free | source |
|---|---|---|---|---|
| **cpu1** (audio thread) | 95 % `SCHED_FIFO` throttle | 16.6 % on a freshly booted 496-ugen graph at `-z 128` | ~78 points, minus whatever the patch uses | `docs/CLAIMS-AUDIT.md` |
| an Eventide reverb | — | 23-33 % of a core on an idle engine | — | `docs/CLAIMS-AUDIT.md` |
| heavy FM through the rack | — | ~24 points | — | `docs/ROADMAP.md:120` |
| **cpu0** (shared) | 1.00 | 0.67-0.87 idle; the old SSH screen mirror saturated it | some | `moogd/README.md` |
| **RAM** | 507,956 kB | `MemFree` 11 MB, `MemAvailable` 96 MB at capture | ~96 MB | `runtime-state.txt` |
| `scsynth` real-time memory | 100,000 kB (`-m`) | — | fixed at start | `runtime-state.txt` |
| **private audio buses** | 112 (17…128) | 14 (50…63) | **98** | `synthdefs.scd`, enumerated |
| **hardware ADC channels** | 9 (buses 8…16) | 5 (ADC 2,3,4,5,6) | **4** (ADC 0, 1, 7, 8) | `synthdefs.scd`, enumerated |
| hardware DAC channels | 8 | 8 | 0 | `synthdefs.scd:564-571` |
| `scsynth` sample buffers | 1,026 (`-b`) | 0 allocated by `init_sc_1.scd` | ~all | `runtime-state.txt` |
| `scsynth` wire buffers | 128 (`-w`) | — | fixed at start | `init_sc_1.scd:13` |
| **effect slots** | 5 | 5 | 0 — a sixth caused dropouts | `init_sc_1.scd:51`, `CLAIMS-AUDIT.md` |
| parameters per effect, live | 15 (`/fxN/p/0…14`) | up to 4 on stock effects | ~11 | `efx_server.scd:195-215` |
| parameters per effect, in a preset message | 12 pairs | — | — | `efx_server.scd:391, 540` |
| **rootfs free space** | 639.0 MiB | 454.3 MiB | **184.7 MiB** | ext4 superblock |
| **rootfs free inodes** | 8,320 | 7,711 | **609** — the harder ceiling | ext4 superblock |
| `/var` free | — | preset DBs ~280 MB | ~3.3 GB | `docs/DANGER.md` |
| USB drive | 234 GB | — | ~all | `docs/CLAIMS-AUDIT.md` |
| **mod-matrix rows per timbre** | 20 observed max | up to 20 | — | three corpora, agreeing |
| compiled expression slots | 17 observed max (119 ÷ 7) | — | — | three corpora, agreeing |
| **expression constant registers** | **128** (`c (array 128)`) | 43 distinct in the factory library, highest `c64` | 85+ | `/usr/share/vx_ee.scm` |
| expression variables `v0…v15` | 16, not saved in presets | **0** | **16** | `/usr/share/vx_ee.scm` |
| external mod inputs `m0…m15` | 16, MIDI-mappable | **0** | **16** | `/usr/share/vx_ee.scm` |
| expression destinations | 126 in `vx_ee.scm`; 141-slot id space in the frontend | 71 used by the factory library | **55+** | `/usr/share/vx_ee.scm` |
| transforms | 42 names, 44-slot id space | 14 seen in the factory library | 28 | `las-frontend 0x7e42005` |
| CV outputs | 4 | assigned in every preset | reassignable | `/p/part/cv_settings` |
| CV/pedal inputs | 5 | assigned in every preset | reassignable | `/p/part/cv_settings` |
| INSERT jacks | 4 | `dir4` used by **zero** factory presets | at least 1 | 1,581 timbre instances |
| EXT INPUT | 2 (COMBO, LINE) | enabled by **1** preset in 527 | effectively all | 527 presets |

---

## 14. Closed doors

Things that look like extension points and are not. Each one has already cost this
project effort; the citation is there so it stops coming back.

### 14.1 A second `scsynth` server, to reach the second core

**Closed. There is no second core to reach.** `isolcpus=1` reserves cpu1 *and* Moog's
patched `SC_AlsaDriver` claims it, pinning the audio thread there at `SCHED_FIFO` 99.
The design is complete. `taskset -p <pid>` shows only a process's **main** thread,
which is how this was missed — twice. `docs/CLAIMS-AUDIT.md`, "Wrong, and retracted",
five separate retracted claims.

The `init_sc_2.scd` two-server configuration is real, shipped, and its own comment
says what it is for: `// frontendGroup lives on shared CPU core, dspGroup lives on DSP
core` (`init_sc_2.scd:75`). It moves **non-DSP** work off cpu1. It does not double the
DSP.

A JACK-capable `scsynth` was built and confirmed loading on the instrument
(`tools/README-scsynth-jack.md`). The binary was never what stood between the
instrument and its second core.

### 14.2 Any audio path over the network

**Closed. 105-165 ms measured to the jacks** (`docs/ROADMAP.md:146`). The instrument's
value is being *inside* the sample clock, and that clock is generated on the analog
side — the XMOS is the ESAI bit- and frame-clock master and the computer follows it
(`docs/ARCHITECTURE.md`). A network path is outside it by construction.

**And the back panel already does the job at analog latency.** EXT INPUT and four
INSERT jacks (§8). The CLAP plugin's audio shapes were built against the software
surface alone and reimplemented hardware that was already there
(`docs/ROADMAP.md:147`). Its *automation* shape survives.

### 14.3 More reverb, or rebuilding the effects rack

**Closed. Five slots and ten pre-allocated Eventide instances already exist**
(`init_sc_1.scd:51-104`). Adding a sixth effect is what caused the dropouts that then
motivated the block-size change — a change since retracted
(`docs/CLAIMS-AUDIT.md`). The five slots the instrument ships with are inside its own
budget; a sixth is not.

### 14.4 Raising the block size

**Closed, and retracted as a bug report to Moog.** Insert effects read straight from
the ADC, so doubling the block doubles the skew between an insert-processed timbre and
an analog-direct one — roughly 8-11 ms to 16-21 ms. **128 is correct.** The measured
gain was ~4 points, not the 21 originally claimed. `docs/CLAIMS-AUDIT.md:19`.

### 14.5 Using `enable` as a mute, or freeing any node

**Closed, and it is the load-bearing invariant of the whole engine.** The six `et_*`
families carry `doneAction: 1` (pause); all 26 other definitions carry `doneAction: 2`
(free). Writing `enable = 0` on a native effect or on either router **frees the node**.
And `/n_free` on a LADSPA node **terminates `scsynth`** — confirmed 2/2. Moog's design
never frees them, so their code never hits it. `docs/ROADMAP.md:150-151`,
`docs/CLAIMS-AUDIT.md`.

### 14.6 Routing the bus effects to the aux / INSERT jacks

**Closed by the graph.** `master1_r` and `master2_r` in `outputRouter` have **no writer
anywhere**, and only index `[0]` (main) is live. The panel control that appears to do
this writes `dry_dir4_r` and produces only the DC bug. `docs/ROADMAP.md:149`,
`docs/arch/audio-graph.md:590-615`.

### 14.7 The Eventide spring reverb, as a quick win

**Closed for now, and for a specific reason.** `eventide_spring.so` ships in both
LADSPA directories and its SynthDef source is in `synthdefs.scd` — inside a `/* … */`
block at `:3629-3700`, so it was never compiled and does not appear in
`synthdef-names.txt`. The obvious fix does not work: the commented-out definition
passes the *plate's* argument list into plugin 29153, and both have ten ports, so it
maps positionally, compiles silently, and **every knob is the wrong knob**
(`docs/CLAIMS-AUDIT.md`; `docs/arch/doc-audit.md` §1.4, §2.6). It is also missing
`pan` and `gain`, and it would need to be `et_spring_1`/`et_spring_2`, not a bare
`et_spring`, to match how the rack selects.

Not impossible — but not a quick win, and it needs the real port order first.

### 14.8 `M_Delay.so`, `M_Phaser4.so`, `M_Vocoder.so`, `SIMDBPF.so`

**Closed. They are not loaded.** They sit in
`/usr/share/las-fx/SCClassLibrary/Effects/`, not in `/usr/lib/SuperCollider/plugins`;
`SC_PLUGIN_PATH` is set nowhere on the filesystem; no `.scsyndef` and no line of
`synthdefs.scd` references any of them; and their `Makefile` is hardcoded to
`/Users/gregsurges/…` and builds macOS `.scx` bundles. **[READ + INFERRED]** Leftovers
from a developer checkout.

### 14.9 Swapping a `.so` to change `StereoSpread`, `Flanger`, `DualChorus` or `Phaser6Stage`

**Closed — there is no `.so` to swap.** Four of the five are plain sclang classes in
`/usr/share/las-fx/SCClassLibrary/Effects/`, resolved at SynthDef-compile time. Only
`Decimator` is a compiled UGen. Changing their behaviour is a text edit plus a
recompile of the affected `.scsyndef` files. **[READ]**

### 14.10 `seq_expression_slots`, as a second expression space

**Closed until someone finds a preset that uses it.** It is **empty in every preset in
every corpus** — 222 `.m1p`, 398 in `MOOG ONE.db`, 129 in `SINGULARITY` — appearing as
`[]` or `null` and never as an array. The table exists; nothing populates it, and
there is no worked example anywhere. (An earlier pass of this report briefly counted
four "non-empty" values in `MOOG ONE.db`; they are the literal token `null`. Corrected.)

### 14.11 `/p/part/t/N/p/modmatrix/expressions` as a live OSC address

**Closed. It does not exist on current firmware.** It is a schema-≤12 preset-file
field. `grep -c "/expressions$" captures/p-namespace-keys.txt` → **0**; `las-frontend`
has no such code literal; `las-sc` has none. The live host-side surfaces are
`matrix_expression_slots` / `seq_expression_slots`. See §3.1.

### 14.12 The `/hw/` namespace

**Closed. The whole namespace 404s except `/hw/mute`**, and a zero-argument message to
a setter is inert. Inferring a *feature's* absence from a 404 there was itself an
error — the CV outputs are real and the `/hw/cvout/0` 404 said nothing about them.
`docs/CLAIMS-AUDIT.md`.

### 14.13 Running anything on cpu1

**Closed, and this one has bitten twice.** `taskset -c 1` on a web server put it on
the realtime audio core. Both `usb/S99moogd`'s header comment and `moogd/README.md`'s
"What is proven" section still carry the pre-correction wording; the code is correct
(`taskset -c 0`). §9.

### 14.14 Building your own firmware package as a delivery mechanism

**Not technically closed — see §12 — but closed on value per risk.** It writes a whole
partition. Everything a custom package could deliver, §5, §9 and §11 deliver with a
file, reversibly.

---

## 15. The ranking, by value per unit of risk

The ordering question is not "what is most capable" — the JavaScript sandbox and the
firmware package are the most capable things here — but "what returns the most for
what it puts at risk on an instrument the owner may want to keep stock".

### Tier 0 — free. Nothing is written to the instrument's software at all.

**1. Presets, and the modulation engine inside them (§2, §3).**
Enormous unclaimed surface: 55 of 126 expression destinations unused, 16 unused
external mod inputs, 16 unused engine variables, 85 unused constant registers, 28
unused transforms, 20 rows per timbre. Costs zero i.MX6 cycles, survives reboots and
firmware updates, and the failure mode is one bad preset. **This is where the work
should go.** The gap is authoring: the current schema wants compiled slot tuples, and
nobody has yet written one by hand and watched it load.

**2. The back panel (§8).** Four INSERT jacks, two EXT inputs, four CV outs, five
CV/pedal inputs, three MIDI DINs. Analog, zero latency, zero risk, and *almost
entirely unused by the factory library* — `dir4` in zero presets of 527, EXT enabled
in one. A cable does at analog latency what this project built a 115 ms network path
to do.

**3. The `/p` namespace as a live control surface (§7).** External sequencing,
automation, bulk editing. Writes nothing; the only traps are operational (the
secondary-address reply quirk, the inert `/hw/` namespace).

**4. Effect presets (§2).** 169 factory rows, a `(type, name)` unique key, and two
panel-knob assignments per preset. Purely additive.

### Tier 1 — reversible by deleting one file.

**5. The USB drive plus one init script (§9).** The whole machine's storage, compute
for anything non-realtime, and a web control surface — for the cost of one file in
`/etc/init.d/`, gated behind an opt-in marker, `exit 0` unconditional, cold-boot
tested. The correct shape for anything large. Its only real cost is that the drive's
`k` file, which is what makes the machine writable at all, **also kills the
watchdog**.

**6. `/fxN "<sclang>"` for experimentation (§5.1).** Highest capability per keystroke
on the machine, and it persists nothing. It is a *laboratory*, not a product: it needs
an external sender, it can take `scsynth` down, and recovery is a service restart.
Perfect for finding out what an idea sounds like before committing it to §5.2.

### Tier 2 — rootfs. Reversible, but erased by the next firmware update.

**7. New `.scsyndef` files (§5.2).** The supported path for a genuinely new effect
algorithm, and Moog left `compile-synthdefs`, `sclang` and the whole SC class library
on the device. Budget it against 78 free points on cpu1.

**8. New sclang classes in `SCClassLibrary` (§5.2).** Cheaper than a `.scsyndef` and
the same persistence. This is how four of the five "custom UGens" are already built.

**9. The splash screen and other pure assets (§11).** Genuinely low stakes; an update
reverts them, which for a splash screen is fine.

**10. A new LADSPA `.so` (§6).** Real native DSP, and the jessie/gcc-4.8/GLIBCXX-3.4.19
toolchain recipe is already written and proven. Two things hold it back: nobody has
established which of the two LADSPA directories is actually live, and the
`/n_free`-terminates-`scsynth` trap sits next to it.

### Tier 3 — high capability, high consequence.

**11. Editing `/usr/share/las-fx/*.scd` (§5, §11).** The most capable rootfs surface
and the one whose failure is worst-shaped: a syntax error boots an instrument that
looks completely normal and has **no effects at all**, with no error anywhere.

**12. `las-frontend --script=` (§10).** OLED, LEDs, panel and OSC from JavaScript —
and a **calibration-write API** on the same object. `docs/DANGER.md` Tier 1 is the one
class of damage no backup in this repo covers. Any harness here must be built so it
*cannot* call `cal*`.

**13. A signed firmware package (§12).** Everything, at partition scale, for something
a file could have done.

### The rule this ordering encodes

**An instrument that is still stock is still updatable, and stock is a feature.**
Tiers 0 and 1 leave it that way; Tier 2 and 3 do not. If the owner wants to keep
taking Moog's firmware updates, essentially all of the value on this list is in
Tier 0 — and Tier 0 is where the largest unexplored surface happens to be.

---

## 16. What would change once the 1.8.2 filesystem is readable

The instrument runs **v1.5.0**; **1.8.0/1.8.1/1.8.2** shipped in Aug-Sep 2025 and
`captures/firmware-1.8.2/pkg/rootfs` is GPG-encrypted and not decrypted. 1.8.2 is a
hotfix for 1.8.1 "which focuses on bug fixes and improvements to Moog One's MIDI
support" **[READ, the release-note PDF]**. Everything above is v1.5.0 unless it came
from the 222-preset 1.8.2 corpus, which is plain text and readable today.

Specifically, these would need re-checking:

1. **`/usr/share/vx_ee.scm`** — §3.2's entire symbol table. If the array sizes or the
   `results` list changed, every count in §3 and §13 moves. Highest priority.
2. **`/usr/share/las-fx/synthdefs/`** — whether the seven source-less definitions
   (`bitcrusher2`, `echo_0..2`, `spaceFlanger`, `spacePhaser`, `timeEnsemble`) are
   still there, and whether `et_spring` was ever uncommented.
3. **The two LADSPA directories** — whether they still diverge, which settles §6.
4. **`init_sc_1.scd`** — block size, slot count, bus assignments.
5. **`efx_server.scd:338-345`** — whether the `interpret` door is still open. Three
   releases of MIDI hardening is exactly the kind of work that closes it.
6. **`/etc/init.d/`** — whether `S99final`'s `k`-file behaviour and `S50dropbear`'s
   SSH gate are unchanged.
7. **The `/p` tree** — 1.8.x added MIDI functionality; `merge_avb_in` and the MIDI
   routing addresses in §8.5 are the likely place it landed.
8. **The mod-matrix schema** — v14 is already the current schema in the 1.8.2 corpus,
   so §3.1 should hold, but the transform and source id spaces in §3.5 were recovered
   from a v1.5.0 `las-frontend` and could have grown.

Nothing in the ranking of §15 depends on the answers. The Tier 0 surfaces are preset
data and back-panel hardware, and neither is version-fragile.

---

## 17. Where this document disagrees with the others

Per the brief, conflicts are reported, not fixed.

| # | document | what it says | what this report found |
|---|---|---|---|
| 1 | `docs/arch/capability-survey.md:47` | "64 constant registers" | **128.** `(c (array 128))` read out of `/usr/share/vx_ee.scm` in the rootfs image, corroborated at `docs/INTERNAL-DO-NOT-DISTRIBUTE.md:117`. `c64` is the highest *observed*, and it is a consequence of the 20-row cap and a 3-registers-per-row allocation. §3.2, §3.3. |
| 2 | `docs/arch/capability-survey.md:47, 116-126` | "36 shaping operators" | **42 names in a 44-value id space** (`las-frontend 0x7e42005`–`0x7e421a4`, id 43 = none). The list also omits `S&H` and does not record that `FUNCTION` uses `tr_a` as an integer index (`id = 11 + tr_a`), which is how thirty of them are reached. §3.5. |
| 3 | `docs/arch/capability-survey.md:298-310` (B1) | "Four compiled effects the panel will not let you select" | **Seven.** `bitcrusher2`, **`echo_0`, `echo_1`, `echo_2`**, `spaceFlanger`, `spacePhaser`, `timeEnsemble`. Independently recomputed for this report; `docs/arch/audio-graph.md:870-885` already has the correct seven. |
| 4 | `docs/arch/capability-survey.md:536-541` | the CV-output source enum starts at `0x7e804a7` and has 24 names | The first ten entries at `0x7e804a7`–`0x7e80516` are the **CV-input** destination additions; the output-source block starts at `0x7e80529`. The 10/14 split matches the v1.5.0 release note verbatim. §7. |
| 5 | `docs/ROADMAP.md:281-282` | "SEND 1 and SEND 2 are physical jacks — they show on the meter strip" | Very likely wrong. `las-frontend`'s OUTPUT MATRIX enumerates the analog output jacks exhaustively — MAIN L/R, SUB L/R, INSERT 1-4 — and has no SEND rows. Sends 1 and 2 are **hardware ADC channels 2 and 3**, fed by analog send VCAs on the voice card (`las-sc`: `send1 vca gain`, `/cal/aux1`), with meters at `/a/stat/send1`/`send2`. **[INFERRED]** internal taps, not jacks. |
| 6 | `docs/ROADMAP.md:147` | EXT INPUT is a "Neutrik combi + LINE" with "TRIM −9 to +65 dB"; the INSERT jacks are "tip = send, ring = return, stereo-normalled pairs" | Uncited, and **not substantiated anywhere in this repository**. The firmware's own word is `COMBO`; the trim range appears in no file; no `TIP`/`RING`/`normalled` string describes the INSERT jacks. Probably right — but there is no manual in `captures/`. §8.1. |
| 7 | `usb/S99moogd:18-19` and `moogd/README.md` "What is proven" | "It runs on cpu1, which `isolcpus=1` reserves and nothing else uses"; "pinned to the isolated core, confirmed `mask=2 last-cpu=1`" | Pre-correction wording. `docs/CLAIMS-AUDIT.md` retracts it and the code is already right (`taskset -c 0`). §9, §14.13. |
| 8 | `docs/arch/effects-engine.md:993` | "How does scsynth actually find `/usr/share/las-fx/ladspa`?" — open | Mostly answered. `LADSPA_PATH` is set **nowhere** durably (zero hits in the whole `/etc` tree, no `/etc/environment`), and `/usr/lib/ladspa` holds a **different build** of five of the six plugins. **[INFERRED]** the `/usr/lib/ladspa` copies are the live ones. One `strings LadspaUGen.so` closes it. §6. |
| 9 | `captures/arch-harvest/runtime-state.txt` | `scsynth … -z 256 -Z 256` | This project's own edit, captured before the restore. Stock is 128 (`init_sc_1.scd:9-10`). Already settled at `docs/arch/doc-audit.md` §0.1; repeated because `runtime-state.txt` carries no warning and is the file people reach for. §5.3. |
| 10 | `captures/backup/README.md` | the rootfs image is "the live root filesystem, ext4 verified" | True, and it is **not a factory-stock baseline**: `/etc/init.d/S99moogd` is present in it (2,755 bytes). The image was taken while this project's modification was installed. Anyone wanting a pristine `/etc/init.d` must use `mmcblk2p2` (`las-v1.4.0`), not this image. §11. |
| 11 | the swarm brief | "the modulation expression language … stored as plain text in presets" | True of schema ≤ 12 and **false of the current v14 schema**, which stores compiled 7-tuple slots and has no `expressions` field at all. The language is the same; the storage is not. §3.1. |
| 12 | the swarm brief | "43 distinct constant registers used, and `c64` appears — so the register file is at least 65 wide" | Correct as far as it goes, and the actual number is **128**. §3.2. |
| 13 | the swarm brief | "the ten `et_*` defs use `doneAction: 1`" | Confirmed, with a nuance: there are **six** `doneAction: 1` lines in `synthdefs.scd` (`:3407, 3492, 3576, 3657, 3735, 3817`) producing ten compiled definitions, because five families expand via `(1..2).do` and the sixth — `et_spring` at `:3657` — is inside the commented-out block and produces none. §4, §14.7. |

---

## 18. What is still unknown, and what would close it

Ordered by what it would unlock.

| # | unknown | how to close it |
|---|---|---|
| 1 | The XMOS expression **evaluation rate** | Not in `las-sc`, `las-frontend`, either XMOS image (both de-obfuscated and searched), or any doc. Would need measurement — drive a fast source and watch a CV out on a scope. |
| 2 | Whether `matrix_expression_slots` is **settable** over OSC, or derived | Write one into a `.m1p`, import from USB, read the tree back. Safest probe is loading a preset, not hand-sending to `:7770`. |
| 3 | Whether `/p/pre-expr` / `/p/post-expr` accept a program | Same session. |
| 4 | Which LADSPA directory `scsynth` actually loads | `strings /usr/lib/SuperCollider/plugins/LadspaUGen.so \| grep ladspa` — one command, on a copy. |
| 5 | Max expression length and max statement count | No string evidence exists. Would need a synthetic preset that grows until it breaks. |
| 6 | The full `source` / `dest` enums for CV out and CV in | Only the v1.5.0 additions are contiguous and readable in `las-frontend`; the base set is deduplicated into the string pool. |
| 7 | Whether `merge_avb_in` (MIDI over the RJ45) functions | It exists as a preset key and nothing else — no AVB string in `las-sc`, no daemon. |
| 8 | Whether the USB-A host port supports USB-MIDI class devices | No evidence either way. |
| 9 | What the global `gate_gain` setting does | It is the likely answer to "can EXT INPUT pass without a held note" (§8.2). |
| 10 | How `/media/thumbdrive` resolves to `/var/local/media/sda1` | No udev rule in the harvest. |
| 11 | `-C 0` on the `scsynth` command line | Not a flag in any SuperCollider version this report could identify. |
| 12 | The INSERT jacks' electrical arrangement, the EXT trim range, the output levels | **All of these are in the owner's manual, which is not in this repository.** Getting it into `captures/` is the single highest-value, lowest-effort next step for §8. |
