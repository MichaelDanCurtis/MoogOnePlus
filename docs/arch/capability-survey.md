# What this instrument can be made to do that its panel does not offer

A ranked survey of latent capability, assembled **entirely from local files** — the two
preset databases, `captures/arch-harvest/{las-sc, las-frontend, synthdefs.scd,
efx_server.scd, init.d/S42sc}`, the firmware images, and the earlier on-device sweep in
`captures/p-namespace-keys.txt`. Nothing was read from a live instrument for this document.

Grading follows `DANGER.md`:

* **[READ]** — directly observed in a binary, script, database or capture, with the
  citation given.
* **[INFERRED]** — reasoned from what was read. Plausible, not demonstrated.

Ranked by (value to a player) × (confidence) ÷ (risk). The rejected list at the end is
part of the answer, not an appendix.

---

## 0. The one thing that reframes the rest

The `/p` tree is **two layers, not one**, and the interesting one was hiding under the
other.

| layer | shape | who holds it | size |
|---|---|---|---|
| **host / preset** | `/p/part/t/<1-3>/p/<module>/<leaf>` | `las-frontend`, the SQLite `presets.data` column | 721 leaves per timbre, 3197 total |
| **engine / voice-controller** | flat `/p/<module>/<leaf>` and `<leaf>_m` | `las-sc` → VC at `203.0.113.2:7770` | 498 leaves, **106 of them `_m`** |

