# Moog One Plus — where we are

Last updated 2026-09-05. The two questions this repository was opened to ask are
**both answered**. What follows is what was settled, what is built, what is open, and
what is closed for good so it does not get re-opened.

---

## The questions, answered

### Is the effects noise DSP or converters?

**Neither is broken.** Measured, not inferred.

| measurement | result |
|---|---|
| main output floor, inside `scsynth` | **−112.9 dBFS** |
| `pingpongDelay_0` contribution | **−11 dB** (it attenuates) |
| `et_blackhole_2` contribution | **+0.44 dB** |
| analog output SNR at full level | **≈ 95 dB** |
| loudest component, digital and analog | **375.0 Hz** = `48000/128`, the block rate |

The DSP adds nothing audible and the analog side is respectable. The hiss in the room
is the room: monitoring chain, cable, headphone impedance.

**One real defect found:** the digital path peaks **20.6 dB below full scale** at
maximum volume. Closing it with a makeup gain was built, measured, and **rejected** —
it bought +2.44 dB against a trial-to-trial scatter of 2.5–3.5 dB, because the noise
travels with the signal rather than being added after it.

### Can we write to the voice engine?

**No.** Three protocols, all confirmed *delivered* and all ignored:

| injected | delivered | effect |
|---|---|---|
| note event → 7772 | captured arriving | none |
| `/x` parameter → 7770 | captured arriving | none |
| `/lsleds` → 9100 | captured arriving | none, watched on the panel |

Not the source port — `las-frontend` sends from several ephemeral ports. The likely
gate is the startup cookie (`--cookie=1`, *"Writing startup cookie"*, the `LTRQ`/`LTRS`
exchange on 9501). **Hypothesis, not result.** Testing it needs a capture running
before the instrument powers on.

**The instrument is readable everywhere and writable nowhere** — except the two doors
it genuinely opens: `scsynth` on 57110, and MIDI.

---

## What is built

**Core** — `moogone`
OSC codec · SC client · UDP transport · mock scsynth · WAV/spectrum/noise analysis ·
FX probe harness · pcap dissector · performance decoder · display decoder ·
voice-bus `/x` codec · SynthDef compiler · on-device recorder · analog capture ·
makeup gain · control catalogue (127 panel controls)

**Vox** — the browser workbench, `uv run vox`
FX · Expression · Patch · Surface · Vector · **Panel** (the instrument's real screens,
live) · Patcher · Ask AI · Learn · Presets

**Recon** — `recon/`
`knob.py` (learn a parameter by turning it) · `blink.py` · `midi-probe.py` ·
`capture-voicebus.sh` · `moog-recon.sh`

**Docs**
`MOOG-ONE-INTERNALS.md` (public, ~1,200 lines) · `INTERNAL-DO-NOT-DISTRIBUTE.md`
(gitignored) · this file

1,018 tests. Ruff clean.

---

## Open, in the order I would do them

### ~~1. Run patcher builds on the instrument~~ — DONE 2026-09-05
Run and Free in the Patcher tab. The graph is compiled by a real `sclang`, sent over
`/d_recv` and started at the tail of the root group. Verified end to end: a
ladder-filtered saw with an LFO on its cutoff, built in the browser's own patch
format, generated, compiled, played, and freed.

### ~~Panel hotspots~~ — DONE 2026-09-05
108 knobs detected, all verified on knob caps, each bindable by turning it.



### 2. Fix the OLED geometry
Documented as wrong rather than quietly shipped. The 192×96 model came from a capture
taken during the screen saver. Needs ten seconds: wake the panel and run
`recon/knob.py --screens-only`.

### ~~A preset browser over `/p`~~ — DONE 2026-09-05
398 presets, searchable, with summaries and diffing, from a read-only copy.



### 3. An iPad app — half done

Vox is now installable. It carries a web app manifest, icons and the iOS meta tags, so
**Share -> Add to Home Screen** gives a full-screen app with no browser furniture.
The UI was already touch-first.

