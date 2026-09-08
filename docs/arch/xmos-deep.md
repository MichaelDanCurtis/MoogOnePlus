<!-- docs/arch/xmos-deep.md -->
# The XMOS side: voice controller and voice cards

A second pass over the half of the Moog One that the Linux box does not run.
Nothing here was obtained from a powered instrument. Every claim is graded
`[READ]` (read directly out of a file, with the file and location named),
`[TESTED]` (someone observed it on hardware in an earlier session — cited),
or `[INFERRED]` (reasoning, stated as such).

This file **extends and in three places corrects**
[`xmos-firmware.md`](xmos-firmware.md). It does not edit it. Section 8 lists
every confirmation and conflict explicitly.

The single most important thing in this pass is a file nobody had opened:
**`/usr/share/vx_ee.scm`**, the LAS VX Expression Engine's variable list, 13,134
bytes of commented Scheme, recovered from the v1.5.0 rootfs image. It is the
authoritative machine description of the modulation engine, and it is quoted at
length in §4.

---

## 0. The one command line that unlocked this pass

`captures/arch-harvest/runtime-state.txt` line 103, a `ps` snapshot from the
live unit: `[READ]`

```
/usr/bin/las-sc -t vc -f localhost:7775 -l localhost:9300 \
  --vxfw=/usr/share/xmosfw/app_vx_10M_v2.1.0.bin \
  --vxdb=/var/tuning.vxtune \
  --vcfw=/usr/share/xmosfw/app_las_v2.1.2.bin \
  --vcfv=33620735 \
  --temp \
  --expr-syms=/usr/share/vx_ee.scm \
  --panel-state=localhost:9500 -q
```

Four things fall out of it:

* **`--expr-syms=/usr/share/vx_ee.scm`.** `las-sc`'s help text for this option is
  `File containing symbols for use in expressions.` `[READ, las-sc strings]`.
  The prefix `vx_` names the **voice card**, not the controller. The modulation
  expression language's symbol table is a file on the Linux filesystem, and the
  engine it describes runs on the cards.
* **`--vxdb=/var/tuning.vxtune`** — the tuning store is passed to `las-sc`, not to
  a separate tool, on every boot.
* **`--vcfv=33620735`** = `0x020102FF`. The voice-card image carries `0x020100FF`
  at offset 0x14 (`xmos-firmware.md` §1, `[READ]`). So the firmware version word
  is **`MM mm pp FF`, big-endian**: `02 01 02 FF` = v2.1.2 (controller),
  `02 01 00 FF` = v2.1.0 (card). `[READ]` for both values, `[INFERRED]` for the
  field layout that reconciles them.
* `-t vc` — the target of `las-sc`'s LAS protocol is the **voice controller**.

And from line 115, `las-frontend`'s argv: `[READ]`

```
las-frontend --host-paneloutput=203.0.113.2 --host-performance=vc
             --host-oleds=203.0.113.2 --host-systemclock=vc --host-vc=vc
             --cookie=1 --startup-coordination --affinity-mask=1 --affinity-panel=1
```

The front panel, the OLEDs, the performance stream **and the system clock** all
terminate on the XMOS voice controller at `203.0.113.2`. `[READ]`

---

## 1. The protocol between the i.MX6 and the XMOS

### 1.1 Three links, not one

| link | carrier | direction | contents |
|---|---|---|---|
| control | USB gadget `usbint`, IP, 203.0.113.1 ↔ .2 | both | OSC over UDP |
| audio | ESAI / TDM, XMOS is clock master | both | `S24_LE`, 8 channels, 48 kHz `[READ]` |
| clock | UDP, its own socket | host → VC, VC → host | `LTRQ` / `LTRS` binary frames |

The ALSA line is exact, from `runtime-state.txt`: `[READ]`

```
00-00: HiFi xmos-codec-0 :  : playback 1 : capture 1
access: RW_INTERLEAVED   format: S24_LE   channels: 8
rate: 48000 (48000/1)    period_size: 256   buffer_size: 512
```

and `scsynth` on the same snapshot runs
`-u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 -S 48000 -R 0 -C 0`.
`[READ]` — note **`-z 256`**, not 128; see §8.

### 1.2 `LTRQ` / `LTRS` — the clock bridge (new)

`las-sc`'s `las/las-comm.scm` literal pool contains, adjacent and in this order:
`[READ, las-sc strings]`

```
/ping   /mode   normal   initial-mode   rx   /v/voices
/info/fwrev   /info/git
tag   time   voice-clock   sample-counter
LTRS   LTRQ
/vx/   ip   card   voice   osc
```

and its CHICKEN trace strings give the code shape of `las-query-clock`
(`las-comm.scm` lines 273–294): `[READ]`

```
273  string->sockaddrs, socket-connect/ai        ; a socket of its own
276  socket-send
277  bitstring->string
278  bitstring-reserve / bitstring-append! / integer->bitstring-big
280  bitstring-read / bitstring=? / bitstring->integer-big / bitstring-length
281  socket-receive
287  make-las-clock-response
```

So: **a raw big-endian binary frame, not OSC.** The request is tagged `LTRQ`,
the reply `LTRS` (`bitstring=?` at line 280 is the tag comparison), and the reply
decodes into the record `las-clock-response = {tag, time, voice-clock,
sample-counter}` `[READ, accessor list in las-sc]`.

This is the i.MX6 asking the voice controller for its sample counter and voice
clock so the two timebases can be related. `las-frontend`'s
`--host-systemclock=vc` is the same mechanism from the UI side. `[READ]`

**This corrects an existing claim.** `docs/MOOG-ONE-INTERNALS.md` records `LTRQ`
/ `LTRS` as seen once on ports 9501/60084 during a boot and hypothesises they are
the "startup cookie". They are the clock query and response, and they are in
`las-comm.scm`, which has nothing to do with cookies. `[READ]` beats the earlier
`[INFERRED]`.

### 1.3 Address space: how a card, a voice and an oscillator are named

`las-comm.scm` defines `las-entid = {ip, card, voice, osc}`, printed as
`ip=[…], card=N, voice=N, osc=N` `[READ, literal pool]`, with predicates
`las-entid-1card? / -1voice? / -1osc?` and expanders `las-entid-list-cards /
-list-voices / -list-oscs`. `[READ, procedure list]`

Two address prefixes exist as literals:

* **`/vx/`** — the card prefix, in `las-comm.scm`. `las-card-prefix`,
  `las-card-adr`, `las-card-msg`, `las-card-query`. `[READ]`