Intersecting them (flattening the DB's timbre-1 subtree) gives **195 shared leaves; 269
engine-only; 526 host-only** [READ, computed over `captures/MOOG ONE.db` and
`captures/p-namespace-keys.txt`].

**Zero `_m` leaves appear in any preset payload.** The host does not store modulation as
per-parameter mod slots. It stores it as **mod-matrix entries plus a compiled expression
program**, and something downstream turns that into `_m` writes on the voice bus.

That is the finding the rest of this document hangs off: the `_m` addresses are not a
hidden second modulation system. They are the **store targets of a small stack-machine
language** that the panel drives through a deliberately narrow editor.

---

# Tier A — high value, [READ], low risk

## A1. The modulation expression engine is a general postfix language, and the panel exposes one template of it

**What it is.** Every timbre carries a little program that runs at modulation rate on the
voice controller. It has arithmetic, min/max, 64 constant registers, store *and recall*,
36 shaping operators, and numeric literals. The panel's mod-matrix page can only write one
fixed sentence in that language — `source × amount → destination` — over and over.

**The evidence.**

`init.d/S42sc` boots `las-sc` with **`--expr-syms=/usr/share/vx_ee.scm`**, whose own help
text is *"File containing symbols for use in expressions."* (`las-sc` strings `0x1e5bfc`,
flag `0x1e5c37`). `las-sc` carries the symbol `expression-nodes` (`0x1e779f`) and the
addresses `/p/pre-expr` (`0x1e2d3f`) and `/p/post-expr` (`0x1e40a5`) [READ].

The language itself is stored **as text** in the preset payload. `mod_matrix_presets` in
`captures/SINGULARITY VOL 1 - GEOSYNTHS.db`, row `EP ONE GEO`:

```
/modmatrix/expressions "e3 c5 * o2pno sto  mw c1 * ofm sto  e3 c8 * mixrm sto  l4 c11 * vca sto"
```

and `LFO RATE GEO`:

```
/modmatrix/expressions "mw c1 * l1po sto  l4 c5 * l1f sto"
```

Reverse Polish. `<source> <constant> * <destination> sto`. **586 preset rows across the two
databases carry a `/modmatrix/expressions` string** [READ, counted over `presets`,
`snapshots` and `mod_matrix_presets` in both files].

The complete symbol vocabulary actually used by factory content — 96 non-numeric symbols,
plus `c1`–`c64` and bare numeric literals `1` and `1.0` [READ, tokenised from those 586
rows]:

* **operators** — `*` (5699), `+` (829), `-` (254), `**` (8), `***` (7), `min` (12),
  `max` (2), **`sto`** (4388), **`rcl`** (31), `rnd` (2), `rndb` (1)
* **sources** — `mw`, `padx`, `pady`, `padz`, `a` (aftertouch), `v` (velocity), `pw`,
  `pnt`, `en`, `e1`–`e3`, `l1`–`l4`
* **constants** — `c1` … `c64`, 42 distinct indices seen, highest `c64`
* **destinations (`sto` targets)** — ~70 symbols that map one-for-one onto the engine's
  `_m` addresses: `e1am e1dm e1rm e1s e1tm e2am e2dm e2rm e2s e2tm e3am e3dlm e3dm e3po
  ensrm fa2pn faegpn fafm falpn fapn far fbal fbegpn fbfm fblpn fbpn fbr l1f l1po l1pno
  l1v l2f l2pno l2v l3f l3od l3pd l3pno l4f l4pno l4v mixn mixo1 mixo2 mixo3 mixrm nsbal
  o1bal o1d o1fo o1pno o1tr o2… o3… ofm p1d p2d p3d pan pno vca`

Compare `/p/e1/am_m`, `/p/e1/dm_m`, `/p/e1/rm_m`, `/p/e1/s_m`, `/p/l1/f_m`, `/p/l1/var_m`,
`/p/fb/p_m`, `/p/mix/rm/g_m` in the engine vocabulary. **The 106 `_m` addresses and the
`sto` target list are the same set** [INFERRED, but the naming correspondence is
one-for-one across ~70 symbols].

Newer presets (`/p/version 14`) store the **compiled** form instead —
`matrix_expression_slots`, a flat array of alternating ints and floats, **exactly 7 tokens
per matrix entry** [READ; token-count histogram over the DB is `{7,14,21,28,42,49,56,63,70,105,119}`,
every value a multiple of 7]. Aligning 262 entries against their `src`/`ctl`/`tr`/`dst`
names decodes the id space:

```
src/ctl ids   0 KB GATE   3 VELOCITY   6 MOD WHEEL   8 PAD X   9 PAD Y
             10 AFTERTOUCH  11 PAD PRESSURE  18-21 LFO 1-4  22 FILTER EG
             24 MODULATION EG  33 KEY PITCH  48 = none
transform ids 1 LIMIT HIGH   6 SLEW   7 SLEW UP   43 = none
dest ids      0 l1/f … 141 = none      (141 destination slots)
```

**The transform set is 36 operators, and factory content uses six of them.** The full list
sits contiguously in `las-frontend` at file offsets `0x7e42005`–`0x7e421a5` [READ]:

```
DIODE(S-C-0.25)  DIODE(S-C+0.25)  DIODE(S-C-0.5)  DIODE(S-C+0.5)  DIODE(S-C)
C|V|+S   V+C(V+S)   (C+1)V+S   CV+S   C(S-V)
HIPASS S OVER C   LOPASS S OVER C   SLEW S OVER C
TRACK S WHILE ~C  TRACK S WHILE C   SAMPLE S ON ~C   SAMPLE S ON C
QUANTIZE S BY C   S OR C   S AND C   MAX(S,C)   MIN(S,C)   |S+C|
SAW(S+C)  TRI(S+C)  SIN(S+C)  (S+C)^2  S/(1-C)
FUNCTION  BOUNCE  SLEW DOWN  SLEW UP  SLEW  HIPASS  LOPASS  CUBED  SQUARED
LIMIT HIGH  LIMIT LOW
```

Across all 398 presets in `MOOG ONE.db` the only transforms ever used are `LIMIT HIGH`
(15), `CUBED` (13), `SQUARED` (8), `SLEW UP` (3), `SLEW` (2), `LIMIT LOW` (1) [READ].
Sample-and-hold, track-and-hold, a quantiser, boolean logic, waveshapers, rectifiers and
one-pole filters **on the modulation signal** are all sitting there unused.

**Cost.** Zero on both cores. This runs on the XMOS voice controller, not on the i.MX6 —
neither `modmatrix` nor `matrix` appears anywhere in `las-sc`, `app_las_v2.1.2.bin` or
`app_vx_10M_v2.1.0.bin` as a string [READ, negative], so the evaluator is compiled code on
the VC and the host only ships it programs. Storage: a few hundred bytes per preset. The
build cost is an editor and a symbol table.

**What could go wrong.** `/usr/share/vx_ee.scm` is **not in this capture set** — the symbol
table has to be recovered from the device or reconstructed from the 96 attested tokens.
A malformed expression's failure mode is unknown; the parser lives on the processor whose
firmware `DANGER.md` D2 says is reflashable over plain OSC, so a crash there is a bigger
deal than a crash on the host. Writing expressions is preset-state only — not `/cal`, not
`/fw` — so the Tier-1 hazards are not in play. Treat "send a malformed expression to the
VC" as unproven and test against a saved preset, not by hand-sending to `:7770`.

**Confidence: [READ]** for the language, the vocabulary, the compiled encoding and the
transform list. **[INFERRED]** for the claim that arbitrary well-formed expressions outside
the panel's 7-token template will be accepted and evaluated. That inference is the one
thing worth settling first, and it can be settled by *loading a preset*, which is the
safest possible probe.

---

## A2. The mod-matrix destination field is a free-text OSC address

**What it is.** In the stored format, "what this modulation moves" is a string containing
an OSC address. Not an index into the panel's list. Anything the address tree can name is
a legal destination.

**The evidence.** Every entry is eight leaves [READ, `captures/MOOG ONE.db`]:

```
/p/part/t/1/p/modmatrix/entry/0/src   "-"              src_a 1.0
/p/part/t/1/p/modmatrix/entry/0/ctl   "MOD WHEEL"      ctl_a 0.00999...
/p/part/t/1/p/modmatrix/entry/0/tr    "-"              tr_a  0.0
/p/part/t/1/p/modmatrix/entry/0/dst   "/p/part/t/1/p/m/l1_p"
/p/part/t/1/p/modmatrix/entry/0/mute  false
```

Proof that `dst` is not validated against an enum at save time: **four factory presets ship
`dst "/dummy"`** [READ]. Proof that it is not scoped to the owning timbre: of 3850 `dst`
values in `MOOG ONE.db`, **3724 say `t/1` regardless of which timbre's matrix they live in**
— and two say `t/2`, two say `t/3` [READ]. Somebody wrote a cross-timbre address and it
persisted.

Three numbers that bound the opportunity:

* **141** destination ids in the compiled encoding (`141` is "none").
* **106** `_m` addresses in the engine vocabulary.
* **75** distinct `dst` strings across all 398 factory presets.

The top destinations are unsurprising (`m/l1_p` 899, `fb/p` 453, `fa/p` 313, `pan` 153),
but the tail already contains things with no obvious panel knob — `p1/d`, `p2/d`, `p3/d`,
`m/l3_od`, `m/l3_pd`, `e2/tscale`, `fa/2/p` [READ]. And the frontend's destination-name
table (`0x7e41dbd`–`0x7e42005`) contains **`MASTER VOLUME`, `HEADPHONES`, `CV OUT 1`–`CV OUT 4`,
`VAR 1`–`VAR 10`, `TIME SCALE`, `EXT LEVEL`, `PITCH OFFSET`, `FM MOD`, `BEAT`** [READ].

**Cost.** Nothing but an editor. The write path is a preset row.

**What could go wrong.** A `dst` naming an address the VC does not implement is the
untested case — `vx-api-map.md` records that unknown addresses answer `404 Not found`, and
`DANGER.md` records `[TESTED]` that a zero-argument message to a live setter is inert, so
the likely outcome is "the route does nothing". Pointing a route at something in `/cal` or
`/fw` would be a different matter entirely (`DANGER.md` Tier 1) — **any destination editor
must refuse anything that is not under `/p/`.**

**Confidence: [READ]** that the field is free text and that cross-timbre strings persist.
**[INFERRED]** that a destination outside the panel's list is honoured by the engine rather
than dropped.

---

## A3. Thirty free modulation inputs nobody uses

**What it is.** Each timbre has ten scratch variables that are both writable state and
selectable modulation sources. In 398 factory presets, all thirty are zero.

**The evidence.** `/p/part/t/<1-3>/p/modmatrix/vars/var0` … `var9` — 30 leaves, present in
the live on-device tree (`captures/p-namespace-keys.txt`) and in every preset payload,
value `0.0` in all 398 [READ]. The matching source names `VAR 1` … `VAR 10` sit in the
frontend's mod-source table at `0x7e41f98`–`0x7e41fce`, with the group label `VARS` at
`0x7e42000` [READ]. `matrix_expression_slots` also has a sibling field
`seq_expression_slots` — the sequencer writes into the same machine.

`rcl` appears 31 times in factory expression text [READ]. The stack machine can read state
back, which is what makes a scratch variable useful rather than decorative.

**Cost.** Zero DSP. One OSC message per update. The rate is bounded by the control plane,
not the audio thread, so it lands on cpu0.

**What could go wrong.** This is the cleanest thing in the survey: writing a var is writing
a preset-tree float. The risk is operational — a controller flooding `:9300` or `:7770` is
exactly the microburst that `DANGER.md` Tier 2 describes as wedging the USB gadget, and a
saturated voice bus makes `las-watchdog` miss a `/ping`, which escalates to a **hardware
XMOS power-cycle** (`control-plane.md` §4.3). Rate-limit anything that drives these.

**Confidence: [READ]** that the addresses exist, are live, and are unused. **[INFERRED]**
that writing one takes effect immediately as a modulation source (they are named as
sources, so this is a short inference).

---

## A4. Patch generation, analysis and bulk editing are trivially feasible — at the SQLite layer

**What it is.** A Moog One preset is a text file. Not a blob, not a proprietary container.
You can read, diff, generate and bulk-edit patches with a text parser.

**The evidence.** Both databases are SQLite 3, page size 4096, written by SQLite 3.25.3.
**There is not a single BLOB column in the schema** [READ]. The payload table:

```sql
CREATE TABLE presets (id INTEGER PRIMARY KEY ASC, timestamp DATETIME NOT NULL,
  name TEXT, comment TEXT, synth1Name TEXT, synth2Name TEXT, synth3Name TEXT,
  data TEXT NOT NULL, CONSTRAINT uq_preset_name UNIQUE (name));
```

`data` is newline-separated `<OSC address> <JSON value>`:

```
/p/version 14
/p/part/t/1/p/o1/fo 0.9311074614524841
/p/part/t/1/p/l1/w "pulse"
/p/part/t/1/p/modmatrix/entry/0/dst "/p/part/t/1/p/m/l1_p"
```

Every value is valid JSON. **The address set of a `/p/version 14` row is set-identical to
the live on-device `/p` dump** — `diff` of the sorted unique sets is empty [READ]. A
round-trip parse of preset id 5 yielded 4697 of 4697 lines as `(address, typetag, args)`
with zero failures.

Sibling tables, all the same format on different roots: `effects_presets` (169 rows),
`mod_matrix_presets`, `sequence_presets`, `midi_map_presets`, `snapshots`, plus a
relational metadata layer — `tags` with `type` (SINGLE/MULTI/SPLIT/LAYER), `group`
(FACTORY/HORIZONS, or GEOSYNTHS in the content pack), 20 `category` values and 32 `mood`
values, joined through `preset_tags` [READ]. `sets` is `(setNumber, bankNumber,
presetNumber) → presetId`.

Where the 101 MB goes, by byte share of `presets.data` [READ]:

| share | subtree |
|---|---|
| 34.8% | `…/seq/n/l/<0-29>/s/<0-63>/{g,n,r,t,v}` — sequencer notes, written in full even when off |
| 29.3% | `…/types/<fxname>/<0-11>` — a full parameter cache for every FX type in every slot |
| 23.0% | the actual synthesis parameters |
| 6.3% | `…/p/c/<0-127>` (dropped at `/p/version 14`) |

**Cost.** Storage on the USB drive; the databases are ~280 MB total and `/var` has 3.3 GB
free (`DANGER.md`, Amber). CPU: off-box entirely. This is the one capability that costs the
instrument nothing at all.

**What could go wrong.** Four practical traps, all [READ]:

1. Strip the trailing ` #raw` annotation before JSON-parsing (426 occurrences in
   `MOOG ONE.db`, 1113 in the content pack, mostly on `o<N>/fo` and `l<N>/knobs/r`).
2. Rewrite the mod-matrix `dst` timbre index, or every route on timbres 2 and 3 aims at
   timbre 1 (see A2).
3. Handle payload versions 6, 8, 10 and 14 — they coexist inside one file, and the address
   sets differ by hundreds of leaves.
4. `presets.name` is `UNIQUE`.

And the operational trap: `/var/las-frontend` is **Amber** in `DANGER.md` — back up before
writing. Whether the device tolerates a *sparse* payload (one whose address set does not
match its `/p/version`) is unknown and needs a live test.

**Confidence: [READ]** throughout — schema, format, round-trip, byte census.

---

# Tier B — real, but each carries a caveat

## B1. Four compiled effects on the device that the panel will not let you select

**What it is.** `spaceFlanger`, `spacePhaser`, `timeEnsemble` and `bitcrusher2` are loaded
into `scsynth` at boot and cannot be reached from the effect-type list. Three more —
`flanger`, `chorus`, `ensemble` — are on the device and in the frontend's *internal* name
table but absent from its *display* list, so they are preset-reachable but not selectable.

**The evidence.** `captures/arch-harvest/synthdef-names.txt` lists 104 names loaded at
runtime. Four of them carry **no `_0..3` slot suffix at all**: `spaceFlanger`,
`spacePhaser`, `timeEnsemble`, `bitcrusher2` — and none appear in `synthdefs.scd`, so they
were compiled from source Moog did not ship us [READ]. `las-frontend` carries adjacent
tables at file offsets ~`0xa356a6` and ~`0xa357eb`: **31 internal type names, then 29
display strings** [READ]. The mismatch is `flanger`/`chorus`/`ensemble`.

Selection is by name, verbatim. `efx_server.scd:358` takes `effect = msg[1]` straight from
the OSC message, and `~initEffect` (line 225) calls `Synth(effect, target: ~efxGroups[unitNum])`
with no validation [READ]. **Any loaded SynthDef name can be instantiated in an insert slot
by sending it.**

Going the other way, four types the panel *offers* have no SynthDef on the device —
`spaceEnsemble`, `phaseEnsemble`, `phaser4stage`, and **`et_spring`** ("EVENTIDE SPRING"),
despite `eventide_spring.so` shipping in `table-and-ladspa-listing.txt` [READ]. Selecting
one makes `Synth()` fail and the slot keeps what it had.

No factory preset uses `vocoder21`, `spaceFlanger`, `spacePhaser`, `timeEnsemble`,
`bitcrusher2` or `et_spring` [READ, counted over `/fx/type` in the frontend's preset bank].

**Cost.** These are insert-slot effects, so they land on cpu1 with the rest of the graph.
Budget against 16.6% idle / ~82% loaded against a 95% `SCHED_FIFO` throttle
(`ARCHITECTURE.md`). An Eventide is 23–33% of a core; these are native SC graphs and will
be cheaper, but none is measured.

**What could go wrong.** Two `/fxN` messages to one slot inside ~250 ms leave a waiter
spinning forever (`DANGER.md` Tier 4). Sending an unknown name is a silent no-op, which is
benign but hard to distinguish from success. And nothing here goes near `/n_free` — do not
be tempted to tidy up afterwards.

**Confidence: [READ]** that the defs are loaded and that selection is by verbatim name.
**[INFERRED]** that they are usable and sound like anything — nobody has heard them.

## B2. `/fxN` with one argument executes SuperCollider source in the running engine

**What it is.** The door through which anything new gets into the live DSP graph without a
reboot. `efx_server.scd:344` — if a `/fxN` message has no second argument, argument one is
interpreted as SuperCollider code.

```supercollider
if( msg[2].isNil == true, {  ...  msg[1].asString.interpret;  })
```

`sclang` runs as root [READ, `efx_server.scd`; already recorded as `DANGER.md` Tier 3,
unauthenticated remote root on UDP 7775 bound to `0.0.0.0`].

**Why it is in the positive column.** Every idea in this survey that touches audio needs a
way to add a node, load a synthdef, or re-`set` a router argument on a machine with no
package manager, 148 MB free on root and a supervisor that restarts the world if you stop a
process. This is that way, and it is the only one that does not require a boot.

**Cost.** Whatever you inject. Nothing per-message.

**What could go wrong.** Everything, and it is already documented: this is the RCE, the
port is open to the LAN, and `/fx/start 1` on a nil `~serverPID` spawns ten more LADSPA
reverbs on a box with ~11 MB free (`DANGER.md` Tier 3). Anything built on this should bind
to loopback and be driven from the instrument, not across the network.

**Confidence: [READ].**

## B3. The sequencer is a 30-lane, 64-step, per-timbre grid with modulation lanes

**What it is.** Not a mono step sequencer. Per timbre: up to 30 note lanes × 64 steps, each
step carrying gate length, note, ratchet count, tie and velocity — plus separate modulation
lanes that write into the mod matrix.

**The evidence.** Address shape `/p/part/t/<T>/p/seq/n/l/<0-29>/s/<0-63>/{g,n,r,t,v}` and
`…/seq/m/l/<N>/s/<0-63>/o` [READ, both databases]. Decoded from real content (preset id 3,
`A DESTINY`):

```
/p/part/t/2/p/seq/n/l/0/s/0/  {g: 0.8, n: 50, r: 1, t: false, v: 117}
```

`g` = gate length 0–1, `n` = MIDI note (`-1` = rest), `r` = ratchet count, `t` = tie,
`v` = velocity 0–127 [READ, from the value domains]. Lane-count histogram across
`MOOG ONE.db`: 1 lane in 42 presets, 30 lanes in 63, and everything between [READ].
Modulation lanes: only ever **one** in factory content, and `/meta/numModLanes` /
`/meta/numNoteLanes` exist as metadata leaves [READ, `las-frontend` `/meta` namespace].

The link into A1 is explicit — `las-frontend` carries the symbol
`las::ModMatrix::Pimpl::updateSequencerParams(las::ModulationLane*)` at file offset
`0x7e41ec8` [READ], and the preset field is `seq_expression_slots` alongside
`matrix_expression_slots`.

Transport and edit vocabulary present in the binary: `SequencerLength` (variable length),
`RATCHET`, `FollowSwing`, `NoteReset`, `RestartOnHold`, `RestartOnTrigger`, `Record` +
`RecordingMode`, `OneShot`, `OutputMode`, `TransposeMode`, `KeyTranspose`,
`DivisionTiming`, `RTZ`, `MOVE UP` / `MOVE DOWN`, `STEP EDIT` [READ]. Router routes
`synth{1,2,3}SequencerNotes` and `synth{1,2,3}SequencerMods`.

**Negative result, and it matters:** there is **no** `Probability`, `Chance` or `Euclid`
anywhere in the binary [READ]. This is a deterministic sequencer with ratchets, not a
generative one. Anything probabilistic has to be built, and the cheapest place to build it
is the mod matrix's `rnd` / `rndb` sources (A1), not the sequencer.

**Cost.** 31.5 MiB of the 90 MB of preset text is sequencer notes, written in full whether
the sequencer is on or not. On the USB drive that is free.

**What could go wrong.** Same as A4 — this is preset data. The one unknown is whether the
device accepts a lane count it did not write.

**Confidence: [READ]** for the structure and field semantics. **[INFERRED]** that all 30
lanes are simultaneously playable — the instrument has 16 voices, so 30 lanes cannot all
sound at once, and what happens above 16 is untested.

## B4. Full MIDI mapping with 14-bit CC learn and NRPN — behind two feature flags

**What it is.** A complete MIDI-learn engine with 7- and 14-bit resolution, NRPN input and
output, and a `midi_map_presets` table to store maps in. Two of the three pieces are
switched off by a feature flag.

**The evidence.** `N3las11MidiMappingE` at `0x7e419f8`, with `/src_cc`, `/bit_depth`,
`/dst_path`, `/dst_index`, `" 14Bits"`, `" 7Bits"`, `"Added MIDI learn mapping CC:"` at
`0x7e41a18`–`0x7e41a94` [READ]. Note `/dst_path` — the mapping destination is an OSC path,
same trick as A2.

The feature-flag vocabulary, which `control-plane.md` §3.1 recorded as "not enumerable": the
RTTI name `N3las12FeatureFlagsE` sits at `0x7e41578` and the **three string literals
immediately following it** are `nrpnInput` (`0x7e415a0`), `nrpnOutput` (`0x7e415aa`),
`midiLearn` (`0x7e415b5`) [READ]. Each appears exactly once in the whole 145 MB binary.
**[INFERRED]** these are the accepted values of `--enable-feature=` / `--disable-feature=`.

Settings tree: `always_send_nrpn_numbers`, `sysex_device_id`, `output_running_status`,
`send_pots/keys/pitch_wheel/mod_wheel/aftertouch/xy_pad/sust_pedal/expression/midi_clock/
midi_start_stop`, `receive_midi_clock`, `receive_midi_start_stop`, a CC `assignments` map;
routes `midiMapping`, `quickMidiLearn`, `quickAssign`, `loadMidiMap`; flag `--print-nrpns`
[READ].

**Negative results [READ]:** no SysEx patch transfer (only a device-ID setting); no MTC or
MMC; **no MPE** — the only MPE classes are JUCE's own (`N4juce14MPESynthesiserE` etc.), with
no `las` MPE class and no MPE setting anywhere. MPE is not a wired feature of this
instrument and cannot be switched on.

**Cost.** cpu0. Storage negligible.

**What could go wrong.** `--enable-feature=` is passed on the `las-frontend` command line,
which means editing `S43gui` — **Red** in `DANGER.md` ("reflash if damaged"). Back up the
init script; a broken one gives you an instrument that boots with no GUI.

**Confidence: [READ]** for the engine and the flag names. **[INFERRED]** for the mapping
from those names to the command-line flag.

## B5. `--script=` is a JavaScript sandbox with hardware access, and the OSC object is the interesting part

**What it is.** `las-frontend --script=<path>` runs arbitrary JavaScript through JUCE's
engine, with five host objects bound. One of them sends OSC.

**The evidence.** `N3las15LASScriptRunnerE` at `0x7e49a68`. Host objects and their full
method vocabulary, read from the registration tables at `0x7e49bf0`–`0x7e4a178` and
`0x7e4b4e8` [READ]:

* `Console` — `debug`, `println`
* `Display` — `clear drawEllipse drawLine drawRect drawRoundedRectangle drawText fillAll
  fillEllipse fillRect fillRoundedRectangle setColour setFontSize activateChineseFont
  activateLatinFont showOled clearOled fillOled setOledColour`
* **`OSC` / `OSCSender`** — `sendMsg` (`0x7e49e90`; both global names at `0x7e49e98`)
* `Panel` — `waitForChange waitForValue waitForAtLeast waitForAtMost waitForReply
  waitForFullTurn waitForSpacebar setLED sendLEDs sendAllLEDs clearLEDs unflashLED`,
  plus `monitor` / `readValue` used by the factory scripts, plus **`calLoad calSave
  calDefaults calSetLow calSetMid calSetHigh calSetXYUpperLeft calSetXYLowerRight`**
* `Utils` — `sleep`

Six factory test scripts are compiled in as JUCE binary resources (`0x7f8b014`):
`BRD-10-011-1204_SYS_TEST.js`, `…1207_RIGHT_TEST.js`, `…1208_MIDDLE_TEST.js`,
`…1209_LEFT_TEST.js`, `FRONT_PANEL_ASSEMBLY_TEST.js`, `LHC_SUBASSEMBLY_TEST.js` [READ].

**Why it is Tier B and not Tier A.** `Panel.calSave` and `calSetLow/Mid/High` are
**calibration writes** — `DANGER.md` Tier 1, the one category of damage that no backup in
this repo covers if it lands on a voice card rather than `vxcal.db`. The existing D9 entry
says "arbitrary JS"; it should say "arbitrary JS with a calibration-write API". This
materially widens D9.

**Cost.** cpu0, one process. No audio-thread impact.

**What could go wrong.** A wrong script writes calibration. There is no signature check
anywhere in the update path (`DANGER.md` D10). Any script harness must be treated as
Tier-1-adjacent and must never call the `cal*` methods.

**Confidence: [READ]** for the object and method vocabulary, verbatim from the binary.
**[INFERRED]** for which OSC endpoints `sendMsg` can reach.

## B6. The per-timbre analog dry can be sent to the four aux outputs independently of the insert routing

**What it is.** `outputRouter` carries two separate matrices for the aux outputs — one for
the insert returns, one for the three per-timbre analog dry feeds. The panel writes both
from a single array, so they can never differ. A direct `/n_set` can decouple them.

**The evidence.** `synthdefs.scd:412-422` [READ]:

```
insert1_r = #[0, 0, 1, 0, 0, 0],   // main, sub, aux1, aux2, aux3, aux4
insert2_r = #[0, 0, 0, 1, 0, 0],
insert3_r = #[0, 0, 0, 0, 1, 0],
dry_dir1_r = #[1, 0, 0, 0],        // aux1, aux2, aux3, aux4
dry_dir2_r = #[0, 1, 0, 0],
dry_dir3_r = #[0, 0, 1, 0],
```

and `efx_server.scd:836-860`, the `/fxN/out` handler, which writes
`insert(N+1)_r := arr` **and** `dry_dir(N+1)_r := arr[2..]` from the same six-element
message [READ]. There is no other writer for `dry_dirN_r`.

Same shape for the dry pan: `dry_1_p`/`dry_2_p`/`dry_3_p` exist as arguments
(`synthdefs.scd:437-439`) but are only ever written by `/fxN/pan` through the coupled
formula `-1 * (1 + 2*(v-1))` (`efx_server.scd:759`), so **a timbre's dry pan is slaved to
its effect slot's pan and the two can be made to disagree only by a direct set** [READ].

**Cost.** Zero — these are existing control-rate arguments on an existing node.

**What could go wrong.** This is the neighbourhood of `DANGER.md` Tier 3, **DC at twice
full scale on an aux output**. `dry_dir4 = 1` is a bare integer (`synthdefs.scd:476`) and
`dry_dir4_r` is summed into all four aux outputs; the array-broadcast and `.sum()` double
it. Any tool that writes the aux block must leave `dry_dir4_r` at `#[0,0,0,0]`. Protect
monitors.

Also note the panning cost: `Pan2` is constant-power and the aux path folds with `.sum()`,
so hard-panning a timbre drops its aux level by 3 dB with nothing compensating [READ,
`synthdefs.scd:473-475`, `517`].

**Confidence: [READ]** for the arguments, the defaults and the coupling. **[INFERRED]** that
the compiled `.scsyndef` on the device matches this source — `effects-engine.md` §1.1 already
records a discrepancy between the harvested boot script and the running server, so this must
be verified against the loaded synthdef before relying on it.

## B7. The mod matrix can drive the four CV outputs

**What it is.** `MODULATION OUTPUT` is a selectable source for a CV output jack. Combined
with A1, that turns the instrument into a four-channel CV generator programmed in the
expression language.

**The evidence.** The CV-output source enum in `las-frontend` runs `0x7e804a7`–`0x7e80615`
[READ]: `EXPRESSION, PITCH V/OCT, ENV GATE, SOSTENUTO PEDAL, NEXT PRESET, PREVIOUS PRESET,
NEXT SET, PREVIOUS SET, SEQ RUN/STOP, SEQ RETURN TO ZERO, CV 1 INPUT, CV 2 INPUT,
PEDAL 1 INPUT (EXP 1), PEDAL 2 INPUT (EXP 2), SUSTAIN PEDAL INPUT, SEQUENCE PITCH (U),
SEQUENCE PITCH (B), SEQUENCE GATE, SEQUENCER RTZ, **MODULATION OUTPUT**, MIDI CC 2 (BREATH),
MIDI CC 4 (FOOT PEDAL), MIDI CC 11 (EXPRESSION), MIDI CC 74 (BRIGHTNESS)`.

`CV OUT 1` … `CV OUT 4` also appear in the **mod-matrix destination** name table at
`0x7e41fd5`–`0x7e41ff9` [READ], which is the other half of the link.

Preset storage: `/p/part/cv_settings/cv_output/<1-4>/{source,min,max,synth}` and
`cv_input/{cvin_1,cvin_2,expr_in_1,expr_in_2,sustain}/{dest,min,max,synth,type}` — 37
leaves [READ]. Across all 527 presets in both databases, the only output sources ever used
are `PITCH WHEEL`, `MOD WHEEL`, `GATE`, `PITCH CV`, `NONE`, `SEQUENCE GATE` (4 presets) and
`PITCH (B)` (2). **`MODULATION OUTPUT` is never used by any factory preset** [READ].

This overlaps `ROADMAP.md` item 9 (`/hw/cvout/0`) — that entry is about the engine address;
this is about the preset-level routing that selects what feeds it.

**Cost.** Nothing on either core.

**What could go wrong.** `OUT VOLTAGE MIN` / `OUT VOLTAGE MAX` exist as settings
(`0x7e802bb`, `0x7e802cb`) but their range is unread. Wrong values on a CV out go to
somebody's Eurorack. Verify the scaling before patching it into anything with a filter
input.

**Confidence: [READ]** for the vocabulary and the non-use. **[INFERRED]** that
`MODULATION OUTPUT` is fed by the mod matrix's `CV OUT n` destinations rather than by some
other internal signal.

## B8. Bulk tuning-table import

**What it is.** A 100-entry per-preset pitch table with a root and a type flag. Scala-style
scales, imported in bulk rather than typed on a 832×480 screen.

**The evidence.** `/p/part/tuning/pitch_0` … `pitch_99`, `/p/part/tuning/root`,
`/p/part/tuning/type` — 132 leaves under `/p/part/tuning` in the live tree, defaults
`pitch_n = n`, `root 0`, `type false` [READ]. Panel routes `settingsTuning`,
`settingsTuningEditor`, `settingsRenameTuning`, `settingsCopyTuning`, `masterTuning` [READ].

**This is panel-exposed** — the capability is not the feature, it is doing it at scale
through the database instead of through the editor.

**Cost.** Storage only.

**What could go wrong.** Nothing beyond A4's caveats. `pitch_99 = 99.0` at default suggests
the unit is semitones, not cents, but that is **[INFERRED]** and a wrong unit makes a
badly-out-of-tune instrument, not a broken one.

**Confidence: [READ]** for the addresses. **[INFERRED]** for the units and for whether the
table is 100 notes or 100 scale degrees.

## B9. Per-voice enable/disable

**What it is.** A panel route and a persisted setting that mask individual voice cards on
and off.

**The evidence.** Screen route `VoiceEnableDisable`, class `23VoiceEnableDisablePanel` at
`0x7e98294`, setting key `enabled_voices` at `0x7e43ab7` [READ]. This is the same surface as
the recent commit *"opcode 8 is the voice-allocation mask, not a mystery"*, seen from the
frontend side.

**Cost.** None.

**What could go wrong.** Masking voices changes what the watchdog sees. `las-watchdog`
defaults to **expecting 8 voices on a 16-voice instrument** and pings `i` up to `count/2`
(`control-plane.md` §4); a card that does not answer logs `"VC IS STILL UP BUT A VOICE IS
DOWN"` but does not escalate. Masking below that is untested.

**Confidence: [READ]** for the route and setting. **[INFERRED]** for the interaction with
allocation and the watchdog.

---

# Tier C — noted, weakly evidenced, do not build on yet

* **`/p/pre-expr` and `/p/post-expr`.** Both exist in `las-sc`'s vocabulary (`0x1e2d3f`,
  `0x1e40a5`) and in **neither** the preset tree nor the live sweep [READ]. The names say
  "expression evaluated before / after the main pass", which would be a per-timbre global
  program independent of the matrix. Semantics entirely **[INFERRED]**. Worth one static
  read of the VC firmware's dispatch before anything else.
* **`/p/e4` — a fourth envelope.** 15 leaves in the engine vocabulary (`a d s r h ak dk rk
  delay key-follow latch loop multi-trig sync trig`), with **no `_m` twins**, **no preset
  storage**, and **no response in the on-device sweep** (`grep -c e4
  captures/p-namespace-keys.txt` → 0) [READ]. Most likely dead vocabulary from a firmware
  that is not this one. Recorded so nobody re-discovers it and gets excited.
* **`/p/p1/d`, `/p/p2/d`, `/p/p3/d` and their `_m` twins.** Real destinations — 63/78/48
  uses as `p1d`/`p2d`/`p3d` in factory expression text, and 59/50/45 as `dst` strings
  [READ]. What they are is unknown. Not `o<N>/d` (duty), which exists separately. Three of
  something, one per oscillator. Worth naming.
* **`/dbg/oscl_ctl`** — a debug hook in the engine namespace, one leaf, unmapped [READ,
  `control-plane.md` §1.2].
* **`LIGHT SHOW`** — a settings-menu string at `0x7e802e6` sitting between `VOICE RULE` and
  `RESTORE DEFAULT SETTINGS` [READ]. No associated class found. Panel-LED demo mode, most
  likely. **[INFERRED]**, and trivial.
* **`libcurl` and JUCE `WebInputStream` are linked into `las-frontend` and nothing uses
  them.** Zero Moog, telemetry, analytics or update hostnames in the binary; every
  `http(s)://` literal is certificate-authority, font or XML-namespace boilerplate [READ,
  negative]. Latent HTTP-client capability, no endpoint. Recorded because it is the kind of
  thing that looks like a discovery later.

---

# Rejected — the architecture forbids these, and here is the citation

These should not come back.

**More reverb, or any significant added DSP.** Five effect slots, ten pre-allocated
Eventide instances, all created at boot and never freed. The audio thread reaches ~82% of
cpu1 against a 95% `SCHED_FIFO` throttle and one Eventide costs 23–33% of a core
(`ARCHITECTURE.md`). `isolcpus=1` gives the audio thread cpu1 alone and there is no third
core. Anything added goes on cpu0 or off-box.

**Rebuilding the effect rack, or "adding an effect send".** Three inserts, two buses, a
full native effect set, routing to main/sub/aux — it exists (`ARCHITECTURE.md`,
`effects-engine.md` §2).

**Anything in the live audio path over a network.** 105–165 ms measured to the jacks. The
instrument's value is being inside the sample clock (`ARCHITECTURE.md`). Network audio as a
*source* is a separate, already-working thing (`ROADMAP.md` 5a, 22.9 ms) and is not this.

**Freeing anything.** `/n_free` on a LADSPA node terminates `scsynth`. The load-bearing
invariant is `doneAction: 1` on the ten `et_*` synthdefs — every other synthdef uses `2`
(`DANGER.md` Tier 4). Do not "tidy" it.

**Routing the Eventide reverbs — or either bus slot — to sub or aux.** This was the most
promising-looking item in the brief and it is dead. `master1_r` and `master2_r` are declared
as six-element arrays (`synthdefs.scd:415-416`) but **only index `[0]` is live**; the sub
line (`synthdefs.scd:513-514`) and all four aux lines (`520-521, 530-531, 540-541, 550-551`)
are commented out. And **neither array has any writer anywhere** — no `set` in
`efx_server.scd`, `init_sc_1.scd` or `init_sc_2.scd` [READ]. Twelve coefficients declared,
two live, zero writable. The bus slots are hard-wired to main at unity. Changing this means
editing `synthdefs.scd` and recompiling, which is a firmware change, not a routing change.

**Worse, the panel control that appears to do this is actively harmful.** `las-sc` builds
master-slot addresses at runtime (`sc/fx.scm:797`, `update-master-fx` + `string-concatenate`,
with `"/out"` in the bare-suffix set), so `/fx3/out` is emitted **[INFERRED, strongly
supported]**. Its `insert4_r` target does not exist, but `dry_dir4_r` does — so routing bus
effect 1 to an aux has no audio effect at all and its only observable consequence is
full-scale DC on that aux (`DANGER.md` Tier 3).

**Sending the per-timbre digital dry to main or sub.** Same shape. `timbre_1_dry_main`,
`timbre_2_dry_main`, `timbre_3_dry_main` are declared (`synthdefs.scd:428-430`) and written
at runtime by `/fxN/dig-dry` (`efx_server.scd:952`), and the lines that would use them
(`495-497`, `507-509`) are commented out [READ]. A live OSC handler writing a control the
graph never reads. Do not build a "digital dry to main" feature on it.

**A per-slot mute.** `enable` is declared on `outputRouter` (`synthdefs.scd:402`) and the
def contains no `EnvGen` at all — completely inert. On `inputRouter` it is worse:
`EnvGen.kr(Env.asr(...), enable, doneAction: 2)` is computed and **never multiplied into
anything**, so its only surviving effect is `doneAction: 2` — `enable 0` **frees the node
instantly, with no fade**, and every send and insert return loses its path to both bus
slots until the engine restarts [READ, `synthdefs.scd:377, 380-385`].

**MPE.** Only JUCE's own `MPESynthesiser` / `MPEInstrument` classes are linked; there is no
`las` MPE class and no MPE setting anywhere in 145 MB [READ, negative]. It is library
residue, not a switched-off feature.

**SysEx patch transfer.** Only `sysex_device_id` exists. No dump, bulk or parser strings
[READ, negative]. MTC and MMC likewise absent.

**Probabilistic or Euclidean sequencing.** No `Probability`, `Chance` or `Euclid` anywhere
[READ, negative]. Build it in the mod matrix (`rnd`, `rndb`, `SAMPLE S ON C`,
`QUANTIZE S BY C`) instead.

**Preset randomise / morph / interpolate / undo in the frontend.** None exist as
operations. `morph` hits are user preset *names*; `randomisation` is a word in the embedded
English dictionary resource; `Undo`/`Redo` are JUCE keymap residue [READ, negative]. A
Compare (A/B) feature does exist (`CompareChangeListener` `0x7e409dc`, physical COMPARE
button). Anything else has to be built externally against the database (A4).

**An FX content-package install or authoring path.** `/package` is a version stamp inside
stored FX-preset payloads (`"0x10102"`, `"0x1001C"`), not an operation. There is no
`FxPackage` class, no `.fxpack` extension, no signing [READ, negative]. The only bulk
transfer is `ImportExportProcessor` moving whole `.db` files over USB.

**A PIN-gated service mode to unlock.** There is none. Service capability is delivered as
unlisted panels reached by `--test-fixture`, `--script=` or a settings path
(`control-plane.md` §3.3, negative result). Nothing is waiting behind a code.

**Anything that reaches `/cal/*`, `/fw/*`, `/load_cal`, `/load_tuning` or `/testosc/*`.**
`DANGER.md` Tier 1. `/var/cal/vxcal.db` and `/var/tuning.vxtune` survive a firmware
rollback and are the only truly irreplaceable state on the instrument. Every tool built on
this survey must refuse those prefixes by construction, not by convention — including the
mod-matrix destination editor of A2 and any `--script=` harness of B5.

---

## What to settle next, in order

1. **Recover `/usr/share/vx_ee.scm`.** It is the symbol table for A1, A2 and A3 at once,
   and it is a file read. Everything above is currently reconstructed from 96 attested
   tokens and a 141-slot id space; the file would make it exact.
2. **Load a preset carrying a hand-written expression** that the panel editor cannot
   produce — one extra operator, or one destination outside the 75 factory ones. That is a
   read-only probe of the riskiest inference in this document, using the safest mechanism
   the instrument has.
3. **Diff the compiled `.scsyndef` for `outputRouter` against `synthdefs.scd`.** B6 and
   three of the rejections rest on source that `effects-engine.md` §1.1 already warns is not
   what ships.
4. **Read the `/cal` dispatch in the controller firmware** and settle whether a
   one-argument message writes. `DANGER.md` demotes this to `[INFERRED]` and says how: find
   the handler, read whether it branches on argument count. No packets.