What that does *not* give, and what a native app would:

- **Offline.** The bridge runs on the Mac; the iPad is a client. That is not a
  limitation to design away — the bridge needs SSH to the instrument and an SC client,
  neither of which belongs on an iPad.
- **Audio in and out.** A PWA cannot take an audio interface's input. Only matters if
  the iPad should *be* a sound source rather than a control surface.
- **Background MIDI.**

**The honest read: the PWA is the right shape.** A native app would be a rewrite to buy
things this tool does not need. Revisit only if the iPad should generate audio.

### 4. A plugin — VST3, CLAP, AU

Wanted, and worth deciding *what it is* before writing any C++, because the obvious
answer does not work: a plugin **cannot host the analog voices**. Sixteen analog voice
cards are not a thing a DAW can instantiate.

What a plugin could genuinely be, in rising order of effort:

1. **A control surface.** Automate the FX chain, the patcher and the sampler from the
   timeline. Every one of those already speaks OSC over a websocket, so the plugin is a
   thin client — the hard part is already built and tested.
2. **An audio insert.** Send a track through the instrument's effects and back. Needs
   the audio path, which today means the interface and two cables; over USB it might
   need none. See below.
3. **A full instrument.** Play the Moog from the timeline, record its audio, keep the
   patch with the project. This is the one people mean, and it is the sum of the other
   two plus state management.

**CLAP first** — it is the friendliest to write and `clap-wrapper` produces VST3 and AU
from the same source, so it is one implementation rather than three.

**The thing to settle before starting:** whether the plugin talks to the bridge (fast to
build, needs the bridge running) or reimplements it in C++ (self-contained, months).
The first is worth doing; the second needs a reason.

### 5. USB — audio and MIDI over one cable, like a Digitone

**Testable in thirty seconds and not yet tested.** Plug a USB cable from the Mac to the
Moog One's USB-B port and see whether CoreAudio and CoreMIDI list it.

What is already known:

- The instrument's own settings carry `midi_in_ports` and `midi_out_ports`, both set to
  `"b"`, which reads as *both* DIN and USB.
- The i.MX6 already runs a USB **gadget**: `usbint` — the network interface it uses to
  reach the voice controller — is one. So the hardware and kernel support gadget mode;
  the question is only what the external port exposes.
- If it presents a USB audio class device, the interface, both cables and the analog
  round trip all disappear, and the plugin's audio path becomes trivial.

**Do this before any plugin work.** It changes what a plugin has to be.

### 6. Decide on `main` and on going public
~90 commits ahead. PR #1 is open against a branch that no longer resembles it.

---

---

## The interesting direction: external and hybrid sources

Verified 2026-09-05, not speculation.

### The main outs are buses 0 and 7

Not 0 and 1. `Out.ar` writes consecutive buses, so the obvious stereo write lands the
right channel on bus 1, which does not reach the jacks — heard as sound on one side
only, while a meter of buses 0 and 1 shows a balanced pair. Mapped by tone injection,
one bus at a time. Two `Out.ar` calls are needed.

### Audio can be pushed INTO the instrument's engine and played there

A wavetable built on the Mac, `scp`'d to `/tmp`, `/b_allocRead` into a buffer,
`PlayBuf` via a compiled SynthDef, out the main bus — partials at 300/1100/2900 Hz
came back at −22.8/−26.5/−30.6 dBFS against a −120 floor. It goes through the digital
FX chain and out the instrument's own jacks. **No extra hardware.**

### External audio is a mixer source exactly like the oscillators

From the instrument's own namespace:

```
/p/part/t/N/p/mix/ext/g     external input level
/p/part/t/N/p/mix/ext/fa    external -> State Variable Filter
/p/part/t/N/p/mix/ext/fb    external -> Ladder Filter
```

Per timbre, with the same independent filter routing `o1`, `o2`, `o3`, noise and ring
mod get. So anything patched into EXT IN goes through the **analog** ladder, the
envelopes and the VCA — articulated by the keyboard.

