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
- ~~**Whether it is voice allocation, a dropped note-off, or something
  upstream.** MIDI terminates in the XMOS voice controller, which Linux cannot
  observe, so none of this can be traced from the host.~~ **Wrong, and it was
  the sentence that stopped the investigation.** Linux is not *in* the note
  path, but it *observes* it: the voice controller reports every note event and
  a live map of which analog voices are gated, on UDP 7772. See the section
  below.

## The allocator was observable the whole time

The line above — "Linux cannot observe" — was the load-bearing excuse for a week
of inference. It is false. `docs/MOOG-ONE-INTERNALS.md:826` has said since
2026-09-05 that `203.0.113.2:7772` carries the voice controller's own report to
Linux:

    /  ,iifi   4  <note>  <velocity>  0      a note began or ended
    /  ,ii     8  <mask>                     which voices are sounding

`src/moogone/performance.py` already decoded both. Nobody pointed it at this
fault. `tools/voice-probe.py` now does, and it reads two independent axes at
once, which is the whole point:

| mask | audio | reading |
|---|---|---|
| 0 | quiet | healthy |
| 0 | loud | a gated voice the allocator has lost |
| set | loud | the allocator is still holding — no note-off reached it |
| set | quiet | a leaked map entry with no sound |

`las-frontend` holds the wildcard bind on 7772, so there is no socket to share;
the probe captures instead. **Bounded twice** — `-c` caps packets and a kill caps
wall clock, because a `-c` that never fills waits forever and this port is silent
at idle.

### What it shows

Healthy, and this is what release looks like — `EP ONE GEO`, ten notes, ten
clean releases:

    0.000  note  48  ON  vel 100
    0.000     -> mask 0x0001  1 sounding [0]
    1.010  note  48  OFF
    1.010     -> mask 0x0000  0 sounding []

The fault, caught on `BIG BALLAD SPLIT GEO`, five different notes, five for five:

    0.000  note  36  ON  → mask 0x1801  3 sounding [0, 11, 12]
    1.009  note  36  OFF → mask 0x0001  1 sounding [0]
    2.417  note  40  ON  → mask 0x6001  3 sounding [0, 13, 14]
    3.427  note  40  OFF → mask 0x0001  1 sounding [0]
      … voice 0 is never released, and never handed out again

Clearer still on `HARMONIC50 GEO`, where the extra voices arrive **late**:

    0.000  note  48  ON  → mask 0x0008  1 sounding [3]        the note's own voice
    0.104                 → mask 0x000e  3 sounding [1, 2, 3]  two more, 104 ms later
    2.012  note  48  OFF  → mask 0x0006  2 sounding [1, 2]     3 releases; 1 and 2 do not

So the leaked voice is not the one the note took. Something gates additional
voices around the first note after a preset load, and nothing ever gates them off.

### What the leaked voice is, established by measurement

- **Analog, not DSP.** Bus 12 is the ADC return; it reads −33 to −40 dB while the
  voice is held. This is not effect feedback.
- **A held gate, not a long release.** Level is flat for over five minutes —
  sampled across three separate windows, oscillating with modulation between −33
  and −47 dB, with no decay trend. A release decays; this does not.
- **The allocator agrees.** It reports the voice as sounding and correctly
  refuses to reuse it, so the map is not corrupt — the voice really is gated.

### What does not clear it

Both of these were tested against a leaked voice and neither moved the mask:

- CC64/66/123/120 on all sixteen channels. **All-sound-off does nothing.**
- Note-off for the played note on all sixteen channels, and separately every note
  0–127 on channel 1. 128 note-offs, no change.

Loading a preset clears it — the mask goes to `0x0000` and the buses drop to the
floor. On one run an exhaustive 2,080-message panic did not, while the preset
load in the same sequence did.

**This inverts the advice below and the user's own reading of the fault.** A
preset change is not what causes sticking; it is what cures it. It *looks*
causal because the first note played on the newly loaded preset can immediately
leak a fresh voice.

### What is still not established

- **What gates the extra voices.** Presets with a sequencer or arpeggiator timbre
  (`BAD BASS SEQUENCE GEO`, `COLD ARP GEO`) leak reliably; a plain `SINGLE` brass
  patch did not. But no arpeggiator is running while the voice is held — a
  14-second idle capture on 7772 caught **zero** note events against −32 dB of
  audio — so "the arp is still playing" is refuted. Correlation only.
