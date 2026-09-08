# Moog One — scsynth audio DSP graph

Reverse-engineered from the instrument's own SuperCollider sources.

**Primary source:** `captures/arch-harvest/synthdefs.scd` (3875 lines, read in full).
**Corroborating local files:** `captures/arch-harvest/synthdef-names.txt` (104 compiled defs on
device), `captures/arch-harvest/efx_server.scd` (the OSC state machine that instantiates and
patches these synths), `captures/arch-harvest/init_sc_1.scd` (boot/node-order),
`captures/arch-harvest/runtime-state.txt` (live `scsynth` command line),
`captures/arch-harvest/init.d/S42sc`, `captures/arch-harvest/table-and-ladspa-listing.txt`.

No instrument was contacted. Everything below is derived from files on disk.

Line numbers cited as `Lnnn` refer to `synthdefs.scd` unless another file is named.

Statements are labelled **[read]** where taken directly from source and **[inferred]** where
I am reasoning about SuperCollider/scsynth semantics or about data that arrives over OSC at
runtime and is therefore not present in the file.

---

## 0. Executive summary of what matters

| # | Finding | Severity |
|---|---|---|
| 1 | `stereoDelay_*` and `pingpongDelay_*` have an **unbounded feedback loop with a hard ×2 in the return path** and no saturator inside the loop. Loop gain > 1 for feedback > 0.5. | Can produce NaN on the DAC |
| 2 | `dry_dir4 = 1` (bare DC constant) is summed into all four aux outs, and its routing row `dry_dir4_r` **is driven at runtime** by bus-effect slot 4's `/fx3/out` message. Not dead. | Full-scale DC on an aux out |
| 3 | `outputRouter` reads the "analog dry" timbre inputs with `In.ar(synth1_in_ch)` whose **defaults 4/5/6 are hardware *output* buses**, not inputs. Only correct after the front end sends `/fx{n}/in`. | Silent dry / wrong source at boot |
| 4 | Aux sums double the insert contribution (mono scalar + stereo array, then `.sum`). Inserts are **+6 dB into aux vs. main/sub**. | Level error |
| 5 | `et_spring` is **entirely inside a `/* */` block** (L3629–L3700), never compiled, absent from the device. `eventide_spring.so` is unreachable. Its arg list is `et_plate`'s; its metadata is a spring's. | Dead feature |
| 6 | `et_shimmer_*` has `highDecay`/`lowDecay` **swapped** between the arg list and the metadata the UI reads. | Mislabelled controls |
| 7 | Every `et_*` steps `preDelay`, `size`, `decay` through `env.floor` — a **0→full step discontinuity** at both ends of the fade. | Reverb clicks |
| 8 | The `rates:` lag arrays are stale in 24 of 33 defs; controls past the array end get **no lag at all** and step. | Zipper noise |
| 9 | Main L/R are phase-inverted (`* -1`); sub and aux are **not**. | Cancellation if summed |
| 10 | `chorus_*` / `stereoChorus_*` pass feedback into `XFade2`'s **`level`** slot instead of its **`pan`** slot. Feedback is zero at knob centre and inverts below it. | Broken control |

---

## 1. Server configuration — verified and corrected

`synthdefs.scd` L11–L20 sets `blockSize = 128`, `hardwareBufferSize = 128`, `sampleRate = 48000`,
but only on the fallback `Server.local` path; the real configuration comes from
`init_sc_1.scd`.

`init_sc_1.scd` **[read]**:

```
blockSize            = 128
hardwareBufferSize   = 128
numOutputBusChannels = 8
numInputBusChannels  = 9
numWireBufs          = 128
memSize              = 100000
latency              = 0.05
sampleRate           = 48000
```

The **live process** (`runtime-state.txt`, PID 1294) **[read]**:

```
scsynth -u 57110 -a 129 -i 9 -b 1026 -z 256 -Z 256 -m 100000 -w 128 -S 48000 -R 0 -C 0 -l 1
```

Corrections to the previously established facts:

* **Block size is 256, not 128.** `-z 256 -Z 256`. `init_sc_1.scd` asks for 128; the running
  server has 256. Either the harvested `init_sc_1.scd` post-dates the running process, or
  something else booted `scsynth`. 256 frames @ 48 kHz = **5.333 ms** per control period. This
  is the granularity of every `InFeedback`, `FbNode` and `LocalIn` loop in the file, and it is
  the quantum you would change if you touched `blockSize`. **Do not change it** — several
  feedback delays are tuned around it.
* **Audio bus count is 129**, not the SC default 1024. `-a 129` = 112 private + 9 in + 8 out
  **[inferred from `ServerOptions.asOptionsString`, which emits `numPrivateAudioBusChannels +
  numInputBusChannels + numOutputBusChannels`; 112 is the SC default private count]**.
  Consequence: **valid audio bus indices are 0…128.** Anything ≥129 is silently discarded by
  `Out` **[inferred: scsynth's `Out` bounds-checks against `mNumAudioBusChannels` and skips the
  write]**. This matters for `par_bus = 200` (see §3).
* Output count is the SC default 8 (no `-o` flag). Confirmed by `efx_server.scd` L508/L817,
  which converts a front-panel hardware channel number to a bus index with `+ 8`.

**Bus layout that follows from `-o 8 -i 9 -a 129`:**

```
bus   0 …   7   hardware OUTPUT  (8)
bus   8 …  16   hardware INPUT   (9)   SoundIn.ar(n) == In.ar(8 + n)
bus  17 … 128   private          (112)
```

### Node order

From `init_sc_1.scd` and `efx_server.scd` L246–L270 **[read]**:

```
~insertGroup   ── efxGroups[0]  insert slot 1 effect
               ── efxGroups[1]  insert slot 2 effect
               ── efxGroups[2]  insert slot 3 effect
~busGroup      ── inputRouter            (addToHead)
               ── efxGroups[3]  bus/master effect 1
               ── efxGroups[4]  bus/master effect 2
               ── outputRouter           (addToTail, re-moved to tail on every effect swap)
~eventideGroup ── parking lot for the 10 idle et_* synths (run(false))
```

