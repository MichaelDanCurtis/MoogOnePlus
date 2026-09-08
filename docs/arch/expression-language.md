# The Moog One modulation expression language

**Scope.** Complete specification of the language behind
`/p/part/t/<N>/p/modmatrix/*` — grammar, the three symbol tables, the constant
register file, the numeric (post-1.3.0) encoding, worked examples, the unused
vocabulary, and safety limits. Written to be sufficient to build a correct
expression compiler with no instrument present.

**Evidence grading.** Every claim is marked `[TESTED]` (observed on hardware),
`[READ]` (read out of a binary, a shipped file, or Moog's own release notes —
file and offset given), or `[INFERRED]` (reasoning from the above). Nothing here
is `[TESTED]`: this pass touched no instrument. Anything not established is
written "unknown".

**Corpus used** (all local, read-only):

| source | content |
|---|---|
| `captures/firmware-1.8.2/corpus/**/*.m1p` | 222 factory presets, 6 packs, `/p/version` 7–14 |
| `captures/MOOG ONE.db` (`presets`) | 398 presets, `/p/version` 6 |
| `captures/SINGULARITY VOL 1 - GEOSYNTHS.db` | 129 presets + 3 standalone `mod_matrix_presets` (§3.1) |
| `captures/arch-harvest/las-sc` | control brain, CHICKEN Scheme → ARM |
| `captures/arch-harvest/las-frontend` | Qt UI, ELF32 ARM, `.rodata` 133 MB |
| `captures/backup/rootfs-p3-las-v1.5.0-*.img.gz` | the running v1.5.0 rootfs |
| `Moog_One_v1.8.2.zip` → `Past Firmware Update Release Notes/*.pdf` | Moog's own docs, v1.0.1–v1.8.2 |

Union: **752 presets / 2256 timbres / 1851 expression strings (1696 non-empty).**

---

## 0. Headline: the blocker is gone, and three recorded facts were wrong

**`/usr/share/vx_ee.scm` has been recovered.** `docs/ROADMAP.md` §1 says the work
is "Blocked on one file … the symbol table, and it is not in the capture set."
It *is* in the capture set — inside the v1.5.0 rootfs image. It sits at byte
offset **637,856,768** of the decompressed
`captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz`, 13,134 bytes, in two
extents (12,288 bytes, then the remainder three bytes later at 637,869,059;
1 KiB blocks). Header: `#| LAS VX Expression Engine variables list … (c)2018
Moog Music Inc. |#`, then `(VX_EE (symbols (args …) (parms …) (vars …)
(results …)))`. [READ]

> The file is Moog-copyright source shipped on the device.
> `docs/INTERNAL-DO-NOT-DISTRIBUTE.md` §3 says never reproduce it. This document
> therefore gives the *derived tables* (symbol names, array sizes, orderings —
> functional facts needed to write a compiler) and not the file's prose. Re-extract
> it from the offset above if you need the original.

Every one of the **76 destination tokens** and **19 source tokens** that appear
across the 1696 non-empty factory expressions is a symbol from that file — `results` and `args`
respectively, with zero misses. The symbol table and the language are the same
thing. [READ]

Three recorded claims are now falsified:

| recorded | actual |
|---|---|
| "64 constant registers" (`docs/arch/capability-survey.md` A1; `docs/ROADMAP.md` §1) | **128.** `(c (array 128))` in `vx_ee.scm`, and every pre-1.3.0 preset writes `/p/part/t/<N>/p/c/0` … `/c/127` — 128 leaves, no gaps, in all 617 such presets. [READ] |
| "36 shaping transforms … factory content uses six" (`docs/ROADMAP.md` §1, `capability-survey.md` A1) | **11 named transforms + FUNCTION, and FUNCTION selects one of 31 functions** = 42 distinct behaviours, plus "none". The "36" came from reading one contiguous `.rodata` string block as a single flat list; it merges the two menus, misses `S+C`, `S/C` and `C(V+S)` (whose literal is shared with the tail of `V+C(V+S)`), and counts `FUNCTION` itself as a transform. The 1.8.2 factory corpus uses **12 of the 12 selectors** (`LIMIT LOW`, `LIMIT HIGH`, `SQUARED`, `CUBED`, `LOPASS`, `HIPASS`, `SLEW`, `SLEW UP`, `SLEW DOWN`, `S&H`, `BOUNCE`, `FUNCTION`) and **5 of the 31 functions**. [READ] |
| "3724 of 3850 entries say `t/1` regardless of which timbre owns them, so cross-timbre routing already persists" (`docs/ROADMAP.md` §1) | **No cross-timbre routing exists in any factory preset.** Of 7476 `entry/*/dst` strings in the union corpus, 7304 say `t/1`, 166 are blank or `/dummy`, 6 say the *owning* timbre, and **zero** name a foreign timbre. The timbre index in `dst` is a template artefact of a fixed prefix; in the post-1.3.0 numeric encoding the destination is a bare integer with no timbre field at all. Cross-timbre routing is *unattested*, not "already persisting". [READ] |

And one claim needs re-reading rather than correcting: `rcl` is not scratch-memory
recall (`capability-survey.md` A3). It is the compiled form of the **sequencer
modulation lane** — see §10.2.

---

## 1. Two representations, one language

The mod matrix has had two on-disk encodings. The split is exact and falls on
`/p/version`:

| `/p/version` | encoding | presets in union | transform vocabulary actually usable |
|---|---|---|---|
| 6 – 12 | `modmatrix/expressions` — an RPN **text** program, plus `p/c/0…127` holding the amounts | 617 (+3 undated `mod_matrix_presets`) | `LIMIT LOW`, `LIMIT HIGH`, `SQUARED`, `CUBED` only |
| 14 | `modmatrix/matrix_expression_slots` — a flat **numeric** array, 7 values per row; no `p/c/*` at all | 132 | all 12 selectors + 31 functions |

No preset carries both; no preset carries neither. [READ, 752/752]

**Why the change.** Firmware **v1.3.0** (2020-03-19) says in its own release
notes: *"The 'expression engine' which runs the Modulation Matrix has been
completely rewritten. In previous versions, it was possible for presets with
large numbers of modulation expressions to load inconsistently or have some
modulations evaluate incorrectly."* [READ,
`Moog One Firmware Update v1.3.0.pdf`] The same release added the LOPASS,
HIPASS, SLEW, SLEW UP, SLEW DOWN, S&H, BOUNCE and FUNCTION transforms, the
`VAR 1…10` variables, `ON/OFF GATE`, `TRIGGER GATE` and `RANDOM KEYED 1-3`.

The corpus explains *why* the rewrite was needed: the four transforms the RPN
text form can express (`max`, `min`, `**`, `***`) are all **stateless**. Slew,
sample-and-hold, one-pole filters, bounce and the track/sample functions all need
per-slot state that survives between evaluation cycles. A flat postfix stream
with a shared value stack has nowhere to put that. The numeric slot array gives
every row a fixed identity — its index — and therefore a place for its state.
[INFERRED, but the version/vocabulary split is exact: no `/p/version` ≤ 12 preset
in 617 ever uses a stateful transform, and 69 of 396 v14 timbres do.]

**The expression engine itself did not go away.** `las-sc` still boots with
`--expr-syms=/usr/share/vx_ee.scm` on the running v1.5.0 unit
(`captures/arch-harvest/init.d/S42sc` and `runtime-state.txt`, identical command
lines) [READ], still carries the `expression-nodes` global (`las-sc` 0x1e779f)
and still exposes `/p/part/t/<N>/p/pre-expr` and `/p/part/t/<N>/p/post-expr` in
its OSC tree [READ, `las-sc` literal table ≈ +0x1e38xx]. What changed is that the
mod matrix no longer *compiles to text*. The live v1.5.0 `/p` namespace
(`captures/p-namespace-keys.txt`, 3197 leaves) contains
`modmatrix/matrix_expression_slots` and `modmatrix/seq_expression_slots` and
contains **neither** `modmatrix/expressions` **nor** any `/p/part/t/<N>/p/c/<i>`.
[READ]

So: to *drive* the instrument today you write slots. To *read* the 620 older
presets — and to understand what the machine is — you need the grammar.

---

## 2. The RPN grammar

### 2.1 Lexical

One flat ASCII string. Tokens are separated by runs of ASCII space. No comments,
no parentheses, no nesting, no string literals. Numeric literals appear as bare
decimals — the compiler emits `1`, `1.0` and
`1.00000000000000000000` interchangeably in different firmware revisions.

```
token   := verb | source | destination | constant | literal
verb    := "*" | "+" | "-" | "min" | "max" | "**" | "***" | "rcl" | "sto"
source  := <a symbol from the vx_ee `args` list>          e.g. mw padx l4 e3 gate rnd
dest    := <a symbol from the vx_ee `results` list>       e.g. fbpn l1po pan vca
constant:= "c" <0..127>
literal := [-]?[0-9]+ ("." [0-9]*)?
```

`source` and `dest` are disjoint namespaces (`args` vs `results`), so a token's
role is unambiguous from the symbol table alone; a parser does not need position
to disambiguate. [READ, verified over all 1696 non-empty expressions: 0 tokens outside
`args ∪ results ∪ verbs ∪ cN ∪ literal`]

### 2.2 Statements

A statement runs to and includes the next `sto`. There is no other terminator and
no separator. Splitting on `sto` is the whole of statement delimitation. [READ]

Across the 1696 non-empty expressions, every string ends on a `sto` — there is
never a trailing partial statement, even in the two whose *contents* are
malformed (§2.5). [READ, 1696/1696]

**Exactly one statement per destination.** No expression in the union corpus ever
names the same destination token in two statements (0/1696), and the statement
count equals the number of distinct live destinations among the panel rows
(1695/1696; the one outlier is a preset with an orphaned sequencer statement).
[READ] Consequently it is *not* observable from the corpus whether `sto` assigns
or accumulates — the compiler always pre-sums. Treat this as **unknown**; if you
emit two `sto` to one destination you are outside attested behaviour.

