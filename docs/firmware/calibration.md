<!-- docs/firmware/calibration.md -->
# Calibration and tuning

The `/cal` namespace, the seventeen voice-card calibrations, `vxcal.db`,
`tuning.vxtune`, `las-voxcal`, `linear-cal`, `config-las-spi`, and the
user-runnable routine.

**The instrument was not contacted at any point.** Everything below is static
analysis of files already on disk, plus the owner's own verified calibration
backup. Proposed live commands are confined to §16, are read-only, and were not
run.

## Grades

* **[READ]** — read directly out of a file. The file, and the byte offset or
  line, is cited.
* **[INFERRED]** — reasoning from what was read. The evidence is named.
* **[UNKNOWN]** — not established. Said so.

## Sources, and which are new

| source | status |
|---|---|
| `captures/firmware-1.8.2/rootfs-1.8.2` | the decrypted v1.8.2 root filesystem. **First read in this pass.** Contains `vxtune`, `lassvc`, `vxmon`, `vxtest`, `vxreport`, `vxping` and `/etc/vxtune/*.scm`, none of which were in the earlier harvest. |
| `captures/rootfs-1.5.0` | the v1.5.0 root filesystem, complete. Used for every version comparison below. |
| `captures/backup/calibration-20260907-222301.tar.gz` | **this instrument's own** `/var/cal` and `/var/tuning.vxtune`. 66 files, **all 66 md5-verified against `calibration-20260907-222301.md5` in this pass.** [READ] |
| `captures/arch-harvest/*` | the 1.5.0 binaries harvested live. `runtime-state.txt` not used (see `CAVEAT-runtime-state.md`). |

Offsets into ARM binaries are **file offsets** unless marked VMA.
`VMA = file offset + 0x10000`, verified from `las-sc`'s section table
(`.rodata` size 0x5e898 at VMA 0x1f0594, `.text` at VMA 0x11650). [READ]

---

## 0. Summary of what is new here

1. **The `tuning.vxtune` binary format is fully decoded.** It is CHICKEN Scheme's
   `s11n` serialisation; the encoding is documented in §5.2 and a working decoder
   is given in §17. All 65 files of the owner's backup parse to the last byte.
   This has not been done before on this project.
2. **`las-voxcal`'s 26 fields are now [READ] verbatim from the binary**, in
   declaration order, including `fm` — not inferred from symbol-table ordering.
   The field list appears as a contiguous run of interned symbols in `las-sc`'s
   literal blob at file 0x2187xx.
3. **The calibration subsystem did not change between 1.5.0 and 1.8.2.** The
   `/cal` address union is byte-identical (223 addresses); `vxtune`'s entire
   CHICKEN source-line trace map is identical line for line; and `las-sc`'s
   differs *only* in the build temp-directory prefix on three `sc/*.scm`
   files — every `cal/*`, `las/*`, `sc/sc.scm`, `mon/*` and `vxfw-lib.scm`
   line matches exactly. `/etc/vxtune/cal-limits.scm`, `mod-cal-limits.scm`,
   `config-las-spi` and `start_tune` are byte-identical files.
4. **`/cal:save`, `/cal:load`, `/cal:cal_default` are real, complete addresses.**
   `docs/arch/cal-dispatch.md` §6.3 left the spelling open. It is the colon form,
   and `/cal/save` and `/cal/load` exist alongside.
5. **`/load_cal` and `/load_tuning` are probably queries, not verbs** — the
   opposite of what `cal-dispatch.md` §6.3 assumes. See §11.2.
6. **This instrument has never had a `las-frontend` voice-card calibration run.**
   Its `vxcal.db` is empty of measurements; its tuning data is the factory
   `vxtune` "legacy" set. See §6.3.
7. `lassvc` is the **service-mode program** and owns the entire *system*
   calibration half of the namespace (CV in/out, expression, sustain, noise,
   panel, left-hand controller) that nothing in this repository had described.
8. The arity result in `cal-dispatch.md` is **independently reproduced** on the
   1.8.2 binary by a different method (§12.1), with one correction to that
   document's supporting detail.

---

## 1. The map

### 1.1 One calibration library, five programs

`las-sc`, `vxtune`, `lassvc`, `vxmon` and `vxtest` are five separate ARM
executables that **all statically link the same compiled CHICKEN Scheme
calibration library.** Each contains exactly **946** `cal/cal.scm:<line>:` trace
strings, **157** `cal/search.scm`, **121** `cal/vxtune-db.scm`, **100**
`cal/jobs.scm`, **360** `las/las-measure.scm`, **264** `las/las-oscl.scm`,
**107** `las/las-math.scm`, **68** `las/las-vox.scm`. [READ]

```
                     cal/cal.scm  search.scm  vxtune.scm  lassvc.scm  vxmon.scm
las-sc     2 499 540      946        157          –           –           –
vxtune     3 066 108      946        157        2862          –           –
lassvc     3 412 468      946        157          –         2291          –
vxmon      1 781 364      946        157          –           –          87
vxtest     2 568 916      946        157          –           –           –
```
[READ] — `strings -a <bin> | grep -oE '^[A-Za-z0-9_/.-]+\.scm:[0-9]+' | sed 's/:[0-9]*$//' | sort | uniq -c`

**Consequence, and it matters for risk assessment: `las-sc` — the process that
runs on every boot — contains the complete voice-card calibration engine.**
It is not a separate tool that has to be invoked; the code is resident. [READ]

`las-frontend` does **not** link it. It carries a **separate C++
re-implementation**, `las::LASVoiceCalibrator`, with its own operation classes
(`SVFCutoffCalOperation`, `SvfVCABiasCalOperation`, `LadderCutoffCalOperation`,
`LadderCutoffMPCalOperation`, `LadderVCABiasCalOperation`,
`LadderHighpassCalOperation`, `TwoPointCVCalOperation`, `FrontPanelCalibration`,
`CalOperation`, `CalDB`, `CalLogger`). [READ, mangled C++ symbols in
`las-frontend`] So **there are two independent implementations of voice-card
calibration on this instrument**, and they persist their results to two
different places (§6).

### 1.2 Programs, in one line each

| program | role | evidence |
|---|---|---|
| `las-sc` | audio/control daemon. Checks each card for cal data at boot and re-provisions from `/var/tuning.vxtune` if absent. Carries the whole cal engine. | [READ] §11 |
| `vxtune` | the factory tuning/calibration tool. `auto-tune`, `write`, `tcode0/1/f`, `cal-op`, `monitor`, CSV import/export. | [READ] §9 |
| `lassvc` | **service mode**: a curses UI over the front panel doing system-level calibration, serial/MAC write, uuid assignment, phone-home. | [READ] §8 |
| `vxmon` | curses monitor over the same library. Only four `las-vox-query` sites (`mon/vxmon-lib.scm:458-461`). | [READ] |
| `vxtest` | hardware test harness; the widest `/cal` literal set after `las-frontend`. | [READ] |
| `vxreport`, `vxping` | reporting / liveness. | [READ, presence] |
| `las-frontend` | the JUCE GUI. Owns `vxcal.db` and the user-facing calibration screens. | [READ] |
| `start_tune` | factory shell wrapper around `lassvc` + `vxtune auto-tune`. | [READ] §10 |
| `config-las-spi` | SPI-bus/XMOS-reset shell script. | [READ] §10 |

### 1.3 Ports and reachability

`S42sc` starts `las-sc` as: [READ, `/etc/init.d/S42sc`, 1.8.2]

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 \
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.2.1.bin --vxdb=/var/tuning.vxtune \
  --vcfw=/usr/share/xmosfw/app_las_v2.2.2.bin --vcfv=33686271 \
  --temp --expr-syms=/usr/share/vx_ee.scm --panel-state=localhost:9500 -q &
```

`lassvc`'s own defaults name the two peers explicitly: `--vc-target` =
`las.local:7770` ("Target VC address"), `--panel-target` = `las.local:9100`
("Target Panel address"). [READ, `lassvc` 0x2a3607, 0x2a3684, 0x2a350c,
0x2a3520]

`vxtune` shells out to `/usr/bin/config-las-spi` and writes
`/var/log/vxtune-log`. [READ, `vxtune` 0x251861, 0x2517e2]

**`S95dhcpd` DNATs UDP 7770, 7771, 9100 and 9300 from `ethext` straight to
203.0.113.2** — unchanged in 1.8.2: [READ, `/etc/init.d/S95dhcpd:11-14`]

```
iptables -t nat -A PREROUTING -i ethext -p udp --dport 7770 -j DNAT --to 203.0.113.2:7770
                                                       7771              203.0.113.2:7771
                                                       9100              203.0.113.2:9100
                                                       9300              203.0.113.2:9300
```

**So the entire `/cal` namespace, `/save_cal`, `/save_tuning` and `/cal:save`
are reachable from the LAN with no authentication of any kind.** [READ for the
rules; [INFERRED] that nothing authenticates, from the absence of any
credential handling in the OSC path in any of the five binaries.]

---

## 2. The `/cal` namespace

### 2.1 Extent

**223 distinct `/cal…` literals** across the ten host binaries in 1.8.2, and the
set is **byte-identical in 1.5.0**. [READ]

```sh
for b in las-sc vxtune las-frontend lassvc vxtest vxmon vxping vxreport \
         las-watchdog las-frontpanel-poll; do
  strings -a "$ROOT/usr/bin/$b" | grep -oE '^/cal([/:][A-Za-z0-9_]+)*$'