The five `et_*` synths are created **once** at boot and permanently `run(false)`. When the
front panel selects a reverb, `efx_server.scd` L392 `moveToTail(~efxGroups[unitNum])` pulls the
pre-made synth *into* `~busGroup` (ahead of `outputRouter`) and `run(true)`s it. That ordering
is load-bearing: if a reverb synth were left in `~eventideGroup` (after `outputRouter`), its
output on buses 60–63 would be read a block late — in practice `In.ar` would return **zeros**,
because scsynth's `In` yields silence from a bus not yet touched in the current block
**[inferred from scsynth's `mAudioBusTouched` mechanism]**. The `~dspOutputWrapper.moveToTail`
at L269 exists to preserve exactly this.

---

## 2. SynthDef catalogue

33 `SynthDef` sites in the file. 19 effect families are built inside `(0..3).do{|n| … }` loops
(4 channel-configuration variants each), 5 Eventide families inside `(1..2).do{|n| … }`.

**The `_n` suffix is a channel configuration, not a slot number** (L670–673 and equivalents):

| n | Input | Internal | Output |
|---|---|---|---|
| 0 | `In.ar(inBus,1)` mono, extra ×0.4–0.5 trim | mono | panned to stereo |
| 1 | `In.ar(inBus,2).sum` stereo folded to mono | mono | panned to stereo |
| 2 | `In.ar(inBus,2)` true stereo | stereo | stereo, no pan |
| 3 | `In.ar(inBus,1)` mono, no extra trim | mono | panned to stereo |

For the `et_*` families, `_1` sums the input to mono (`input.sum * 0.45` or `* 0.5`) and `_2`
keeps it stereo — i.e. `_1` is the dual-mono master-bus instance and `_2` the stereo one.

### 2a. Routers and I/O utilities

| Def | L | Reads | Writes | Notes |
|---|---|---|---|---|
| `none_0…3` | 33 | — | — | **No `Out` at all** (L51 commented). Pure no-op holder. `EnvGen … doneAction:2` so `enable=0` frees it. This is the "bypass" effect and the default in all 5 slots. |
| `default` | 67 | — | — | Identical to `none_*`. |
| `sendInput` | 103 | `SoundIn.ar(inBus,2)` (default hw 0,1 → bus 8,9); `In.ar(par_bus,1)` (default **100**) | `Out.ar([outBus, outBus+1])`, default **0 and 1** | Not instantiated by `init_sc_1.scd`. Bus 100 is never written by anything → reads zeros. Default `outBus=0` would dump into main-R and sub-R. |
| `input` | 143 | `AudioIn.ar(inBus, volume*g_in)` | `Out.ar(outBus)` default `[0,1]` | `AudioIn` is SC's deprecated **1-based** input pseudo-UGen **[inferred]**: `AudioIn.ar([0,1])` resolves to `In.ar([7,8])` — bus 7 is main-L *output*. Not instantiated. |
| `output` | 177 | `In.ar([inBus])` (mono, default bus 1) | `Out.ar(outBus)`=`[0,4]`; `Out.ar(sendOneBus)`; `Out.ar(sendTwoBus)`; `Out.ar([par_bus, par_bus+1])`=200,201 | `sendOneBus`/`sendTwoBus` are declared with **no default → 0**, i.e. main-R. `par_bus=200` is out of range (§1). Not instantiated. |
| `inputRouter` | 224 | `SoundIn.ar(2)`→bus 10, `SoundIn.ar(3)`→bus 11, `In.ar([50,51])`, `In.ar([52,53])`, `In.ar([54,55])`, `InFeedback.ar(60)`, `InFeedback.ar(61)` | `Out.ar(56)`, `(57)`, `(58)`, `(59)` | The send/insert → master matrix. |
| `outputRouter` | 401 | `In.ar([50,51])`, `[52,53]`, `[54,55]`, `[60,61]`, `[62,63]`, `In.ar(synth1/2/3_in_ch)` | `Out.ar(7,0,2,1,5,6,3,4)` | The summing matrix and the only thing that touches the DAC. |
| `stereoOutput` | 596 | `In.ar([inBus, inBus+1])` | `Out.ar([0,4])`; `Out.ar([par_bus, par_bus+1])`=200,201 | Compiled and on device but **not instantiated**. Hard-codes `[0,4]` (main-R + aux4) — the `outBus` arg is ignored (L622 commented). |

**`inputRouter` full argument list** (L225–L262) **[read]**:

```
enable       = 1
send1_r      = #[1, 1, 0, 0]     // → [master1L, master1R, master2L, master2R]
send2_r      = #[0, 0, 1, 1]
insert1_r    = #[1, 1, 0, 0]
insert2_r    = #[0, 0, 0, 0]
insert3_r    = #[0, 0, 0, 0]
par_amount   = 0
balance      = 0                 // DEAD — never referenced in the body
mode         = 0                 // DEAD — never referenced in the body (set by /fx/bus-mode!)
send1Gain    = 1
send2Gain    = 1
send1Thresh  = 0.0001
send2Thresh  = 0.0001
clampTime    = 0.01
relaxTime    = 4.0
gainFactorMin= 0.1
```

`mode` is set on every `/fx/bus-mode` message (`efx_server.scd` L133) and does nothing; the
handler's *side effect* of rewriting `send1_r`/`send2_r` is what actually switches dual-mono
(`[1,1,0,0] / [0,0,1,1]`) versus stereo (`[0,0,1,0] / [0,0,0,1]`).

The send gate (L276–L291): `DetectSilence.ar` inverted into a 0/1 state, `Lag.ar` with
`Select.kr(state, [relaxTime, clampTime])` — 10 ms attack, **4 s release**, floored at
`gainFactorMin = 0.1` (−20 dB, never fully muted). Note `Select.kr` is being fed an
audio-rate index; scsynth reads the first sample of the block **[inferred]**.

**`outputRouter` full argument list** (L402–L444) **[read]**:

```
enable            = 1
inBus             = 1            // DEAD
outBus            = #[0,4]       // DEAD
ctlIn/ctlOut      = [0,0]        // DEAD
sendOneBus/sendTwoBus            // DEAD (no default → 0)
ctl = 0.5, mix = 0.5             // DEAD
insert1_r  = #[0,0,1,0,0,0]      // columns: [main, sub, aux1, aux2, aux3, aux4]
insert2_r  = #[0,0,0,1,0,0]
insert3_r  = #[0,0,0,0,1,0]
master1_r  = #[1,1,0,0,0,0]      // only [0] is used; [1..5] DEAD (L513-514, 520-521, 530-531, 540-541, 550-551 commented)
master2_r  = #[1,1,0,0,0,0]      // same
dry_dir1_r = #[1,0,0,0]          // columns: [aux1, aux2, aux3, aux4]
dry_dir2_r = #[0,1,0,0]
dry_dir3_r = #[0,0,1,0]
dry_dir4_r = #[0,0,0,0]          // *** driven at runtime by /fx3/out — see §6.2
timbre_1_dry / _2_ / _3_ = 0
timbre_1_dry_main / _2_ / _3_ = 0   // ALL THREE DEAD (only in commented lines 495-497, 507-509)
insert_1_g / _2_g / _3_g = 1
dry_1_p / _2_p / _3_p    = 0     // Pan2 positions for the digital dry
synth1_in_ch = 4                 // *** wrong defaults — see §6.3
synth2_in_ch = 5
synth3_in_ch = 6
digDryGain   = 0.9               // 1.9 on old hardware (efx_server.scd L157)
stereoSpread = 0.5
```

`master1_r` and `master2_r` are **never set by `efx_server.scd`** (grep confirms no writer), so
they permanently hold `#[1,1,0,0,0,0]` and only index `[0]` is read. **The bus/master effects
reach the main outputs only.** They cannot be routed to sub or to any aux.

### 2b. Insert effects (delay / modulation / filter family)

All share the generic prefix `enable, inBus, outBus, ctlIn, ctlOut, ctl, g_in, g_out, wet, dry,
pan, mix` then family-specific parameters then `gain`. `wet` and `dry` are declared in every
single def and **used in none of them**. `ctl`, `ctlIn`, `ctlOut` likewise. Input is always
`In.ar(inBus, …)` where `inBus` arrives over OSC as `hardware_channel + 8`
(`efx_server.scd` L508, L817) **[read]**; output is always `Out.ar(outBus, …)` where `outBus`
arrives over OSC — 50/52/54 for the three insert slots **[inferred from the fact that
`inputRouter` and `outputRouter` read exactly those buses]**.

| Def | L | Family params (defaults) | Internal feedback | Output limiting |
|---|---|---|---|---|
| `delay_*` | 643 | `feedback=0, time=0, gain=1` | `FbNode`, 24 s `DelayC` | **none** |
| `stereoDelay_*` | 726 | `timeL=0, timeR=0, feedbackL=0, feedbackR=0, modRateL=0, modRateR=0.2, modDepthL=0.1, modDepthR=0.2, tone=0.1, gain=1` | 2× `FbNode`, **`sigL*2` written back** | **none** |
| `pingpongDelay_*` | 856 | `feedback=0, timeL=0, timeR=0, offset=0, tone=0.1, gain=1` | 2× `FbNode`, cross-coupled, **`sigR*2` / `sigL*2` written back** | `.tanh` on output only |
| `bbdDelay_*` | 975 | `feedback=0, time=0, noise=0, tone=0.1, modulation=0, gain=1` | `FbNode`, `.tanh` + `.clip(-1,1).softclip` in loop | bounded in-loop |
| `tapeDelay_*` | 1125 | `feedback=0, time=0, flutter=0.1, wow=0.2, bias=0.1, gain=1` | `LocalIn/LocalOut`, `.atan` in loop (±1.5708) | bounded to ±1.57, then ×`g_out`×(0…4) |
| `flanger_*` | 1279 | `feedback=0.1, time=0.0001, rate=0.01, depth=1.0, tone=0.1, noiseGain=1, gain=1` | inside `Flanger` UGen (opaque) | none |
| `stereoFlanger_*` | 1391 | `feedbackLeft/Right=0.1, timeLeft=0.0001, timeRight=0.0002, rateLeft=0.01, rateRight=0.1, depth=1.0, phaseOffset=0.5, tone=0.5, gain=1` | inside `Flanger` UGen | none |
| `chorus_*` | 1508 | `feedback=0.1, time=0.0001, rate=0.01, depth=1.0, tone=0.5, gain=1` | `LocalIn/LocalOut`, gain ≤ 0.42 | none (stable) |
| `dualChorus_*` | 1629 | `feedback=0.5, time=0.5, rate=0.1, depth=0.1, tone=0.5, vibratoRate=0.1, vibratoDepth=0.1, gain=1` | inside `DualChorus` UGen | none |
| `ensemble_*` | 1722 | same as `dualChorus_*` | 3× `FbNode`, tap gains 0.6/0.7/0.8 × `map(-1..1)`, tap 2 inverted | `LeakDC`, no clip |
| `stereoChorus_*` | 1930 | same as `stereoFlanger_*` | 2× `FbNode`, gain ≤ 0.707 | none (stable) |
| `timePhaser_*` | 2072 | `feedback=0, sweep=0, rate=0, depth=0, tone=0, regen=0, time=0, gain=1` | `FbNode`, `.tanh` in loop, **`regen` maps 0…1 → 0…2** | `.softclip` |
| `phaser6stage_*` | 2206 | `feedback=0.99, sweep=0.3, rate=0.1, depth=0.5, tone=1, noiseGain=1, gain=1` | inside `Phaser6Stage` UGen | `.softclip` |
| `phaser12stage_*` | 2307 | `feedback=0.99, sweep=0.5, rate=0.1, depth=0.5, tone=1, noiseGain=1, gain=1` | none (feed-forward), but `BBandPass … mul: 25` ×3 + `HPF … mul: 5` | `.softclip` |
| `bitcrusher_*` | 2506 | `bitDepth=1, sampleRate=0.5, gain=1` | none | **none**, and a hard-coded `g_comp = 5` |
| `resonator_*` | 2608 | `resonance=0.1, cutoff1=1, cutoff2=0.5, cutoff3=0.25, levelLow/Mid/High=1, filterType=1, rate=0, depth=0.5, gain=1`; `mix` defaults to **1** here | none | `.tanh` |
| `vocoder16_*` | 2752 | `sib=0.65, sensitivity=0.1, tone=0.5, noiseGain=0.5` | none | **none**; band envelopes have `mul: 1000` |
| `vocoder21_*` | 2970 | same | none | **none** |
| `vocoder10_*` | 3201 | same | none | **none** |

Custom scsynth UGens referenced (not defined in this file, supplied by the LAS plugin build):
`Flanger`, `DualChorus`, `Phaser6Stage`, `StereoSpread`, `Decimator`, `FbNode` (a sclang-side
feedback pseudo-UGen from the Feedback quark), `LADSPA`.

`FbNode`/`LocalIn` loops all incur exactly one control period of latency
(**5.333 ms at the live `-z 256`**) **[inferred]**.

Vocoder band tables (all three read their modulator from `SoundIn.ar(6)`, i.e. bus 14):

* `vocoder16` (L2818–L2846): 70, 180, 226, 285, 359, 452, 570, 718, 904, 1139, 1435, 1808,
  2278, 2870, 3616, 4556 Hz. A 16-band "Moog" table is present but **commented out** (L2820–L2831).
* `vocoder21` (bark): 60, 150, 250, 350, 450, 570, 700, 840, 1000, 1170, 1370, 1600, 1850,
  2150, 2500, 2900, 3400, 4000, 4800, 5800, 7000 Hz. Its `n_bands` local still says `16` (stale).
* `vocoder10` (vp33): **250, 200,** 280, 400, 700, 900, 1300, 2000, 2800, 4000 Hz — bands 1 and 2
  are non-monotonic. Matches `~vp33_freqs` at L2712, so it is at least consistent, but it looks
  like a transposition.

`~vocoder_params` (L2708–L2721) is an `Environment` of band tables that **nothing ever reads** —
each vocoder inlines its own copy. Dead code.

### 2c. Bus / master effects

There is no separate class of synthdef for these. The same 19 effect families are used; the
distinction is made entirely by `efx_server.scd` at instantiation time: slots 0–2 go into
`~insertGroup` and slots 3–4 into `~busGroup`, and for slots 3–4 the `inBus` is taken as
`[msg[3], msg[3]+1]` **without** the `+8` hardware offset (`efx_server.scd` L508 vs L511)
**[read]** — i.e. a bus/master effect reads a *private* bus pair (56/57 or 58/59) while an
insert reads a *hardware input*.

### 2d. Eventide LADSPA wrappers

See §4.

---

## 3. Complete bus map

`W` = written, `R` = read. Line numbers in `synthdefs.scd`.

### Hardware output buses 0–7

| Bus | Role | Written by | Read by |
|---|---|---|---|
| 0 | **main R** (inverted) | `outputRouter` L565 `main[1] * -1`; also `stereoOutput` L623 `Out.ar([0,4])`, `output` L205/L206/L207 (defaults), `sendInput` L127 (default `outBus=0`) | nothing in `synthdefs.scd` |
| 1 | **sub R** | `outputRouter` L567 | `sendInput` L127 writes `outBus+1` = 1 at default |
| 2 | **sub L** | `outputRouter` L566 | — |
| 3 | **aux3** | `outputRouter` L570 | — |
| 4 | **aux4** | `outputRouter` L571; `output` L205, `stereoOutput` L623 | `outputRouter` L473 `In.ar(synth1_in_ch)` **at the default `synth1_in_ch = 4`** |
| 5 | **aux1** | `outputRouter` L568 | `outputRouter` L474 at default `synth2_in_ch = 5` |
| 6 | **aux2** | `outputRouter` L569 | `outputRouter` L475 at default `synth3_in_ch = 6` |
| 7 | **main L** (inverted) | `outputRouter` L564 `main[0] * -1` | `input`/`default` via `AudioIn.ar(0)` → `In.ar(7)` **[inferred]** |

Phase: **main L and main R are both `* -1`**; sub and all four aux are **not** inverted.
The pair-internal polarity of main is therefore correct, but main is 180° out of phase with
sub and aux. The commented-out "usb" alternative at L574–L581 shows a different, non-inverted
channel order — evidence the inversion and the odd 7/0/2/1/5/6/3/4 order are ESAI/codec-specific.

### Hardware input buses 8–16 (`SoundIn.ar(n)` → bus `8+n`)

| Bus | HW ch | Used as | Where |
|---|---|---|---|
| 8, 9 | 0, 1 | `sendInput` default input pair | L120 (synth not instantiated) |
| 10 | 2 | **effect send 1** | `inputRouter` L276 `SoundIn.ar(2)` |
| 11 | 3 | **effect send 2** | `inputRouter` L288 `SoundIn.ar(3)` |
| 12 | 4 | timbre-1 digital dry / insert-slot source | via runtime `inBus` and `synth1_in_ch` **[inferred]** |
| 13 | 5 | timbre-2 digital dry / insert-slot source | as above |
| 14 | 6 | timbre-3 digital dry **and the hard-wired vocoder modulator** | L2914, L3144, L3319 `SoundIn.ar(6, 1)` **[read]** |
| 15, 16 | 7, 8 | not referenced anywhere in `synthdefs.scd` | — |

All three vocoders take their **carrier** from `inBus` (whatever timbre is patched into the
slot) and their **modulator** unconditionally from hardware channel 6. If the established
mapping "ch4/5/6 = timbre 1/2/3 digital dry" is right, the vocoder is always modulated by
**timbre 3**, regardless of which slot it sits in and regardless of which timbre feeds it.
That is either a deliberate design decision or a hard-coded leftover; nothing in these files
makes it configurable.

### Private buses

| Bus pair | Role | Written by | Read by |
|---|---|---|---|
| 50, 51 | insert slot 1 return | insert-slot-0 effect via runtime `outBus` **[inferred]** | `inputRouter` L294, `outputRouter` L460 |
| 52, 53 | insert slot 2 return | insert-slot-1 effect **[inferred]** | `inputRouter` L295, `outputRouter` L461 |
| 54, 55 | insert slot 3 return | insert-slot-2 effect **[inferred]** | `inputRouter` L296, `outputRouter` L463 |
| 56, 57 | inputRouter → master 1 | `inputRouter` L380, L381 | bus-effect slot 3 via runtime `inBus` **[inferred]** |
| 58, 59 | inputRouter → master 2 | `inputRouter` L384, L385 | bus-effect slot 4 **[inferred]** |
| 60, 61 | master 1 return | bus-effect slot 3 via runtime `outBus` **[inferred]** | `outputRouter` L464 (`In.ar`), `inputRouter` L362, L371 (**`InFeedback.ar`**) |
| 62, 63 | master 2 return | bus-effect slot 4 **[inferred]** | `outputRouter` L465 |
| 100, 101 | `sendInput` `par_bus` default | **nothing** | `sendInput` L121 `In.ar(par_bus, 1)` — bus 100 only |
| 200, 201 | `output` / `stereoOutput` `par_bus` default | `output` L208, `stereoOutput` L624 | **nothing** |
| 17–49, 64–128 | unallocated private buses (95 of the 112 available) | — | — |

### Anomalies in the bus map

1. **Bus 100 is read but never written.** `sendInput` L121 adds `In.ar(100,1) * par_amount`
   into its input. Harmless only because `par_amount` defaults to 0 *and* `sendInput` is never
   instantiated. Dead read.
2. **Buses 200/201 are written but do not exist.** With `-a 129` the valid range is 0…128.
   `Out.ar(200, …)` is silently dropped by scsynth **[inferred]**. Both `output` and
   `stereoOutput` use `par_bus = 200`, while `sendInput` — the only synth that *reads* a
   `par_bus` — defaults to **100**. The parallel-send mechanism in these three defs is wired to
   two different non-existent rendezvous points and can never have worked. It is superseded by
   the `InFeedback` path in `inputRouter`.
3. **Output buses 4, 5, 6 are read by `outputRouter` at its own default settings.** See §6.3.
4. Buses 62/63 are read by `outputRouter` but `master2_r[1..5]` are dead, so master 2 can only
   reach the main outs.

---

## 4. The Eventide LADSPA wrappers

Five plugin `.so` files ship on the device (`table-and-ladspa-listing.txt`): `eventide_blackhole.so`,
`eventide_hall.so`, `eventide_plate.so`, `eventide_room.so`, `eventide_shimmer.so`,
`eventide_spring.so`.

### Plugin IDs and port order

Every wrapper calls `LADSPA.ar(2, <id>, c0, c1, c2, c3, c4, c5, c6, c7, c8, mix, inL, inR)` —
**10 control ports followed by 2 audio input ports**, 2 audio outputs. The arity is identical
across all six.

| Def | L | LADSPA ID | c0 | c1 | c2 | c3 | c4 | c5 | c6 | c7 | c8 | c9 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `et_blackhole_1/2` | 3417/3419 | **29150** | `modDepth` | `modRate` | `feedback * env` | `res * env` | `highLvl` | `lowLvl` | `preDelay * env.floor` | `size * env.floor` | `invGravity * env.floor` | `mix` (forced 1) |
| `et_hall_1/2` | 3584/3586 | **29151** | `lowDecay * env` | `highDecay` | `modLvl` | `midLvl` | `highLvl` | `lowLvl` | `preDelay * env.floor` | `size * env.floor` | `decay * env.floor` | `mix` (forced 1) |
| `et_room_1/2` | 3501/3503 | **29152** | `reflection` | `diffusion` | `modLvl` | `highFreq` | `highLvl` | `lowLvl` | `preDelay * env.floor` | `size * env.floor` | `decay * env.floor` | `mix` (forced 1) |
| `et_spring` | 3662 | **29153** | `distance` | `diffusion` | `modLvl` | `tone` | `highDamp` | `lowDamp` | `preDelay` | `size` | `decay` | `mix` (forced 1) |
| `et_plate_1/2` | 3742/3744 | **29154** | `distance` | `diffusion` | `modLvl` | `tone` | `highDamp` | `lowDamp` | `preDelay * env.floor` | `size * env.floor` | `decay * env.floor` | `mix` (forced 1) |
| `et_shimmer_1/2` | 3827/3829 | **29155** | `aPitch` | `bPitch` | `pitchDecay` | `midDecay` | `highDecay` | `lowDecay` | `delay * env.floor` | `size * env` | `decay * env.floor` | `mix` (forced 1) |

Audio inputs: `_1` variants pass `input.sum * 0.45` (blackhole, plate, shimmer) or
`input.sum * 0.5` (room, hall) into **both** plugin inputs — a mono-summed feed with a −7 dB /
−6 dB trim. `_2` variants pass `input[0]`, `input[1]` at unity.

### `et_spring` — confirmed, and worse than reported

**Confirmed and escalated.** Two problems, not one:

1. **The whole SynthDef is commented out.** `/*` at **L3629**, `*/` at **L3700**. `et_spring`
   is never compiled, never stored, and is correspondingly **absent from
   `synthdef-names.txt`** — the device has all ten `et_*_1/_2` synths and no spring at all.
   `eventide_spring.so` is present on the filesystem and unreachable from SuperCollider.
2. **Its argument list is a verbatim copy of `et_plate`'s** — `distance, diffusion, modLvl,
   tone, highDamp, lowDamp, preDelay, size, decay` — while its `metadata.description` array
   (L3679–L3692) describes a completely different control set: *Trem Intensity, Trem Rate, Mod
   Level, Resonance, High Damp, Low Damp, Num Springs, Tension, Decay*. Nine of nine parameter
   labels disagree with the nine arg names. Since the front end addresses parameters
   **positionally** (`efx_server.scd` L526–L530 derives `psize` from `controlNames.size` and
   indexes into it), the wire order would still "work"; the labels and ranges shown on the
   panel would be wrong, and — because the description array is what documents what each port
   *is* — nobody could tell which port did what.
3. Additional divergence nobody has flagged: `et_spring` is **missing the `pan` and `gain`
   arguments** that all five compiled `et_*` defs carry (20 args vs 22). Its control-name
   ordinals are therefore offset by one relative to every other reverb, so the positional
   parameter indexing in `efx_server.scd` would land on the wrong ports if it were ever
   uncommented as-is.
4. It is also the only `et_*` that does not apply `env.floor` to `preDelay`/`size`/`decay`, and
   the only one without the `softclip` output stage.

### Other `et_*` mismatches — one found

**`et_shimmer_*` has `highDecay` and `lowDecay` swapped between the code and the metadata.**

* Argument list (L3796–L3804): `aPitch, bPitch, pitchDecay, midDecay, **highDecay, lowDecay**,
  delay, size, decay`
* `metadata.specs` (L3844–L3853): `aPitch, bPitch, pitchDecay, midDecay, **lowDecay, highDecay**,
  delay, size, decay`
* `metadata.description` (L3859–L3869): Mix, A Pitch, B Pitch, Pitch Decay, **Mid Decay, Low
  Decay, High Decay**, Delay, Size, Decay

Both the spec dictionary *and* the ordered description array place Low before High; the actual
LADSPA port order is High (c4) then Low (c5). The Shimmer's "Low Decay" and "High Decay"
front-panel controls are therefore driving each other's ports **[inferred — this depends on the
front end using description ordinals, which `efx_server.scd` L964–L990 suggests it does]**.

`et_blackhole`, `et_room`, `et_hall` and `et_plate` were each checked argument-by-argument
against their `specs` and `description` arrays: **all four are internally consistent.**

### Other `et_*` observations

* `mix` is reassigned to the literal `1` immediately before every `LADSPA.ar` call (L3415,
  L3499, L3582, L3661, L3740, L3825). **The `mix` control exists, appears in `controlNames`,
  consumes a parameter slot, and does nothing.** Setting it from the panel has no effect.
* `doneAction: 1` (pause), not 2. Setting `enable = 0` on a reverb **pauses the node**; it
  cannot restart itself, because a paused node does not run its `EnvGen`. Only an explicit
  `/n_run 1` revives it — which is exactly what `efx_server.scd` L380/L620 does. If that path
  is ever bypassed, the reverb is permanently silent with no error.
* `env.floor` on `preDelay`/`size`/`decay` produces a **step**: 0 for the whole 0.1 s attack,
  then a jump to full value the instant the envelope reaches 1.0, and a jump back to 0 the
  instant release begins. For a reverb, an instantaneous change of `size` means an
  instantaneous change of delay-line length — a click, and possibly a buffer-pointer jump
  inside the plugin.
* `LADSPA_PATH` is set with `("export LADSPA_PATH=…").systemCmd` (`init_sc_1.scd`). `systemCmd`
  runs a subshell; **an `export` in a subshell cannot alter the sclang or scsynth environment**.
  Whatever makes the plugins load, it is not that line.

---

## 5. Signal flow, ADC to DAC

```
 ┌──────────────────────────── ADC — 9 hardware inputs (buses 8..16) ─────────────────────────┐
 │  hw0  hw1   hw2          hw3          hw4        hw5        hw6            hw7  hw8        │
 │   │    │   send 1       send 2      timbre1     timbre2    timbre3          -    -         │
 └───┼────┼─────┼────────────┼───────────┼──────────┼──────────┼──────────────────────────────┘
     │    │     │            │           │          │          │
     │    │     │            │           └──────────┴──────────┴──► insert slots' inBus
     │    │     │            │                 (runtime = hw_ch + 8)      │
     │    │     │            │                                            │
     │    │     │            │                    ┌───────────────────────┴────────────┐
     │    │     │            │                    │  ~insertGroup                      │
     │    │     │            │                    │   slot 1 effect ──► bus 50/51      │
     │    │     │            │                    │   slot 2 effect ──► bus 52/53      │
     │    │     │            │                    │   slot 3 effect ──► bus 54/55      │
     │    │     │            │                    └────────────┬───────────────────────┘
     │    │     │            │                                 │
     │    │     ▼            ▼                                 │      hw6 ──► vocoder
     │    │  ┌──────────────────────────────────────────────┐  │              modulator
     │    │  │  inputRouter    (head of ~busGroup)          │◄─┘             (hard-wired,
     │    │  │                                              │                 SoundIn.ar(6))
     │    │  │  send1 = SoundIn(2) × send1Gain × gate       │
     │    │  │  send2 = SoundIn(3) × send2Gain × gate       │
     │    │  │    gate: DetectSilence, 10 ms up / 4 s down, │
     │    │  │          floor 0.1                           │
     │    │  │  insert1..3 = In.ar(50/51, 52/53, 54/55)     │
     │    │  │                                              │
     │    │  │  to_master1 = Σ( send1_r[0..1]·send1,        │
     │    │  │                  send2_r[0..1]·send2,        │
     │    │  │                  insertN_r[0..1]·insertN )   │
     │    │  │  to_master2 = Σ( send1_r[2..3]·send1,        │
     │    │  │                  send2_r[2..3]·send2,        │
     │    │  │                  insertN_r[2..3]·insertN,    │
     │    │  │      ┌──────────► InFeedback.ar(60/61)       │
     │    │  │      │               × par_amount )          │   1 control period late
     │    │  └──────┼─────────────┬────────────────┬────────┘   (5.33 ms @ -z 256)
     │    │         │             │                │
     │    │         │        bus 56/57        bus 58/59
     │    │         │             │                │
     │    │         │             ▼                ▼
     │    │         │   ┌───────────────┐  ┌───────────────┐
     │    │         │   │ bus/master    │  │ bus/master    │      (~busGroup, before
     │    │         │   │ effect slot 4 │  │ effect slot 5 │       outputRouter; an
     │    │         │   │  (unit 3)     │  │  (unit 4)     │       et_* is moved in
     │    │         │   │  et_*_1 or    │  │  et_*_2 or    │       here on selection)
     │    │         │   │  any fx def   │  │  any fx def   │
     │    │         │   └───────┬───────┘  └───────┬───────┘
     │    │         │           │                  │
     │    │         └───────────┤ bus 60/61        │ bus 62/63
     │    │                     │                  │
     ▼    ▼                     ▼                  ▼
 (unused)          ┌────────────────────────────────────────────────────────────┐
                   │  outputRouter        (tail of ~busGroup)                    │
                   │                                                            │
                   │  insert1..3 = In.ar(50/51, 52/53, 54/55)   [stereo]         │
                   │  master1    = In.ar(60/61)                 [stereo]         │
                   │  master2    = In.ar(62/63)                 [stereo]         │
                   │  dry_dirN   = Pan2.ar(In.ar(synthN_in_ch), dry_N_p)         │
                   │                × timbre_N_dry × digDryGain   [stereo]       │
                   │  dry_dir4   = 1        ◄── BARE DC CONSTANT                 │
                   │                                                            │
                   │  main = Σ insertN·insertN_r[0]·insert_N_g                   │
                   │        + master1·master1_r[0] + master2·master2_r[0]        │
                   │  sub  = Σ insertN·insertN_r[1]·insert_N_g   (no masters)    │
                   │  auxK = Σ 0.5·(insertN[0]+insertN[1])·insertN_r[K+1]        │
                   │        + Σ dry_dirN·dry_dirN_r[K-1]                         │
                   │        + dry_dir4·dry_dir4_r[K-1]     ◄── DC injection      │
                   │                                                            │
                   │  main = StereoSpread.ar(main, stereoSpread)                 │
                   │  sub  = StereoSpread.ar(sub,  stereoSpread)                 │
                   │                                                            │
                   │  NO LIMITER ANYWHERE IN THIS SYNTH                          │
                   └───┬────┬────┬────┬────┬────┬────┬────┬─────────────────────┘
                       │    │    │    │    │    │    │    │
        Out.ar(7, main[0] × -1)   │    │    │    │    │    │
             Out.ar(0, main[1] × -1)   │    │    │    │    │
                  Out.ar(2, sub[0])    │    │    │    │    │
                       Out.ar(1, sub[1])    │    │    │    │
                            Out.ar(5, aux1.sum)   │    │   │
                                 Out.ar(6, aux2.sum)  │   │
                                      Out.ar(3, aux3.sum) │
                                           Out.ar(4, aux4.sum)
                       │    │    │    │    │    │    │    │
 ┌─────────────────────▼────▼────▼────▼────▼────▼────▼────▼──────────────────────┐
 │  DAC — 8 hardware outputs                                                     │
 │  bus 7 = main L (inv)   bus 0 = main R (inv)                                  │
 │  bus 2 = sub  L         bus 1 = sub  R                                        │
 │  bus 5 = aux1           bus 6 = aux2      bus 3 = aux3     bus 4 = aux4       │
 └───────────────────────────────────────────────────────────────────────────────┘
```

### The summing matrix in `outputRouter`, precisely

```
                       main   sub    aux1   aux2   aux3   aux4
  insert 1   stereo    r[0]   r[1]   r[2]   r[3]   r[4]   r[5]     × insert_1_g
  insert 2   stereo    r[0]   r[1]   r[2]   r[3]   r[4]   r[5]     × insert_2_g
  insert 3   stereo    r[0]   r[1]   r[2]   r[3]   r[4]   r[5]     × insert_3_g
  master 1   stereo    r[0]   ----   ----   ----   ----   ----     (rows 1-5 commented out)
  master 2   stereo    r[0]   ----   ----   ----   ----   ----     (rows 1-5 commented out)
  dry_dir1   stereo    ----   ----   r[0]   r[1]   r[2]   r[3]     × timbre_1_dry × digDryGain
  dry_dir2   stereo    ----   ----   r[0]   r[1]   r[2]   r[3]     × timbre_2_dry × digDryGain
  dry_dir3   stereo    ----   ----   r[0]   r[1]   r[2]   r[3]     × timbre_3_dry × digDryGain
  dry_dir4   =1 (DC)   ----   ----   r[0]   r[1]   r[2]   r[3]     × nothing
                                     └───── these four sum, then .sum() folds L+R to mono ─────┘

  main/sub keep stereo → StereoSpread → 2 × Out.ar
  aux1..4 are computed as 2-channel arrays and then .sum()'d to mono at the Out.
```

---

## 6. Dangerous, broken, and load-bearing

Ordered by how badly it would hurt.

### 6.1 Unbounded feedback with a ×2 in the loop — `stereoDelay_*` and `pingpongDelay_*`

`stereoDelay_*` (L800–L806):

```
sigL = DelayL.ar( LPF.ar(source, cutoff) + (sigLfb * ControlSpec.new(-1,1,\lin,0.01).map(feedbackL)), … );
sigLfb.write( LPF.ar( sigL * 2, cutoff) );        // ← hard ×2 back into the loop
```

`pingpongDelay_*` (L919–L926) is the same with the channels crossed (`sigLfb.write(LPF(sigR*2))`).

Loop gain = **2 × |map(feedbackL)|**, i.e. it exceeds unity for `|feedbackL| > 0.5`. There is no
`tanh`, `softclip`, `clip`, `Compander` or `Limiter` **inside** either loop — only an `LPF`,
which attenuates highs but has unity DC gain. Above the threshold the delay-line contents grow
exponentially and will reach `inf`, then `NaN`, within seconds.

`pingpongDelay_*` has `.tanh` at L944, but it is applied to `out` *after* the loop, so it bounds
what is written to the bus while the loop itself still diverges. Once the delay buffer holds
`NaN`, `tanh(NaN) = NaN`, and NaN reaches `outputRouter` and the DAC. `stereoDelay_*` has no
output limiter at all (L824). **This is the single most likely way to produce a hard,
non-recoverable audio fault from a patch parameter.**

Contrast `bbdDelay_*` (L1085 `.clip(-1,1).softclip` inside `local.write`) and `tapeDelay_*`
(L1213 `.atan` inside `LocalOut`), which are both correctly bounded. Someone knew to do this and
it did not get applied to the two stereo delays.

`delay_*` (L677) is the near-miss version:

```
local.write( wet_sig * max(feedback - ControlSpec.new(0.01, 0, \lin, 0.01).map(time), 0) );
```

Loop gain = `feedback` minus a time-dependent 0.01…0. At `time = 1` the subtraction is exactly 0,
so `feedback = 1.0` gives a loop gain of **exactly 1** — infinite sustain, and any DC offset in
the loop integrates without bound. No limiter in the loop, no limiter on the output (L698).

### 6.2 `dry_dir4 = 1` — the routing row is NOT permanently zero

L476: `dry_dir4 = 1;` — a bare integer, later multiplied by `dry_dir4_r[0..3]` and summed into
aux1–aux4 (L525, L535, L545, L555).

The previously stated mitigation ("harmless only because its routing row defaults to zeros") does
not hold. `efx_server.scd` L853–L855 **[read]**:

```
param_name = ("dry_dir" ++ (unitNum.asInteger + 1).asString ++ "_r").asSymbol;
~dspOutputWrapper.set(param_name, arr[2..]);   // aux1..aux4 toggles from /fx{n}/out
```

`~initUnit` is invoked for units **0 through 4** (`init_sc_1.scd`, `5.do{arg i; …}`), so a
`/fx3/out` message — the *first bus/master effect slot's* output routing — computes
`param_name = \dry_dir4_r` and writes it. `outputRouter` really does have a `dry_dir4_r` control,
so the write lands.

Consequence: **route bus-effect slot 4 to any aux output and `dry_dir4_r[k]` becomes 1**, which
injects a constant `1.0` into that aux bus. Because the constant is a scalar added to a
2-channel array and the result is then `.sum()`'d (§6.4), the DC that actually reaches the DAC
is **2.0** — twice full scale. That is a hard DC offset on an analogue output.

Note also that `/fx4/out` computes `\dry_dir5_r` and `\insert5_r`, neither of which exists —
those `set`s are silently ignored **[inferred]**, so the second bus-effect slot has no aux
routing path at all.

### 6.3 `In.ar(synth1_in_ch)` reads output buses at its defaults

L473–L475:

```
dry_dir1 = Pan2.ar(In.ar(synth1_in_ch), dry_1_p);   // synth1_in_ch = 4
dry_dir2 = Pan2.ar(In.ar(synth2_in_ch), dry_2_p);   // synth2_in_ch = 5
dry_dir3 = Pan2.ar(In.ar(synth3_in_ch), dry_3_p);   // synth3_in_ch = 6
```

With `numOutputBusChannels = 8`, buses 4/5/6 are **hardware outputs aux4/aux1/aux2**, not
hardware inputs. Reading a hardware input requires `SoundIn.ar(n)` or `In.ar(8 + n)`. The
defaults are off by the 8-bus output offset.

At runtime this is repaired: `efx_server.scd` L817–L824 sets `synthN_in_ch` from the same
`hw_ch + 8` array it gives the effect's `inBus`. So the defaults only bite in the window between
`outputRouter` being created and the first `/fx{n}/in` message arriving.

In that window, `In.ar(4)` on a bus that `outputRouter` itself writes *later in the same synth*
returns **zeros**, because scsynth's `In` yields silence from a bus not yet touched this block
**[inferred]** — so the symptom is silent digital dry, not feedback. But if any other node were
ever ordered ahead of `outputRouter` and wrote bus 4, 5 or 6, this would become a live
output-to-dry-input feedback path. It is one node-order mistake away from howling.

**Do not "fix" the defaults to 12/13/14 without checking the front end**, because the runtime
value overrides them anyway and the only observable effect of changing them is in that startup
window.

### 6.4 The aux sums double the insert contribution

L517–L525 (aux1; aux2/3/4 identical):

```
aux1 = (0.5 * (insert1[0] + insert1[1]) * insert1_r[2])    ← mono scalar
     + …
     + (dry_dir1 * dry_dir1_r[0])                          ← 2-channel array
     + …
…
Out.ar(5, aux1.sum);
```

In SuperCollider, `mono + [L, R]` multichannel-expands to `[mono + L, mono + R]`. `.sum()` then
yields `2·mono + L + R`. The insert (and `dry_dir4`) terms are therefore **multiplied by two**,
while the `dry_dirN` terms are correctly folded L+R to mono.

An insert routed to an aux is **+6 dB** relative to the same insert routed to main or sub. Fixing
this changes the level of every aux-routed insert, so it is a compatibility-breaking fix, not a
free one.

### 6.5 `chorus_*` / `stereoChorus_*` — `XFade2` argument-order bug

L1567–L1569 and L1999–L2006:

```
LocalOut.ar( XFade2.ar(input, sig, 0, ((feedback * 2) - 1)) );
```

`XFade2.ar(inA, inB, pan, level)`. The feedback control has been placed in the **`level`** slot
with `pan` pinned at 0. Consequences:

* The crossfade is permanently locked at 50/50 between the dry input and the delayed signal.
* `feedback = 0.5` → `level = 0` → **zero feedback at the knob's centre**.
* `feedback < 0.5` → negative level → **the feedback path is phase-inverted**.
* The knob's actual behaviour is |2·fb − 1|, a V shape, not a monotonic amount.

The intent was almost certainly `XFade2.ar(input, sig, (feedback*2)-1)`. Both loops remain
stable (peak gain 0.42 and 0.707 respectively), so this is a wrong-control bug, not a safety bug.

### 6.6 `resonator_*` — `Select.ar` index runs off the end of the array

L2679: `out = Select.ar( floor(filterType*3), [lpf, bpf, hpf] );`

`filterType` defaults to **1** → `floor(3) = 3` → index 3 into a 3-element array. `Select` clips
the index to the valid range **[inferred: scsynth's `Select` applies `sc_clip(index, 0,
numInputs-2)`]**, so it lands on `hpf`. The metadata declares
`fitlerType: ControlSpec(0.0, 3.0, …)` (note the typo in the key), so the front end plausibly
sends 0…3, which after `×3` and `floor` gives 0, 3, 6, 9 — three of the four settings clip to
`hpf` and only "0" reaches `lpf`. **`bpf` is unreachable.** The multiplier should be 2 for a
0…1 control, or the `floor(…)` should be dropped for a 0…2 integer control.

Also note `Select.ar` evaluates every branch: nine filters (3× `RLPF`, 3× `BPF`, 3× `RHPF`) run
continuously regardless of selection. And the `bpf` branch carries a hard `×8` on each band
(L2677) that the other two branches do not.

### 6.7 Gain applied twice — `phaser12stage_*`

L2455: `out = ((sig * 0.5) + (source * 0.5)) * g_comp;`
L2467: `Out.ar( outBus, (out * env * g_out * g_comp).softclip );`

`g_comp = ControlSpec.new(0, 1.7, …).map(gain)` (L2453). It is applied twice, so the effective
range is 0…**2.89**, and the taper is quadratic rather than linear. `phaser6stage_*` applies it
once (L2270) — the two are inconsistent.

The same def also builds its resonance path from `BBandPass.ar(…, 0.02, 25)` — a 0.02-octave
band-pass with a **×25** output multiplier, three of them plus an `HPF … 5`, summed and scaled by
`feedback` (default **0.99**) × 0.95 (L2447). Peak feed-forward gain approaching 80×, held in
check by nothing but the final `.softclip`.

### 6.8 Unbounded output stages

No `outputRouter` limiter of any kind. Upstream, the following write to a bus with no ceiling:

| Def | Uncontrolled term | L |
|---|---|---|
| `delay_*` | `g_comp = 3` × `((gain*1)+0.1)` | 698 |
| `bbdDelay_*` | `g_comp = 1.3` × `((gain*1.35)+1)`, after a **2:1 upward expander** (`Compander … slopeAbove: 2`) | 1080, 1091 |
| `bitcrusher_*` | hard-coded `g_comp = 5` then `g_scaled` 0…3 → **up to 15×**, no clip | 2568, 2574 |
| `vocoder10/16/21_*` | band envelopes `Amplitude.ar(…, mul: 1000)`, 10–21 bands summed, then `Out.ar(outBus, out * env * g_out)` with **no clip at all** | 2939, 2943 |
| `tapeDelay_*` | loop bounded to ±1.5708 by `.atan`, then `g_scaled` 0…4 → **±6.28** | 1213, 1239 |
| `ensemble_*` | `XFade2(…, level: 2.25)` then `g_scaled` 0…1.5 | 1875, 1893 |

The vocoders are the worst of these: a 1000× envelope driving 21 resonant band-passes with no
limiter anywhere in the chain.

### 6.9 Control discontinuities — the stale `rates:` arrays

`SynthDef`'s `rates:` argument assigns a lag time per *argument, positionally*. A short array is
padded with zeros **[inferred: `SynthDef.addControlsFromArgsOfFunc` does
`rates.asArray.extend(names.size, 0)`]** — so every control past the end of the array is
**completely unlagged and steps instantaneously**.

24 of the 33 defs have a `rates:` array that no longer matches the argument list:

| Def | args | rates | Controls that step with no lag |
|---|---|---|---|
| `outputRouter` | 35 | 10 | `insert2_r`, `insert3_r`, `master1_r`, `master2_r`, `dry_dir1..4_r`, `timbre_1..3_dry`, `insert_1..3_g`, `dry_1..3_p`, `synth1..3_in_ch`, `digDryGain`, `stereoSpread` |
| `inputRouter` | 16 | 10 | `send2Gain`, `send1Thresh`, `send2Thresh`, `clampTime`, `relaxTime`, `gainFactorMin` |
| `resonator_*` | 23 | 13 | `cutoff1..3`, `levelLow/Mid/High`, `filterType`, `rate`, `depth`, `gain` |
| `ensemble_*` | 20 | 11 | `mix`, `feedback`, `time`, `rate`, `depth`, `tone`, `vibratoRate`, `vibratoDepth`, `gain` |
| `phaser6stage_*`, `phaser12stage_*` | 19 | 12 | `feedback`, `sweep`, `rate`, `depth`, `tone`, `noiseGain`, `gain` |
| `stereoFlanger_*`, `stereoChorus_*` | 22 | 16 | `rateLeft`, `rateRight`, `depth`, `phaseOffset`, `tone`, `gain` |
| `flanger_*` | 19 | 14 | `rate`, `depth`, `tone`, `noiseGain`, `gain` |
| `et_blackhole_*` | 22 | 16 | `highLvl`, `lowLvl`, `preDelay`, `size`, `invGravity`, `gain` |
| `et_room_*`, `et_hall_*`, `et_plate_*` | 22 | 16 | `highLvl`/`highDamp`, `lowLvl`/`lowDamp`, `preDelay`, `size`, `decay`, `gain` |
| `et_shimmer_*` | 22 | 16 | `highDecay`, `lowDecay`, `delay`, `size`, `decay`, `gain` |
| `vocoder10/16/21_*` | 16 | 13 | `sensitivity`, `tone`, `noiseGain` |
| `bitcrusher_*` | 15 | 12 | `bitDepth`, `sampleRate`, `gain` |
| `chorus_*` | 18 | 16 | `tone`, `gain` |
| `dualChorus_*` | 20 | 19 | `gain` |
| `output` | 15 | 10 | `send_one`, `send_two`, `par_bus`, `par_amount`, `g_out` |
| `sendInput` | 11 | 10 | `g_in` |

Two of these are worth calling out individually because they create an **asymmetry between
otherwise-symmetric controls**:

* `inputRouter`: `send1Gain` gets a **0.2 s lag**, `send2Gain` gets **none**. The two effect
  sends smooth differently. Also `insert3_r` gets 0.1 s while `insert1_r`/`insert2_r` get 0.
* `outputRouter`: `insert1_r` happens to land on the last rates entry and gets a **0.2 s lag**,
  while `insert2_r` and `insert3_r` get **none**. Changing insert-1 routing crossfades; changing
  insert-2 or insert-3 routing steps and clicks.

Nine defs are correct: `stereoOutput`, `delay_*`, `stereoDelay_*`, `pingpongDelay_*`,
`bbdDelay_*`, `tapeDelay_*`, `timePhaser_*`, plus `none_*`/`default`/`input` where the array is
merely longer than the argument list (extra entries ignored).

Combined with `env.floor` in the `et_*` defs (§4), these are the two main sources of clicks in
the box.

### 6.10 Phase and polarity

* **Main is inverted, sub and aux are not** (L564–L571). L/R polarity within main is consistent,
  so a stereo listener hears nothing wrong. A user summing main and sub into the same console —
  or comparing main against an aux — gets partial cancellation. The commented-out "usb" block at
  L574–L581 has no inversion and a different channel order, so this is ESAI/DAC-specific and
  **must not be removed without knowing the codec's polarity.**
* `ensemble_*` L1856 deliberately inverts feedback tap 2: `fb2.write(sig2 * tap2Feedback * -1)`.
  Intentional decorrelation.
* `chorus_*` / `stereoChorus_*` invert the feedback path *accidentally* below knob centre (§6.5).
* `~panScale = ControlSpec.new(1, -1, …)` (L24) — an inverted spec, so `pan = 0` is hard **right**
  and `pan = 1` is hard **left**. Consistent with `bitcrusher_*`'s `Pan2.ar(sig, (pan*-2)+1)`, but
  it is the opposite of the usual convention and easy to get backwards.

### 6.11 Feedback across the node graph — `InFeedback`

`inputRouter` L362 / L371:

```
+ (InFeedback.ar(master1_out_busses[0]) * par_amount)     // master1_out_busses = [60, 61] (L273)
```

This is the only cross-node feedback in the system: master 1's **return** is fed into master 2's
**input** with one control period (5.333 ms) of delay. `InFeedback` is the correct UGen here
because the master-1 effect runs *after* `inputRouter`.

Risks:

1. `par_amount` is **unclipped**. `efx_server.scd` L906 sets it straight from the OSC message.
2. All five effect slots' `/fx{n}/par` handlers write the **same** `par_amount` control on the
   same `inputRouter` synth. Units 0–4 fight over one value; last writer wins. Almost certainly
   a bug — there is one parallel amount for the whole machine, controllable from five places.
3. The loop is only open because master 2 writes 62/63, which nothing feeds back. **If the front
   end ever assigned bus-effect slot 5 an `outBus` of 60**, this becomes a real audio feedback
   loop with a user-controllable gain and no limiter. Nothing in the SynthDef prevents it.

### 6.12 Divide-by-zero and NaN sources

I found **no explicit division by a control value** anywhere in the file. `ControlSpec.map` clips
its input to 0…1 before warping **[inferred: `ControlSpec:map` is `^warp.map(value.clip(0.0,
1.0))`]**, so the many `\exp` warps cannot be handed a non-positive value and cannot produce
`log(0)`.

The realistic NaN sources are:

1. Divergent delay loops (§6.1) reaching `inf` then `inf - inf`.
2. Filter blow-up: `BBandPass.ar(carrier, freq, 0.01, …)` in `vocoder10_*` — a **0.01-octave**
   bandwidth at 48 kHz is an extremely high-Q biquad; with a 1000× envelope on `mul`, single-
   precision coefficient error can drive it unstable **[inferred]**.
3. `resonator_*` `RLPF`/`RHPF` with `rq` clipped to 0.01 (L2665) — safe, that clip is doing real work.

### 6.13 Dead code and dead controls

Worth knowing before anyone "cleans up":

* `wet` and `dry` are declared in **every** effect SynthDef and used in **none**. Same for `ctl`,
  `ctlIn`, `ctlOut`. They occupy control ordinals, which the front end's positional parameter
  indexing depends on — **deleting them will shift every parameter index.**
* `mix` is dead in all six `et_*` defs (reassigned to 1).
* `timbre_1/2/3_dry_main` in `outputRouter` are set over OSC (`efx_server.scd` L951) and used
  only in commented-out lines. The "digital dry to main" feature is **not implemented**.
* `master1_r[1..5]`, `master2_r[1..5]` — commented out. Masters reach main only.
* `balance` and `mode` in `inputRouter` — never referenced.
* `bbdDelay_*` L1017: `readPointer = Phasor.ar(0, numSamples * time, 0, numSamples)` where
  `numSamples = 1152000`. The only consumers are commented out (L1073). A `Phasor` running at up
  to 1.15M samples/sample burns CPU for nothing, and its accumulator is well past the point where
  single-precision float has 1-sample resolution.
* `tapeDelay_*` L1165: `ampComp = Amplitude.ar((sig * 30).clip(-1,1), …)` is evaluated when `sig`
  is still the literal `[0]` from its declaration, and `ampComp` is then never used. Dead.
* `chorus_*` L1564: `sig.tanh;` — a bare expression whose result is discarded. Almost certainly
  meant to be `sig = sig.tanh`, which means the intended saturation stage **is not in the graph**.
* `~vocoder_params` (L2708) — an entire band-table environment nothing reads.
* `sendInput`, `input`, `output`, `stereoOutput` are compiled and shipped but never instantiated
  by `init_sc_1.scd`. All four contain hard-coded writes to hardware output bus 0 (main R) and/or
  bus 4 (aux4) and default `sendOneBus`/`sendTwoBus` of 0. If anything ever instantiates them,
  audio lands on main R.

### 6.14 Wet/dry semantics are inconsistent across the family

Every effect ends with `XFade2.ar(<A>, wet, (mix*2)-1)`. `<A>` differs:

* `flanger_0/3`, `chorus_0/3`, `phaser6stage_0/3`, `phaser12stage_0/3`, `resonator_0/3`,
  `ensemble_0/3`, `stereoChorus_0/3`, `stereoFlanger_0/3`, `dualChorus_0/3` use the **source**,
  scaled by an arbitrary makeup constant: `×1.25`, `×1.75`, `×1.9`, `×2`, `×2.5`. `mix = 0`
  therefore gives the dry signal **louder than unity**.
* All `_1` and `_2` variants, and every delay family, use `Silent.ar(…)`. `mix = 0` gives
  **silence**, not dry.

So the same front-panel "Mix" control means "wet/dry blend" on some effects and "wet level" on
others, and turning it to zero either boosts the dry by up to 8 dB or mutes the slot, depending
on which channel configuration the slot happens to be in.

---

## 7. Source vs. device inventory

`synthdefs.scd` defines 98 SynthDefs. `synthdef-names.txt` lists 104 on the device.

**In the source, missing from the device (1):**

* `et_spring` — commented out at L3629–L3700, therefore never `.store`d. See §4.

**On the device, not in this source (7):**

`bitcrusher2`, `echo_0`, `echo_1`, `echo_2`, `spaceFlanger`, `spacePhaser`, `timeEnsemble`

These are stale `.scsyndef` files left in `/usr/share/las-fx/synthdefs/` from an earlier build.
`init_sc_1.scd` does `loadDirectory("/usr/share/las-fx/synthdefs/")`, which loads **everything in
the directory** regardless of whether the current `synthdefs.scd` still defines it — so they are
live, loadable synthdefs whose source is not in this file. If a preset ever names one of them it
will instantiate, and nothing here documents what it does.

The remaining 97 match one-for-one.

---

## 8. Things to leave alone

If you touch any of these, the instrument changes audibly or stops working:

1. **`-z 256` block size.** Every `FbNode`/`LocalIn`/`InFeedback` loop's delay is one block.
   Changing it retunes every feedback effect and changes the master-1 → master-2 parallel path
   latency.
2. **The `Out.ar(7/0/2/1/5/6/3/4)` order and the `* -1` on main.** ESAI/codec-specific.
3. **`~dspOutputWrapper.moveToTail(~busGroup)` in `efx_server.scd` L269.** Remove it and every
   bus/master effect goes silent, with no error.
4. **The `wet`, `dry`, `ctl`, `ctlIn`, `ctlOut` and `mix` dead controls.** They hold the
   positional parameter ordinals the front end indexes into.
5. **The +6 dB aux doubling (§6.4).** It is a bug, but every factory preset's aux level was
   voiced with it in place.
6. **`dry_dir4 = 1` (§6.2).** Deleting it is safe and correct; leaving it while changing
   `dry_dir4_r`'s wiring is not.
