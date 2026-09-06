# A plugin for the Moog One

Design, grounded in what this project measured rather than what a plugin usually
assumes. Everything cited here was measured on the instrument; where a thing is
unproven it is marked unproven and the design does not lean on it.

---

## The three findings that set the shape

**1. Audio comes over the network, not USB.** The USB socket declares
MIDIStreaming and no AudioStreaming interface, and both of its configuration
descriptors are byte-identical — there is no hidden audio mode to switch into
(§8a, §8d). But `scsynth` will stream its output bus to a TCP socket in real
time, and it was measured at **22.9 ms median from trigger to sound, 9.8 ms
spread** (§8b). That is plugin-viable, and it is the opposite of the conclusion
this project held a day earlier.

**2. Never burst.** The instrument's LAN and its internal link to the voice
controller are two CDC-Ether functions of a **single USB gadget**. Paced traffic
at 1.47× the realtime audio rate is untroubled; 2000 datagrams sent back to back
wedge the gadget below the level the host can reset, and only removing power
clears it (§8c). This is an architectural constraint, not advice. A plugin that
flushes a buffer in one go takes the instrument down mid-performance.

**3. The analog filters are upstream and unreachable.** The voice cards feed
`scsynth`'s input buses; nothing routes back. Audio sent to the instrument can
pass through its **effects**, never through its ladder filters. Any plugin
promising "your guitar through the Moog filter" over this path would be lying.

---

## What a plugin can be, and what each needs

| shape | what it does | status |
|---|---|---|
| **Control surface** | DAW automation of the instrument's parameters | **viable today** — needs only OSC |
| **Instrument** | play it, capture its audio, keep the patch with the project | **viable** — MIDI out + network audio in, 22.9 ms |
| **Effect** | audio out through the Moog's effects and back | **viable** — 115 ms round trip |

### The effect shape, and what it cost to open

This was gated on unproven ingress, and the gate is now cleared — but not by the
route the gate anticipated. TCP into a FIFO read by `DiskIn` does not work:
`/b_read` reads a FIFO honestly, and `DiskIn` will not continue from one, and
every attempt blocks the scsynth thread that also loads the instrument's own
presets (§8e). What works is `/b_setn` into a ring buffer read by a `Phasor` and
`BufRd` — no disk thread, and the traffic rides the same paced UDP interlock as
everything else here.

Measured, `et_plate_1` in the path, over a 6000-frame ring with a 2000-frame lead:

```
round trip     median 115.2 ms   spread 5.3 ms
writer         1.000x realtime
gap            held within 1232 frames of target
ethext/usbint  no new errors over 30 s of sustained ingress
```

**Sustained ingress does not wedge the gadget.** That was the actual question, and
the answer is that paced TCP and paced OSC at these rates are untroubled — the
Ethernet cable did not change this, since `/proc/net/route` still shows one route
out `ethext`, which is still a function of the same shared USB gadget.

Two rules the implementation must keep:

* **Never `/n_free` one of the instrument's effects.** It terminates scsynth. They
  are created once at boot and never freed by Moog's own code, and the free path
  takes the audio engine with it. Stop one with `enable = 0`, which releases an
  envelope whose doneAction is *pause*.
* **Run the effect on private buses.** Buses 64 and up are unused. Injecting on an
  input bus reaches nothing with the shipped patch — every digital dry gain in
  `outputRouter` is zero — so what a signal there reaches depends on the user's
  patch. Private buses depend on nothing and modify nothing.

---

## Architecture: a small real-time core, and the bridge for everything else

Two obvious options, both wrong on their own.

*Talk to the Vox bridge for everything.* Fast to build, but it puts a Python
process and a WebSocket hop inside a DAW's audio path, and it makes "run a Python
server first" a precondition for the plugin working at all. Wrong for the audio
path and wrong as a product.

*Reimplement the bridge in C++.* The library reader, the 127-control panel
catalogue, the learn system, the FM engine — months of work, none of which needs
to run in an audio callback.

**So: split them by whether they are real-time.**

