"""FX noise probe: script generation and before/after comparison.

The decisive experiment. A tone generated inside SuperCollider is routed
THROUGH the FX SynthDef and recorded on-box, so the signal never passes
through the ADC. If that recording is hissy the noise is DSP-side and
reachable from software; if it is clean while real playing is hissy, the
noise enters at the converters and no amount of OSC will fix it.

That only holds if the FX genuinely sits in the signal path -- a probe that
records the bare tone still produces a clean recording, and a clean
recording reads as "the DSP is quiet," a false negative that would end the
project on the wrong conclusion. See render_probe_script's docstring and
harness/README.md for how the generated script guarantees that.
"""

from dataclasses import dataclass
from typing import Literal

from .analysis.noise import noise_floor_dbfs
from .analysis.spectrum import a_weighted_dbfs
from .analysis.wav import Audio

_TEMPLATE = """// Moog One FX noise probe — generated, do not edit by hand.
//
// Signal path: tone -> {defname} -> recorder, all inside SuperCollider.
// The tone is generated IN-BOX and routed THROUGH {defname} before it is
// recorded -- the signal never touches the ADC, which is what makes this
// diagnostic decisive (see harness/README.md). Hissy probe recording ->
// noise is DSP-side and fixable. Clean probe recording but hissy real
// playing -> noise enters at the converters, a hardware ceiling.
//
// Node order below is EXPLICIT (tone -> Synth.after -> fx -> Synth.after ->
// rec), not incidental, because SuperCollider synths execute once per audio
// block in their group's node order, and a node that READS a bus must run
// AFTER the node that WROTE it in that same block, or it reads stale or
// silent data. Creation order alone would not guarantee this: Synth.new's
// default addAction is \\addToHead, which puts each newly-created synth
// AHEAD of the ones already running -- the opposite of tone-then-fx-then-
// record. Synth.after(target, ...) sidesteps that default entirely by
// naming the dependency directly.
//
// Paste into the running sclang session, or feed it via the screen session.

(
SynthDef(\\moog_probe_tone, {{ |out = 0, freq = {tone_hz}, amp = {tone_amp}|
    Out.ar(out, SinOsc.ar(freq) * amp ! 2);
}}).add;

SynthDef(\\moog_probe_record, {{ |in = 0, bufnum = 0|
    DiskOut.ar(bufnum, In.ar(in, 2));
}}).add;
);

(
~toneBus  = Bus.audio(s, 2);   // tone's output -- fx's input
~probeBus = Bus.audio(s, 2);   // fx's output -- the signal actually probed
~buf = Buffer.alloc(s, 65536, 2);
~buf.write("{out_path}", "wav", "float", 0, 0, true);

~tone = Synth(\\moog_probe_tone, [\\out, ~toneBus]);

// TODO-ON-HARDWARE: this fx instantiation is complete in structure and
// wrong only in these specific, narrow values -- fill them in from the
// recon /g_queryTree capture, nothing else in this file should need to
// change:
//   1. \\in / \\out below are PLACEHOLDER control names. {defname} may not
//      call its audio ports "in"/"out" at all -- use its real control
//      names from the query-tree capture.
//   2. Confirm a freshly-instantiated {defname} behaves like the instance
//      already running in Moog's own signal chain. If the effect depends
//      on a fixed bus wired in by firmware rather than a control arg,
//      delete this instantiation and route ~toneBus into the ALREADY
//      RUNNING node's real node ID instead (e.g. via /n_map).
~fx = Synth.after(~tone, \\{defname}, [\\in, ~toneBus, \\out, ~probeBus]);

~rec  = Synth.after(~fx, \\moog_probe_record, [\\in, ~probeBus, \\bufnum, ~buf]);

{{
    {seconds}.wait;
    ~rec.free; ~fx.free; ~tone.free;
    ~buf.close; ~buf.free; ~toneBus.free; ~probeBus.free;
    "probe written to {out_path}".postln;
}}.fork;
);
"""


