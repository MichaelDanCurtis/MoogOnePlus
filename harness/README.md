# FX noise harness

The decisive experiment for the gain-staging project.

## What it does

Generates **two** recordings from one pasted script, routing everything **through** an FX
SynthDef inside SuperCollider: `clear -> tone -> fx -> recorder`, wired with explicit bus
routing and explicit node ordering (see "Why node order matters" below). The signal never
passes through the ADC.

| File | What it is | What it measures |
|---|---|---|
| `silence_probe_path(out_path)` | **Silence probe** — the FX running with **no tone input** | What the effect adds *on its own*. **This is the one that answers the project's question.** |
| `out_path` | **Tone probe** — the same graph, tone switched on | What the effect does *to signal* |

That the signal never touches the ADC is the entire diagnosis. If a script recorded the bare
tone instead — never actually routing it through the effect — a clean recording would prove
nothing: it would read as "the DSP is quiet" when it had never touched the DSP's effect at all.
`render_probe_script` always emits a real `Synth` for the effect, positioned between the tone
and the recorder in the generated source, not merely named in a comment.

## Why a silence probe, and why it is the important one

A noise floor is measured **in the gaps**. `noise_floor_dbfs` takes a low percentile of
windowed RMS — which only measures noise if some windows contain nothing but noise. On a
continuous test tone there is no gap for the percentile to find: every window contains the
tone, roughly 50 dB above the noise, so the number that comes back is a measurement of the
tone.

This was measured, not theorised. Given two recordings carrying a **true 12 dB noise
improvement**:

| Probe shape | Reported floor delta | Verdict | Truth |
|---|---|---|---|
| Continuous tone (what this harness used to emit) | **+0.000 dB** | **"worse"** | −12 dB |
| Silence probe (noise only) | −12.05 dB | "improved" | −12 dB |
| Tone then silence | −11.98 dB | "improved" | −12 dB |

The project's central question — DSP or converters — came down to float rounding.

`compare_recordings` now **refuses** a recording with no quiet windows rather than returning a
plausible number for it. If you feed it tone probes it raises `ValueError` and tells you to use
the silence probe. To measure what the effect does to signal, which is what a tone probe is
genuinely for, use `snr_db(tone_probe, silence_probe)`.

The silence probe is recorded **first**, before the tone has ever played. A reverb or delay fed
a tone rings for seconds afterwards; a silence capture taken second would measure that tail and
call it the effect's noise floor.

The tone and clear SynthDefs use `ReplaceOut`, not `Out`. SuperCollider zeroes the hardware
output buses every block but **not** private ones, and `Out.ar` mixes into a bus rather than
overwriting it — so a silence probe read off a bus still carrying whatever its index held
before would report someone else's audio as this effect's self-noise. `ReplaceOut` makes "no
tone input" literally true rather than merely intended.

## Why the generated script forks and syncs

`SynthDef.add`, `Buffer.alloc` and `Buffer.write` are all **asynchronous**: they return
immediately and complete on the server later. Pasted into an IDE by hand, human typing latency
hides that. Fed through the `screen` session this harness's own header offers, the blocks race,
and the symptom is `SynthDef not found` for `\moog_probe_tone` — which reads as "the fx defname
is wrong" and sends you hunting in entirely the wrong place.

The generated script therefore wraps its second block in `fork { s.sync; ... }` and syncs again
after allocating the buffers and after opening the files. `s.sync` only works inside a Routine,
which is what `fork` provides.

## Reading the result

| Probe recording | Real playing | Verdict |
|---|---|---|
| Hissy | Hissy | Noise is DSP-side — **fixable** via `/n_set` or `/d_recv` |
| Clean | Hissy | Noise enters at the converters — **hardware ceiling**, project ends in a diagnosis |
| Hissy | Worse | Both contribute; fix what is reachable and accept the rest |

SuperCollider runs 32-bit float internally, putting its quantisation floor near -140 dBFS.
Audible hiss in the probe recording is therefore not "digital resolution" — it is a real
signal-level or algorithm problem, and real problems have fixes.

