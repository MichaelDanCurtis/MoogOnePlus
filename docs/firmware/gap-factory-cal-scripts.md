# The Moog-authored factory calibration scripts in `/usr/bin`

`open_ladder`, `run_process`, `check` — and the two more that came with them,
`start_tune` and `write`.

Sources: `captures/firmware-1.8.2/rootfs-1.8.2` (decrypted v1.8.2 rootfs),
`captures/rootfs-1.5.0` (v1.5.0, from the owner's instrument), and
`captures/backup/calibration-20260907-222301.tar.gz` (this unit's own
`/var/tuning.vxtune`). No instrument was contacted. Every offset below is a file
offset in the named binary, readable with `strings -a -t x` or `xxd -s`.

Grading: **[READ]** = quoted from a file at a stated line/offset. **[INFERRED]**
= reasoning, with the evidence named. **[UNKNOWN]** = not established.

---

## 0. Summary

1. There are **five** Moog-authored calibration shell scripts, not three. The
   assignment named `open_ladder`, `run_process`, `check`; `start_tune` and
   `write` are the same toolkit by the same two authors. [READ, §1]
2. **`run_process`'s fifteen-entry menu is the complete, true `--cal-op`
   vocabulary.** It matches the fifteen `cal-have-*?` predicates in `vxtune`
   one-for-one, as a set. `vxtune`'s own `--cal-op` help string advertises a
   *different, stale* thirteen-name list. The script is right and the built-in
   help is wrong. [READ, §4.1–4.2]
3. **The sparse numbering `1,7,8,9,11,13,14,15,16,17,18,19,20,22,24` is a
   1-based index into the 26-field `las-voxcal` record**, whose field order I
   read directly out of `las-sc` at 0x218761–0x218803. Fourteen of the fifteen
   land exactly. [READ for the field run; INFERRED for the mapping, §5]
4. **The write boundary is not where the prompt is.** `run_process` asks "would
   you like to write this to the vX?" *after* the calibration has already run
   with `--force`. Answering `n` does not undo anything — the analog measurement
   pass has already executed on the hardware and the on-disk database has
   already been overwritten. `n` only skips the push to the voice cards'
   persistent storage. [READ, §6]
5. `open_ladder` prints **"use ENTER to skip"** and then never reads input. The
   operator is told they can skip a step that is not skippable. [READ, §7.1]
6. All five scripts, plus `config-las-spi`, `cal-limits.scm` and
   `mod-cal-limits.scm`, are **byte-identical between v1.5.0 and v1.8.2**. [READ, §1.2]

---

## 1. Inventory

### 1.1 The five scripts

All in `usr/bin/`, all mode `0755`, all `#!/bin/bash` except `config-las-spi`
(`#!/bin/sh`). [READ]

| file | bytes | md5 | byline (verbatim, line 2) |
|---|---:|---|---|
| `check` | 115 | `1c1f9d771ebe7c4e81620378d2653116` | `#Christian Stryffeler - (c) Moog Music Inc. 2019` |
| `start_tune` | 2012 | `dc164b49e13a5f982d39ca60b7d7abb0` | `#Kevin Forte - 1/7/19 - (c) Moog Music Inc.` |
| `run_process` | 2050 | `ad5d5dd3f9f03750e9e1817189b62a36` | `#Christian Stryffeler, (c) Moog Music Inc. 2019` |
| `open_ladder` | 2195 | `ce45061e0fb8576efd53701d154eed1c` | `#Kevin Forte - 3/5/19 - (c) Moog Music Inc.` |
| `write` | 511 | `b1df4c3d3979c62395efa3b48f486b1e` | `#Christian Stryffeler - (c) Moog music Inc. 2019` |

[READ] all rows.

`write` carries **lowercase "Moog music"**, which is why a case-sensitive sweep
for `Moog Music` misses it. That is how it stayed unfound: a case-sensitive
`grep -rl "Moog Music" usr/bin/` returns only four of the five. [READ]

Two authors, two dates: Kevin Forte wrote the two unattended sequencers
(`start_tune` 1/7/19, `open_ladder` 3/5/19); Christian Stryffeler wrote the
three interactive/one-shot tools (`run_process`, `check`, `write`, all 2019).
[READ, bylines]

### 1.2 Version stability

| file | v1.5.0 vs v1.8.2 |
|---|---|
| `usr/bin/open_ladder` | identical |
| `usr/bin/run_process` | identical |
| `usr/bin/check` | identical |
| `usr/bin/write` | identical |
| `usr/bin/start_tune` | identical |
| `usr/bin/config-las-spi` | identical (`5f42be1d13a52886aced6b9e63111198`) |
| `etc/vxtune/cal-limits.scm` | identical (`4f9ea2778e31dfbb5f86318f740933d9`) |
| `etc/vxtune/mod-cal-limits.scm` | identical (`fa103e0402489334573b9a4199517a2c`) |
| `usr/bin/vxtune` | **differs** — `a31afa0f…` vs `f8f5eedb…`, both 3,066,108 B |

[READ, md5 of both trees]

The scripts and the limits data froze in 2019; the engine underneath them did
not. `vxtune` is the same *size* in both releases and a different *hash*.

### 1.3 Everything that invokes `vxtune`

`grep -rl vxtune` over the v1.8.2 rootfs returns exactly: the five scripts, the
binary itself, `usr/lib/chicken/8/vxtune.setup-info`, and `etc/init.d/S42sc`.
[READ]

`S42sc` line 4 is the one non-factory consumer: [READ]

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 \
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.2.1.bin \
  --vxdb=/var/tuning.vxtune \
  --vcfw=/usr/share/xmosfw/app_las_v2.2.2.bin --vcfv=33686271 --temp \
  --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 $1
```

`--vxdb=/var/tuning.vxtune` — **the directory these scripts write is the
directory the running synth engine reads at every boot.** That is the whole
reason they matter. [READ]

### 1.4 What `-c vc` actually connects to

`/etc/hosts` in the v1.8.2 rootfs is two lines: [READ]

```
127.0.0.1 localhost
203.0.113.2 vc
```

Every `vxtune` invocation in all five scripts passes `-c vc`. `vc` is a hostname
that resolves to **203.0.113.2** — the far side of the cdc_ether link, i.e. the
live voice-card bus. `vxtune`'s option doc for that flag is `connect` /
"Target address (required)" at 0x251ead–0x251efc. [READ]

So `-c vc` is not a mode selector or a card-class name. It is a network address,
and it is the address the project rules forbid touching. Running any of these
scripts *is* an instrument write.

The UDP port `vxtune` uses for `vc` is **[UNKNOWN]** — no port literal appears
in the binary's strings; it is presumably a default inside the las-comm
library. `start_tune` names ports explicitly for a *different* tool
(`lassvc -t 203.0.113.2:7770 -p 203.0.113.2:9100`, line 17). [READ]

---

## 2. `open_ladder` — the unattended eleven-step sequence

2,195 bytes, 90 lines. Structure: [READ]

- L4 `export TERM=xterm`
- L6–11 a `ctrl_c()` function and `trap ctrl_c SIGINT` — the *only* way out
- L15 `config-las-spi xmos`, then `sleep 3`
- L19–83 eleven `vxtune cal` invocations, each preceded by an `echo` and
  `sleep 2`, each followed by `sync`
- L87 `vxtune write -c vc -f /var/tuning.vxtune`, then `sync`

Every calibration line is literally: [READ, L21/27/33/39/45/51/57/63/69/75/81]

```
vxtune cal --cal-op <OP> -c vc -f /var/tuning.vxtune --force
```

| # | line | `--cal-op` | the script's own label (L19–79) |
|---:|---:|---|---|
| 1 | 21 | `oscvca` | "Flashing Osc VCA calibration (use ENTER to skip)" |
| 2 | 27 | `ladf` | "Ladder Cutoff calibration" |
| 3 | 33 | `gldr` | "Ladder VCA calibration" |
| 4 | 39 | `rmvca` | "Ring Mod VCA calibration" |
| 5 | 45 | `oscvca` | "Osc VCA calibration" |
| 6 | 51 | `gsvf` | "SVF VCA calibration" |
| 7 | 57 | `svf1` | "SVF1 calibration" |
| 8 | 63 | `svf2` | "SVF2 calibration" |
| 9 | 69 | `ovca` | "Main L/R VCA calibration" |
| 10 | 75 | `svca` | "Send 1/2 VCA calibration" |
| 11 | 81 | `vxnoise` | "Noise VCA calibration" |

[READ] all rows.

Eleven invocations, **ten distinct** operations — `oscvca` runs twice, first
(L21) under the label "Flashing", then again (L45) as an ordinary pass.

Five of the fifteen available operations are **absent**: `extin`, `ladr`,
`ladhp`, `biasfa`, `biasfb`. [READ, by set difference against §4.1]

The name is a service procedure, not a description of the audio path: it is what
you run **after opening the ladder filter**, i.e. after physically servicing a
voice card. `ladf` and `gldr` (the ladder's own cutoff and VCA) are steps 2 and
3, immediately after the XMOS cycle. [INFERRED, from the ordering and the name;
no Moog service document is in this corpus]

The final `vxtune write` at L87 carries **neither `--cal` nor `--tune`**, so it
pushes both calibration and tuning data. Contrast `run_process` L98, which
passes `--cal`. [READ; see §6.3]

---

## 3. `run_process` — the interactive menu

2,050 bytes, 102 lines, no `trap`, no `set -e`. Three prompts, in order: [READ]

**Prompt 1 (L4–22)** prints the numbered table and reads `$choiceone`. The table
verbatim, L5–19:

```
1. oscvca      13. ladf       19. gldr
7. rmvca       14. ladr       20. ovca
8. extin       15. ladhp      22. svca
9. svf1        16. biasfa     24. vxnoise
11. svf2       17. gsvf
                18. biasfb
```

L24–72 is a fifteen-arm `if/elif` chain mapping each number to `process="<name>"`;
anything else prints "Please enter a number from the list" and `exit 1`. [READ]

**Prompt 2 (L74–89)** reads `$voicenum`:

```
L78  if [ $voicenum == "a" ]                       -> all voices
L81      vxtune cal --cal-op $process -c vc -f /var/tuning.vxtune --force
L82  elif [ $voicenum -ge 0 2>/dev/null -a $voicenum -le 15 2>/dev/null ]
L85      vxtune cal --cal-op $process -c vc -f /var/tuning.vxtune --force -v $voicenum
```

[READ] The bound is `0..15` inclusive — sixteen voices, per-voice addressable.
The two `2>/dev/null` redirections inside the `[ ]` are the idiom for swallowing
bash's "integer expression expected" on non-numeric input; they are recognised
as redirections of the whole `[` command, so the test still evaluates as
`[ $voicenum -ge 0 -a $voicenum -le 15 ]`. [INFERRED, standard bash parsing]

**Prompt 3 (L92–102)** — and this is the one that matters:

```
L91  echo "Calibration completed"
L92  echo "Would you like to write this calibration data to data to the vX (y/n)?"
L94  read choice
L96  if [ $choice == "y" ]
L98      vxtune write -c vc -f /var/tuning.vxtune/ --cal
```

[READ] The calibration at L81/L85 has **already run** by the time this question
is asked. See §6.

(L92 contains a verbatim typo, "to data to", in the shipped file. [READ])

---

## 4. `check` — one line, no arguments, no confirmation

115 bytes, 4 lines, entire body: [READ]

```
#!/bin/bash
#Christian Stryffeler - (c) Moog Music Inc. 2019

vxtune cal --cal-op gsvf -c vc -f /var/tuning.vxtune/
```

Three properties worth stating separately:

- It **takes no arguments and reads no input.** `check --help`, `check -n`,
  `check --dry-run` all run the same SVF VCA gain calibration against
  203.0.113.2. This is the concrete script behind the standing project rule.
  [READ]
- It is the only one of the five that **omits `--force`.** [READ]
- It never writes to the voice cards — there is no `vxtune write`. [READ]

Because `--force` is documented as "Force given operation(s) to run, overwriting
previous results" (0x251d1a, §6.1), the absence of `--force` means `check`
should *skip* `gsvf` on a voice that already has a `gsvf` result, and the
`cal-have-gsvf?` predicate (0x252f9e) is the gate. So on a calibrated
instrument `check` is plausibly close to a no-op. [INFERRED — the option doc and
the predicate's existence are [READ]; that the gate is consulted on this path is
not proven from the binary, and I did not disassemble the dispatch.] Do not
treat this as a safety guarantee.

### 4.1 `run_process`'s menu is the real `--cal-op` vocabulary

`vxtune` contains fifteen "already done?" predicates: [READ, `strings` of
`usr/bin/vxtune`, region cited at 0x252f2e onward]

```
cal-have-oscvca?  cal-have-rm?         cal-have-extin?
cal-have-svf1?    cal-have-svf2?       cal-have-ladf?
cal-have-ladr?    cal-have-ladhp?      cal-have-biasfa?
cal-have-gsvf?    cal-have-biasfb?     cal-have-gldr?
cal-have-main-vcas?  cal-have-send-vcas?  cal-have-noise?
```

Set-map them onto `run_process`'s fifteen menu entries — `rm`↔`rmvca`,
`main-vcas`↔`ovca`, `send-vcas`↔`svca`, `noise`↔`vxnoise` — and the
correspondence is **exact and total, in both directions**. [READ for both lists;
INFERRED for the four name equivalences, which follow from `open_ladder`'s own
labels: `ovca` = "Main L/R VCA", `svca` = "Send 1/2 VCA", `vxnoise` = "Noise
VCA", `rmvca` = "Ring Mod VCA".]

The seven implementation functions are fewer than fifteen because several
operations share one: [READ]

```
cal-oscvca  cal-noise  cal-svf  cal-main-vcas  cal-send-vcas
cal-svfbias  cal-ladbias
```

`biasfa → cal-svfbias`, `biasfb → cal-ladbias` — independently confirming
`docs/firmware/calibration.md` §9.2's identification of `fa` as the SVF and `fb`
as the ladder. [READ, agrees with prior work]

### 4.2 `vxtune`'s own `--cal-op` help is stale

At 0x252aa5, verbatim: [READ]

```
Calibration operation to perform: oscvca, ladf, ladr, svf1f, svf1r, svf2f,
svf2r, fvca, ovca, flhp, rm, extin, vxnoise
```

Thirteen names. Compare the fifteen that actually dispatch (§4.1):

| in the help but **not** dispatchable | dispatchable but **not** in the help |
|---|---|
| `svf1f`, `svf1r`, `svf2f`, `svf2r` | `svf1`, `svf2` |
| `fvca` | `gsvf`, `gldr` |
| `flhp` | `ladhp` |
| `rm` (scripts pass `rmvca`) | `biasfa`, `biasfb` |

[INFERRED, by comparing the two [READ] lists.] `svf1f/svf1r/svf2f/svf2r`,
`fvca` and `flhp` are names from the *storage* layer — `svf1f`, `svf1r`,
`svf2f`, `svf2r` are all real `las-voxcal` fields and real `/cal/` addresses
(§5.1) — that were never renamed in the help text when the dispatch names
changed. `run_process`, not `--help`, is the accurate documentation of this
tool. That is a genuinely useful thing to know and it is the strongest reason to
catalogue these scripts.

---

## 5. Decoding the sparse numbering

Present: `1, 7, 8, 9, 11, 13, 14, 15, 16, 17, 18, 19, 20, 22, 24`.
Absent: `2, 3, 4, 5, 6, 10, 12, 21, 23`. Fifteen present, nine absent, 24 total.
[READ, `run_process` L5–19]

### 5.1 The field order, read directly

`las-sc` holds one contiguous NUL-separated run of interned symbols — the
`las-voxcal` record's field names — at **0x218761–0x218803**: [READ,
`xxd -s 0x218700 -l 288 usr/bin/las-sc`]

```
o1  p1  o2  p2  o3  p3  rm  extin  svf1f  svf1r  svf2f  svf2r
ladf  ladr  ladhp  bias-gsvf  gsvf  bias-gldr  gldr
mainl  mainr  sub1  sub2  fm  noisecw  noiseccw
```

Twenty-six fields. This reproduces, from the binary and independently, the
`VOXCAL` list that `docs/firmware/calibration.md` §17 uses in its `s11n.py`
decoder. [READ]

Corroborating `/cal` OSC addresses in `vxtune` (77 distinct `/cal/...` literals):
`/cal/o1`, `/cal/o2`, `/cal/o3`, `/cal/p1`, `/cal/p2`, `/cal/p3`, `/cal/rm`,
`/cal/extin`, `/cal/svf1f`, `/cal/svf1r`, `/cal/svf2f`, `/cal/svf2r`,
`/cal/ladf`, `/cal/ladr`, `/cal/gsvf`, `/cal/gldr`, `/cal/mainl`, `/cal/mainr`,
`/cal/aux1`, `/cal/aux2`, `/cal/noisecw`, `/cal/noiseccw`, `/cal/biasfa`,
`/cal/biasfb`, `/cal/hpf`, `/cal/decay`. [READ]

Note `sub1`/`sub2` in the record vs `aux1`/`aux2` on the wire — the same pair of
send VCAs under two names. [INFERRED, from `open_ladder`'s "Send 1/2 VCA" label
on `svca` plus both name pairs appearing exactly twice.]

### 5.2 The mapping

Take the 1-based position of each menu name's *first* field in that 26-list:

| menu # | menu name | field at that position | span it opens |
|---:|---|---|---|
| 1 | `oscvca` | `o1` | 1–6 (`o1 p1 o2 p2 o3 p3`) |
| 7 | `rmvca` | `rm` | 7 |
| 8 | `extin` | `extin` | 8 |
| 9 | `svf1` | `svf1f` | 9–10 (`svf1f svf1r`) |
| 11 | `svf2` | `svf2f` | 11–12 (`svf2f svf2r`) |
| 13 | `ladf` | `ladf` | 13 |
| 14 | `ladr` | `ladr` | 14 |
| 15 | `ladhp` | `ladhp` | 15 |
| 16 | `biasfa` | `bias-gsvf` | 16 |
| 17 | `gsvf` | `gsvf` | 17 |
| 18 | `biasfb` | `bias-gldr` | 18 |
| 19 | `gldr` | `gldr` | 19 |
| 20 | `ovca` | `mainl` | 20–21 (`mainl mainr`) |
| 22 | `svca` | `sub1` | 22–23 (`sub1 sub2`) |
| 24 | `vxnoise` | **`fm`** | — mismatch |

**Fourteen of fifteen land exactly, and every one of the nine gaps is explained**
as the second-or-later field of a multi-field operation: 2–6 are `oscvca`'s
remaining five oscillator VCAs, 10 and 12 the reverse halves of the two SVFs, 21
the right main VCA, 23 the second send. [INFERRED — the field run and the menu
are both [READ]; the positional identification is my reasoning.]

Three independent cross-checks support it: `biasfa`→`bias-gsvf` and
`biasfb`→`bias-gldr` fall out of the positions *and* agree with the
`cal-svfbias`/`cal-ladbias` implementation names (§4.1); `ovca`→`mainl mainr`
agrees with `open_ladder`'s "Main L/R VCA" label; `svca`→`sub1 sub2` agrees with
"Send 1/2 VCA". [READ for all three labels]

### 5.3 The one that does not fit

`vxnoise` is listed at **24**, but position 24 is `fm`; the noise fields are
`noisecw` at 25 and `noiseccw` at 26. **[UNKNOWN]** — I could not establish why.

The tempting explanation is that the numbering came from a list that omitted
`fm`, which would put `noisecw` at 24 and leave positions 1–23 untouched. I
tested that and **it does not hold up**: `las-voxcal-fm` and `las-voxcal-fm-set`
are both present in `vxtune` (4 occurrences) and in `las-sc` (4). [READ] `fm` is
a real field with real accessors, so "the list without `fm`" is not a list the
firmware appears to hold.

Remaining candidates, none of which I can decide from this corpus:
a 2019-era field order that differed from the shipped one; an off-by-one in the
script; or a source table (a Moog test fixture or service document) that is not
in the firmware at all. `run_process` is the only artefact here that carries the
numbers, and nothing in the rootfs enumerates them. I looked for a numbered job
table in `cal/jobs.scm`; its symbols are a generic concurrency job controller
(`make-job-controller`, `start-job`, `exec-job`, `job-log-entry-*`), not a
process index. [READ]

Do not present the `vxnoise = 24` cell as decoded.

---

## 6. The write / no-write boundary

Three distinct places state can be committed. They are not the same, and the
scripts do not treat them the same.

### 6.1 Boundary A — the analog hardware, during `vxtune cal`

`vxtune cal` is not a read. It drives the voice-card analog path and measures
it. Evidence: the `/cal/*` OSC send sites, each paired with a log line —
`/cal/biasfa` "sending biasfa data" (0x24fc43/0x24fc54), `/cal/ladf` "sending
ladf data" (0x24fd37/0x24fd46), `/cal/gsvf`, `/cal/gldr`, `/cal/ladr`,
`/cal/extin`, `/cal/mainl`, `/cal/mainr`, `/cal/noisecw`, `/cal/noiseccw`, and
the `svf1f/svf1r/svf2f/svf2r` quartet at 0x24fc97–0x24fd2f. [READ]

`--force` is documented at **0x251d1a**, verbatim: [READ]

```
Force given operation(s) to run, overwriting previous results
```

`--force-all` at **0x251cb3**: "Force all operations to run, including
requirements". [READ]

**Every `vxtune cal` in `open_ladder` and `run_process` passes `--force`.**
[READ, 11 + 2 call sites] Only `check` omits it.

### 6.2 Boundary B — the on-disk database, `/var/tuning.vxtune`

At **0x2517b1**, the doc for the `-f` / `Database file` option's absence: [READ]

```
No database file -- data will be discarded
```

The contrapositive is the point: **with `-f`, results are not discarded — they
are written.** All five scripts pass `-f /var/tuning.vxtune`. So `vxtune cal`
alone, with no `vxtune write` anywhere near it, already mutates the file that
`S42sc` feeds to `las-sc` as `--vxdb` at every boot (§1.3). [INFERRED from the
[READ] option doc and the [READ] `S42sc` argv]

Related: "Cannot write to the vxtune database at this path" at 0x292d4b. [READ]

This is the boundary that `run_process`'s prompt does **not** protect.

### 6.3 Boundary C — the voice cards' own persistent storage, via `vxtune write`

Two OSC verbs, used only in the write path: [READ]

| offset | string |
|---|---|
| 0x250181 | `/save_tuning` |
| 0x250194 | `Sending write tuning command` |
| 0x250132 | `Sent write tuning command` |
| 0x250151 | `Tuning data write failed: [` |
| 0x2501f4 | `/save_cal` |
| 0x250203 | `Sending write cal command` |
| 0x2501b6 | `Sent write cal command` |
| 0x2501d2 | `Cal data write failed: [` |
| 0x250222 | ` in write process` |

The three selectors: [READ]

| flag | doc string | offset |
|---|---|---|
| `--tune` | "Send only tuning data" | 0x251fa8 |
| `--cal` | "Send only calibration data" | 0x251fe7 |
| `--no-send` | "Do not send data, just send write command" | 0x251f4e |

With neither `--tune` nor `--cal`, both sets go. [INFERRED, from "Send **only**"
in both doc strings.]

How the scripts use it:

| script | write invocation | scope |
|---|---|---|
| `open_ladder` L87 | `vxtune write -c vc -f /var/tuning.vxtune` | cal **and** tuning, unconditional |
| `run_process` L98 | `vxtune write -c vc -f /var/tuning.vxtune/ --cal` | cal only, gated on `y` |
| `write` L9/11/13 | `--tune` / `--cal` / neither | operator picks |
| `check` | none | — |
| `start_tune` | none (uses `auto-tune`) | — |

[READ]

### 6.4 The consequence

For `run_process`, the operator-visible sequence is:

```
choose process -> choose voice -> [CALIBRATION RUNS, --force] -> "write? (y/n)"
```

Answering **`n` reverts nothing.** Boundary A has been crossed (the analog pass
ran) and Boundary B has been crossed (`--force` overwrote the previous result in
`/var/tuning.vxtune`). `n` declines Boundary C only. A subsequent reboot will
load the overwritten database, because that is what `S42sc --vxdb` does.
[INFERRED, from §6.1–6.3; each component is [READ], the composition is mine.]

For `open_ladder` there is no prompt at all: eleven forced calibrations and a
full cal+tuning write, start to finish, from one command with no arguments.
[READ]

---

## 7. Defects and traps in the scripts themselves

### 7.1 `open_ladder` promises a skip it does not implement

Lines 19–21, verbatim and consecutive: [READ]

```
echo "Flashing Osc VCA calibration (use ENTER to skip)..."
sleep 2
vxtune cal --cal-op oscvca -c vc -f /var/tuning.vxtune --force
```

There is **no `read`** anywhere in `open_ladder` — the file contains zero `read`
statements. [READ] The operator is told ENTER skips the step; pressing ENTER
does nothing and the calibration proceeds. The two-second `sleep` is the only
window, and the only thing in it that works is Ctrl+C, which the `trap` at L11
turns into "Open Ladder process cancelled by user." and `exit 1`. [READ]

This is almost certainly a leftover from a version that did prompt. Whatever the
history, the shipped file misinforms the operator about its own abortability.

### 7.2 Ctrl+C during a `vxtune write` is not clean

`open_ladder`'s trap exits the *script*. It cannot unwind a `vxtune write`
already in flight to the voice cards, and the failure strings "Cal data write
failed: [" / "Tuning data write failed: [" (0x2501d2, 0x250151) show the
transfer is one that can fail partway. [READ for the trap and the strings;
INFERRED that an interrupted write can leave a card partially updated — I have
not read the card-side commit logic and cannot say whether `/save_cal` is
atomic.]

### 7.3 `start_tune` leaves the instrument headless

L47–79 loop until `las-watchdog`, `las-sc` and `las-frontend` are all dead,
`killall`-ing each: [READ]

```
if [ $watchdog = 0 ]; then killall las-watchdog; ...
if [ $sc = 0 ]; then killall las-sc; ...
if [ $frontend = 0 ]; then killall las-frontend; ...
```

Nothing in the remaining 18 lines restarts them, and the script ends at L97 with
a `cp`. [READ] After `start_tune`, the synth engine and the UI are down until
the machine is rebooted or the init scripts are re-run by hand.

### 7.4 `start_tune` deletes tuning data on a `y`

L20–38: if `/var/tuning.vxtune` exists **and** `/var/tuning.vxtune/v0` exists,
it warns "continuing will overwrite", reads one character, and on `[Yy]` does
`rm -r /var/tuning.vxtune`. [READ] This is the only `rm -r` in the five scripts.
It is guarded by a prompt, unlike everything in §6.

L40–46 then recreates the directory and seeds it:

```
mkdir /var/tuning.vxtune
echo '(vxtune-db 3)' >/var/tuning.vxtune/vxtune-db
```

[READ]

### 7.5 The seed line does not match what is on the instrument

This unit's own `vxtune-db`, from `captures/backup/calibration-20260907-222301.tar.gz`:

```
00000000: 2876 7874 756e 652d 6462 2033 29         (vxtune-db 3)     13 bytes
```

What `start_tune` L43's `echo` writes:

```
00000000: 2876 7874 756e 652d 6462 2033 290a       (vxtune-db 3).    14 bytes
```

[READ, both — `xxd` of the extracted file and of `echo '(vxtune-db 3)'`]

The shipped file has **no trailing newline**; `echo` adds one. So the
`vxtune-db` on this instrument was not left as `start_tune` wrote it — `vxtune`
itself rewrote it, which is consistent with the `vxtune-db-open` /
`vxtune-db-close` pair at `cal/vxtune.scm:3322` and `:3402–3549`. [INFERRED;
the byte counts and the symbol names are [READ]] `start_tune`'s `echo` is a
bootstrap that the tool subsequently overwrites. The schema version is **3**.

### 7.6 A claim I tested and withdrew

I expected `start_tune` to exit prematurely: L16–17 tell the operator to press
Ctrl+C to end the `lassvc` noise-level step, but a `trap ctrl_c SIGINT` is armed
at L12, and Ctrl+C in a terminal goes to the whole foreground process group. If
bash ran that trap after `lassvc` returned, the script would `exit 1` before
reaching the tuning phase at L81.

I built a stand-in (a parent with the same trap, a child that handles SIGINT and
exits) and signalled both. **The trap did not fire and the parent continued past
the child** — bash 3.2.57 on this Mac. The hypothesis did not reproduce, so I am
not asserting it. Whether the device's bash behaves the same is **[UNKNOWN]**
and I have not established it matters. Recorded so it is not re-derived and
shipped as a finding by someone who does not test it.

### 7.7 Minor

- `run_process` L92 ships the typo "write this calibration data to data to the
  vX". [READ]
- Unquoted `$choiceone` (L24…) and `$voicenum` (L78, L82) throughout
  `run_process`. Empty input makes `[ == 1 ]` a bash syntax error, which is
  false, so the chain falls to the `else` and exits 1. Not exploitable from a
  local interactive prompt. [INFERRED, standard bash `[` semantics]
- `run_process` L98 and `check` L4 pass `-f /var/tuning.vxtune/` **with** a
  trailing slash; `open_ladder` L87 and `start_tune` L86 pass it without. It is a
  directory in both cases, so this is cosmetic. [READ; the directory-ness is
  [READ] from §8]

---

## 8. What `/var/tuning.vxtune` actually is

Not in the shipped rootfs — `var/` in the v1.8.2 tree has no `tuning.vxtune`.
[READ] It is generated on the instrument, which is consistent with the settled
project position that calibration data is regenerable on the unit.

From this unit's backup, **65 files**: [READ]

```
vxtune-db                      1   the 13-byte (vxtune-db 3) schema stamp
v0 … v15                      16   one las-vox + las-voxcal per voice, ~1408 B
v{0..15}-o{1,2,3}             48   one las-osc + four las-phase per oscillator, ~57 kB
```

1 + 16 + 48 = 65. This is direct confirmation of **16 voices** and **3
oscillators per voice**, matching `run_process`'s `-v 0..15` bound (L82) and
`vxtune`'s "Oscillator number (0..2)" (0x251d9a). [READ]

`start_tune`'s existence guard at L20 tests exactly `-d /var/tuning.vxtune -a -f
/var/tuning.vxtune/v0` — and `v0` is present in the backup. [READ]

The head of `v0` shows the nesting: [READ, `xxd`]

```
00000000: 0506 0000 080d 0407 0000 426c 6173 2d76  ..........Blas-v
00000010: 6f78 0301 0000 0008 0808 051b 0000 080d  ox..............
00000020: 040a 0000 426c 6173 2d76 6f78 6361 6c05  ....Blas-voxcal.
00000030: 0600 0008 0d04 0a00 0042 6c69 6e65 6172  .........Blinear
00000040: 2d63 616c 0408 0000 5500 0000 0000 0000  -cal....U.......
```

`las-vox` containing `las-voxcal` containing `linear-cal`. The serialization
format itself is already covered by `docs/firmware/calibration.md` §17 and I did
not re-derive it.

---

## 9. `/etc/vxtune/cal-limits.scm` — the targets these scripts calibrate to

`vxtune` names this path at **0x251829**, with a build-relative fallback
`cal/cal-limits.scm` at 0x251849. [READ] It also embeds `/usr/bin/config-las-spi`
at **0x251861** — the tool shells out to the same script `open_ladder` and
`start_tune` call by hand. [READ]

The file defines three record types (`cal-targets` {max, maxt, min, mint},
`bias-target` {out-min, out-max, target, tol}, `minimize-p` {start-point, alpha,
precision}) and **two complete limit sets**, `old-lim` (L45–117) and `new-lim`
(L120–194). [READ]

`new-lim` is uniformly looser. Selected [READ] pairs:

| target | `old-lim` | `new-lim` |
|---|---|---|
| `ovca` min / mint | 0.00004 / 0.000005 | 0.00005 / 0.00005 |
| `svca` maxt | 0.005 | 0.010 |
| `extin` max | 0.0775 | `(* 2 0.0775)` |
| `rm` max | `(db->frac -9)` | `(* 2 (db->frac -9))` |
| `noise` max | `(db->frac -9)` | `(* 2.25 (db->frac -9))` |
| `gsvf` max / maxt | `(db->frac -9.0)` / 0.08 | `(* 1.6 (db->frac -9.0))` / 0.12 |
| `gldr` max / maxt | `(db->frac -9.0)` / 0.02 | `(* 2 (db->frac -9.0))` / 0.05 |
| `oscvca` max / maxt | `(db->frac -9.0)` / 0.02 | `(* 2 (db->frac -9.0))` / 0.05 |
| `bias-hp` target / tol | 0.36 / 0.01 | 0.64 / 0.005 |

`bias-hp` in `new-lim` carries a commented-out `target: 0.72` directly above the
live `target: 0.64` (L186–187). [READ]

**The last line of the file is `(define lim (make-limits))` (L196)** — which
binds `lim` to the `defstruct` *defaults*, not to `old-lim` and not to
`new-lim`. Both named sets are defined and neither is selected here. [READ]
Which one a given run uses is **[UNKNOWN]** from this file; `vxtune`'s option
table has `new-lim` and `old-lim` as symbols at 0x253536/0x253540 and a `--mod`
flag documented "Flag for VX Mods" at 0x251bd1, so the selection is made in the
binary. [READ for the symbols; the selection logic is not established.]

`mod-cal-limits.scm` is a *self-contained* variant: it carries its own `(use fmt
defstruct)` and its own `defstruct` declarations with the limits inlined as
field defaults, ending in the same `(define lim (make-limits))` — so there `lim`
*does* get the values. It prints "mod-cal-limits.scm loaded" on load (L5). Its
`bias-hp` target is 0.47, a third value distinct from both 0.36 and 0.64. [READ]
Its path does **not** appear in `vxtune`'s strings. [READ] How it is loaded is
**[UNKNOWN]**.

Note the structural difference: in `cal-limits.scm` the `defstruct` forms are
all commented out (L4–43) — it expects the struct definitions to already exist,
i.e. it is `load`ed into a running `vxtune`. [READ]

---

## 10. `config-las-spi` — the bus handover both sequencers open with

1,047 B, `#!/bin/sh`, `set -e`, no Moog byline. Called as `config-las-spi xmos`
by `open_ladder` L15 and `start_tune` L81, and named inside `vxtune` itself
(0x251861). [READ]

Two functions, `config_spi_xmos` and `config_spi_som`, each writing IOMUXC
registers with `devmem` and toggling the XMOS reset line: [READ]

| register | comment in file | `xmos` value | `som` value |
|---|---|---|---|
| `0x20e0244` | KEY_COL0 | 5 | 0 |
| `0x20e0248` | KEY_COL1 | 5 | 0 |
| `0x20e0258` | KEY_ROW0 | 5 | 0 |
| `0x20e025c` | KEY_ROW1 | 5 | 5 |
| `0x20a8004` | GPIO4_GDIR | `0x40008020` | `0x40008220` |

Reset line, `xmos` path (L20–21): `echo 0 > /sys/class/leds/XMOS_RESET_N/brightness`
then `echo 1`. The `som` path (L30) writes only `0` — it **holds** the XMOS in
reset. [READ]

The file's own comments state the purpose: `xmos` "forces SPI1 pins to be GPIO
inputs so that XMOS may control the bus"; `som` "returns SPI1 pins to original
function and places XMOS in reset so that SOM may control the bus". [READ]

With no argument it prints "Please pass {xmos} or {som}" and exits 1 — the only
one of these tools that validates its arguments. [READ, L46–49]

This is the mechanism behind the already-recorded observation that `open_ladder`
left `/v/voices` reporting `-1`: L15 resets the XMOS out from under a running
`las-sc`. [INFERRED; the reset is [READ] here, the `-1` symptom is [READ] from
`docs/INTERNAL-DO-NOT-DISTRIBUTE.md:193`.]

---

## 11. `start_tune` and `write`, briefly

**`start_tune`** (2,012 B, 97 lines) is the top of the factory chain: noise-level
calibration via `lassvc` (L17) → optional destroy/recreate of the database
(L20–46) → kill the three `las-*` processes (L47–79) → `config-las-spi xmos`
(L81) → **`vxtune auto-tune -c vc -f /var/tuning.vxtune`** (L86) → back up the
result to `/root/$(date +%m.%d.%y)_tune` (L95). [READ]

`auto-tune` is a different operation from `cal`; `vxtune`'s operation symbols
include `auto-tune`, `auto-cal` and `just-tune` (0x253511–0x253528). [READ]
`start_tune` never calls `vxtune write`, so it stops at Boundary B. [READ]

**`write`** (511 B, 19 lines) is the standalone Boundary-C tool: one prompt,
`t`/`c`/`a` → `--tune` / `--cal` / neither. [READ] It prints "Data successfully
written to the vX" unconditionally at L19, outside the `if`, with no check of
`vxtune`'s exit status — so it reports success even when `vxtune` reports "Cal
data write failed". [READ]

---

## 12. `vxtune` option surface, as it bears on these scripts

Only the flags the five scripts use or that change what they do. All [READ] at
the stated offsets.

| flag | doc string | offset |
|---|---|---|
| `connect` (`-c`) | `Target address (required)` | 0x251ead |
| — (`-f`) | `Database file` | 0x251c6b |
| `force` | `Force given operation(s) to run, overwriting previous results` | 0x251d1a |
| `force-all` | `Force all operations to run, including requirements` | 0x251cb3 |
| `voice` (`-v`) | `Voice number (1..)` | 0x251e59 |
| `nvoices` | `Number of voices present in system.` | 0x251def |
| — | `Oscillator number (0..2)` | 0x251d9a |
| `cal-op` | the stale list, §4.2 | 0x252aa5 |
| `tune` | `Send only tuning data` | 0x251fa8 |
| `cal` | `Send only calibration data` | 0x251fe7 |
| `no-send` | `Do not send data, just send write command` | 0x251f4e |
| `mod` | `Flag for VX Mods` | 0x251bd1 |
| `quiet` | `Quiet Mode` | 0x251c1f |
| `no-results` | `Flag to turn off Display Results screen` | 0x251907 |
| `log-file` | `Filename for vx test log output` | 0x251b3d |

Default log path `/var/log/vxtune-log` (0x2517e2), fallback `./vxtune-log`
(0x2517fa). [READ] Anyone running these scripts leaves a trail there.

Two internal inconsistencies in `vxtune`'s own text, both [READ]:

- `-v` help says **"Voice number (1..)"** (0x251e59), but the runtime error is
  **"invalid voice number -- must be from 0 to "** (0x25148c) and `run_process`
  bounds-checks **0..15** (L82). The help is the odd one out.
- The CLI says **"Oscillator number (0..2)"** (0x251d9a); the database-facing
  doc says **"oscnr - oscillator number: 1, 2, or 3"** (0x250278). The on-disk
  files are `v0-o1`, `v0-o2`, `v0-o3` (§8), i.e. 1-based.

---

## Conflicts

Reported, not fixed, per instruction. I did not edit any existing document.

1. **My own assignment brief is wrong on one point.** It states "`open_ladder`
   and `run_process` occur 0 times across all 18 reports." `run_process` does
   occur zero times, as do `check` and `write`. **`open_ladder` does not** — it
   appears at `docs/INTERNAL-DO-NOT-DISTRIBUTE.md:171,188,193` and
   `docs/MOOG-ONE-INTERNALS.md:39,44`. `start_tune` appears at
   `docs/INTERNAL-DO-NOT-DISTRIBUTE.md:170,189`, `docs/MOOG-ONE-INTERNALS.md:40`
   and `docs/firmware/calibration.md:51,115`. [READ, `grep -rn` over `docs/`]
   The genuinely unread files are `run_process`, `check` and `write`.

2. **`docs/firmware/calibration.md` §"item 7" (~line 1576)** states the
   `las-voxcal` accessor order in `vxtune` "omits `fm`". `las-voxcal-fm` and
   `las-voxcal-fm-set` are both present in `vxtune` (4 string occurrences) and
   in `las-sc` (4). [READ] The 26-field interned run at `las-sc` 0x218761
   includes `fm` at position 24. The list quoted in that item has 25 names and
   is missing `fm`; the omission looks like an artefact of how that list was
   collected. This matters because "omits `fm`" is the most attractive
   explanation for the `vxnoise = 24` anomaly in §5.3, and it does not survive.

3. **`docs/firmware/calibration.md:51`** lists the files that are byte-identical
   between 1.5.0 and 1.8.2 as "`/etc/vxtune/cal-limits.scm`, `mod-cal-limits.scm`,
   `config-las-spi` and `start_tune`". Correct as far as it goes, and I confirm
   all four. It should also include **`open_ladder`, `run_process`, `check` and
   `write`**, which are likewise byte-identical (§1.2). [READ]

4. **`docs/firmware/calibration.md` §9.2** reproduces the `--cal-op` help string
   at 0x252aa5 as the `--cal-op` list, graded [READ]. The quotation is accurate,
   but the section does not note that the list **does not match the fifteen
   operations `vxtune` actually dispatches** (§4.2). A reader would take
   `svf1f`, `fvca`, `flhp` and `rm` to be usable `--cal-op` values; the scripts
   pass `svf1`, `gsvf`/`gldr`, `ladhp` and `rmvca` instead. The same section's
   predicate list is correct and complete — my own first pass missed
   `cal-have-main-vcas?` and `cal-have-send-vcas?` because my regex excluded
   hyphens; `calibration.md` had them right.

5. **`docs/DANGER.md:26`** describes "a user-runnable voice-card calibration,
   added in firmware **1.5.0**". Not contradicted, but worth setting beside:
   these five *factory* scripts are dated 1/7/19–3/5/19 in their own bylines and
   are byte-identical in 1.5.0 and 1.8.2, so the factory path predates and is
   independent of the user-facing screen. [READ] They are also not mentioned in
   `DANGER.md`, which reaches Boundary C (`vxtune write … [--tune|--cal]`,
   line 49) but not Boundary B.

6. **Housekeeping, not a documentation conflict:** the extracted rootfs
   directories contain `.omc/` state directories written by this project's own
   tooling — e.g. `captures/firmware-1.8.2/rootfs-1.8.2/.omc/state/sessions/…`,
   and likewise under `docs/arch/`, `docs/firmware/` and `captures/backup/`.
   They are not Moog artefacts and should be excluded from any file-level diff
   or hash of the rootfs. [READ, directory listing]

---

## Unexplored

- I did not disassemble `vxtune`'s `dispatch-cal-op` (`cal/vxtune.scm:831,837`,
  symbol at 0x2d02cb) to confirm the `--force` / `cal-have-*?` gate empirically.
  §4 and §6.1 rest on option doc strings and symbol presence.
- The source of `run_process`'s numbering for `vxnoise = 24` (§5.3).
- Which of `old-lim` / `new-lim` a given run selects, and how
  `mod-cal-limits.scm` is loaded (§9).
- The UDP port `vxtune` uses for `-c vc` (§1.4).
- `/cal/hpf` and `/cal/decay` appear in the `/cal` namespace but correspond to no
  `--cal-op` and no `las-voxcal` field. Not investigated.
- `vxtune`'s other operations — `auto-cal`, `just-tune`, `tcal`, `tcode0/1/f`,
  `monitor`, `db-csv`/`csv-db`, `gen-c-freq-tables`, `autor-curve`, `lf-curve`.
  Only `cal`, `write` and `auto-tune` are reachable from these five scripts.
- The v1.5.0↔v1.8.2 `vxtune` binary delta (same size, different hash). Prior work
  reports the CHICKEN source-line map is identical; I did not locate the changed
  bytes.

---

## Validation plan — READ-ONLY, for a human to run

Nothing here writes, and nothing invokes `vxtune`, `check`, `open_ladder`,
`run_process`, `write`, `start_tune` or `config-las-spi`. Do not add `--help` to
any of those names: `check` ignores argv entirely and `vxtune`'s subcommands are
positional.

On a workstation, against the extracted rootfs — these reproduce every [READ]
in this document and touch no instrument:

```sh
R="captures/firmware-1.8.2/rootfs-1.8.2"

# §1.1 the five scripts and their bylines
grep -ril "moog music" "$R/usr/bin" | xargs -I{} sh -c 'echo "== {}"; sed -n 2p {}'

# §1.2 byte-identity across releases
for f in open_ladder run_process check write start_tune config-las-spi; do
  cmp -s "$R/usr/bin/$f" "captures/rootfs-1.5.0/usr/bin/$f" && echo "$f identical"
done

# §1.4 what "vc" resolves to
cat "$R/etc/hosts"

# §5.1 the 26-field las-voxcal run, read directly
xxd -s 0x218700 -l 288 "$R/usr/bin/las-sc"

# §4.1 the fifteen dispatchable operations
strings -a "$R/usr/bin/vxtune" | grep -oE 'cal-have-[a-z0-9-]+\?' | sort -u

# §4.2 the stale help string
strings -a -t x "$R/usr/bin/vxtune" | grep 'Calibration operation to perform'

# §6.1 / §6.3 the boundary strings
strings -a -t x "$R/usr/bin/vxtune" | grep -E 'Force given|No database file|/save_cal|/save_tuning|Send only'

# §7.1 open_ladder contains no read
grep -c '^[[:space:]]*read' "$R/usr/bin/open_ladder"   # expect 0

# §7.5 the seed-line byte mismatch
tar xzOf captures/backup/calibration-20260907-222301.tar.gz tuning.vxtune/vxtune-db | xxd
echo '(vxtune-db 3)' | xxd
```

On the instrument, if the owner wants live confirmation — read-only, one at a
time, and none of it is required for anything above:

```sh
cat /etc/hosts                                  # confirm 203.0.113.2 vc
ls -la /var/tuning.vxtune | head                # confirm 65 entries, v0..v15, *-o1..o3
xxd /var/tuning.vxtune/vxtune-db                # confirm 13 bytes, no trailing newline
md5sum /usr/bin/{open_ladder,run_process,check,write,start_tune}
ls -la /var/log/vxtune-log 2>/dev/null          # has vxtune ever run here?
cat /proc/cmdline                               # unrelated, but free while you are there
```

`ls -la /var/log/vxtune-log` is the interesting one: if that file is absent, no
`vxtune` operation has been run on this unit since the log path was introduced,
which would corroborate `calibration.md`'s finding that this instrument still
carries factory tuning data.