**Statement order is not row order and is not significant in this form.**
Destinations are `results` and sources are `args`, and the two sets are disjoint,
so no statement can read what another wrote. (In the post-1.3.0 slot form this
stops being true — `VAR 1…10` are both — and Moog specifies the order there; see
§10.1.)

### 2.3 Verbs, arity, stack discipline

The machine is a value stack. Operands push, verbs pop.

| verb | arity | effect | panel meaning | uses |
|---|---|---|---|---|
| `*` | 2 | `push(a*b)` | — | 7004 |
| `+` | 2 | `push(a+b)` | merge of two matrix rows on one destination | 1046 |
| `-` | 2 | `push(a-b)` | — | 371 |
| `min` | 2 | `push(min(a,b))` | transform **LIMIT HIGH**, arg = the limit | 49 |
| `max` | 2 | `push(max(a,b))` | transform **LIMIT LOW**, arg = the limit | 13 |
| `**` | 1 | `push(a*a)` | transform **SQUARED** | 10 |
| `***` | 1 | `push(a*a*a)` | transform **CUBED** | 11 |
| `rcl` | 1 | read a register at run time (§10.2) | sequencer modulation lane | 32 |
| `sto` | 2 | pop destination symbol, pop value, write | end of one matrix row-group | 5240 |

Counts are over the 1696 non-empty expressions of the union corpus. [READ]

`**` and `***` are **unary postfix**, not exponentiation:
`v ** c8 *` is `(velocity²)·c8`. Both were confirmed against their panel rows —
every `**` statement's row carries `tr "SQUARED"`, every `***` statement's row
carries `tr "CUBED"` (10 and 11 instances respectively, no exceptions). [READ]

`min`/`max` are binary and take the transform argument as their second operand:
`a c6 min` is `min(aftertouch, c6)`. Confirmed against `tr "LIMIT HIGH"` /
`tr "LIMIT LOW"` rows, with `c6` = that row's `tr_a`. [READ]

`-` is only ever emitted in one idiom: **371 of 371** occurrences are the
three-token sequence `1 c<n> -`, i.e. `1 − ctl_a`. Subtraction exists; the
compiler has exactly one use for it. [READ]

**Stack discipline.** At every `sto` the stack holds exactly `[value,
destination]`; between statements it is empty. A stack simulator built from the
table above accepts **1694 of the 1696** non-empty expressions with no underflow,
no leftovers and no unknown tokens. There is no observed instance of a value
surviving across a `sto`, no `dup`, no `swap`, no `drop`. [READ] The two
exceptions are not a flaw in the model — see §2.5.

The destination symbol is *not* on the value stack in this model: `sto` takes it
from the token immediately preceding it, and in all 5238 well-formed statements
that token is a `results` symbol. Whether the real machine pushes it or peeks it
is unobservable and does not matter for a compiler.

### 2.5 Two malformed programs exist in the wild

`MOOG ONE.db` presets 45 (`BOWED ELECTRICITY`) and 283 (`SOUND WHIP`), both
`/p/version` 6, timbre 1, contain this statement:

```
padz padz * c28 * padz 1.0 c28 - * + c29 * a * c34 *  + c35 1 * + l4f sto
```

Trace it: after `c34 *` the stack holds one value; the following `+` has nothing
to add to it. Then `c35 1 *` pushes one value and the second `+` underflows
again; `sto` is reached with an empty value stack. Note also the **double space**
before the first stray `+` — the compiler emitted an empty token there, which is
what a term that failed to compile looks like.

This is the only structural defect in 1696 expressions, and it is exactly the bug
class Moog acknowledged in v1.3.0: *"some modulations evaluate incorrectly"*
(§1). It matters for two reasons:

* A parser for this language **must not assume well-formedness.** Real presets
  violate it.
* These presets are in the instrument's own database. Whatever the voice
  controller does with a stack underflow, it evidently does not brick anything —
  which is the only evidence in this entire document about the malformed-input
  failure mode, and it is weak evidence (see §13.2).

### 2.4 `rnd` and `rndb`: per-note or per-block?

They are **sources, not verbs.** `rnd` and `rndb` are entries in the `vx_ee`
`args` list, alongside `mw`, `gate` and `l4`. In every compiled statement they
occupy the *controller* position or the *source* position of an ordinary matrix
row, and the corresponding panel row names them:

* `gate rnd * c13 * gate 1 c13 - * + c14 * e2dlm sto` — panel row: `src "KB GATE"`, `ctl "RANDOM"`, `dst /p/e2/delay`. [READ, BLOOM t1]
* `rndb c8 * pno sto` — panel row: `src "RANDOM BIPOLAR"`, `dst /p/po`. [READ, CIVIC MAESTRO t1]
* `l4 rndb * c7 * l4 1 c7 - * + c8 * fbal sto` — panel row: `src "LFO 4"`, `ctl "RANDOM BIPOLAR"`. [READ, CASUAL BUNGALOW t1]

`vx_ee.scm` documents `rnd` as a random source in 0..1 and `rndb` as a random
source in −1..1. [READ] Neither is described as keyed. **They are free-running,
not per-note** — this is what makes the v1.3.0 addition of `RANDOM KEYED 1-3`
("A new random value is generated on each new key press, and held constant until
the next key press") a new feature rather than a rename. [READ, v1.3.0 release
notes] Whether "free-running" means per-sample, per-control-block or per
evaluation cycle of the expression engine is **unknown** — it is not readable
from the corpus, and the evaluator is compiled code inside the obfuscated XMOS
image.

Note the naming drift: pre-1.3.0 presets write `src "RANDOM"` / `"RANDOM
BIPOLAR"`; the 1.8.x source enum keeps `RANDOM` (26) and `RANDOM BIPOLAR` (27)
and adds `RANDOM KEYED 1-3` (28–30).

---

## 3. How a panel row compiles

This is the whole of what the panel can say, and the corpus contains nothing
else. A matrix row *i* has seven fields: `src`, `src_a`, `ctl`, `ctl_a`, `tr`,
`tr_a`, `dst`, plus `mute`.

**The canonical compiled form** (row *i*, source `S`, controller `C`, transform
`T`, destination `D`):

```
S <T> C * c(3i+1) * S 1 c(3i+1) - * + c(3i+2) * D sto
└─ T(S)·C·ctl_a ─┘  └─ S·(1−ctl_a) ─┘        └ ×src_a ┘
```

i.e.

```
D  :=  src_a · ( ctl_a · T(S)·C  +  (1 − ctl_a) · S )
```

with three constant registers per row:

| register | field | meaning |
|---|---|---|
| `c[3i]` | `tr_a` | transform argument (the limit for `min`/`max`) |
| `c[3i+1]` | `ctl_a` | CONTROLLER AMOUNT — crossfades the controller *and the transform* in |
| `c[3i+2]` | `src_a` | SOURCE AMOUNT — final depth |

Verified against each preset's own `p/c/*` block, over the 222-preset 1.8.2
corpus: `c[3i]` equals `tr_a` in 1552/1606 rows, `c[3i+2]` equals `src_a` in
1488/1606, and `c[3i+1]` equals `ctl_a` in **531/533 rows that actually have a
controller** (the remainder are
rows with no controller, where the compiler leaves the register at 0 or stale —
it is not referenced). [READ]

**The compiler folds aggressively.** Only the terms it needs are emitted:

| row shape | emitted |
|---|---|
| source only (`ctl` empty, `tr` empty) | `S c(3i+2) * D sto` |
| source + transform, no controller | `S <T> c(3i+2) * D sto` |
| source + controller, no transform | `S C * c(3i+1) * S 1 c(3i+1) - * + c(3i+2) * D sto` |
| `ctl_a` = 0 | the `(1−ctl_a)` factor is dropped: `… S + c(3i+2) *` |
| `src` empty, `ctl` set | the controller becomes the source: `C c(3i+1) * D sto` |
| two rows, same `dst` | one statement, the two sub-expressions joined by `+` |
| `mute true` | **nothing at all** — the row vanishes from the program |

All seven shapes are attested. [READ]

Two consequences worth knowing:

1. **`ctl_a` gates the transform too.** In the RPN form the transform is applied
   only inside the controller branch. At `ctl_a = 0` a row with `tr "LIMIT HIGH"`
   compiles to plain `S · src_a` — the limit does nothing. This is a property of
   the pre-1.3.0 compiler, not of the panel's stated semantics. Moog's v1.3.0
   notes describe the newer engine as *"All other transforms use SOURCE *
   CONTROLLER as their input signal"* [READ], which is the `ctl_a = 1` case.
   Whether the ≥1.3.0 engine keeps the crossfade is **unknown**.
2. **Muting is destructive to the program.** A muted row leaves its `entry/*`
   fields and its constant registers in the preset but contributes no statement.
   In the numeric form muting is handled differently — the slot survives with
   `src = 48` (none) and `dst` set to the "unassigned" sentinel (§5).

### 3.1 The panel rows are authoritative; the program is derived

Both SQLite databases carry a separate `mod_matrix_presets` table — standalone,
reusable mod-matrix snapshots detached from any timbre. Their key namespace is
root-relative (`/modmatrix/entry/<i>/*`, `/modmatrix/expressions`,
`/modmatrix/name`, `/modmatrix/comment`) and, decisively, **they carry no
`p/c/*` block at all**:

```
/modmatrix/entry/0/ctl "MOD WHEEL"   ctl_a 0.00999999   dst "/p/part/t/1/p/m/l1_p"
/modmatrix/entry/1/src "LFO 4"       src_a 0.07175384   dst "/p/part/t/1/p/l1/f"
/modmatrix/expressions "mw c1 * l1po sto  l4 c5 * l1f sto"
```
[READ, `SINGULARITY VOL 1 - GEOSYNTHS.db` `mod_matrix_presets` id 3, "LFO RATE GEO"]

The program references `c1` and `c5` and nothing in the object supplies their
values. They can only come from the `entry` rows on apply. So the direction is
settled: **`entry/*` is the source of truth, and both the RPN text and the
constant register file are compiler output.** A tool that wants to change a
modulation must write the `entry` fields (and, for pre-1.3.0 targets, regenerate
both the expression string and the `c` block consistently) — writing only the
expression string leaves the panel showing something else.