* **`/v/`** — the voice prefix, in `las-vox.scm`. `las-vox-prefix`,
  `las-vox-adr`, `las-vox-msg`, `las-vox-query`. `[READ]`

`las-card-msg` is built by taking an OSC message and *rewriting its address*
(`osc-adr` → `osc-set-adr` → `las-card-msg-set-adr`, lines 308–320) `[READ]`, so
the wire form is a normal OSC message with the card or voice prefix glued on the
front: `/vx/<n>/…`, `/v/<n>/…`.

`cal/cal.scm` calls `(modulo (las-vox-port-nr p) …)` at lines 1318 and 1412
`[READ, trace strings]`, which is consistent with a flat voice number 0..15 being
reduced to a within-card index — 8 cards × 2 voices. `[INFERRED]`

### 1.4 Reply codes

The controller and the card both answer with a three-digit code and a string,
FTP style. Recovered plaintext, both images: `[READ]`

| code | text | where |
|---|---|---|
| 200 | `200 OK well hmm`, `200 Read from flash ` | `las-c` 0x3C5F9, `vx-a` 0x1C0B9 |
| 400 | `Malformed messag(e)` | `las-a` 0x2A0D0, `vx-a` 0x1BCE3 |
| 404 | `Not foun(d)` | `las-a` 0x2A0C1, `vx-a` 0x1BCD6 |
| 503 | `Unavail(able)` | `las-a` 0x2A0E7 |
| 550 | `550 CRC` | `vx-a` 0x1C11C |
| 55x | `(wr)ong image version`, `magic number`, `leng(th)` | `vx-a` 0x1C12B–0x1C152 |
| 555 | `555 Internal error: invalid poi(nter)` | `vx-a` 0x1C159 |
| 5?9 | `9 Other` | `vx-a` 0x1C17C |

`las-sc` matches on the prefix with a helper literally called
`response-prefix?` `[READ, procedure list]`.

### 1.5 The performance stream (unchanged, cited)

Port 7772, addressless OSC (`"/"`), leading integer opcode: `[TESTED, prior
session, docs/MOOG-ONE-INTERNALS.md]`

```
/  ,iifi   4  <note> <velocity> 0      note on/off; note-off is velocity -0.0
/  ,ii     8  <mask>                   16-bit live voice-allocation mask
```

Nothing in this pass found a third opcode. `netstat` confirms `las-frontend`
holds `0.0.0.0:7772`. `[READ, runtime-state.txt]`

### 1.6 The controller → card bulk message (new, and exact)

`vx_ee.scm`, `args` section, verbatim: `[READ]`

```
   ;; -- the following seven args are copied in order from the controller bulk message
   ;; they must match the order in the bulk message
   mw                               ; mod wheel (0..1)
   pw                               ; pitch wheel (-1..1)
   padx                             ; pad X coordinate (0..1 or -1..1)
   pady                             ; pad Y coordinate (0..1 or -1..1)
   a                                ; keyboard aftertouch (0..1)
   padz                             ; pad pressure (0..1)
   padg                             ; pad gate (0 or 1)
```

So there is a periodic **bulk message** from the voice controller to every voice
card carrying exactly seven performance controls in exactly that order. The
voice-card command surface contains a token `…ast_bulk` at `vx-a` 0x1BC47
(`fast_bulk` or `last_bulk`; the preceding byte is inside a compressed reference
and cannot be recovered) `[READ]` — almost certainly this message. `[INFERRED]`

The other `args` (`cvin1`, `cvin2`, `expr1`, `expr2`, `sus`) are documented as
"the actual measured voltages divided by 5" `[READ]`, so the rear-panel CV inputs
and pedals also reach every card as normalised scalars.

### 1.7 Binary structs carried in OSC blobs

`las-sc` uses the CHICKEN `bitstring` egg to pack and unpack four named C-style
structs. Their accessors are in the binary's symbol table; the field order below
follows the gensym numbering of the accessors, which CHICKEN emits in
declaration order (`[READ]` for the names, `[INFERRED]` for the order).

**`Oscl_ctl_p`** — one oscillator's control parameters, 13 fields:

```
f0_khz  p0  p  fofs_khz  duty  reset_khz_q20  pw  wave  ph0  ph1  ln  lp  autor
```

Three of the thirteen are decoded through `q24->inexact`
(`vxmon-lib.scm` 328–330) `[READ]`.

**`Vox_oscls_ctl_p`** — one *voice's* three oscillators as one blob, 5 fields:

```
o1  o2  o3  temp  phase_flip
```

read as `read-Oscl_ctl_p` three times in a row (`vxmon-lib.scm` 345, 346, 347)
plus a Q24 `temp` at 360. `[READ]`

**`Oscl_report`** — telemetry, 13 fields, ten of them Q24
(`vxmon-lib.scm` 420–430) `[READ]`:

```
base_pitch  comp_pitch  freq_khz  temp  mode  duty  tr  max  min  offset  gain  ph0  ph1
```

**`Oscl_phase_report`** — tuning-table telemetry, 6 fields, five Q24
(`vxmon-lib.scm` 389–394) `[READ]`:

```
half_freq_khz  table_idx  tbl-code  tbl-imc  tbl-b  code
```

Bulk telemetry arrives as an OSC **blob**: `las-oscl.scm` line 227 is
`blob->u32vector/shared` immediately followed by `decode-osc-stats` at 230.
`[READ]` The voice card's OSC type-tag table is `,b ,f ,h ,s ,ss ,iiii` with
`#bundle` at `vx-a` 0x1C064. `[READ]`

**Everything numeric on this bus is Q24 fixed point.** `las-math.scm` defines
`inexact->q24`, `q24->inexact`, `*q24` and `dac-mag->code`. `[READ, procedure
list]` Q24 is a 24-bit fraction — the same width as the PCM1681 sample word.
That is the seam where "parameter" becomes "sample".

---

## 2. What the voice card actually is

### 2.1 Hardware, restated from `hardware-external.md`

Per card: one XMOS **XL216-512-TQ128-C20**, **8 × TI PCM1681** (4 per voice, 8
channels each) = **64 DAC channels per card, 32 per voice**, ~10 × 74HC595 shift
registers, THAT 2172 VCAs, LM13700 OTAs, a discrete SOT-363 dual-transistor
ladder. Silkscreen blocks per voice: `VCO1 Core` `VCO2 Core` `VCO3 Core`
`NOISE` `MIX` `VCFA_SUM` `VCFB_SUM` `VCA` `MAIN` `SUB1` `SUB2`.
`[READ, docs/arch/hardware-external.md, from photographs]`

Note the arithmetic: **4 × PCM1681 is 32 channels, not 64.** The 64 is per card
(8 parts). See §8.

