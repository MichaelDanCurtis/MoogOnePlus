# Moog One — FX Gain-Staging Diagnostic

**Date:** 2026-08-10
**Status:** Approved, blocked on Foundation and on hardware
**Depends on:** [Foundation](2026-08-10-moog-one-foundation-design.md)

## The problem

The Moog One's onboard effects raise the noise floor. Audible hiss appears with effects
engaged and **scales with the wet amount**. Moog acknowledged gain-staging issues in the FX
section.

That symptom — hiss proportional to wet — narrows the cause to three candidates, and they are
not equally tractable:

| # | Cause | Fixable? |
|---|---|---|
| 1 | Signal arrives at the DSP too low, is processed near the floor, made up after | Yes — `/n_set` |
| 2 | Engaging FX inserts an ADC→DAC round trip through a mediocre codec | **No.** Hardware ceiling. |
| 3 | The SynthDef's own internal gain structure raises the floor | Yes — `/d_recv` |

Cause 2 ends the project. It should be ruled in or out before any effort goes into a fix.

## The decisive test

**Generate a test tone inside SuperCollider, feed it directly to the FX SynthDef, record the
output to a file on the box.**

That path never touches the ADC. It is the entire diagnosis:

- **Tone comes back hissy** → noise originates in the DSP domain → cause 1 or 3 → fixable
- **Tone comes back clean, but real signal is hissy** → noise enters at the converters →
  cause 2 → hardware ceiling
- **Both hissy, analog worse** → both contributing; fix what is reachable, accept the rest

SuperCollider runs 32-bit float internally, putting its quantization floor near −140 dBFS.
Audible hiss in the in-box recording is therefore **not** "digital resolution" — it is a real
signal-level or algorithm problem, and real problems have fixes.

This test needs no audio interface and no analog measurement. It runs entirely on the device.

## Sequence

**Phase 1 — Diagnose.**
Run the harness. Analyze with the measurement rig. Determine which cause is in play. If the
answer is cause 2, write up the finding and stop; the remaining phases are moot.

**Phase 2 — Find the handles.**
`/g_queryTree` to enumerate the FX chain's live controls. Identify anything resembling input
trim, output gain, dry/wet balance, or internal scaling.

**Phase 3 — Sweep and measure.**
For each candidate control, sweep across its range, measuring noise floor and SNR at each
step. This produces a curve rather than a guess, and the optimum is read off it. Watch for
the trade: raising input trim improves SNR until it starts clipping, and the best setting is
the knee, not the extreme.

**Phase 4 — Escalate if needed.**
If the reachable controls cannot recover enough SNR, read the existing SynthDef structure and
author a replacement with corrected internal gain staging, loaded via `/d_recv`.

`/d_recv` sends a synth definition to a running server. It is the documented, intended
mechanism SuperCollider provides for exactly this. It is runtime data, not firmware — nothing
signed is touched and nothing persists across a reboot unless we deliberately arrange it.

## Persistence

If loading a preset rebuilds the node graph, `/n_set` changes are wiped on every preset
change, which would make a parameter-level fix useless in practice.

Test this early — in Phase 2, not Phase 4. Query the tree, change a preset, query again, and
compare node IDs. If the graph is rebuilt, that pushes the solution toward `/d_recv` (where
the corrected gain structure lives inside the definition itself) or toward re-applying
settings on each preset change.

## Deliverables

One of:

- **A fix**, with before/after noise floor and SNR figures from the measurement rig, and a
  documented procedure for re-applying it.
- **A diagnosis** that the noise is converter-side and unreachable from software, with the
  measurements that establish it.

Both are worth having. Only the first is worth further work, and the test in Phase 1 tells us
which we have on day one.

## Explicitly out of scope

**Downward expansion or gating on the wet path.** It is the reflexive fix for hiss and it is
wrong here: expansion on reverb tails is where gating artifacts are most audible. It would
trade a constant hiss for breathing tails, which is a worse problem presented as a solution.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Noise is converter-side | Project delivers diagnosis, not fix | Accepted, and detected on day one |
| SynthDefs are compiled `.scsyndef` with no source | Phase 4 is harder | `/g_queryTree` still exposes control names; we lose internals, not handles |
| Preset load rebuilds the node graph | Parameter fix does not persist | Tested in Phase 2; pushes toward `/d_recv` |
| No writable location for recordings | Harness cannot capture | Recon reports free space; fall back to thumbdrive |
| Test tone cannot be routed to the FX input bus | Blocks the decisive test | Recon captures the bus layout; fallback is `/dumpOSC` observation of the real signal path |
