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

### 5. USB — tested 2026-09-05. MIDI only, and one switch stands in the way. ✅/⚠️

**Answered.** It is not a Digitone. The USB socket presents **MIDI and nothing else**:
`0x2662:0x000d`, one MIDIStreaming interface with a bulk IN and a bulk OUT endpoint,
and **no AudioStreaming interface at all**. No audio device appears on the Mac because
there is none to appear. Full descriptors and method in `docs/MOOG-ONE-INTERNALS.md` §8a.

Three things came out of it that change what happens next:

**MIDI in works and costs nothing.** Notes sent over USB drive the voice engine — a
+67.8 dB rise against the noise floor — and arrive on port 7772 as the ordinary
opcode-4 performance messages, the same ones the instrument's own keyboard writes.
No DIN cable, no interface. The `keys`/`midi` sampler plumbing already reads them.

**MIDI out is switched off, per preset, in all 398 factory presets.** Not a hardware
limit: the IN endpoint exists. The gate is `/p/part/t/{1,2,3}/in/midi_out/en`, which is
`False` everywhere, with `usb0/en` true in only 13 presets (`INIT` among them) and
useless while the master is off. The earlier note here — that `midi_out_ports = "b"`
meant MIDI out was already on — was wrong; `"b"` picks the ports, it does not enable
them. **This switch was deliberately left alone**: it lives in the preset and saves
with the sound, so flipping it changes stored patches.

**Turning it on is the single highest-value change to the instrument's settings.**
The sampler's `keys` mode watches the keyboard by SSH-tcpdumping 7772 at a measured
**+373 ms**. With MIDI out enabled those notes arrive over USB in about a millisecond
and `midi` mode replaces `keys` outright. That is the janky-latency fix, and it costs
one setting rather than any code.

> **Confirmed working, 2026-09-06.** MIDI Out was enabled on the instrument and the
> keyboard played: 44 note events reached the host over USB and every note-on
> triggered a sample, with no capture anywhere in the path. `recon/sampler-midi.py`
> is the one-command version. The SSH-tcpdump `keys` mode is now the fallback
> rather than the only option.

**The second configuration is a duplicate, not a hidden audio mode.** The device
declares two; both descriptors are byte-identical, 143 bytes, both carrying
`bConfigurationValue = 1` — so there is nothing to switch into even in principle.
libusb on macOS could not answer this: it returns the *active* configuration for every
index, which only shows itself when you ask for index 4 and get data instead of an
error. `recon/usb-configs.c` reads them through IOUSBLib, which indexes properly and
needs no device open, so `MIDIServer` keeps its claim and MIDI is never interrupted.

**What this means for the plugin:** audio does not come over USB. But it does come over
the network — see below, which changes the answer.

### 5a. Audio over the network — works, 22.9 ms ✅

`scsynth` owns the sound card exclusively, so ALSA is closed. It does not matter:
scsynth writes a raw float stream into a FIFO and `nc` pushes it at a TCP socket, with
no SSH in the audio path. **5.03 s of stereo audio in 5 s of wall clock**, the loudest
component at 375.0 Hz — the block-rate tone, confirming it is genuinely the output bus.

The `DiskOut` ring buffer is the latency and the usual size is the wrong one: 65536
frames costs 372 ms, 2048 frames costs 22 ms.

This is also the trustworthy way to time a trigger, and it closes the measurement that
an audio interface could not settle — both ends are this machine's clock and the answer
is a byte offset in a stream:

```
trigger -> sound on the instrument : median  22.9 ms   spread  9.8 ms
trigger -> bytes on this machine   : median  21.4 ms   spread 11.2 ms
```

Against `keys` mode's +373 ms and 767 ms spread, that is about sixteen times faster.
`recon/net-audio.py` is the one-command version.

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

> Note added later the same day: part of that spread was a bug, not the
> architecture. Triggering the sampler drew `/fail` from `/n_free` for one-shots
> that had already ended, and the client blamed those on the next request —
> measured as a delay falling 953, 757, 603, 533, 389 ms across five triggers as
> the backlog drained. Both are fixed. The SSH capture path is still the dominant
> cost in `keys` mode and the conclusion stands, but the number deserves
> re-measuring now that the poisoning is gone.

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