There are three such objects in the corpus, all in the Singularity pack, all
using the root-relative form; none appears in `MOOG ONE.db`.

---

## 4. Formal grammar

```ebnf
program     = { statement } ;
statement   = expr , dest , "sto" ;
expr        = term { term } ;          (* postfix; well-formedness is a stack
                                          property, not a syntactic one *)
term        = operand | verb1 | verb2 ;
operand     = source | constant | literal ;
verb1       = "**" | "***" | "rcl" ;
verb2       = "*" | "+" | "-" | "min" | "max" ;
source      = ? symbol in vx_ee `args` ? ;
dest        = ? symbol in vx_ee `results` ? ;
constant    = "c" , digit , [ digit ] , [ digit ] ;   (* 0..127 *)
literal     = [ "-" ] , digit , { digit } , [ "." , { digit } ] ;
```

Well-formedness condition: evaluating `expr` from an empty stack must leave
exactly one value; `dest` then contributes the destination and `sto` consumes
both. A validator should reject anything else *before* it reaches the voice
controller (§13.3).

---

## 5. The numeric form (`/p/version` 14, firmware ≥ 1.3.0)

`/p/part/t/<N>/p/modmatrix/matrix_expression_slots` is a flat JSON-ish array whose
length is always a multiple of 7, and whose 7-tuple count is always **exactly**
the number of `entry/<i>/*` rows in the same timbre. [READ, 300/300 timbres in
the 1.8.2 corpus]

```
[ src_id, src_a, ctl_id, ctl_a, tr_id, tr_a, dst_id,   ← row 0
  src_id, src_a, ctl_id, ctl_a, tr_id, tr_a, dst_id,   ← row 1
  … ]
```

* ints at positions 0, 2, 4, 6; floats at 1, 3, 5.
* **Tuple *k* corresponds to `entry/k`**, in order (not reversed): under forward
  alignment 987/987 `src_a` values and 987/987 `ctl_a` values match the panel row
  exactly, and the id→name maps are single-valued; under reverse alignment they
  are not. [READ]
* `dst_id` carries **no timbre field**. The `entry/*/dst` string that accompanies
  it is a human-readable echo whose `t/1` prefix is fixed boilerplate.
* Mute is compiled away: **25/25** muted rows carry `src_id = 48` (none) and a
  "no destination" `dst_id`. The row keeps its size in the array so that indices
  — and therefore per-slot state — stay stable.

`seq_expression_slots` is the identical encoding for the sequencer's modulation
lanes. It is `[]` in 299 of 300 factory timbres and `null` in one — **no factory
preset uses a sequencer modulation lane in the 1.8.2 pack.** The frontend symbol
`las::ModMatrix::Pimpl::updateSequencerParams(las::ModulationLane*)` is present in
`las-frontend` at +0x7e41ec8. [READ]

### 5.1 Transform argument scaling (panel value → slot value)

The panel writes `tr_a` in user units into `entry/<i>/tr_a` and the *engine* units
into the slot. Measured over rows whose `src_id` still agrees with `src`
(i.e. non-stale rows):

| transform | slot value | samples | fit |
|---|---|---|---|
| `SLEW`, `SLEW UP`, `SLEW DOWN` | `10 · x³` seconds | 30 distinct | exact, no exceptions |
| `S&H` | `100 · x` Hz | 3 | exact |
| `BOUNCE` | `x` (gravity, observed 0…5) | 9 | identity |
| `LIMIT HIGH` / `LIMIT LOW` | `x` | 1 + (RPN corpus) | identity |
| `LOPASS`, `HIPASS` | **unresolved** — 4 rows identity, 3 rows `10·x³` | 13 | see below |
| `FUNCTION` | slot `tr_a` is always `0.0`; the function number lives in the **panel** `tr_a` and in `tr_id` | 14 | exact |

`10·x³` for slew matches Moog's *"Parameter is Slew Time; higher values make
modulation changes take longer"* with a 0…10 s range and a cubic taper.
`100·x` for S&H matches *"The parameter is sample rate in Hz"*. [READ, v1.3.0
notes] The LOPASS/HIPASS split is real and not explained: e.g. `0.49 → 1.17649`
(= 10x³) and `0.72 → 0.72` (identity) both occur, both from two-decimal panel
values. Most likely a scaling change between two 1.3.x–1.8.x builds, with the
`entry` echo written by one build and the slot by another. **Do not rely on
either mapping for LOPASS/HIPASS.**

---

## 6. Symbol table 1 — sources and controllers

`src` and `ctl` share one id space. **22 ids are directly attested** by
slot↔name co-occurrence in the 1.8.2 corpus; the rest of the table is
reconstructed from the `vx_ee` `args` ordering, which fits all 22 anchors with no
slack.

The reconstruction works like this. Take the v1.5.0 `args` list, drop the 16-wide
`m` array, and apply the three insertions that v1.3.0's release notes announce
(`ON/OFF GATE` + `TRIGGER GATE` after `gate`; `RANDOM KEYED 1-3` after `rndb`)
plus `VEL RELEASE` after `v`. Every observed id then lands on its own symbol —
`gate`=0, `v`=3, `mw`=6, `pw`=7, `padx`=8, `pady`=9, `a`=10, `padz`=11,
`l1..l4`=18–21, `e1..e3,en`=22–25, RK1–3=28–30, `pnt`=33, `CONSTANT`=36,
`VAR 1`=37. That is 22 independent coincidences; the fit is not accidental.

| id | panel name | `vx_ee` arg | evidence |
|---|---|---|---|
| 0 | `KB GATE` | `gate` | [READ] 57 slots |
| 1 | `ON/OFF GATE` | — (added 1.3.0) | [INFERRED] |
| 2 | `TRIGGER GATE` | — (added 1.3.0) | [INFERRED] |
| 3 | `VELOCITY` | `v` | [READ] 31 |
| 4 | `VEL RELEASE` | — | [READ] 7 |
| 5 | *unknown* (likely `p`, base pitch) | `p` | [INFERRED] |
| 6 | `MOD WHEEL` | `mw` | [READ] 106 + 212 as ctl |
| 7 | `PITCH WHEEL` | `pw` | [READ] 1 |
| 8 | `PAD X` | `padx` | [READ] 73 |
| 9 | `PAD Y` | `pady` | [READ] 59 |
| 10 | `AFTERTOUCH` | `a` | [READ] 88 |
| 11 | `PAD PRESSURE` | `padz` | [READ] 1 (as ctl) |
| 12 | `PAD GATE` | `padg` | [INFERRED] |
| 13 | `CV IN 1` | `cvin1` | [INFERRED] |
| 14 | `CV IN 2` | `cvin2` | [INFERRED] |
| 15 | `EXP 1` or `EXP 2` | `expr2` | [INFERRED], order unknown |
| 16 | `EXP 2` or `EXP 1` | `expr1` | [INFERRED], order unknown |
| 17 | `SUSTAIN` | `sus` | [INFERRED] |
| 18–21 | `LFO 1` … `LFO 4` | `l1`–`l4` | [READ] 9/27/47/93 |
| 22 | `FILTER EG` | `e1` | [READ] 3 |
| 23 | `AMPLIFIER EG` | `e2` | [READ] 46 |
| 24 | `MODULATION EG` | `e3` | [READ] 12 |
| 25 | `NOISE EG` | `en` | [READ] 1 |
| 26 | `RANDOM` | `rnd` | [INFERRED] |
| 27 | `RANDOM BIPOLAR` | `rndb` | [INFERRED] |
| 28–30 | `RANDOM KEYED 1..3` | — (added 1.3.0) | [READ] 4/2/1 |
| 31 | *unknown* (likely `pp`, processed pitch) | `pp` | [INFERRED] |
| 32 | *unknown* (likely `ktc`, key-track centre) | `ktc` | [INFERRED] |
| 33 | `KEY PITCH` | `pnt` | [READ] 34 |
| 34 | *unknown* (likely `pto`, key track in octaves) | `pto` | [INFERRED] |
| 35 | *unknown* (likely `vspr`, voice spread) | `vspr` | [INFERRED] |
| 36 | `CONSTANT` | — | [READ] 11 (as ctl) |
| 37–46 | `VAR 1` … `VAR 10` | — (added 1.3.0) | [READ] `VAR 1` = 37 |
| 47 | *unknown / spare* | | |
| **48** | **none** (`"-"` or `""`) | | [READ] 250 + 599 |

The panel strings themselves are in `las-frontend` `.rodata` at
0x7e421a5–0x7e422b4, and the frontend's source-menu pointer array is in `.data`
at 0x8a57ee4–0x8a57f88 (`LFO 1`, `LFO 2`, `LFO 3`, `LFO 4`, `FILTER EG`,
`AMPLIFIER EG`, `MODULATION EG`, `NOISE EG`, `MOD WHEEL`, `PITCH WHEEL`, `PAD X`,
`PAD Y`, `PAD PRESSURE`, `PAD GATE`, `VELOCITY`, `VEL RELEASE`, `AFTERTOUCH`,
`KEY PITCH`, `KB GATE`, `ON/OFF GATE`, `TRIGGER GATE`, `SUSTAIN`, `EXP 1`,
`EXP 2`, `CV IN 1`, `CV IN 2`, `RANDOM`, `RANDOM BIPOLAR`, `RANDOM KEYED 1..3`,
`CONSTANT`, `VAR 1..10`). That array is **menu order, not wire order** — it does
not reproduce the observed ids. [READ]

`vx_ee` also defines **16 general-purpose MIDI-mappable mod sources `m0…m15`**
("intended for external controls; MIDI controllers can be mapped to these").
No panel name is known for them and no preset references them. Their id range is
unknown. [READ for their existence; [INFERRED] that they precede `gate`]

---

## 7. Symbol table 2 — destinations

