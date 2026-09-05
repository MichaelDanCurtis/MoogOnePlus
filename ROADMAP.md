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

### 1. Run patcher builds on the instrument  ← next
Every piece is proven: compile via sclang, `/d_recv`, `/s_new`, `ReplaceOut` as a
master insert, and record-to-verify. The patcher currently emits source to paste.
Wiring **Load** and **Free** into the Patcher tab makes it: build an effect in the
browser, hear it on the Moog. This is the "effect creator" from the first message.

### 2. Panel hotspots
Catalogue and photo both exist. Clicking a knob *in the picture* to select it is
geometry, no hardware, no unknowns.

### 3. Fix the OLED geometry
Documented as wrong rather than quietly shipped. The 192×96 model came from a capture
taken during the screen saver. Needs ten seconds: wake the panel and run
`recon/knob.py --screens-only`.

### 4. A preset browser over `/p`
3,197 parameters per preset, plain text, 398 presets in the factory bank. Vox could
show, diff and search them.

### 5. Decide on `main` and on going public
~90 commits ahead. PR #1 is open against a branch that no longer resembles it.

---

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