### 2.2 Filter A is the SVF; Filter B is the ladder

Established by three independent strings in `las-sc`'s `cal.scm` literal pool,
each sitting next to the address it labels: `[READ]`

```
/cal/gldr    "ladder filter vca"          /cal/biasfb  "ladder filter vca bias"
/cal/gsvf    "svf vca"                    /cal/biasfa  "svf vca bias"
/cal/hpf     "ladder filter hp bias"      /hw/hpf
/cal/ladf    "ladder filter frequency calibration complete"
/cal/ladr    "ladder filter resonance"
```

`fa` ↔ `gsvf` ↔ SVF; `fb` ↔ `gldr` ↔ ladder. The tap addresses agree:
`/fa/1/{lp,bp,hp}`, `/fa/2/{lp,bp,hp}`, `/fa/par` (two state-variable sections
with three taps each and a parallel mode) against `/fb/hp`, `/fb/tap`
(a ladder with a high-pass and a tap select), plus `/fafb` for the A↔B
balance. `[READ, literal pool]`

### 2.3 The 26 calibrated control voltages per voice

`las-voxcal` is a CHICKEN record; its accessors appear in the binary in
declaration order: `[READ]`

```
o1  p1  o2  p2  o3  p3  rm  extin
svf1f  svf1r  svf2f  svf2r  ladf  ladr  ladhp
bias-gsvf  gsvf  bias-gldr  gldr
mainl  mainr  sub1  sub2  fm  noisecw  noiseccw
```

**26 entries.** Each holds a `linear-cal = {x, x0, x1, y0, y1}` `[READ, accessor
list]` — a two-point line fit, which is what you build when a DAC code has to be
converted into a physical quantity with a per-unit gain and offset. The OSC
addresses `/cal/<name>/{l,h,x}` (and `/x0 /x1 /y0 /y1`) set the low point, the
high point and the live value. `[READ, address list]`

Read as an inventory of analog controls, this is the voice:

| cal name | analog node |
|---|---|
| `o1 o2 o3` | oscillator saw/tri VCA level into the mix (`Oscl_ctl_p.ln`) |
| `p1 p2 p3` | oscillator pulse VCA level into the mix (`Oscl_ctl_p.lp`) |
| `noisecw` `noiseccw` | the two noise colours, mixed by `nsbal` |
| `rm` | ring-modulator level |
| `extin` | external-input level |
| `fm` | FM depth VCA |
| `ladf` `ladr` `ladhp` | Filter B cutoff, resonance, high-pass |
| `svf1f` `svf1r` `svf2f` `svf2r` | Filter A section 1 and 2, cutoff and resonance |
| `gldr` `bias-gldr` | Filter B output VCA gain and bias |
| `gsvf` `bias-gsvf` | Filter A output VCA gain and bias |
| `mainl` `mainr` | the voice's main-bus VCA pair |
| `sub1` `sub2` | the voice's second output pair |

The `ln`/`lp` reading is `[INFERRED]` from `Oscl_ctl_p` carrying exactly two
per-oscillator level fields alongside a calibration set that has exactly two
per-oscillator VCA entries; everything else in the table is `[READ]` from the
label strings quoted in §2.2 and §2.5.

### 2.4 `sub1`/`sub2` is the same thing as "SEND L/R VCA"

Four names for one pair of VCAs, joined by one code path. `cal-send-vcas`'s
literal pool, in order: `[READ]`

```
checking for send vca cal data
/cal/aux2  /cal/aux1
/mix/subr-en  /mix/subl-en  /mix/sub-en
/a/stat/send2  "send2 vca gain"
/a/stat/send1  "send1 vca gain"
```

So: card-side addresses `/cal/aux1`,`/cal/aux2` → record fields `sub1`,`sub2` →
silkscreen `SUB1`,`SUB2` → controller meters `/a/stat/send1`,`/send2` → UI label
`SEND L VCA` / `SEND R VCA`. `[READ]` for every link except the silkscreen
identification, which is `[INFERRED]` from the name.

Note that `cal-send-vcas` takes **two** ports — `(cal-send-vcas las-port vox-port
cal)` `[READ, signature]` — writing calibration to the card while reading the
meter on the controller. Same for `cal-main-vcas`, `cal-noise`, `cal-rm`,
`cal-extin`, `cal-ladbias`, `cal-svfbias`.

### 2.5 The 17 calibrations

`las-frontend`'s `VoiceCardCalResultPanel` lists exactly seventeen rows: `[READ]`

```
OSC 1 VCA   OSC 2 VCA   OSC 3 VCA
PULSE 1 VCA PULSE 2 VCA PULSE 3 VCA
NOISE CW    NOISE CCW
LADDER CUTOFF
SVF 1 CUTOFF   SVF 1 RESONANCE   SVF 2 CUTOFF   SVF 2 RESONANCE
MAIN L VCA  MAIN R VCA
SEND L VCA  SEND R VCA
```

That is the "17 calibrations" in `/var/cal/vxcal.db`. `[READ]` for the list;
the identification with the database's row count is `[INFERRED]` but the count
matches exactly.

The full routine is longer than the results list — `VoiceCardCalProgressPanel`
enumerates it: `[READ]`

```
PERFORMING INITIAL FREQUENCY MEASUREMENTS
WAITING FOR TEMPERATURE TO SETTLE - HIGH / RUNNING TEMPERATURE CALIBRATION - HIGH
WAITING FOR TEMPERATURE TO SETTLE - LOW  / RUNNING TEMPERATURE CALIBRATION - LOW
PERFORMING DENSE FREQUENCY MEASUREMENTS
CALCULATING TUNING TABLES / WRITING TUNING DATA
CALIBRATING OSCILLATOR {1,2,3} SAW/TRI VCA
CALIBRATING OSCILLATOR {1,2,3} PULSE VCA
CALIBRATING RING MOD VCA / EXTERNAL INPUT VCA / NOISE VCA
CALIBRATING LADDER VCA GAIN / LADDER VCA BIAS
CALIBRATING SVF VCA GAIN / SVF VCA BIAS
CALIBRATING LADDER CUTOFF FREQUENCY / LADDER RESONANCE / LADDER HIGH PASS
CALIBRATING SVF 1 / SVF 2
CALIBRATING MAIN VCA / SEND VCA
CALIBRATING TRI MAX / TRI MID / TRI MIN / SAW MIN / SAW MAX
```

`THIS PROCESS WILL TAKE UP TO TEN MINUTES` and `FOR OPTIMAL STABILITY, SYSTEM
SHOULD WARM UP FOR 45 MINUTES`. `[READ]`