The destination id is **the index into the `vx_ee` `results` list**. That list has
exactly 126 entries (0–125). Of the 64 observed ids that resolve to a real parameter, 62 land on the
vx_ee symbol exactly; two disagree (see the note after the table). Two further
ids — 137 and 141 — are "no destination" sentinels. `var0…var9` continue at
126–135. [READ]

The `results` symbol names are also, verbatim, the destination tokens of the RPN
form — all 76 tokens used across 1696 expressions are `results` symbols, with
zero misses. [READ]

`seen` column: "*n* slots" = attested *n* times in the numeric corpus; "RPN" =
attested only via the text corpus.

| id | vx_ee symbol | OSC parameter (relative to `/p/part/t/N`) | seen |
|---|---|---|---|
| 0 | `l1f` | `/p/l1/f` | 1× |
| 1 | `l1pno` | `/p/l1/pno` | 3× |
| 2 | `l1v` | `/p/l1/var` | RPN |
| 3 | `l1dm` | `/p/l1/td` | 1× |
| 4 | `l1fim` | — |  |
| 5 | `l1fom` | — |  |
| 6 | `l2f` | `/p/l2/f` | RPN |
| 7 | `l2pno` | `/p/l2/pno` | 10× |
| 8 | `l2v` | `/p/l2/var` | RPN |
| 9 | `l2dm` | `/p/l2/td` | 1× |
| 10 | `l2fim` | — |  |
| 11 | `l2fom` | — |  |
| 12 | `l3f` | `/p/l3/f` | 4× |
| 13 | `l3pno` | `/p/l3/pno` | 4× |
| 14 | `l3v` | `/p/l3/var` | 1× |
| 15 | `l3dm` | — |  |
| 16 | `l3fim` | — |  |
| 17 | `l3fom` | — |  |
| 18 | `l4f` | `/p/l4/f` | 8× |
| 19 | `l4pno` | `/p/l4/pno` | RPN |
| 20 | `l4v` | `/p/l4/var` | RPN |
| 21 | `l4dm` | — |  |
| 22 | `l4fim` | — |  |
| 23 | `l4fom` | — |  |
| 24 | `e1dlm` | `/p/e1/delay` | 5× |
| 25 | `e1am` | `/p/e1/a` | 2× |
| 26 | `e1hm` | `/p/e1/h` | RPN |
| 27 | `e1dm` | `/p/e1/d` | 8× |
| 28 | `e1s` | `/p/e1/s` | 1× |
| 29 | `e1rm` | `/p/e1/r` | 1× |
| 30 | `e1tm` | `/p/e1/tscale` | RPN |
| 31 | `e2dlm` | `/p/e2/delay` | 24× |
| 32 | `e2am` | `/p/e2/a` | RPN |
| 33 | `e2hm` | `/p/e2/h` | RPN |
| 34 | `e2dm` | `/p/e2/d` | RPN |
| 35 | `e2s` | `/p/e2/s` | 1× |
| 36 | `e2rm` | `/p/e2/r` | RPN |
| 37 | `e2tm` | `/p/e2/tscale` | 17× |
| 38 | `e3dlm` | `/p/e3/delay` | RPN |
| 39 | `e3am` | `/p/e3/a` | 2× |
| 40 | `e3hm` | — |  |
| 41 | `e3dm` | `/p/e3/d` | 4× |
| 42 | `e3s` | `/p/e3/s` | RPN |
| 43 | `e3rm` | `/p/e3/r` | 1× |
| 44 | `e3tm` | — |  |
| 45 | `ensam` | `/p/noise/a` | 16× |
| 46 | `ensdm` | — |  |
| 47 | `enss` | — |  |
| 48 | `ensrm` | `/p/noise/r` | RPN |
| 49 | `oct` | — |  |
| 50 | `po` | — |  |
| 51 | `pno` | `/p/po` | 40× |
| 52 | `l1po` | `/p/m/l1_p` | 271× |
| 53 | `e3po` | `/p/m/e3_p` | 2× |
| 54 | `l3od` | `/p/m/l3_od` | 11× |
| 55 | `l3pd` | `/p/m/l3_pd` | 3× |
| 56 | `ofm` | `/p/fm/amt` | 11× |
| 57 | `o1pno` | `/p/o1/po` | 12× |
| 58 | `o1o` | — |  |
| 59 | `o1po` | — |  |
| 60 | `o1fo` | `/p/o1/fo` | 3× |
| 61 | `o1d` | `/p/o1/d` | 4× |
| 62 | `o1tr` | `/p/o1/tr` | 1× |
| 63 | `o1ang` | — |  |
| 64 | `p1d` | `/p/p1/d` | 3× |
| 65 | `o1bal` | `/p/mix/o1/plsbal` | 6× |
| 66 | `o1fm` | — |  |
| 67 | `o2pno` | `/p/o2/po` | 11× |
| 68 | `o2o` | — |  |
| 69 | `o2po` | — |  |
| 70 | `o2fo` | `/p/o2/fo` | 10× |
| 71 | `o2d` | `/p/o2/d` | 2× |
| 72 | `o2tr` | `/p/o2/tr` | RPN |
| 73 | `o2ang` | — |  |
| 74 | `p2d` | `/p/p2/d` | 9× |
| 75 | `o2bal` | `/p/mix/o2/plsbal` | 6× |
| 76 | `o2fm` | — |  |
| 77 | `o3pno` | `/p/o3/po` | 10× |
| 78 | `o3o` | — |  |
| 79 | `o3po` | — |  |
| 80 | `o3fo` | `/p/o3/fo` | 12× |
| 81 | `o3d` | `/p/o3/d` | RPN |
| 82 | `o3tr` | `/p/o3/tr` | 2× |
| 83 | `o3ang` | — |  |
| 84 | `p3d` | `/p/p3/d` | 6× |
| 85 | `o3bal` | `/p/mix/o3/plsbal` | 7× |
| 86 | `o3fm` | — |  |
| 87 | `nsbal` | `/p/noise/mix` | 5× |
| 88 | `mixo1` | `/p/mix/o1/g` | 1× |
| 89 | `mixo2` | `/p/mix/o2/g` | 2× |
| 90 | `mixo3` | `/p/mix/o3/g` | 4× |
| 91 | `mixrm` | `/p/mix/rm/g` | 4× |
| 92 | `mixn` | `/p/mix/n/g` | 3× |
| 93 | `mixext` | — |  |
| 94 | `fpn` | — |  |
| 95 | `fr` | — |  |
| 96 | `ffm` | — |  |
| 97 | `fapn` | `/p/fa/p` | 82× |
| 98 | `far` | `/p/fa/r` | 22× |
| 99 | `fafm` | `/p/fa/fm/idx` | 14× |
| 100 | `fa1pn` | — |  |
| 101 | `fa1r` | — |  |
| 102 | `fa1fm` | — |  |
| 103 | `fa2pn` | `/p/fa/2/p` | 15× |
| 104 | `fa2r` | — |  |
| 105 | `fa2fm` | — |  |
| 106 | `fbpn` | `/p/fb/p` | 79× |
| 107 | `fbr` | `/p/fb/r` | 8× |
| 108 | `fbfm` | `/p/fb/fm/idx` | 8× |
| 109 | `fbal` | `/p/fbal` | 30× |
| 110 | `fegpn` | — |  |
| 111 | `faegpn` | `/p/fa/eg_p` | 10× |
| 112 | `fa1egpn` | — |  |
| 113 | `fa2egpn` | — |  |
| 114 | `fbegpn` | `/p/fb/eg_p` | 12× |
| 115 | `flpn` | — |  |
| 116 | `falpn` | `/p/fa/lfo_p` | 13× |
| 117 | `fa1lpn` | — |  |
| 118 | `fa2lpn` | — |  |
| 119 | `fblpn` | `/p/fb/lfo_p` | 17× |
| 120 | `fxb1s` | — |  |
| 121 | `fxb2s` | — |  |
| 122 | `vca` | `/p/g` | 7× |
| 123 | `main` | — |  |
| 124 | `pan` | `/p/pan` | 34× |
| 125 | `sustain` | — |  |
| 126 | `var0` | `/p/modmatrix/vars/var0` | 4× |
| 127 | `var1` | — |  |
| 128 | `var2` | — |  |
| 129 | `var3` | — |  |
| 130 | `var4` | — |  |
| 131 | `var5` | — |  |
| 132 | `var6` | — |  |
| 133 | `var7` | — |  |
| 134 | `var8` | — |  |
| 135 | `var9` | — |  |

**Two rows disagree with the v1.5.0 ordering.** `dst_id 3` appears once with
`entry/dst = /p/part/t/1/p/l1/td` and `dst_id 9` once with `/p/l2/td`
(OMNI - RIDER t3 row 2; FASCINATE t1 row 5). Both rows are otherwise internally
consistent (their `src_id` matches their `src` name), so these are not stale. The
v1.5.0 `results` names those three per-LFO slots `l<n>dm` / `l<n>fim` /
`l<n>fom` (delay / fade-in / fade-out time multipliers) while `las-sc`'s own `_m`
alias table names the corresponding OSC parameters `/p/l1/d`, `/p/l1/ta`,
`/p/l1/td`. Only `id = block+3 ↔ /p/l<n>/td` is attested. **The pairing of
slots +3/+4/+5 to `d`/`ta`/`td` is unresolved.** Everything else in the table is
either directly attested or falls out of the 64-anchor exact fit.

**Two "no destination" sentinels exist: 137 and 141.** Both appear on rows whose
`entry/dst` is `""` or `"/dummy"`, and both appear on muted rows. No preset
contains both (24 presets use 137, 9 use 141) — consistent with two firmware
revisions choosing different values as the `results` list grew. `126–135` are
`var0…var9`; `136–139` are most likely `cvout1…cvout4` (v1.5.0 added *"The Mod
Matrix now allows … CV Outputs as Destinations"* and the preset carries
`modmatrix/vars/cvout1…4`), which would put 137 inside the CV-out range and make
141 the true "none". **Unresolved** — do not emit 137 or 141 as a destination;
emit a real destination or omit the row. [READ for the observations, INFERRED for
the reading]

