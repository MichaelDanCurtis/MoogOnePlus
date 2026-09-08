# Documentation audit — what is wrong, unsupported, stale, or contradicted

Written after the architecture teardown (`docs/arch/*`, `docs/ARCHITECTURE.md`) invalidated a
number of earlier conclusions. `docs/CLAIMS-AUDIT.md` records the corrections that were made;
this file records the ones **still outstanding**, document by document.

**No instrument was contacted for this audit.** Every citation is to a file on this
workstation. Where a claim is checked against the instrument's own source, the file is
`captures/arch-harvest/`.

## Classification

| tag | means |
|---|---|
| **WRONG** | contradicted by an authoritative source, quoted |
| **UNSUPPORTED** | asserted with no evidence, or evidence that turns out circular |
| **STALE** | was true, no longer is |
| **CONTRADICTED** | two documents in this repo disagree; both named |

## Priority

**P0** — would mislead someone working on the instrument into damage, or is going to Moog
and is false. **P1** — materially wrong, would waste real time. **P2** — imprecise or stale
but harmless.

## The P0 list

| § | file | in one line |
|---|---|---|
| 0.1 | three arch docs + `ARCHITECTURE.md:122` | They read our own `-z 256` edit as Moog's configuration, and one still recommends it |
| 0.2 | `xmos-firmware.md:384` vs `control-plane.md:587` | Is a zero-argument `/cal` message a read or a write? The two teardowns disagree, and one says it flatly |
| 1.1 | `BUGS.md:434-518` | Finding 11 tells Moog they left half the machine idle. They pinned the audio thread to it at FIFO 99 |
| 1.2 | `BUGS.md:112-115` | Finding 2 says their firmware has no USB descriptors. It has the exact string finding 2 quotes |
| 1.3 | `BUGS.md:354-416` | Finding 10 blames the wrong cause and says a commented-out SynthDef "compiles cleanly" |
| 1.4 | `patches/0003-…scd` | The `et_spring` patch offered to Moog would misalign every panel parameter |
| 2.1 | `MOOG-ONE-INTERNALS.md:888-912` | Main L/R swapped, phase inversion omitted, and the code sample writes to the wrong buses |
| 2.2 | `MOOG-ONE-INTERNALS.md:59` | Lists `vxtune` as safe to query; `control-plane.md:465` says it runs calibration regardless of args |
| 2.3 | `MOOG-ONE-INTERNALS.md:26-29` | Warns the reader off `S42sc restart`, the only recovery that works |
| 2.4 | `MOOG-ONE-INTERNALS.md:2083, 2292, 2400` | cpu1 called unclaimed in three places, and the audio core in a fourth |
| 3.1 | `DANGER.md:216` | Says a reflash recovers the calibration. Nothing recovers it |
| 3.2 | `DANGER.md` Tier 3 | Six unbounded output stages missing, including the worst one |
| 4.1 | `ASSUMPTIONS.md:5` | "Nothing in this repository has ever contacted the Moog One" |
| 5.1 | `moogd/README.md:204` | The install command pins the web server to the audio core |
| 5.2 | `tools/README-scsynth-jack.md:9-13` | The document's whole premise is the retracted "cpu1 sits near idle" |
| 5.3 | `PLUGIN.md:67-70` | Generalises the LADSPA crash to all 25 effects; 20 of them behave the opposite way |
| 5.4 | `PLUGIN.md:37` | Says parameter automation is "viable today". Writes to the instrument are ignored |
| 5.5 | `README.md:353-355, 423-426` | Same main-output error as 2.1, plus "somewhere that never leaves the instrument" is the sub jack |
| 5.6 | `usb/README.md:80` | A captured log line was edited to agree with a later conclusion |
| 6.1 | `src/moogone/vox/fx.py:24` | Offers `enable` as a writable toggle; on `inputRouter` it frees the send path |
| 6.2 | `effect.py:17`, `BUGS.md:62`, `INTERNALS:1532` | All three quote the commented-out spring's envelope as the shipping one |
| 6.3 | `sampler.py:31`, `fm.py:34`, `record.py:8` | Main L/R reversed; `In.ar(0, 2)` is main R + sub R |
| 6.4 | `makeup.py:1` | "Main output" gain stage that gains main R and sub R |

---

# 0. The authoritative sources contradict each other in three places

These have to be settled first, because the other documents cite them.

### 0.1 · P0 · CONTRADICTED — block size: `-z 256` is the project's own edit, and three arch documents read it as stock

The teardown was performed against a `runtime-state.txt` captured **while the project's own
block-size experiment was still in place**. Three authoritative documents therefore record
256 as the instrument's configuration and tell the reader not to change it.

`captures/arch-harvest/init_sc_1.scd:9-10` (verified):

```
Server.named.at(\server_main).options.blockSize = 128;
Server.named.at(\server_main).options.hardwareBufferSize= 128;
```

`captures/arch-harvest/runtime-state.txt:115` (verified):

```
1294 root  scsynth -u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 ...
```

`docs/MOOG-ONE-INTERNALS.md:316-318` explains the discrepancy the arch docs could not:

> "**Confirmed 2026-09-07 by running that test.** `init_sc_1.scd` was edited to
> `blockSize = 256` and `hardwareBufferSize = 256`, the engine restarted…"

So `-z 256` in the harvest is **our edit**, not Moog's. The instrument has since been
restored to 128. The following all need correcting:

| file:line | quote | problem |
|---|---|---|
| `docs/arch/audio-graph.md:66` | "**Block size is 256, not 128.** `-z 256 -Z 256`. `init_sc_1.scd` asks for 128; the running server has 256. Either the harvested `init_sc_1.scd` post-dates the running process, or something else booted `scsynth`." | WRONG. Neither branch is right; the running process post-dated an edit to the file. |
| `docs/arch/audio-graph.md:69-71` | "256 frames @ 48 kHz = **5.333 ms** per control period… **Do not change it** — several feedback delays are tuned around it." | WRONG. The quantum is **2.667 ms** at the restored 128, and the instruction "do not change it" now points the wrong way. |
| `docs/arch/audio-graph.md:245` | "(**5.333 ms at the live `-z 256`**)" | WRONG — 2.667 ms. |
| `docs/arch/audio-graph.md:473`, `:798` | "1 control period late / (5.33 ms @ -z 256)" and "one control period (5.333 ms) of delay" | WRONG — 2.667 ms. |
| `docs/arch/audio-graph.md:895` | "1. **`-z 256` block size.** Every `FbNode`/`LocalIn`/`InFeedback` loop's delay is one block." | WRONG heading; the observation about one-block loop delay stands, the value does not. |
| `docs/arch/effects-engine.md:129-134` | "**`-z 256 -Z 256` contradicts `init_sc_1.scd:9-10`, which asks for 128/128.**… **Treat block size as 256 when reasoning about the live machine, and re-harvest `init_sc_1.scd` before trusting it.**" | WRONG instruction. The file was right; the process reflected our edit. |
| `docs/arch/effects-engine.md:991-992` | "Does the on-device `init_sc_1.scd` really request blockSize 128 when the running scsynth has 256? Re-harvest before trusting §1." | STALE — answered by INTERNALS §4/§8e. Close it. |
| `docs/arch/system-and-failure-modes.md:336-340` | "`init_sc_1.scd` **has been edited on the device since the running `scsynth` was launched**." | Correct diagnosis, wrong culprit — it says nothing about *who* edited it. Should name the project. |
| `docs/arch/system-and-failure-modes.md:974-987` | "**`/usr/share/las-fx/init_sc_1.scd` has been edited on the device.**… **Keep the pristine copy** — `captures/arch-harvest/init_sc_1.scd` is *not* it, it is the modified one." | **WRONG and dangerous to act on.** The harvested copy reads `blockSize = 128`, i.e. it *is* the pristine value. The running process was the modified state, and the file has since been restored. Anyone "restoring the pristine copy" from this instruction would be guessing at a file that is already correct. |
| `docs/ARCHITECTURE.md:31` | "`scsynth` runs with **9 input and 8 output** hardware channels, block size 256, 48 kHz (`init_sc_1.scd`)." | WRONG, and mis-cited: `init_sc_1.scd` says 128, not 256. |
| `docs/ARCHITECTURE.md:122` | "**Block size.** 128 → 256 gave back real headroom and cost 2.7 ms of latency." | **WRONG — this is the retracted recommendation, still standing in the synthesis document.** `docs/CLAIMS-AUDIT.md:19` retracts it: "Insert effects read straight from the ADC, so doubling the block doubles the skew… **128 is correct.**" |

**Suggested correction, everywhere:** state 128 as the instrument's configuration; note that
`runtime-state.txt` was captured during a project experiment that has since been reverted;
replace every 5.333 ms with 2.667 ms; and delete block size from the list of levers.

### 0.2 · P0 · CONTRADICTED — is a zero-argument message to a `/cal` setter a read or a write?

Two authoritative documents take opposite positions on a claim that governs every probe
anyone will ever send this instrument.

`docs/arch/xmos-firmware.md:384-386` asserts it as established:

> "**Most `/cal/*` and `/hw/*` addresses are the same address for reading and
> writing. Sending one with no arguments is a query; sending it with a value is a
> write.** There is no separate setter namespace to avoid."

`docs/arch/control-plane.md:587-588` says it is unproven:

> "Whether sending a zero-arg OSC message to a `/p/*` or `/cal/*` setter reads vs. writes —
> unproven; `vxping` sends a blob, and blob-at-setter behaviour is untested"

`docs/MOOG-ONE-INTERNALS.md:429-431` agrees with control-plane; `docs/MOOG-ONE-INTERNALS.md:2452-2458`
and `:2483-2488` then declare it "**Answered.**" on the strength of a single observation on
`/hw/mute`.

The evidence is also **circular**. INTERNALS:2458 says the `/hw/mute` result is "the first
direct evidence for the assumption the entire 767-address census was built on" — i.e. the
census was conducted *assuming* inertness, and the one datum offered in support comes from
inside that census. `/hw/mute` is a mute toggle, not a calibration coefficient; one address
acking is not evidence that 62 `/cal` leaves behave the same way.

**Suggested correction:** xmos-firmware.md §"The trap that matters most" should be relabelled
**[INFERRED]** and reworded to: *"`/cal/*` and `/hw/*` appear to use one address for read and
write, so a zero-argument message is believed to be a query. This is inferred, not
established — the only direct test is `/hw/mute`, which acked and did not audibly change
anything. Treat every `/cal/*` address as write-capable until a controlled test says
otherwise."* INTERNALS §13 should move the item back from "Answered" to "Inferred, one
supporting observation."

### 0.3 · P1 · CONTRADICTED — where does the analog calibration actually live?

Three positions in three documents:

* `docs/MOOG-ONE-INTERNALS.md:1969-1976` — "`/var/cal/vxcal.db` is **an empty scaffold**. 35 of
  its 38 tables have zero rows… **The real calibration is `/var/tuning.vxtune/`.**"
* `docs/arch/xmos-firmware.md:316-321` — the trim set "is stored **in the card's own flash**,
  not on the Linux side… the host copy is a backup of card-resident state."
* `docs/MOOG-ONE-INTERNALS.md:1985-1987` — "None of this is in the firmware… the tables are
  loaded into the cards at boot by `las-sc --vxdb`."

The last two are incompatible: either the card's flash is authoritative and the host file is a
backup, or the host file is authoritative and is pushed into the cards at boot. This changes
whether losing `/var/tuning.vxtune` is recoverable, which is the single most consequential
question in `docs/DANGER.md`.

Meanwhile the uncorrected version survives in two places:

* `docs/MOOG-ONE-INTERNALS.md:21-25` — "`/var/cal/vxcal.db` and `/var/tuning.vxtune` are the
  **only copy** of your instrument's analog calibration" (never updated after §11a corrected it)
* `docs/arch/system-and-failure-modes.md:962` — "`/var/cal/vxcal.db`, `/var/tuning.vxtune/**` |
  **the only copy of the analog calibration**"

**Suggested correction:** state the position that the evidence supports —
`--vxdb=/var/tuning.vxtune` is on the boot line (`S42sc:4`) and the cards are loaded from it,
so the host file is the master and `vxcal.db` is an empty scaffold — and mark the card-flash
reading in xmos-firmware.md as the inference it is.

### 0.4 · P2 · `docs/arch/audio-graph.md:350` miscounts the plugins it then lists

> "Five plugin `.so` files ship on the device (`table-and-ladspa-listing.txt`):
> `eventide_blackhole.so`, `eventide_hall.so`, `eventide_plate.so`, `eventide_room.so`,
> `eventide_shimmer.so`, `eventide_spring.so`."

