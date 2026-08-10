# Moog One — Per-Voice Pressure

**Date:** 2026-08-10
**Status:** Approved, blocked on Foundation and on hardware
**Depends on:** [Foundation](2026-08-10-moog-one-foundation-design.md)

## The idea

Route per-key polyphonic aftertouch from a Native Instruments Komplete Kontrol S88 MK3 to
per-voice analog parameters on the Moog One, giving a 16-voice analog polysynth per-note
pressure expression that Moog never shipped.

### What each side brings

**The S88 MK3 is fully capable.** Fatar hammer-action keybed with true polyphonic aftertouch,
MPE output, MIDI 2.0 — the first widely available weighted keybed with per-key pressure. The
controller side requires nothing from us.

**The Moog One does not do this.** No per-voice aftertouch. MPE was named on the roadmap at
launch and never shipped. So this is not a rebuild of something that already exists.

### On naming

What this delivers is **per-note pressure**, not full MPE. MPE's other two dimensions —
per-note pitch bend and per-note timbre — have no physical control surface on a hammer-action
keybed. Pressure is the dimension the hardware provides, and it is the one worth having.

Poly aftertouch (MIDI `0xA0`, note number + pressure on one channel) is if anything a cleaner
input format for this purpose than MPE's channel-spread encoding, because it is already keyed
by note number. Either input mode works; the translator can accept both.

## Why the community's objection does not apply

Moog One owners have concluded this is infeasible, on the grounds that *"the mod matrix would
have to support up to sixteen values that affect sixteen destinations differently — a large
rewrite of the code."*

That objection is about **Moog implementing it in the front-panel mod matrix.** This approach
does not go through the mod matrix. It addresses the voice cards directly over OSC and
bypasses the front panel entirely. The stated blocker is an argument about the UI layer, and
it does not constrain us.

There is also a structural argument in favor. **The Moog One already performs per-voice
modulation** — every voice runs its own envelopes and LFOs against its own analog hardware.
That is what makes it sixteen independent analog voices rather than sixteen copies of one. So
an internal path for "set voice N's parameter to value X" necessarily exists. The open
question is not whether the hardware can do it, but whether that path is reachable from the
OSC bus.

## Go/no-go

**Hold one note. Send OSC to move that one voice's filter cutoff.**

If exactly one voice in a held chord changes timbre, the thesis is proven and everything
after it is engineering. If nothing moves, the project is dead and it cost one message to
find out.

This runs the same day access is established, before any other work on this spec. It is the
whole project compressed into a single experiment, and its cost is close to zero.

## Sequence

**Phase 1 — Recon answers.**
From the Foundation recon bundle: are voice cards individually addressable over OSC, and is
the note→voice assignment observable? The `/dumpOSC` capture taken while playing is the
primary evidence.

**Phase 2 — Go/no-go.** As above.

**Phase 3 — Note→voice tracking.**
To send pressure to the right voice, we must know which voice is playing which note. Two
routes:

- *Observe* — watch Moog's own allocator via `/dumpOSC` and mirror its decisions. Less
  invasive; depends on assignments being visible on the bus.
- *Take over* — assign notes to voices ourselves, sending note-on directly to a chosen voice.
  More invasive and more work, but makes the mapping trivially known because we authored it.

Prefer observation. Fall back to taking over allocation only if assignments are not visible.

**Phase 4 — The translator.**
ALSA MIDI in → poly-AT decode → per-voice OSC out, **running on the Moog One itself.**

**Phase 5 — Latency and jitter.**
Measure end to end. Tune update rate, add smoothing if the OSC path proves control-rate
limited, and set a sane pressure→parameter curve.

## Why it runs on the box

Streaming continuous gesture data for up to sixteen voices through an SSH tunnel is the wrong
shape. `ssh -L` forwards TCP, which adds head-of-line blocking and jitter to data whose whole
value is being smooth and immediate.

Running on the device removes the network from the performance path entirely:

```
S88 ──USB──▶ Moog One USB host ──▶ ALSA MIDI ──▶ translator ──▶ OSC ──▶ localhost:9300
```

The box is ARMv7 with an ordinary Linux userland, so this is well within reach. The tunnel
remains useful for development and for the FX work — just not for live gesture data.

### Input path fallbacks

| Path | Bandwidth | Note |
|---|---|---|
| S88 → USB host on the Moog One | Ample | Preferred. Recon checks whether class-compliant MIDI enumerates. |
| S88 → DIN MIDI in | Tight | 31250 baud. Poly AT across many held voices at a high update rate competes with note data; workable with rate limiting. |
| S88 → Mac → network → Moog One | Ample | Reintroduces the latency this design exists to avoid. Last resort. |

## Persistence

The translator is a userspace process, not a firmware change. It does not survive a reboot
unless deliberately arranged.

Default to **ephemeral** — start it when you want it. Persisting it means touching init,
which crosses from "running a program on a computer I own" into modifying system
configuration, and that decision should be made deliberately after the thing works, not
assumed now.

## Deliverable

Per-note pressure expression on a 16-voice analog polysynth, playable from the S88, with
measured end-to-end latency.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| **Voice cards not individually addressable over OSC** | **Project dead** | Go/no-go on day one, before any other work |
| Note→voice assignment not observable | Phase 3 harder | Fall back to taking over allocation |
| USB host will not enumerate the S88 | Ergonomics | DIN fallback with rate limiting, or Mac-in-the-middle |
| OSC path to voice cards is control-rate limited | Pressure feels steppy | Measure in Phase 5; add smoothing, reduce update rate |
| Per-voice writes fight Moog's own modulation engine | Values jump or are overwritten | Characterize in Phase 2; may require choosing destinations Moog is not actively driving |
| Latency too high even on-box | Feels disconnected from the keys | Measured in Phase 5; informs whether the result is performable or a curiosity |

## Sources

- [Kontrol S-Series MK3 — Native Instruments](https://www.native-instruments.com/en/products/komplete/keyboards/kontrol-s49-s61-s88/)
- [Moog One — Initial Findings](https://www.ryanzachry.com/2021/09/07/moog-one-initial-findings.html)
- [Moog One owners' discussion, Gearspace](https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/1236885-moog-one-owners-discussion-199.html)