Also note: `las-sc` carries an *independent* alias table of 115 entries mapping
`/p/<param>_m` OSC addresses to `results`-style short symbols
(`captures/arch-harvest/las-sc`, 0x1e2d5f … 0x1e4090 — e.g. `/p/fb/p_m → fbpn`,
`/p/g_m → vca`, `/p/pan_m → pan`). That is a *different* mechanism — a direct
host-side write of a modulation value — and it disagrees with the mod matrix in
two places: it maps `/p/o1/po_m → o1po` (semitone domain, `results` 59) where the
matrix uses `o1pno` (normalised, `results` 57), and it maps the four
`/p/noise/*_m` addresses onto `e1am`/`e1dm`/`e1s`/`e1rm` rather than the noise
envelope's own `ensam`/`ensdm`/`enss`/`ensrm`. The latter looks like a
copy-paste defect in v1.5.0's `las-sc`. [READ]

---

## 8. Symbol table 3 — transforms and functions

### 8.1 Transform selector

One integer field. Ids 1–10 are the named transforms; **11 + F** selects
`FUNCTION` number F; 43 is "none".

| id | name | argument (`tr_a`) | in 1.8.2 corpus |
|---|---|---|---|
| 0 | `LIMIT LOW` — `max(in, a)` | the floor | 11 (RPN `max`) |
| 1 | `LIMIT HIGH` — `min(in, a)` | the ceiling | 4 slots + 37 RPN |
| 2 | `SQUARED` | — | 2 + 10 RPN |
| 3 | `CUBED` | — | 5 + 11 RPN |
| 4 | `LOPASS` — one-pole LP on the modulation signal | cutoff | 7 |
| 5 | `HIPASS` — one-pole HP; passes change, rejects DC | cutoff | 7 |
| 6 | `SLEW` — symmetric rate limit | slew time = 10·x³ s | 48 |
| 7 | `SLEW UP` — rate-limit rising only | 10·x³ s | 15 |
| 8 | `SLEW DOWN` — rate-limit falling only | 10·x³ s | 8 |
| 9 | `S&H` — free-running sample & hold of `S·C` | rate = 100·x Hz | 4 |
| 10 | `BOUNCE` — bouncing-ball physics; input sets drop height | gravity | 13 |
| 11 + F | `FUNCTION` *F* (F = 0…30) | slot `tr_a` = 0; F is carried in the panel `tr_a` **and** in the id | 14 |
| 42 | *unassigned / unknown* | | |
| **43** | **none** | | 861 |

Ids 1–10 and the `11 + F` rule are `[READ]` — 1–10 by direct slot↔name
co-occurrence in the corpus, and `11 + F` from five independent FUNCTION rows
(`tr_a` 3→id 14, 12→23, 14→25, 17→28, 19→30; `id − tr_a = 11` in all five).
`43 = none` is `[READ]` (861 rows).

`LIMIT LOW = 0` is `[INFERRED]`. It is never seen in a numeric slot (it only
occurs in the RPN corpus, where it is `max`). Id 0 is the only free value below
11, and `{0 LIMIT LOW, 1 LIMIT HIGH, 2 SQUARED, 3 CUBED}` is exactly the
pre-1.3.0 transform set — the four the RPN compiler can express. The frontend's
transform menu array (`las-frontend` `.data` +0x8a57eb0: `-`, `LIMIT HIGH`,
`SQUARED`, `CUBED`, `LOPASS`, `HIPASS`, `SLEW`, `SLEW UP`, `SLEW DOWN`, `S&H`,
`BOUNCE`, `FUNCTION`, `LIMIT LOW`) is menu order and puts `LIMIT LOW` last, which
is why the id has to be recovered by argument rather than read off. [READ for the
array, INFERRED for the id]

The gap at 42 is consistent with the FUNCTION block being **32 slots wide**
(11…42) with only 31 defined, `none` following at 43.

### 8.2 The FUNCTION list

31 functions. Recovered two independent ways that agree exactly: the pointer array
in `las-frontend` `.data` at **0x8a57f8c – 0x8a58004** (31 consecutive `const
char*` into `.rodata` 0x7e42005–0x7e42145), and Moog's own v1.3.0 release notes,
which list them in the same order. [READ ×2]

The distinction that matters: *"All other transforms use SOURCE * CONTROLLER as
their input signal … FUNCTIONS allow the Source and Controller to be used as two
separate inputs."* `V` is the function's own output from the previous evaluation
pass — genuine per-slot feedback state. [READ, v1.3.0 notes]