- **Why it is intermittent.** `EP ONE GEO` leaked once under one harness and then
  released cleanly ten times out of ten under another. Presets 0, 1, 5, 6 and 8
  all leaked at least once. Preset 3 also has a run of ten clean releases, and
  whichever preset was loaded before it had five.
  The state that decides this is not yet identified.

## Correction: most of what the section above calls a leak is `voice-limit-mode`

Read the presets before theorising about the allocator. The owner had to say so
twice.

`/p/part/t/N/a/voice-limit-mode` takes `"avail"` or `"fix"`, and `"fix"` with
`a/max-voices N` **permanently reserves N voices for that timbre**. Together with
`a/unison/{en,max-stack}` it fully accounts for the two things the section above
presents as a fault:

- "one note gates three voices" — HARMONICS GEO t1 is `mono`, `unison/en true`,
  `unison/max-stack 2`, `max-voices 2`, `"fix"`, plus one poly voice from t2.
  Three is the designed number.
- "voice 0 is held forever and never handed out again" — BIG BALLAD SPLIT GEO t1
  is `"fix"` with `max-voices 1`. That is the reservation, not a leak.

The underlying error: **the 7772 mask reports allocation, not gating.** Those were
treated as the same thing for an afternoon. A reserved voice is allocated for as
long as the preset is loaded and says nothing about whether it is sounding.

### What is still a real fault

The sound does not stop. Measured across seven presets — load, full panic, one
note, wait 30 s:

| preset | mode | `e1/r` | +30 s |
|---|---|---|---|
| BOLD AS BRASS / EP ONE / FX NOT REQUIRED / BLADERUNNER | `"avail"` | — | quiet, 4/4 |
| ONLY ONE GEO | `"fix"` | 0.000 | quiet |
| HARMONICS GEO | `"fix"` | 0.063, + LFO 3 → VCA | −25.7 dB |
| BIG BALLAD SPLIT GEO | `"fix"` | 0.593 | −47.7 dB |
| ULTIMATE SYNC GEO | `"fix"` | 1.912 | −14.8 dB |

No `"avail"` preset sustained. Only `"fix"` presets did, and among those it tracks
the amp release — zero release goes quiet, everything else rings on. It is not a
release tail: BIG BALLAD held flat for over five minutes and HARMONICS for sixty
seconds, neither trending down.

So `"fix"` is **necessary but not sufficient**, on a sample of seven. It is a
property of the preset, readable before a note is played, which is why the fault
has felt random: **126 of 398** presets in `MOOG ONE.db` and **48 of 129** in the
GEOSYNTHS set have an enabled timbre in `"fix"` mode.

Not established: whether an indefinitely sounding reserved voice is a defect or
Moog's intent for drone patches. The accumulation reported above (mask growing one
per note until priming with a note-off for that same note stops it) is also still
unexplained, and is measured in allocation, so it may be reserved-voice churn
rather than a leak.

## `/api/meter` was lying, and had been for a while

While measuring the above, the meter reported a frozen −82.8 dB on the main pair
while `/api/scan` showed those same buses moving between −37 and −50.

`ensure()` returned early on a `running` flag that nothing ever cleared. Its own
comment claimed it "restarts it if the engine has been restarted underneath us";
it could not. Once the `voxMeter` synth was gone — an engine reset, an `S42sc`
restart, any `/n_free` — the control bus kept its last value and `Read()`
returned it as a live measurement. `/api/scan` was never affected because it
builds its synth per call.

It now asks instead of remembering: `/n_query` on the node, and no `/n_info`
inside 300 ms means re-create, whatever this process believes.

**This is why the earlier reading of "the main output is dead at −120 dB while
buses 8–12 carry signal" should not be trusted.** That was very likely a dead
meter, not a dead audio path.

## What to do when it happens

**Load any preset.** That is the reliable cure, measured: the mask goes to zero
and the buses drop to the floor. The MIDI panic is not reliable against this
fault and was observed failing against it:

    uv run --extra vox python3 tools/midi-panic.py      # try it, but it may do nothing

To see which of the two faults you have, rather than guessing:

    uv run --extra vox python3 tools/voice-probe.py control

If that fails, `/etc/init.d/S42sc restart` clears it — but note it leaves the
instrument silent until a preset is loaded, because `las-frontend` does not
re-push its state to the new engine. Loading any preset restores sound.

Never `/sbin/reboot` this instrument; see `docs/DANGER.md`.
