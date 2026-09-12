# The stuck note, measured

A night's work on the fault reported as "note sticking … but just gets louder
and louder". It is written up with the wrong turns left in, because three of the
five theories were wrong and the corrections are the useful part.

The instrument was left clean. Nothing here is a fix; it is a characterisation,
and it says plainly where it stops.

## The tooling this needed, which did not exist

Every voice on this machine passes through `scsynth` on its way out — the analog
ones arrive on bus 12 from the ADC — so buses 7 and 0 after everything are the
one place that sees the whole instrument. Two things now read them:

- **`/api/meter`** — level on the main pair, fast and slow envelopes, `rising`.
- **`/api/record`** — the audio itself, to a WAV on the drive.

The meter alone was not enough and the reason is worth keeping: polled over
HTTP it manages about 5 Hz, and at that rate it produced two contradictory
pictures of the same event within ten minutes. Only the recordings settled it.

## What is established, by measurement

**1. A note on this preset has a ~10 second release.** Recorded, not inferred:
floor at −92 dB, note on to −33 dB, smooth decay back to −92 over about ten
seconds. The fundamental is 65 Hz — C2, an octave below the C3 played — with a
clean harmonic series. An ordinary voice with a long release.

**That single fact explains "louder and louder" without any fault at all.** Play
faster than ten seconds a note and they accumulate.

**2. The fault is real and separate from that.** `captures/stuck-notes/repeat.wav`
(local only — `captures/` is gitignored, and 20 MB of WAV does not belong in git)
is 35 seconds: twelve notes over the first seven, then nothing played at all.
The level does not move from about −20 dB for the remaining 27 seconds. The
spectrum at 30 s still contains E2, G2 and C3 — the sub-octaves of the notes
played — so those voices were still sounding half a minute after their
note-offs.

**3. In that state, the ordinary panic messages do not clear it.** CC123 (all
notes off) and CC120 (all sound off), on all sixteen channels, moved the level
from −20 dB to −18 dB. An exhaustive sweep — sustain-off, all-notes-off,
all-sound-off, *and* an explicit note-off for all 128 notes on all 16 channels —
did clear it, reaching the floor about ten seconds later.

**That ten seconds matters.** It is the release time from (1). Anyone who
panics and listens for four seconds will conclude the panic failed. That is
almost certainly what happened earlier in the evening, twice.

**4. From a properly cleared start, the fault does not reproduce.** Bursts of 1,
2, 4, 6, 8, 12 and 16 notes, each preceded by a full clear waited out to the
floor: every one released correctly.

## What I got wrong, and how

**A sweep that measured itself.** An earlier run reported every hold time from
0.05 s to 3.0 s as STUCK, and the note count threshold as "one note". It allowed
two seconds of settle between trials against a ten-second release, so each trial
was reading the previous trial's tail. Re-run with the clear waited out to the
floor, every one of those cases releases. **The reported threshold of "one note"
was an artefact of the measurement, not a property of the instrument.**

**Blaming the newest thing.** The first theory was a reverb added minutes
earlier. Rendering it (`tools/measure-reverb-tail.py`) showed it decays to
numerical silence at every setting.

**Blaming sustain.** CC64=0 on all sixteen channels changed nothing, and CC64=127
changed nothing either. Sustain is not the mechanism.

## Three events, captured and compared

| recording | what it is | length | behaviour |
|---|---|---|---|
| `repeat.wav` | 12 notes played, then nothing | 35 s | held at −20 dB for the last 27 s |
| `spontaneous.wav` | **nobody played anything** | 18 s | held at −29 dB, fell only −2.6 dB |
| `onset-093906.wav` | **nobody played anything** | 91 s | held at −35 dB, no decay at all |

All three are **tonal**, not noise: spectral flatness 0.0000, with every bit of
the energy below 500 Hz. So this is held voices, not a runaway filter or a noise
burst.

**Two of the three happened with nobody at the keyboard**, minutes after the
instrument had been cleared to the floor. `spontaneous.wav` is a clean A2
harmonic series — 109 Hz with partials at 215, 220, 330, 431, 441 — and **no A
had been played**. Every note sent that session was C3, E3, G#3 or C4.

A caution on reading spectra here: picking the loudest FFT bins over a six
second window made the peaks look like they drifted, which suggested noise.
They do not drift; detuned partials beat, and which one is loudest moves. The
flatness measure settled it. The first reading was mine and it was wrong.

## Ruled out by test, not by argument

**The panic itself.** `tools/midi-panic.py` sends 16 channels × (3 CC + 128
note-offs) — over two thousand messages with no pacing — and it went out
immediately before two of the "it's back" reports. The theory was that flooding
the XMOS's MIDI parser produced spurious note-ons. Fired at a quiet instrument:
2096 messages, no sound, floor throughout. **Not the cause.**

**Sound hiding on another output.** The operator reported hearing effects while
a meter on buses 7 and 0 read −86 dB. `/api/scan` now meters the first sixteen
buses at once; with the instrument quiet all sixteen sat between −88 and
−120 dB, so nothing was leaking out of a bus the meter did not watch.

## A measurement error worth knowing about

Every "main output" recording this project made before 2026-09-13 was of the
**wrong pair**. The recorder read `In.ar(bus, 2)` — two consecutive buses — and
the main pair is 7 and 0. It captured main-right and *sub*-right. Fixed in
`ca3e0c4`, along with the network streamer, which had it too and which nobody
had noticed because a stream of the wrong two channels still sounds like a
stream.

## What is not established

- **What puts the instrument into the held state.** It was observed once, from a
  state that had itself not been thoroughly cleared. It did not recur from a
  clean start in seven subsequent attempts.
- **Whether the v14 preset is implicated.** The instrument's library is 126
  presets at `/p/version 10`; a version 14 preset from the 1.8.2 package was
  imported earlier the same evening. The editor now warns about that
  (`74f9425`), but no causal link has been shown.
- **Whether it is voice allocation, a dropped note-off, or something upstream.**
  MIDI terminates in the XMOS voice controller, which Linux cannot observe, so
  none of this can be traced from the host.

## What to do when it happens

Send the full sweep and **wait fifteen seconds before judging it**:

    uv run --extra vox python3 tools/midi-panic.py

If that fails, `/etc/init.d/S42sc restart` clears it — but note it leaves the
instrument silent until a preset is loaded, because `las-frontend` does not
re-push its state to the new engine. Loading any preset restores sound.

Never `/sbin/reboot` this instrument; see `docs/DANGER.md`.
