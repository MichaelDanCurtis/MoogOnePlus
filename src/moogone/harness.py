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

from .analysis.noise import noise_floor_dbfs, peak_dbfs
from .analysis.spectrum import a_weighted_dbfs, peak_bin_power_fraction
from .analysis.wav import Audio

# --- "this recording has no quiet windows" -----------------------------------
#
# noise_floor_dbfs takes a low percentile of windowed RMS. That measures
# the noise only if some windows contain nothing but noise. On a
# continuous tone every window contains the tone, so the number that comes
# back measures the tone -- identically in both recordings, which is how a
# true 12 dB improvement got reported as +0.000 dB and "worse".
#
# There is no way to classify a single recording as "tone probe" vs
# "silence probe" from its temporal statistics: a silence probe is ALSO
# stationary with no gaps -- its "signal" just happens to be the noise we
# want. Any within-recording dynamic-range test rejects the good case
# along with the bad one. What actually separates them is TONALITY, and
# these two constants were chosen from measurement, not intuition:
#
#   peak_bin_power_fraction   a steady sinusoid puts 0.50-0.66 of total
#                             spectral power in one bin (measured across
#                             every tone fixture: 1 kHz and 440 Hz, with
#                             and without added noise). Broadband noise:
#                             0.0004. Band-limited noise: 0.008 (1 kHz
#                             wide) to 0.27 (20 Hz wide). 0.10 sits ~5x
#                             below the tone cases and ~250x above white
#                             noise.
#
#   crest (peak - floor)      a pure sine's crest factor is exactly
#                             3.01 dB; Gaussian noise over a multi-second
#                             capture runs ~13 dB; a tone-then-silence
#                             recording, which HAS gaps and measures
#                             correctly, runs ~54 dB. 10.0 dB sits above
#                             every tone fixture (max 7.97, for a tone
#                             only 11 dB above its own noise) and below
#                             every fixture with real gaps.
#
# Both must indict before the recording is refused, and that conjunction
# is the load-bearing part. Each arm alone has a known false positive:
# uniform quantisation noise has a 4.77 dB crest factor and would trip the
# crest arm; 20 Hz-wide band noise and a tone-then-silence capture both
# trip the tonality arm. Neither trips both. The one fixture that does
# trip both while arguably being legitimate is broadband noise with a
# single spectral line >~15 dB above it -- and this probe records the DSP
# digitally, in-box, never through the ADC, so mains hum cannot get in;
# a dominant tonal line in a digital effect's self-noise would itself be
# the headline finding, worth stopping for rather than averaging over.
#
# Near the threshold the cost of a miss is small by construction: the
# sweep shows the guard stops firing once the tone is within ~6 dB of the
# noise, and at that point the tone no longer swamps the measurement -- a
# real 12 dB improvement still shows up. It fires precisely where the
# tone dominates enough to erase the delta.
_TONAL_PEAK_BIN_FRACTION = 0.10
_MIN_CREST_DB = 10.0

# --- and the pairwise half, which closes what the above cannot ---------------
#
# The single-recording guard has a failure class it structurally cannot see:
# a tone through a MODULATED effect. Chorus, flanger and tremolo are all Moog
# One effects, so this is inside the set being diagnosed, not a hypothetical.
# The sweeping comb notch creates amplitude minima; the 10th-percentile window
# lands in one, tens of dB below the tone; the crest test therefore sees a
# recording that looks like it has quiet windows, and acquits. Measured on a
# true 12 dB improvement, a 1 ms / 0.5 Hz chorus -- the most ordinary chorus
# setting there is -- reported +0.000 dB and verdict "worse", verbatim the
# signature this guard exists for. Deeper and faster settings ARE caught; the
# hole is at slow and shallow.
#
# No single-recording criterion in this family closes it. The evidence is not
# in either recording; it is in the comparison. See _floors_agree_implausibly
# for the measured derivation of both numbers below and for the deliberate
# decision about genuine no-change comparisons.
_PAIRWISE_TONAL_FRACTION = 0.35
_PAIRWISE_MAX_FLOOR_DELTA_DB = 0.10

