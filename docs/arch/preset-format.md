# The `.m1p` preset format and the `/p` OSC namespace

Static analysis only. **No instrument was contacted** — no OSC, no MIDI, no ssh, no
network. Every claim below comes from files already on this disk.

## Evidence grades used here

| grade | meaning |
|---|---|
| **[TESTED]** | I ran an analysis program over files on disk and observed the result. The programs are described in §8 so the numbers are reproducible. This is *not* "tested on the instrument". |
| **[READ]** | read directly out of a binary, database or text file; file and offset given |
| **[INFERRED]** | reasoning from the above, not directly observed |

## Corpus actually used

| source | n | what | grade |
|---|---|---|---|
| `captures/firmware-1.8.2/corpus/Moog One v1.8.2/Past Preset Packs/**/*.m1p` | **222** | the six factory packs, the brief's corpus | [READ] |
| **`captures/arch-harvest/las-frontend`** | **580** | **complete `.m1p` bodies embedded in the firmware-1.5.0 UI binary, including the factory `INIT` resource.** Not previously used by this project. | [READ] |
| `captures/MOOG ONE.db` + `captures/SINGULARITY VOL 1 - GEOSYNTHS.db`, table `presets` | **527** | preset payloads out of two SQLite librarians | [READ] |
| `captures/p-namespace-keys.txt` | 3,197 lines | the previously harvested key list | [READ] |
| `captures/sysmap/addrs-p.txt` | 464 lines | the **engine** namespace — a different tree (see §4) | [READ] |

**1,329 preset payloads in total**, spanning preset-schema versions 6 through 14.
Headline counts (§2) are given over the briefed 222 so they are checkable against the
brief; every range and enum is additionally widened over all 1,329.

---

# 1. The file format

## 1.1 It is line-oriented ASCII, and the value grammar is JSON

```
/meta/name "SWEET DREAMS"
/meta/comment "BASS, BRASS ARP & LEAD.\n\nPRESS C3 TO START BOTH THE BASS & BRASS ARP."
/meta/type "SPLIT"
...
/p/version 8
/p/clk/loadPresetTempo true
/p/clk/rate 125.00000000000000000000
/p/lc/kbd/lhc/1/pad_xyz [0.50000762939453125000, 0.50000762939453125000, 0.0000000000000000000]
/p/part/t/1/p/o1/fo 0 #raw
```

Grammar, one line per parameter:

```
line    := address SP value LF
address := "/" segment ("/" segment)*          ; no spaces, printable ASCII
value   := json-value [ SP "#" tag ]
```

**Confirmed over all 222 files** [TESTED]:

* 222/222 pure **ASCII**, **LF** line endings, **no BOM**, **trailing newline present**.
* 222/222 parse with `^(/\S*) (.*)$` — **zero malformed lines**.
* 222/222 contain **no duplicate address** within a file.
* Non-ASCII is escaped, not emitted: `FASCINATЕ.m1p` (Cyrillic Е, U+0415) stores
  `/meta/name "FASCINATЕ"` and the file stays ASCII. [READ]

The value grammar is JSON: `true` / `false` / `null`, JSON numbers, JSON strings, JSON
arrays. `las-frontend` carries JSON-parser diagnostics —
`Expected a property name in double-quotes`, `Expected ':'`, `Unexpected character '`,
`Unexpected EOF in string constant`, `Unexpected EOF in array declaration`,
`Unexpected EOF in object declaration` [READ, `strings las-frontend`] — and the observed
value set is exactly JSON. **[INFERRED, strongly supported]**: the loader splits the line
at the first space and hands the remainder to a JSON parser.

## 1.2 String escaping

Escapes observed across the 222 [TESTED]: `\n` (2,273 occurrences), `\"` (2), `\uXXXX` (1).
No unescaped `"` inside any quoted value. Literal characters actually seen inside strings
are space, `!#&'()*+,-./0123456789:?`, `A-Z`, `_`, `a-z`. Longest string 900 characters
(a `/meta/comment`).

So: standard JSON string escaping. The multi-line comments the brief mentions are ordinary
`\n` escapes inside a single physical line — **a `.m1p` line never wraps**.

## 1.3 Why `1.0` and `1.00000000000000000000` both appear — three writer generations

This is a **serializer version**, not a type distinction. All of them are the same type
(`ParamFloat`, §1.6). I reconstructed all three float formatters and validated them token
by token against every non-integer numeric value in the 222 presets — **451,222 tokens,
100% explained, zero residual** [TESTED]:

| `/p/version` | formatter | rule | corpus tokens | fit |
|---|---|---|---|---|
| 6, 7, 8 (and 9) | **A** | `printf("%.20f", x)` — fixed, always exactly 20 decimals | 119,856 | 100% |
| 10, 11 | **B** | 16 significant digits in normalised scientific form, trailing mantissa zeros stripped, bare exponent (`e-1`, `e2`), and **a zero exponent is omitted entirely** | 25,249 | 100% |
| 12, 14 | **C** | **16 significant figures in fixed notation**, trailing zeros stripped but at least one decimal kept (`120` → `120.0`); falls back to formatter B when the required decimal count would exceed 20 | 306,117 | 100% |

Formatter B examples: `120.0` → `1.2e2`; `0.5` → `5e-1`; `0.0` → `0`;
`1.602994322776794` → `1.602994322776794` (exponent 0, so no `e`).

Formatter C is **`juce::String::toDecimalStringWithSignificantFigures(x, 16)`** or an exact
reimplementation of it: it computes `shift = 16 - ceil(log10(|x|))` and prints with
`shift` decimals. That is why `-1.012802113109501e-5` is written
`-0.00001012802113109501` — 20 decimals, 16 significant figures — while
`-1.144409154107962e-7` (which would need 22) drops to scientific. Reimplementing that
formula reproduces every v12/v14 token exactly. `las-frontend` is a **JUCE** application
(866 `N4juce…` mangled symbols; **zero Qt symbols**) and contains
`N4juce24NumberToStringConverters16StackArrayStreamE` [READ].

**Practical consequence:** a generator may emit any of the three. The parser is
version-agnostic JSON; the version tag selects schema, not number syntax. [INFERRED]

## 1.4 Values are 32-bit floats

`%.20f` output is full precision, so generation-A files show the exact decimal expansion of
whatever is stored. **47,438 of 47,531 v7 tokens and 72,113 of 72,325 v8 tokens are exactly
representable as IEEE-754 binary32** [TESTED]. `0.06f` is written
`0.05999999865889549255` — the exact binary32 expansion; a double would have printed
`0.06000000000000000333`. The ~0.4% that are not binary32-exact are all values below
~1e-6, where `%.20f`'s 20 decimals give fewer than 9 significant digits and the formatter
itself loses precision.

Round-tripping is safe in every generation: for all 451,222 corpus values,
`float32 → "%.16g" → float32` is exact [TESTED].

## 1.5 The ` #raw` suffix tag

`#raw` is the only suffix tag in the whole corpus (2,297 instances; no other `#tag`
exists) [TESTED]. It appears on exactly **nine normalised addresses**, all of them
rate-or-pitch controls that have a synced/free dual mode:

```
/p/part/t/{t}/p/o1/fo   /p/part/t/{t}/p/o2/fo   /p/part/t/{t}/p/o3/fo
/p/part/t/{t}/p/l1/knobs/r  …/l2/knobs/r  …/l3/knobs/r  …/l4/knobs/r
/p/part/t/{t}/p/arp/knobs/r  /p/part/t/{t}/p/seq/knobs/r
```

The same nine addresses also appear **without** the tag in other presets, and the tagged
and untagged value ranges overlap, so it is not a range or unit switch that I can pin
down from the corpus alone. `#raw` never occurs as a standalone string constant in
`las-frontend` — the only NUL-terminated instance is inside a unit-test fixture,
`/p/clk/rate1 20000.0 #raw` [READ, `las-frontend` offset 132403892] — so it is built by
concatenation at write time.

**What is certain** [TESTED]: it is a suffix on the value, it appears only on those nine
addresses, and it never changes the JSON value itself. **What is not known**: its
semantics. My best guess is "this number is the un-quantised knob/rate value rather than
the synced division", because those nine are exactly the parameters with a sync mode — but
I could not correlate it cleanly with the neighbouring `sync`/`div`/`tim` fields, so it
stays **[INFERRED, weak]**. A generator should simply omit the tag.

## 1.6 The type system, read out of the binary

`las-frontend` contains the RTTI names of the parameter-tree classes [READ]:

```
N3las13TreeComponentE   N3las4NodeE   N3las4RootE   N3las5ParamE
N3las10ParamFloatE   N3las9ParamBoolE   N3las8ParamIntE
N3las11ParamStringE  N3las10ParamArrayE
```

and, adjacent, the fragments of the `describe()` string it builds:

```
 type=Float   default=   min=   rest=   max=
 type=Int     type=Bool     type=Array
 type=String  default="   options=[
 generatesData=   blueprint=   blueprintInstance=   synthesized=
```

So there are **exactly five value types** — Float, Int, Bool, String, Array — a Float
carries `default`, `min`, `rest` and `max`, and **an enumerated parameter is a
`ParamString` with an `options` list**. That matches the corpus exactly: every string-typed
address either has a small closed value set or is free text. The tree also enforces
`the path of tree components can't contain slashes / can't contain spaces / can't be
empty` [READ].

I could **not** extract the `min`/`max`/`default` table itself — the tree is built by a
fluent API in code, not from a resource. The observed ranges in the schema JSON are
empirical, not declared.

## 1.7 Serialisation order

It is not a plain sort. The rule, **validated to 222/222 exact reproduction** [TESTED]:

1. The **9-line `/meta` block first, in fixed order**:
   `name, comment, type, category, mood, group, synth1name, synth2name, synth3name`.
   Identical in 222/222 files, and the same nine literals with their opening quotes sit
   consecutively in the binary as the writer's format-string table
   [READ, `las-frontend` offset 132395073].
2. Then a **pre-order walk of the `/p` tree**. At each node: emit that node's **scalar
   leaves first**, sorted, then recurse into **child nodes**, sorted. That is why
   `/p/version` precedes `/p/clk/...`, and why `/p/part/t/1/p/o1/tr` precedes
   `/p/part/t/1/p/o1/knobs/po`.
3. Sorting is **bytewise ASCII** — `.../p/0`, `.../p/1`, `.../p/10`, `.../p/11`,
   `.../p/2` — **except at two array nodes**, which are emitted in integer index order:
   `/p/part/t/{t}/p/modmatrix/entry` and `/p/part/t/{t}/p/seq/n/l`.

Getting the exception wrong is what makes a naive sort fail on 30 of the 222.

## 1.8 It is a complete state dump, and `.m1p` = `/meta` header + the librarian's blob

**Hard result** [TESTED]: for all **25** presets that appear both in the 222-file corpus and
in this unit's librarian (`captures/MOOG ONE.db`), the `.m1p` file with its first 9 lines
removed is **byte-identical** to the `presets.data` column. 25 matched, **0 differed**.

```
CREATE TABLE presets (id, timestamp, name, comment, synth1Name, synth2Name,
                      synth3Name, data TEXT NOT NULL, UNIQUE(name))
```

So the librarian is the canonical store, `data` is the `/p` body verbatim, and `.m1p` is
that body with the metadata columns re-serialised as a 9-line header. `/meta/category`,
`/meta/mood` and `/meta/group` have **no SQL column** — they must live elsewhere
(`tags`/`preset_tags`) and be reassembled on export. [INFERRED]

Each preset is a **full dump of the whole `/p` tree**, not a delta: median 3,578 lines,
114 KB–674 KB, 3,198–19,037 lines. All 222 carry all three timbres and the complete
128-note tuning table whether used or not.

But the *loader* clearly accepts fragments. The `PresetTests` fixtures compiled into
`las-frontend` include five-line and eighteen-line "presets"
[READ, `las-frontend` offset 132395635]:

```
/p/clk/rate 101
/p/clk/swing 0.1
/p/part/t/1/en false
/p/part/t/1/p/e1/a 0.9037
/p/part/t/1/p/e1/ak 0.0289
```

— no `/meta` block, no `/p/version`. See §5.

## 1.9 `/meta/*` — the categorical vocabularies

Enumerated from all 1,329 payloads [TESTED]. Counts are payloads, not presets in the 222.

**`/meta/type`** — 4 values, closed:
`SINGLE` (548) · `MULTI` (172) · `SPLIT` (54) · `LAYER` (28)

**`/meta/category`** — 24 values (23 + empty):
`PAD` 100 · `KEYS` 99 · `CLASSIC` 87 · `LEADS` 58 · `ATMOSPHERIC` 48 · `CINEMATIC` 48 ·
`ARPEGGIO` 44 · `STRINGS` 41 · `BASS` 37 · `MODERN` 32 · `BRASS` 30 · `LUSH` 26 ·
`PLUCKED` 25 · `PERCUSSION` 24 · `EVOLVING` 23 · `ORGANS` 18 · `SEQUENCE` 17 · `CHORD` 13 ·
`FX` 13 · `WINDS` 7 · `VOCODER` 5 · `MONO` 2 · `ORGAN` 2 · `""` 3

`ORGAN`/`ORGANS` and the lone `MONO` are almost certainly hand-typed strays — the field is
free text validated by the UI, not by the format. [INFERRED]

**`/meta/mood`** — 34 values (33 + empty):
`DREAMY` 105 · `NOSTALGIC` 71 · `BRIGHT` 57 · `CALM` 51 · `DARK` 46 · `COMPLEX` 42 ·
`COSMIC` 38 · `FUNKY` 37 · `AGGRESSIVE` 34 · `CHILL` 27 · `HEAVY` 26 · `ENERGETIC` 24 ·
`COLD` 21 · `EERIE` 20 · `MELLOW` 19 · `INTENSE` 19 · `HOPEFUL` 18 · `MYSTERIOUS` 17 ·
`MELANCHOLY` 16 · `WEIRD` 15 · `BLISSFUL` 13 · `SOMBER` 12 · `SUSPENSEFUL` 12 · `HAPPY` 12 ·
`SMOOTH` 11 · `PLAYFUL` 10 · `ATMOSPHERIC` 7 · `CHAOTIC` 6 · `LIGHT` 4 · `HARSH` 4 ·
`STOKED` 2 · `SAD` 2 · `SCARY` 2 · `""` 2