def render_probe_script(
    fx_defname: str,
    out_path: str,
    seconds: float = 5.0,
    tone_hz: float = 1000.0,
    tone_amp: float = 0.5,
) -> str:
    """Generate the sclang source for one noise probe: tone -> fx_defname ->
    recorder, entirely inside SuperCollider so the signal never touches the
    ADC. See the module docstring and harness/README.md for why that is
    what makes the probe decisive.
    """
    return _TEMPLATE.format(
        defname=fx_defname,
        out_path=out_path,
        seconds=seconds,
        tone_hz=tone_hz,
        tone_amp=tone_amp,
    )


@dataclass
class NoiseComparison:
    """floor_improved / weighted_improved are the two independent, honest
    observations. verdict is "improved" iff both are True, "worse" iff
    neither is, and "mixed" when they disagree -- see compare_recordings's
    docstring for why a single "improved: bool" cannot stand in for this.
    """

    floor_before_dbfs: float
    floor_after_dbfs: float
    floor_delta_db: float
    weighted_before_dbfs: float
    weighted_after_dbfs: float
    weighted_delta_db: float
    floor_improved: bool
    weighted_improved: bool
    verdict: Literal["improved", "worse", "mixed"]


def compare_recordings(before: Audio, after: Audio) -> NoiseComparison:
    """Compare two probe recordings. Negative deltas mean quieter, i.e. better.

    Both weighted and unweighted figures are reported: the unweighted number
    is the honest physical measurement, the A-weighted one tracks what you
    actually hear.

    `verdict` replaces a single `improved: bool`. Collapsing floor_delta_db
    and weighted_delta_db into one flag from floor_delta_db alone (the
    brief's original definition) can report "improved" for a change that
    makes the instrument sound WORSE: hiss is a perceptual complaint, and
    it is entirely possible for the raw noise floor to drop while the
    A-weighted figure -- the one that tracks the 2-5 kHz band where hiss
    actually lives -- rises, e.g. because whatever changed shifted energy
    out of an inaudible band and into an audible one. `floor_improved` and
    `weighted_improved` are reported individually so neither number is
    hidden behind the other; `verdict` is "improved"/"worse" only when they
    agree, and "mixed" -- not a guess in either direction -- when they do
    not. A "mixed" verdict is itself informative: it means the two figures
    are telling different stories and a human needs to look at both deltas,
    not just the summary label.

    Raises ValueError on a sample-rate mismatch (checked here -- this is a
    pairwise property of comparing two recordings, not something either
    recording's own validation could catch on its own) or, inherited from
    noise_floor_dbfs/a_weighted_dbfs (both call validate_audio before doing
    anything else), on zero-length or non-finite input in either recording.
    Confirmed by test that this inherited protection actually reaches
    through compare_recordings, not assumed from those functions' own
    tests -- see test_compare_recordings_raises_on_zero_length_audio and
    test_compare_recordings_raises_on_non_finite_samples.
    """
    if before.sample_rate != after.sample_rate:
        raise ValueError(
            f"sample rate mismatch: {before.sample_rate} vs {after.sample_rate}"
        )
    floor_before = noise_floor_dbfs(before)
    floor_after = noise_floor_dbfs(after)
    weighted_before = a_weighted_dbfs(before)
    weighted_after = a_weighted_dbfs(after)

    floor_delta = floor_after - floor_before
    weighted_delta = weighted_after - weighted_before
    # bool(...): the dbfs helpers return numpy float64 scalars, so a bare
    # `floor_delta < 0` is a numpy bool_, not a Python bool -- it satisfies
    # `==` and truthiness checks fine, but fails `is True`/`is False`
    # identity checks and dataclasses.asdict()-then-json.dumps() (numpy
    # bool_ is not JSON serialisable). NoiseComparison's fields are typed
    # `bool`; make them actually be that.
    floor_improved = bool(floor_delta < 0)
    weighted_improved = bool(weighted_delta < 0)

    verdict: Literal["improved", "worse", "mixed"]
    if floor_improved and weighted_improved:
        verdict = "improved"
    elif not floor_improved and not weighted_improved:
        verdict = "worse"
    else:
        verdict = "mixed"

    return NoiseComparison(
        floor_before_dbfs=floor_before,
        floor_after_dbfs=floor_after,
        floor_delta_db=floor_delta,
        weighted_before_dbfs=weighted_before,
        weighted_after_dbfs=weighted_after,
        weighted_delta_db=weighted_delta,
        floor_improved=floor_improved,
        weighted_improved=weighted_improved,
        verdict=verdict,
    )