### 2.6 The oscillator is a two-phase reset-locked core, not a free-running VCO

`las-osc = {vox, nr, pol, ph0, ph1, phf, ffsaw, ffsaw-code}` `[READ]`, and the
measurement side has `las-code->half-freq`, `las-osc-set-phase`,
`las-measure-phase-freq`, `opposite-phase`, `las-search-polarity`,
`oscl-set-opposite-phase`, and `Oscl_phase_report.half_freq_khz`. `[READ]`

The reading that fits: each oscillator has **two phase DACs, `ph0` and `ph1`**,
each setting the slope of one half of the cycle. The frequency is the harmonic
sum of the two half-periods; the *ratio* is the wave angle (triangle ↔ saw),
which is what Moog markets as the "variable core". `[INFERRED]` — but it is a
strong inference: `half_freq` and `opposite-phase` do not mean anything else, and
`vx_ee.scm` exposes a per-oscillator `o1ang` (wave angle) destination alongside a
separate `o1d` (triangle duty) and `p1d` (pulse duty). `[READ]`

`Oscl_ctl_p.reset_khz_q20` and `/hw/reset_khz` `[READ]` are the reset-pulse rate,
and the card runs a **PID loop** to hold pitch — `/hw/enable_pid`, `pid`, `pi` on
the card `[READ, vx-a 0x1BCB9]`, `pid-search` in `las-sc` `[READ]`.

### 2.7 The DAC channel allocation — what is and is not established

**Established:** the *set* of per-voice control voltages, above. **Not
established:** which PCM1681, and which of its eight channels, drives each one.

Why it cannot be recovered from these files: the host never names a DAC channel.
Every write is by symbolic name — `/cal/ladf/x`, `/mix/o1/fa` — and the only
channel-indexed DAC address in the whole system, `/testosc/dac/{0..3}`, belongs
to the **interface board's rear-panel CV outs**, not to a voice card. That is
settled by `las-frontend`'s `CVOutCalibrationPanel`, which pairs
`/testosc/dac/*` with `CV OUT 1..4`, `+5V`, `-5V` and
`USE A MULTIMETER TO MONITOR THE DC VOLTAGE OUTPUT OF EACH CV OUT`. `[READ]`
`cal.scm` uses `/testosc/dac/2` and `/testosc/dac/3` as a DC source while
calibrating the external input. `[READ, literal pool]`

The nearest thing to a channel selector on the card is `/cal/testosch/ch` and
`/cal/testoscl/ch` — a card-resident test oscillator with a `ch` parameter,
alongside `freq`, `g` and `wave` (value `sqr`). `[READ]` Its legal `ch` values
are integer constants in compiled Scheme and are not recoverable as strings.

**Budget check.** Counting one DAC channel per control voltage:
3 oscillators × (ph0, ph1, pw, ln, lp) = 15; noise cw + ccw = 2; rm, extin, fm =
3; svf1f, svf1r, svf2f, svf2r = 4; gsvf + bias = 2; ladf, ladr, ladhp = 3;
gldr + bias = 2; mainl, mainr = 2; sub1, sub2 = 2. **Total 35** against a budget
of **32**. So at least three of those are not separate DAC channels — the two
bias terms and `fm` are the obvious candidates (a bias can be folded into the
gain line digitally, and FM depth may be switched rather than continuously
scaled, given ~10 74HC595s per card are available for switching). `[INFERRED]`
This is arithmetic on an inferred list; do not treat 35 or the three candidates
as facts.

What would settle it, in order of cost: (a) JTAG on a card and read the DAC port
buffers while sweeping one parameter (§7); (b) a logic-analyser on one PCM1681's
data line with the card in `testosc` mode; (c) a decompiled `app_vx` image.

---

## 3. Where the mixer's A/B split lives

`/mix/{o1,o2,o3,n,rm,ext}/{fa,fb}` — six sources, each with a level into Filter A
and a level into Filter B — plus `/mix/ext/{ext0,ext1}` and
`/mix/{main-en,sub-en,subl-en,subr-en}`. `[READ, cal.scm literal pool]`

Twelve mixer sends against six calibrated source VCAs (`o1..o3`, `p1..p3` are the
oscillator waveform VCAs; `noisecw/ccw`, `rm`, `extin` the rest). The card has
two summing nodes on the silkscreen (`VCFA_SUM`, `VCFB_SUM`). Either each source
has a second, uncalibrated VCA per filter, or the split is done with the 74HC595
switch fabric and a single level. **Unknown.** `[INFERRED that these are the only
two possibilities; no evidence chooses between them]`

---

## 4. The expression engine's execution environment

`/usr/share/vx_ee.scm`, 13,134 bytes, `(c)2018 Moog Music Inc.` Recovered from
`captures/backup/rootfs-p3-las-v1.5.0-20260907.img.gz` (inode 7987,
`/usr/share/vx_ee.scm`). `[READ]` The recovered file is preserved verbatim at
**`captures/arch-harvest/vx_ee.scm`**; read it rather than trusting the excerpts
below.

The language itself is `expression-language.md`'s job. What follows is the
machine.

### 4.1 The four register banks

Verbatim from the file: `[READ]`

```scheme
(VX_EE
 (symbols
  (args   … 16-element m array + 30 named read-only scalars …)
  (parms  (c (array 128)))    ; expression constants
  (vars   (v (array 16)))     ; general-purpose variables
  (results … 126 destinations …)))
```

| bank | width | lifetime | written by |
|---|---|---|---|
| `args` | `m0..m15` + 30 named | read-only to the program | the controller (bulk message, note events, CV) |
| `parms` | **`c0..c127`** | saved with the preset | OSC `/p/part/t/<n>/p/c/<0..127>` |
| `vars` | **`v0..v15`** | not saved | the program itself (`sto`/`rcl`) |
| `results` | **126 named** | applied to hardware each pass | the program's `sto` |