**`/meta/group`** — 10 values: `FACTORY` 367 · `TRANSFORMERS` 106 · `CLASSICS` 102 ·
`STEREO FUTURES` 90 · `KING` 52 · `POLYPHONIC DESTINATIONS` 26 · `HORIZONS` 25 · `MOOG` 18 ·
`1.0.4` 13 · `""` 3. This is the pack name, and `HORIZONS` names a **seventh pack not in
the 222-file corpus** — it is only in the firmware binary and the librarian.

`/meta/name`, `/meta/comment` and `/meta/synth{1,2,3}name` are free text. The longest `/meta/name` across all 1,329 payloads is 40 characters
(`CONFLUENCE - SOLO FOR MOOG FACTORY FLOOR`); the format itself imposes no limit I can see.

## 1.10 `/p/version` — the preset schema version

Not a firmware version. Values seen: **6, 7, 8, 9, 10, 11, 12, 14** (no 13) [TESTED].
Distribution across the 222: v7 ×18, v8 ×29, v10 ×45, v11 ×1, v12 ×29, v14 ×100.
All eight literals `/p/version 6` … `/p/version 14` are present in `las-frontend`, so the
loader branches on them [READ].

Schema deltas, restricted to changes that are **universal within their version** (present in
0% of presets before and 100% after, over all 1,329) [TESTED]:

| bump | change |
|---|---|
| 7 → 8 | **+** `/p/part/las-fx/spread`, `/p/part/t/{t}/p/mix/ngate/gain`, `/p/part/t/{t}/p/pan-spread` |
| 8 → 9 | **+** effect types `stereoChorus`, `stereoFlanger` (both insert and bus). **`/p/part/t/{t}/p/seq/p/rec_mode` changes type: bool → int** |
| 9 → 10 | **+** `/p/part/t/{t}/in/din0/note-enable`, `…/in/usb0/note-enable` |
| 10 → 11 | **+** the panel-knob shadow set `l1..l4/knobs/r`, `arp/knobs/r`, `seq/knobs/r`, `fx/knobs/{0,1}`. **−** `/p/part/t/{t}/in/midi/{ch,en}` |
| 11 → 12 | no address change observed |
| 12 → 14 | **the mod-matrix representation is replaced.** **−** `/p/part/t/{t}/p/modmatrix/expressions` (the RPN string) and **−** `/p/part/t/{t}/p/c/0…127` (the constant registers). **+** `matrix_expression_slots`, `seq_expression_slots`, `vars/var0…var9`, and (in 25% of v14) `vars/cvout1…4` + `cv_settings/cv_output/{i}/voice_rule` |

**This corrects a claim in the brief.** The constant-register file is
`/p/part/t/{t}/p/c/{0..127}` — **128 registers, not 64** [TESTED, index domain 0–127 in
1,122 payloads]. `c64` appearing in the RPN was never anomalous.

## 1.11 Sibling formats using the same line syntax

The same `address SP json-value LF` serialisation is used for other subtrees [READ]:

* `effects_presets.data` — root `/fx/…` (`/fx/mix`, `/fx/name`, `/fx/type`,
  `/fx/c/control1`, …), 169 rows in this unit's librarian.
* Sequence presets — root `/sequence/…` with its own header
  `/meta/version`, `/meta/numNoteLanes`, `/meta/numModLanes`, then `/sequence/n/l/…` and
  `/sequence/m/l/…` [READ, `LoadSequencePanel` strings].
* `snapshots.data` — a full `/p` body, same format, keyed to a preset id.
* The global settings blob lives in `global` under key `settings` and is a **different
  namespace**: 658 lines, all `/m/settings/…` [READ].

---

# 2. The namespace, reconciled

Machine-readable schema: **`docs/arch/p-namespace.json`** (611 KB).

## 2.1 Coverage, stated honestly

| | count |
|---|---|
| distinct normalised addresses over all 1,329 payloads | **764** |
| … of which typed with direct observational evidence | **764 (100%)** |
| … typed by guess | **0** |
| normalised shapes in `captures/p-namespace-keys.txt` | 734 |
| key-list shapes that **never appear in any preset** | **0** |
| preset shapes **missing from** the key list | **30** (9 `/meta/*` + 21 real `/p` shapes) |
| addresses seen in the 222-file corpus alone | 761 |
| addresses added by the 580 binary + 527 librarian payloads | 3 |

**The answer to "how many known keys are settings rather than preset state" is: none of
them, in this key list.** `captures/p-namespace-keys.txt` is a strict *subset* of preset
state — every one of its 734 shapes occurs in real presets. The settings live in a
separate root, `/m/settings/*`, 658 lines in the librarian's `global` table [READ]; they
are not `/p` at all. (The separate `captures/sysmap/addrs-p.txt` is a *third* namespace —
see §4.)

The 21 `/p` shapes the key list misses are all **optional or dynamically created** subtrees,
which is why a single-preset harvest missed them:

```
/p/lc/kbd/lhc/{i}/touch_x|touch_y|touch_z
/p/part/cv_settings/cv_output/{i}/voice_rule
/p/part/t/{t}/in/midi/ch, /in/midi/en                (dropped at v11)
/p/part/t/{t}/p/c/{0..127}                           (the 128 constant registers, ≤v12)
/p/part/t/{t}/p/modmatrix/expressions                (the RPN program, ≤v12)
/p/part/t/{t}/p/modmatrix/vars/cvout1..4
/p/part/t/{t}/p/seq/m/l/{i}/ctl|ctl_a|dst, .../s/{j}/o
/p/part/t/{t}/p/seq/n/l/{i}/s/{j}/g|n|r|t|v
```

## 2.2 Type census

| type | addresses | how it was decided |
|---|---|---|
| **float** | 431 | at least one value with a `.` or an exponent |
| **bool** | 128 | only `true`/`false` |
| **int** | 109 | only bare integers, **and** seen in at least one generation-A or generation-C file, where every float is guaranteed to print a `.` — that makes int-vs-float decidable rather than a guess |
| **string** | 88 | quoted; 79 of them are closed enums (≤ 40 distinct values), 9 are free text |
| **array** | 8 | `[...]`, or `null` meaning "unset" |

The int/float discrimination is the only subtle part. Generation B prints a whole-valued
float as a bare integer (`5.0` → `5`, `0.0` → `0`), so a v10-only address could be
mistyped. Restricting the "bare integer implies Int" inference to generation-A/C files
removes the ambiguity, and every one of the 109 ints has such evidence. **Exactly one
address has genuinely mixed evidence**: `/p/part/t/{t}/p/seq/p/rec_mode`, bool at v6–v8 and
int at v9+ (`0`, `1`, `2`) [TESTED].

## 2.3 Per-address content of the schema JSON

Each of the 764 entries carries:

```jsonc
"/p/part/t/{t}/p/l1/w": {
  "type": "string", "type_confidence": "observed",
  "in_p_namespace_keys_txt": true,
  "corpus222_presets": 222, "corpus222_instances": 666,
  "all_sources_presets": 1329,
  "preset_schema_versions": {"6":738,"7":36,"8":59,"10":220,"11":2,"12":58,"14":207},
  "index_domains": {"t": {"min":1,"max":3,"count":3}},
  "n_distinct_values": 4, "enum": true,
  "values": {"\"tri\"":3819, "\"saw\"":77, "\"pulse\"":46, "\"s-h\"":45},
  "factory_default": "\"tri\"",
  "corpus222_presets_differing_from_INIT": 221,
  "per_pack_differing_from_INIT": {"CLASSICS":51, "KING":26, ...}
}
```

`corpus222_range` and `observed_range` carry the numeric ranges; `examples` and
`null_instances` cover arrays; `raw_tag_instances` counts `#raw`.

**`factory_default` is the value in the JUCE BinaryData resource `INIT_m1p`, carved out of
`las-frontend` at offset 143838219** — the real factory INIT patch, `/p/version 6`,
3,386 lines [READ]. It covers **715 of the 764** addresses. The 49 it omits fall into two
groups. **32 addresses did not exist at `/p/version 6`**: `pan-spread`, `las-fx/spread`,
`mix/ngate/gain`, the `din0`/`usb0` `note-enable` flags, the `stereoChorus` and
`stereoFlanger` parameter banks, the `knobs/r` + `fx/knobs` shadow set, and the whole v14
`matrix_expression_slots` / `seq_expression_slots` / `vars/var0..9` block. **17 are optional
subtrees** that do not exist until the feature is used: the sequencer note and mod lanes and
their steps, `cv_output/{i}/voice_rule`, `modmatrix/vars/cvout1..4`, and
`lc/kbd/lhc/{i}/touch_{x,y,z}`. Adding the librarian's v14 slot-1 row as a fallback covers
747 of 764; only those 17 have no reference value at all.

A second field, `librarian_slot1_INIT`, records the row named `INIT` (id 1, `/p/version 14`)
in this unit's librarian. **Do not treat it as a default.** It differs from the factory
INIT at 106 shared addresses — unison on, EG1 at 2 s / 4 s / 32 s, both filter cutoffs
moved, LFO 1 set to pulse [TESTED]. Somebody edited slot 1 on this instrument.

## 2.4 Selected enumerations

Full lists are in the JSON; these are the ones a patch generator needs first.

| address | values |
|---|---|
| `…/p/o{1,2,3}/m` | `F` `v` |
| `…/p/l{1..4}/w` | `tri` `saw` `pulse` `s-h` |
| `…/p/l{1..4}/r` | `slow` `low` `mid` `high` (rate range) |
| `…/p/l{1..4}/rst` | `none` `leg` `trig` |
| `…/p/l{1..4}/tim` | `s` `d` `t` (straight / dotted / triplet) |
| `…/p/noise/mode` | `wr` `wp` `rp` |
| `…/p/pt/mode` | `lcr` `lct` `exp` (glide) |
| `…/p/sus/mode` | `sus` `sos` `off` |
| `…/a/note-pri` | `last` `low` `soft` `loud` |
| `…/a/note-steal` | `lru` `mru` `off` `quiet` |
| `…/a/voice-limit-mode` | `all` `avail` `fix` |
| `…/p/arp/p/direction` | `u` `d` `ud` `du` |
| `…/p/arp/p/pattern` | `u` `o` `r` `d` |
| `…/p/{arp,seq}/p/div` | `1/32` `1/16` `1/8` `1/4` `1/2` `1` `2` `4` |
| `/p/lc/kbd/curve` | `soft` `med` `hard` `comp` `exp` |
| `/p/lc/sus/type` | `norm` `inv` |
| `…/p/fx/ins/type` (per-timbre insert) | 19 observed: `none` + 18 effects. 19 parameter banks exist under `fx/types/`; only `vocoder21` is never selected |
| `/p/part/las-fx/{i}/type` (global/bus) | 21 observed: `none` + 20 effects, **including the five Eventide `et_room` `et_hall` `et_plate` `et_shimmer` `et_blackhole`**. 24 banks exist under `las-fx/{i}/types/`; `phaser6stage`, `vocoder10`, `vocoder16`, `vocoder21` are never selected |
| `…/p/modmatrix/entry/{i}/src` | 27 distinct: 25 named sources plus the two "none" spellings `-` and `""` (see §2.5) |
| `…/p/modmatrix/entry/{i}/tr` | 14 distinct: **12 named** — `SLEW` `SLEW UP` `SLEW DOWN` `LIMIT HIGH` `LIMIT LOW` `SQUARED` `CUBED` `LOPASS` `HIPASS` `BOUNCE` `S&H` `FUNCTION` — plus `-` and `""` |

The `.../types/<name>/...` subtrees exist for **every** effect type in **every** preset,
whether selected or not — the preset stores a complete parameter bank per effect so
switching type is instant. `las-fx` has the five Eventide `et_*` banks; the per-timbre
insert slot does not.

## 2.5 `matrix_expression_slots` decoded

`/p/part/t/{t}/p/modmatrix/matrix_expression_slots` is a flat JSON array of **exactly 7
tokens per mod-matrix entry**, in entry order. Verified: **300 of 300** timbre instances in
the 222-preset corpus have `len(slots) == 7 × (number of entries)`, **zero mismatches**
[TESTED]. Token counts are 0, 7, 14, … 119 — always a multiple of 7.

```
[ src_id, src_amount, ctl_id, ctl_amount, transform_id, transform_amount, dest_id ]
```

Aligning each group against the same preset's `entry/{i}/{src,src_a,ctl,ctl_a,tr,tr_a,dst}`
strings over all 1,329 payloads, and **excluding muted entries** (whose name fields go
stale while the slots do not), gives an unambiguous decode [TESTED]:

**source / control ids** (24 seen; 48 = none)
```
 0 KB GATE   3 VELOCITY   4 VEL RELEASE   6 MOD WHEEL   7 PITCH WHEEL
 8 PAD X     9 PAD Y     10 AFTERTOUCH   11 PAD PRESSURE
18 LFO 1    19 LFO 2     20 LFO 3        21 LFO 4
22 FILTER EG  23 AMPLIFIER EG  24 MODULATION EG  25 NOISE EG
28 RANDOM KEYED 1   29 RANDOM KEYED 2   30 RANDOM KEYED 3
33 KEY PITCH   36 CONSTANT   37 VAR 1   48 = none
```

**transform ids** (43 = none)
```
1 LIMIT HIGH  2 SQUARED  3 CUBED  4 LOPASS  5 HIPASS
6 SLEW  7 SLEW UP  8 SLEW DOWN  9 S&H  10 BOUNCE
14 / 23 / 25 / 28 / 30 all display as FUNCTION
```
`FUNCTION` occupying five distinct ids means the displayed name hides a function index;
the corpus cannot tell me which function each is. **unknown.**

