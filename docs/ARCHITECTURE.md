# How the Moog One is actually built

Read before adding anything. This is assembled from the instrument's own
`init_sc_1.scd`, `synthdefs.scd` and `efx_server.scd`, and from live measurement —
not from inference.

## Corrections from the hardware, added after the software teardown

Three things this document had wrong, from reading teardown photographs and Moog's
own documentation rather than the firmware.

**The audio link is ESAI, not USB.** `xmos-audio` is the i.MX6's ESAI (TDM) port
with the XMOS presenting as a codec, and **the XMOS is the bit- and frame-clock
master**. The USB link carries *control* only — the voice controller is an IP host
at `203.0.113.2` on `usbint`. Two separate paths that this document had conflated.

**And the USB link runs the other way round from how this document once described
it.** The i.MX6 is the USB **host**, not a gadget: both `ci_hdrc` controllers come
up as `EHCI Host Controller` and `cdc_ether` binds to a peripheral on the bus
(`dmesg` t=0.49 s and t=12.06 s). The **XMOS is the USB device**, and it also
enumerates the rear USB-B socket that a computer sees as "Moog One" — those
descriptors live in `app_las_v2.1.2.bin`, stored bit-reversed. `ethext`, the RJ45,
is a second `cdc_ether` interface on that same link, because the i.MX6's own
Ethernet MAC is `status = "disabled"` in the device tree.

The consequence is not cosmetic: **no MIDI byte from either port ever reaches
Linux.** Both DIN and USB MIDI terminate in XMOS firmware — `ttymxc` appears zero
times in the rootfs and `31250` zero times in `las-frontend`. Nothing installed on
the Linux side can observe or inject MIDI at the port level. See
`docs/arch/midi-stack.md`.
It also makes the argument about staying inside the sample clock stronger than it
was written: the clock is generated on the analog side, and the computer follows it.

**The voices are generated as audio.** Each voice carries **four PCM1681 8-channel
DACs — 32 DAC channels per voice, 64 per card**. Moog produce the control voltages
as 24-bit audio streams, which is why every voice card needs an audio-capable
processor rather than a microcontroller. The analog is genuinely analog — THAT 2172
VCAs, LM13700 OTAs, and a **discrete** ladder (SOT-363 dual NPNs alternating with
caps, one pair per stage). No CEM, AS or SSI parts anywhere.

**Card and voice counts.** Two voices per card, four cards per stack, one stack per
side: an 8-voice is 4 cards, a 16-voice is 8. Voice-card processor is an
`XL216-512-TQ128-C20`; the interface board carries two `XU216-512-TQ128-C20` — the
same die with a USB PHY, which is why the U-series sits where USB is needed and the
L-series out on the cards.

**And this instrument is not on the newest firmware.** It runs **v1.5.0**; **1.8.0,
1.8.1 and 1.8.2** shipped in August and September 2025. Two of their fixes land
squarely in this project's path: **crashes on large MIDI input**, and **oscillator
hard sync via CC causing panel lag and crashes**. Nothing tuning-related changed
after 1.5.0. The Moog One is *not* on Moog's November 2025 end-of-service list.

## The one thing to understand first

**The voices are analog and most of their audio never enters the computer.** The
i.MX6 is not the voice engine. It is the effects and routing engine, and it sees
only what the analog side sends it.

```
   analog voice cards  ──────────────────────────────► main outs (analog dry)
            │
            │  effect sends            ┌──────────── i.MX6 / scsynth ──────────┐
            ├─► ADC in 2 ─ send 1 ────►│ inputRouter                          │
            ├─► ADC in 3 ─ send 2 ────►│   gates, gains, routes to masters    │
            │                          │        │                             │
            │  per-timbre dry          │        ▼  bus 56/57, 58/59           │
            ├─► ADC in 4 ─ timbre 1 ──►│   master fx 1, master fx 2           │
            ├─► ADC in 5 ─ timbre 2 ──►│        │  (the Eventide reverbs)     │
            └─► ADC in 6 ─ timbre 3 ──►│        ▼  bus 60/61, 62/63           │
                                       │   outputRouter                       │
                                       │     sums inserts + masters + dry     │
                                       └──────────────┬───────────────────────┘
                                                      ▼  8 DAC channels
                                            main, sub, aux1-4
```

`scsynth` runs with **9 input and 8 output** hardware channels, block size 256,
48 kHz (`init_sc_1.scd`).

### Hardware channel map

Taken from `Out.ar` in `outputRouter` and `SoundIn.ar` in `inputRouter`.

| DAC out | carries | | ADC in | carries |
|---|---|---|---|---|
| 7 | main L *(phase inverted)* | | 2 | effect send 1 |
| 0 | main R *(phase inverted)* | | 3 | effect send 2 |
| 2 | sub L | | 4 | timbre 1 dry |
| 1 | sub R | | 5 | timbre 2 dry |
| 5 | aux 1 | | 6 | timbre 3 dry |
| 6 | aux 2 | | | |
| 3 | aux 3 | | | |
| 4 | aux 4 | | | |