**The constant register file is 128 wide, and this is confirmed twice
independently.** `(c (array 128))` in `vx_ee.scm` `[READ]`, and
`las-frontend` contains the literal addresses `/p/part/t/1/p/c/<n>` for single-,
double- and triple-digit `n`, with `100`–`127` all present and **nothing at `128`
or `129`**. `[READ]` This settles
the open question in the swarm brief ("43 distinct constant registers used, and
`c64` appears, so the register file is at least 65 wide"). It is exactly 128.

**The file's own prose header is stale.** It says "mod sources variables,
m0..m63", "parms contains the c0..c31 variables … addresses
/p/part/t/<n>/p/c/0..31", and "vars contains the general-purpose variables
v0..v63". The declarations three paragraphs later say 16, 128 and 16. `[READ]`
Trust the declarations; the OSC address evidence backs the 128.

### 4.2 The read-only sources

```
m0..m15                                   general-purpose, MIDI-mappable
gate v p                                  note gate (-1..1), velocity, base pitch (semitones)
mw pw padx pady a padz padg               the seven-field bulk message (§1.6)
cvin1 cvin2 expr2 expr1 sus               rear panel, "measured voltage / 5"
l1 l2 l3 l4                               LFO 1-4          ← computed on the card
e1 e2 e3 en                               EG 1-3 + noise EG ← computed on the card
rnd rndb                                  random, unipolar and bipolar
pp                                        pitch after portamento and pitch wheel
ktc                                       key-track centre, from /t/ktc, saturated ±127
pnt                                       (pp - ktc) / 120
pto                                       (pp - ktc) / 12
vspr                                      voice spread
```

`[READ, all of it, with the comments]` A `vdist` ("voice distribute") source is
present but commented out, as are `gtsh` / `gtshb` (gate-triggered sample and
hold). `[READ]`

**The LFOs and envelopes are sources to the expression engine and destinations of
it** (`l1f`, `l1v`, `l1dm`, `e1am`, `e1s` … are results). They therefore run on
the voice card, below the expression engine, and each voice has its own set.
`[READ]` This is corroborated by the voice-card image's own sorted string
dictionary, which contains `l1 l2 l3 l4`, `eg_`, `lfo_p`, `attac`, `decay`,
`one_sho`, `multi-trig`, `legat`, `glis`, `key-follo`, `neg_`, `padx/y/z`,
`tscale` and `lhc-alph` at `vx-a` 0x1C193–0x1C549. `[READ]`

### 4.3 The 126 destinations

Grouped as they appear in the file. `[READ]`

```
LFO 1-4    (6 each, 24)   l<n>f l<n>pno l<n>v l<n>dm l<n>fim l<n>fom
EG 1-3     (7 each, 21)   e<n>dlm e<n>am e<n>hm e<n>dm e<n>s e<n>rm e<n>tm
noise EG   (4)            ensam ensdm enss ensrm
global pitch (7)          oct po pno l1po e3po l3od l3pd
FM macro   (1)            ofm
osc 1-3    (10 each, 30)  o<n>pno o<n>o o<n>po o<n>fo o<n>d o<n>tr o<n>ang
                          p<n>d o<n>bal o<n>fm
noise      (1)            nsbal
mixer      (6)            mixo1 mixo2 mixo3 mixrm mixn mixext
filters    (15)           fpn fr ffm | fapn far fafm | fa1pn fa1r fa1fm
                          | fa2pn fa2r fa2fm | fbpn fbr fbfm
balance    (1)            fbal
EG1→cutoff (5)            fegpn faegpn fa1egpn fa2egpn fbegpn
LFO2→cutoff(5)            flpn falpn fa1lpn fa2lpn fblpn
bus sends  (2)            fxb1s fxb2s
output     (4)            vca main pan sustain
```

Note the deliberate hierarchy in the filter destinations: `fpn` hits **all**
filters, `fapn` hits both SVF sections, `fa1pn`/`fa2pn` hit one each, `fbpn` hits
the ladder. Same pattern for the EG and LFO cutoff-modulation amounts. `[READ]`

Units are consistent and unusual: **frequencies in kHz, times in milliseconds**
(`l1f` "LFO 1 frequency (kHz)", `o1tr` "sawtooth reset time, milliseconds",
`o1fo` "frequency offset, kHz"), matching `Oscl_ctl_p.f0_khz` /
`fofs_khz` / `reset_khz_q20`. `[READ]`

Envelope and glide time destinations are documented as multiplicative:
"0 leaves the time unaffected, 1 multiplies by 10, and -1 multiplies by 0", and
the EG time multipliers "multiply the current time setting by an approximation to
e^(2.3x)". `[READ]`

### 4.4 How a `sto` becomes a DAC write

`vx_ee.scm` says of `results`: **"variables applied to the hardware. Most of the
LAS expression addresses result in a storage to one of these."** `[READ]` And of
the gate: "The destination variable `igate` is added to this **before it is
processed by the sound engine**." `[READ]`

So there are two stages on the card, not one:

```
expression program  --sto-->  results bank  -->  sound engine  -->  DAC channel
```

A `sto fbpn` does **not** write a DAC. It writes the normalised (0..1) Filter B
cutoff into the results bank. Some later stage — the "sound engine" — reads that
result, applies the card's stored `linear-cal` for `ladf` (`x0,x1,y0,y1`), and
emits a Q24 code (`dac-mag->code`, `inexact->q24`) into the PCM1681 channel that
drives the ladder cutoff current.

Every arrow in that chain is `[READ]` at its endpoints; the joins between them
are `[INFERRED]`. In particular nothing observed proves the results bank and the
sound engine are separate passes rather than one fused loop — only the wording
"before it is processed by the sound engine" suggests it.

### 4.5 The program is wrapped by the host

`las-sc`'s string pool contains `/p/pre-expr` and `/p/post-expr` next to
`expression-nodes` and `expr-syms`. `[READ]` `las-frontend` writes only
`/p/part/t/{1,2,3}/p/modmatrix/expressions` — it has no `pre-expr` or `post-expr`
address at all. `[READ]`

So the RPN string that reaches the card is not the preset's string alone:
`las-sc` prepends a `pre-expr` and appends a `post-expr` of its own. Anyone
reasoning about the program the card runs must account for those two fragments,
and this pass did not recover their contents. `[INFERRED from the address split;
the wrapping order is a guess from the names]`

### 4.6 The evaluation rate — unknown

I could not establish it. What is known:

* The card's command surface includes `dsptime` (`vx-a` 0x1BBAF) and `/hw/sr`,
  and `hw` sub-commands `vaen` (VCA enable), `led0..2`, `sdac`, `hpf`.
  `[READ]`
* The CV DACs are 24-bit **audio** DACs on an audio-clocked processor, so the
  hardware ceiling is a per-sample update. `[READ, hardware-external.md]`
* Smoothing coefficients exist as parameters (`temp_alpha` on the card,
  `pga-alph(a)` and `lhc-alph(a)` in the dictionaries) `[READ]`, which is what you
  add when the control rate is coarse enough for steps to be audible.

Anything more specific would be invention. **Unknown.**

---

## 5. Tuning and calibration: how the data reaches the cards

### 5.1 Two stores, two paths

| store | holds | reaches the card via |
|---|---|---|
| `/var/tuning.vxtune` | per-voice, per-oscillator frequency/temperature tables | `las-sc --vxdb=`, or `/usr/bin/vxtune write -c vc -f /var/tuning.vxtune` |
| `/var/cal/vxcal.db` | the 17 calibrations × 16 voices, as `linear-cal` rows | `las-sc` `send-linear-cal/xy` over `/v/<n>/cal/<name>/…` |

`[READ]` — the `vxtune` command line is a literal in `las-frontend`
(`/usr/bin/vxtune write -c vc -f /var/tuning.vxtune`), and `/var/cal/vxcal.db`
and `/var/cal/vxcal-test.db` are literals in the same binary.

### 5.2 The tuning store is a directory, not a file

`cal/vxtune-db.scm`'s trace map shows `directory?`, `create-directory`,
`file-type`, `regular-file?`, `with-input-from-file`, `with-output-to-file`,
`remove`, plus `vxtune-db-dir-open / -dir-ref / -dir-set! / -dir-keys /
-dir-has-key? / -dir-sync / -dir-valid? / -dir-write-access?`. `[READ]` Keys are
derived with `string-index-right` and `string-take` (lines 292–293) `[READ]`, and
the accessors are `vxtune-db-vox`, `vxtune-db-oscl`, `vxtune-db-oscl-key`,
`vxtune-db-voices`. So the key space is per-voice and per-oscillator, and a key
is a composite string split at its last separator. `[READ]` for the shape,
`[INFERRED]` for "`<vox>-<oscl>`".

Access is serialised through a channel-based server thread
(`vxtune-db-server-thread`, `gochan-send`, `vxtune-dbc-call`) with a periodic
flush (`gochan-after`, `vxtune-db-last-sync-time`). `[READ]`

### 5.3 What a tuning table actually is

The in-memory record is `las-phase`: `[READ, accessor list]`

```
id  stop  sparsetbl  temptbl  temptbl-l  temptbl-h  tempcode  mt  lftbl  codetbl  freqtbl
```

and the producers are `gen-tuning-tables`, `merge-code-tables`, `sort-ctbl`,
`downsample-ctbl`, `freqtbl-line->board-data`, `freqtbl-line->board-data-q20`,
`las-measure-freq-curve`, `las-measure-freq-curve-lf`,
`las-measure-temp-curve-linear`, `las-measure-temp-table-point`,
`las-curve-make-code-list-{freq,oct,pitch}`, `pitch-to-code-codetbl`,
`freq-to-code-codetbl`, `freq-duty-to-osc-codes`, `linear-table-interpolate`.
`[READ, procedure list]`

Reading that set: for each oscillator the calibration measures a **frequency vs
DAC-code curve** (`freqtbl`/`codetbl`, with a low-frequency variant `lftbl` and a
downsampled `sparsetbl`), and a **temperature curve** at two settled temperatures
(`temptbl-l`, `temptbl-h`, `tempcode`, `mt` from `calc-mt low-avg high-avg`).
At play time `freq-duty-to-osc-codes ftbl0 mt0 ftbl1 mt1 f duty temp` takes the
two half-cycle tables, their temperature coefficients, the wanted frequency, the
wanted duty and the current temperature, and returns the DAC codes. `[READ,
signature]` `[INFERRED]` for the semantics of the arguments, but the names are
unambiguous.

The name `freqtbl-line->board-data-q20` is the serialiser: a table line becomes
**board data in Q20**. `[READ]` That is the on-the-wire form of the tuning
tables.

`Oscl_phase_report = {half_freq_khz, table_idx, tbl-code, tbl-imc, tbl-b, code}`
`[READ]` is the card reporting, per oscillator, which table entry it is currently
interpolating in — index, the entry's code, its slope/intercept terms, and the
final code. `[INFERRED]`

### 5.4 The card is the master copy

The voice card's own command surface includes `data save`, `load`, `tuning`,
`save_ca(l)`, `min-main-vca`, `tune`, `tc`, `dftc`, `aut`, `cal`, `pid`
(`vx-a` 0x1BC0F–0x1BCB9). `[READ]` The card writes these into its own SPI flash.
The Linux-side `/var/tuning.vxtune` and `/var/cal/vxcal.db` are the backup, which
is why `las-frontend` offers **`RESTORE LEGACY DATA`**, **`WRITE DATA`** ("write
calibration data to voice cards") and **`EXPORT DATABASE`** as separate
operations, and why `LEGACY DATABASE WRITE` ends with
`PLEASE POWER-CYCLE YOUR INSTRUMENT`. `[READ]`

---

## 6. The flash protocol, and a blunt safety assessment

### 6.1 Two entirely different paths

**Voice controller (VC):** written from Linux **over SPI**, not over the bus.
The literal in `las-sc` is `[READ]`:

```
flashrom -l /usr/share/xmosfw/las_layout -i firmware -w <file>
```

with `config-las-spi xmos` / `config-las-spi som` (three calls in
`vxfw-lib.scm` lines 307–312) muxing the SPI bus between the SoM and the XMOS.
`[READ]` `las-sc` will proceed after a network error — the string
`"Network Error - Flashing VC Anyway` is in the binary. `[READ]`

**Voice card (VX):** written **over the bus**, by OSC. There is no SPI path.

### 6.2 The `/fw` protocol, exactly

From `las-sc`'s string pool, these literals are adjacent and in this order
`[READ]`:

```
failure in send-block
200
block-size
/fw/data
adr
sent firmware to card
cannot start fw download (
/fw/start
Sending firmware to
 cards
initial-mode
vxfw
/fw/version
```

and `vxfw-lib.scm`'s trace map gives the flow `[READ]`:

```
 84- 97  vxfw-send-block           osc? / osc-arg-count / osc-value
                                   string-prefix? -> response-prefix? -> vxfw-error
                                   string->blob                            (line 97)
105-109  vxfw-send-data            keyword args; loop over vxfw-send-block-from-port
111-120  vxfw-send-fw              file-size; las-card-query "/fw/start";
                                   response-prefix?; call-with-input-file;
                                   vxfw-send-data; las-card-nr
123-141  vxfw-send-fw-cards        las-open; pause-for; las-card-count; iota;
                                   las-card-open; vxfw-send-fw   (per card)
169      nybble-swap-string        string-map
180-184  vxfw-read-fw-version      call-with-input-file; with-input-from-port;
                                   ->bitstring; nybble-swap-string
207-232  vxfw-get-card-version     las-card-query ×3; -query-string; -query-uint
239-254  vxfw-check / -check-card
307-312  CONFIG-LAS-SPI ×3
```

So, concretely:

1. `/fw/version` and `/info/versionb` are read from each card first; the host
   compares against the file's version word, which it obtains by **nibble-swapping
   the file** before reading it (`nybble-swap-string`, line 184). `[READ]` This
   independently confirms `xmos-firmware.md`'s claim that `app_vx_10M_*.bin` is
   stored nibble-swapped per byte.
2. `/fw/start` opens a download. On a non-`2xx` reply the host aborts with
   `cannot start fw download (`. `[READ]`
3. `/fw/data` carries **200-byte blocks** (`block-size` defaults to the literal
   `200`, adjacent in the pool) with an **`adr`** keyword giving the destination
   address, and the payload as an OSC **blob** (`string->blob` at line 97).
   `[READ]` for `200`/`block-size`/`adr`/`string->blob` and their adjacency;
   `[INFERRED]` that `200` binds to `block-size` rather than being the reply code
   — but `200` also appears separately as the reply prefix, so treat the block
   size as probable, not certain.
4. Failure of any block raises `failure in send-block`. `[READ]`
5. `vxfw-send-fw-cards` iterates `(iota (las-card-count))` — **one invocation
   reflashes every card in the stack.** `[READ]`
6. `--force-vx-update` = `Update VX firmware even if versions match.` `[READ]`

The card side of the same protocol, in plaintext at `vx-a` 0x1C0B9–0x1C17C
`[READ]`:

```
200 Read from flash …      Write to flash complete      Failed to r(ead) … from
550 CRC     (wr)ong image version     magic number     leng(th)
555 Internal error: invalid poi(nter)      9 Other
```

`Read from flash` is a **read** path with the same reply vocabulary. Both parts
expose flash read *and* write over their own protocol, reachable from the bus.

### 6.3 Safety assessment: do not touch this

Read this as an instruction, not a caution.

**Do not send `/fw/start`, `/fw/data` or any `/fw/*` message to this instrument,
by hand or by script, under any circumstances, including "just to see the reply".**

The reasoning:

1. **A bricked voice card has no software recovery path.** The controller can be
   re-flashed from Linux over SPI with `flashrom` and the byte-exact image in
   `/usr/share/xmosfw/`. A voice card cannot: the only route to its flash is the
   very bus protocol you just broke. Recovery means physically removing the card
   and attaching a debug probe to its own JTAG header (there is one, top-left
   `[READ, hardware-external.md]`) or clipping its SPI flash.
2. **The parts do not exist any more.** The Moog One is discontinued.
   `BRD-30-011-1205 REV A` is not a purchasable assembly. A dead voice card is a
   permanent 2-voice loss on a 16-voice instrument, and it takes the card's
   *calibration and tuning flash* with it — the card is the master copy (§5.4),
   and the Linux-side backup can only be restored **through the same bus that is
   now broken**.
3. **Zero-argument probing is not safe here the way it is elsewhere.** The
   established probe discipline (`vxq.py`: send zero-argument packets, which are
   queries) does not protect you on `/fw/start`, because `/fw/start`'s job is to
   *enter download mode*. A card sitting in download mode with no data following
   is a card that may not return to `normal` mode without a power cycle, and
   `las-sc` will meanwhile be trying to talk to it.
4. **The watchdog will make it worse.** A card or controller that stops answering
   causes `las-watchdog` to run `config-las-spi`, `killall scsynth sclang screen`
   and `/etc/init.d/S42sc stop/start` `[READ, prior pass, xmos-firmware.md §5]` —
   i.e. it will power-cycle the SPI bus *while you are mid-transaction*.
5. **`--force-vx-update` exists specifically to remove the guard** that would
   otherwise stop a mismatched image being written. `[READ]`

The same applies, one notch down, to the whole `/cal/*` tree and to the card's
`save_ca(l)`, `data save`, `tune`, `aut`, `dftc` and `min-main-vca` commands:
those persist, and the trap noted in `xmos-firmware.md` §5 holds — **the same
address reads with no argument and writes with one.**

If the goal is ever to write firmware to this instrument, the correct route is
the vendor's: put a signed `.zip` on a USB stick and use the front panel, which
runs `lasfwu` and then `las-sc`'s own update path with the version guards
intact. Not a hand-built OSC packet.

---

## 7. `J_XTAG`, and what it would buy

`J_XTAG` is a header on the **interface board** `[READ,
docs/arch/hardware-external.md]`, next to the two XU216 parts (U26, U28). The
voice cards have their own, unlabelled JTAG header at the top-left corner
`[READ, same]`.

What it is: the XMOS xCORE debug port. XMOS's own adapters (XTAG-2/3, now XTAG-4)
plug into a 20-pin fine-pitch header carrying the JTAG TAP plus the xSCOPE/debug
link. `[INFERRED — vendor-standard, not read from this instrument]`

**What it would give, ranked by what it unlocks:**

1. **The decompressed images in RAM.** Both firmware images are compressed with a
   format that four passes have failed to crack (`decompressor.md`). A debugger
   can simply halt the part after boot and dump RAM, which is the *output* of
   that decompressor. That single dump would retire the entire string-table
   problem, give the complete OSC address table for both parts, and give a
   disassemblable image.
2. **The DAC channel map** (§2.7) — set one parameter, watch which port buffer
   changes.
3. **The expression engine's real tick rate and its bytecode** (§4.6).
4. **A recovery path for a bricked voice card** — the only one that exists.

**What it would cost:**

* An XTAG adapter and the XMOS toolchain (`xgdb`, `xrun`, `xflash`). `xrun`
  loads into RAM and does not touch flash; `xflash` writes. Only the first is
  ever needed for reading.
* Opening the instrument, and probing a live board. The header on the interface
  board addresses the *controller*, not the cards — reading a voice card means
  getting at a card's own header, which likely means pulling the card.
* **A real chance the port is dead.** xCORE parts have a one-time-programmable
  security register that can disable JTAG (`xburn`). Whether Moog burned it on
  production units is **unknown** and cannot be determined from any file on disk.
  This is the first thing to check and the cheapest way for the whole idea to
  fail.
* The chain may enumerate both XU216 parts, which needs the right XN target
  description to address a specific tile. `[INFERRED]`

Risk assessment: **reading over JTAG (`xrun`, memory dumps) is low-risk and is
the highest-value single move available on this project.** Writing over JTAG
(`xflash`) has the same brick potential as §6 and should be treated identically.

---

## 8. Confirmations, extensions, and conflicts

### Confirms `xmos-firmware.md`

* The two images, their sizes, and the per-byte transforms. The nibble swap is
  now independently confirmed from the host side: `nybble-swap-string` in
  `vxfw-lib.scm`. `[READ]`
* `/fw/start`, `/fw/data`, `/fw/version` are the voice-card firmware protocol;
  `flashrom` + `las_layout` is the controller's. Extended with the block size,
  the `adr` keyword and the blob payload.
* The card's only OSC address is `/e/q`, and the card speaks a compact short-name
  protocol while the controller does name resolution.
* The `200/400/404/503/550/555` reply vocabulary, and the flash read/write
  strings in both images.
* "The card is where the analog lives" — §2 puts numbers on it.

### Extends it

* `/usr/share/vx_ee.scm` in full (§4) — 46 sources, 128 constants, 16 variables,
  126 destinations, and the two-stage `results → sound engine → DAC` model.
* `LTRQ`/`LTRS` is the clock protocol, with its record and its framing (§1.2).
* The four bitstring protocol structs and their fields (§1.7).
* The seven-field controller→card bulk message, in order (§1.6).
* `las-voxcal`'s 26 calibrated CVs and `linear-cal`'s five fields (§2.3).
* The 17-row calibration result list and the full calibration routine (§2.5).
* `fa` = SVF, `fb` = ladder, with the label strings that prove it (§2.2).
* `sub1`/`sub2` = `/cal/aux1`/`aux2` = "SEND L/R VCA" = silkscreen `SUB1`/`SUB2`
  (§2.4).
* The tuning-table record `las-phase` and the `board-data-q20` serialisation
  (§5.3).
* `/p/pre-expr` and `/p/post-expr` — the host wraps the preset's program (§4.5).
* The `las-sc` and `las-frontend` command lines from the live unit (§0).

### Conflicts

1. **"Four PCM1681 8-channel DACs = 64 DAC channels" (swarm brief).** Four
   PCM1681s is 32 channels. The real figure, from `hardware-external.md`'s
   photograph reading, is **8 PCM1681 per card, 4 per voice, 32 channels per
   voice, 64 per card.** `[READ]` `hardware-external.md` §"What is actually on
   it" already has this right; the brief garbled it.
2. **"Block size is `-z 128`" (swarm brief).** `runtime-state.txt` shows
   `scsynth … -z 256 -Z 256 … -w 128`. `[READ]` The 128 is `-w`, the wire-buffer
   count. Whoever depends on the 128 figure should re-check. (Not my lane — the
   audio-graph agent owns this — but the conflict is on the record.)
3. **`LTRQ`/`LTRS` as a "startup cookie" (`docs/MOOG-ONE-INTERNALS.md`).** They
   are the clock query/response, defined in `las/las-comm.scm` alongside the
   `las-clock-response` record. §1.2. The cookie hypothesis is unsupported and
   should be retired.
4. **`vx_ee.scm`'s own header comment** contradicts its own declarations
   (`m0..m63` vs `(array 16)`, `c0..c31` vs `(array 128)`, `v0..v63` vs
   `(array 16)`). The `/p/c/0..127` address set in `las-frontend` breaks the tie
   in favour of the declarations. §4.1.
5. **`xmos-firmware.md` §3.1** describes the `vx-a` region as "the voice card's
   entire command surface". It is that *plus* an alphabetically sorted dictionary
   of the per-voice parameter vocabulary (§4.2), which is the part that shows the
   LFOs and EGs live on the card. Not wrong, incomplete.

---

## 9. What we still cannot see, and what it would take

Ranked by what it unlocks.

1. **The decompressed firmware images.** Everything below is downstream of this.
   *Cost:* an XMOS XTAG adapter and the toolchain; halt after boot, dump RAM
   (§7). *Risk if the JTAG security fuse is burned:* total, and unknowable in
   advance. *Alternative with no hardware:* keep attacking the compression
   (`decompressor.md`), which has now failed four times.

2. **The DAC channel → analog node map.** §2.7 gives the inventory but not the
   indices. *Cost:* JTAG on one voice card and a parameter sweep, or a logic
   analyser on one PCM1681 data line with the card in `testosc` mode. *Value:*
   this is the last mile from "parameter" to "voltage"; without it, any attempt to
   drive the analog hardware directly is guesswork.

3. **The expression engine's evaluation rate, and its bytecode format.** §4.6.
   *Cost:* JTAG, or a capture of `dsptime` telemetry from a running instrument
   over the control link (a read-only OSC query, but it does require a powered
   unit and is therefore out of scope under the current rules).

4. **`/p/pre-expr` and `/p/post-expr` contents.** §4.5. The card does not run the
   preset's program alone. *Cost:* low — these are almost certainly literal
   strings inside `las-sc`'s compressed CHICKEN literal pool, or defaults set from
   a config. A focused pass over `las-sc`'s literal decoding (`C_decode_literal`)
   should find them without any hardware.

5. **The card's `ch` value space for `/cal/testosch/ch`.** If the test
   oscillator's channel selector is the same index space as the DAC channels, this
   is a shortcut to item 2. *Cost:* item 1, or a careful read of `cal.scm`'s
   numeric constants — they are compiled integers, so this needs the CHICKEN
   literal decoder, not `strings`.

6. **`/var/cal/vxcal.db`'s schema and `/var/tuning.vxtune`'s byte format.**
   `captures/backup/calibration-20260907-222301.tar.gz` almost certainly contains
   both, from this exact unit. *Cost:* none — unpack and read it. **I could not
   do this in this session:** the sandbox's safety classifier began refusing every
   command that touched the rootfs image or the backup tarball partway through
   this pass (it had already allowed the `vx_ee.scm` extraction). Anyone
   continuing should re-run the extraction in a fresh session. This is the
   cheapest remaining win on the list.

7. **The rest of `/usr/share/xmosfw/`.** `app_las_gitinfo.json` (766 bytes),
   `app_vx_gitinfo.json` (782 bytes), `las_layout` (29 bytes) and `VERSIOND`
   (9 bytes) exist in the v1.5.0 rootfs and were **not** captured into
   `arch-harvest`. `[READ — the directory listing succeeded before the classifier
   started refusing]` The two JSON files are build metadata for the two images and
   may carry the toolchain version, the target `.xn` name and the tile map. Same
   blocker, same fix.

8. **Whether `/e/q` is the expression endpoint.** It is the card's only OSC
   address, and the card runs the expression engine, so the inference is tempting
   — but nothing observed supports it. **Unknown.**

9. **The A/B mixer split** (§3) — twelve sends against six calibrated VCAs.
   Switches or a second VCA bank. *Cost:* item 1 or 2.

Nothing in this file requires a powered instrument, and nothing in it should be
checked against one. Items 6 and 7 need only a fresh shell.