**destination ids** — 66 distinct observed, e.g. `52 → /p/part/t/1/p/m/l1_p`,
`97 → …/p/fa/p`, `106 → …/p/fb/p`, `124 → …/p/pan`, `109 → …/p/fbal`,
`126 → …/p/modmatrix/vars/var0`. Full map in the JSON. **Both 137 and 141 appear with an
empty destination**, so the "none" sentinel is not a single id — a correction to the
earlier "141 = none" claim in `docs/arch/capability-survey.md`.

The id map covers **11 of the 12 named transforms**: `LIMIT LOW` appears in the `tr` string
enum but has **no observed id**, because no unmuted factory entry uses it.

---

# 3. The structural map

## 3.1 Top level

```
/meta/                      9 fixed lines (name comment type category mood group synth1-3name)
/p/version                  int, schema version 6..14
/p/clk/                     loadPresetTempo rate swing nudge_mode
/p/lc/                      local control: kbd/{curve,oct}, kbd/lhc/{…,1..3/…}, sus/type, xy/{hold,mode}
/p/mix/                     aux1-db aux2-db aux3-db aux4-db sub-db      (master sends)
/p/panel_focus/             closest synth1 synth2 synth3
/p/part/
    cv_settings/cv_input/   cvin_1 cvin_2 expr_in_1 expr_in_2 sustain   → dest min max synth [type]
    cv_settings/cv_output/  1..4                                        → source min max synth voice_rule
    las-fx/                 ser spread stereo                           (the two global/bus effects)
    las-fx/{1,2}/           en name sync type
    las-fx/{1,2}/p/{0..11}                                              live parameter bank
    las-fx/{1,2}/types/<21 effect names>/{0..11}                        per-type saved banks
    midi_io/                17 leaves — in/out ports, routes, per-synth channels, merges
    mix/                    ext-dir3 ext-dir4
    tuning/                 type root data name_0 + pitch_0..pitch_127  (132 leaves)
    t/O/p/tune/             fbase (440.0) po                            master tuning pseudo-timbre
    t/{1,2,3}/              the three timbres — §3.2
```

`/p/part/t/O` — capital letter O, not a digit — is a fourth, non-playing timbre slot
carrying master tune reference and offset. It is in the key list too. [READ]

## 3.2 A timbre: `/p/part/t/{1,2,3}` — 513 leaf shapes

```
en                                              timbre enabled

a/                    allocation & voicing
  hold hold-state max-stack max-voices mono note-pri note-steal rnd
  voice-limit-mode voice-steal
  chord/{en, ofs[]}                             ofs = JSON array of semitone offsets, or null
  unison/{en, max-stack, pitch-spread}  unison/knobs/detune

in/                   per-timbre input routing
  cv/{cv1,cv2,exp1,exp2,sus}/{dest,en,in-min,in-max,out-min,out-max}
  din0/{ch,en,note-enable}   usb0/{ch,en,note-enable}
  midi/{ch,en}                                  ≤ v10 only
  local/{en,on,note-min,note-max}
  midi_out/{ch,en}  midi_out/din0/{ch,en}  midi_out/usb0/{ch,en}

mix/                  output bus assignment
  main-en sub-en aux1 aux2 dir1 dir2 dir3 dir4

p/                    THE SOUND ENGINE
  o1/ o2/ o3/         14 each: fo oct pt po d tr m krst pbup pbdn scsrc sync1 sync2 sync3
                      + o{n}/knobs/po
  noise/              a ar r s mix mode                (its own AR envelope)
  mix/                en, ngate/gain,
                      o1|o2|o3/{g,fa,fb,plsbal}, n/{g,fa,fb}, rm/{g,fa,fb},
                      ext/{g,fa,fb,ext0,ext1}
                      — every source has a level plus a send to filter A and filter B
  fa/                 p r eg_p lfo_p p_fp par     fa/fm/{src,idx}
      fa/1/ fa/2/     bp hp lp p                  the two poles of the SVF
  fb/                 p r eg_p lfo_p p_fp hp tap  fb/fm/{src,idx}
  fbal fa_cm fb_cm fafb flink flink_offset        filter balance / routing
  e1/ e2/ e3/         16 each: a d s r h delay ak dk rk latch loop multi-trig rst sync
                      tscale velmod   + e{n}/knobs/{a,d,delay,h,r}
  l1/ l2/ l3/ l4/     22 each: f w r div fmul ph pol sm sync tim td tfin tfout rst rsts
                      one_shot pno var var_pulse var_saw var_sh var_tri
                      + l{n}/knobs/{f,r,td,tfin,tfout}
  m/                  e3_p l1_p l3_od l3_pd       four hardwired mod paths
  p1/d p2/d p3/d      three "pan/depth" destinations
  pt/                 en mode t gated gliss legato          (portamento / glide)
  g pan pan-spread po pbup pbdn ktc ringsrc3
  fm/{amt, route[]}                              route is a 2-element int array
  c/{0..127}                                     128 constant registers   (≤ v12)
  modmatrix/
      name comment
      entry/{0..19}/{src,src_a,ctl,ctl_a,tr,tr_a,dst,mute}     20 slots
      expressions                                RPN string   (≤ v12)
      matrix_expression_slots  seq_expression_slots            (v14)
      vars/{var0..var9, cvout1..cvout4}                        (v14)
  arp/p/             17 leaves + arp/knobs/r
  seq/               name, knobs/r
      seq/p/         16 leaves: on tempo div tim length one_shot sync key_transpose …
      seq/n/l/{0..29}/s/{0..63}/{g,n,r,t,v}      30 note lanes × 64 steps
      seq/m/l/{0}/{ctl,ctl_a,dst}, .../s/{0..63}/o    1 mod lane × 64 steps  (≤ v7)
      seq/r/{0..63}/en                                64 rest flags
  fx/                pan
      fx/ins/{en,mix,name,sync,type}, fx/ins/c/{control1_a,control2_a}
      fx/ins/p/{0..11}                           live insert-effect bank
      fx/knobs/{1,2}                             (v11+)
      fx/types/<19 effect names>/{0..11, ctl1_a, ctl2_a}
  sus/{mode, src}
```

Index domains, all read off the corpus [TESTED]:
mod-matrix **20** entries · sequencer **30** note lanes × **64** steps · **64** rest flags ·
constant registers **128** · effect banks **12** parameters · filter A **2** poles ·
bus effects **2** slots · CV outputs **4** · left-hand-controller banks **3**.

---

# 4. The `_m` twins

**They are not in the preset format at all, and they are not `/p` in the sense this
document uses.** They belong to a *different tree* in a *different process*.

Evidence:

* **Zero** addresses ending in `_m` occur in any of the 1,329 preset payloads, and none in
  `captures/p-namespace-keys.txt` [TESTED].
* They live in `captures/sysmap/addrs-p.txt`, which is a **flat** `/p/<module>/<leaf>`
  namespace: `/p/e1/a`, `/p/e1/am_m`, `/p/o1/fo`, `/p/o1/fo_m`, `/p/fa/1/p_m`,
  `/p/mix/rm/g_m`, `/p/pan_m`, `/p/g_m`. There is **no `/p/part/t/{n}` prefix** — no timbre
  index, because this tree *is* one timbre. [READ]