_TEMPLATE = """// Moog One FX noise probe — generated, do not edit by hand.
//
// ONE paste, TWO recordings, in this order:
//
//   1. {silence_path}
//      SILENCE PROBE -- {defname} running with NO tone input. This is the
//      one that answers the project's question. It measures what the
//      effect ADDS ON ITS OWN, which is what "the noise floor" means.
//      Feed a pair of these (before/after some change) to
//      moogone.harness.compare_recordings.
//
//   2. {out_path}
//      TONE PROBE -- the same graph with the tone switched on. Measures
//      what the effect does TO SIGNAL. Feed it, paired with the silence
//      probe above, to moogone.analysis.spectrum.snr_db.
//
// Why both, and why the silence probe is the important one: a noise floor
// is measured in the GAPS. moogone.analysis.noise.noise_floor_dbfs takes a
// low percentile of windowed RMS, and on a continuous tone there is no gap
// for that percentile to find -- every window contains the tone, which
// sits ~50 dB above the noise, so the number that comes back is a
// measurement of the tone. Measured against recordings carrying a true
// 12 dB noise improvement, a tone-only probe reported the floor delta as
// +0.000 dB and the verdict as "worse". The project's central question
// decided by float rounding. The silence probe has nothing BUT gaps.
//
// Signal path: clear -> tone -> {defname} -> recorder, all inside
// SuperCollider. The tone is generated IN-BOX and routed THROUGH
// {defname} before it is recorded -- the signal never touches the ADC,
// which is what makes this diagnostic decisive (see harness/README.md).
// Hissy probe recording -> noise is DSP-side and fixable. Clean probe
// recording but hissy real playing -> noise enters at the converters, a
// hardware ceiling.
//
// Node order below is EXPLICIT (clear -> Synth.after -> tone ->
// Synth.after -> fx -> Synth.after -> rec), not incidental, because
// SuperCollider synths execute once per audio block in their group's node
// order, and a node that READS a bus must run AFTER the node that WROTE it
// in that same block, or it reads stale or silent data. Creation order
// alone would not guarantee this: Synth.new's default addAction is
// \\addToHead, which puts each newly-created synth AHEAD of the ones
// already running -- the opposite of tone-then-fx-then-record.
// Synth.after(target, ...) sidesteps that default entirely by naming the
// dependency directly.
//
// ReplaceOut, not Out, in the tone and clear SynthDefs: SuperCollider
// zeroes the hardware output buses every block but NOT private ones, and
// Out.ar MIXES into a bus rather than overwriting it. A silence probe
// recorded off a bus still carrying whatever its index held before would
// report someone else's audio as this effect's self-noise -- the exact
// lie a silence probe exists to rule out. ReplaceOut makes "no tone
// input" literally true rather than merely intended.
//
// Paste into the running sclang session, or feed it via the screen session.

(
SynthDef(\\moog_probe_clear, {{ |out = 0|
    ReplaceOut.ar(out, Silent.ar(2));
}}).add;

// amp defaults to 0: the tone synth starts SILENT and is switched on with
// ~tone.set(\\amp, ...) for the second recording. The first recording is
// therefore taken through exactly the same graph, with exactly one thing
// different.
SynthDef(\\moog_probe_tone, {{ |out = 0, freq = {tone_hz}, amp = 0|
    ReplaceOut.ar(out, SinOsc.ar(freq) * amp ! 2);
}}).add;

SynthDef(\\moog_probe_record, {{ |in = 0, bufnum = 0|
    DiskOut.ar(bufnum, In.ar(in, 2));
}}).add;
);

(
// fork + s.sync, not a bare block: SynthDef.add above, and Buffer.alloc and
// Buffer.write below, are all ASYNCHRONOUS -- they return immediately and
// complete on the server later. Pasted into an IDE by hand, human typing
// latency hides that. Fed through the screen session this file's own header
// offers, the blocks race, and the symptom is "SynthDef not found" for
// \\moog_probe_tone, which reads as "the fx defname is wrong" and sends you
// hunting in entirely the wrong place. s.sync only works inside a Routine,
// which is what fork provides.
fork {{
    s.sync;   // block 1's three SynthDef.add calls have landed

    ~toneBus  = Bus.audio(s, 2);   // tone's output -- fx's input
    ~probeBus = Bus.audio(s, 2);   // fx's output -- the signal actually probed
    ~silenceBuf = Buffer.alloc(s, 65536, 2);
    ~toneBuf    = Buffer.alloc(s, 65536, 2);
    s.sync;   // both buffers exist on the server

    ~silenceBuf.write("{silence_path}", "wav", "float", 0, 0, true);
    ~toneBuf.write("{out_path}", "wav", "float", 0, 0, true);
    s.sync;   // both files are open on disk

    ~clear = Synth(\\moog_probe_clear, [\\out, ~probeBus]);
    ~tone  = Synth.after(~clear, \\moog_probe_tone, [\\out, ~toneBus]);

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

    // ---- recording 1: SILENCE PROBE (tone still at amp 0)
    // Taken FIRST, deliberately. A reverb or delay fed a tone keeps ringing
    // for seconds after the tone stops; measuring silence after the tone has
    // played would measure that tail and call it noise.
    ~rec = Synth.after(~fx, \\moog_probe_record, [\\in, ~probeBus, \\bufnum, ~silenceBuf]);
    {seconds}.wait;
    ~rec.free;
    ~silenceBuf.close; ~silenceBuf.free;

    // ---- recording 2: TONE PROBE (same graph, tone switched on)
    ~tone.set(\\amp, {tone_amp});
    ~rec = Synth.after(~fx, \\moog_probe_record, [\\in, ~probeBus, \\bufnum, ~toneBuf]);
    {seconds}.wait;

    ~rec.free; ~fx.free; ~tone.free; ~clear.free;
    ~toneBuf.close; ~toneBuf.free; ~toneBus.free; ~probeBus.free;
    "probes written to {silence_path} (silence) and {out_path} (tone)".postln;
}};
);
"""