| F | id | name | semantics (Moog's wording, condensed) |
|---|---|---|---|
| 0 | 11 | `S+C` | add |
| 1 | 12 | `S/C` | divide — **see §13.2 on C = 0** |
| 2 | 13 | `S/(1-C)` | divide by `1−C` — **see §13.2 on C = 1** |
| 3 | 14 | `(S+C)^2` | sum, squared |
| 4 | 15 | `SIN(S+C)` | sum mapped onto a sine |
| 5 | 16 | `TRI(S+C)` | sum mapped onto a triangle |
| 6 | 17 | `SAW(S+C)` | sum mapped onto a saw |
| 7 | 18 | `\|S+C\|` | rectified sum |
| 8 | 19 | `MIN(S,C)` | minimum |
| 9 | 20 | `MAX(S,C)` | maximum |
| 10 | 21 | `S AND C` | logical AND, TRUE when > +0.5 |
| 11 | 22 | `S OR C` | logical OR, TRUE when > +0.5 |
| 12 | 23 | `QUANTIZE S BY C` | quantise S to 1…16 steps set by C |
| 13 | 24 | `SAMPLE S ON C` | sample S on C's FALSE→TRUE edge |
| 14 | 25 | `SAMPLE S ON ~C` | sample S on C's TRUE→FALSE edge |
| 15 | 26 | `TRACK S WHILE C` | track-and-hold, gate high |
| 16 | 27 | `TRACK S WHILE ~C` | track-and-hold, gate low |
| 17 | 28 | `SLEW S OVER C` | slew S at a rate set by C |
| 18 | 29 | `LOPASS S OVER C` | LP S, cutoff = C |
| 19 | 30 | `HIPASS S OVER C` | HP S, cutoff = C |
| 20 | 31 | `C(S-V)` | *iterative* — V is last pass's output |
| 21 | 32 | `C(V+S)` | iterative |
| 22 | 33 | `CV+S` | iterative |
| 23 | 34 | `(C+1)V+S` | iterative |
| 24 | 35 | `V+C(V+S)` | iterative |
| 25 | 36 | `C\|V\|+S` | iterative |
| 26 | 37 | `DIODE(S-C)` | `max(S−C, 0)` |
| 27 | 38 | `DIODE(S-C+0.5)` | `max(S−C+0.5, 0)` |
| 28 | 39 | `DIODE(S-C-0.5)` | `max(S−C−0.5, 0)` |
| 29 | 40 | `DIODE(S-C+0.25)` | `max(S−C+0.25, 0)` |
| 30 | 41 | `DIODE(S-C-0.25)` | `max(S−C−0.25, 0)` |

**Only five functions appear in 222 factory presets**, in 14 rows total:
`QUANTIZE S BY C` (7 rows), `SAMPLE S ON ~C` (2), `SLEW S OVER C` (1),
`HIPASS S OVER C` (1), `(S+C)^2` (1). Twenty-six functions — including every one
of the six iterative/feedback functions and all five diodes — are **never used**.
[READ]

---

## 9. The constant register file

**128 registers per timbre**, `c0` … `c127`.

* `vx_ee.scm` declares the `parms` section as a 128-wide `c` array, described as
  "expression constants … intended for adjustable modulation amounts, and
  intended for saving with presets". Its prose comment says `c0..c31` and
  `/p/part/t/<n>/p/c/0..31`; **the comment is stale, the array is 128**. [READ]
* Every `/p/version` ≤ 12 preset (617 in the union corpus) carries
  `/p/part/t/<N>/p/c/0` through `/c/127` — 128 leaves per timbre, no gaps, every
  preset. [READ]
* `/p/version` 14 presets carry **no** `p/c/*` at all, and neither does the live
  v1.5.0 `/p` namespace. In the numeric form the amounts are inline in the slot
  tuple. [READ]

**Where the values live.** Not in the expression string — in the preset, at
`/p/part/t/<N>/p/c/<i>`, one OSC leaf per register. That is the whole point of
the design: turning an amount knob re-sends one float to one address and never
recompiles the program.

**Allocation.** Row *i* owns `c[3i]` (`tr_a`), `c[3i+1]` (`ctl_a`), `c[3i+2]`
(`src_a`). The highest row-register seen anywhere is `c59` (row 19). `c64` is
reserved for the sequencer lane (§10.2). Registers not referenced by the current
program keep stale values from previous edits and are ignored.

The recorded claim "64 constant registers" is wrong; so is the inference in
`docs/ROADMAP.md` that `c64` "exists" as evidence for a 65-wide file. `c64` is a
*specific reserved* register, and the file is 128 wide.

---

## 10. VARs, the sequencer lane, CV outs

### 10.1 `VAR 1` … `VAR 10`

Ten per-timbre variables, added in v1.3.0. They are simultaneously

* **destinations** — `results` ids 126–135, OSC
  `/p/part/t/<N>/p/modmatrix/vars/var0…var9`. `var0` is attested as a slot
  destination in 4 factory rows. [READ]
* **sources** — panel names `VAR 1`…`VAR 10`, source ids 37–46 (`VAR 1` = 37
  attested). [READ]

Moog's semantics, verbatim in substance: *"The Modulation Matrix and sequencer
modulations are evaluated in a fixed order… Sequencer modulation lanes are
evaluated first, then mod-matrix slots, each in top to bottom order… VARS will
contain what was previously sent to them for each evaluation cycle and are then
cleared for the next cycle… You can use the same VAR as the destination for more
than one modulation; in this case the values sent to the VAR will be summed."*
[READ, v1.3.0 release notes]

So: **VARs are per-cycle accumulators with one cycle of latency when read above
their writer, and zero latency when read below it.** They are the only way to
chain modulation, and they are what makes row order significant in the numeric
form (it is not significant in the RPN form — see §2.2).

All 3000 `var0…var9` leaves in the 1.8.2 corpus are `0.0` — the saved value is an
initial condition, and the factory never sets one. [READ]

### 10.2 `rcl` is the sequencer modulation lane

`rcl` occurs 32 times in the union corpus and **every occurrence is the two-token
sequence `c64 rcl`** — never any other register, never any other shape. It always
contributes an additive term to one destination:

```
c64 rcl fbal sto                       (whole statement)
padx c20 * c64 rcl + fbal sto          (added to an ordinary row)
mw c2 * e1 c5 * + c64 rcl + fbpn sto   (added to two merged rows)
```

In **29 of 32** cases the destination of the `rcl` statement is exactly the
destination named by that timbre's sequencer modulation lane,
`/p/part/t/<N>/p/seq/m/l/0/dst`. The other three are timbres with no lane at all —
orphaned statements left behind when a lane was deleted. [READ]

The lane itself is a matrix-row-shaped object: `seq/m/l/0/{dst, ctl, ctl_a}` plus
64 per-step values `seq/m/l/0/s/<0..63>/o`. Exactly one lane exists per timbre in
the pre-1.3.0 format; 30 timbres out of 2256 in the union corpus have one. [READ]

So the operational reading is: **`c64` is the register into which the sequencer
writes the current step's modulation offset, and `c64 rcl` reads it at
evaluation time.** [INFERRED, strongly]

What `rcl` *means* as an opcode is **unresolved**. Two readings survive:

1. `c<n>` in a value position is a compile-time-resolved immediate and `c<n> rcl`
   forces a live read. Argues against itself: bare `c<n>` must already be a live
   read, because turning an amount knob sends one float to `/p/c/<n>` and does
   not recompile.
2. `c<n>` pushes a value and `rcl` uses it as an index into another file — most
   plausibly `vx_ee`'s 16 general-purpose `v0…v15` "state storage" variables.
   `c64` is `0.0` in every saved preset, so this would read `v0`.

The corpus cannot separate them: the only register ever recalled holds 0.0 on
disk and is written at run time. If you need this, it is settleable by reading
one `c64 rcl` preset with a sequencer lane on a v1.2.x instrument, or by
decompiling the VX image.

In the ≥1.3.0 world this whole mechanism is replaced by `seq_expression_slots`
and the lanes are ordinary slot rows evaluated before the matrix.

### 10.3 CV outputs

`/p/part/t/<N>/p/modmatrix/vars/cvout1…cvout4` exist in 25 of the 100 v14
presets, all `0.0`. v1.5.0's notes: *"The Mod Matrix now allows CV Inputs as
Sources and CV Outputs as Destinations"*, with the caveat that
`SETTINGS > CV OUTPUTS > CV OUT [n] > SOURCE` must be `MODULATION OUTPUT` for
anything to reach the jack. Their destination ids are unattested; 136–139 is the
obvious placement (immediately after `var9`) but see the 137/141 problem in §7.
[READ for existence and the release note; INFERRED for the ids]

---

## 11. Worked examples

Each gives the raw compiled form, the panel row(s) it came from, and a reading.

### 11.1 The simplest statement — controller-only row

```
mw c1 * l1po sto
```
`AEROBICS` t2 (`/p/version` 7). Panel row 0:
`src "-" / 1.0`, `ctl "MOD WHEEL" / 0.00999999`, `tr "-"`, `dst /p/part/t/1/p/m/l1_p`.
`c1` = `c[3·0+1]` = `ctl_a` = 0.00999999.

With no source selected the controller *is* the source. Mod wheel scales the
LFO 1 → global pitch amount by up to 1 %. This is the "vibrato on the mod wheel"
row; it is present in a majority of factory presets and is the single most common
statement in the corpus.

### 11.2 Plain source × amount

```
l4 c5 * p1d sto
```
`SWEET DREAMS` t1. Panel row 1: `src "LFO 4" / 0.30997834`, `ctl ""`, `tr ""`,
`dst /p/part/t/1/p/p1/d`. `c5` = `c[3·1+2]` = `src_a`.

LFO 4 modulates oscillator 1's pulse width by ±31 %. Two tokens of program.

### 11.3 `+` — two rows on one destination

```
l4 c5 * a c14 * + o3pno sto
```
`CHAMBER STRINGS` t1. Two panel rows:
* row 1 `src "LFO 4" / 0.023142` → `/p/o3/po`
* row 4 `src "AFTERTOUCH" / 0.0072024` → `/p/o3/po`

`c5 = c[3·1+2]`, `c14 = c[3·4+2]`. The compiler merged them into one statement
because they share a destination. Oscillator 3 gets LFO vibrato plus an
aftertouch-controlled pitch lift, summed. **`+` in this language is never
user-authored — it is only ever the compiler merging same-destination rows, or
folding in the sequencer lane.**

### 11.4 The full template — source, controller, controller amount

```
a pnt * c7 * a 1 c7 - * + c8 * l1po sto
```
`BLOOM` t1. Panel row 2: `src "AFTERTOUCH" / 3.4923549`,
`ctl "KEY PITCH" / 1.0`, `tr ""`, `dst /p/m/l1_p`.
`c7 = ctl_a = 1.0`, `c8 = src_a`.

Reads as `l1po := c8 · ( c7·(a·pnt) + (1−c7)·a )`. With `c7 = 1` the second term
vanishes and it is `a · pnt · c8`: aftertouch vibrato depth that scales with how
far up the keyboard you are. Note the compiler still emits the dead branch — it
folds only when `ctl_a` is exactly 0 or the controller is absent.

### 11.5 `min` = LIMIT HIGH

```
e2 c3 min gate * c4 * e2 1.0 c4 - * + c5 * fapn sto
```
`DATA ROLL` t1. Panel row 1: `src "AMPLIFIER EG" / -2.0`, `ctl "KB GATE" / 1.0`,
`tr "LIMIT HIGH" / 0.5`, `dst /p/fa/p`.
`c3 = tr_a = 0.5`, `c4 = ctl_a = 1.0`, `c5 = src_a = −2.0`.

`fapn := −2.0 · min(e2, 0.5) · gate`. The amp envelope opens the SVF, but its
contribution is clipped at half height, so the filter sweep flattens out for the
top half of the envelope. Gate as controller mutes it between notes.

### 11.6 `max` = LIMIT LOW

```
a c3 max pnt * c4 * a 1 c4 - * + c5 * l1po sto
```
`TYRELL` t1. Panel row 1: `src "AFTERTOUCH" / 0.014181`,
`ctl "KEY PITCH" / 1.0`, `tr "LIMIT LOW" / 1.0`.

`tr_a` is 1.0, and aftertouch is 0…1, so `max(a, 1.0)` is **constantly 1** — the
transform pins the source. The result is `pnt · src_a`: pure key-tracked vibrato
depth with aftertouch defeated. Whether that was intended is another question;
it is what the preset says.

### 11.7 `**` = SQUARED

```
v ** c8 * padx c32 * + fapn sto
```
`BLURRY HURRY` t1 (`/p/version` 8) — one of only two `**` statements in the
222-preset corpus. Two panel rows on `/p/fa/p`:
* row 2 `src "VELOCITY" / 0.79`, `tr "SQUARED"` → `c8 = c[3·2+2]`
* row 10 `src "PAD X" / −1.51` → `c32 = c[3·10+2]`

`fapn := velocity²·0.79 + padx·(−1.51)`. Squaring the velocity makes the filter
response quadratic — soft playing barely opens the filter, hard playing opens it
fast. The other `**` statement in the same preset,
`e3 ** v * c1 * e3 1.0 c1 - * + c2 * pady c26 * + o2pno sto`, shows `**` used
inside the full template with a controller: a squared modulation envelope times
velocity, plus pad-Y, all into oscillator 2 pitch.

### 11.8 `***` = CUBED

```
e3 c8 * a *** c23 * + fbpn sto
```
`NIGHTLY NEWS` t1 (`/p/version` 7). Two panel rows on `/p/fb/p`:
* row 2 `src "MODULATION EG" / 0.12567` → `c8`
* row 7 `src "AFTERTOUCH" / 0.28457`, `tr "CUBED" / 1.0` → `c23`

`fbpn := e3·0.1257 + aftertouch³·0.2846`. The cube gives aftertouch a very long
dead zone and a sharp top — you have to lean into the key before the ladder moves
at all. The same preset's `a *** c20 * e2s sto` cubes aftertouch into the
amplitude envelope's **sustain level**, which is not something the front panel
offers as a dedicated control.

### 11.9 Random as a controller

```
gate rnd * c13 * gate 1 c13 - * + c14 * e2dlm sto
```
`BLOOM` t1. Panel row 4: `src "KB GATE" / 1.0`, `ctl "RANDOM" / 1.0`,
`dst /p/e2/delay`. `c13 = ctl_a = 1.0`, `c14 = src_a`.

`e2dlm := gate · rnd · src_a` — a random delay before the amplitude envelope
starts, re-rolled per note *if* `rnd` is sampled at note-on, or continuously
otherwise (§2.4, unresolved). Five factory presets use exactly this idiom.

### 11.10 `rcl` — the sequencer lane folded into a row

```
padx c20 * c64 rcl + fbal sto
```
`EQUAL LATERALS` t1 (`MOOG ONE.db`, `/p/version` 6). Panel row 6:
`src "PAD X" / 1.0` → `/p/fbal`. And
`/p/part/t/1/p/seq/m/l/0/dst = "/p/part/t/1/p/fbal"` — the sequencer's modulation
lane targets the same parameter.

`fbal := padx·1.0 + <sequencer step value>`. The filter A/B balance is driven by
the pad and offset per sequencer step.

### 11.11 A numeric-form row that the text form cannot express

`BOTANY` t1, rows 0 and 1 (`/p/version` 14):

```
slots: [21, 0.4, 36, 0.57, 23, 0.0, 67]
       [21, 0.4, 36, 0.37, 23, 0.0, 77]
panel: src "LFO 4"/0.4  ctl "CONSTANT"/0.57  tr "FUNCTION"/12  dst /p/o2/po
       src "LFO 4"/0.4  ctl "CONSTANT"/0.37  tr "FUNCTION"/12  dst /p/o3/po
```

src 21 = `LFO 4`, ctl 36 = `CONSTANT`, tr 23 = 11 + 12 = **FUNCTION 12 =
`QUANTIZE S BY C`**, dst 67/77 = `o2pno`/`o3pno`.

Two copies of LFO 4, each quantised to a different number of steps (0.57 and 0.37
of the 1…16 range), driving oscillators 2 and 3. A stepped, non-synchronised
pitch pattern per oscillator. There is no RPN encoding for this — `QUANTIZE`
needs no state, but `FUNCTION` as a class arrived with the slot form.

`ALCOVE` t1 rows 0 and 1 show the stateful case:

```
[28, 1.0,   23, 1.0, 28, 0.0, 103]   RANDOM KEYED 1 × AMPLIFIER EG, FUNCTION 17
[23, 0.0025, 0, 1.0, 30, 0.0,  57]   AMPLIFIER EG × KB GATE,        FUNCTION 19
```

FUNCTION 17 = `SLEW S OVER C`: a per-note random value slewed at a rate set by
the amplitude envelope, into SVF 2 cutoff. FUNCTION 19 = `HIPASS S OVER C`: the
amp envelope high-passed (so only its *changes* survive) into oscillator 1 pitch —
a per-note pitch blip. Both need per-slot memory; both are unreachable from the
text language.

---

## 12. What the factory never does

The vocabulary is far larger than the factory's use of it. Counted over the
1.8.2 corpus (and, where noted, the 752-preset union).

**Never used at all:**

| unused | count | of |
|---|---|---|
| destinations | 50 | 126 `results` |
| functions | 26 | 31 |
| sources | 11 | 30 non-`m` `args` |
| MIDI mod sources `m0…m15` | 16 | 16 |
| variables `VAR 2…VAR 10` | 9 | 10 |
| sequencer modulation lanes (1.8.2 packs) | all | — |

Unused destinations include every LFO fade/delay multiplier
(`l<n>dm/fim/fom`, 11 of 12), all three envelope `hm` (hold) slots, all four
`o<n>fm` per-oscillator FM amounts, all of SVF 1 (`fa1pn/fa1r/fa1fm/fa1egpn/fa1lpn`),
the global filter aliases (`fpn/fr/ffm/fegpn/flpn`), `mixext`, `oct`, `po`,
`o<n>o`, `o<n>po`, `o<n>ang`, **`fxb1s`/`fxb2s` (the two bus effect sends)**,
`main`, and `sustain`.

Unused sources: `cvin1`, `cvin2`, `expr1`, `expr2`, `sus`, `padg`, `p`, `pp`,
`ktc`, `pto`, `vspr`, plus `m0…m15`.

Below, each idea is given as something you could actually write. Text-form
examples are legal pre-1.3.0 programs; slot-form examples are `[src, src_a, ctl,
ctl_a, tr, tr_a, dst]` tuples for firmware ≥ 1.3.0. **None of these has been run.
All are `[INFERRED]`, and §13 applies to every one of them.**

### 12.1 Chained arithmetic across more than two terms

The compiler only ever emits `+` to merge same-destination rows, and never nests
more than the fixed template. The stack machine has no such limit.

```
l1 l2 * l3 * c10 * fbpn sto
```

Three LFOs multiplied — a ring-modulated modulator. Two LFOs multiplied is
already impossible from the panel (the panel gives you `source × controller`,
one level); three is well outside it. Sonically: a pulsing, beating filter motion
whose envelope is itself an LFO product, going near-silent whenever any of the
three crosses zero. The same shape with `min`/`max` gives a chopped, gated sweep.

In the slot form the equivalent needs two rows and a VAR:
```
[18, 1.0, 19, 1.0, 43, 0.0, 126]      LFO1 × LFO2  → var0
[37, 1.0, 20, 1.0, 43, 0.0, 106]      VAR 1 × LFO3 → fbpn
```
Three factory presets do exactly this two-row shape (§12.4), so the mechanism is
attested; three-deep is not.

### 12.2 Cross-timbre modulation

**Unattested and probably not expressible.** The RPN destination token is a bare
`results` symbol with no timbre qualifier, and the numeric `dst_id` is a bare
integer. The expression program is per-timbre, and the evaluator instance is
per-voice on a voice card assigned to one timbre. The `t/1` in `entry/*/dst` is
a display string, not a route (§0). If cross-timbre routing exists it is via a
mechanism this corpus does not contain — most plausibly the host-side
`/p/part/t/<N>/p/<param>_m` alias table in `las-sc` (§7), where the timbre *is*
in the address and the value comes from the i.MX6. That is a real, separate lever
and it is worth its own investigation.

### 12.3 `rcl` as scratch memory

Zero factory presets use `rcl` for anything but the sequencer lane, and none
writes to a `c` register from inside an expression (there is no `sto`-to-`c`
form; `sto`'s destination namespace is `results`, disjoint from `parms`). So the
"store and recall" reading of this machine is **not supported by the corpus**.
The `vx_ee` `vars` section — 16 general-purpose `v0…v15` slots explicitly
described as state storage for LFOs and LFSRs — has no attested access path from
the expression text at all. If reading 2 in §10.2 is right, `c<n> rcl` reads
`v[c<n>]`, and writing them would need an opcode nobody has seen.

**The supported way to do scratch memory is `VAR 1…10`** (slot form only).

### 12.4 Sample-and-hold built out of `sto`

Not needed, and not possible: `sto` has no read-back path. Sample-and-hold is a
first-class transform (`S&H`, id 9, free-running, rate `100·x` Hz) and two
first-class functions (`SAMPLE S ON C` / `SAMPLE S ON ~C`, gate-edge triggered).
The factory uses `S&H` in 4 rows and `SAMPLE S ON ~C` in 2, and never uses
`SAMPLE S ON C` or either `TRACK` function.

What the factory *does* do — and only three presets do it — is chain through a
VAR:

```
GAMMA-RAY t1 row 8: [8, 0.43, 36, 0.57, 23, 0.0, 126]   PAD X quantised by 0.57 → var0
GAMMA-RAY t1 row 9: [37, 1.0, 48, 1.0,  6, 0.64, 57]    VAR 1 slewed 0.64 s     → o1 pitch
MAGIC    t1 row 8: [24, 0.30, 48, 0.57, 9, 5.0,  126]   MOD EG sampled at 5 Hz  → var0
MAGIC    t1 row 9: [37, 1.0, 36, 0.57, 23, 0.0,  57]    VAR 1 quantised         → o1 pitch
VAST EDGE t1 row 9:  [8, 1.0, 48, 1.0, 10, 2.6,  126]   PAD X through BOUNCE    → var0
VAST EDGE t1 row 10: [37, 1.0, 48, 1.0,  6, 0.156, 103] VAR 1 slewed 156 ms     → SVF2 cutoff
```

Note the writer is always the row immediately above the reader — the fixed
top-to-bottom evaluation order (§10.1) makes that a same-cycle read. **Three
presets out of 222 use the chaining feature at all, all of them one link deep,
all of them into `var0`.** Nine of the ten variables are dead.

An obvious unused extension: put the reader *above* the writer to get a
deliberate one-cycle delay, and you have a two-row recursive filter without using
the iterative functions.

### 12.5 Feedback

Two independent feedback mechanisms exist and neither is used.

**(a) The iterative functions.** `C(S-V)`, `C(V+S)`, `CV+S`, `(C+1)V+S`,
`V+C(V+S)`, `C|V|+S` (ids 31–36) each feed the slot's own previous output back in.
`CV+S` with `S` = a gate and `C` slightly below 1 is a one-pole decay envelope of
arbitrary length — a fifth envelope generator, per slot, per voice. `C(S-V)` is a
difference tracker; `C|V|+S` is a rectifying feedback loop that will chirp.
**Zero factory uses of any of the six.**

```
[0, 1.0, 36, 0.98, 33, 0.0, 106]     KB GATE, CONSTANT 0.98, FUNCTION 22 (CV+S) → fbpn
```
Reading: on each cycle `V := 0.98·V + gate`. Holding a note ramps the ladder
cutoff up to a ceiling of `1/(1−0.98)` = 50× the gate; releasing it decays with a
time constant of ~50 cycles. That ceiling is exactly why this is dangerous
(§13).

**(b) VAR loops.** Write `var0` from a row *below* the row that reads it and the
value persists one evaluation cycle — a unit delay. Two such rows make a
two-tap recursive filter; a VAR chain of three makes a state-variable one. Moog's
own release note frames VARs as chaining, not feedback, and warns that they are
"cleared for the next cycle", which suggests a VAR read before any write in a
cycle yields 0 rather than the previous cycle's value. **Unresolved** — this
determines whether (b) works at all.

### 12.6 The unused destinations that would sound like something

* **`fxb1s` / `fxb2s`** — the two bus effect sends, modulatable per voice, never
  used by any factory preset. A per-note random into `fxb1s` gives you reverb
  amount that varies note to note within one chord. There is no panel control
  for this.
* **`l<n>fim` / `l<n>fom`** — LFO fade-in and fade-out times. Velocity into
  `l1fim` makes vibrato arrive faster the harder you play.
* **`o<n>fm`** — per-oscillator FM amount, as opposed to the global `ofm` macro
  the factory uses 11 times.
* **`e<n>hm`** — envelope hold time. Aftertouch into `e2hm` is a sustain pedal
  that you press with your finger.
* **`sustain`** and **`main`** — modulating the timbre's own sustain state and
  main output level from the matrix.
* **`mixext`** — external input level into the voice mixer, per voice, from a
  modulator.

### 12.7 The unused sources

`cvin1`, `cvin2`, `expr1`, `expr2` and `sus` are all real jacks on the back panel
(v1.5.0 explicitly added them to the matrix). `vspr` (voice spread) is per-voice
— using it as a source is the only way to make each voice of a chord behave
differently from a single matrix row, and it is the single most interesting
unused source in the list. `pto` (key track in octaves) and `ktc` (key-track
centre) give exact-interval key tracking that `pnt` (normalised, /120) does not.

---

## 13. Limits and safety

### 13.1 Measured limits

| quantity | max observed | where |
|---|---|---|
| matrix rows per timbre | **20** | union corpus, 2256 timbres |
| statements per expression | **14** | union corpus |
| expression string length | **414 bytes** | `BLURRY HURRY` t1 |
| tokens in one statement | **33** | `NOKOMIS` t1 (three rows merged onto `l1po`) |
| constant registers | 128 (`c0`…`c127`) | every pre-1.3.0 preset |
| sequencer mod lanes | 1 per timbre (pre-1.3.0), 64 steps | union corpus |

**No hard cap was read out of any binary.** [unknown] Two soft bounds do follow
from the encoding:

* In the RPN era the register file bounds the matrix at `⌊128/3⌋ = 42` rows, and
  `c64` is reserved for the sequencer lane, so **21 rows** (`c0`…`c62`) is the
  largest layout that does not collide. Observed max is 20.
* In the slot era there is no register pressure at all; the array simply grows.
  The observed max is still 20, which suggests a UI limit rather than an engine
  one.

### 13.2 Failure modes — what is known, and it is not reassuring

**Moog documents that this engine used to be wrong.** v1.3.0's release notes:
*"In previous versions, it was possible for presets with large numbers of
modulation expressions to load inconsistently or have some modulations evaluate
incorrectly. Modulations now always load correctly and evaluate consistently."*
[READ] So the pre-1.3.0 engine had a load-order or capacity bug that was
reproducible enough to be a headline fix. That is the only vendor statement about
robustness in the whole document set, and it is about the version of the engine
that the RPN text form targets.

**Everything else is unknown.** Specifically:

* What a malformed program does. There is exactly one data point: two presets in
  the instrument's own database contain a **stack underflow** (§2.5) and the
  instrument evidently still runs. That says nothing about the other failure
  modes — an unknown symbol, an unterminated final statement, a destination out
  of range, a `dst_id` of 137/141 written deliberately. No error string for the
  expression parser exists in `las-sc` (`strings | grep -i expr` yields four
  hits, all option-parsing), so a rejection would be silent.
  Whether the parse happens on the i.MX6 (in `las-sc`, which owns
  `expression-nodes` and reads `vx_ee.scm`) or on the voice card is **unresolved
  in the load-bearing direction**: `las-sc` clearly reads the symbol table, so it
  at least resolves names, but nothing in it looks like an evaluator, and the
  file is called the *VX* Expression Engine list.
* What a divide by zero does. `S/C` (function 1) and `S/(1-C)` (function 2) are
  both selectable from the front panel, and `CONSTANT` can be set to 0 and 1
  respectively. So the divide-by-zero case is reachable *by a user turning two
  knobs*, which is a strong argument that it is clamped — but there is no
  evidence, and "the panel can reach it" is not the same as "the OSC path
  validates it".
* What an unbounded iterative function does. `(C+1)V+S` (function 23) with
  `C ≥ 0` is the recurrence `V := (C+1)V + S`, whose gain is ≥ 1 — it diverges
  for any positive `C`. Six functions of this class exist, all reachable from the
  panel, none used by any factory preset. If the result is not clamped, this
  produces `inf` and then `NaN` in a per-voice state variable that is never reset
  except by a note event.
* Whether a poisoned NaN persists. `docs/DANGER.md` records the analogous
  failure on the *host* side: `stereoDelay_*` above ~0.5 feedback diverges to
  `inf` then `NaN` "and the node stays poisoned until replaced". No equivalent
  observation exists for the VX.

### 13.3 The rule

**This executes on the XMOS that runs the analog voices.** Treat expression
authoring as follows.

1. **Never hand-send an expression to the voice controller.** Write a `.m1p` or a
   preset row, load it, listen. `docs/arch/capability-survey.md` already says
   this and it is right.
2. **Validate before you write — the firmware does not.** A compiler for this
   language should refuse: unknown symbols; a statement whose stack does not
   balance to exactly one value (Moog's own compiler emitted two that do not,
   §2.5); `dst_id` ≥ 136 (past `var9`), which includes the 137/141 sentinels; `tr_id` = 42 or > 43; `src_id`/`ctl_id`
   outside 0…48; more than 21 rows for a pre-1.3.0 target; a `c` index > 127.
   Every one of those is cheap to check and none of them is checked for you.
3. **Have a way back before trying anything in §12.5.** The recurrences are the
   only construct here that can produce an unbounded value, and they are per
   voice on the processor that is also the ESAI clock master. If a voice card
   wedges, the recovery is `/etc/init.d/S42sc restart` — **never
   `/sbin/reboot`**, which wedges the USB gadget and needs power removed
   (`docs/DANGER.md`, Tier 2). Keep a known-good preset selected and reachable by
   a single front-panel press.
4. **The write itself is Tier-3 safe.** `/p/part/t/<N>/p/modmatrix/**` and
   `/p/part/t/<N>/p/c/<i>` are preset state — the same leaves the panel writes
   when you turn a knob, recoverable by reloading the preset. Not `/cal`, not
   `/fw`. The hazard is the *evaluated result*, not the write.
5. **Do not try the iterative functions, `S/C` with a zero controller, or
   `S/(1-C)` with a unity controller, on the real instrument until someone has a
   way to observe and reset a wedged voice card.** They are the one part of this
   language that can plausibly produce a non-finite per-voice state, and they
   have never been exercised — not by 752 presets, not by anyone.

---

## 14. What changes when `pkg/rootfs` (1.8.2) becomes readable

Six things to re-check, in order of value:

1. **`/usr/share/vx_ee.scm` for 1.8.2.** The whole of §6 and §7 is anchored on
   the v1.5.0 copy plus a reconstruction. The 1.8.2 `args` list settles source
   ids 1, 2, 5, 12–17, 26, 27, 31, 32, 34, 35, 47 outright, and the 1.8.2
   `results` list settles the LFO slot +3/+4/+5 question, the `var0…var9` and
   `cvout1…4` ids, and therefore what 137 and 141 actually are.
2. **Whether the `_m` alias table in 1.8.2's `las-sc` still maps
   `/p/noise/*_m` onto the EG-1 symbols.** If it does, that is a live defect
   worth reporting; if it doesn't, v1.5.0's copy is simply old.
3. **The `ctl_a` crossfade.** §3 documents `ctl_a·T(S)·C + (1−ctl_a)·S` from the
   pre-1.3.0 compiler. Whether the 1.3.0+ engine keeps it, or does the simpler
   `T(S·C)·src_a` its release notes describe, changes the meaning of every
   CONTROLLER AMOUNT setting in every modern preset.
4. **LOPASS/HIPASS argument scaling** (§5.1) — the corpus is genuinely split.
5. **Whether `rnd`/`rndb` are per-block or per-note**, and at what rate the whole
   expression program is evaluated. That rate is the unit of the "evaluation
   cycle" that VAR semantics and all six iterative functions are defined in
   terms of, and nothing in this document pins it down.
6. **Any row-count constant in the frontend or the VX.** 20 is the observed
   maximum; whether 21, 32 or 42 is the real cap is unknown.

Also worth doing without 1.8.2: the XMOS images `app_vx_10M_v2.1.0.bin` and
`app_las_v2.1.2.bin` are obfuscated (2022 and 1108 `strings` hits, all noise) —
`docs/INTERNAL-DO-NOT-DISTRIBUTE.md` §7 records a nibble-reversal transform for
them. Applying it and looking for the evaluator's opcode dispatch would settle
`rcl`, the division behaviour and the clamping question directly.

---

## 15. Reproduction

Everything above is reproducible from local files. Key coordinates:

| what | where |
|---|---|
| `vx_ee.scm` | decompressed v1.5.0 rootfs, byte 637,856,768, 12,288 bytes, then remainder at 637,869,059 (1 KiB blocks, two extents) |
| `--expr-syms` flag | `captures/arch-harvest/init.d/S42sc`; same line in `runtime-state.txt` |
| `las-sc` `_m` alias table (115 pairs) | `las-sc` 0x1e2d5f … 0x1e4090 (immediately after the `/p/pre-expr` leaf); CHICKEN literal encoding `FE 42 <len:3> <string>` for strings, `FE 01 <len:3> <symbol>` for symbols, `FE 03 00 00 02` = pair, `FE FF 0E` = nil |
| transform names | `las-frontend` `.rodata` 0x7e42149–0x7e421a4 (laid out in reverse declaration order) |
| function names | `las-frontend` `.rodata` 0x7e42005–0x7e42148 (reverse order; `C(V+S)` at 0x7e42057 shares its bytes with the tail of `V+C(V+S)` and is easy to miss) |
| source names | `las-frontend` `.rodata` 0x7e421a5–0x7e422bd (reverse order); `VAR 1..10` + `CV OUT 1..4` + `VARS` at 0x7e41f98–0x7e42005 |
| menu pointer arrays (`const char*[]`) | `las-frontend` `.data`: transforms 0x8a57eb0, sources 0x8a57ee4, functions 0x8a57f8c. `vaddr = file_offset + 0x10000` (PH3: off 0 → va 0x10000) |
| `ModMatrix::Pimpl::updateSequencerParams` | `las-frontend` +0x7e41ec8 |
| Moog's own semantics | `Moog_One_v1.8.2.zip` → `Past Firmware Update Release Notes/Moog One Firmware Update v1.3.0.pdf`, "NEW FEATURES" and "New FUNCTION class of TRANSFORMs" |

The corpus analyses in this document were run with throwaway Python over a
flattened `{address: value}` dict per preset; the `.m1p` files and the `data`
column of the SQLite `presets` / `mod_matrix_presets` tables use the identical
`\n`-separated `<address> <value>` format, so one parser reads both.