The main outs are **7 and 0**, not 0 and 1, and both are inverted. Anything writing
to the mains has to match that or it cancels against the instrument's own output.

### Internal buses

| bus | carries |
|---|---|
| 50/51, 52/53, 54/55 | insert slot 1, 2, 3 returns |
| 56/57, 58/59 | `inputRouter` → master effect 1, 2 (the send **into** the bus effects) |
| 60/61, 62/63 | master effect 1, 2 returns (**out of** the bus effects) |

56-59 and 60-63 are the two halves of one chain, not a mismatch.

## The effect rack: five slots, and the Eventides live in two of them

`init_sc_1.scd` makes five units. **Slots 0-2 are inserts** (in `~insertGroup`),
**slots 3-4 are bus/master** (in `~busGroup`).

**Every Eventide instance is created at boot and immediately paused:**

```supercollider
~eventides.add(\et_plate_1 -> Synth(\et_plate_1, target: ~eventideGroup));
~eventides.at(\et_plate_1).run(false);
```

Ten of them — five reverbs × two instances, one per bus slot. They are never
created on demand and never freed. `~initEffect` swaps one in by **moving the
existing node** from `~eventideGroup` into the slot's group, and swaps it out by
moving it back and calling `.run(false)`.

That is not an implementation detail, it is the whole design, and it exists because
**freeing a LADSPA node terminates `scsynth`** (`MoogOneFixes` finding 1). Moog
never free them, so they never hit it.

Two consequences worth stating plainly:

* **The reverbs are only available on the two bus slots.** An insert slot gets a
  fresh `Synth` of whatever native effect is asked for; a bus slot gets a
  pre-allocated Eventide moved into place.
* **The rack already exists and is complete.** Five slots, a full native effect set,
  five Eventide reverbs, routing to main/sub/aux. Anything that adds "an effect
  send" is rebuilding infrastructure the instrument already has.

## What runs where

Two cores, and both are spoken for.

| | cpu0 | cpu1 |
|---|---|---|
| reserved by | — | `isolcpus=1` in the kernel command line |
| runs | `las-frontend`, X, `sclang`, `las-sc`, panel | **`scsynth`'s audio thread, alone** |
| scheduling | ordinary | `SCHED_FIFO` **priority 99** |

`scsynth`'s audio thread is pinned to cpu1 by Moog's own patched `SC_AlsaDriver` —
upstream SuperCollider has no ALSA backend at all, and the driver's error strings
(`Unsuccessful in setting thread core affinity`) say what it was written for.

`taskset -p <pid>` shows only a process's **main** thread. `scsynth` reads
`affinity=1` while the thread that matters is on cpu1. Check
`/proc/<pid>/task/*/stat` instead.

**There is no spare core.** Anything added to this instrument belongs on cpu0.

## The budget, and why it is tight

The audio thread reaches **82% of cpu1** on a loaded patch. `SCHED_FIFO` is
throttled at 95%. An Eventide reverb costs **23-33%** of a core (`CPU_COST`, measured
on an idle engine — measuring on a loaded one reads about half, because the throttle
caps the thread and the difference records the ceiling).

So the five-slot rack is already close to what the machine can do, and the levers
are narrow:

* **Block size.** 128 → 256 gave back real headroom and cost 2.7 ms of latency.
* **Moving non-DSP work off cpu1.** What `init_sc_2.scd` means by `frontendGroup
  lives on shared CPU core, dspGroup lives on DSP core`. It was never about gaining
  a core.

## What this rules out, and what it leaves

**Ruled out by the architecture, not by effort:**

* More reverb. There are five, on dedicated hardware-adjacent slots, pre-allocated.
* Big added DSP. There is no core to put it on.
* Anything in the live audio path over a network. Measured at 105-165 ms to the
  jacks — the machine's value is that it is *inside the sample clock*.

**Left open, and genuinely:**

* **Control, not audio.** The instrument's own namespace is huge and largely
  unmapped — 464 `/p` addresses, `/v2/nw`, the whole compressed table.
* **Things that are cheap in DSP and expensive in interface.** The screen is 832×480
  and the panel has 108 knobs; a browser has neither limit.
* **Storage.** 234 GB of USB against 148 MB free on the rootfs.
* **The routing matrix.** `outputRouter` already sums inserts, masters and per-timbre
  dry into main/sub/aux with a full routing matrix, and the panel exposes a fraction
  of it.

## Latent bug spotted while reading

`outputRouter` sets `dry_dir4 = 1` — a bare constant, not a signal — and then sums
`dry_dir4 * dry_dir4_r[n]` into all four aux outputs. It is harmless only because
`dry_dir4_r` defaults to `#[0,0,0,0]`. Anything that sets a non-zero value in that
row puts **DC on an aux output**.