def silence_probe_path(out_path: str) -> str:
    """The silence-probe file that render_probe_script(out_path=...) writes
    alongside the tone probe: `-silence` inserted before the extension.

    A function rather than string-munging at each call site, so the Python
    side and the generated sclang can never disagree about where the file
    landed -- render_probe_script uses this to build the script, and the
    caller uses it to find the result.

    >>> silence_probe_path("/tmp/probe.wav")
    '/tmp/probe-silence.wav'
    """
    head, sep, tail = out_path.rpartition("/")
    stem, dot, ext = tail.rpartition(".")
    tail = f"{stem}-silence{dot}{ext}" if dot else f"{tail}-silence"
    return f"{head}{sep}{tail}"


def render_probe_script(
    fx_defname: str,
    out_path: str,
    seconds: float = 5.0,
    tone_hz: float = 1000.0,
    tone_amp: float = 0.5,
) -> str:
    """Generate the sclang source for a noise probe pair, entirely inside
    SuperCollider so the signal never touches the ADC. See the module
    docstring and harness/README.md for why that is what makes the probe
    decisive.

    ONE script, TWO recordings, in this order:

    - `silence_probe_path(out_path)` -- the SILENCE probe: fx_defname
      running with no tone input. This is what measures the effect's own
      noise floor, and it is the recording that answers the project's
      question. compare_recordings takes a pair of these.
    - `out_path` -- the TONE probe: the same graph with the tone switched
      on. Measures what the effect does to signal, not what it adds.
      Pair it with the silence probe through
      moogone.analysis.spectrum.snr_db.

    The signature is unchanged from the tone-only version, and `out_path`
    still names the tone recording, so existing callers keep working and
    keep getting the file they asked for -- they simply also get a silence
    probe next to it.

    Why the tone probe alone was not enough: noise_floor_dbfs measures the
    quiet windows, and a continuous tone leaves none (see its own
    docstring, and compare_recordings below, which now refuses rather than
    returning a number for such a recording).
    """
    return _TEMPLATE.format(
        defname=fx_defname,
        out_path=out_path,
        silence_path=silence_probe_path(out_path),
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


def _continuous_tone_evidence(audio: Audio) -> tuple[float, float] | None:
    """(peak_bin_fraction, crest_db) if this recording is a continuous tone
    with no quiet windows for noise_floor_dbfs to measure; None otherwise.

    Returns the evidence rather than a bare bool so the caller can put the
    actual numbers in its error message -- "refused" without the figures
    that drove the refusal is the sort of message that gets overridden by
    the first person who hits it.
    """
    fraction = peak_bin_power_fraction(audio)
    if fraction <= _TONAL_PEAK_BIN_FRACTION:
        return None
    crest = peak_dbfs(audio) - noise_floor_dbfs(audio)
    if crest >= _MIN_CREST_DB:
        return None
    return fraction, crest


def _require_measurable_floor(audio: Audio, label: str) -> None:
    evidence = _continuous_tone_evidence(audio)
    if evidence is None:
        return
    fraction, crest = evidence
    raise ValueError(
        f"the {label} recording is dominated by a single steady tone, so its "
        f"noise floor cannot be measured and no comparison can be made from it. "
        f"{fraction:.0%} of its spectral power sits in a single FFT bin, and its "
        f"peak is only {crest:.1f} dB above its own floor. noise_floor_dbfs takes "
        f"a low percentile of windowed RMS, which needs windows containing nothing "
        f"but noise; when one component dominates every window, the figure it "
        f"returns measures that component and is IDENTICAL in two recordings whose "
        f"noise differs by 12 dB.\n"
        f"TWO readings fit this evidence, and which one applies decides what to do "
        f"next:\n"
        f"  (a) this is a TONE PROBE. Use the silence probe instead -- "
        f"render_probe_script writes one at silence_probe_path(out_path) alongside "
        f"the tone probe. To measure what the effect does to SIGNAL, which is what "
        f"a tone probe is for, use "
        f"moogone.analysis.spectrum.snr_db(tone_probe, silence_probe).\n"
        f"  (b) this IS the silence probe, and the effect's own noise is dominated "
        f"by a tonal component -- a limit cycle, a denormal artefact, an LFO "
        f"leaking into the audio path. A line only ~5 dB above the broadband floor "
        f"is enough to land here. That is not a mistake to route around: it is a "
        f"finding, and a more specific one than a floor number. Look at "
        f"moogone.analysis.spectrum.spectrum(audio) to see where the line sits. "
        f"noise_floor_dbfs(audio) still returns the floor including that line if "
        f"you want the figure anyway; this refusal is about compare_recordings not "
        f"being able to tell you whether it CHANGED."
    )


def _floors_agree_implausibly(
    before: Audio, after: Audio, floor_delta: float
) -> tuple[float, float] | None:
    """(fraction_before, fraction_after) when two tone-dominated recordings
    report floors that agree to within measurement precision; None otherwise.

    This is the pairwise half of the guard, and it exists because the
    single-recording half cannot close its own failure class. A tone through
    a MODULATED effect -- chorus, flanger, tremolo, all of which are Moog One
    effects, so this is inside the set being diagnosed -- sweeps a comb notch
    across the tone and creates amplitude minima. The 10th-percentile window
    lands in a notch, tens of dB below the tone's own level, so the crest
    test sees a recording that looks like it HAS quiet windows and acquits
    it. Measured on a true 12 dB improvement, a 1 ms / 0.5 Hz chorus (the
    most ordinary chorus setting there is) reported +0.000 dB and verdict
    "worse" -- verbatim the signature this whole guard was written for.

    No single-recording criterion in this family closes it: crest-only also
    acquits the chorus (12.4 dB), and tonality-only falsely refuses pink
    noise, band-limited noise and tone-then-silence. The evidence that
    something is wrong is not in either recording. It is in the COMPARISON:
    every failing case reports |floor_delta| well under 0.1 dB when the true
    answer is -12.

    Two arms, both required:

      floor delta   < 0.1 dB. Below this, no conclusion about improvement is
                    available in either direction: measured run-to-run
                    scatter for a genuine no-change comparison is 0.012 dB
                    (uniform noise) to 0.73 dB (narrow-band noise) at the
                    median, so a delta this small is not "no change
                    detected", it is "this comparison resolves nothing".
                    Above it the direction is at least real.

      tonality      BOTH recordings > 0.35 peak-bin power fraction. This is
                    a WEAKER bar than the single-recording guard needs (which
                    also demands a low crest) and it can afford to be,
                    because it is not deciding alone -- it has the delta as
                    corroboration. Measured: every modulated-effect case that
                    escapes the single-recording guard sits at 0.445-0.577,
                    while white noise is 0.0004, band-limited noise 0.008 to
                    0.291, and pink noise 0.160.

    Deliberate consequence, decided rather than stumbled into: a GENUINE
    no-change comparison of two tone-dominated recordings is also refused.
    That is not a defect of the criterion, it is the criterion being honest.
    When two tonal recordings' floors agree to within a hair, the data
    admits exactly two readings -- "the measurement is blind to the change"
    and "there was no change" -- and nothing in either recording chooses
    between them. Returning a number would assert the second without
    evidence. The message names both, and the cost is asymmetric: "nothing
    changed" is recoverable (the floors are in the message, and
    noise_floor_dbfs still works), while "+0.000 dB, verdict worse" on a
    real 12 dB improvement ends the project on the wrong conclusion.

    Measured false-refusal rate over 100 independent no-change seed pairs
    per fixture: 0/100 for white noise, pink noise, uniform quantisation
    noise, and 20 Hz-and-wider band noise. For bands narrower than that it
    is a low single-digit percentage that moves with the seed set -- three
    independent measurements of the same fixtures got 4%, 6% and 2% for a
    10 Hz-wide band and 8%, 4% and 4% for a 2 Hz-wide one, so quoting one
    figure would be over-precise. Those bands are a tone with a wobble,
    which is the case this is meant to be suspicious of. Tone-then-silence
    is refused 100/100 -- the accepted consequence above.

    Note this rate applies only to genuine NO-CHANGE pairs. Every one of
    these fixtures carrying a real 12 dB improvement still measures
    -12.000: what a refusal costs here is the ability to be told "nothing
    changed", not the ability to measure something that did.
    """
    if abs(floor_delta) >= _PAIRWISE_MAX_FLOOR_DELTA_DB:
        return None
    fraction_before = peak_bin_power_fraction(before)
    fraction_after = peak_bin_power_fraction(after)
    # BOTH must look tonal. One tonal and one not is a mismatched pair, and
    # its delta would not be near zero anyway -- requiring both is the
    # conservative direction for a guard whose false positives cost the
    # operator a measurement they cannot retake.
    if min(fraction_before, fraction_after) <= _PAIRWISE_TONAL_FRACTION:
        return None
    return fraction_before, fraction_after


def _require_a_comparison_that_resolves_something(
    before: Audio, after: Audio, floor_delta: float
) -> None:
    evidence = _floors_agree_implausibly(before, after, floor_delta)
    if evidence is None:
        return
    fraction_before, fraction_after = evidence
    raise ValueError(
        f"this comparison resolves nothing: both recordings are tone-dominated "
        f"({fraction_before:.0%} and {fraction_after:.0%} of spectral power in a "
        f"single FFT bin) and their noise floors agree to {abs(floor_delta):.4f} dB "
        f"-- below the run-to-run scatter of a real noise-floor measurement, so the "
        f"sign of that delta is decided by rounding rather than by anything that "
        f"happened.\n"
        f"TWO readings fit this evidence and nothing in the recordings chooses "
        f"between them:\n"
        f"  (a) the floors are measuring the TONE, not the noise, so the "
        f"measurement is blind to any change at all. A tone through a modulated "
        f"effect -- chorus, flanger, tremolo -- produces exactly this: the sweeping "
        f"notch creates amplitude minima, the low percentile lands in one, and the "
        f"result is identical in both recordings however much their noise differs. "
        f"Measured on a TRUE 12 dB improvement, a 1 ms / 0.5 Hz chorus reports "
        f"+0.000 dB. If these are tone probes, this is what happened: use the "
        f"silence probes instead (silence_probe_path(out_path)).\n"
        f"  (b) these are silence probes and genuinely nothing changed. Possible, "
        f"and this refusal cannot rule it out -- but it cannot confirm it either, "
        f"which is why it is not reported as a result. The floors are "
        f"{noise_floor_dbfs(before):.2f} and {noise_floor_dbfs(after):.2f} dBFS if "
        f"you want them; call noise_floor_dbfs directly to work with the numbers "
        f"without this check."
    )


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

    Raises ValueError, BEFORE measuring anything, if either recording has
    no quiet windows -- i.e. is a continuous tone rather than a noise-floor
    capture. This is not a stylistic preference for strictness: fed the
    tone probe this harness used to be the only generator of, on
    recordings carrying a true 12 dB noise improvement, this function
    returned floor_delta_db = +0.000 dB and verdict = "worse". The tone
    sits ~50 dB above the noise in every window, so both metrics measured
    the tone, and the verdict came down to float rounding -- on the
    question the whole project exists to answer. A measurement that cannot
    be made has to fail loudly rather than produce a plausible number.
    Use the SILENCE probe (render_probe_script writes one at
    silence_probe_path(out_path)); for what the effect does to SIGNAL, use
    moogone.analysis.spectrum.snr_db(tone_probe, silence_probe).

    Also raises ValueError on a sample-rate mismatch (checked here -- this
    is a pairwise property of comparing two recordings, not something
    either recording's own validation could catch on its own) or,
    inherited from noise_floor_dbfs/a_weighted_dbfs (both call
    validate_audio before doing anything else), on zero-length or
    non-finite input in either recording.
    Confirmed by test that this inherited protection actually reaches
    through compare_recordings, not assumed from those functions' own
    tests -- see test_compare_recordings_raises_on_zero_length_audio and
    test_compare_recordings_raises_on_non_finite_samples.
    """
    if before.sample_rate != after.sample_rate:
        raise ValueError(f"sample rate mismatch: {before.sample_rate} vs {after.sample_rate}")
    # Refuse before measuring, not after. A measurement that cannot be made
    # must fail loudly rather than produce a plausible number -- see this
    # function's docstring, and the eleven documented instances in this
    # project's ledger of a green result that was measuring the wrong thing.
    _require_measurable_floor(before, "`before`")
    _require_measurable_floor(after, "`after`")
    floor_before = noise_floor_dbfs(before)
    floor_after = noise_floor_dbfs(after)
    floor_delta = floor_after - floor_before
    # The pairwise half of the guard, and the only one that can see a tone
    # through a MODULATED effect -- the notch minima make each recording look
    # individually measurable, and only the comparison betrays that neither
    # floor moved when it should have moved 12 dB. Runs before the weighted
    # figures, which cost a second pair of FFTs and are not worth computing
    # for a comparison that is about to be refused.
    _require_a_comparison_that_resolves_something(before, after, floor_delta)

    weighted_before = a_weighted_dbfs(before)
    weighted_after = a_weighted_dbfs(after)
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
