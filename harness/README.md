# FX noise harness

The decisive experiment for the gain-staging project.

## What it does

Generates a test tone inside SuperCollider and routes it **through** an FX SynthDef before
recording the result to a file on the Moog One: `tone -> fx -> recorder`, all three stages
wired together with explicit bus routing and explicit node ordering (see "Why node order
matters" below). The signal never passes through the ADC.

That last sentence is the entire diagnosis. If a script recorded the bare tone instead — never
actually routing it through the effect — a clean recording would prove nothing: it would read as
"the DSP is quiet" when it had never touched the DSP's effect at all. `render_probe_script`
always emits a real `Synth` for the effect, positioned between the tone and the recorder in the
generated source, not merely named in a comment.

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
from moogone.harness import render_probe_script

print(render_probe_script("moog_fx_reverb", "/tmp/probe_before.wav", seconds=5.0))
```

Paste the output into the running sclang session. Then `scp` the WAV off and:

```python
from moogone.analysis.wav import load_wav
from moogone.harness import compare_recordings

result = compare_recordings(load_wav("probe_before.wav"), load_wav("probe_after.wav"))
print(result)
```

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