Six are listed, and `captures/arch-harvest/table-and-ladspa-listing.txt:4-9` confirms six.
Change "Five" to "Six". The distinction is load-bearing everywhere else in the repo.

---

# 1. `MoogOneFixes/BUGS.md` — the report going to Moog

Audited hardest. A wrong finding here is worse than no finding.

### 1.1 · P0 · WRONG — Finding 11 is built on a premise the teardown destroyed

`MoogOneFixes/BUGS.md:434-450`:

> "## 11. The two-server configuration cannot run — CONFIRMED, and the cause is the build"
> …
> "Under a loaded patch cpu0 saturates while cpu1 remains roughly 87% idle. A single
> Eventide reverb costs 23-33% of one core (finding 4). **The second core of a two-core
> machine is not used for audio at all**, and that is the difference between a reverb
> that fits and one that does not."

`docs/ARCHITECTURE.md:96-110`:

> "| runs | `las-frontend`, X, `sclang`, `las-sc`, panel | **`scsynth`'s audio thread, alone** |
> | scheduling | ordinary | `SCHED_FIFO` **priority 99** |
> `scsynth`'s audio thread is pinned to cpu1 by Moog's own patched `SC_AlsaDriver`…
> **There is no spare core.**"

`docs/CLAIMS-AUDIT.md:12-15`:

> "| \"cpu1 sits idle — 87% idle\" | It runs `scsynth`'s audio thread, alone, at `SCHED_FIFO` 99.
> `taskset -p` shows only a process's MAIN thread, which hid it. |
> | \"Moog reserved a core and never claimed it\" | They reserved it with `isolcpus=1` **and**
> claimed it… The design is complete. |
> | \"The second core is one binary away\" | The binary was never what stood between the
> instrument and its second core. |"

The per-thread evidence is in `docs/MOOG-ONE-INTERNALS.md:2177-2189`: `tid 1342 affinity=2
last-cpu=1 jiffies=71290 policy/prio=1/99`, against 2888 jiffies for the next busiest thread.

Everything downstream of the premise fails with it:

| BUGS.md line | quote | status |
|---|---|---|
| 437 | "`init_sc_2.scd` describes exactly the architecture this hardware needs" | WRONG. `ARCHITECTURE.md:123-125` — it is about moving *non-DSP* work off cpu1, not about gaining a core. |
| 441-447 | the `cpu0 12.6% / cpu1 11.6%` measurement, then "Under a loaded patch cpu0 saturates while cpu1 remains roughly 87% idle" | UNSUPPORTED. Three seconds on a quiet instrument extrapolated to loaded behaviour, and the aggregate `/proc/stat` method is the one INTERNALS:2254-2258 itself disowns ("A figure that does not move when the load moves is not measuring the load"). |
| 449-450 | "The second core of a two-core machine is not used for audio at all" | WRONG. |
| 469-471 | "**The shipped `scsynth` is an ALSA-only build.** `SC_AlsaDriver` is present; `SC_JackDriver` appears **zero** times." | Factually true, framed as a deficiency. `ARCHITECTURE.md:102-104`: "upstream SuperCollider has no ALSA backend at all, and the driver's error strings (`Unsuccessful in setting thread core affinity`) say what it was written for." `SC_AlsaDriver` is the *mechanism that pins the audio thread to cpu1* — the thing the finding says is missing. |
| 510-513 | "**What would fix it is one binary, not three.** Ship a `scsynth` built with the JACK driver… The sharing layer is already on the device, already works, and is not used by anything." | WRONG. Retracted at `CLAIMS-AUDIT.md:15`. |

**This finding tells the manufacturer their engineers left half the machine idle, when in
fact they pinned the realtime audio thread to an isolated core at `SCHED_FIFO` 99 and wrote
a custom ALSA driver to do it.** It is the most damaging item in the report.

**Suggested correction:** withdraw finding 11 entirely, or replace it with what survives —
four small, real defects in files Moog ships (`launch-sc-2` symlinked to `launch-sc-1`;
`~dspGroup` used at lines 68-69 and defined at 77; `~serverANumOuts = 4` against main outs on
buses 0 and 7; `launch-sn` asking for `-dhw:4` and `-S` on an `S24_LE` card) — under a heading
that makes no claim about CPU headroom, and with an explicit note that cpu1 already carries
the audio thread so the configuration is a *code-tidiness* report, not a performance one.

### 1.2 · P0 · WRONG — Finding 2 says the firmware carries no USB descriptors; the teardown found them, and quotes the same string finding 2 quotes

`MoogOneFixes/BUGS.md:112-115`:

> "**No fix offered.** Neither XMOS firmware image on the device contains a USB
> descriptor table or string descriptors, so the gadget stack is not in either of
> them and is not reachable from here."

`docs/arch/xmos-firmware.md:40-43`:

> "The controller image also carries USB descriptor text — `Moog Music, Inc`,
> `LAS internal` (at 0x11C26), ` Clock Selector`, `…ternal Clo…` — so the
> controller is the part that enumerates as the USB network interface the host
> renames to `usbint`."

`BUGS.md:80` itself identifies the gadget by **that exact string**: "`2662:800d`, product
string \"LAS internal\"". The earlier scan (`INTERNALS:1410-1422`) searched the images *before*
the bit-reversal/nibble-swap transforms were known (`xmos-firmware.md:19-31`,
`INTERNALS:1882-1896`), so it was searching ciphertext. Telling a manufacturer that their own
firmware does not contain a string that it demonstrably does contain is the kind of error
that costs the whole report its credibility.

**Suggested correction:** replace with — *"The gadget's USB stack is in the controller image
(`app_las`), which is stored bit-reversed per byte; decoded, it carries the descriptor strings
including the `LAS internal` product string. An earlier pass searched the raw image and found
nothing, which was a transform error, not an absence. No fix is offered because the fault is
in the gadget's USB state machine, which we have not disassembled."*