## Why node order matters

SuperCollider synths execute once per audio block, in their group's node order. A node that
**reads** a bus must run **after** the node that **wrote** it in that same block, or it reads
stale or silent data. Creating the tone, fx, and recorder synths back-to-back with plain
`Synth.new` would *not* guarantee this: `Synth.new`'s default `addAction` is `\addToHead`, which
puts each newly-created synth **ahead** of the ones already running — the opposite of what a
tone → fx → recorder chain needs.

The generated script sidesteps this with explicit chaining: `~fx = Synth.after(~tone, ...)`, then
`~rec = Synth.after(~fx, ...)`. Each line names the node it must run after, directly in the
source — the ordering is evident on read, not something the operator has to reason out from
SuperCollider's default-argument behaviour.

## Generating a probe

```python
from moogone.harness import render_probe_script, silence_probe_path

print(render_probe_script("moog_fx_reverb", "/tmp/probe_before.wav", seconds=5.0))
print(silence_probe_path("/tmp/probe_before.wav"))  # -> /tmp/probe_before-silence.wav
```

Paste the output into the running sclang session. It writes **two** files: the silence probe
first, then the tone probe. Change something, run it again with a different `out_path`, then
`scp` all four WAVs off and:

```python
from moogone.analysis.spectrum import snr_db
from moogone.analysis.wav import load_wav
from moogone.harness import compare_recordings

# The noise-floor question: compare the two SILENCE probes.
result = compare_recordings(
    load_wav("probe_before-silence.wav"),
    load_wav("probe_after-silence.wav"),
)
print(result)

# What the effect does to signal: pair each tone probe with its silence probe.
print("SNR before:", snr_db(load_wav("probe_before.wav"), load_wav("probe_before-silence.wav")))
print("SNR after: ", snr_db(load_wav("probe_after.wav"), load_wav("probe_after-silence.wav")))
```

Feeding tone probes to `compare_recordings` raises `ValueError` rather than returning a number —
see "Why a silence probe" above.

## Reading a comparison

`compare_recordings` reports the unweighted noise-floor delta and the A-weighted (perceptual)
delta side by side, plus three summary fields:

- `floor_improved` — the raw noise floor got quieter.
- `weighted_improved` — the A-weighted figure, which tracks the 2-5 kHz band where hiss actually
  lives, got quieter.
- `verdict` — `"improved"` when both agree it's quieter, `"worse"` when both agree it's louder,
  `"mixed"` when they disagree.

`verdict` is deliberately not a single `improved: bool`. Hiss is a perceptual complaint, and it is
possible for a change to lower the raw noise floor while raising the A-weighted figure — for
example, by shifting energy out of a band nobody hears and into one everybody does. Collapsing
that into one flag from the unweighted number alone can report "improved" for a change that makes
the instrument sound worse. A `"mixed"` verdict is itself the useful answer in that case: it says
look at both deltas, don't trust a single label.

## The things still open

The template carries a single, narrowly-scoped `TODO-ON-HARDWARE` marker, right at the fx
instantiation line. It is structurally complete — a real `Synth.after(...)` call with real bus
routing either side of it — and wrong only in specific, labelled values that cannot be known until
the device is in hand:

1. **The fx SynthDef's real control names.** The template uses `\in`/`\out` as placeholders;
   `moog_fx_reverb` (or whatever the real defname turns out to be) may call its audio ports
   something else entirely, or not expose them as controls at all. The recon `/g_queryTree`
   capture is the source of truth.
2. **Whether a freshly-instantiated fx synth behaves like the one already running in Moog's own
   signal chain.** If the effect depends on a bus wired in by firmware rather than a control
   argument, the fix is to route into the *already-running* node (e.g. via `/n_map` on its real
   node ID) instead of creating a new instance — the query-tree capture settles this too.
3. **The actual bus indices**, if the fix above turns out to be necessary.

Everything else in the file — the SynthDef bodies, the ordering, the cleanup, the comparison
logic — is final.