```
┌──────────────────────────── the DAW process ────────────────────────────┐
│                                                                          │
│  audio thread          ── lock-free SPSC ring ──▶  never blocks,         │
│    pulls frames                                    never allocates,      │
│    reports latency                                 never takes a lock    │
│         ▲                                                                │
│         │                                                                │
│  network thread        TCP ← instrument's scsynth (raw float, paced)     │
│                        UDP → OSC to scsynth       (PACED, see below)     │
│                        CoreMIDI ↔ "Moog One"                             │
└──────────────────────────────────────────────────────────────────────────┘
              │ optional, non-real-time
              ▼
        the Vox bridge — library browsing, panel photo, learn, FM presets
```

The plugin's own core is small: OSC encode/decode, a TCP audio reader, MIDI, and a
ring buffer. OSC is a couple of hundred lines. Everything rich stays in the bridge
and is **optional** — the plugin works without it, and gains features when it is
running.

**CLAP first.** `clap-wrapper` produces VST3 and AU from the same source, so it is
one implementation rather than three.

---

## The four things that will actually be hard

### 1. Clock drift — the real problem with network audio in a DAW

The instrument runs on its own crystal. The DAW runs on its interface's. They are
not the same clock and they diverge. Measured: a network stream delivered 5.03 s
of audio in 5 s of wall clock — small, but **not zero**, and over a five-minute
take a fraction of a percent is seconds of divergence.

There is no way around this, only ways through it:

- **Adaptive resampling** driven by ring-buffer fill level — the correct answer,
  and the expensive one.
- **Accept drift for short takes** and resynchronise between them — acceptable for
  a capture workflow, unacceptable for live monitoring.

A plugin that ignores this will work beautifully in a demo and drift audibly in
a real session. **Decide this before writing the audio path, not after.**

### 2. Real-time discipline

No network I/O, no allocation, no locks, no logging on the audio thread. The
network thread fills a single-producer/single-consumer ring; the audio thread
drains it and nothing else. The measured **9.8 ms of jitter** sets the floor for
ring depth: 20 ms minimum, 40 ms for comfort.

### 3. Latency reporting

22.9 ms is about 1100 samples at 48 kHz, plus the ring. Report it through CLAP's
latency extension so the host compensates. Getting this wrong makes everything
recorded through the plugin land late, silently.

### 4. The pacing interlock is not optional

`moogone.transport.udp` spaces datagrams by 1 ms and the plugin must do the same,
in its own code, from the first commit. This is the one bug in this whole system
whose consequence is a dead instrument needing a power cycle.

---

## The CPU budget on the instrument side

`scsynth` idles at **55.2% of one core** running the instrument's own effects, is
**single-threaded for DSP** (the second core does not help), and runs `SCHED_FIFO`
at priority −95. A two-operator FM voice costs **0.50% of a core**; 64 voices
reached 87% with zero xruns.

So there is roughly 45% of one core for anything a plugin asks the instrument to
compute — real headroom, but a fixed and modest amount. Budget against
`moogone.fm.VOICE_CPU_COST`, which carries the measured number.

---

## Build order

1. **Control surface.** No audio, so no clock problem and no real-time risk.
   Proves the OSC path, the parameter map, and the pacing interlock under a host.
2. **Capture.** Add the TCP audio reader and the ring. This is where clock drift
   has to be solved. At the end of this step the instrument is a recordable
   instrument in a DAW.
3. **Effect.** Ingress through the ring, an effect on private buses, and the
   existing capture path as the return. Done: `moogone.ingress`, proven on
   hardware at 115 ms round trip.

Each step is useful on its own, which is the point of the ordering.

---

## What to tell users it cannot do

- No USB audio. The socket is MIDI only, and this was settled by reading the
  descriptors through IOKit, not inferred (§8a, §8d).
- No routing external audio through the analog ladder filters. They are upstream.
- No zero-latency monitoring. 22.9 ms is the floor for capture, and about
  **115 ms** round trip for the effect — most of it the lead the writer has to
  hold over the instrument's read pointer, which is what buys tolerance for two
  clocks that are not the same clock.
- The effect is the Moog's *digital* rack — 25 effects including the five Eventide
  reverbs. It is not the analog ladder filters, which are upstream.

Stating these plainly is worth more than discovering them in a session.
