# What we said, and whether it survived

Written after mapping the architecture properly. Two discoveries invalidated a lot
of earlier reasoning: **cpu1 is the audio core, not a spare one**, and **the
instrument already has a complete five-slot effect rack**. This is the honest
reckoning, so nothing false gets built on.

## Wrong, and retracted

| claim | why it was wrong |
|---|---|
| "cpu1 sits idle — 87% idle" | It runs `scsynth`'s audio thread, alone, at `SCHED_FIFO` 99. `taskset -p` shows only a process's MAIN thread, which hid it. |
| "Moog reserved a core and never claimed it" | They reserved it with `isolcpus=1` **and** claimed it, with a patched `SC_AlsaDriver` that pins the audio thread there. The design is complete. |
| "The two-server config would roughly double the DSP" | There is no spare core to gain. `frontendGroup lives on shared CPU core, dspGroup lives on DSP core` is about moving *non-DSP* work off cpu1. |
| "The second core is one binary away" | The binary was never what stood between the instrument and its second core. |
| "moogd on the isolated core cannot take cycles from audio" | Backwards. `taskset -c 1` put a web server **on the realtime audio core**. It runs on cpu0 now. |
| "The screen mirror saturates your audio core" | It saturates cpu0, which is the *shared* core — `las-frontend`, X, the panel. Still worth fixing; it was not stealing from the DSP. |
| "The control surface moved off the audio core" | It was never on the audio core. What moved was load off cpu0. |
| "Ship a larger default block size" (Moog bug report) | Retracted. Insert effects read straight from the ADC, so doubling the block doubles the skew between an insert-processed timbre and an analog-direct one — roughly 8-11 ms to 16-21 ms. **128 is correct.** |
| "`-z 256` took a patch from 72% to 51%" | Measured with a method since found unreliable. Re-measured cleanly on the default graph: **16.6% at 128, 12-13% at 256** — about 4 points, not 21. Directionally right, magnitude badly overstated. |
| "The effect send is a useful feature" | It duplicates a five-slot rack the instrument already has, with ten Eventide instances pre-allocated at boot. Adding a sixth effect is what caused the dropouts that then motivated the block-size change. |

## Still true

| claim | status |
|---|---|
| busybox `top` reports `%CPU` as a fraction of BOTH cores | Calibrated: 42% for a thread measured at 82% of one. |
| `scsynth`'s `/status.reply` reports CPU as exactly 0.000 | Verified against a thread doing 82% of a core. Dead fields in a working reply. |
| `moogone.load` measures the right thing | It takes the **busiest thread**, which is the audio thread on cpu1. Every number it produced stands. |
| An effect's cost cannot be measured on a busy engine | At an 82% baseline every reverb read 12-15%; on an idle engine, 23-33%. The throttle caps the thread and the difference records the ceiling. |
| `/n_free` on a LADSPA node terminates `scsynth` | Confirmed 2/2 — and now explained: Moog's own design never frees them, so they never hit it. |
| `et_spring` passes the plate's argument list into plugin 29153 | Ten ports either way, so it maps positionally and compiles silently, and every knob is the wrong knob. |
| The spring is a genuinely unreachable sixth reverb | `init_sc_1.scd` instantiates blackhole, room, hall, plate and shimmer. No spring. |
| 375 Hz is the block rate | 48000/128 = 375 exactly, and it moved to 187.5 at `-z 256`. |
| A warm `reboot` wedges the instrument | LEDs on, OLEDs one line, no display, no network; only power removal recovers it. |
| `jackd` works on this hardware | 48000/256/2, 24-bit both directions, all 16 ports, zero xruns. |
| `/hw/cvout/0` is a string in the firmware, not a live address | The whole `/hw/` namespace 404s except `/hw/mute`. |
| A zero-argument message to a setter is inert | `/hw/mute` acked one and the instrument played on. |
| The screen mirror leaked a framebuffer loop per bridge restart | Three found running at once; the sweep took cpu0 from 100% to 12.6%. |
| The screen feed had no liveness detection | 80 seconds after the remote side was killed, the local ssh was still alive with no frames. |
| mmap is 26x faster than read for the framebuffer | 12.8 ms against 331 ms, and a static screen changes zero bytes. |
| The instrument can host its own control surface | Cold-boot verified: `ppid=1`, UI served from USB, scsynth over localhost. |

## Needs qualification

**"The instrument idles at 82%."** That was a 752-ugen graph left over from experiments.
A freshly booted instrument is 496 ugens and **16.6%** at block size 128. The 82%
figure describes a heavy graph, not an idle one.

**"Reverbs straddle the 95% throttle."** True for a *sixth* effect added on top of the
instrument's own rack. The five slots the instrument ships with are already inside
its own budget.

**"Two servers ran, one per core."** The observation is sound — both registered as JACK
clients and server B executed on cpu1. But cpu1 was only free because the audio stack
was stopped for the test. In normal operation that core is taken.

## What this changes going forward

The instrument is not an underused machine waiting for someone to switch on its
second core. It is a complete, tight design with both cores committed and a full
effects rack. The room that exists is in **control and interface**, not in DSP:

* 464 `/p` addresses unmapped, and a compressed firmware table hiding more.
* A routing matrix in `outputRouter` the front panel barely exposes.
* A 832x480 screen and 108 knobs, against a browser with neither limit.
* 148 MB free on the rootfs, against 234 GB of USB.
