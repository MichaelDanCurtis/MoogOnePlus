# The sound that would not stop, 2026-09-12

An incident on the instrument, written up because the diagnosis took four
attempts and three of them were wrong. The failure mode worth recording is not
the fault itself — it is how confidently it was misattributed.

## What happened

While testing the Engine tab, the operator reported a note sticking, then that
it was "sustain… but just gets louder and louder", then — after each proposed
fix — that it was unchanged. It stopped when `scsynth` was restarted.

## The sequence, including the wrong turns

| # | theory | action | result |
|---|---|---|---|
| 1 | the reverb just added | freed node 96000 | no change |
| 2 | a latched sustain | MIDI panic, all 16 channels | no change |
| 3 | a long reverb tail | *proposed* lowering the default | **retracted — measured instead** |
| 4 | effects feedback | `/etc/init.d/S42sc restart` | **stopped** |

Theory 3 never shipped. It was about to: the argument was that `room = 0.8`
could read as a note that will not die. Rendering an impulse through the real
UGen gave 2.4 s at that setting, and full decay to numerical silence at *every*
value up to 1.0. The effect was incapable of what it was accused of. See
`tools/measure-reverb-tail.py`.

## What the restart established

`scsynth` came back with `ugens` 726 → 496, `defs` 106 → 105 (proving a genuinely
fresh graph — the Engine's own definition was gone with it), and **cpu1 55% →
19%**. So the sound was inside the SuperCollider effects engine. It was not
notes: MIDI all-sound-off on sixteen channels did not touch it. It was not the
analog voice path, or a fresh DSP graph would not have cleared it.

## The most likely cause, unproven

The instrument runs `las-v1.5.0`, whose library is **126 presets at
`/p/version 10`**. The preset being tested was **version 14**, taken from the
1.8.2 package and imported over USB. `las-frontend` logged
`Imported 1/1 items successfully` and gave no version warning.

A preset format four versions ahead of the firmware reading it, carrying effect
settings into a rack that stops behaving, is the obvious suspect. It is **not
proven**, and it should not be written down as though it were: three other v14
presets were already in that library, though there is no evidence any had been
loaded.

## What changed as a result

- `Preset.Version()`, surfaced through `/api/presets` and `/api/preset`.
- The matrix editor marks any preset ahead of the drive's most common version
  with a warning, and says so again on open.
- This file, so the next person does not re-derive it.

## What did not change

The reverb's defaults. The measurement says they are fine, and changing them
would have been superstition dressed as caution — a fix aimed at a thing that
had already been ruled out by evidence I had in hand.

## The lesson worth keeping

Each wrong theory was reasonable and each was offered with more confidence than
it had earned, because the operator was standing at a synth making a noise and
answers felt more useful than uncertainty. They were not. The thing that
actually settled it was a state change with a measurable before and after, and
the thing that exonerated the reverb was a rendered waveform.

**Every voice on this instrument passes through `scsynth` on its way out**, the
analog ones arriving via the ADC on bus 12. So the signal was observable
throughout, and nothing here observed it. A meter reading the main pair inside
the engine would have answered in one step what four theories could not — and
would have shown immediately whether the level was growing.

That is the piece of tooling this incident argues for, and it does not exist.