* `docs/arch/capability-survey.md` §0 attributes that tree to `las-sc` talking to the
  voice controller at `203.0.113.2:7770`. The naming lines up one-for-one with the `sto`
  destination tokens of the modulation RPN language (`o1fo`, `fapn`, `fbr`, `vca`, `pno`).

So the layering is [INFERRED, well supported]:

```
.m1p / librarian          →  las-frontend's las::Root       →  las-sc  →  voice controller
/p/part/t/2/p/o1/fo          per-timbre, 764 shapes             flat /p/o1/fo
(no _m addresses)            (no _m addresses)                  + /p/o1/fo_m  ← modulation depth
```

`<leaf>` is the parameter's base value; `<leaf>_m` is the **modulation amount summed into
that parameter** at control rate. The host never stores `_m`; it stores mod-matrix entries
and, from v14, the compiled 7-token slot array, and something between `las-frontend` and
the voice controller turns those into `_m` writes.

**Correction to a number.** The brief and `docs/arch/capability-survey.md` both say
**106** `_m` addresses. `captures/sysmap/addrs-p.txt` contains **92**, and 92 is also the
count of `_m` anywhere in the file, not just at end of line [TESTED]. Either the 106 was
computed over a different capture or it double-counted. The 92 are:

```
e{1,2,3}/{am_m,dm_m,rm_m,hm_m,delaym_m}            15
f/{p_m,r_m,eg_p_m,lfo_p_m}                          4
fa/{eg_p_m,lfo_p_m,fm/idx_m}, fa/{1,2}/{p_m,r_m,eg_p_m,lfo_p_m,fm_m}   13
fb/{eg_p_m,fm_m,lfo_p_m}                            3
l{1,2,3,4}/{ph_m,ta_m,td_m,var_m}                  16
m/{e3_p_m,l1_p_m,l3_od_m,l3_pd_m}                   4
mix/{ext/g_m,n/g_m,rm/g_m,o{1,2,3}/{g_m,plsbal_m}} 10
noise/{am_m,dm_m,rm_m,s_m}                          4
o{1,2,3}/{ang_m,fm1_m,fm2_m,fm3_m,fo_m,po_m,tr_m}  21
fm_m, g_m, pan_m                                    3
                                                   ---
                                                    92
```

Two things worth noting for a patch generator. First, the engine tree has an `ang`
(oscillator angle/phase) and an `fm1/fm2/fm3` triple that the **preset** tree does not —
the preset stores `/p/part/t/{t}/p/fm/{amt,route}` instead. Second, `/p/m/{e3_p, l1_p,
l3_od, l3_pd}` exists on both sides, with `_m` twins on the engine side; those four are the
panel's hardwired modulation paths and they are also the most-used mod-matrix destination
in the whole corpus (`…/p/m/l1_p`, dest id 52, 558 uses).

**What I did not verify:** that the `_m` values are additive rather than replacing, and
their scaling. That needs either the decrypted rootfs or a live read, and I did neither.

---

# 5. What this unlocks

## 5.1 Can a valid preset be generated from scratch, offline?

**Yes, with high confidence, for a full-dump preset.** Everything needed is now on disk:

1. **A guaranteed-valid skeleton exists**: the factory `INIT_m1p` resource carved from
   `las-frontend` (3,386 lines, `/p/version 6`). Any factory preset works equally well —
   there are 1,329 of them.
2. Every one of the 764 addresses is typed with observational evidence, with an empirical
   range and (for 747) a factory default.
3. The three float formatters are reconstructed exactly, so output is byte-reproducible.
4. The serialisation order rule reproduces all 222 corpus files exactly, so a
   round-trip test is available: **parse a factory preset, re-serialise, diff. It must be
   byte-identical.** That is the single best regression test for a generator and it costs
   nothing.

**Recommended approach:** load a factory preset of the target `/p/version`, mutate, and
re-emit — do not synthesise from nothing. The corpus is the safety net.

## 5.2 What is the minimum viable preset?

Two different questions, with two different answers.

**Minimum that is definitely accepted:** a full dump. Every real preset in every source is
one. Not risky, just verbose.

**Minimum that the loader appears to accept:** a fragment. The `PresetTests` fixtures
compiled into `las-frontend` are `.m1p` bodies of **five** and **eighteen** lines, with no
`/meta` block and no `/p/version` [READ, `las-frontend` offsets 132395635 and 132395949;
the test-suite name `PresetTests` is at 132392650]:

```
/p/part/t/1/en true
/p/part/t/1/p/e1/a 0.10
/p/part/t/1/p/fa/r 0.12
/p/part/t/1/p/l1/rsts "l1"
/p/part/t/2/en true
…
```

That, plus the fact that the parameter tree already holds defaults before a preset is
applied, makes it **[INFERRED]** that the loader applies whatever lines it finds and leaves
the rest alone — i.e. a fragment behaves as a delta against current state, not against
INIT. **This is inference from unit-test fixtures. It has not been demonstrated on an
instrument and it should not be relied on for a first experiment.**

The **9-line `/meta` block** is separately required for the *file* form, because export
reconstructs it from the librarian's columns and import presumably reverses that. A
fragment with no `/meta` may load over OSC and still be rejected by the USB-import path.
**unknown.**

If you must minimise, minimise conservatively: full dump, correct `/p/version`, correct
ordering, complete `/meta`.

## 5.3 Risk of loading a malformed preset — read this part carefully

I am going to be explicit about the boundary between what I know and what I do not,
because the honest answer is that **the risk is not characterised**.

**What is known:**

* The instrument's own release notes record **preset loading causing real failures**:
  v1.8.1 "fixed presets with oscillator hard sync not loading correctly"; v1.8.0 "OSC HARD
  SYNC via CC no longer causes panel lag and crashes" and "crashes on large MIDI input
  fixed" [OFFICIAL, per `docs/arch/hardware-external.md` §7]. **This unit runs v1.5.0 and
  has none of those fixes.** A hard-sync-related parameter combination is a documented
  crash on this exact firmware.
* Preset load writes to `las-frontend`'s parameter tree, which forwards to `las-sc`, which
  drives **analog** voice cards. Values leave the digital domain.
* The value parser rejects bad JSON with diagnostics rather than accepting garbage [READ].
* The tree rejects malformed paths (slashes, spaces, empty) by throwing
  `std::domain_error` [READ, `Fluent API Errors` test strings]. An exception thrown during
  preset load has an unknown handler.

**What is not known, and I did not test:**

* Whether an **unknown address** is ignored, logged, or fatal.
* Whether an **out-of-range float** is clamped, rejected, or passed to the voice cards.
  I could not extract the `min`/`max` table (§1.6), so I cannot even say what in-range is.
  The empirical ranges in the schema JSON are *observed*, not *permitted*.
* Whether a **type mismatch** (string where a float is expected) is caught.
* Whether a **missing `/p/version`**, or an unknown one (e.g. 13, 15), is handled.
* Whether a fragment leaves the engine in a **half-updated** state.
* Whether anything about a bad preset can reach **calibration** data. I have no evidence
  it can, and no evidence it cannot.