done | sort -u | wc -l          # 223, same for rootfs-1.5.0 and rootfs-1.8.2
```

Per binary: `las-frontend` 166, `lassvc` 122, `vxtest` 118, `vxtune` 92,
`las-sc` 62, `vxmon` 62. [READ]

`docs/DANGER.md` says "the `/cal/*` OSC namespace (62 leaves)". **62 is the
`las-sc` figure specifically.** The namespace as a whole is 223 literals, of
which **148 are the voice-card half** and 75 the system half (`/cal/cv` 27,
`/cal/cvin` 21, `/cal/lhck` 14, `/cal/lk` 4, `/cal/rk` 4, and the five
`save`/`load`/`cal_default` verbs).

Three of the 223 are bare prefixes — `/cal/o`, `/cal/p`, `/cal/svf` — which
`las-frontend` concatenates with an index at runtime (`/cal/o` + `1` + `/y0`).
[INFERRED, from their presence as standalone literals beside `osc `, `pulse `
and ` svf ` fragments at `las-frontend` 0xa37ad5, 0xa37b1f, 0xa37f7f, 0xa37b1a,
0xa37b39, 0xa37f4f] This is why some indexed forms appear as literals and their
siblings do not.

### 2.2 The voice-card half — per-card leaves

These are sent to a **card**, not to the controller: `las/las-vox.scm` rewrites
the address with a per-card prefix (`las-vox-prefix`, `csosc#osc-set-adr`,
`las-vox-msg-set-adr`), and the literal `/vx/` sits in the same frames. [READ,
symbol list; corroborates `cal-dispatch.md` §1]

| leaf group | sub-leaves | what it is |
|---|---|---|
| `/cal/o1 /o2 /o3` | `/l /h /x` (+ `/y0 /y1` from `las-frontend`) | oscillator saw/tri VCA |
| `/cal/p1 /p2 /p3` | `/l /h /x` | oscillator pulse VCA |
| `/cal/rm` | `/l /h /x /x0 /x1 /y0 /y1` | ring-modulator VCA |
| `/cal/extin` | `/x0 /x1` | external-input VCA |
| `/cal/noisecw`, `/cal/noiseccw` | `/l /h /x /x0 /x1 /y0 /y1` | the two noise colours |
| `/cal/svf1f /svf2f` | `/x0 /x1 /y0 /y1` | Filter A section 1/2 cutoff |
| `/cal/svf1r /svf2r` | `/x /x0 /x1 /y0 /y1` | Filter A section 1/2 resonance |
| `/cal/ladf` | `/l /h /x /x0 /x1 /y0 /y1` | Filter B (ladder) cutoff |
| `/cal/ladr` | `/l /h /x /x0 /x1 /y0 /y1` | Filter B resonance |
| `/cal/hpf` | — | Filter B high-pass bias ("ladder filter hp bias") |
| `/cal/gsvf` | `/l /h /x /x0 /x1 /y0 /y1` | Filter A output VCA gain |
| `/cal/gldr` | `/l /h /x /x0 /x1 /y0 /y1` | Filter B output VCA gain |
| `/cal/biasfa`, `/cal/biasfb` | — | Filter A / Filter B VCA bias |
| `/cal/mainl /mainr` | `/x0 /x1 /y0 /y1` | the voice's main-bus VCA pair |
| `/cal/aux1 /aux2` | `/l /h /x /x0 /x1 /y0 /y1` | the voice's SUB/SEND VCA pair |
| `/cal/decay` | — | noise/decay measurement window |
| `/cal/testosch/{ch,freq,g,wave}`, `/cal/testoscl/ch` | — | card-resident test oscillator, high and low |
| `/cal/cal_sw_version` | — | calibration software version |

The identifications are [READ] from the label strings that sit beside each
address in `las-sc`'s `cal.scm` literal frame — the pool is a plain run of
`\xfe\x42 <24-bit BE length> <bytes> \x00` records and the pairing is literal
adjacency: [READ, `las-sc` file 0x218f38–0x2191c0]

```
0x218f38  checking for main vca cal data
0x218f5c  /a/stat/mainl        0x218f78  /cal/mainr/x     0x218f8a  /cal/mainl/x
0x218f9c  /mix/main-en         0x218faf  /a/stat/mainr
0x218fc2  /cal/mainr           0x218fd2  main vca r gain
0x218fe7  /cal/mainl           0x218ff7  main vca l gain
0x21900c  /cal/gldr/x          0x21901d  /cal/gsvf/x
0x21902a  30000.0              0x219039  /stat/decay      0x21904a  /cal/decay
0x21906c  checking for send vca cal data
0x219090  /cal/aux2            0x21909f  /cal/aux1
0x2190ad  /mix/subr-en  0x2190bf  /mix/subl-en  0x2190d2  /mix/sub-en
0x2190e3  /a/stat/send2        0x2190f6  send2 vca gain
0x21910a  /a/stat/send1        0x21911d  send1 vca gain
0x219131  checking for extin cal data
0x219152  /cal/extin           0x219162  external input gain
0x21917b  /mix/ext/ext1  0x21918e  /mix/ext/ext0
0x2191a1  /a/in2  0x2191ad  /a/in1  0x2191b9  /hw/mute
```

`/cal/decay` sits beside `/stat/decay` and the constant `30000.0`. [READ]
It is [INFERRED] to be the decay-measurement window used by the noise
calibration; the units are [UNKNOWN].

The `/l` `/h` `/x` triple (used by `las-sc`, `vxtune`, `vxtest`, `vxmon`,
`lassvc`) and the `/x0 /x1 /y0 /y1` quadruple (used by `las-frontend`) are two
naming schemes over the same `linear-cal` record. `l`/`h` correspond to the low
and high **measured** points; `x` is the live value. [INFERRED, from
`linear-cal`'s field names (§4.1) and from `las-frontend`'s SQL, which selects
literally `X0, X1, Y0, Y1` from every VCA table.] Whether the card accepts both
spellings is **[UNKNOWN]**.

### 2.3 The system half — `lassvc` and `las-frontend` only

Absent from `las-sc` entirely. [READ]

| group | addresses | what |
|---|---|---|
| CV **outputs** | `/cal/cv/{0,1,6,7}` each with `/x /x0 /x1 /y0 /y1`; `/cal/cv/{3,4,5}/x` | rear-panel CV out calibration |
| CV **inputs** | `/cal/cvin/{cvin0,cvin1}/{x0,x1}` | CV in |
| expression / sustain | `/cal/cvin/{expr0,expr1,sus}/{x0,x1,y0,y1}` | pedal inputs |
| left-hand controller | `/cal/lhck/{pitch,mod,glide}` each with `:cal_low :cal_mid :cal_high`; `/cal/lhck/atouch`; `/cal/lhck/xy:cal_lr`, `:cal_ul` | wheels, glide knob, aftertouch, XY pad |
| panels | `/cal/lk`, `/cal/rk`, each with `:cal_low :cal_mid :cal_high` | **left panel / right panel** knob calibration |
| noise | `/cal/noise` | noise source |
| verbs | `/cal/save`, `/cal/load`, `/cal:save`, `/cal:load`, `/cal:cal_default` | §2.4 |

`lk`/`rk` are the **left and right front panels**, not keyboard halves: `lassvc`'s
menu items at 0x2a2873 and 0x2a2887 are literally `left panel` and `right panel`,
and the panel-calibration instructions say "turn all knobs on the l/r panels".
[READ]

`lassvc` also carries the paired hardware leaves and the constants:
[READ, `lassvc` 0x2a30a8–0x2a33a6]

```
/hw/cvin0 → /cal/cvin/cvin0      x0 = -0.99   x1 = +0.99
/hw/cvin1 → /cal/cvin/cvin1
/hw/expr0 → /cal/cvin/expr0      0.05 appears in the same frame
/hw/expr1 → /cal/cvin/expr1
/hw/sus   → /cal/cvin/sus
/cal/cv/0/x0 = 0.0028   /cal/cv/1/y1 = -0.5   ±5.0  ±0.9  0.95  0.75  0.6  1.86
/a/stat/cvin0 ↔ /cal/cv/6        /a/stat/cvin1 ↔ /cal/cv/7
```

The pairing of `/cal/cv/6` and `/cal/cv/7` with `/a/stat/cvin0` and
`/a/stat/cvin1` is [READ] adjacency, and is consistent with the on-screen
instruction "connect cv out 1 to expr in 1, cv out 2 to expr in 2, and cv out 3
to sus in" (0x2a1f02) and "connect hph l to cv in 1 and hph r to cv in 2"
(0x2a1617): **the system calibrations are loopbacks, measured through the
instrument's own inputs.** [READ for the strings, [INFERRED] for the mapping of
index → physical jack, which is not established. `/cal/cv/{0..7}` is eight
indices for four rear CV outs; what indices 2–7 address is **[UNKNOWN]**.]

### 2.4 The verbs, settled

`docs/arch/cal-dispatch.md` §6.3 said of the controller's calibration verbs:
"the full address they hang off (`/cal:save`? `/cal/save`? something under
`/lc`?) is behind the compressed address table and is **[INFERRED]** at best."

**It is not. All five spellings exist as complete literal strings.** [READ]

| address | in | neighbours in the literal frame |
|---|---|---|
| `/cal:save` | `lassvc` 0x2a3484, `las-frontend` | `/v/voices`, `/cal/save`, `/info/serial`, `/info/save`, `/info/mac` |
| `/cal/save` | `lassvc` 0x2a3493, `las-frontend` | as above |
| `/cal:load` | `las-frontend` | — |
| `/cal:cal_default` | `las-frontend` | — |
| `/cal/load` | `las-frontend` | — |
| `/save_cal` | `vxtune` 0x2501f4, `las-frontend` 0x7e507b2 | see below |
| `/save_tuning` | `vxtune` 0x250181, `las-frontend` 0x7e502f8 | see below |
| `/load_cal`, `/load_tuning` | `las-sc` 0x1e53e5, 0x1e53f3 | §11.2 |

`/save_cal` and `/save_tuning` are the **card-side commit verbs**, and `vxtune`
labels them in its own log strings: [READ, `vxtune` 0x250132–0x250203, a
contiguous literal run]

```
0x250132  Sent write tuning command
0x250151  Tuning data write failed: [
0x250181  /save_tuning
0x250194  Sending write tuning command
0x2501b6  Sent write cal command
0x2501d2  Cal data write failed: [
0x2501f4  /save_cal
0x250203  Sending write cal command
```

`las-frontend` independently ends its own cal-to-card sequence with the same two
addresses: `/save_tuning` at 0x7e502f8 after `/tune/l0tc`, `/tune/l1tc`,
`/tune/ftc`, `/tune/l/`, `/tune/autor/`; and `/save_cal` at 0x7e507b2 after the
run of `SELECT updated, X0, X1, Y0, Y1 FROM <table> WHERE VOICE ==` statements.
[READ]

**Two independent codebases, the same set/commit split.** This is a firmer basis
for the volatile/persistent split than `cal-dispatch.md` §4.3's search-loop
argument, which was explicitly an inference.

---

## 3. The seventeen voice-card calibrations

`las-frontend`'s `VoiceCardCalResultPanel` lists exactly seventeen rows.
[READ, `las-frontend` 0x7e9849e–0x7e9855c, contiguous]

```
OSC 1 VCA   OSC 2 VCA   OSC 3 VCA
PULSE 1 VCA PULSE 2 VCA PULSE 3 VCA
NOISE CW    NOISE CCW
LADDER CUTOFF
SVF 1 CUTOFF  SVF 1 RESONANCE  SVF 2 CUTOFF  SVF 2 RESONANCE
MAIN L VCA  MAIN R VCA
SEND L VCA  SEND R VCA
```

Unchanged from 1.5.0. This is the list the front panel shows and it is what
`CALIBRATIONS = 17/17` on the calibration screen counts. [READ for the list;
[INFERRED] for the identification with the 17/17 counter, which is the reading
in `docs/DANGER.md` and which nothing here contradicts.]

**The result *database* is wider than the result *screen*.** `cal_results` has
**25** columns beyond `voice`: [READ, `vxcal.db` schema, and the identical
`CREATE TABLE` text in `las-frontend` at 0x7e4e845]

```
osc_one_vca osc_two_vca osc_three_vca pulse_one_vca pulse_two_vca pulse_three_vca
rm_vca extin_vca noise_cw_vca noise_ccw_vca
ladder_vca ladder_bias svf_vca svf_bias
ladder_resonance ladder_cutoff ladder_hp
svf1f svf1r svf2f svf2r
mainl mainr sendl sendr
```

The eight the screen does not show are `rm_vca`, `extin_vca`, `ladder_vca`,
`ladder_bias`, `svf_vca`, `svf_bias`, `ladder_resonance`, `ladder_hp`.
[READ, by difference]

### 3.1 The 29 progress stages

`VoiceCardCalProgressPanel`, in order. [READ, `las-frontend`
0x7e97d85–0x7e9812f, contiguous]

```
PERFORMING INITIAL FREQUENCY MEASUREMENTS
WAITING FOR TEMPERATURE TO SETTLE - HIGH
RUNNING TEMPERATURE CALIBRATION - HIGH
WAITING FOR TEMPERATURE TO SETTLE - LOW
RUNNING TEMPERATURE CALIBRATION - LOW
PERFORMING DENSE FREQUENCY MEASUREMENTS
CALCULATING TUNING TABLES
WRITING TUNING DATA
CALIBRATING OSCILLATOR {1,2,3} SAW/TRI VCA
CALIBRATING OSCILLATOR {1,2,3} PULSE VCA
CALIBRATING RING MOD VCA
CALIBRATING EXTERNAL INPUT VCA
CALIBRATING NOISE VCA
CALIBRATING LADDER VCA GAIN
CALIBRATING LADDER VCA BIAS
CALIBRATING SVF VCA GAIN
CALIBRATING SVF VCA BIAS
CALIBRATING LADDER CUTOFF FREQUENCY
CALIBRATING LADDER RESONANCE
CALIBRATING LADDER HIGH PASS
CALIBRATING SVF 1
CALIBRATING SVF 2
CALIBRATING MAIN VCA
CALIBRATING SEND VCA
CALIBRATING TRI MAX / TRI MID / TRI MIN / SAW MIN / SAW MAX
```

The tuning half runs first (frequency measurement, two temperature points, dense
measurement, table calculation, write), then the analog calibrations. [READ]

`VoiceCardCalSelectPanel` groups them for selection: `SELECT ALL`,
`SELECT NONE`, and category names including `NOISE SOURCE`, `MAIN OUT VCA`,
`SEND OUT VCA`. [READ, 0x7e98858–0x7e9889d]

---

## 4. The data model

Every record definition below is **[READ] verbatim** from `las-sc`'s literal
blob, where CHICKEN emits the interned field-name symbols as a contiguous run of
`\xfe\x01 <24-bit BE length> <name> \x00` records.

### 4.1 `linear-cal`

`las-sc` file 0x218737 ff., the names emitted in reverse: [READ]

```
y1  y0  x1  x0  x
```

so the record is

```scheme
(define-record linear-cal x x0 x1 y0 y1)     ; 5 fields
```

`cal/cal.scm:30` is `make-linear-cal` via `##sys#get-keyword` and `old-make`
(the `defstruct` signature), and `cal/cal.scm:39` is `lerp`. [READ, trace map]
`cal/vxtune.scm:596-600` reads it with `linear-cal?`, `linear-cal-x0`,
`linear-cal-x1`, `linear-cal-y0`, `linear-cal-y1` inside `lincal-success?`.
[READ]

**What the fields mean.** From the instrument's own data (§5.3):

* `x` is the **live** value. It is `0.0` in all 320 `linear-cal` records on this
  instrument (16 voices x 20 records). [READ]
* `x0`, `x1` are the **input domain** endpoints and are *identical across all
  sixteen voices* for each cal type — 0→1 for most, 0.1→1 for the oscillator
  VCAs, 0.05→1 for the main VCAs, and 0.12→3.84 for the ladder cutoff. Because
  they do not vary between cards they are constants of the routine, not
  measurements. [READ for the invariance; [INFERRED] for "constants of the
  routine".]
* `y0`, `y1` are the **measured DAC control codes**. All 521 flonum y values on
  this instrument (including the two breakpoint lists and the three bare
  doubles) lie in [-0.9453394311669423, +0.938901132255568]; the only flonum
  x values anywhere are 0.05, 0.06, 0.1, 0.12, 0.3, 3.0 and 3.84. [READ]
* For the two *frequency* calibrations the x axis is in **kHz**: `ladf` spans
  0.12 → 3.84 (120 Hz to 3840 Hz, exactly five octaves), and `svf1f`/`svf2f`
  carry breakpoints at 0.06, 0.1, 0.3, 3.0. [READ for the numbers; [INFERRED]
  that the unit is kHz, from the values themselves and from the UI string
  `CALIBRATING SVF <n> <freq> HZ` at `las-frontend` 0xa37f0a/0xa37f1b.]

`lerp` at `cal/cal.scm:39` then maps a parameter to a code across (x0,y0)-(x1,y1).
[INFERRED, from the name and position immediately after `make-linear-cal`.]

**Unset endpoints keep exact-integer defaults.** In the serialised form a
measured endpoint is an IEEE double and an untouched one is a CHICKEN fixnum
(0, 1 or -1). That is how §5.3 can say which calibrations actually ran.

### 4.2 `las-voxcal` — 26 fields, verbatim

`las-sc` file 0x218737 ff., immediately after the `linear-cal` names, as one
unbroken run of symbols: [READ]

```
o1  p1  o2  p2  o3  p3  rm  extin
svf1f  svf1r  svf2f  svf2r  ladf  ladr  ladhp
bias-gsvf  gsvf  bias-gldr  gldr
mainl  mainr  sub1  sub2  fm  noisecw  noiseccw
```

This is the declaration order, read out of the binary — **not** inferred from
accessor ordering, and it includes `fm`, which appears nowhere in the accessor
symbol list and is unset in every file. It agrees exactly with
`docs/arch/xmos-deep.md` §2.3.

It is confirmed a second time, independently, by `cal/vxtune.scm`'s report
function, which enumerates the accessors in source order:
[READ, trace map lines 625–678]

```
625 o1   [626-632 the oscillator's own tuning]   633 p1
634 o2   [635-641]                               642 p2
643 o3   [644-650]                               651 p3
653 rm   654 extin
656 svf1f  657 svf1r  658 svf2f  659 svf2r
661 ladf   662 ladr   663 ladhp
665 bias-gsvf  666 gsvf     668 bias-gldr  669 gldr
671 mainl      672 mainr    674 sub1       675 sub2
677 noisecw    678 noiseccw
```

25 names in exactly that order, with `fm` absent because it is never populated.

And a third time, structurally, by the data itself (§5.3): slots 8 and 10 are
4-point breakpoint lists, slots 14/15/17 are bare doubles, slot 23 is `#f`. All
five positions match. [READ]

Field types, from the data:

| slot | field | type in file |
|---|---|---|
| 0-7 | `o1 p1 o2 p2 o3 p3 rm extin` | `linear-cal` |
| 8 | `svf1f` | list of 4 `(kHz . code)` pairs |
| 9 | `svf1r` | `linear-cal` |
| 10 | `svf2f` | list of 4 pairs |
| 11-13 | `svf2r ladf ladr` | `linear-cal` |
| 14 | `ladhp` | bare double |
| 15 | `bias-gsvf` | bare double |
| 16 | `gsvf` | `linear-cal` |
| 17 | `bias-gldr` | bare double |
| 18-22 | `gldr mainl mainr sub1 sub2` | `linear-cal` |
| 23 | `fm` | `#f` on all sixteen cards |
| 24-25 | `noisecw noiseccw` | `linear-cal` |

The three bare doubles and the two breakpoint lists map exactly onto the three
single-`x` tables (`ladhp`, `bias_gsvf`, `bias_gldr`) and the 4-point
`svf_freq` table in `vxcal.db`, and there is no `fm` table. [READ, both sides]

### 4.3 `las-osc`, `las-phase`, `las-vox`

`las-sc` file 0x207000 ff., one contiguous symbol run: [READ]

```
id  stop  sparsetbl  temptbl  temptbl-l  temptbl-h  tempcode  mt  lftbl  codetbl  freqtbl
vox  nr  pol  ph0  ph1  phf  ffsaw
```
followed by the flonum `0.9` and the symbol `ffsaw-code`.

```scheme
(define-record las-phase id stop sparsetbl temptbl temptbl-l temptbl-h
                         tempcode mt lftbl codetbl freqtbl)      ; 11
(define-record las-osc   vox nr pol ph0 ph1 phf ffsaw ffsaw-code) ; 8, ffsaw-code default 0.9
```

`las-vox` from its accessor run at `las-sc` 0x204aa8: [READ]

```scheme
(define-record las-vox nr osc1 osc2 osc3 cal)                     ; 5
```

`vxtune`'s own help text names three of the `las-phase` fields: [READ, `vxtune`
0x25049b, 0x2505f3, 0x2503de, 0x250354]

```
osc-<ph>-tempcode  - code for temptbl measurements & mt calculation
osc-<ph>-sparsetbl - sparse (octave) table
osc-<ph>-codetbl   - code table: code -> half-freq
osc-<ph>-freqtbl   - frequency table: half-freq -> (m . b)
osc-pol            - oscillator polarity: 1 or -1
osc-ffsaw-code     - code for phase 0 for fixed saw
```

---

## 5. `/var/tuning.vxtune` — the format

### 5.1 The container

A **directory**, not a file. [READ, `start_tune`; [READ] the backup]

```
/var/tuning.vxtune/
    vxtune-db          13 bytes, ASCII:  (vxtune-db 3)
    v0 … v15           ~1.4 kB each      one las-vox, holding one las-voxcal
    v0-o1 … v15-o3     ~56 kB each       one las-osc, holding four las-phase
```

`start_tune` creates it and writes the version marker literally: [READ,
`/usr/bin/start_tune`]

```sh
mkdir /var/tuning.vxtune
echo '(vxtune-db 3)' >/var/tuning.vxtune/vxtune-db
```

65 files on this instrument (1 + 16 + 48). The backup archive holds 66 —
those 65 plus `cal/vxcal.db`. All 66 md5-verified in this pass. [READ]

`--vxdb=/var/tuning.vxtune` is passed to `las-sc` on every boot, described in its
own option table as **"Voice Card Tuning Data"**. [READ, `S42sc`; `las-sc`
0x1e5f8f]

### 5.2 The serialisation — CHICKEN `s11n`

Not documented anywhere in this repository before. **Fully decoded here; the
decoder in §17 consumes every one of the 65 files to the last byte.** [READ]

A stream of tagged objects. All multi-byte fields are **little-endian**.

| tag | meaning |
|---|---|
| `0x01` | the empty list `()` |
| `0x02` | `#t` |
| `0x03` + int32 | fixnum, **CHICKEN-boxed**: the stored word is `(n << 1) \| 1` |
| `0x08` | `#f` |
| `0x0a` + uint32 | back-reference to object *n* in the shared-object table |
| `0x0d` + object | symbol; the object that follows is its name string |
| `0x04`, `0x05` + header | a block. `0x05` registers in the shared-object table. |

A block header is one little-endian 32-bit word `(TYPE << 24) | SIZE`, with
CHICKEN's own type byte:

| TYPE | meaning | SIZE |
|---|---|---|
| `0x00` | vector | slots |
| `0x03` | pair | 2 |
| `0x08` | structure (record) | slots, **slot 0 is the type symbol** |
| `0x42` | string | bytes |
| `0x48` | bytevector | bytes |
| `0x55` | flonum | 8 (IEEE-754 double follows) |

Worked example, the first 18 bytes of `v0`:

```
05 06 00 00 08      block, header 0x08000006 -> structure, 6 slots
0d                  slot 0: symbol
   04 07 00 00 42   block, header 0x42000007 -> string, 7 bytes
   "las-vox"
03 01 00 00 00      slot 1: fixnum, word 1  ->  0   (voice number)
08 08 08            slots 2,3,4: #f #f #f   (osc1 osc2 osc3, not inlined)
05 1b 00 00 08      slot 5: structure, 27 slots -> las-voxcal
```

**The boxed-fixnum rule is not optional.** Reading the raw word gives voice
numbers 1, 3, 5 … 31 across `v0`…`v15`, oscillator numbers 3/5/7 in `v*-o1/2/3`,
and phase ids 1/3/5. `(w-1)>>1` gives 0…15, 1/2/3 and 0/1/2. [READ] Getting
this wrong makes every `linear-cal` look incoherent — it is the reason the
default endpoints appear as "3" and "-1" until unboxed.

The same `(TYPE << 24) | SIZE` header, big-endian and behind an `\xfe` marker,
is CHICKEN's *compiled-literal* framing inside the ARM binaries
(`\xfe\x42\x00\x00\x08/hw/mute\x00`). The two encodings are the same object
model. [READ, `las-sc` file 0x2191b0]

### 5.3 What is actually in this instrument's files

#### The per-voice files, `v0`…`v15`

One `las-vox` with `nr` = 0…15, `osc1/osc2/osc3` = `#f`, and `cal` = a
`las-voxcal`. Voice 0, in full: [READ, decoded from
`calibration-20260907-222301.tar.gz`]

```
 0 o1         x=0.0  x0=0.1   x1=1     y0=0.8993967274035615   y1=-1
 1 p1         x=0.0  x0=0     x1=1     y0=0.03988389555736509  y1=0.4764705455027183
 2 o2         x=0.0  x0=0.1   x1=1     y0=0.8963125775159422   y1=-1
 3 p2         x=0.0  x0=0     x1=1     y0=0.021003195365117307 y1=0.45744815752455226
 4 o3         x=0.0  x0=0.1   x1=1     y0=0.8971496678814085   y1=-1
 5 p3         x=0.0  x0=0     x1=1     y0=0.03539853580636454  y1=0.4784808990193936
 6 rm         x=0.0  x0=0     x1=1     y0=-1                   y1=0.5982890931016576
 7 extin      x=0.0  x0=0     x1=1     y0=1                    y1=-0.3763863164967195
 8 svf1f      (0.06,-0.686230) (0.1,-0.674735) (0.3,-0.644848) (3.0,-0.458401)
 9 svf1r      x=0.0  x0=0     x1=1     y0=-1                   y1=0.6272035903611188
10 svf2f      (0.06,-0.698112) (0.1,-0.686632) (0.3,-0.656214) (3.0,-0.463621)
11 svf2r      x=0.0  x0=0     x1=1     y0=-1                   y1=0.6400446619977939
12 ladf       x=0.0  x0=0.12  x1=3.84  y0=-0.83896             y1=-0.6817560422278642
13 ladr       x=0.0  x0=0     x1=1     y0=1                    y1=-0.756584709977816
14 ladhp      0.7017979981750784
15 bias-gsvf  0.09564804634390059
16 gsvf       x=0.0  x0=0     x1=1     y0=1                    y1=-1
17 bias-gldr  -0.04862386365525823
18 gldr       x=0.0  x0=0     x1=1     y0=1                    y1=-1
19 mainl      x=0.0  x0=0.05  x1=1     y0=1                    y1=0.0
20 mainr      x=0.0  x0=0.05  x1=1     y0=1                    y1=0.0
21 sub1       x=0.0  x0=0     x1=1     y0=1                    y1=0.0
22 sub2       x=0.0  x0=0     x1=1     y0=1                    y1=0.0
23 fm         #f
24 noisecw    x=0.0  x0=0     x1=1     y0=1                    y1=-0.7447881507224663
25 noiseccw   x=0.0  x0=0     x1=1     y0=1                    y1=-0.8539883094679791
```

Across all sixteen voices: [READ]

| field | endpoints actually measured | spread across the 16 cards |
|---|---|---|
| `o1 o2 o3` | `y0` only (`y1` at the -1 rail on 15 of 16 cards) | y0 0.862 … 0.939 |
| `p1 p2 p3` | **both** `y0` and `y1` | y0 0.009 … 0.056; y1 0.447 … 0.508 |
| `rm` | `y1` only | 0.518 … 0.682 |
| `extin` | `y1` only | −0.541 … −0.376 |
| `svf1r svf2r` | `y1` only | 0.608 … 0.672 |
| `ladf` | **both** | y0 −0.859 … −0.810; y1 −0.701 … −0.657 |
| `ladr` | `y1` only | −0.867 … −0.757 |
| `ladhp` | the single value | 0.702 … 0.745 |
| `bias-gsvf` | the single value | 0.065 … 0.183 |
| `bias-gldr` | the single value | −0.061 … +0.078 |
| **`gsvf`, `gldr`** | **neither — both endpoints are the untouched fixnum defaults `y0=1, y1=-1` on all sixteen cards** | — |
| `mainl` | `y1` only, and it is `0.0` on 15 cards, `−0.111` on one | — |
| `mainr sub1 sub2` | `y1` only, `0.0` on all sixteen | — |
| `fm` | never | — |
| `noisecw noiseccw` | `y1` only | −1.0 … −0.700 |

Two things follow, and they are the most consequential findings in this section.

1. **The filter output VCA gain calibrations (`gsvf`, `gldr`) never ran on this
   instrument.** Both endpoints are the exact `defstruct` defaults. What *did*
   run is their bias counterpart (`bias-gsvf`, `bias-gldr`), which carries real
   per-card values. [READ]
2. **The main and send VCA calibrations produced `0.0`** on essentially every
   card. `0.0` is a flonum, so the field was written; but it is also the value a
   failed or clamped search would leave. Whether this is a legitimate result or
   a non-convergence is **[UNKNOWN]** from static analysis. It is worth noting
   that `MAIN L VCA`, `MAIN R VCA`, `SEND L VCA` and `SEND R VCA` are four of
   the seventeen rows the user-facing results screen reports.

`ladhp` sits at 0.702–0.745 on this unit. `/etc/vxtune/cal-limits.scm` sets
`bias-hp target: 0.64` with `; target: 0.72` commented out immediately above.
[READ] The correspondence is suggestive but **[UNKNOWN]** — nothing establishes
that `ladhp` and `bias-hp` are the same quantity in the same units.

#### The per-oscillator files, `v*-o1/2/3`

One `las-osc` holding four `las-phase` records. `v0-o1`: [READ]

```
las-osc  vox=(las-vox nr=0)  nr=1  pol=1  ffsaw-code=0.9

las-phase id=0 (ph0)                      las-phase id=2 (phf)
  temptbl-l  3 rows @ 38.19-38.26 °C        temptbl-l  3 rows @ 38.21 °C, ~10108 Hz
  temptbl-h  2 rows @ 55.67-55.83 °C        temptbl-h  2 rows @ 55.7-55.8 °C
  tempcode   1 row: code -0.035185,          tempcode   1 row: target 10000, tol 200
             118.94 Hz, 38.48 °C,            mt         2.432370213081464
             target 110, tol 10               lftbl      #f
  mt         0.14803526356503188             codetbl    25 rows, 198 Hz … 180 831 Hz
  lftbl      157 rows, 18.98 …  100.09 Hz    freqtbl    19 rows, 987 Hz … 133 952 Hz
  codetbl    187 rows, 99.96 … 20 974.9 Hz
  freqtbl    119 rows, 16.3516 … 14080.0 Hz  las-phase id='ffsaw  — every field #f
las-phase id=1 (ph1): same shape, mt = -0.26425431825226564
```

Row shapes, [READ] from the values and corroborated by the matching `vxcal.db`
column lists:

| table | row | matching `vxcal.db` table |
|---|---|---|
| `temptbl-l`, `temptbl-h` | `(code, freq, temp)` | `tcal_low_table`, `tcal_high_table` — same three columns |
| `tempcode` | `(code, freq, temp, target_freq, tolerance)` | `tcode_table` (`ph0, ph1, autor`) |
| `mt` | scalar | `mt_table.mt` |
| `lftbl` | `(code, freq, temp)` | `lf_table` (`freq, temp, code`) |
| `codetbl` | `(code, freq, temp)` | `hf_table` (`freq, temp, code`) |
| `freqtbl` | `(half-freq, m, b)` | `freq_table` (`freq, mc, bc`) |

`freqtbl` spans **16.351597831287414 Hz to 14080.0 Hz** — C0 to A9 on the
equal-tempered A440 grid, to full double precision. [READ] The identification
with note names is [INFERRED] but 16.3516 Hz and 14080.0 Hz are both exact
A440 grid points and 14080.0 is stored as an exact value.

`las-phase` ids 0, 1, 2 correspond to the record fields `ph0`, `ph1`, `phf`;
the fourth is tagged with the symbol `ffsaw` and is **entirely empty on all 48
oscillators**. [READ] So the "fixed saw" phase is provisioned for and unused.

`sparsetbl` and `temptbl` are `#f` on every phase of every oscillator on this
instrument. [READ] `vxtune`'s help calls `sparsetbl` the "sparse (octave)
table". [READ]

Point counts across the 48 oscillator files, [READ]:
`lftbl` 152–158, `codetbl` 185–187 for ph0/ph1 and 25–26 for phf, `freqtbl` 119
for ph0/ph1 and 19 for phf. `temptbl-l` 2–3 rows, `temptbl-h` 2–3 rows.

#### Timestamps

[READ, from the tar]

```
cal/vxcal.db              2022-05-29 01:13:10
tuning.vxtune/vxtune-db   2000-05-05 05:48:48
tuning.vxtune/v0          2000-05-05 09:21:47
tuning.vxtune/v0-o1       2000-05-08 03:15:09
```

The year-2000 dates are an unset RTC. The three-day gap between the `v*` and
`v*-o*` groups is consistent with an accumulated-uptime clock and a long tuning
pass, but the interpretation is **[UNKNOWN]**. What is [READ] is that the
tuning data predates `vxcal.db` by a wide margin and that `vxcal.db` is dated to
within a day of the `1.5.0` binaries in `captures/rootfs-1.5.0` (`May 16 2022`
for `/usr/bin/*`, `May 29 2022` for the DB).

---

## 6. `/var/cal/vxcal.db`

### 6.1 Schema

38 tables. The instrument's file and `las-frontend`'s `CREATE TABLE` strings
(0x7e4dd13–0x7e4eb89) agree statement for statement. [READ, both sides]

**Per-voice analog tables**, all keyed on `voice`:

| table | columns beyond the key | matches `las-voxcal` slot |
|---|---|---|
| `osc_vca` | `osc, updated, x0, x1, y0, y1` | `o1 o2 o3` |
| `pulse_vca` | `osc, updated, x0, x1, y0, y1` | `p1 p2 p3` |
| `rm_vca`, `extin_vca`, `ladr`, `gsvf`, `gldr`, `mainl`, `mainr`, `send1`, `send2`, `noisecw`, `noiseccw` | `updated, x0, x1, y0, y1` | the corresponding `linear-cal` |
| `svf_res` | `svf_num, updated, x0, x1, y0, y1` | `svf1r svf2r` |
| `svf_freq` | `svf_num, updated, num_points, f0,c0 … f3,c3` | `svf1f svf2f` — **4 points, exactly the file's list length** |
| `ladf` | `updated, num_points, f0,c0 … f11,c11` | `ladf` — **12 points declared** |
| `ladhp`, `bias_gsvf`, `bias_gldr` | `updated, x` | the three bare doubles |

**Note the one structural mismatch:** the schema declares `ladf` as a 12-point
breakpoint table, while this instrument's `tuning.vxtune` stores `ladf` as a
2-point `linear-cal`. [READ, both] `las-frontend` reads it as
`SELECT updated, num_points, <cols> FROM ladf` (0x7e50503) and logs
`ladder cutoff retrieved` (0x7e5053b). So the newer path can hold a 12-point
ladder-cutoff curve where the legacy path holds a line. Whether the card accepts
both is **[UNKNOWN]**. There is no `fm` table.

**Per-oscillator tuning tables**, keyed on `(voice, osc[, phase][, idx])`:
`tune_info_table` (point counts for `ph0_lf/hf/freq`, `ph1_lf/hf/freq`,
`autor`, `autor_freq`), `tcode_table` (`ph0, ph1, autor`), `tcal_low_table`,
`tcal_high_table`, `mt_table`, `lf_table`, `hf_table`, `autor_table`,
`ph0_ds_table`, `ph1_ds_table`, `autor_ds_table`, `freq_table`,
`autor_freq_table`. [READ]

The `autor` group has **no counterpart in `tuning.vxtune`** — the file's fourth
`las-phase` is `ffsaw`, not `autor`. [READ] `vxtune` has `/tune/autor/`,
`autor-curve`, `send autor table` and `las-osc-set-freq-ffsaw`. [READ] So
`autor` and `ffsaw` are two names for, or two of, the additional oscillator
modes; the relationship is **[UNKNOWN]**.

**System tables:** `cal_info(version, cal_performed)`, `pid(performed)`,
`cal_results` (25 flags), `error_log(voice, type, message TEST)` — the typo
`TEST` for `TEXT` is in Moog's own DDL and therefore in the live schema, which
SQLite accepts as an unrecognised type name. [READ]

```sql
CREATE TABLE system_cal_table (version INTEGER NOT NULL PRIMARY KEY DEFAULT 1,
  cv_out, cv_in, pedal_in, main_out, headphone_out, noise,
  front_panel_low, front_panel_mid, front_panel_high, lhc);
CREATE TABLE system_cvout_table (cvout_num INTEGER NOT NULL PRIMARY KEY,
  version, updated, x0, x1, y0, y1);
```

`system_cal_table`'s ten flags map one-for-one onto `lassvc`'s service-mode
calibration menu (§8). [READ, both lists]

### 6.2 Related paths

[READ, `las-frontend`]

```
/var/cal/vxcal.db          0x7ea726d (command-line option table)
/var/cal/vxcal-test.db     0x7e4f757, 0x7e4feff
/var/cal/system_uuid       0xa3e04f
Copied Cal DB to USB:      0x7e4dcf0
```

### 6.3 What is actually in this instrument's `vxcal.db`

241 664 bytes, SQLite 3, written by SQLite 3.25.3. [READ, `file(1)`]

| table | rows |
|---|---|
| `cal_results` | **16, every column 0** |
| `pid` | **2 rows, `performed = 1`** |
| `system_cal_table` | **1 row, version 1, every flag 0** |
| **all other 35 tables** | **0** |

[READ, `sqlite3 vxcal.db "SELECT COUNT(*) FROM …"` over every table]

**Reading, and it is a clean one.** `las-frontend` labels its
`tuning.vxtune`-writing path "**legacy**":
[READ, `las-frontend` 0x7e976bc–0x7e979bd]

```
0x7e976bc  TRANSFERRING LEGACY CALIBRATION AND
0x7e976e0  TUNING DATA TO VOICE CARDS
0x7e976fb  LEGACY DATABASE WRITE
0x7e97a34  killall las-watchdog
0x7e97a49  /usr/bin/vxtune write -c vc -f /var/tuning.vxtune
0x7e97aa7  RESTORE LEGACY DATA
0x7e979bd  PRESS ENCODER TO WRITE LEGACY CALIBRATION DATA TO VOICE CARDS
```
against its own path
```
0x7e97986  PRESS ENCODER TO WRITE CALIBRATION DATA TO VOICE CARDS
```
and the class method names `voiceCalWrite` / `voiceCalLegacyWrite`.

**[INFERRED, and load-bearing]** This instrument was calibrated at the factory
through the `vxtune` "legacy" path, and no `las-frontend` voice-card calibration
has ever been run on it. The evidence: `tuning.vxtune` is complete and dated to
an unset RTC (factory); `vxcal.db` was created in May 2022, contains its full
38-table schema, contains not one measurement, and `cal_info` — the table
holding `cal_performed` — is **empty**. `cal_results`' 16 all-zero rows and
`system_cal_table`'s single all-zero row are the rows `las-frontend` inserts on
first open.

`pid` holding two rows of `performed = 1` is the one thing that does not fit
that story, and it is **[UNKNOWN]** whether those were written by the factory,
by a service visit, or by `las-frontend`'s `RUN PID` menu item
(0x7e97aea). The table has no unique constraint, so `REPLACE INTO pid VALUES(…)`
appends rather than replaces — two rows means two runs. [READ, DDL and the
`REPLACE INTO pid VALUES(` literal at 0x7e4ec85]

**Practical consequence for the owner.** `/var/tuning.vxtune` is the only copy
of this instrument's calibration that has any content. `vxcal.db` is worth
keeping for the `pid` rows and for provenance, but it is not the irreplaceable
artefact — the 65 files under `tuning.vxtune/` are.

---

## 7. The calibration routine

### 7.1 `cal/cal.scm`, mapped

The CHICKEN trace strings give every call site with its source line. The
function boundaries below are read off the `limits-*` accessor calls, which each
open one calibration. [READ, trace map of `las-sc` 1.8.2; identical in `vxtune`,
`lassvc`, `vxmon`, `vxtest`, and identical in 1.5.0]

| lines | calibration | limits used | notable calls |
|---|---|---|---|
| 30, 39, 45 | record constructors | — | `make-linear-cal`, `lerp`, `make-las-voxcal` |
| 86–120 | `calibrate-gain` (generic) | — | `brent-search`, `las-vox-measure-mix-ampl`, `average-measurements` |
| 122–163 | second search variant | — | `meas`, `loop` |
| 166–213, 215–258, 261–305 | further search variants | — | |
| 307–341 | bias search | — | `las-vox-measure-stats`, `db->frac`, `section-search`, `brent-search` |
| 349–383 | `calibrate-main-vca-gain` | — | uses `las-send` (controller), not `las-vox-send` |
| 397–425 | gain pair → `make-linear-cal` | — | `calibrate-gain` ×2 |
| 429–509 | oscillator setup helpers | — | `las-oscl-set-hw-mode`, `las-osc-set-phase` |
| 516–628 | **main VCA** (`mainl`, `mainr`) | `limits-ovca` | `voice->mains`, `/a/stat/mainl`, `/a/stat/mainr` |
| 634–718 | **send VCA** (`sub1`, `sub2`) | `limits-svca` | `voice->subs`, `/a/stat/send1`, `/a/stat/send2` |
| 722–795 | **external input** | `limits-extin` | `/mode`, `/testosc/freq`, `/testosc/dac/2`, `/testosc/dac/3`, `/hw/mute`, `/a/in1`, `/a/in2`, `/mix/ext/ext0`, `/mix/ext/ext1` |
| 800–868 | **ring mod** | `limits-rm` | `las-search-freq`, `timeout-wrapper` |
| 876–954 | **noise** | `limits-noise` | |
| 965–1123 | **oscillator + pulse VCAs** | `limits-oscvca` | `set-pulse-duty!`, `calibrate-gain-gs`, `pulse-cal-prefix`, `oscl-cal-prefix` |
| 1131–1198 | **filter frequency** | — | `calibrate-freq`, `set-linear-cal`, `make-linear-cal` ×3 |
| 1206–1247 | **ladder resonance** | `limits-ladr` | |
| 1252–1298 | **ladder VCA gain** | `limits-gldr` | |
| 1306–1388 | **ladder high-pass bias** | `limits-bias-hp` | `las-search-freq`, `calibrate-bias-gs`, `las-vox-query`, `csosc#osc-value-int`, `q24->inexact` |
| 1400–1454 | **ladder VCA bias** | `limits-lad-bias` (`minimize-p`) | `calibrate-bias-gs` |
| 1491–1528 | measurement helpers | — | `las-vox-measure-stats` |
| 1541–1731 | **SVF 1 and SVF 2** | `limits-svfr` | `setup-svf`, `peak-search`, `svf-measure`, `cal-svff1`, `cal-svfr`, `zip`, `send-linear-cal/xy` ×4 |
| 1749–1796 | **SVF VCA gain** | `limits-gsvf` | |
| 1806–1857 | **SVF VCA bias** | `limits-svf-bias` (`minimize-p`) | `calibrate-bias-gs` |

`send-linear-cal/xy` at 1725–1730 is what pushes the **4-point SVF cutoff
breakpoint lists** (as opposed to a two-point line) to the card. [READ]

`cal/cal.scm:1367-1373` reads a card reply and converts it with `q24->inexact`
— **the calibration bus carries Q24 fixed point**, consistent with
`docs/arch/xmos-deep.md` §1. [READ]

### 7.2 The limit tables — real source on disk

`/etc/vxtune/cal-limits.scm` (4026 bytes) and `/etc/vxtune/mod-cal-limits.scm`
(1791 bytes) are **plain Scheme source**, shipped uncompiled, **byte-identical
between 1.5.0 and 1.8.2**. [READ, `diff`]

`vxtune` loads the first by absolute path at runtime (`/etc/vxtune/cal-limits.scm`
at 0x251829, with `cal/cal-limits.scm` as a build-time fallback at 0x251849).
[READ]

The `limits` record has thirteen fields — `svf-bias lad-bias ovca svca extin rm
noise ladr svfr gsvf gldr bias-hp oscvca` — each holding either a `cal-targets`
(`max maxt min mint`), a `bias-target` (`out-min out-max target tol`) or a
`minimize-p` (`start-point alpha precision`). [READ,
`mod-cal-limits.scm` `defstruct` block; the accessors `limits-*-set!` and
`cal-targets-*` are all present in the binaries]

`cal-limits.scm` defines **two** complete limit sets, `old-lim` and `new-lim`,
and then `(define lim (make-limits))` — i.e. the file as shipped falls through
to the `defstruct` defaults, and `old-lim`/`new-lim` are named alternatives.
[READ]

`new-lim` widens almost every ceiling relative to `old-lim`:

| target | `old-lim` | `new-lim` |
|---|---|---|
| `extin.max` | 0.0775 | `(* 2 0.0775)` |
| `rm.max` | `(db->frac -9)` | `(* 2 (db->frac -9))` |
| `noise.max` | `(db->frac -9)` | `(* 2.25 (db->frac -9))` |
| `svfr.max` | 0.9 | `(* 1.2 0.9)` |
| `gsvf.max` | `(db->frac -9.0)` | `(* 1.6 (db->frac -9.0))` |
| `gldr.max` | `(db->frac -9.0)` | `(* 2 (db->frac -9.0))` |
| `oscvca.max` | `(db->frac -9.0)` | `(* 2 (db->frac -9.0))` |
| `bias-hp.target` | 0.36 | 0.64 (with `; target: 0.72` commented out above it) |
| `ovca.mint` | 0.000005 | 0.00005 |
| `svca.min` | 0 | 0.00005 |

[READ, `/etc/vxtune/cal-limits.scm`]

**[INFERRED]** The factor-of-two ceilings are the limits for a hardware
revision with more gain. Two independent things point at it: `las-sc` carries
the log line `found VX with gain mods` beside the address `/vx/0/info/hwrev`
(0x1e5a00, 0x1e5a1d), and both `las-sc` and `vxtune` expose an option `-m` /
`--mod` documented as **"Flag for VX HW Mod."** / "Flag for VX Mods"
(las-sc 0x1e5cbe, vxtune 0x251bd1; the option names are the two-record run
`\xfe\x01\x00\x00\x01m` / `\xfe\x01\x00\x00\x03mod` immediately after each
description). [READ] Nothing read here shows the selection between `old-lim`
and `new-lim` being made — that binding is **[UNKNOWN]**.

`mod-cal-limits.scm` is a third set again (`bias-hp target: 0.47`,
`svfr` scaled 1.4/1.6). It is the only one of the three files that actually
contains the `defstruct` declarations; `cal-limits.scm` has them commented out
at the top. [READ] So `mod-cal-limits.scm` must be loaded first, or the
declarations must come from the compiled unit.

### 7.3 The search algorithms

`cal/search.scm` spans lines 25–546 and its callee set is: [READ, trace map]

```
clamp  sgn  meas  get-value  backoff-search  in-tol  loop  log  log*
take  sort  filter  compare  value  iota  collect-peaks  peak-search*
list->pairs  call/cc  interval-search  expand-interval  pid  saturate
early-return  brackets?  convert-meas  backoff  saturate  max
```

plus, from `cal.scm`'s own literal frame, the parameter names
`msg-prefix meas max-backoffs search settle-time sections navg rev? out-max
out-min in-goal out-point out-goal tol min-ampl mh ml start-point prec rate m`
and the constants `-0.4`, `-0.99`, `0.8`, `0.1`, `0.05`, `1e-5`,
`2.236067977499789805…` (= √5, the golden-section constant). [READ, `las-sc`
0x218806–0x218a83]

So the searches are: `brent-search` and `section-search` for gains,
`interval-search` with backoff for bracketed quantities, a `minimize-p`
gradient-style descent (`start-point`, `alpha`, `precision`) for the two bias
terms, `peak-search` for SVF resonance, `bisection-search` and `search-pd-bisection`
for tuning codes, and a `pid` / `saturate` pair. [READ, names]

`cal/jobs.scm` is a `gochan`-based job controller (`start-job-controller`,
`exec-job`, `job-log-stderr`, `make-job-log-entry`) — the calibrations run as
scheduled jobs with per-job logging. [READ]

---

## 8. The system calibrations — `lassvc` service mode

`lassvc` is a curses program driven from the front panel. Its two menu headers
are: [READ, `lassvc` 0x2a2904, 0x2a2969]

```
moog one service mode - main menu - use encoder to select a routine
moog one service mode - calibration menu - use encoder / arrow keys to select a routine
```

**Main menu** (0x2a2324–0x2a24b7): `calibration`, `panel validation`,
`phone home (alpha)`, `save cal data`, `serial number`, `mac address`,
`assign uuids`, plus a save-state indicator (`saved` / `unsaved` /
`save state: `), `running on target` / `running on host`, `vx cnt: `, and a
Moog logo in ASCII art. [READ]

**Calibration menu** (0x2a238a–0x2a2466), and its exact correspondence with
`system_cal_table`: [READ, both lists]

| menu item | `system_cal_table` column |
|---|---|
| cv out calibration | `cv_out` |
| cv in calibration | `cv_in` |
| expression / sustain input calibration | `pedal_in` |
| main out calibration | `main_out` |
| headphone out calibration | `headphone_out` |
| panel calibration | `front_panel_low`, `front_panel_mid`, `front_panel_high` |
| lhc calibration | `lhc` |
| noise source calibration | `noise` |

Ten flags, eight menu items, the panel one supplying three. Every column
accounted for.

The on-screen procedures, verbatim: [READ]

```
0x2a1b86  panel knob calibration is a 3 step process.
0x2a1b32    1) turn all knobs on the l/r panels fully ccw, and press the "cal-low" button.
0x2a1ade    2) turn all knobs on the l/r panels to center, and press the "cal-mid" button.
0x2a1a8a    3) turn all knobs on the l/r panels fully cw, and press the "cal-high" button.

0x2a17fc  lhc calibration is a 3 step process.
0x2a177f    1) turn the glide knob fully counter-clockwise, pull pitch and mod
             wheels fully "down" and press the "cal-low" button.
0x2a172f    2) return the knob and wheels to their center positions, and press the "cal-mid" button.
0x2a16a9    3) turn the glide knob fully clockwise, push the pitch and mod
             wheels fully "up" and press the "cal-high" button.

0x2a1c4d  noise source calibration
0x2a1be6    use the soft buttons to adjust the noise source until a reading of
             approximately 1.0 is obtained

0x2a1ddf  cv out calibration
0x2a1c6a    adjust the soft-pots and compare the output value to the measured voltage.

0x2a1f56  expression in calibration
0x2a1f02    connect cv out 1 to expr in 1, cv out 2 to expr in 2, and cv out 3 to sus in.

0x2a164c  headphone vca calibration
0x2a1617    connect hph l to cv in 1 and hph r to cv in 2.

0x2a1521  voice card external input calibration
0x2a14d3    connect sub l to combi jack and sub r to line in  (both 1/4" unbalanced)
```

That last one is the same cabling the user-facing voice-card calibration asks
for ("PLEASE CONNECT COMBO AND LINE INS TO SUB L AND SUB R OUTS.",
`las-frontend` 0x7e9783e). [READ]

`lassvc` also carries a `panel knob validation` screen naming every knob
(`lfo 1..4`, `osc 1..3`, `freq beat shp pwm mix`, `tri mod pls mod fm amt`,
`mstr clk arp rt seq rt detune noise a`, `vco 1..3 mix rmod mix noise mix`,
`svf ladder cutoff res filt mix filt eg amp eg cutoff mod eg fm ctl1 ctl2
send1 send2 master hph level pan`), a manual fan-control screen
(`/hw/fan/` with `pone ptwo pthree pfour` and `FAN 1/2/3`), and the phone-home
port list `22222 27650 27910 27950 44000 45000`. [READ, 0x2a1201–0x2a1a09,
0x2a29b6, 0x2a1841–0x2a188c]

The `lk`/`rk`/`lhck` calibrations use the **colon form**: `/cal/lk:cal_low`,
`/cal/lhck/pitch:cal_mid`, and so on, alongside the `:save` verb. [READ]

---

## 9. `vxtune`

3 066 108 bytes, same size in both firmwares, different bytes (recompiled), and
its CHICKEN trace map is **identical line for line**. [READ,
`diff <(traces 1.5.0) <(traces 1.8.2)` → empty]

### 9.1 Operations

The `operations` dispatch table (`operations-dispatch`, `operation-sym`,
`operation-proc`, `operation-desc`, `operation-doc`, `operation-options`) names:
[READ, `vxtune` 0x25341f–0x2535c9]

```
auto-tune   auto-cal   just-tune   tune   write   monitor   cal-op   cal-test
tcode0  tcode1  tcodef   lf-curve  freq-curve  autor-curve  sparse-curve
db-csv  csv-db   gen-c-freq-tables   set-op   error-log
```

`start_tune` uses `auto-tune`; `las-sc` and `las-frontend` both use `write`.
[READ]

### 9.2 The `--cal-op` list

```
Calibration operation to perform: oscvca, ladf, ladr, svf1f, svf1r, svf2f,
svf2r, fvca, ovca, flhp, rm, extin, vxnoise
```
[READ, `vxtune` 0x252aa5]

with the internal implementations `cal-oscvca`, `cal-noise`, `cal-svf`,
`cal-main-vcas`, `cal-send-vcas`, `cal-svfbias`, `cal-ladbias`, and the
"already done?" predicates `cal-have-oscvca?`, `cal-have-rm?`,
`cal-have-extin?`, `cal-have-noise?`, `cal-have-gldr?`, `cal-have-gsvf?`,
`cal-have-ladr?`, `cal-have-ladhp?`, `cal-have-svf1?`, `cal-have-svf2?`,
`cal-have-main-vcas?`, `cal-have-send-vcas?`, `cal-have-ladf?`,
`cal-have-biasfa?`, `cal-have-biasfb?`. [READ, 0x252f2e–0x253098]

`biasfa → cal-svfbias` and `biasfb → cal-ladbias` — **a third independent
confirmation that `fa` is the SVF and `fb` the ladder**, after the label strings
and the tap addresses in `docs/arch/xmos-deep.md` §2.2. [READ]

### 9.3 Options

[READ, `vxtune` 0x251907–0x2532c3; descriptions verbatim]

| option | description / default |
|---|---|
| `--no-results` | Flag to turn off Display Results screen |
| `--temp-set` | Temp to settle at after tcal |
| `--temp-high`, `--temp-low` | Tcal temperatures |
| `--averages` | Number of averages per reading |
| `--tcal-db` | Database file for temperature calibration |
| `--log-format` | s-exp or json (default s-exp) |
| `--log-file`, `--log-stderr` | |
| `-m` / `--mod` | Flag for VX Mods |
| `-q` / `--quiet` | |
| `-f` | Database file |
| `--force-all` | Force all operations to run, including requirements |
| `--force` | Force given operation(s) to run, overwriting previous results |
| `-o` | Oscillator number (**0..2**) |
| `--nvoices` | Number of voices present in system |
| `-v` / `--voice` | Voice number (**1..**) |
| `-c` / `--connect` | Target address (required) |
| `--outfile` | |
| `--no-send` | Do not send data, just send write command |
| `--tune` | Send only tuning data |
| `--cal` | Send only calibration data |
| `--ffsaw` | FFSAW mode |
| `--tempco0` | Use tempco instead of measured value |
| `--monitor`, `--duty`, `--base-pitch`, `--base-freq`, `--freq`, `--pitch`, `--method`, `--freq-table` | |
| `--start`, `--end`, `--increment` | defaults 16, 131, 0.5 |
| `--phase` | Phase to measure (0 or 1) |
| `--lf-inc` | LF increment code (default 0.000025) |
| `--lf-start-freq`, `--lf-end-freq` | defaults 20, 100 |
| `--lf-averages` | default 50 |
| `--mode` | Increment mode: pitch, freq, oct (default pitch) |
| `--ttol` | Temperature tolerance, °C (default 0.25) |
| `--tff` | Half-freq for temperature measurement, fast phase, Hz (default 5000) |
| `--tfreq` | Half-freq for temperature measurement, Hz (default 288) |
| `--tcode0`, `--tcode1`, `--tcodef` | DAC code overrides |
| `--span` | Minimum temperature reading span, °C (default 10) |
| high / low temperature targets | **default 50 °C / 41 °C** |
| `--no-stop`, `--measure-high`, `--measure-low` | |
| `--tpd-phf` | List of periods for temperature calibration of fast phase |
| `--cal-op` | §9.2 |
| `--no-comp` | (paired with `set-op`) |

**`-o` is 0-based and `-v` is 1-based.** [READ] The files on disk are `v0`…`v15`
and `-o1`…`-o3`, and the records store `las-vox.nr` 0…15 and `las-osc.nr` 1…3.
[READ] Anyone driving `vxtune` by hand should assume nothing about which
convention a given flag uses.

The default temperature targets (41 °C low, 50 °C high) do **not** match this
instrument's stored data (38.2 °C and 55.8 °C, span 17.6 °C). [READ] So the
factory pass used non-default targets, or the routine records where it actually
landed rather than where it aimed. **[UNKNOWN]** which.

### 9.4 Addresses `vxtune` uses beyond `/cal`

[READ, `vxtune` string table]

```
/tune/  /tune/l/  /tune/autor/  /save_tuning  /save_cal
/hw/  /hw/mute  /hw/hpf  /hw/autor
/mode  /ping  /v/voices  /info/{product,fwrev,git,versionb,uuid}
/vx/  /vx/0/info/hwrev
/mix/{o1,o2,o3,n,rm,ext}/{fa,fb}  /mix/ext/{ext0,ext1}  /mix/sub-en
/fa/{1,2}/{lp,bp,hp}  /fa/par  /fb/hp  /fb/tap  /fafb
/a/{in1,in2}  /a/in1-ins4  /a/in2-ins3  /a/stat/{mainl,mainr,send1,send2}
/stat  /statr  /sstat  /stat/mix  /stat/temp  /stat/decay
/therm/{t,min-som,min-vx,ttrip-sys,fan-normal-max,vx-temp-avg}
/testosc/freq  /testosc/dac/2  /testosc/dac/3
/o{1,2,3}/dbg/oscl_report  /dbg/oscl_ctl  /p{1,2,3}/d  /noise/mode
/fw/start  /fw/data  /fw/version
```

Note `/fw/start`, `/fw/data`, `/fw/version` — **`vxtune` can flash a voice
card**, not just `las-sc` and `lasfwu`. [READ]

Alongside the file/CSV column names `osc-{ph0,ph1,phf,ffsaw}-{tempcode,
sparsetbl,lftbl,codetbl,freqtbl,temptbl-h,temptbl-l,mt}` and `osc-pol`,
`osc-ffsaw-code`, which is how `db-csv`/`csv-db` name the `las-phase` fields.
[READ]

---

## 10. The shell layer

### 10.1 `config-las-spi`

`/usr/bin/config-las-spi`, 1047 bytes, **byte-identical in 1.5.0 and 1.8.2**.
[READ, `md5`]

Two subcommands. `xmos` hands the SPI1 bus to the XMOS and pulses its reset;
`som` holds the XMOS in reset and takes the bus back. [READ, full source]

```sh
config_spi_xmos() {          # SPI1 pins -> ALT5 (GPIO in), XMOS drives the bus
  devmem 0x20e0244 32 5      # IOMUXC KEY_COL0
  devmem 0x20e0248 32 5      # IOMUXC KEY_COL1
  devmem 0x20e0258 32 5      # IOMUXC KEY_ROW0
  devmem 0x20e025c 32 5      # IOMUXC KEY_ROW1
  devmem 0x20a8004 32 0x40008020   # GPIO4_GDIR
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
  echo 1 > /sys/class/leds/XMOS_RESET_N/brightness
}
config_spi_som() {           # XMOS held in reset, SoM drives the bus
  echo 0 > /sys/class/leds/XMOS_RESET_N/brightness
  devmem 0x20e0244 32 0 ; devmem 0x20e0248 32 0 ; devmem 0x20e0258 32 0
  devmem 0x20e025c 32 5
  devmem 0x20a8004 32 0x40008220
}
```

With no argument it prints `Please pass {xmos} or {som}` and exits 1 — **this
script does check its arguments**, unlike the calibration binaries. [READ] It
is nonetheless the one that leaves the instrument mute if you run `som` and stop:
`config_spi_som` **holds the XMOS in reset** and does not release it. [READ]
`docs/DANGER.md`'s Tier-2 entry is correct.

Callers: `start_tune` (`config-las-spi xmos`), `vxtune` (literal
`/usr/bin/config-las-spi` at 0x251861), and `las-sc` via
`vxfw-lib.scm:307` and `:312` (`CONFIG-LAS-SPI` + `system`). [READ]

### 10.2 `start_tune`

`/usr/bin/start_tune`, 2012 bytes, byte-identical in both firmwares.
Header: `#!/bin/bash` / `#Kevin Forte - 1/7/19 - (c) Moog Music Inc.` [READ]

The factory tuning sequence, in order: [READ, full source]

1. `read -p "Press ENTER to calibrate noise level. Press CTRL+C when finished."`
   then `lassvc -t 203.0.113.2:7770 -p 203.0.113.2:9100` — the **noise-source
   calibration is done by hand in service mode before anything else.**
2. If `/var/tuning.vxtune/v0` exists, warn "**continuing will overwrite**",
   prompt y/n, and on `y` do `rm -r /var/tuning.vxtune`.
3. Recreate the directory and write `(vxtune-db 3)`.
4. **Kill `las-watchdog`, `las-sc` and `las-frontend`**, looping until all three
   are gone.
5. `config-las-spi xmos` ; `sleep 3`
6. `vxtune auto-tune -c vc -f /var/tuning.vxtune`
7. `sync`, then `cp -R /var/tuning.vxtune /root/$(date +%m.%d.%y)_tune`

Two things worth stating plainly. The script **deletes the tuning directory
before regenerating it** — an interrupted `auto-tune` after step 2 leaves the
instrument with no tuning data at all. And it kills the watchdog first, which is
the mechanism `docs/DANGER.md` Tier 2 describes; here it is [READ] in Moog's own
script rather than inferred.

`las-frontend` does the same pairing but **restarts** the watchdog: the literals
`killall las-watchdog` (0x7e97a34) and `las-watchdog &` (0x7e976ad) are both
present in the calibration panel's string region. [READ] `docs/DANGER.md`'s
"killall las-watchdog … then write to the voice cards" is accurate for
`start_tune`; for the front-panel path there is a restart on the other side.
[READ for both literals; [INFERRED] that they bracket the same operation.]

---

## 11. Boot-time provisioning

### 11.1 What `las-sc` does on every boot

`S42sc` passes `--vxdb=/var/tuning.vxtune`. [READ] `sc/sc.scm:593-627` then:
[READ, trace map + the literal frame at `las-sc` 0x1e52e9–0x1e54d3]

```
:593  las-open ; :594 las-voice-count
:596  "checking voices for existing tuning / cal data"
:601  (las-query (osc <adr>))  ->  osc-value  ->  string-prefix?
:602  (las-query (osc <adr>))  ->  osc-value  ->  string-prefix?
:605  "voice <n> has tuning / cal data"    (or)
:609  (system "/usr/bin/vxtune write -c vc -f <vxdb> --nvoices 1 -q -v <n>")
:616  (system "… --nvoices 1 -q --tune -v <n>")
:623  (system "… --nvoices 1 -q --cal  -v <n>")
:626  "finished writing tuning / cal data to voices"  /  "no cards needed tuning / cal data"
```

with the procedures `tune-the-untuned`, `update-vx`, `gen-tuning-tables`.
[READ, symbol list]

**A card that comes up with no calibration data is silently re-provisioned from
`/var/tuning.vxtune` at boot.** [READ] A card with *wrong* data is not — the
check is presence, not correctness. That matches `cal-dispatch.md` §4.4 and is
now confirmed with the exact command lines.

### 11.2 `/load_cal` and `/load_tuning` — a correction

`docs/arch/cal-dispatch.md` §6.3 lists these under "**The leaves where zero
arguments is NOT safe**", as "reload verbs".

The evidence here points the other way. In `las-sc`'s literal frame they sit
between the provisioning log strings: [READ, `las-sc` file offsets]

```
0x1e53b4  "voice "
0x1e53c0  " has tuning / cal data"
0x1e53e5  /load_cal
0x1e53f3  /load_tuning
0x1e5406  "checking voice "
0x1e541a  "Network Unreachable - Power-cycling XMOS"
0x1e54d3  "checking voices for existing tuning / cal data"
```

and the two call sites that consume them, `sc/sc.scm:601` and `:602`, are both
**`las-query` with `argc 3` — zero OSC arguments — followed by `csosc#osc-value`
and `string-prefix?`.** [READ, trace map and my own argc scan]

**[INFERRED, moderately strong]** `/load_cal` and `/load_tuning` are queried
with no arguments to ask a card *whether it holds* calibration/tuning data; the
reply is a string that `string-prefix?` tests. They are how "voice N has tuning
/ cal data" is decided.

What is **not** established: that the specific literals at 0x1e53e5/0x1e53f3 are
the ones loaded at lines 601/602. That binding rests on literal-frame adjacency
to the surrounding log strings, not on reading the literal-frame slot indices.
**Do not treat this as settled.** But it is enough that the flat statement
"`/load_cal` is a reload verb, do not probe it" should not be relied on either.
Whichever way it resolves, `/save_cal` and `/save_tuning` remain unambiguous
verbs and must not be sent.

`las-sc` holds **no** `/save_*` literal at all. [READ, `grep`] Only `vxtune`
and `las-frontend` do.

### 11.3 `--ofs-cache`, an undocumented third persistence path

`las-sc`'s option table, verbatim: [READ, `las-sc` 0x1e5dc3]

```
Offset cache file. If given, offset data are periodically gathered from the VX
and written to this file. At startup, offsets are transmitted back to the cards.
```
option name `ofs-cache` (0x1e5e78, 0x1e5e9a).

**`S42sc` does not pass it**, in either firmware. [READ] So the mechanism is
inert on a stock instrument. What "offsets" are, and whether they overlap the
`/cal` values, is **[UNKNOWN]**. Nothing in this repository mentions it. It is
the most interesting unexplored thread in this region.

---

## 12. Writes — what actually writes what

This is the section to be careful in.

### 12.1 The arity question, independently reproduced

`docs/arch/cal-dispatch.md` establishes that `las-sc`'s OSC calls carry their
Scheme argument count in a literal `mov r0,#N` after the `C_trace` call, that
`N-2` is the number of OSC arguments, and that `cal/cal.scm:751` is
`(las-send (csosc#osc "/hw/mute" 0))`.

**Reproduced here on the 1.8.2 binary, by locating the trace string's
literal-pool word rather than by the original method.** [READ]

`cal/cal.scm:751: csosc#osc` is at file 0x21c571 → VMA 0x22c571. That word
appears exactly once in `.text`, at file 0x133188 (VMA 0x143188), inside the
literal pool of the function that begins at VMA 0x143138:

```
143138: eb...        bl   C_trace
14313c: e59f1050     ldr  r1, [pc, #0x50]     -> 0x00284548   (literal frame base)
143148: e3a00004     mov  r0, #4              <-- argc 4  =>  ONE OSC argument
143150: e59132b8     ldr  r3, [r1, #0x2b8]    -> csosc#osc
143158: e8850014     stm  r5, {r2, r4}        -> a[0]=proc  a[1]=continuation
14315c: e591368c     ldr  r3, [r1, #0x68c]    -> the address literal
143164: e5853008     str  r3, [r5, #0x8]      -> a[2]
143168: e3a03001     mov  r3, #1              -> CHICKEN fixnum 1  ==  the integer 0
14316c: e585300c     str  r3, [r5, #0xc]      -> a[3]
143174: e12fff33     blx  r3
```

Same VMA, same `mov r0,#4`, same slot offsets `0x2b8` and `0x68c` as
`cal-dispatch.md` reports for 1.5.0; only the literal-frame base moved
(0x2842f8 → 0x284548). [READ]

And the matching query, `cal/cal.scm:521` at VMA 0x1475e8: [READ]

```
1475e8: bl   C_trace
1475ec: ldr  r1, [pc, #0x44]     -> 0x00284548
1475f8: mov  r0, #3              <-- argc 3  =>  NO OSC arguments
147600: ldr  r3, [r1, #0x2b8]    -> csosc#osc
14760c: ldr  r3, [r1, #0x584]    -> the address literal
147614: str  r3, [r4, #0x8]      -> a[2]      (nothing at a[3])
14761c: blx  r3
```
paired in the trace table with `cal/cal.scm:521: las-query`.

**A matched pair on one binary, hand-read: one argument is a set, zero arguments
is a query.** [READ]

I also confirmed by hand that `sc/sc.scm:342` is `mov r0,#3` at VMA 0x3608c with
a single argument stored from `lf[0xc8c]` — agreeing with `cal-dispatch.md`.
[READ]

An automated scan over all 159 resolvable `csosc#osc` trace strings in `las-sc`
1.8.2 gives `cal/cal.scm` = **3 sites with argc 3 (lines 521, 594, 686) and 37
with argc 4**, against `cal-dispatch.md`'s 3 and 46. The three argc-3 lines are
identical. My scan resolves fewer sites (it demands a unique literal-pool
reference and mis-attributes where two `C_trace` calls share a pool region — it
gets `sc/sc.scm:342` wrong for exactly that reason), so **treat my counts as a
lower bound and `cal-dispatch.md`'s as the better figure.** The qualitative
result — cal.scm is overwhelmingly one-argument sets with a handful of
zero-argument queries — replicates. [READ]

### 12.2 What is *not* settled, and stays unsettled

**The firmware's own dispatch rule.** Nothing here changes
`cal-dispatch.md` §7: the XMOS address table is behind an unsolved encoding, no
xcore disassembler is available, and the host-side arity convention is exactly
that — a convention. `las-watchdog` sends `/v/voices` with `,i 1` and reads the
reply, so the firmware demonstrably does not store every one-argument message.
[READ, `cal-dispatch.md` §5, not re-verified here]

I looked for a counter-example inside the `/cal` namespace specifically and
found none: `vxmon`, the one program whose job is reading, has only **four**
`las-vox-query` sites in its own module (`mon/vxmon-lib.scm:458-461`) and does
not query `/cal` leaves. [READ] Consistent with `cal-dispatch.md` §6.2's finding
that the card will not report a trim.

### 12.3 The persistence map

| artefact | written by | via | can OSC reach it? |
|---|---|---|---|
| a card's **live** trim | `cal.scm` searches, `las-frontend`'s `LASVoiceCalibrator` | `/cal/<leaf>[/l\|/h\|/x\|/x0\|/x1\|/y0\|/y1] <value>` | **yes** |
| a card's **persistent** cal | the commit verb | `/save_cal` | **yes** |
| a card's **persistent** tuning | the commit verb | `/save_tuning` | **yes** |
| controller / panel cal | `lassvc`, `las-frontend` | `/cal:save`, `/cal/save` | **yes** |
| `/var/cal/vxcal.db` | `las-frontend` only | plain SQL (`REPLACE INTO …`) | **no** |
| `/var/tuning.vxtune/*` | `vxtune` only | CHICKEN `s11n` to files | **no** |

[READ for every row.] The two host-side files are unreachable by OSC. This
confirms `cal-dispatch.md` §4.1 and §4.5, and adds the `tuning.vxtune` row,
which that document did not state.

### 12.4 Verbs — the actual hazard

A verb has no value to omit, so a zero-argument message *is* the action. The
complete verb list for this region, all [READ]:

```
/save_cal        /save_tuning        (voice card, commit)
/cal:save        /cal:load           /cal:cal_default     (controller / panel)
/cal/save        /cal/load
/cal/lk:cal_low  /cal/lk:cal_mid     /cal/lk:cal_high     (left panel capture)
/cal/rk:cal_low  /cal/rk:cal_mid     /cal/rk:cal_high     (right panel capture)
/cal/lhck/{pitch,mod,glide}:cal_{low,mid,high}            (LHC capture)
/cal/lhck/xy:cal_lr   /cal/lhck/xy:cal_ul                 (XY pad corners)
/fw/start        /fw/data            /fw/version          (card flash)
```

`/cal:cal_default` is the one whose name says outright what it does. **None of
these was in the 2026-09-02 303-address sweep** — [READ,
`captures/sweep/core.txt` contains no colon-form address and no `/save_*`.]

The `:cal_low` / `:cal_mid` / `:cal_high` family deserves its own line: these
capture *whatever position the controls are currently in* as a calibration
point. Sending `/cal/lhck/pitch:cal_high` with the pitch wheel at rest would
record rest as the top of travel. Recoverable by re-running the service-mode
routine, but only by someone who knows to.

---

## 13. Cross-check against `docs/DANGER.md`

Requested explicitly. Taking its calibration claims one at a time.

| DANGER.md claim | verdict here |
|---|---|
| "`/var/cal/vxcal.db` and `/var/tuning.vxtune` hold this unit's per-card analog calibration, unique to its hardware." | **Half right.** `tuning.vxtune` does. `vxcal.db` on *this* instrument holds no measurements at all (§6.3). [READ] |
| "the `/cal/*` OSC namespace (62 leaves)" | **62 is `las-sc`'s count.** The namespace is 223 literals; `las-frontend` alone has 166. [READ] |
| "Written by: `vxtune write … [--tune\|--cal]`, the `/cal/*` OSC namespace, `/load_cal`, `/load_tuning`, and a calibration-DB reset screen" | `/load_cal` and `/load_tuning` appear to be **queries**, not writers (§11.2). The rest holds. The list omits `/save_cal`, `/save_tuning`, `/cal:save` and `/cal:cal_default`, which are the actual commit verbs. |
| "It measures the instrument's own output through its own inputs" | **Confirmed** [READ] — "PLEASE CONNECT COMBO AND LINE INS TO SUB L AND SUB R OUTS.", and the system calibrations loop CV outs into CV/expression ins and headphones into CV ins (§8). |
| "user-runnable voice-card calibration, added in firmware 1.5.0" | The **panels and the routine are present and identical in 1.5.0 and 1.8.2** [READ]. This pass has no evidence about when they were added, since 1.4.0 was not read. |
| "warm up 45 minutes … allow at least 4 hours" | `las-frontend` says **`FOR OPTIMAL STABILITY, SYSTEM SHOULD WARM UP FOR 45 MINUTES`** and **`THIS PROCESS WILL TAKE UP TO TEN MINUTES`**. [READ, cited in `xmos-deep.md` §2.5; the 45-minute string is in the 1.8.2 binary] Ten minutes is per voice; sixteen voices plus temperature settling is where four hours comes from. [INFERRED] |
| "CALIBRATIONS = 17/17" | **Confirmed**: exactly seventeen result rows (§3). [READ] |
| "`killall las-watchdog` … then write to the voice cards" | **Confirmed in Moog's own `start_tune`.** [READ] But `las-frontend` also carries `las-watchdog &`, so its path restarts the watchdog (§10.2). |
| "any `/cal` address with one argument permanently writes a voice card's trim table — half confirmed, half refuted" | **The refutation stands and is now better supported**: the set/commit split is [READ] in two independent codebases via `/save_cal` and `/save_tuning`, not only inferred from the search loop. |
| "Zero-argument reads of `/cal` are demonstrably safe" | Unchanged. The 47-leaf sweep is [TESTED] evidence in `captures/sweep/core.txt`. Note that all 47 are *quantity* leaves; none of the verbs in §12.4 was in it. |
| "`config-las-spi som` without the reverse" | **Confirmed from source** (§10.1). [READ] |
| "No signature or checksum check anywhere" (voice-card flash) | Not re-examined here, except to add that **`vxtune` also carries `/fw/start`, `/fw/data`, `/fw/version`** — a third program that can flash a card. [READ] |

### One thing DANGER.md should gain

**The `:cal_low` / `:cal_mid` / `:cal_high` capture verbs.** They are reachable
from the LAN on port 7770 or 9100 through the DNAT rules, they fire on a
zero-argument message, and they overwrite the front-panel and left-hand-controller
calibration with whatever the controls happen to be doing. They are not
irreversible — service mode can redo them — but they will make the instrument
feel broken, and nothing currently warns about them.

---

## 14. Conflicts with existing documents

Reported, not fixed.

1. **`docs/DANGER.md`** — "`/var/cal/vxcal.db` and `/var/tuning.vxtune` hold this
   unit's per-card analog calibration." On this instrument `vxcal.db` contains
   zero measurements (§6.3). The sentence overstates its importance and
   understates `tuning.vxtune`'s.
2. **`docs/DANGER.md`** — "the `/cal/*` OSC namespace (62 leaves)". 62 is the
   `las-sc` figure; the namespace is 223 literals across the ten binaries (§2.1).
3. **`docs/DANGER.md`** and **`docs/arch/cal-dispatch.md` §6.3** — both list
   `/load_cal` and `/load_tuning` as verbs / writers. The evidence in §11.2 is
   that they are queried with zero arguments and their replies string-matched.
4. **`docs/arch/cal-dispatch.md` §6.3** — "the full address they hang off
   (`/cal:save`? `/cal/save`? …) is **[INFERRED]** at best." All five spellings
   are complete literals in `lassvc` and `las-frontend` (§2.4). This can be
   promoted to [READ].
5. **`docs/arch/cal-dispatch.md` §3** — records `sc/sc.scm:342` as argc 3 and
   `:344` as argc 4. Correct; my automated scan disagreed and my scan is wrong.
   Recorded so the disagreement is not rediscovered later.
6. **`docs/arch/cal-dispatch.md` §2.2** — "46 are argc 4 … one, line 440, reads
   as argc 2". My scan resolves 37 argc-4 sites and does not see line 440 at
   all. Neither figure is a clean [READ]; the three argc-3 lines (521, 594, 686)
   agree exactly and are the load-bearing part.
7. **`docs/arch/xmos-deep.md` §2.3** — "`las-voxcal` is a CHICKEN record; its
   accessors appear in the binary **in declaration order**." The *accessor
   symbol* order in `vxtune` is `o1 p1 o2 p2 o3 p3 rm noiseccw noisecw ladr gsvf
   gldr extin mainl mainr sub1 sub2 ladf svf1f svf1r svf2f svf2r bias-gldr
   bias-gsvf ladhp` — **not** declaration order, and it omits `fm`. The order
   `xmos-deep.md` states is nevertheless **correct**; it is confirmed here from
   the interned field-name run and from `cal/vxtune.scm:625-678` (§4.2). The
   conclusion is right; the stated method is not reliable and should not be
   reused.
8. **`docs/arch/xmos-deep.md` §2.5** — "the 17 rows … the identification with the
   database's row count is [INFERRED] but the count matches exactly." The
   database's `cal_results` has **25** result columns, not 17 (§3). The
   seventeen is the *screen's* list. The inference should be withdrawn; the
   17-row list itself is fine.
9. **`docs/arch/xmos-deep.md` §2.3** — "`linear-cal = {x, x0, x1, y0, y1}` — a
   two-point line fit." Confirmed [READ] (§4.1). Adding: `svf1f` and `svf2f` are
   **not** `linear-cal` at all but 4-point breakpoint lists, and `ladhp`,
   `bias-gsvf`, `bias-gldr` are bare doubles. The table in that section implies
   all 26 are `linear-cal`.
10. **`docs/INTERNAL-DO-NOT-DISTRIBUTE.md`** — "Per-voice `las-voxcal`: 26
    payload slots = 20 six-slot linear-cal records + 2 four-element `[x,y]`
    breakpoint lists + 3 doubles + 1 unset." **Exactly right**, independently
    reproduced here. Same file: "`vxcal.db`: 38 tables, 35 empty; `cal_results`
    16 rows all-zero; `system_cal_table` 1 row all-zero" — also right, and I
    would add that the 36th non-empty table is `pid`, with two rows of
    `performed = 1`.
11. **`captures/backup/README.md`** — "unique to this unit's analog hardware and
    **cannot be regenerated without factory equipment**." `docs/DANGER.md` has
    already retracted this; the README still says it. And `start_tune` shows the
    factory procedure needs only two ¼" cables and a terminal (§10.2).

---

## 15. Open questions

* What `/cal/cv/{2,3,4,5}` address. Eight indices for four rear CV outs, with
  `/cal/cv/6` and `/cal/cv/7` bound to `/a/stat/cvin0` and `/a/stat/cvin1`.
* Whether `ladhp` and `cal-limits.scm`'s `bias-hp` are the same quantity.
* Whether the card accepts both `/cal/<leaf>/l` and `/cal/<leaf>/y0`.
* Whether `ladf` can carry a 12-point table on the wire, as `vxcal.db` declares.
* What selects `old-lim` vs `new-lim` vs the `defstruct` defaults.
* What `--ofs-cache` offsets are.
* Whether `autor` (in `vxcal.db`) and `ffsaw` (in `tuning.vxtune`) are the same
  oscillator mode.
* Why `gsvf` and `gldr` are uncalibrated on all sixteen cards of this
  instrument, and whether that is normal.
* Whether `mainl`/`mainr`/`sub1`/`sub2` `y1 = 0.0` is a result or a failure.

---

## 16. Validation plan

**Read-only. Not run. Every one of these is safe by inspection — they read files
or process state on the SoM and send nothing to the voice bus.** Nothing here
requires the audio stack to be stopped.

### 16.1 Confirms §6.3 — the DB is empty and the tuning data is the real asset

```sh
ssh root@<ip> "sqlite3 -header -column /var/cal/vxcal.db \
  \"SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid;\""
ssh root@<ip> "for t in \$(sqlite3 /var/cal/vxcal.db \
  \"SELECT name FROM sqlite_master WHERE type='table';\"); do \
    printf '%-22s %s\n' \$t \$(sqlite3 /var/cal/vxcal.db \"SELECT COUNT(*) FROM \$t;\"); done"
ssh root@<ip> "sqlite3 /var/cal/vxcal.db 'SELECT * FROM pid; SELECT * FROM cal_info;'"
```
Expect: 38 tables; only `cal_results` (16), `pid` (2) and `system_cal_table` (1)
non-empty; `cal_info` empty.

### 16.2 Confirms §5.1 — the tuning directory

```sh
ssh root@<ip> "ls -la /var/tuning.vxtune | head -20; cat /var/tuning.vxtune/vxtune-db; \
               ls /var/tuning.vxtune | wc -l"
ssh root@<ip> "md5sum /var/cal/vxcal.db /var/tuning.vxtune/*"
```
Expect 65 entries, `(vxtune-db 3)`, and md5s matching
`captures/backup/calibration-20260907-222301.md5`. **A mismatch means something
has rewritten the calibration since 2026-09-07 and should stop all other work.**

### 16.3 Confirms §5.3 — the byte-level format, without copying the data off

```sh
ssh root@<ip> "head -c 64 /var/tuning.vxtune/v0 | od -An -tx1"
```
Expect the file to begin
`05 06 00 00 08 0d 04 07 00 00 42 6c 61 73 2d 76 6f 78 03 01 00 00 00 08 08 08 05 1b 00 00 08`
— structure(6), symbol "las-vox", fixnum 0, three `#f`, structure(27).

### 16.4 Confirms §11.3 — `--ofs-cache` is not in use

```sh
ssh root@<ip> "cat /proc/\$(pidof las-sc)/cmdline | tr '\0' ' '; echo"
ssh root@<ip> "ls -la /var/*.ofs /var/cal/ 2>/dev/null"
```
Expect no `--ofs-cache` in the command line.

### 16.5 Confirms §1.3 — the DNAT exposure is live

```sh
ssh root@<ip> "iptables -t nat -L PREROUTING -n -v"
ssh root@<ip> "cat /proc/sys/net/ipv4/ip_forward"
```
Expect the four UDP DNAT rules to 203.0.113.2 and forwarding enabled.

### 16.6 Confirms §7.2 — the limit files on the live unit

```sh
ssh root@<ip> "md5sum /etc/vxtune/cal-limits.scm /etc/vxtune/mod-cal-limits.scm"
```
Compare against the rootfs copies; expect a match, since 1.5.0 and 1.8.2 are
byte-identical.

### 16.7 The zero-risk test of the volatile/persistent split

Unchanged from `cal-dispatch.md` §7, and still the right experiment: record
`md5sum /var/cal/vxcal.db /var/tuning.vxtune/*` before and after a normal play
session and a power cycle. Stability across both is what §12.3 predicts. **No
packets are sent to the voice bus.**

### 16.8 Explicitly NOT proposed

Any `/cal` probe, zero-argument or otherwise. The 2026-09-02 sweep already
covered 47 quantity leaves and returned nothing useful; the remaining
unexplored addresses are disproportionately the verbs in §12.4. There is nothing
left to learn from the live bus in this region that is worth the risk.

---

## 17. Unexplored

* **`vxtest`** (2 568 916 bytes, 118 `/cal` literals — more than `vxtune`). Read
  only for its address list. It is the hardware test harness and almost certainly
  carries the pass/fail thresholds for the 17 calibrations.
* **`vxreport`** (764 204 bytes) — not opened beyond confirming it links the
  same library.
* **`vxmon`** — only the source map and its four query sites.
* **`las-frontend`'s `LASVoiceCalibrator`** — I read its progress and log
  strings and its class names, not its code. It is a complete second
  implementation of the routine and deserves its own pass.
* **`cal/vxtune-db.scm`** (121 traces) — the file-format writer. I decoded the
  format from the data instead of from the code, so the two have not been
  cross-checked.
* **`cal/jobs.scm`** (100 traces) — the job controller; names only.
* **`las/las-measure.scm`** (360 traces) — the measurement layer. Only the names
  that leak into `cal.scm` were followed.
* **The CHICKEN literal-frame index.** I could not decode the blob far enough to
  read `lf[0x68c]` and confirm for myself that it is `/hw/mute`; the blob
  contains non-string records (`\xfe\x01` symbols, `\xfe\x03` pairs, `\xfe\x55`
  flonums and at least two tags I did not identify, `\xfe\xff\x0e` and
  `\xfe\xff\x0a`) and my chaining parser stops at the first. Doing this properly
  would let every `lf[...]` reference in every `C_trace` site be resolved
  mechanically, which would settle §11.2 and a good deal else.
* **The `autor` tables.** Present throughout `vxcal.db` and `vxtune`, absent
  from `tuning.vxtune`. Not chased.
* **`/cal/decay`, `/cal/noise`, `/stat/decay`.** Identified, not understood.
* **The XMOS side.** Unchanged: the address table is still behind the unsolved
  encoding, and nothing here attempts it. Note that 1.8.2 ships **new** card and
  controller firmware — `app_vx_10M_v2.2.1.bin` (commit `02619910`, 2025-09-10)
  and `app_las_v2.2.2.bin` (commit `d888eec9`, 2025-09-11), from
  `gitlab.inmusicbrands.com/moog/hardware/moog-one/{vx-fw,las-fw}` [READ,
  `usr/share/xmosfw/app_{vx,las}_gitinfo.json`] — against 1.5.0's v2.1.0 /
  v2.1.2 from `gitlab.com/moogmusic/vx-fw` (2021-11-03). Those images have not
  been diffed.
* **1.4.0.** The A/B slot on `mmcblk2p2` was not read, so nothing here can date
  when the user-runnable calibration appeared.

---

## 18. Reproducing everything above

```sh
R8="captures/firmware-1.8.2/rootfs-1.8.2"
R5="captures/rootfs-1.5.0"

# --- the namespace, and that it did not change ---------------------------
cals(){ for b in las-sc vxtune las-frontend lassvc vxtest vxmon vxping vxreport \
                 las-watchdog las-frontpanel-poll; do
          strings -a "$1/usr/bin/$b" | grep -oE '^/cal([/:][A-Za-z0-9_]+)*$'
        done | sort -u; }
diff <(cals "$R5") <(cals "$R8")      # empty; 223 lines on each side
cals "$R8" | wc -l                    # 223

# --- the source-line trace maps, and that they did not change ------------
tm(){ strings -a "$1" | grep -oE '^[A-Za-z0-9_/.-]+\.scm:[0-9]+: [^ ]+$' | sort -u; }
diff <(tm "$R5/usr/bin/vxtune") <(tm "$R8/usr/bin/vxtune")     # empty
# las-sc differs ONLY in the build temp-dir prefix on three sc/*.scm files;
# every cal/*, las/*, sc/sc.scm, mon/* and vxfw-lib.scm line is identical:
diff <(tm "$R5/usr/bin/las-sc" | grep -v '^/tmp/') \
     <(tm "$R8/usr/bin/las-sc" | grep -v '^/tmp/')             # empty
tm "$R8/usr/bin/las-sc" | grep '^cal/cal.scm' | sort -t: -k2,2n   # §7.1

# --- the record definitions, verbatim ------------------------------------
python3 - <<'EOF'
b=open("captures/firmware-1.8.2/rootfs-1.8.2/usr/bin/las-sc","rb").read()
print(repr(b[0x218737:0x218806]))   # linear-cal + las-voxcal field names
print(repr(b[0x207000:0x207096]))   # las-phase + las-osc field names
print(repr(b[0x204aa0:0x204b20]))   # las-vox accessors
EOF

# --- the /hw/mute call site, argc 4 --------------------------------------
OBJ=/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/llvm-objdump
$OBJ -d --triple=armv7-none-linux-gnueabihf \
    --start-address=0x143130 --stop-address=0x143180 "$R8/usr/bin/las-sc"
$OBJ -d --triple=armv7-none-linux-gnueabihf \
    --start-address=0x1475e0 --stop-address=0x147620 "$R8/usr/bin/las-sc"   # argc 3

# --- the commit verbs ----------------------------------------------------
strings -a -t x "$R8/usr/bin/vxtune"  | sed -n '/250132/,/250203/p'
strings -a -t x "$R8/usr/bin/lassvc"  | grep -E '/cal[:/](save|load)'
strings -a -t x "$R8/usr/bin/las-frontend" | grep -E '/cal:(save|load|cal_default)'

# --- vxcal.db ------------------------------------------------------------
mkdir -p /tmp/cal && tar xzf captures/backup/calibration-20260907-222301.tar.gz -C /tmp/cal
(cd /tmp/cal && md5sum -c ../../captures/backup/calibration-20260907-222301.md5)  # 66 OK
sqlite3 /tmp/cal/cal/vxcal.db .schema
for t in $(sqlite3 /tmp/cal/cal/vxcal.db \
      "SELECT name FROM sqlite_master WHERE type='table' ORDER BY rowid;"); do
  printf '%-22s %s\n' "$t" "$(sqlite3 /tmp/cal/cal/vxcal.db "SELECT COUNT(*) FROM \"$t\";")"
done
```

### The `tuning.vxtune` decoder

Self-contained. Consumes every one of the 65 files completely.

```python
import struct, sys
class R:
    def __init__(s, b): s.b = b; s.i = 0; s.tab = []
    def u8(s):  v = s.b[s.i];                        s.i += 1; return v
    def u32(s): v = struct.unpack_from('<I', s.b, s.i); s.i += 4; return v[0]
    def i32(s): v = struct.unpack_from('<i', s.b, s.i); s.i += 4; return v[0]

IMM = {0x01: '()', 0x02: '#t', 0x08: '#f',
       0x09: '#!eof', 0x0b: '#!void', 0x0c: '#!default'}

class Sym(str): pass

def rd(r):
    off = r.i; t = r.u8()
    if t in IMM: return IMM[t]
    if t == 0x03:                      # fixnum, CHICKEN-boxed  (n<<1)|1
        w = r.i32()
        return (w - 1) >> 1 if (w & 1) else ('RAW', w)
    if t == 0x0a: return ('REF', r.u32())          # shared-object back-reference
    if t == 0x0d:                                   # symbol: name object follows
        v = Sym(rd(r)); r.tab.append(v); return v
    if t in (0x04, 0x05):                           # block; 0x05 is referenceable
        h = r.u32(); typ = (h >> 24) & 0xff; size = h & 0xffffff
        slot = len(r.tab); r.tab.append(None)
        if   typ == 0x55: v = struct.unpack_from('<d', r.b, r.i)[0]; r.i += 8
        elif typ == 0x42: v = r.b[r.i:r.i+size].decode('latin1');    r.i += size
        elif typ == 0x48: v = ('BYTES', r.b[r.i:r.i+size]);          r.i += size
        elif typ == 0x03: a = rd(r); d = rd(r); v = ('PAIR', a, d)
        elif typ == 0x08: v = ('S', [rd(r) for _ in range(size)])    # record
        elif typ == 0x00: v = ('V', [rd(r) for _ in range(size)])    # vector
        else:             v = ('UNK', hex(typ), size)
        r.tab[slot] = v; return v
    raise ValueError('unknown tag %#x at %#x' % (t, off))

def res(x, r, d=0):
    if isinstance(x, tuple):
        if x[0] == 'REF':
            o = r.tab[x[1]]
            return o if isinstance(o, (str, float, int)) else ('#%d' % x[1],)
        if x[0] == 'PAIR':
            out = []; c = x
            while isinstance(c, tuple) and c[0] == 'PAIR':
                out.append(res(c[1], r, d+1)); c = c[2]
            if c != '()': out.append(('.', res(c, r, d+1)))
            return out
        if x[0] in ('S', 'V'): return (x[0], [res(s, r, d+1) for s in x[1]])
    return x

def load(path):
    b = open(path, 'rb').read(); r = R(b); out = []
    while r.i < len(b): out.append(res(rd(r), r))
    assert r.i == len(b), 'trailing bytes'
    return out, r

VOXCAL = ("o1 p1 o2 p2 o3 p3 rm extin svf1f svf1r svf2f svf2r ladf ladr ladhp "
          "bias-gsvf gsvf bias-gldr gldr mainl mainr sub1 sub2 fm "
          "noisecw noiseccw").split()
PHASE  = "id stop sparsetbl temptbl temptbl-l temptbl-h tempcode mt lftbl codetbl freqtbl".split()
LINCAL = "x x0 x1 y0 y1".split()
# las-vox = (nr osc1 osc2 osc3 cal)   las-osc = (vox nr pol ph0 ph1 phf ffsaw ffsaw-code)

if __name__ == '__main__':
    o, r = load(sys.argv[1])
    import pprint; pprint.pprint(o, width=150)
```

Usage:

```sh
python3 s11n.py /tmp/cal/tuning.vxtune/v0        # one las-vox + las-voxcal
python3 s11n.py /tmp/cal/tuning.vxtune/v0-o1     # one las-osc + four las-phase
```

Nothing in this file requires, or should be checked against, a powered
instrument, except the read-only commands in §16 — which a human should run.
