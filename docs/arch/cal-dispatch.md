<!-- docs/arch/cal-dispatch.md -->
# Does one argument write? Settling the `/cal` and `/hw` dispatch question

The question this file exists to answer, from `docs/DANGER.md`:

> Does a `/cal/*` or `/hw/*` OSC message with **one** argument write persistent
> calibration, while the same address with **zero** arguments only reads?

**Nothing here was obtained from a running instrument.** Every claim is
reproducible from files already in `captures/`. Grades:

* **[READ]** — read directly out of a binary or capture file, with the offset cited.
* **[INFERRED]** — reasoned from what was read.
* **[TESTED]** — recorded from this instrument in an earlier session, sourced to
  the capture file that holds it.

Offsets: for `las-sc`, `las-frontend`, `las-watchdog` and `las-frontpanel-poll`,
**VMA = file offset + 0x10000** (verified from each ELF's section table). Firmware
offsets are into the *decoded* image (bit-reverse for `app_las`, nibble-swap for
`app_vx_10M`).

---

## Verdict

**CONFIRMED for the write half, with one important correction to its shape.**

* **One argument is a write.** [READ] It is exactly how Moog's own software sets
  every parameter on this bus, calibration included. The code path is shown in §2.
* **Zero arguments is not a write.** [READ] + [TESTED] It is the request form, it
  carries no value a handler could store, and Moog's own software uses it as a
  query on the same socket against the same addresses.
* **But the write is not "persistent calibration".** [READ] + [INFERRED] A
  `/cal/*` message with a value sets a *live* trim. Committing to non-volatile
  storage is a **separate address** — `/save_cal`, `/save_tuning`, `/save_pid` —
  and the host-side calibration database `vxcal.db` is written by **SQL**, not by
  OSC at all. See §4.
* **The rule is not universal.** [READ] `las-watchdog`, factory software that
  runs on every stock boot, sends `/v/voices` with **one integer argument** and
  reads the voice count out of the reply. So the firmware plainly does not treat
  every one-argument message as a store. Arity is the *convention*, not the
  *mechanism* (§5).

**The residual danger is not arity. It is which leaf.** A zero-argument message
to a *value* leaf is a query. A zero-argument message to a *verb* leaf —
`/save_cal`, `/load_cal`, `/cal:save`, `/cal:cal_default`, `/reset`, `/fw/start` —
is the whole action, because a verb has no value to omit. That is the real hazard
and it was not what the entry in `DANGER.md` was fencing off. See §6.

**Not settled: the firmware's own dispatch rule.** §7 says precisely why, and what
would settle it.

---

## 1. The two primitives, in Moog's own source-file names

`las-sc` is a compiled CHICKEN Scheme program. CHICKEN emits a
`"<file>:<line>: <callee>"` string immediately before every call and passes it to
`C_trace`, so the binary carries a complete call map with source line numbers.
[READ] `strings -a captures/arch-harvest/las-sc | grep '\.scm:'` — 17 source
files, ~4,100 literal slots recovered.

The OSC layer is the `csosc` egg. Two send primitives exist in
`las/las-comm.scm`:

| primitive | traces | meaning |
|---|---|---|
| `las-send` | `las-comm.scm:175 socket-send`, `184 osc-encode`, `193 las-send-str` | encode and send; do not wait |
| `las-query` | `:194 poll`, `:196 socket-receive-ready?`, `:200 socket-receive`, `:201 osc-decode`, `:204 osc-adr`, `:221 las-query` | send, then poll for a reply whose address matches |

Both use the same socket to `203.0.113.2:7770`. [READ] `las-vox-send` /
`las-vox-query` in `las/las-vox.scm` are the same pair with the address rewritten
to a per-card prefix (`:61 las-vox-prefix`, `:65 csosc#osc-set-adr`,
`:86 las-vox-msg-set-adr`); the literal `/vx/` is in that unit's literal frame and
in the calibration unit's (slots 0x283348, 0x284c9c, 0x284d20). [READ]

Messages are built by `csosc#osc`. In CHICKEN's ARM output a call is

```
    bl   C_trace          ; r0 = "cal/cal.scm:751: csosc#osc"
    ldr  r3,[r7,#OFF]     ; r7 = literal frame, OFF = the csosc#osc symbol
    mov  r0,#N            ; N = argument count, including proc and continuation
    ...
    blx  r3
```

so **`N-2` is the number of Scheme arguments** to `csosc#osc`. `(osc adr)` → N=3
is a message with **no** OSC arguments; `(osc adr v)` → N=4 is a message with
**one**. A scan of all 332 `csosc#osc*` call sites recovers N at every one. [READ]

---

## 2. The write path, shown

### 2.1 `/hw/mute` with one argument — the exact address that was tested with zero

`cal/cal.scm:751`, trace `cal/cal.scm:751: csosc#osc`, paired in the trace table
with `cal/cal.scm:751: las-send`. Disassembly at VMA 0x143138: [READ]

```
143138: bl   C_trace              ; "cal/cal.scm:751: csosc#osc"
14313c: ldr  r1,=0x2842f8         ; literal frame of the cal compilation unit
143148: mov  r0,#4                ; <-- argc 4  =>  (csosc#osc <adr> <value>)
143150: ldr  r3,[r1,#0x2b8]       ; lf[0x2b8] = symbol  csosc#osc
143158: stm  r5,{r2,r4}           ; a[0]=proc  a[1]=continuation
14315c: ldr  r3,[r1,#0x68c]       ; lf[0x68c] = "/hw/mute"
143164: str  r3,[r5,#0x8]         ; a[2] = "/hw/mute"
143168: mov  r3,#1                ; CHICKEN fixnum 1 == the number 0
14316c: str  r3,[r5,#0xc]         ; a[3] = 0
143174: blx  r3
```

Literal-slot verification: `lf[0x2b8]` at 0x2845b0 is the interned symbol
`csosc#osc`; `lf[0x68c]` at 0x284984 decodes to the string `/hw/mute`
(CHICKEN literal framing `FE 42 <24-bit len> <bytes>`). [READ]

So the line is `(las-send (csosc#osc "/hw/mute" 0))` — **`/hw/mute` with exactly
one argument, sent, not queried.** The calibration routine unmutes the instrument
this way before it measures.

Set against the entry in `DANGER.md`: a zero-argument `/hw/mute` was **[TESTED]**
inert and acknowledged. That is a matched pair on one address — zero arguments
did nothing, one argument is the setter. That is as close to a controlled
experiment as this material offers.

### 2.2 The calibration search loop

`cal/cal.scm` lines 93-250 are a measurement search (`brent-search` at :93,
`search` at :116, `las-vox-measure-mix-ampl`, `average-measurements`,
`pause-for`, `loop`). Inside it, at lines **100, 104, 137, 185, 224, 229**, every
one is `csosc#osc` with **argc 4** paired with **`las-vox-send`**. [READ]

That is the write: set a coefficient on one card, wait, measure, iterate.

`cal/cal.scm` has **50** `csosc#osc` sites, lines 100 to 1815. **46 are argc 4**
(one value, paired with `las-send` or `las-vox-send`). Three are argc 3 — lines
**521, 594, 686**, all paired with `las-query` and `csosc#osc-value` (§3). One,
line 440, reads as argc 2, which is almost certainly my scanner picking up the
wrong `mov r0,#imm`; its trace pairs with `las-vox-send` like its neighbours.
[READ, except the last sentence which is INFERRED]

So the calibration module is 46 writes and 3 reads, and the two are told apart by
nothing but the argument count.

### 2.3 Other confirmed one-argument writes

| trace | argc | address | paired with |
|---|---|---|---|
| `cal/cal.scm:739` | 4 | `/mode` | `las-send` |
| `cal/cal.scm:741` | 4 | `/testosc/freq` | `las-send` |
| `cal/cal.scm:743` | 4 | `/testosc/dac/2` | `las-send` |
| `cal/cal.scm:751` | 4 | `/hw/mute` | `las-send` |
| `las/las-comm.scm:120` | 4 | `/mode` | (init) |
| `sc/sc.scm:229` | 4 | `/therm/sys-temp` | `las-send` |
| `sc/fx.scm:325-328` | 4 | `/a/dir{1..4}-aux{1..4}` | `las-send` |
| `sc/fx.scm:842` | 4 | `/fx/bus-mode` | `las-send` |

[READ] `/therm/sys-temp` is instructive: `sc/sc.scm:223` opens
`/sys/class/thermal/thermal_zone0/temp`, and :229 pushes the number to the
controller with one argument. The host writes the SoM temperature to the
controller for fan control — a plain, non-calibration example of the same shape.

### 2.4 A second, independent codebase agrees

`las-watchdog` is a small C program using **tinyosc** — its `tosc_printMessage`
format strings sit verbatim at file 0x2cec-0x2d94 (`Error while reading OSC
buffer: %i`, `[%i bytes] %s %s`, ` Unknown format: '%c'`), and the identical set
is at 0x1dfc-0x1e8c in `las-frontpanel-poll`. It calls
`tosc_writeMessage(buf, 1024, address, format, ...)` at 0x117b8. At VMA 0x11e30:
[READ]

```
11e3c: movw r2,#0x2dd8 -> [sp]  ; vararg  = "normal"  (file 0x2dd8)
11e50: movw r2,#0x2dcc          ; address = "/mode"   (file 0x2dcc)
11e58: movw r3,#0x2dd4          ; format  = "s"       (file 0x2dd4)
11e60: bl   0x117b8             ; tosc_writeMessage
11ec4: bl   sendto              ; -> 203.0.113.2:7770 (htons 0x1e5a at 0x11c98)
```

A one-argument message that sets a mode. Different language, different OSC
library, same convention as `las-comm.scm:120`.

---

## 3. The read path, shown

`las-query` sites use argc **3** — address only, **no OSC arguments** — and then
pull the value out of the reply with `csosc#osc-value`. [READ]

| trace | argc | address | what follows |
|---|---|---|---|
| `las/las-comm.scm:101` | 3 | `/ping` | `las-query` |
| `las/las-comm.scm:245` | 3 | `/v/voices` | `osc?`, `osc-adr`, `osc-arg-count`, `osc-value` ×3 |
| `las/las-comm.scm:256` | 3 | `/info/fwrev` | `osc-value` |
| `las/las-comm.scm:259` | 3 | `/info/git` | `osc-value` |
| `sc/sc.scm:342` | 3 | `/info/git` | `las-query`, then reply to client |
| `sc/sc.scm:346` | 3 | `/v/voices` | `las-query`, `osc-value` |
| `sc/sc.scm:426` | 3 | `/ping` | `las-query` |
| `cal/cal.scm:521, 594, 686` | 3 | (computed) | `las-query`, `osc-value` |
| `las/las-vox.scm:119, 147` | — | `/stat/mix` | `las-vox-query`, `osc-arg-count`, `osc-value-int` |

Verification of one, `sc/sc.scm:342` at VMA 0x3607c: `mov r0,#3` at 0x3608c,
`ldr r3,[r7,#0x20]` = symbol `csosc#osc` (slot 0x281c98), `ldr r2,[r7,#0xc8c]` =
`/info/git` (slot 0x282904), one argument stored at `a[2]`, nothing at `a[3]`.
[READ]

`sc/sc.scm:332-349` is the clearest single window on the whole protocol. It is
`las-sc`'s own OSC server handling a client's `/info/*` request: [READ]

```
:332-345  string-prefix? on the incoming address
:342      (las-query (osc "/info/git"))        ; argc 3 -> zero-argument request
:343      (osc? reply)
:344      (osc "/info/git" (osc-value reply))  ; argc 4 -> one-argument reply
          osc-encode, udp-send                 ;   back to the client
```

**The same address is the request with no arguments and the answer with one.**
That is a standard OSC query idiom and it is what this bus speaks.

---

## 4. Where a `/cal` write actually lands

This is the part `DANGER.md` most needed and it comes out well.

### 4.1 `vxcal.db` is a host SQLite file written by SQL, not by OSC — [READ]

`las-frontend` contains a `las::CalDB` class whose SQL is in plaintext at file
0x7e4d56b-0x7e50014:

```
CREATE TABLE IF NOT EXISTS svf_freq( ... svf_res( ... ladf( ... ladr( ... pid ( ...
CREATE TABLE IF NOT EXISTS cal_info(   cal_results(   tune_info_table(   tcode_table(
REPLACE INTO svf_freq VALUES(     REPLACE INTO ladf VALUES(     REPLACE INTO pid VALUES(
REPLACE INTO tcal_low_table VALUES(   REPLACE INTO lf_table VALUES(?, ?, ?, ?, ?, ?, ?)
SELECT updated, X0, X1, Y0, Y1 FROM gldr  WHERE VOICE == 
SELECT updated, num_points, <col> FROM ladf WHERE VOICE == 
```

The paths are elsewhere in the same binary: `/var/cal/vxcal.db` at 0x7ea726d (in
the command-line option table), `/var/cal/vxcal-test.db` at 0x7e4f757,
`/var/cal/system_uuid` at 0xa3e04f, and the literal
`/usr/bin/vxtune write -c vc -f /var/tuning.vxtune` at 0x7e97241 — the frontend's
own copy of the shell-out `las-sc` also makes. [READ]

The calibration database is a **host-side SQLite file**, read and written by
`las-frontend` with ordinary SQL. **No OSC message writes it.** A `/cal/*`
message cannot touch it. [READ]

### 4.2 Committing is a different address — [READ]

`las-frontend` holds the literals `/save_cal` (0x7e5000a), `/save_tuning`
(0x7e4fb50), `/save_pid` (0xa3e4c3), `/load_tuning` (0xa3e0e0), and
`/cal/cal_sw_version` (0x7e4fb5d). `las-sc` holds `/load_cal` (blob at 0x1f53e0)
and `/load_tuning` (0x1f53ef) — **and no `save` verb at all.**

The same split appears one level down, in the firmware itself:

* voice card `app_vx_10M`, decoded 0x1bc52-0x1bc9b: `cal`, `min-main-vca`,
  `save_ca`(l), `data save`, `load`, `tuning` — `cal` and `save_cal` are separate
  commands. [READ]
* controller `app_las`, decoded 0x0dc2c-0x0dc49 (front-panel calibration region):
  `_default`, `save`, `load`, `print` as sibling verbs. [READ]

So the design is uniform at all three levels: **set the value, then separately
commit it.** [INFERRED, from three independent instances of the same split]

### 4.3 The search-loop argument — [INFERRED]

`cal/cal.scm`'s calibration is a bisection/Brent search that writes a coefficient,
waits, measures, and repeats — six `argc 4` `las-vox-send` sites inside one loop
(§2.2). A design in which each of those probes committed to flash would destroy a
voice card's flash in a single calibration pass. It does not; therefore a bare
`/cal/... <value>` sets a live value, and persistence needs the separate verb.
This is the strongest single argument in the file for the volatile/persistent
split, and it is an inference, not a read.

### 4.4 The host copy can re-provision a card — [READ]

`las-sc` carries these log literals:

```
checking voices for existing tuning / cal data
<n> has tuning / cal data
no cards needed tuning / cal data
writing tuning and cal data to voice <n>
finished writing tuning / cal data to voices
```
plus the internal procedure names `tune-the-untuned`, `update-vx`,
`gen-tuning-tables`, and three `system()` calls at `sc/sc.scm:609`, `:616` and
`:623` whose command strings are built at `:610`, `:617` and `:624` from the
literal `/usr/bin/vxtune write -c vc -f ` (VMAs 0x337b0, 0x33514, 0x33278).
`/etc/init.d/S42sc` starts it with
`--vxdb=/var/tuning.vxtune` on **every boot**. [READ]

**[INFERRED]** Both the card and the host hold a copy. The card's copy is
persistent (otherwise the boot-time check would always find none). The host copy
is the re-provisioning source, and `captures/backup/` is a verified copy of it.
So a card whose cal was corrupted is recoverable from files this project already
holds — but note `tune-the-untuned` only fires for a card with **no** data, so
recovery from *wrong* data would need `vxtune write` run deliberately, not a
reboot.

### 4.5 Answering the question as asked

**A `/cal` write lands in the voice card's live state, not in `vxcal.db` and not
(without a separate `save` verb) in the card's flash.** `vxcal.db` is written only
by `las-frontend`'s SQL. The irreplaceable artefacts are the host files, and those
are backed up. [READ] for `vxcal.db`; [INFERRED] for the flash half.

---

## 5. The correction: arity is the convention, not the mechanism

Two pieces of factory software send **one-argument messages as reads**:

* **`las-watchdog`** — helper at VMA 0x12140 builds
  `tosc_writeMessage(buf, 1024, address, "i", 1)` (format string `"i"` at file
  0x2e0c, the literal `1` at 0x12234), `sendto` to **203.0.113.2:7770**, then
  `recvfrom` and returns the integer from the reply. Callers: [READ]

  | address (file offset) | use |
  |---|---|
  | `/vx/<n>/ping` (0x3274 + 0x327c) | liveness; expects 1 |
  | `/ping` (0x32b0) | controller liveness |
  | `/v/voices` (0x3358) | logged as `LAS-WATCHDOG : VC REPORTING %d VOICES` |

  If one argument always stored, this watchdog would set the voice count to 1
  every poll. `vx-api-map.md` records `/v/voices → i:16` from a live unit while
  the watchdog was running. [TESTED, `captures/sysmap/vx-api-map.md`]

* **`las-frontpanel-poll`** — `main` at VMA 0x11988 sends
  `tosc_writeMessage(buf, 1024, argv[1], "i", 1)` to 203.0.113.2:**9100** and
  prints the reply's `f` and `i` arguments. An arbitrary-address diagnostic that
  reads by sending one integer. [READ]

* **`vxping`** sends a random **blob** and reports the reply; addresses holding a
  value answer with the value instead of the echo. [TESTED,
  `captures/sysmap/vx-api-map.md`]

**[INFERRED]** The firmware's rule is closer to *"apply the arguments you can
apply to this leaf, then reply"*: read-only leaves ignore what you sent and answer
with their value; settable leaves take a type-compatible value. Arity is what
Moog's *host* software uses to express intent, and it is a reliable convention —
but it is not a firmware-enforced gate, and a one-argument message to a leaf you
have not identified is not made safe by the argument being "wrong".

---

## 6. What is safe to read with zero arguments

### 6.1 It has already been done, to 47 `/cal` leaves

`captures/sweep/core.txt` is a zero-argument sweep of 303 addresses run on this
instrument on 2026-09-02: 182 `404`, 113 `ACK`, 7 `VALUE`, 1 `503`. It includes
**47 `/cal/*` addresses**, every one of which answered `ACK`: [TESTED]

```
/cal/biasfa  /cal/biasfb  /cal/decay  /cal/extin  /cal/gldr/{h,l,x}  /cal/gsvf/x
/cal/hpf  /cal/ladf/{x,x0,x1}  /cal/ladr/{h,l,x}  /cal/mainl  /cal/mainl/x
/cal/mainr  /cal/mainr/x  /cal/noiseccw{,/h,/l,/x}  /cal/noisecw{,/h,/l,/x}
/cal/o1  /cal/o2  /cal/o3  /cal/p1  /cal/p2  /cal/p3  /cal/rm
/cal/svf1f{,/x}  /cal/svf1r{,/x}  /cal/svf2f{,/x}  /cal/svf2r{,/x}
/cal/testosch/{ch,freq,g,wave}  /cal/testoscl/ch
```

plus `ACK /hw/mute`, `ACK /mode`, `ACK /ping`, `ACK /lc/xy/mode`, `404 /hw/hpf`,
`503 /vx/0/info/hwrev`. The instrument has been played since (the USB-MIDI work of
2026-09-05/07), so no oscillator or filter trim was destroyed by that sweep. That
is an informal but real negative control. [TESTED + INFERRED]

**The `DANGER.md` entry under-credits its own evidence.** It says only `/hw/mute`
was tested. In fact 47 `/cal` leaves were, and all survived.

### 6.2 Why almost everything answers `ACK` rather than a value

Only 7 of 303 returned data: `/info/product`, `/info/version`, `/info/versionb`,
`/a/stat/{mainl,mainr,send1,send2}`. [TESTED, `captures/sweep/core.txt`]

**[INFERRED]** A zero-argument message is a request with no values in it. A leaf
that exists to *hold* a settable value has nothing to echo back and answers empty;
a leaf that exists to *report* (identity, telemetry) answers with its reading.
This matches `las-sc` exactly — it only ever zero-argument-queries the reporting
leaves (`/info/*`, `/v/voices`, `/ping`, `/stat/mix`) and, so far as the
resolvable literals go, never a `/cal` or `/p` leaf. It also explains why
`las-frontend` reads calibration values out of `vxcal.db` by SQL instead of asking
the hardware: **the hardware will not tell it.**

Consequence, and it is the practical one: **a zero-argument `/cal` read is safe
but nearly useless.** It proves the address exists. It does not return the trim.

### 6.3 The leaves where zero arguments is NOT safe

A verb has no value to omit, so omitting the value does not disarm it. Do not send
a zero-argument message to:

* `/save_cal`, `/save_tuning`, `/save_pid` — the commit verbs [READ, `las-frontend`]
* `/load_cal`, `/load_tuning` — reload verbs [READ, `las-sc`, `las-frontend`]
* the controller's front-panel calibration verbs `save`, `load`, `_default`
  (and `print`), which sit as siblings in the same table — the *tokens* are
  [READ, `app_las` decoded 0x0dc2c], but the full address they hang off
  (`/cal:save`? `/cal/save`? something under `/lc`?) is behind the compressed
  address table and is **[INFERRED]** at best
* voice-card `save_cal`, `data save`, `aut`, `dftc` [READ, `app_vx_10M` decoded
  0x1bc1b-0x1bc9b]
* `/fw/start`, `/fw/data`, `/reset`, `/hw/enable_pid`, `/hw/reset_khz`
* anything named for an action rather than a quantity

None of these was in the 2026-09-02 sweep. [READ, `captures/sweep/core.txt`]

---

## 7. What could not be settled, and what would settle it

**The firmware's own dispatch rule was not recovered.** Three things block it, in
order of how hard they are:

1. **The address table is compressed.** The controller's OSC name table sits at
   decoded 0x29800-0x2AD90 and 0x3C400-0x3DF00 behind the unsolved LZ77-style
   encoding documented in `docs/arch/xmos-firmware.md` §2. Any per-leaf metadata —
   a type byte, a writable flag, a getter/setter pair — lives in or beside that
   table and is unreadable until the encoding is solved. Reading the raw bytes at
   0x2A2C0 shows only compressed text: no per-entry type or flag field is visible.
   [READ]
2. **No xcore disassembler is available here**, and none of the usual tools
   (`objdump` targets, radare2, capstone) is installed. Apple's `objdump` handles
   the ARM host binaries and nothing else.
3. **But the code is *not* compressed**, so this is worth another attempt.
   [INFERRED] Byte entropy across 0x0000-0x3C000 of the decoded controller image
   is a uniform 7.0-7.35 bits, which looks like compressed data — but the
   *halfword* distribution is strongly skewed: 24,613 distinct 16-bit values in
   79,872 slots, with `0xf001` ×598, `0x17ff` ×474, `0xf000` ×435, `0xf002` ×374,
   `0xf003` ×293 dominating. The voice card shows the same shape (`0x17ff` ×1347).
   That is the signature of a fixed-16-bit-width ISA, not of an entropy coder.
   The earlier reading that "the images are decompressed at boot" (from the
   segment table's size ratios) is probably wrong for the code segments.

**What would settle it, in order of cost:**

* An xcore disassembler (the `xmos/tool_xmos_*` open-source stack, or a hand
  table for the ~40 opcodes that matter). With uncompressed code, finding the OSC
  parser's branch on the type-tag string is then a normal reverse-engineering job.
* Solving the string encoding (`recon/strtab_decode.py --rosetta`), which would
  expose whatever metadata sits beside each address.
* **Zero-risk hardware confirmation of the volatile/persistent split**, which is
  the only claim in §4 that is inferred rather than read: send nothing. Power the
  instrument down and up, and compare `md5sum /var/cal/vxcal.db` and
  `/var/tuning.vxtune` before and after a *normal play session*. If they are
  stable across boots, the host copies are not being rewritten by ordinary
  operation, which is what §4.4 predicts. Still no packets.
* The write side cannot be confirmed without writing, and must not be.

---

## 8. What this changes in `DANGER.md`

Recorded here, not edited there.

1. The `[INFERRED]` entry "Calibration writes" can be promoted to **[READ]** for
   its central claim: one argument writes, zero arguments does not. §2 shows the
   code.
2. Its scarier half is **wrong as written**. "Writes a voice card's trim table
   permanently" overstates it: a `/cal` message sets a live value. `vxcal.db` is
   written by SQL from `las-frontend` and is not reachable by OSC at all (§4.1).
   Persisting to a card needs a separate `save` verb (§4.2).
3. "A zero-argument message to a live setter is inert" should be strengthened
   from one address to **47 `/cal` leaves plus `/hw/mute`, `/mode`, `/ping` and
   `/lc/xy/mode`**, already swept on this instrument, with the results in
   `captures/sweep/core.txt` (§6.1).
4. A **new** hazard belongs in Tier 2 that is not currently there: *verb* leaves
   fire on a zero-argument message. The `/cal` namespace is not uniformly safe to
   probe with zero arguments — the `/save_*` / `/load_*` group and the
   controller's `save` / `load` / `_default` calibration verbs are actions, and
   omitting a value does not disarm an action (§6.3). The 47 leaves already swept
   are all *quantities*; the verbs were not in that sweep.
5. The 168-family `/cal` namespace is **not** as fenced as it looked. Reading it
   with zero arguments is demonstrably safe and demonstrably uninformative: it
   returns `ACK`, never the trim value. The trims are readable, without touching
   the instrument, from `captures/backup/`'s copy of `vxcal.db` — it is SQLite,
   and §4.1 lists its schema.

---

## 9. Reproducing this

```sh
# Argument counts at every csosc#osc call site in las-sc.
#   trace strings:  strings -a captures/arch-harvest/las-sc | grep '\.scm:.*csosc'
#   the argc:       objdump -d --start-address=0x143138 --stop-address=0x143178 \
#                       captures/arch-harvest/las-sc      # /hw/mute, mov r0,#4
#                   objdump -d --start-address=0x3607c --stop-address=0x360ac \
#                       captures/arch-harvest/las-sc      # /info/git, mov r0,#3

# The two C programs that read with one argument.
objdump -d --start-address=0x12140 --stop-address=0x122a0 captures/arch-harvest/las-watchdog
objdump -d --start-address=0x11b84 --stop-address=0x11bec  captures/arch-harvest/las-frontpanel-poll

# The calibration database schema and the commit verbs.
strings -a -t x captures/arch-harvest/las-frontend | sed -n '/REPLACE INTO/,+40p'
strings -a captures/arch-harvest/las-frontend | grep -E '^/save_|^/load_'
strings -a captures/arch-harvest/las-sc       | grep -E '^/load_|tuning / cal data'

# The zero-argument sweep that was already run on this instrument.
grep -c ACK captures/sweep/core.txt ; grep '/cal' captures/sweep/core.txt
```

Nothing above requires, or should be checked against, a powered instrument.