**Recommended posture.** Treat generated presets as untrusted input to a device with a
known crash history on this firmware. Specifically:

1. Only ever emit **values already observed in the corpus** for a given address, or values
   inside the observed range for that address. The schema JSON gives both.
2. Only emit **addresses that exist at the `/p/version` you declare** — the JSON's
   `preset_schema_versions` field says which.
3. Avoid `o{1,2,3}/sync{1,2,3}` entirely until someone has confirmed the v1.5.0 hard-sync
   crash conditions. That is the one combination with documented crash history.
4. Round-trip test offline first (§5.1) and diff against a factory preset before anything
   touches the instrument.
5. Prefer writing to a **librarian slot via the DB / USB import** over live OSC, so a bad
   patch can be deleted without the instrument having played it. Whether that is actually
   possible is **unknown** — I have not looked at the import path.

## 5.4 For programmatic patch generation specifically

The roadmap item is now unblocked on the *format* side. What a generator needs and now has:

* the exact byte format and ordering (§1.7) — byte-reproducible;
* 764 typed addresses with ranges, defaults and enums (`p-namespace.json`);
* the mod-matrix compiled encoding and its three id maps (§2.5) — so v14 modulation can be
  written directly rather than by string RPN;
* 1,329 real presets as style priors (§6) and as round-trip test cases.

What it still lacks: the declared `min`/`max`/`rest` per parameter (§1.6), the meaning of
`#raw` (§1.5), the five `FUNCTION` transform variants (§2.5), and any statement at all
about loader robustness (§5.3).

---

# 6. What 222 factory presets say about how Moog programs this instrument

Method: compare each preset's value at each address against the **factory `INIT_m1p`**,
numerically with a 1e-6 relative tolerance so the three float formatters don't create
false differences. "Touched" means "differs from INIT in at least one timbre" [TESTED].
Corpus: CLASSICS 51, TRANSFORMERS 53, STEREO FUTURES 45, KING 26, LISA BELLA DONNA 25,
POLYPHONIC DESTINATIONS 22.

## 6.1 The 42 addresses that are different in every single preset

```
o1/{d,fo,po,tr} + o1/knobs/po      o2/{d,fo}      o3/{d,fo,tr}
mix/{o1/g, o2/g, o2/plsbal, o3/g, rm/g}
noise/{a,r,mix}
e1/{a,d,r,s} + e1/knobs/{a,d,r}    e2/{a,r} + e2/knobs/{a,r}
l1/{f,var} + l1/knobs/f
fa/p   fb/{p,r}   fbal   fm/amt   m/e3_p   p3/d   pt/t
a/unison/{pitch-spread, knobs/detune}
```

Read that as the mandatory surface. Nobody ships a Moog One patch without setting all
three oscillators' shape and tune, the mixer levels, EG1 in full, EG2's attack and release,
LFO 1's rate and shape, both filter cutoffs, filter B resonance, the filter balance, the FM
amount, glide time and unison detune. **Ring-mod level (`mix/rm/g`) and noise
(`noise/{a,r,mix}`) are in that list** — they are always deliberately positioned, usually
at zero, not left alone.

Note what is *absent*: `fa/r` (filter A resonance) moves in only **181** of 222, and
`o2/tr` in 137, `o2/po` in 142, `o3/po` in 218. The asymmetry between the three
oscillators is real, and filter A's resonance is left alone far more often than filter B's.

## 6.2 The 258 addresses no factory preset ever moves

Whole subsystems are simply not part of the design vocabulary:

| subsystem | addresses | ever touched |
|---|---|---|
| `/p/part/tuning/*` (132 leaves, the full 128-note table) | 132 | **0** |
| `/p/part/mix/{ext-dir3, ext-dir4}` | 2 | **0** |
| `/p/part/cv_settings/*` | 26 | 10 |
| `/p/part/midi_io/*` | 17 | 12 |
| per-timbre `in/*` (CV, MIDI, local-keyboard routing) | 48 | 23 |
| per-timbre `fx/*` (insert effects incl. all 19 type banks) | 67 | 38 |

**The custom-tuning system has never been used by a factory preset**, in any of the six
packs, at any version. `/p/part/tuning/type` is `false`, `root` is `0`, `name_0` is
`"FROM PRESET"` and `data` is the same constant table, in **all 1,329 payloads** — not one
of them differs [TESTED]. If you are generating patches, the tuning block is 132 lines of
pure boilerplate: copy it verbatim and never think about it.

Also never touched: all four `cv_input` min/max pairs, `sustain/*` except in one preset,
`arp/p/global_swing`, `arp/p/note_hold_mode`, `arp/p/sequencer_coupling`, `fx/ins/mix`,
`a/max-stack`, `a/voice-steal`, `mix/{main-en,sub-en,dir4}`, the vocoder10/16/21 parameter
banks on the bus effects, and `modmatrix/vars/var0..9` (present only in v14 and left at
default in all 100 of them — the mod-matrix variable registers are a v14 feature that the
factory content does not use).

76 more addresses are touched in five presets or fewer — `l{n}/one_shot`, `l{n}/var_sh`,
`l{n}/var_saw`, `l4/tfout`, `e2/loop`, `o2/pt`, `seq/p/out_mode`,
`seq/p/transpose_mode_interval`. Each of those is a real feature that essentially nobody
uses.

## 6.3 What the six packs disagree about

Fraction of each pack's presets that move the parameter away from INIT:

| | CLASSICS | KING | LISA B.D. | POLY.DEST | STEREO FUT | TRANSF |
|---|---|---|---|---|---|---|
| mod-matrix entries | 100% | 96% | 96% | 82% | 100% | 98% |
| unison on | 69% | 73% | **92%** | **100%** | 93% | 94% |
| insert effect enabled | 69% | 88% | **96%** | 82% | 89% | 83% |
| bus effect 1 enabled | 67% | 85% | **96%** | 73% | **98%** | 92% |
| sequencer on | 27% | 46% | **64%** | 36% | 16% | 17% |
| arpeggiator on | 2% | 15% | 8% | 9% | 16% | 4% |
| **external audio in** (`mix/ext/g`) | **0%** | **88%** | 48% | 14% | 9% | 19% |
| **filter A parallel** (`fa/par`) | **69%** | **77%** | 52% | 27% | 33% | **19%** |
| LFO 3 rate | 41% | **96%** | 60% | 50% | 87% | 75% |
| EG 3 attack | 20% | **96%** | 44% | 14% | 31% | 38% |
| glide enabled | 25% | 27% | 28% | 5% | **56%** | 26% |
| chord mode | 4% | **23%** | 4% | 9% | 2% | 6% |
| CV output routed | 2% | 8% | **12%** | 0% | 2% | 2% |

Three things stand out.

**KING is the outlier on signal path.** 88% of its presets route external audio into the
voice — nothing else comes close, and CLASSICS is at literally zero. KING also uses LFO 3
and EG 3 in 96% of patches (versus 20–41% for CLASSICS) and chord mode four times as often
as anyone. It is the pack that treats the Moog One as a processor rather than a synth.