The same wrong claim is the whole of `docs/MOOG-ONE-INTERNALS.md:1383-1423` ("§8d. Where the
wedging USB gadget's firmware is not") — see §3.9 below.

### 1.3 · P0 · WRONG — Finding 10 blames the wrong cause, and says a commented-out SynthDef "compiles cleanly"

Finding 20 (`BUGS.md:823-826`) already carries the correction:

> "**Correction to finding 10:** `et_spring` is not merely mis-argued, it is **commented
> out** in `synthdefs.scd` (`/*` at L3629, `*/` at L3700). That is why no `.scsyndef`
> exists and why `eventide_spring.so` is unreachable — a cleaner explanation than the
> one first given here."

Verified against `captures/arch-harvest/synthdefs.scd`: `/*` at 3629, `SynthDef(\et_spring,`
at 3632, `*/` at 3700. But finding 10 was never updated, and still reads:

| line | quote | problem |
|---|---|---|
| 354-356 | "**Impact.** One of the six Eventide reverbs you ship cannot be selected on the instrument, and never has been." — under a heading blaming `systemCmd` | WRONG cause. The `LADSPA_PATH` bug is real and separate; the spring is unreachable because its SynthDef is inside a comment block. |
| 379-383 | "`et_spring` has SynthDef source in `synthdefs.scd` beside the other five… but there is no `et_spring.scsyndef`… so an uncompiled definition does not exist to the server." | WRONG. Implies a build step was skipped. It was commented out deliberately or by accident; either way the fix is different. |
| 404 | "Ten control ports either way, so it maps positionally and **compiles cleanly**." | WRONG. It does not compile at all. |
| 406 | "**Instantiated as written it produces silence, measured on hardware**" | UNSUPPORTED as phrased. "As written" it cannot be instantiated. The measurement required uncommenting the block; the report must say so or the manufacturer cannot reproduce it. |
| 370-377 | the `/usr/share/las-fx/ladspa/` vs `/usr/lib/ladspa/` listing, and "Five plugins appear to have been copied into the fallback directory by hand. The sixth was missed" | UNSUPPORTED / at risk of contamination. This project itself later copied `eventide_spring.so` into `/usr/lib/ladspa` (`BUGS.md:413-416`). The listing must be dated and shown to predate our own copy, or it cannot be offered as evidence about Moog's build. |
| 413-416 | "**Verified fixed.** With the plugin copied into `/usr/lib/ladspa` and a definition using the real port order, scsynth reports `LADSPA: Found plugin 29153 (Eventide Spring)` at boot…" | STALE. `eventide_spring.so` has been removed from `/usr/lib/ladspa` and the instrument restored to stock. The result stands as a past measurement; the sentence reads as present state. |

**Also missing, and it changes the proposed fix.** `docs/arch/audio-graph.md:390-394`:

> "Additional divergence nobody has flagged: `et_spring` is **missing the `pan` and `gain`
> arguments** that all five compiled `et_*` defs carry (20 args vs 22). Its control-name
> ordinals are therefore offset by one relative to every other reverb, so the positional
> parameter indexing in `efx_server.scd` would land on the wrong ports if it were ever
> uncommented as-is."

**Suggested correction:** merge finding 20's correction into finding 10, restate the cause as
the comment block, keep the `LADSPA_PATH` `systemCmd` bug as its own finding (it is real and
independently worth reporting), state that the silence measurement was taken with the block
uncommented, and add the missing-`pan`/`gain` divergence.

### 1.4 · P0 · WRONG — `patches/0003-et-spring-correct-ports.scd` would misalign every panel parameter

The patch offered to Moog declares only eight generic controls before its
effect-specific block:

`MoogOneFixes/patches/0003-et-spring-correct-ports.scd:16-33` —
`enable, inBus, outBus, ctlIn, ctlOut, ctl, g_in, g_out,` then `tremIntensity…`

`docs/arch/effects-engine.md:577-595` establishes the contract:

> "Every effect SynthDef begins with the same generic block. `num_generic_params = 11`
> (`efx_server.scd:325, 201`), and the mapping is `panel index k → controlNames[k + 11]`"

with the eleven being `enable, inBus, outBus, ctlIn, ctlOut, ctl, g_in, g_out, wet, dry, pan`
and `mix` as panel parameter 0. The patch omits `wet`, `dry`, `pan` **and** `gain`. Its
control list is 18 long, so `psize = 18 - 11 = 7` and panel parameter 0 resolves to
`controlNames[11]` = `resonance`, not `mix`. **Every knob would be the wrong knob — exactly
the defect the patch exists to fix.**

`docs/arch/audio-graph.md:830-832` is explicit about why the dead controls must stay:

> "`wet` and `dry` are declared in **every** effect SynthDef and used in **none**. Same for
> `ctl`, `ctlIn`, `ctlOut`. They occupy control ordinals, which the front end's positional
> parameter indexing depends on — **deleting them will shift every parameter index.**"

Three further problems with the patch:

1. **It defines a bare `\et_spring`, not `et_spring_1` / `et_spring_2`.** `docs/arch/effects-engine.md:402-414`
   shows `~initEffect` adopting a parked instance only `if (~eventides.keys.includesEqual(effect))`;
   a name that is not in `~eventides` takes the `else` branch and creates a **fresh LADSPA
   Synth**. On the way out (`effects-engine.md:402-405`) it is likewise not parked. Each
   selection would leave a paused LADSPA node behind, on a box with `MemFree: 11 MB`
   (`effects-engine.md:905`).
2. `docs/arch/effects-engine.md:263-267` — the `_1`/`_2` suffix "is the input topology…
   `n==1` feeds the LADSPA plugin `input.sum * 0.45`… `n==2` feeds `input[0], input[1]`".
   The patch implements only the `_2` shape, so dual-mono bus mode has nothing to select.
3. No `.softclip` on the output, where `docs/arch/audio-graph.md:693-694` records that "The
   eventides do `.softclip` (`synthdefs.scd:3422`)", and no `ControlSpec`-mapped `gain`.

The patch header comment (`:7`) repeats the "compiles without complaint" error from §1.3.

**Suggested correction:** rewrite the patch as `et_spring_1` and `et_spring_2` with the full
22-control layout matching `et_plate_*`, add both to `~eventides` in `init_sc_1.scd`, and
keep `doneAction: 1`. Until then the patch should not be sent.

### 1.5 · P1 · WRONG — Finding 6 asks Moog to run a test the project has already answered

`MoogOneFixes/BUGS.md:253-264`:

> "## 6. `/etc/init.d/S42sc` stop/start asymmetry — NEEDS ONE CONTROLLED TEST
> `stop()` kills `sclang`, `jackd`, `scsynth` and `las-sc`. `start()` runs only
> `las-sc`. On its face `restart` should leave a control layer with no audio engine."

`docs/arch/system-and-failure-modes.md:306-330`:

> "**That is wrong, and this is why the field experience contradicts it.**
> **[READ]** `las-sc` contains the literal string `,screen -d -m /usr/share/las-fx/launch-sc-1 &`…
> **`las-sc` spawns the SuperCollider stack itself.**… Starting `las-sc` starts everything.
> `S42sc restart` is symmetric in effect"

with the process tree at `runtime-state.txt:112-115` as corroboration. The test the finding
asks for has been performed, by reading the binary.

**Suggested correction:** withdraw finding 6. If the `0 synths with 105 synthdefs loaded`
observation at `BUGS.md:259-260` is worth reporting, it is a *different* finding — the
restart bug of `docs/arch/effects-engine.md:733-778`, where the frontend is never asked to
re-push and all five slots stay at `\none_1`. That is a genuine, well-evidenced defect and it
is currently absent from the report (§1.9).

### 1.6 · P1 · UNSUPPORTED — Finding 4 retracts the recommendation but keeps the unreliable numbers

`MoogOneFixes/BUGS.md:169-180` presents:

| graph | `-z 128` | `-z 256` |
|---|---|---|
| bare default, 496 ugens | 22% | **17%** |
| a real patch, 682 ugens, five effects routed | 72% | **51%** |

> "That is 21 points of a core handed back for 2.7 ms of extra block latency"

`BUGS.md:182-197` then retracts the *recommendation* — correctly, and well — but leaves the
table and the "21 points" standing. `docs/CLAIMS-AUDIT.md:20` retracts the **numbers**:

> "| \"`-z 256` took a patch from 72% to 51%\" | Measured with a method since found unreliable.
> Re-measured cleanly on the default graph: **16.6% at 128, 12-13% at 256** — about 4 points,
> not 21. Directionally right, magnitude badly overstated. |"

Note also that the honest re-measurement of the *bare default* graph is 16.6%, against the
22% in the table — so the first row is off too. And `BUGS.md:158` ("at 72% of a core") plus
`BUGS.md:539-542` (`ugens=710`) describe a graph that `docs/CLAIMS-AUDIT.md:46-48` identifies
as an experimental leftover:

> "**\"The instrument idles at 82%.\"** That was a 752-ugen graph left over from experiments.
> A freshly booted instrument is 496 ugens and **16.6%** at block size 128."

**Suggested correction:** in the retraction paragraph, add that the measurements themselves
were taken with a method since found unreliable, replace the table with the clean
re-measurement (16.6% vs 12-13% on the 496-ugen default graph), and delete "21 points". State
that the 72%/710-ugen figures describe an experimental graph, not a normal patch. The
surviving finding — *the RT throttle is reachable and the headroom above a normal patch is
thin* — is unaffected and is worth keeping.

### 1.7 · P1 · WRONG — Finding 5's priority table omits the audio thread, and its conclusion depends on that

`MoogOneFixes/BUGS.md:228-240`:

> "`S99final` puts the IPU threads on `SCHED_FIFO` at priority 93 via `chrt -f -p`, directly
> below `scsynth` at 94:
> ```
>   prio 94  scsynth
>   prio 93  ipu1_task  (x2)
> ```
> Realtime tasks share one budget, and this unit logged `sched: RT throttling activated`
> (finding 4). Display and audio are adjacent priorities drawing on the same throttled budget."

The 94 is `scsynth`'s **main** thread. `docs/MOOG-ONE-INTERNALS.md:2177-2182` shows the
per-thread picture: four threads at `policy/prio=1/94` on cpu0, and `tid 1342 affinity=2
last-cpu=1 … policy/prio=1/99` — the audio thread, at 99, alone on cpu1.
`docs/ARCHITECTURE.md:96-100` places everything else, IPU threads included, on cpu0.

So display and audio are **not** adjacent priorities, and they are not on the same core.

**Suggested correction:** show the per-thread table, state that the audio thread is at 99 on
isolated cpu1 while the IPU threads are at 93 on cpu0, and either drop the "same throttled
budget" argument or state explicitly that it is unverified whether the RT throttle is shared
across cores on this kernel. The IPU fault itself (finding 5's actual subject) stands.

### 1.8 · P1 · UNSUPPORTED — Finding 13 concludes "did not write" from an ack

`MoogOneFixes/BUGS.md:592-595`:

> "**`/hw/mute` acknowledges a zero-argument message** rather than returning `400 Malformed
> message`… The instrument went on playing normally afterwards, **so the message matched a
> setter and did not write.**"

The conclusion does not follow — writing `mute = <nothing>` and writing nothing are
indistinguishable from "the instrument went on playing". This is the §0.2 claim, and
`docs/arch/control-plane.md:587-588` calls it unproven.

**Suggested correction:** end the sentence at "matched a setter". Drop "and did not write", or
mark it inferred.

### 1.9 · P1 · WRONG — Finding 1 quotes the commented-out spring's envelope as the shipping one

`MoogOneFixes/BUGS.md:60-64`:

> "`efx_server.scd` creates the five effect slots once during `waitForBoot` and stops them with
> `enable = 0` — whose envelope is `EnvGen.kr(Env.asr(0.1, 1, 2), enable, doneAction: 1)`, and
> doneAction 1 is *pause*."

Verified: `grep -n "Env.asr(0.1, 1, 2)" captures/arch-harvest/synthdefs.scd` returns exactly two
lines — 619 (`stereoOutput`, `doneAction: 2`) and **3657, inside the `/* */` block at
3629-3700**, i.e. `et_spring`. The five live Eventide defs all read
`EnvGen.kr(Env.asr(0.1, 1, 0.1), enable, doneAction: 1)` at lines 3407, 3492, 3576, 3735 and
3817. The release is **0.1 s, not 2 s**.

This is the paragraph that explains to Moog why their own firmware never hits the crash, and it
quotes a definition their firmware does not compile. The 0.1 s figure also matters
independently: `docs/arch/effects-engine.md:973-976` notes that the state machine's
`0.125.wait` leaves only 25 ms of margin against it.

The same wrong quote is at `docs/MOOG-ONE-INTERNALS.md:1532` and `src/moogone/effect.py:17`
(§6.2). Fix all three from the same grep.

### 1.10 · P1 · Gaps — defects the arch reports establish that the report does not carry

Each of these is at least as well evidenced as the findings that are in the report, and
several are more serious. Listed so the decision to include or exclude is deliberate.

| Defect | Source | Why it belongs |
|---|---|---|
| **The restart bug: `S42sc restart` leaves all five slots at `\none_1` and the frontend is never asked to re-push** | `effects-engine.md:733-778` | Three-layer mechanism, fully read from source. This is the user-visible symptom finding 6 half-noticed. |
| **A negative parameter index in a `/fxN` preset reaches backwards into the generic control block, including `\enable`** | `effects-engine.md:665-668` | "`pindex = -1` → `pan`, `-3` → `g_out`, `-11` → `enable`… No guard anywhere." A malformed preset silently kills an effect slot. |
| **Assigning the same eventide defName to both master slots steals the node from slot 3** | `effects-engine.md:793-814` | Silent, and the next change on slot 3 kills slot 4's reverb. |
| **Immortal `~fxEnableCheckRoutine` / waiter routines** | `effects-engine.md:780-791`, `:826-868` | "Sweeping the effect encoder through ten effects leaves nine of them behind", each at 100 Hz forever, with a replay time-bomb. |
| **`chorus_*` / `stereoChorus_*` put feedback in `XFade2`'s `level` slot instead of `pan`** | `audio-graph.md:666-683` | Same class as finding 20 and equally shippable: zero feedback at knob centre, phase-inverted below it. |
| **`resonator_*` `Select.ar` index runs off the array; `bpf` is unreachable** | `audio-graph.md:685-699` | One of four filter settings is unreachable on a shipping effect. |
| **Aux sums double the insert contribution — inserts are +6 dB into aux vs main/sub** | `audio-graph.md:645-664` | A level error on every aux-routed insert. |
| **`mix` is reassigned to the literal `1` in all six `et_*` defs — the control does nothing** | `audio-graph.md:419-421` | A front-panel control with no effect, on every reverb. |
| **`las-dwm` embeds a hardcoded-password reverse SSH tunnel to `remote.moogmusic.com`** | `xmos-firmware.md:391-394` | Same security class as findings 7 and 17, and arguably more serious than either. Its absence from a report that does cover the empty root password is conspicuous. |
| **24 of 33 SynthDefs have stale `rates:` arrays; controls past the array end step with no lag** | `audio-graph.md:731-773` | The named cause of zipper noise, including `send1Gain` lagged and `send2Gain` not. |

### 1.11 · P2 · Smaller items in BUGS.md

| line | quote | tag | note |
|---|---|---|---|
| 3 | "Firmware ~v1.2/v1.3" | CONTRADICTED | `docs/MOOG-ONE-INTERNALS.md:3` says "firmware **v1.8.2**"; `docs/arch/control-plane.md:9-11` establishes `app_las` **v2.1.2** and `app_vx_10M` **v2.1.0**. A report to the manufacturer must name the exact baseline it was taken on. Same string at `MoogOneFixes/README.md:3`. |
| 6 | the `scsynth` command line, `-z 128 -Z 128` | correct now | Worth a footnote saying the unit was restored to the stock 128 before these findings were finalised, since three arch documents record `-z 256` from an earlier capture (§0.1). |
| 60-64 | "`efx_server.scd` creates the five effect slots once during `waitForBoot` and stops them with `enable = 0`" | imprecise | `init_sc_1.scd:73-104` creates **ten** `et_*` synths in `~eventideGroup` in addition to the five slots (`effects-engine.md:79`). The sentence conflates them. |
| 64 | "Nothing in the shipped firmware ever frees one" | narrow the scope | True of LADSPA nodes. Non-eventide effects *are* freed, by `doneAction: 2` (`effects-engine.md:38-42`). Say "never frees a LADSPA node". |
| 670 | "`-rw-r--r-- 1 root root 7 Sep 8 19:11`" | note | A day ahead of the session date. `docs/arch/effects-engine.md:132` flags the same anomaly on `init_sc_1.scd`'s mtime ("Sep 8 2026… is also anomalous"). If the unit's RTC runs ahead, every timestamped piece of evidence in the report inherits it — worth one sentence. |

### 1.12 · P2 · `MoogOneFixes/README.md`

| line | quote | tag |
|---|---|---|
| 3 | "firmware ~v1.2/v1.3" | see §1.10 |
| 25 | "There is **a** retracted entry in `BUGS.md`." | WRONG (count). There are two full RETRACTED sections (`BUGS.md:830`, `:854`) plus a partial retraction inside finding 4 (`BUGS.md:182`). In a document whose whole argument is "the labels are not decoration", the count matters. |

---

# 2. `docs/MOOG-ONE-INTERNALS.md`

The largest document and the one most affected. It has been corrected by **appending**
sections rather than editing earlier ones, so several claims now appear twice in opposite
directions.

### 2.1 · P0 · WRONG — the main-output map is L/R swapped, omits the phase inversion, and the code sample is wrong

`docs/MOOG-ONE-INTERNALS.md:888-912`:

> "**the main outputs are buses 0 and 7 — not 0 and 1.**
> | bus | reaches |
> | **0** | **main L** |
> | **7** | **main R** |
> …
> ```supercollider
> Out.ar(0, sig[0]);
> Out.ar(7, sig[1]);
> ```"

Verified against `captures/arch-harvest/synthdefs.scd:564-565`:

```
Out.ar(7, main[0] * -1);
Out.ar(0, main[1] * -1); // good
```

`main[0]` is left. So **bus 7 is main L and bus 0 is main R**, and both are phase-inverted.
`docs/ARCHITECTURE.md:40-41` and `docs/arch/audio-graph.md:283-290` both agree.

The consequence is stated at `docs/ARCHITECTURE.md:49-50`:

> "The main outs are **7 and 0**, not 0 and 1, and both are inverted. Anything writing
> to the mains has to match that or it cancels against the instrument's own output."

Following the code sample as printed puts left on main R, right on main L, and both in
opposite polarity to whatever the instrument is producing.

**Suggested correction:** swap the table rows, add the `* -1`, and rewrite the sample as
`Out.ar(7, sig[0] * -1); Out.ar(0, sig[1] * -1);`. This also needs fixing wherever it is
carried forward: `:1463` ("Mains are 0 and 7 (§8)") and `:2095` ("the main outputs are buses
0 and 7 (§8)").

### 2.2 · P0 · CONTRADICTED — `vxtune` is listed as safe to query, and the arch report says it is not

`docs/MOOG-ONE-INTERNALS.md:59-60`:

> "A compiled binary with a real argument parser (`vxtune`, `vxreport`, `lassvc`, `vxping`) is
> safe to query. A `#!/bin/bash` script is not."

`docs/arch/control-plane.md:465-467`:

> "**Owner note:** the auto-memory entry \"never run unknown Moog scripts for --help\" is exactly
> this class — the bash launch scripts and **`vxtune`**/`config-las-spi` ignore `--help` and run
> their real action (calibration/reset)."

`docs/arch/control-plane.md:539-540` restates it as a rule: "treat any bare Moog script
(`config-las-spi`, `vxtune`, `launch-*`) as executing its action regardless of args."

`vxtune write` is the calibration writer (`control-plane.md:456-462`). The INTERNALS sentence
names it as safe, immediately under a section headed "`--help` is not safe on this device"
that exists because running an unknown tool locked the instrument up.

**Suggested correction:** remove `vxtune` from the safe list, or replace the whole heuristic
with the one control-plane.md gives — *"`file` and `head` every tool before running it, and
assume anything named `vx*`, `las*` or `config-*` performs its action regardless of
arguments."*

### 2.3 · P0 · WRONG — the `S42sc` asymmetry caution, in the section headed "Scope and cautions"

`docs/MOOG-ONE-INTERNALS.md:26-29`:

> "- `/etc/init.d/S42sc` has an **asymmetric stop/start**: `stop()` kills `sclang`,
>   `jackd`, `scsynth` and `las-sc`, but `start()` relaunches only `las-sc`. Run
>   `S42sc restart` and you get a running control layer with no audio engine
>   behind it. The instrument looks alive and makes no sound."

`docs/arch/system-and-failure-modes.md:1115-1118` names this as correction 1:

> "**§\"Scope and cautions\" — `S42sc` is not asymmetric.** `las-sc` spawns
> `screen -d -m /usr/share/las-fx/launch-sc-1`, which starts `sclang` and `scsynth`.
> Starting `las-sc` starts the whole stack."

and `:330` gives the replacement text: "*`S42sc restart` is the supported recovery and it
works; the loaded patch is lost and it takes about 45 seconds.*"

This one is actively harmful: `S42sc restart` is the **only** software recovery the project
has that works (`system-and-failure-modes.md:1010-1012`, "The recorded track record is
unbroken"), and the caution tells the reader not to trust it. Meanwhile
`docs/MOOG-ONE-INTERNALS.md:1291-1293` recommends it — the same document arguing both ways.

Same wrong claim at `docs/MOOG-ONE-INTERNALS.md:1703`: "`/etc/init.d/S42sc` | audio stack
init — **asymmetric stop/start, see cautions**".

### 2.4 · P0 · WRONG and self-contradicting — cpu1 described as unclaimed in two sections, and as the audio core in a third

The correction landed at `docs/MOOG-ONE-INTERNALS.md:2170-2224` ("The second core is the DSP
core, and it has been in use all along") and it is excellent. The claims it corrects were
never removed:

| line | quote | status |
|---|---|---|
| 2083-2084 | "the ceiling is real: **cpu0 carries the load and cpu1 sits about 87% idle**, so a working split would roughly double the DSP this instrument can do." | WRONG — `CLAIMS-AUDIT.md:12-14` |
| 2292-2295 | "**This changes what the idle second core means.** It is not a core nobody thought to use. It is a core deliberately reserved and then never claimed — the `// dspGroup lives on DSP core` of `init_sc_2.scd`, set up in the bootloader and left waiting for a server that was never shipped." | WRONG — `CLAIMS-AUDIT.md:13`, "They reserved it with `isolcpus=1` **and** claimed it" |
| 2279-2280 | "It is online, and nothing runs there unless explicitly placed with `taskset`." | WRONG as written. `SC_AlsaDriver` places the audio thread there with `sched_setaffinity` inside the process, which `taskset -p` cannot see (`ARCHITECTURE.md:106-108`). |
| 2400-2409 | "**What that leaves is one missing binary.** Not three things, one… **The two-server configuration is not a bug to be fixed and not impossible either; it is one build away.**" | WRONG — `CLAIMS-AUDIT.md:15` |
| 2411-2413 | "**one core of this two-core machine does the audio and the other is nearly idle**" | WRONG |
| 2335 | "Before using a core that has been idle since the instrument shipped" | WRONG (the thermal section's own premise; its conclusion at `:2368-2371` already contradicts it) |
| 2217 | "The only levers are the ones already found: block size (§the throttle finding), and moving work that is *not* DSP off cpu1" | WRONG in part — block size is retracted (`CLAIMS-AUDIT.md:19`). The second half stands. |

**Suggested correction:** delete §"The second core is reserved, not unused" (`:2270-2302`)
and the CPU premise of §"The two-server configuration cannot be made to work"
(`:2077-2084`, `:2400-2413`) outright, and let §"The second core is the DSP core"
(`:2170-2224`) be the document's only statement on the subject. The four `init_sc_2.scd`
defects and the JACK/ALSA driver facts survive on their own as file-level observations.

### 2.5 · P1 · WRONG/STALE — §8e "Block size is the cheapest CPU there is"

`docs/MOOG-ONE-INTERNALS.md:1597-1621` is the source of the retracted recommendation, and is
still written as advice:

> "**Block size is the cheapest CPU there is, and it is set in one line**"
> …
> "the change hands back **21 points of a core**. Adding a sixth effect through a send then
> measures 79% -- under the throttle, where at `-z 128` the same thing measured 101% and
> dropped out audibly."
> …
> "Reverting is the same one line. The backup taken before the change is at
> `/var/init_sc_1.scd.blocksize-backup` on the instrument."

Four separate problems:

1. WRONG — retracted at `docs/CLAIMS-AUDIT.md:19` and, in more detail, at `MoogOneFixes/BUGS.md:182-197`.
2. UNSUPPORTED — the numbers are the unreliable ones (`CLAIMS-AUDIT.md:20`).
3. **The "101%" figure is arithmetically impossible.** `MoogOneFixes/BUGS.md:162-167` already
   says so: "a thread cannot exceed one core, and this one is descheduled near 95% by the very
   throttle being described." That correction never reached INTERNALS.
4. STALE — the instrument has been restored to 128, so the "backup… on the instrument" line
   describes state that no longer exists. `:1616` also says "the five Eventide reverbs cost
   25-31% each" where the rest of the repo says 23-33%.

**Suggested correction:** replace the whole section with the retraction reasoning from
`BUGS.md:182-197` — insert effects read from the ADC, doubling the block doubles the skew
against the analog-direct path, 128 is the correct choice for this design — and record the
clean re-measurement as a fact about cost, not a recommendation.

### 2.6 · P1 · WRONG — `et_spring` "was never compiled"

`docs/MOOG-ONE-INTERNALS.md:2029-2033`:

> "**`et_spring` was never compiled.** The SynthDef source is in `synthdefs.scd`
> alongside the other five and calls `LADSPA.ar(2, 29153, ...)`, but there is no
> `et_spring.scsyndef` in `/usr/share/las-fx/synthdefs/`."

`docs/arch/audio-graph.md:377-380`:

> "1. **The whole SynthDef is commented out.** `/*` at **L3629**, `*/` at **L3700**. `et_spring`
> is never compiled, never stored, and is correspondingly **absent from `synthdef-names.txt`**"

Verified in `captures/arch-harvest/synthdefs.scd`. Also affects the table at `:2037-2044`
(the "compiled: no" cell needs the reason) and `:1519` — "the five Eventide reverbs, which are
LADSPA plugins in `las-fx/ladspa/`" — which is WRONG about the load path: the section three
pages later (`:2020-2027`) establishes that the `export` fails and `LadspaUGen` falls back to
`/usr/lib/ladspa`.

### 2.7 · P1 · WRONG — port ownership table disagrees with control-plane.md, and with itself

`docs/MOOG-ONE-INTERNALS.md:795-804`:

| INTERNALS says | `docs/arch/control-plane.md` says | verdict |
|---|---|---|
| ":797 `22 (TCP)` … `sshd` — **the only TCP listener on the machine**" | ":192 `22/tcp` … `dropbear` (SSH, dev-key gated)" | WRONG. There is no `sshd`; `S50dropbear` starts `dropbear` (`MoogOneFixes/BUGS.md:270-277`). |
| ":798 `7772` … `las-frontend`" | ":188 `7772` … `las-sc`/VC — voice-bus companion port" | CONTRADICTED |
| ":802 `9600` … `las-dwm`" | ":187 `9600` … `las-sc` (2nd), secondary `las-sc` socket (`:2580` in `/proc/net/udp`)" | CONTRADICTED |

And INTERNALS contradicts itself on 7775: `:229` says "`1E57` | 7775 | `las-sc` → `las-frontend`
replies" and `:218` "replies to las-frontend on 7775", while `:799` correctly says `sclang`.
`docs/arch/control-plane.md:184` settles it: "**7775** … **EFX control input.**
`efx_server.scd`: `thisProcess.openUDPPort(7775)`; `las-sc -f localhost:7775` names this as
the \"EFX Server address\"". 7775 is the effects engine's input, not a reply channel to the UI.

### 2.8 · P1 · CONTRADICTED — `fw_printenv` listed as absent, and as the rescue path

`docs/MOOG-ONE-INTERNALS.md:1838`:

> "### Still absent
> `timeout`, `python`, `python3`, `perl`, `base64`, `ss`, `sftp-server`, `fw_printenv`."

`docs/arch/system-and-failure-modes.md:1034-1038`:

> "**6 · U-Boot — [INFERRED] present, and the real rescue path.** `fw_printenv` and
> `fw_setenv` are in `/usr/bin` (`captures/harvest/04-tools.txt`), and those tools exist
> only to manipulate a U-Boot environment."

`system-and-failure-modes.md:1058-1065` calls the U-Boot/A-B-root question "**the single
highest-value thing to confirm**" and its check list opens with `fw_printenv`. If INTERNALS
is right, that entire recovery path is unavailable; if system-and-failure-modes.md is right,
INTERNALS is steering people away from the only non-service-call recovery on the machine.
Resolvable from `captures/harvest/04-tools.txt` alone.

### 2.9 · P1 · WRONG — §8d's conclusion rests on a pre-transform search

`docs/MOOG-ONE-INTERNALS.md:1383-1423` ("§8d. Where the wedging USB gadget's firmware is not")
concludes at `:1417-1421`:

> "**Every USB device must carry a LANGID string descriptor.** Its absence from plain,
> uncompressed images is proof, not inference: the USB stack is in neither file."

The premise at `:1394-1406` is that the images are "plain, uncompressed code". §11a of the
same document (`:1882-1896`) later establishes that they are **not** plain — the controller is
bit-reversed per byte and the voice card nibble-swapped, and that "Every 'the firmware
contains no strings' claim — and there were many — was this, misread."
`docs/arch/xmos-firmware.md:40-43` then finds the USB descriptor strings in the decoded
controller image.

**Suggested correction:** rewrite §8d to say the search was performed before the transform
was known and its negative result does not hold; point to `xmos-firmware.md:40-43`. This is
the same error as `MoogOneFixes/BUGS.md:112-115` (§1.2) and both must be fixed together.

### 2.10 · P1 · STALE — instrument state that has been reverted

| line | quote | note |
|---|---|---|
| 2304-2307 | "### A JACK-capable `scsynth` runs on this instrument — built and tested — `scsynth 3.9.0` built for armhf with `AUDIOAPI=jack`, **installed alongside the shipped binary at `/var/scsynth-jack`**" | `/var/scsynth-jack` has been removed. Rewrite in the past tense and say so. |
| 2139-2140, 2239-2240 | "Both logged `Found 6 LADSPA plugins` — including the spring, which the shipped engine cannot see" | Depended on `eventide_spring.so` having been copied into `/usr/lib/ladspa`; that copy has been removed. |
| 1620-1621 | "The backup taken before the change is at `/var/init_sc_1.scd.blocksize-backup` on the instrument." | Block size restored; backup path no longer meaningful. |
| 2222-2224 | "`moogd` was first run with `taskset -c 1`… It now runs `-c 0`." | `moogd` and `S99moogd` are no longer installed. Reword to past tense. The *lesson* (`ARCHITECTURE.md:110`, "Anything added to this instrument belongs on cpu0") should stay. |

### 2.11 · P1 · STALE — the `.137`/`.138` address advice

`docs/MOOG-ONE-INTERNALS.md:2052-2075` records `192.168.1.137` primary / `.138` secondary and
concludes "**Use `.138` for OSC.**" The later capture
(`docs/arch/control-plane.md:162`, `runtime-state.txt:171-172`) shows **`.136`** primary and
`.138` secondary — the primary lease has already moved once.

`docs/arch/system-and-failure-modes.md:736-759` (F-08) supplies the mechanism INTERNALS
lacked — two DHCP clients, BusyBox `udhcpc` from `S40network:13` and `dhcpcd` from
`S95dhcpd:9` — and adds "**Do not \"fix\" it** by killing one client".

Note F-08's own advice ("Use `moog-one.local`") is incomplete: mDNS answers with the
**primary**, which is the address INTERNALS records as not working for OSC replies. The two
documents together do not give a reliable instruction.

**Suggested correction (both files):** describe the mechanism, not the addresses; and say that
a client must either accept replies from any address on the host or resolve to the secondary,
because the numbering is a DHCP artefact and will move again.

### 2.12 · P1 · WRONG — `:1532` quotes the commented-out spring's envelope

`docs/MOOG-ONE-INTERNALS.md:1531-1537`:

> "```supercollider
> var env = EnvGen.kr(Env.asr(0.1, 1, 2), enable, doneAction: 1);
> ```
> **doneAction 1 is pause, not free.**"

The conclusion is right; the quote is from `synthdefs.scd:3657`, inside the `/* */` block, i.e.
`et_spring`. Every live Eventide def reads `Env.asr(0.1, 1, **0.1**)`. See §6.2 for the full
verification and the two other copies.

### 2.13 · P2 · Counting and cross-reference defects

| line | issue |
|---|---|
| 529 vs 1699 vs `control-plane.md:54-77` | "**767 OSC addresses**" vs "`/usr/bin/las-sc` — **799** OSC address strings" vs "**810 address-like leaves**". Three counts from one binary. `control-plane.md:112-117` reconciles 497 (binary) against ~464 (live) for `/p` specifically; the totals still need one number and one method. |
| 542 vs `control-plane.md:56` vs `xmos-firmware.md:276` | `/cal`: "94" vs "62" vs "168 families". Same problem. |
| 2126-2168 and 2226-2268 | **The section "### Two servers, one per core — run, and the part that is still unproven" appears twice, verbatim.** Delete one. |
| 2158, 2211, 2258 | "(§CPU_COST)" — there is no §CPU_COST in this document. The referent is `moogone.effect.CPU_COST` in `src/moogone/effect.py:207`. |
| 21-25 vs 1969-1976 | "Scope and cautions" still says `vxcal.db` is half of "the only copy"; §11a says it is an empty scaffold. See §0.3. |
| 1517-1519 | "The whole rack is reachable this way: **25** distinct effects" — unsourced, and inconsistent with `audio-graph.md:117` (19 effect families + 5 eventide families) and `xmos-firmware.md:297-299` ("23 effect type names… plus the five reverbs"). |
| 1468 | "64-128 | unused (`-a 129`)" — incomplete. `audio-graph.md:329` gives "17–49, 64–128 | unallocated private buses (95 of the 112 available)". |

---

# 3. `docs/DANGER.md`

The document people will read fastest and act on hardest. Two of these understate a hazard.

### 3.1 · P0 · WRONG — the Red list says a reflash recovers the calibration. Nothing recovers it.

`docs/DANGER.md:216-218`:

> "**Red — reflash if damaged.** `/var/cal/*`, `/var/tuning.vxtune`, `/usr/share/xmosfw/*.bin`,
> `config-las-spi`, `S25xmosfw`, `S42sc`, `S43gui`, `S99final`, `inittab`, `fstab`, the
> `las-*` binaries…"

`docs/arch/system-and-failure-modes.md:962` gives the calibration row its own, different
recovery:

> "| `/var/cal/vxcal.db`, `/var/tuning.vxtune/**` | **the only copy of the analog calibration**
> — 48 oscillator tables, 16 voice files | a backup helps only if the failure is file
> corruption. Nothing else does |"

DANGER.md contradicts itself twice over: `:22-23` says calibration "**cannot be regenerated
without factory equipment**", and `:246-249` says "**neither slot protects the calibration
data**". A reader who skips to the summary table is told the worst hazard in the document is
a reflash away from fixed.

**Suggested correction:** split the row — "**Red — no recovery.** `/var/cal/*`,
`/var/tuning.vxtune`. **Red — reflash if damaged.** `/usr/share/xmosfw/*.bin`,
`config-las-spi`, `S25xmosfw`, `S42sc`, `S43gui`, `S99final`, `inittab`, `fstab`, the `las-*`
binaries, all of `/usr/share/las-fx/**`, and `/boot/moog_splash.fb`." The Red list also drops
two paths the arch table carries: `/boot/moog_splash.fb` and `/etc/authorized_keys`
(`system-and-failure-modes.md:966-967`).

### 3.2 · P0 · UNDERSTATED — Tier 3 lists two ways to hurt a monitor; the teardown documents six more

`docs/DANGER.md` Tier 3 carries the aux DC (`:137-141`) and the delay NaN (`:143-147`) and
stops. `docs/arch/audio-graph.md:715-717, 728-729`:

> "### 6.8 Unbounded output stages
> No `outputRouter` limiter of any kind. Upstream, the following write to a bus with no ceiling:"
> …
> "The vocoders are the worst of these: a 1000× envelope driving 21 resonant band-passes with
> no limiter anywhere in the chain."

The table at `audio-graph.md:720-726` lists `bitcrusher_*` at "up to 15×, no clip",
`vocoder10/16/21_*` with "no clip at all", `tapeDelay_*` at "±6.28", plus `ensemble_*`,
`delay_*`, `bbdDelay_*`.

**Suggested correction:** add a Tier 3 entry naming the class and pointing at
`audio-graph.md` §6.8, with the vocoders called out as the worst.

### 3.3 · P1 · WRONG — "`bbdDelay` and `tapeDelay` … are fine"

`docs/DANGER.md:146-147`:

> "`bbdDelay` and `tapeDelay` in the same file saturate *inside* the loop and are fine."

Bounded in the loop is not bounded at the output. `docs/arch/audio-graph.md:725`:
"| `tapeDelay_*` | loop bounded to ±1.5708 by `.atan`, then `g_scaled` 0…4 → **±6.28** |";
`:722`: "| `bbdDelay_*` | `g_comp = 1.3` × `((gain*1.35)+1)`, after a **2:1 upward expander** |".

**Suggested correction:** "…saturate *inside* the loop, so they cannot diverge to NaN — but
neither is bounded at its output: `tapeDelay` reaches ±6.28 after `g_scaled`, and `bbdDelay`'s
gain sits behind a 2:1 upward expander."

### 3.4 · P1 · UNDERSTATED (omission) — `/dev/watchdog` is a one-line route into the Tier 2 wedge

`docs/arch/system-and-failure-modes.md:899-908` (F-16):

> "**The hazard.** If anything added ever opens `/dev/watchdog` and then stops writing to it,
> the SoC hard-resets 60 seconds later — which is a warm reset, i.e. **F-04, the wedge**."
> "**Rule.** Do not open `/dev/watchdog`."

A warm reset is DANGER.md's own Tier 2 item 1. Any supervisor or health-check daemon added on
the USB stick can reach it by accident. DANGER.md never mentions it.

### 3.5 · P1 · MISGRADED — `FormatUSBDrivePanel` in Tier 4, and `/media/thumbdrive/**` green with no caveat

`docs/DANGER.md:183-185` puts `--test-fixture`, `--script=<path>` and `FormatUSBDrivePanel`
under Tier 4, "audible or operational, no lasting harm". `docs/DANGER.md:208` puts
`/media/thumbdrive/**` in green.

`docs/arch/system-and-failure-modes.md:872-877` (F-14):

> "**Symptom.** **No SSH on the next boot**, `moogd` does not start, and — the sharp edge —
> `S99final` does *not* find the key, so it proceeds to `killall xterm; killall las-dwm;
> mount -f -o remount,ro /`. The instrument boots and plays perfectly and you cannot get in."
> "**Recovery.** Physical: put the correct FAT32/MBR stick in the only USB port and power
> cycle. There is no software recovery from a machine you cannot log into except the serial
> console."

The `k` file lives on that stick. `--script=<path>` is likewise not Tier 4 —
`docs/arch/control-plane.md:260` rates it "**Arbitrary JS execution**… **Danger, see D9**",
and D9's persistence column reads "some (serial/MAC/cal-DB)" (`control-plane.md:534`).

**Suggested correction:** move `FormatUSBDrivePanel` and `--script=<path>` to Tier 2, and
annotate the green row: *"the files are green, the stick is not"* — verify
`ls -l /media/thumbdrive/k` before every reboot or power-off.

### 3.6 · P1 · UNSUPPORTED — "The recovery path — CONFIRMED" rests on an [INFERRED] switch

`docs/DANGER.md:225, 240-242`:

> "## The recovery path — CONFIRMED, and it changes the risk calculus"
> …
> "So a damaged live rootfs is **not** a service call."

The second filesystem is corroborated. The *switch* is not.
`docs/arch/system-and-failure-modes.md:1034`: "**6 · U-Boot — [INFERRED] present, and the real
rescue path.**" `:1053-1056` calls the A/B pair a "signature", and `:1058` calls confirming it
"**the single highest-value thing to confirm**" — i.e. unconfirmed. Nothing in the repo shows
`fw_printenv` output or a read of `lasfwu`. (And see §2.8: the two documents disagree on
whether `fw_printenv` is even installed.)

"Not a service call" is exactly the belief that makes someone accept a risk they otherwise
would not.

**Suggested correction:** retitle "a second rootfs is CONFIRMED, the switch is not", and name
the two read-only commands that would settle it.

### 3.7 · P1 · CONTRADICTED — Tier 1 asserts what Tier 2 spends 35 lines demoting

`docs/DANGER.md:25-26` lists "the `/cal/*` OSC namespace (62 leaves)" under "Written by:",
ungraded. `docs/DANGER.md:97-100` then says:

> "**What is NOT established:** that a one-argument message to a `/cal` address writes
> anything, or where such a write would land"

This is §0.2 surfacing inside a single document. Tier 1 should carry the **[INFERRED]** tag
and point at Tier 2.

### 3.8 · P1 · STALE — present-tense claims about reverted state

| line | quote | note |
|---|---|---|
| 208-210 | "`moogd` is the right shape: the binary and the UI live on the USB stick and cost the root filesystem exactly one file." | `S99moogd` removed; past tense. |
| 232-233 | "`p2` holds the previous release, is **pristine** — no `S99moogd`, factory `blockSize = 128` — and nothing this project has done has touched it." | Reads as *p2 differs from p3 in these two ways*. Both halves are now false: `p3` has been restored to stock too. |

### 3.9 · P2 · smaller items in DANGER.md

| line | issue |
|---|---|
| 231-232 | `las-v1.5.0` (partition label) sits unreconciled beside `v1.8.2` in `MOOG-ONE-INTERNALS.md:3` and `ASSUMPTIONS.md:11`. Say which is a volume label and which is a release. |
| 7 | "**Every entry is graded**" — two entries carry a grade in their heading and one section has inline grades; Tier 1, most of Tier 3, all of Tier 4 and the "Safe to modify" table are ungraded. Either grade them or reword to "graded where the evidence is mixed". |
| 37-38 | "**No signature or checksum check** anywhere in `las-frontend`" — `control-plane.md:331-336` records this as a **NEGATIVE RESULT** and an **INFERRED** conclusion, with `lasfwu` never read. Mark it inferred. |
| 137-138 | "Routing bus effect slot 3 to any aux output writes `dry_dir4_r`" vs `audio-graph.md:27` "driven at runtime by bus-effect **slot 4**'s `/fx3/out` message". Both self-consistent, different indexing. Pin it to the wire message (`/fx3/out`) so a cross-reader guards the right slot. |
| 25 vs 92 | "`/cal/*` … (62 leaves)" against "`/cal` has 168 address families". Both sourced (`control-plane.md:56`, `xmos-firmware.md:276`) but counting different things. Say which is which. |
| 189-202 | The "safety net that is switched off" section omits the other half of what the USB key does: `control-plane.md:495-498` — "`S99final` **skips the read-only remount**… So the key is what makes flash/cal writes *stick* across the session." That belongs beside the "Safe to modify" table. |
| — | `/testosc/*` is absent from DANGER.md entirely. `control-plane.md:487-490`: "inject a raw signal into the analog path… Loud-output / unexpected-routing risk". Tier 3 or 4 material. |

**Checked and sound:** the `/cal` demotion at `:71-107` matches both arch reports and correctly
identifies the circularity in the firmware report's justification. The phone-home entry, the
`/fx/start 1` reload loop, `doneAction: 1`, the two-`/fxN`-within-250 ms waiter leak, the
same-Eventide-on-both-slots steal, the `S99final:36` watchdog kill, the S95dhcpd DNAT port
list, the `2662:800d` gadget, the 234 GB / 3.3 GB / 149 MB figures and the `efx_server.scd:344`
RCE all check out. DANGER.md carries none of the retracted cpu1, block-size or effect-send
claims.

---

# 4. `docs/ASSUMPTIONS.md`

### 4.1 · P0 · STALE — the document's premise, which every claim in it inherits

`docs/ASSUMPTIONS.md:5-7`:

> "**Nothing in this repository has ever contacted the Moog One.** 282 passing tests mean the
> code is internally consistent with assumptions written down in `src/moogone/mock/server.py`."

Contradicted by essentially the whole repo: `docs/MOOG-ONE-INTERNALS.md:3-6` ("Everything here
was read back from a running instrument"), `docs/DANGER.md:9` ("**[TESTED]** — done on this
instrument and observed"), `docs/CLAIMS-AUDIT.md:35`, the 66 files in `captures/` including
five `.pcap`s and `captures/arch-harvest/runtime-state.txt`, and the git log ("usb midi out
works: 44 notes from the keys").

The document is framed as pre-flight caution for a session that has since happened, so a
reader can take it as current guidance on what is and is not known.

**Suggested correction:** replace the headline with something like — *"This file was written
before the instrument was reached. It has been. Everything below described the risk of
building against a mock; read `docs/arch/` first."* The "282 passing tests" figure also needs
re-measuring (`tests/` currently defines roughly 700 `def test_` functions).

### 4.2 · P1 · STALE — "six releases of drift" is resolved, in the reassuring direction

`docs/ASSUMPTIONS.md:9-12` worries that `las-sc` on `localhost:9300`, `/usr/share/las-fx/` and
`/etc/init.d/S42sc` may all have drifted since ~v1.2/v1.3. All three are now read off the
device's own boot script, `captures/arch-harvest/init.d/S42sc:4`, and corroborated at
`docs/arch/control-plane.md:185`. Mark it settled.

### 4.3 · P1 · UNDERSTATED — the socket-binding row offers "direct" as an option

`docs/ASSUMPTIONS.md:23`:

> "| It is bound to `127.0.0.1` vs `0.0.0.0` | `03-sockets.txt` | Decides on-box vs `--tunnel`
> vs direct |"

`las-sc`'s 9300 socket is on `127.0.0.1` (`control-plane.md:185`), so "direct" does not reach
it — and `docs/arch/system-and-failure-modes.md:699-703` shows where it does go:

> "`S95dhcpd:11-14` DNATs UDP 7770, 7771, 9100 and 9300 arriving on `ethext` straight to
> `203.0.113.2` — the gadget… Any host on the LAN that bursts UDP at those ports on the
> instrument's address is bursting at the XMOS, with no rate limit in between."

That is F-05, which DANGER.md Tier 2 grades as needing power removed.

ASSUMPTIONS.md also never mentions the UDP pacing interlock, which
`system-and-failure-modes.md:1000` calls mandatory ("**Pace UDP.** The §8c interlock is not
optional."). For a document meant to be read immediately before pointing the toolkit at the
instrument, that is the omission that matters most.

### 4.4 · P2 · STALE — §3's premise and the closing paragraph

`:63-64` "`sclang` was unavailable throughout… nothing has ever run it" — the unavailability
was on the *workstation*; `sclang` is the effects engine on the instrument
(`effects-engine.md:283-284`). `:116-117` "The `dumpOSC` capture in step 6 is what converts
this from assumption to fact. Everything above is provisional until then." — the capture
exists, `captures/dumposc.log`. `:3` "Read this before the September session" needs re-dating.

---

# 5. `README.md`, `docs/PLUGIN.md`, `moogd/README.md`, `usb/README.md`, `tools/README-scsynth-jack.md`

### 5.1 · P0 · WRONG — `moogd/README.md:204` pins the workbench to the audio core

The copy-pasteable install command at the bottom of the file:

```
ssh root@<ip> 'taskset -c 1 /media/thumbdrive/moogd -addr :8080 &'
```

Contradicted by its own file 189 lines earlier — `moogd/README.md:15`: "**Run it on cpu0, NOT
cpu1.** cpu1 looks free … and it is not: it is where `scsynth`'s audio thread runs, pinned
there by Moog's own ALSA driver at `SCHED_FIFO` 99." — by `usb/S99moogd:61` (`taskset -c 0`),
by `docs/ARCHITECTURE.md:110` ("**There is no spare core.**"), and by `docs/CLAIMS-AUDIT.md:16`
("`taskset -c 1` put a web server **on the realtime audio core**. It runs on cpu0 now.").

**Fix:** `taskset -c 0`, with a pointer back to the top of the file.

### 5.2 · P0 · WRONG — `tools/README-scsynth-jack.md:9-13` is built on the retracted premise

> "That single choice is what pins the whole instrument to one core. `scsynth` is
> single-threaded for DSP and is pinned to cpu0 (`affinity mask: 1`), while cpu1 sits near
> idle. Two `scsynth` processes cannot share the card … so without JACK there is no way to
> reach the second core."

`affinity mask: 1` is the **main** thread — the exact trap `docs/CLAIMS-AUDIT.md:12` names.
`docs/ARCHITECTURE.md:99-100` puts "**`scsynth`'s audio thread, alone**" on cpu1 at
`SCHED_FIFO` 99. `docs/CLAIMS-AUDIT.md:15` retracts "one binary away".

This is the premise the whole document rests on, so it needs a rewritten opening: the audio
thread is already on cpu1; JACK does not unlock a spare core, it only allows a second
`scsynth` against the card, and only with the audio stack stopped.

### 5.3 · P0 · WRONG — `docs/PLUGIN.md:67-70` generalises the LADSPA crash to all effects

> "* **Never `/n_free` one of the instrument's effects.** It terminates scsynth. They are
> created once at boot and never freed by Moog's own code… Stop one with `enable = 0`, which
> releases an envelope whose doneAction is *pause*."

True only of the five Eventide LADSPA families. `docs/arch/effects-engine.md:38-42`:

> "every `et_*` SynthDef uses `EnvGen … doneAction: 1` (pause) while **every other effect uses
> `doneAction: 2` (free)** … vs. 26 occurrences of `doneAction: 2`."

`docs/CLAIMS-AUDIT.md:31` scopes it correctly ("`/n_free` on a **LADSPA** node"). The
project's own code already gets this right — `src/moogone/effect.py:312-332` documents both
behaviours and records the bug that follows from assuming the node survives. A plugin author
following PLUGIN.md will hold a stale node id for the other twenty effects and hit exactly
that.

### 5.4 · P0 · WRONG — `docs/PLUGIN.md:37` claims parameter automation is viable

> "| **Control surface** | DAW automation of the instrument's parameters | **viable today** —
> needs only OSC |"

`docs/MOOG-ONE-INTERNALS.md:918-927`, headed "**The instrument is readable everywhere and
writable nowhere**": three injections on three protocols, "all **confirmed to arrive** and all
ignored". What is writable is `scsynth`'s effect nodes, not the instrument's `/p` tree.

### 5.5 · P0 · WRONG — `README.md:353-355` mislocates the right channel and omits the inversion

> "**The main outputs are buses 0 and 7**, not 0 and 1, and `Out` writes *consecutive* buses —
> so a stereo signal into `Out bus 0` sends its right channel somewhere that never leaves the
> instrument."

Bus 1 is a physical output: `docs/arch/audio-graph.md:284` "| 1 | **sub R** |". The right
channel does not vanish, it comes out of the **sub jack**. And the passage omits the phase
inversion, which is the thing that actually breaks a patch —
`docs/ARCHITECTURE.md:49-50`: "both are inverted. Anything writing to the mains has to match
that or it cancels against the instrument's own output."

Same omission at `README.md:423-426`, where the sampler's two writes are presented as the
complete set of non-obvious details. Per `audio-graph.md:292` the sampler is currently layering
polarity-inverted against the analog path it is deliberately stacked on.

This is the same defect as §2.1 in `MOOG-ONE-INTERNALS.md`; fix all three together.

### 5.6 · P0 · Evidence integrity — a captured log line in `usb/README.md` was edited to match a later conclusion

`usb/README.md:78-83` presents a cold-boot transcript:

```
uptime 386s
running: 1703   affinity=1  last-cpu=0  ppid=1
```

followed at `:85-86` by "*(That cold boot predated the discovery that cpu1 is the audio core;
the script now uses `taskset -c 0`…)*". A boot that predated the fix cannot report the
post-fix affinity.

Verified with git: commit `93f8409` ("cold boot works…") recorded
`running: 1703   affinity=2  last-cpu=1  ppid=1`; commit `f35da58` ("consolidate the danger
list") rewrote that captured line to `affinity=1  last-cpu=0`. The original is what
`docs/arch/system-and-failure-modes.md:502-505` quotes:

> "But `usb/README.md` records a cold-boot test showing `affinity=2 last-cpu=1` — mask `0x2`
> is **cpu1**. That output cannot have come from the `taskset -c 0` in the current file."

and it is the sole evidence for failure mode **F-13** (`:848-857`). As the file now stands,
F-13 is unfalsifiable and the arch report looks like it misquoted.

**Fix:** restore the log verbatim to `affinity=2  last-cpu=1` and let the parenthetical carry
the correction. A measurement record should never be edited to agree with a later conclusion —
the parenthetical is the right mechanism and it is already there.

### 5.7 · P1 · Bad numbers a design would be sized against

| file:line | quote | problem |
|---|---|---|
| `docs/PLUGIN.md:163-164` | "**single-threaded for DSP** (the second core does not help), and runs `SCHED_FIFO` at priority −95." | WRONG. −95 is the `PR` column for the **main** thread (FIFO 94); the audio thread is **99** (`ARCHITECTURE.md:100`, `system-and-failure-modes.md:818`). "The second core does not help" inverts the picture — the DSP *is* on the second core. |
| `docs/PLUGIN.md:162, 167-169` | "`scsynth` idles at **55.2% of one core**… roughly 45% of one core for anything a plugin asks the instrument to compute" | UNSUPPORTED and circular: the only source in the repo is `src/moogone/fm.py:51` `BASELINE_CPU = 0.552`, whose docstring points back here. Superseded by `CLAIMS-AUDIT.md:46-48` — a freshly booted instrument is 496 ugens and **16.6%**. The "45%" is also wrong against the 95% throttle ceiling, and `ARCHITECTURE.md:131` rules the conclusion out ("Big added DSP. There is no core to put it on"). |
| `docs/PLUGIN.md:72-73` | "* **Run the effect on private buses.** Buses 64 and up are unused." | WRONG. `audio-graph.md:329` gives **17–49 and 64–128**; `:75-77` bounds valid indices at 0…128 with anything higher "silently discarded by `Out`"; `:327-328` shows 100/101 and 200/201 are shipped-def defaults. As written this invites a plugin to write to bus 200 and get silence with no error. |
| `moogd/README.md:189-190` | "**The screen mirror.** Direct `/dev/fb0`, **on cpu1**. … it removes the thing currently **saturating the audio core**." | WRONG twice. Recommends the audio core; and `CLAIMS-AUDIT.md:17` retracts the second half — "It saturates cpu0, which is the *shared* core". The same file says so correctly at `:38-40`. |
| `moogd/README.md:120-121` | "the Python bridge doing the same job over SSH on cpu0: **511 ms and 52 kB every 0.4 s, saturating the audio core**" | WRONG, and self-contradicting within the sentence ("on cpu0 … the audio core"). |
| `moogd/README.md:51` | "- pinned to the isolated core, confirmed `mask=2 last-cpu=1`" — listed under "## What is proven" | WRONG. `mask=2` is cpu1. `CLAIMS-AUDIT.md:16` retracts it; `system-and-failure-modes.md:848-857` files it as **F-13**. |

### 5.8 · P1 · STALE — reverted instrument state

| file:line | quote | note |
|---|---|---|
| `tools/README-scsynth-jack.md:60-69` | "`ssh root@<ip> 'cat > /var/scsynth-jack && chmod +x /var/scsynth-jack' < scsynth`" under "## Installing" | `/var/scsynth-jack` removed. Head the section "**Not currently installed.**" and keep the commands. |
| `tools/README-scsynth-jack.md:73-75` | "**Not yet run against `jackd`** — that needs the audio stack stopped so the card is free, and is the next step." | CONTRADICTED. `CLAIMS-AUDIT.md:54-56`: "both registered as JACK clients and server B executed on cpu1. But cpu1 was only free because the audio stack was stopped for the test." Rewrite as done, and say it is a bench configuration, not a way to gain DSP. |
| `usb/README.md:29-34, 52-57, 99-101` | "**One new file: `/etc/init.d/S99moogd`.**… If `moogd` dies it stays dead until the next boot or a manual `/etc/init.d/S99moogd start`." | All present tense about a file no longer on the instrument. `:99-101` describes live runtime behaviour of an uninstalled service. |
| `moogd/README.md:181-197` | "## What is not done", items 1-2 | Both documented as done earlier in the same file (`:109` "## The screen mirror, built — measured on the instrument"; `:141` "## The real Vox UI, served by the instrument — working"). |
| `usb/README.md:74-76` | "## Not done" heading above "**A cold boot is tested and works.**" | Heading not updated when the content was. |

### 5.9 · P1 · `README.md` — the front page is wrong about the project and about the tooling

| line | quote | tag |
|---|---|---|
| 6-10 | "**Nothing in this repository has ever touched the hardware.** The whole toolkit was built against a mock server." | STALE, and the first thing a reader sees. The same file then reports dozens of hardware measurements (`:208`, `:276`, `:323`, `:414`, `:604`, `:611`). |
| 16-17 | "The hardware window is short and does not repeat. **Print this page.**" | STALE — sessions ran 2, 3, 4, 5, 6 and 7 September. |
| 3-4, 65, 201 | "talking to the Moog One's internal SuperCollider audio engine (`las-sc`, OSC over UDP)"; "Confirms `las-sc` speaks the SuperCollider protocol at all."; "A mock scsynth. Where this project's assumptions about `las-sc` are written down." | WRONG. `las-sc` is the voice-card controller on 9300; the SuperCollider server is `scsynth` on 57110 (`control-plane.md:182,185`). `README.md:51` says so itself, and `MOOG-ONE-INTERNALS.md:256-264` has a whole section headed "A correction worth inheriting" about exactly this conflation. The front page still makes the mistake the document warns about. |
| 167-180 | "`scp -r src/moogone root@<ip>:/tmp/`" then "`cd /tmp && python3 -m moogone.cli status`" then "Check `06-toolchain.txt`… for whether `python3` exists on the device at all." | CONTRADICTED, twice settled. `MOOG-ONE-INTERNALS.md:1836-1838` lists `python3` under "Still absent"; `moogd/README.md:9-11` — "**The instrument has no interpreter.**" And the `scp` fails: `MOOG-ONE-INTERNALS.md:1849-1850` — "macOS `scp` uses SFTP and dropbear has no `sftp-server`. Use `cat file \| ssh root@host 'cat > /dest'`." |
| 30, 32 | `scp recon/moog-recon.sh root@<ip>:/tmp/` and `scp -r root@<ip>:/tmp/moog-recon ./captures/` | WRONG — step 2 of the printed checklist, and both fail from macOS for the reason above. `README.md:368` gets it right elsewhere in the same file (`scp -O`). |

### 5.10 · P2 · Omissions worth adding

* `usb/README.md:21` — the install block runs `mkdir -p /media/thumbdrive/vox` over SSH. If
  the mount is absent, `mkdir -p` silently creates the directory on the **root filesystem** and
  2.2 MB of UI lands in the 148 MB of free rootfs. `system-and-failure-modes.md:863-877` (F-14)
  records that the drive actually mounts at `/var/local/media/sda1`. Prefix with a
  `mountpoint -q` check.
* `docs/PLUGIN.md:41-49, 180-182` — presents adding an effect on private buses as clean, and
  never mentions that the instrument already ships a complete five-slot rack.
  `docs/ARCHITECTURE.md:88-90`: "**The rack already exists and is complete.**… Anything that
  adds 'an effect send' is rebuilding infrastructure the instrument already has."
  `CLAIMS-AUDIT.md:21`: "**Adding a sixth effect is what caused the dropouts** that then
  motivated the block-size change." The file's own promise at `:3-5` — "where a thing is
  unproven it is marked unproven and the design does not lean on it" — is not met here.

**Checked and sound:** port 57110 vs 9300 (`README.md:48-51`), the `/lsleds` LED-write result
(`README.md:526-541`), parameter 358 / MIDI CC 7 (`README.md:551`), the 375 Hz block-rate line
(`README.md:226-228`), the latency measurements in `docs/PLUGIN.md` (all trace to
`MOOG-ONE-INTERNALS` §8a–§8e), the 1 ms UDP pacing claim against
`src/moogone/transport/udp.py:31`, the mmap-vs-read and atlas-encoding measurements in
`moogd/README.md:63-139`, and the glibc/GLIBCXX ABI constraints in
`tools/README-scsynth-jack.md:26-58`.

---

# 6. Docstrings in `src/moogone/`

### 6.1 · P0 · Missing safety warning — `vox/fx.py` offers `enable` as a writable switch on any live node

`src/moogone/vox/fx.py:24`: `_SWITCH = {"enable"}` — classified as an ordinary 0…1 toggle.
`src/moogone/vox/fx.py:51-52` states the intent:

> "# do not pretend to a range: show the value and refuse to write. Guessing at an
> # unnamed control on a live audio router is how this project locked the synth up."

Two problems.

**(a) Nothing refuses.** `FxWorkbench.set` (`vox/fx.py:101-103`) sends `/n_set`
unconditionally, and `Bridge._fx_set` (`vox/bridge.py:1295-1304`) passes whatever node id and
control name arrive over the WebSocket. `kind` is consulted only when building the router
destination list (`vox/bridge.py:1008`). "Refuse to write" describes an intention, not the
code.

**(b) `enable = 0` is not a pause on most of the instrument's nodes.** Verified directly in
`captures/arch-harvest/synthdefs.scd`: only six sites use `doneAction: 1`, at lines 3407,
3492, 3576, 3657, 3735 and 3817 — the five live `et_*` families plus the commented-out spring.
Everything else uses `doneAction: 2` (free). Including `inputRouter`, at
`captures/arch-harvest/synthdefs.scd:377`:

```
env = EnvGen.kr(Env.asr(0.1, 1, 0.1), enable, doneAction: 2);
```

So **`enable = 0` on `inputRouter` frees the instrument's entire insert/master send path**, and
setting it back does nothing because the node is gone. `docs/arch/effects-engine.md:38-42`
states the split; `docs/DANGER.md:176-178` states the invariant.

**Suggested correction:** classify `enable` as read-only on any node this project did not
create, make `FxWorkbench.set` enforce `kind` rather than leaving it advisory, and replace the
comment with the fact: *`enable = 0` releases an ASR envelope whose `doneAction` is 2 (free) on
26 of the instrument's 33 synthdefs, `inputRouter` included. Only the five `et_*` families
pause.*

### 6.2 · P0 · WRONG — `effect.py:14-19` quotes the commented-out spring's envelope as the shipping one

> "Moog create their effects once at boot and stop them with `enable = 0`, whose envelope is
> `EnvGen.kr(Env.asr(0.1, 1, 2), enable, doneAction: 1)`, and doneAction 1 is *pause*."

Verified: `grep -n "Env.asr(0.1, 1, 2)" synthdefs.scd` returns exactly two lines — 619
(`stereoOutput`, `doneAction: 2`) and **3657, which is inside the `/* */` block at 3629-3700**,
i.e. `et_spring`. The five *live* Eventide defs all read `Env.asr(0.1, 1, 0.1)` (lines 3407,
3492, 3576, 3735, 3817). The release is **0.1 s, not 2 s** — which is exactly the number
`docs/arch/effects-engine.md:973-976` says has only 25 ms of margin against the state
machine's `0.125.wait`.

**The same wrong quote is in two other places, one of them going to Moog:**

* `MoogOneFixes/BUGS.md:62` — "whose envelope is `EnvGen.kr(Env.asr(0.1, 1, 2), enable,
  doneAction: 1)`". The report quotes a commented-out definition to the manufacturer as if it
  were the shipping one, inside the finding (§1) whose whole argument rests on that envelope.
* `docs/MOOG-ONE-INTERNALS.md:1532` — same string.

Two smaller errors in the same `effect.py` paragraph: "it took the audio engine down **three
times**" against `docs/CLAIMS-AUDIT.md:31` ("Confirmed **2/2**") and `src/moogone/ingress.py:46`
("twice out of two"); and "That rule lives here, once, and `moogone.ingress` imports it rather
than keeping a second copy that could drift" — `ingress.py:44-51` **is** a second prose copy,
and it has already drifted in both particulars.

### 6.3 · P0 · WRONG — main L/R reversed in three modules

Ground truth, `captures/arch-harvest/synthdefs.scd:564-565`, verified:

```
Out.ar(7, main[0] * -1);
Out.ar(0, main[1] * -1); // good
```

`effect.py:66-74` gets it right and says so. Three modules still carry the tone-sweep reading:

| file:line | quote | fix |
|---|---|---|
| `src/moogone/sampler.py:31-33` | "`MAIN_LEFT = 0` / `MAIN_RIGHT = 7`" | swap |
| `src/moogone/fm.py:34-36` | "`MAIN_LEFT, MAIN_RIGHT = 0, 7`" | swap |
| `src/moogone/record.py:8`, `:67` | "`In.ar(0, 2)` reads the main output bus", `bus = 0` default | `In.ar(0, 2)` reads buses 0 **and 1** = main R + **sub R** (`audio-graph.md:283-284`). Capturing the main pair means reading 7 and 0 separately. |
| `src/moogone/netaudio.py:51-53` | same shape, "Writes the instrument's output bus", `bus = 0` | same |

Neither `fm.py` nor `sampler.py` mentions the `* -1`, so their voices are opposite in polarity
to the instrument's own output — which matters because the sampler deliberately layers rather
than replaces.

### 6.4 · P0 · WRONG — `makeup.py` is described as a main-output stage; it gains main R and sub R

`src/moogone/makeup.py:1`: "A makeup gain stage for the instrument's main output."
`:44-45`: `"|bus = 0, …| ReplaceOut.ar(bus, Limiter.ar(In.ar(bus, 2) * gain, ceiling, 0.005))"`.

With `bus = 0`, that is buses 0 and 1 — main **R** and sub **R** (`audio-graph.md:283-284`).
Main L (bus 7) and sub L (bus 2) are untouched, so applying it produces a channel imbalance of
the full makeup amount on the mains and silently gains one leg of the sub output.

**Suggested correction:** say what it covers, and either instantiate twice (buses 7 and 0) or
state the limitation prominently. The measurement quote at `:7` is fine but should read
"main R".

### 6.5 · P1 · STALE — `effect.py`'s spring section asserts a reverted instrument state

`src/moogone/effect.py:136-143`:

> "#: Copy it into the directory scsynth actually reads and restart the audio engine:
> #:     cp /usr/share/las-fx/ladspa/eventide_spring.so /usr/lib/ladspa/
> #: Confirmed by scsynth's own boot line: `LADSPA: Found plugin 29153 (Eventide Spring)`."

and `:446-447`: "The sixth Eventide -- shipped with the instrument and **unreachable on it
until now**."

`eventide_spring.so` is no longer in `/usr/lib/ladspa`. This is not cosmetic:
`vox/bridge.py:584` warms `ensure_spring()` at startup and `EffectSend.engage(SPRING_DEF)` will
now send a SynthDef whose `LADSPA.ar(2, 29153, …)` scsynth cannot resolve, while `PRESETS`
still advertises it as working.

**Suggested correction:** mark the `cp` block as a prerequisite that is **currently not
satisfied**, and reword the preset description.

### 6.6 · P1 · WRONG — `effect.py:113-114` and `:110-112` on `et_spring` and `LADSPA_PATH`

> "#: 2. `et_spring` has SynthDef source but was never compiled to a `.scsyndef`"

Commented out at `synthdefs.scd:3629`-`:3700` (§0.1 verification). Same correction as §1.3.

> "#: 1. …scsynth, which falls back to `/usr/lib/ladspa` where five of the six plugins were
> #:    evidently copied by hand."

`docs/arch/effects-engine.md:113-117` explicitly declines to resolve this:

> "scsynth must therefore be finding the plugins some other way (a compiled-in default, or an
> env var set by `launch-sc-1`/`las-sc`). **Not resolvable from this harvest** — flagged as an
> open question, not a bug to 'fix'."

And `captures/arch-harvest/table-and-ladspa-listing.txt:4-9` shows all **six** `.so` files in
`/usr/share/las-fx/ladspa`, so the "five of six" framing is about the *fallback* directory and
carries the contamination risk of §1.3. Mark the fallback path `[INFERRED]`.

### 6.7 · P1 · WRONG/STALE — `effect.py:551-555` says the instrument runs at 256

> "The headroom warning was built on a constant measured at the shipped block size of 128, and
> **the instrument now runs at 256**."

Reverted. `docs/CLAIMS-AUDIT.md:19`: "**128 is correct.**" This is the one place in the package
where the running block size is asserted.

### 6.8 · P1 · UNSUPPORTED — three unreconciled idle-load figures, one of them the retracted 72%

| file:line | constant / claim | against |
|---|---|---|
| `effect.py:245-249` | `TYPICAL_PATCH_LOAD = 0.72`, "Measured at 72% on a normal patch; at 82% on a 752-ugen graph; at 12% on an engine with no patch loaded at all" | `CLAIMS-AUDIT.md:20` retires the method; `:46-48` gives 496 ugens / **16.6%** at 128 for a fresh boot. The "12%" is the block-**256** figure. This seeds `fits()`. |
| `effect.py:192-193` | "On an idle engine (12-13% baseline, 519 ugens)" | same — 12-13% is the 256 measurement |
| `fm.py:51` | `BASELINE_CPU = 0.552`, feeding `cpu_estimate()` (`fm.py:170-172`) | a third figure, and the sole source for `docs/PLUGIN.md:162` (§5.7) |

The `CPU_COST` values themselves survive — `CLAIMS-AUDIT.md:30` lists 23-33% under "Still
true". Only the baselines are stale.

### 6.9 · P1 · WRONG — `fm.py:7-11` on scheduler priority

> "scsynth runs `SCHED_FIFO` at priority **-95**, which is why it holds."

Two errors. `docs/ARCHITECTURE.md:100` — `SCHED_FIFO` **99**; the −95 conflates the FIFO
priority with the RT *throttle ratio* (950000/1000000, `system-and-failure-modes.md:817`). And
the throttle is precisely not "why it holds": `system-and-failure-modes.md:811-819` (F-11)
records `sched: RT throttling activated` as a hazard, caused by `S02sys:8` writing the budget
into a file called `/sched_rt_runtime_us`.

### 6.10 · P1 · CONTRADICTED — `effect.py:147-149` repeats the `_1` misreading the arch report exists to correct

> "#: The numbered variants are **per-slot copies** of one definition; `_1` is the instance
> #: this project instantiates."

`docs/arch/effects-engine.md:263-267`: "**Correcting a likely misreading of the `_1`/`_2`
suffix:** it is *not* 'one per slot'. It is the input topology. `n==1` feeds the LADSPA plugin
`input.sum * 0.45`… a mono sum; `n==2` feeds `input[0], input[1]` — true stereo."
`docs/arch/audio-graph.md:120`: "**The `_n` suffix is a channel configuration, not a slot
number**".

Practical consequence: `EFFECTS` pins every effect to `_1`, which for the `et_*` families is
the **mono-sum** variant — the send's stereo input is summed to mono inside the plugin.

### 6.11 · P1 · CONTRADICTED — `fm.py:38-41`'s analog input map

> "#: Input buses carrying the analog voices, pre-effects… 8/9 and 10/11 are stereo pairs, 12
> #: is the loudest single feed, and 13-15 are silent."

`docs/arch/audio-graph.md:301-307`: 8/9 are `sendInput`'s (uninstantiated) default pair; **10
and 11 are two independent mono effect sends**, not a stereo pair, and they are gated
post-timbre sends rather than pre-effects voices; 12/13/14 are timbre 1/2/3 digital dry, with
14 doubling as the vocoders' hard-wired modulator. 13 and 14 read silent because one timbre was
sounding. `ANALOG_IN_DEFAULT = 12` is right.

### 6.12 · P1 · Needs one check — four buffer numbers may be above the server's allocation

`captures/arch-harvest/runtime-state.txt:115` runs `scsynth … -b 1026 …`, and `-b` is the
sample-**buffer count**, so valid indices are 0…1025. Against that:
`sampler.py:37 FIRST_BUFFER = 1100`, `ingress.py:72 RING_BUFFER = 1054`,
`netaudio.py:46 STREAM_BUFFER = 1050` are all out of range; `record.py:28 RECORD_BUFFER = 1000`
is inside it. `init_sc_1.scd` never sets `numBuffers`, so this comes from SC's default and does
not change across restarts.

**This is flagged rather than asserted**, because `docs/MOOG-ONE-INTERNALS.md:1584-1593` records
the ingress ring working on hardware and the git log records the sampler triggering 44 notes —
which the arithmetic says should have failed with `/fail /b_alloc`. Either the flag means
something else on this build, or those measurements used different constants. One `/b_alloc`
on buffer 1100 settles it. The comment at `sampler.py:35-38` ("clear of… buffers the firmware
may be using") reasons about the wrong ceiling either way.

### 6.13 · P2 · `effect.py:11-12` — the free-bus claim is incomplete

> "scsynth runs with `-a 129`; the instrument works in 0-16 and 50-63, so everything from 64 up
> is free."

`IN_BUS = 100` (`effect.py:63`) is `sendInput`'s `par_bus` default (`audio-graph.md:327`), and
200/201 are `output`/`stereoOutput`'s. They are safe only because all four defs are shipped and
never instantiated (`audio-graph.md:847-850`) — which is the thing worth writing down. The
sibling `ingress.py:39-42` states it more precisely and should be the model.

### 6.14 · P2 · `harness.py:140-146` — right choice, wrong reason

> "// SuperCollider zeroes the hardware output buses every block but NOT private ones"

`docs/arch/audio-graph.md:108-110`: "`In.ar` would return **zeros**, because scsynth's `In`
yields silence from a bus not yet touched in the current block **[inferred from scsynth's
`mAudioBusTouched` mechanism]**." `ReplaceOut` is still correct — it prevents same-block
summing from another writer — but the stated reason is not.

**Checked and correct:** `effect.py`'s `MONITOR_GRAPH` note (`:78-90`) matches
`synthdefs.scd:3739/3742/3747` including the forced `mix = 1`; `UNITY_GAIN = 0.85` (`:100-104`)
is the correct solution of `ControlSpec.new(0.01, 2.25, \exp)` mapping to 1.0; the
`stop_effect` doneAction table (`:318-320`) matches `DANGER.md:176-178`; every control name in
`PRESETS` exists on the effect it is sent to; `THROTTLE_CEILING` (`:240-242`) matches
`system-and-failure-modes.md:817`; and `load.py`'s busybox-`top` and dead-`/status.reply`
claims are both under "Still true" in `CLAIMS-AUDIT.md:27-29`.

---

# 7. `ROADMAP.md`

Not on the original list, but it carries the retracted claims in their most actionable form —
as work items someone is meant to pick up.

| line | quote | tag |
|---|---|---|
| 226-231 | "The i.MX6 has two cores and **nothing in the shipped configuration uses the second one for audio**, while one Eventide reverb takes an ordinary patch from 72% to 101% of the first.… Hard, and the honest prize: **roughly double the DSP budget**." | **WRONG.** `CLAIMS-AUDIT.md:12-14`. And "101%" is the impossible figure `MoogOneFixes/BUGS.md:162-167` retracts. Item 8 should be deleted or rewritten as "tidy four defects in `init_sc_2.scd`", with no performance claim. |
| 210-215 | "`et_spring` has SynthDef source calling `LADSPA.ar(2, 29153, ...)`, **was never compiled** to a `.scsyndef`" | WRONG — commented out at `synthdefs.scd:3629-3700`. Also STALE: item 7's goal was reached and then reverted (`INTERNALS:2139-2140`), so the item needs re-scoping or closing. |
| 233-237 | "### 9. `/hw/cvout/0` — a CV output nothing exposes… **Unverified**" | STALE. Answered: `INTERNALS:2415-2450` ("**It returns `404 Not found`.**") and `CLAIMS-AUDIT.md:37`. Close it. |

---

# 8. `docs/CLAIMS-AUDIT.md` — is the audit itself complete and correct?

Mostly yes. Four gaps.

### 8.1 · P1 · The `et_spring` row contradicts the correction it is supposed to embody

`docs/CLAIMS-AUDIT.md:32`, under **Still true**:

> "| `et_spring` passes the plate's argument list into plugin 29153 | Ten ports either way, so
> it maps positionally and **compiles silently**, and every knob is the wrong knob. |"

It does not compile at all — that is correction 4, and `docs/arch/audio-graph.md:377-380` is
the citation. Two further details from `audio-graph.md:390-394` are missing: `et_spring` also
lacks `pan` and `gain` (20 args vs 22), so its ordinals are offset by one against every other
reverb.

**Suggested correction:** "…maps positionally in LADSPA port order, but the SynthDef is inside
a `/* */` block (`synthdefs.scd` L3629–L3700) so it never compiles, and it is missing `pan`
and `gain`, which offsets its control ordinals against every other reverb."

### 8.2 · P1 · The block-size retraction does not say where it still needs applying

`CLAIMS-AUDIT.md:19-20` retracts both the recommendation and the magnitude, correctly. It does
not record that the retraction has **not** been applied to `docs/ARCHITECTURE.md:122`,
`docs/MOOG-ONE-INTERNALS.md:1597-1621`, `MoogOneFixes/BUGS.md:169-180` or `ROADMAP.md:228`.
A one-line "applied in / outstanding in" column would make the next pass cheap.

### 8.3 · P1 · Two authoritative contradictions are not in the audit at all

Neither §0.1 (the arch documents reading our own `-z 256` edit as stock) nor §0.2 (`/cal`
read-vs-write) appears. §0.2 is listed in the brief as correction 5, so it is known; it has
simply never been written down where a reader of the arch reports would meet it.

### 8.4 · P2 · One row is now ambiguous

`CLAIMS-AUDIT.md:34`, under **Still true**: "| 375 Hz is the block rate | 48000/128 = 375
exactly, and it moved to 187.5 at `-z 256`. |" This is right for the restored instrument but
reads oddly next to three arch documents insisting the machine runs at 256. Fixing §0.1
resolves it.

---

# 9. Verification commands used

All read-only, all local. No instrument was contacted.

```sh
cd captures/arch-harvest
grep -n "blockSize\|hardwareBufferSize" init_sc_1.scd     # -> 128 at L9-10   (§0.1)
grep -n "scsynth -u" runtime-state.txt                    # -> -z 256 at L115 (§0.1)
sed -n '3625,3635p;3696,3702p' synthdefs.scd              # -> /* 3629, */ 3700 (§1.3, §2.6)
sed -n '562,575p' synthdefs.scd                           # -> Out.ar(7, main[0] * -1) (§2.1)
grep -n "eventide" table-and-ladspa-listing.txt           # -> six .so files (§0.4)
grep -n "doneAction: 1" synthdefs.scd                     # -> 6 sites; 3657 is the spring (§6.1)
grep -n "Env.asr(0.1, 1, 2)" synthdefs.scd                # -> only 619 and 3657 (§1.9, §6.2)
sed -n '375,378p' synthdefs.scd                           # -> inputRouter doneAction: 2 (§6.1)

cd ../..                                                  # repo root
git log --oneline -S'affinity=2  last-cpu=1  ppid=1' -- usb/README.md   # -> f35da58, 93f8409 (§5.6)
git show 93f8409:usb/README.md | grep 'running: 1703'                   # -> the original capture
```

## Suggested order of work

1. **§0.1** first — three arch documents and `ARCHITECTURE.md` are the citation targets for
   everything else, and the block-size correction touches most of them.
2. **§1** next, and hold the report until §1.1-§1.4 are resolved. Two of those four
   (§1.1, §1.2) tell the manufacturer something demonstrably false about their own product,
   and §1.4 would ship them a patch that reproduces the bug it fixes.
3. **§0.2** — decide the `/cal` question one way and make both teardowns say the same thing,
   because it governs every probe anyone sends the instrument from here on.
4. **§2.1 / §5.5 / §6.3** together — the main-output L/R error is one fact in five files.
5. **§6.2 / §1.9 / §2.12** together — one wrong envelope quote in three files, one grep.
6. The rest by priority tag.