### And there are 3 inserts and 2 sends

`inputRouter` carries `insert1_r`..`insert3_r`, `send1Gain`, `send2Gain`;
`outputRouter` carries `insert_1_g`..`insert_3_g`, `sendOneBus`, `sendTwoBus`. SEND 1
and SEND 2 are physical jacks — they show on the meter strip.

### What that makes possible

1. **A sampler inside the synth.** Push samples to buffers; trigger them from the note
   stream on port 7772, which reports every note the instrument plays whatever the
   source. Play the Moog's own keyboard, hear your samples.
2. **Digital source through the analog filters.** Mac or iPad audio into EXT IN, routed
   to `fa`/`fb`, played by the keyboard through the real ladder.
3. **The hybrid loop.** Sample plays inside `scsynth` -> out SEND -> one patch cable ->
   EXT IN -> analog filters -> main out. Digital source, analog filter, one box.

**The limit, stated honestly:** the routing and level controls above are preset
parameters, and preset parameters are not writable from outside (see the closed
section). They have to be set once on the panel. Software supplies the audio; the
instrument supplies the path.

## Rough — works, but not good

**The sampler.** Michael's word was "janky", and that is recorded rather than
explained away, because the specifics were not gathered before moving on. Candidates,
in the order they are worth checking:

- Latency. A note goes keyboard -> voice controller -> port 7772 -> a `tcpdump` over
  SSH -> this Mac -> back over OSC. That round trip has never been measured, and if
  it is tens of milliseconds the instrument will feel like it is answering late.
- It layers rather than replaces, so the analog voice sounds under every sample
  unless the panel is set up for it. Nothing says so in the UI.
- One root note for a whole keyboard means the extremes are badly transposed.
- The `sampler.hit` feed and the panel feed share a socket, and the panel feed is
  chatty.

**Measured, 2026-09-05: median +373 ms, ranging -50 to +717 ms.**

That is the answer, and it is worse than "janky" implies. Not merely late but wildly
inconsistent — a 767 ms spread, which no amount of playing around can adapt to.

Measured by finding the instrument's own voice and the sample in the *same* recording
and taking the difference between their onsets, so the audio stream's start-up
cancels out. An earlier attempt timed from the MIDI send and got 780 ms climbing
monotonically across trials, which is the signature of a measurement artefact rather
than a system.

**The cause is architectural.** A note travels keyboard -> voice controller -> port
7772 -> `tcpdump` -> an SSH pipe -> this Mac -> OSC -> `scsynth`. `-U` makes tcpdump
write per packet, but SSH buffers regardless, and nothing in that chain is scheduled.
This cannot be tightened into a playable instrument from outside the box.

What it means for the feature:

- **Triggering from the instrument's own keyboard is not viable for rhythm.** It is
  usable for pads and drones, where a few hundred milliseconds is texture rather than
  timing, and it should say so rather than pretending.
- **Triggering from MIDI arriving at the Mac has none of this.** BUILT 2026-09-05:
  the Sampler tab has a mode selector, and the MIDI path skips the capture entirely.
  Its latency has not been measured yet — the instrument was off — so it is *expected*
  to be tight rather than *known* to be.
- Running the trigger on the instrument itself would remove the SSH hop, but there is
  no Python on the box and `scsynth` cannot be told to watch a UDP port for us.

## Closed — do not re-open

- **Voice-bus writes.** Delivered and ignored, three ways. Only a boot capture could
  advance it.
- **Panel LED control.** Same.
- **Makeup gain as a noise fix.** Built, measured, rejected on the numbers.
- **The 376.8 Hz mystery.** It is 375.0 Hz, the block rate, at −124 dBFS.

## Blocked

- **MPE adapter.** The instrument responds to CC 7 and CC 32 and nothing else, and
  `midi_mapping/assignments` is `null` with the `midi_map_presets` table empty in both
  the factory and user banks. Needs a MIDI map to exist before expression can route.
- **Per-voice pressure.** Needs voice-bus writes. See above.