**Series-versus-parallel filtering is a generational marker, not a taste.** `fa/par` moves
from INIT in 69–77% of the two oldest packs (CLASSICS `/p/version 7–8`, KING `7–8`) and
only 19–33% of the newest (TRANSFORMERS and LISA BELLA DONNA at `v14`, STEREO FUTURES at
`10–12`). The default changed underneath the packs, so this row measures firmware era at
least as much as it measures style.

**Newer packs lean on unison and effects; older packs lean on the filter.** Unison goes
69% → 100% and both effect slots go ~67% → ~96% as you move from 2018-era CLASSICS to the
2020–2022 packs.

## 6.4 What only Lisa Bella Donna does

Eleven addresses are touched by the LISA BELLA DONNA pack and by no other pack. Five of
them are touched in **all 25** of her presets:

```
/p/part/t/{t}/p/modmatrix/vars/cvout1
/p/part/t/{t}/p/modmatrix/vars/cvout2
/p/part/t/{t}/p/modmatrix/vars/cvout3
/p/part/t/{t}/p/modmatrix/vars/cvout4
/p/part/cv_settings/cv_output/{i}/voice_rule
```

That is the entire **CV-output** subsystem — the four analog CV outs on the back panel,
driven from mod-matrix variables, with a per-output voice-assignment rule. Those five
addresses do not exist below `/p/version 14`; they arrived with the v1.5.0 firmware whose
release notes advertise "14 new CV output sources" and "25 Lisa Bella Donna presets". **The
pack exists partly to demonstrate the feature**, and it is the only factory content in
1,329 payloads that uses it.

The other six are one-offs: `cv_output/{i}/synth` and `cv_input/cvin_1/synth` (2 presets
each), `cv_input/sustain/type`, `mix/ext/fb` (external input into filter B),
`fx/types/ensemble/ctl1_a`, and `e2/loop` (the looping envelope — set in exactly **one** of
the 222, hers; across all 1,329 payloads it is `true` in only 12 timbre instances).

She is also the heaviest user of the sequencer (64% of presets versus 16–46% elsewhere) and
ties for the most consistent use of both effect slots (96%).

## 6.5 A crib for a patch generator

* Start from a factory preset of the target version, never from nothing.
* Always set the 42 addresses in §6.1. Leaving them at INIT reads as unfinished.
* Never touch `/p/part/tuning/*` (132 lines), `midi_io`, `cv_settings` (unless you are
  doing CV), or the `in/*` routing block. Copy them.
* Effect `types/*` banks: write the bank for the type you select and copy the other 18
  from the source preset. They are always all present.
* Mod matrix: 20 slots available; the **mode is 1 entry and the median is 2**. Over the
  666 timbre slots in the 222 presets: 30 have none, 263 have one, 68 two, 36 three,
  31 four, 24 five, 33 six, 50 seven, 34 eight, 36 nine, 28 ten, then a thin tail to a
  single timbre with 20. More than ten routings is rare even for Lisa Bella Donna.
* At `/p/version 14` you must write `matrix_expression_slots` **and** the entry strings
  consistently; the slots are what the engine reads and the strings are what the panel
  shows. Seven tokens per entry, in entry order (§2.5).

---

# 7. Conflicts with existing documentation

Reported, not fixed, per the brief's rule 4.

1. **`docs/arch/hardware-external.md:605`** says a finding was "verified directly against
   the repo's `INIT0.m1p`". **There is no `INIT0.m1p` in this repository**, and none in git
   history — `find . -iname '*init0*'` and
   `git log --all --diff-filter=A --name-only | grep -i m1p` are both empty. The quoted
   sample (`/p/version 14`, `/p/clk/rate 120.0`) is consistent with a generation-C v14 file
   from the mlazarev GitHub repo, not with anything on this disk. The claim is unsourced as
   written. A real factory INIT **is** now available — carved from `las-frontend`, §2.3.
2. **`docs/arch/hardware-external.md`** describes `las-frontend` as "Qt UI + MIDI + panel".
   It is **JUCE**: 866 `N4juce…` symbols, **zero** Qt symbols [TESTED].
3. **`docs/arch/capability-survey.md:27,176`** and the brief say **106** `_m` addresses.
   `captures/sysmap/addrs-p.txt` has **92** [TESTED]. See §4.
4. **`docs/arch/capability-survey.md`** says the mod-matrix constant register file is
   "64 constants" and flags `c64` as contradicting it. The preset tree has
   `/p/part/t/{t}/p/c/0…127` — **128 registers** [TESTED]. §1.10.
5. **`docs/arch/capability-survey.md`** gives "dest ids 0–141, 141 = none". **Both 137 and
   141** occur with an empty destination in unmuted entries [TESTED]. §2.5.
6. **`docs/arch/capability-survey.md`** gives "transform ids … 43 = none" and "36
   transforms, factory uses six". I see **12 named transforms in the `tr` string enum**
   and **15 non-none transform ids** in the compiled slots, resolving to 11 distinct names
   because `FUNCTION` spans five ids (14, 23, 25, 28, 30). Neither "36" nor "factory uses
   six" matches the corpus. §2.5.
7. **`docs/arch/control-plane.md:91-92`** lists LFO leaves `sym`, `fidx`, `nrst`, `phr`,
   `sh_noise`, `ta`, and envelope leaves `key-follow`, `trig`, and "`/p/e4`" (a fourth
   envelope). **None of those exist in the preset tree**, which has three envelopes and the
   LFO leaves listed in §3.2. Those names belong to the *engine* tree
   (`captures/sysmap/addrs-p.txt`), not to `/p/part/t/{t}/p`. The two namespaces are mixed
   together in that table.

---

# 8. How to reproduce

Everything here comes from six analysis programs run over files already on disk. They are
in the session scratchpad; each is small enough to re-derive from this description.

1. **Byte survey** — encoding, line endings, BOM, size/line distribution over the 222.
2. **Lexer** — `^(/\S*) (.*)$` per line; duplicate and ordering checks.
3. **Order model** — build the tree, walk leaves-then-children with bytewise sort plus the
   two integer-ordered array nodes; compare to file order. Result: 222/222.
4. **Float-formatter model** — implement A/B/C, test every non-integer numeric token.
   Result: 451,222/451,222 explained.
5. **Carver** — `re.finditer(rb'/meta/name "', las_frontend)`, then walk forward while each
   line matches `^/[!-~]* [^\n]*$`. Yields 580 presets plus the INIT resource at 143838219.
6. **Schema builder** — normalise digit path segments to `{i0}/{i1}/{i2}` (and the timbre
   index to `{t}`), accumulate type evidence, ranges, enums, index domains, version
   presence, and INIT defaults; emit `docs/arch/p-namespace.json`.

The single cheapest regression test for anyone building on this: **parse a factory `.m1p`,
re-serialise with the §1.7 order rule and the §1.3 formatter for its `/p/version`, and
diff. It must be byte-identical.** That exercises the ordering rule, the float formatters,
the escaping and the meta block all at once, against 1,329 real files.

## Files produced

| path | what |
|---|---|
| `docs/arch/preset-format.md` | this document |
| `docs/arch/p-namespace.json` | 764 typed addresses + the mod-matrix id maps, 611 KB |
