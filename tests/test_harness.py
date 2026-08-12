"""Tests for the SuperCollider FX noise probe harness.

Everything downstream of this task depends on one fact being true: the
generated sclang script must actually route the tone THROUGH the FX
SynthDef before recording it. A probe that records the bare tone still
produces a clean, plausible-looking recording -- and a clean recording is
read as "the DSP is quiet, the noise must be the converters," which ends
the whole project on a false negative. The brief's own template had this
exact defect (the FX SynthDef was never instantiated -- {defname} appeared
only inside a comment), and the brief's own test (`"moog_fx_reverb" in
src`) could not catch it, because a comment mention satisfies a raw
substring check just as well as real code does.

So the tests here are split, and each is labelled, into:

- MENTION: a raw substring/regex check on the full generated text. Cheap,
  and satisfiable by a comment. Kept only where a stronger sibling test
  already covers the property that actually matters (see the recon script
  task's precedent for this pattern), or where the property genuinely IS a
  presence/absence fact (e.g. "SoundIn must never appear, comment or not").
- STRUCTURAL: parses actual Synth(...)/Synth.after(...) call sites out of
  COMMENT-STRIPPED source (see _strip_line_comments) and checks the parsed
  structure -- which variable holds which defname, which node is chained
  after which, which bus each node's `in`/`out` control points at. A
  comment can no longer satisfy these; only real code can.
- BEHAVIOUR (for compare_recordings/NoiseComparison): calls the real
  function against constructed audio and checks the numbers it returns.

Every STRUCTURAL test's discrimination is proven directly, not just
asserted in prose: see test_would_fail_against_a_template_with_no_fx_node,
which runs the exact same check used by the positive test against a
verbatim copy of the brief's original, defective template and confirms it
raises.
"""

import re

import numpy as np
import pytest

from moogone.analysis.noise import noise_floor_dbfs, peak_dbfs
from moogone.analysis.spectrum import peak_bin_power_fraction
from moogone.analysis.wav import Audio, synth_noise
from moogone.harness import (
    _continuous_tone_evidence,
    _floors_agree_implausibly,
    compare_recordings,
    render_probe_script,
    silence_probe_path,
)

# --- The brief's ORIGINAL template, copied verbatim (see task-13-brief.md,
# --- Step 3). Kept only so test_would_fail_against_a_template_with_no_fx_node
# --- can prove -- by actually running the same check used elsewhere in this
# --- file against it -- that the coverage below would have caught the
# --- defect this task exists to fix, rather than asserting that claim
# --- without evidence. Never imported from moogone.harness; if this ever
# --- needs to change to stay verbatim-accurate, it is because the brief
# --- changed, not because the shipped template did.
_BRIEF_TEMPLATE_MISSING_FX_NODE = """// Moog One FX noise probe — generated, do not edit by hand.
//
// Generates a test tone INSIDE SuperCollider and routes it through {defname}.
// The signal never touches the ADC, which is what makes this diagnostic.
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
// TODO-ON-HARDWARE: replace probeBus and the {defname} instantiation with the
// real bus indices and argument names from the recon /g_queryTree capture.
// Everything else in this file is final.
~probeBus = Bus.audio(s, 2);
~buf = Buffer.alloc(s, 65536, 2);
~buf.write("{out_path}", "wav", "float", 0, 0, true);

~tone = Synth(\\moog_probe_tone, [\\out, ~probeBus]);
~rec  = Synth.tail(s, \\moog_probe_record, [\\in, ~probeBus, \\bufnum, ~buf]);

{{
    {seconds}.wait;
    ~rec.free; ~tone.free;
    ~buf.close; ~buf.free; ~probeBus.free;
    "probe written to {out_path}".postln;
}}.fork;
);
"""


# --- Structural parsing helpers -------------------------------------------
#
# These are deliberately tailored to the shape of code render_probe_script
# emits (a handful of `~var = Synth(...)` / `~var = Synth.after(~target,
# ...)` statements), not a general sclang parser -- that would be far more
# machinery than this task needs. What matters is that they cannot be
# satisfied by a comment, and that they extract enough structure (defname,
# explicit ordering target, in/out bus args) to prove the FX sits IN the
# signal path rather than merely existing somewhere in the file.

_PLAIN_SYNTH_RE = re.compile(
    r"~(?P<var>\w+)\s*=\s*Synth\(\s*\\(?P<defname>\w+)\s*,\s*\[(?P<args>[^\]]*)\]"
)
_AFTER_SYNTH_RE = re.compile(
    r"~(?P<var>\w+)\s*=\s*Synth\.after\(\s*~(?P<target>\w+)\s*,\s*"
    r"\\(?P<defname>\w+)\s*,\s*\[(?P<args>[^\]]*)\]"
)
# Synth.tail(target, \defname, [args]) / Synth.head(...) -- the brief's
# original (defective) template creates its recorder this way. `target`
# here is a group/server (e.g. `s`), not a sibling node being chained after,
# so it carries no ordering claim this file's checks rely on; parsed with
# target=None, same as the plain form. Supporting this is what lets
# test_would_fail_against_a_template_with_no_fx_node's failure land
# specifically on the missing fx node, rather than incidentally on a
# recorder-parsing gap that has nothing to do with the defect under test.
_TAIL_HEAD_SYNTH_RE = re.compile(
    r"~(?P<var>\w+)\s*=\s*Synth\.(?:tail|head)\(\s*~?\w+\s*,\s*"
    r"\\(?P<defname>\w+)\s*,\s*\[(?P<args>[^\]]*)\]"
)


def _strip_line_comments(src: str) -> str:
    """Remove `// ...` comments so a mention inside one can never satisfy a
    structural check meant to prove real code exists. This is precisely the
    gap that let the brief's own `"moog_fx_reverb" in src` test pass against
    a template that only ever mentioned the defname in a comment.
    """
    return "\n".join(line.split("//", 1)[0] for line in src.splitlines())


def _parse_synth_args(args_str: str) -> dict[str, str]:
    """`"\\in, ~toneBus, \\out, ~probeBus"` -> `{"in": "~toneBus", "out": "~probeBus"}`."""
    tokens = [t.strip() for t in args_str.split(",") if t.strip()]
    return {tokens[i].lstrip("\\"): tokens[i + 1] for i in range(0, len(tokens) - 1, 2)}


def _find_synth_nodes(src: str) -> dict[str, dict]:
    """Parse every `~var = Synth(...)` / `~var = Synth.after(~target, ...)`
    call out of comment-stripped source into
    `{var: {"defname": ..., "target": str | None, "args": {...}}}`.

    `Synth(` and `Synth.after(` cannot both match the same call site (the
    literal text right after `Synth` differs -- `(` vs `.`), so the two
    regexes are mutually exclusive; no dedup logic is needed to keep a
    plain call from double-counting as an `.after` call or vice versa.
    """
    code = _strip_line_comments(src)
    nodes: dict[str, dict] = {}
    for m in _AFTER_SYNTH_RE.finditer(code):
        nodes[m.group("var")] = {
            "defname": m.group("defname"),
            "target": m.group("target"),
            "args": _parse_synth_args(m.group("args")),
        }
    for pattern in (_TAIL_HEAD_SYNTH_RE, _PLAIN_SYNTH_RE):
        for m in pattern.finditer(code):
            nodes.setdefault(
                m.group("var"),
                {
                    "defname": m.group("defname"),
                    "target": None,
                    "args": _parse_synth_args(m.group("args")),
                },
            )
    return nodes


def _assert_fx_is_wired_between_tone_and_recorder(src: str, fx_defname: str) -> None:
    """The core structural property this task exists to guarantee.

    Shared verbatim by the positive test (must NOT raise against the real
    template) and test_would_fail_against_a_template_with_no_fx_node (must
    raise against the brief's original template) so the two can never drift
    apart -- the claim "this test would have caught the defect" is proven by
    literally running the same code against the defect, not restated in a
    second, hand-synchronised copy.
    """
    nodes = _find_synth_nodes(src)

    tone_vars = [v for v, n in nodes.items() if n["defname"] == "moog_probe_tone"]
    rec_vars = [v for v, n in nodes.items() if n["defname"] == "moog_probe_record"]
    fx_vars = [v for v, n in nodes.items() if n["defname"] == fx_defname]

    assert tone_vars, "no Synth instantiates the tone SynthDef outside a comment"
    assert rec_vars, "no Synth instantiates the recorder SynthDef outside a comment"
    assert fx_vars, f"no Synth instantiates the fx defname {fx_defname!r} outside a comment"
    tone_var, rec_var, fx_var = tone_vars[0], rec_vars[0], fx_vars[0]

    fx = nodes[fx_var]
    rec = nodes[rec_var]
    assert fx["target"] == tone_var, "fx synth must be explicitly ordered (Synth.after) after tone"
    assert rec["target"] == fx_var, "recorder must be explicitly ordered (Synth.after) after fx"

    tone_out = nodes[tone_var]["args"].get("out")
    fx_in = fx["args"].get("in")
    fx_out = fx["args"].get("out")
    rec_in = rec["args"].get("in")
    assert tone_out is not None and tone_out == fx_in, "fx must read the bus the tone synth writes"
    assert fx_out is not None and fx_out == rec_in, "recorder must read the bus the fx synth writes"


# --- render_probe_script ---------------------------------------------------


def test_fx_synth_is_instantiated_between_tone_and_recorder():
    # STRUCTURAL. This is the test that guards the severe defect: the FX
    # SynthDef must be a real, explicitly-ordered node reading the tone's
    # output bus and writing the bus the recorder reads -- not merely named
    # in a comment. See test_would_fail_against_a_template_with_no_fx_node
    # for direct proof this would have failed against the brief's template.
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav")
    _assert_fx_is_wired_between_tone_and_recorder(src, "moog_fx_reverb")


def test_fx_synth_is_instantiated_between_tone_and_recorder_with_a_different_defname():
    # Same property, different defname/out_path -- confirms the wiring
    # isn't accidentally pinned to one literal string.
    src = render_probe_script("fx", "/tmp/p.wav")
    _assert_fx_is_wired_between_tone_and_recorder(src, "fx")


def test_would_fail_against_a_template_with_no_fx_node():
    # Direct, mechanical proof of the discrimination property the task asks
    # for, instead of a claim in prose: reconstruct the brief's ORIGINAL
    # template (tone -> recorder only, {defname} appearing solely inside a
    # `//` comment) and confirm the EXACT SAME check used by the positive
    # test above actually raises against it.
    #
    # If this test ever silently passed, the coverage above would be worth
    # exactly as little as the brief's own `"moog_fx_reverb" in src` check
    # was -- this project's now-familiar shape of bug, caught here before
    # shipping rather than after.
    defective_src = _BRIEF_TEMPLATE_MISSING_FX_NODE.format(
        defname="moog_fx_reverb",
        out_path="/tmp/probe.wav",
        seconds=5.0,
        tone_hz=1000.0,
        tone_amp=0.5,
    )
    # Sanity check on the parser itself, not the template: the defective
    # template's tone (`Synth(...)`) and recorder (`Synth.tail(s, ...)`)
    # both use forms the parser supports. Confirming both are found here
    # rules out the degenerate case where fx_vars comes up empty only
    # because the parser matches nothing at all against this input -- which
    # would make the assertion below pass vacuously, the same "check that
    # can't fail" shape this whole task is about avoiding. It also pins
    # down WHERE the check fails: on the fx defname specifically, not
    # incidentally on tone or recorder parsing.
    defnames_found = {n["defname"] for n in _find_synth_nodes(defective_src).values()}
    assert "moog_probe_tone" in defnames_found
    assert "moog_probe_record" in defnames_found

    with pytest.raises(AssertionError, match="no Synth instantiates the fx defname"):
        _assert_fx_is_wired_between_tone_and_recorder(defective_src, "moog_fx_reverb")


def test_fx_instantiation_carries_a_todo_on_hardware_marker():
    # MENTION, but for a property where presence-anywhere-in-the-file is
    # actually the right check: real bus indices, the fx's real control
    # names, and whether a freshly-instantiated fx behaves like the one
    # already running in Moog's own graph are genuinely not knowable until
    # the device is in hand (see harness/README.md). The marker must exist;
    # it does not need to be load-bearing code.
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav")
    assert "TODO-ON-HARDWARE" in src


def test_script_embeds_the_target_defname_and_output_path():
    # MENTION for the defname half -- kept as a cheap regression guard, but
    # the property that actually matters (the defname names a real Synth,
    # not a comment) is proven by test_fx_synth_is_instantiated_between_
    # tone_and_recorder above, which this test does not duplicate.
    # out_path has no stronger sibling test elsewhere, so this is the real
    # (if simple) check for it: routed through comment-stripped source so
    # it fails if out_path is ever dropped from the actual write/postln
    # calls and left only in a comment somewhere.
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav")
    assert "moog_fx_reverb" in src
    assert "/tmp/probe.wav" in _strip_line_comments(src)


def test_script_generates_its_tone_internally():
    # The whole diagnostic rests on the signal never touching the ADC.
    # `SoundIn not in src` is a genuine behaviour guard as-is: it is a
    # "must never appear" property, so raw textual absence (comment or not)
    # IS the correct check -- there is no weaker "mention" version of this
    # to worry about, unlike the "must appear and be real code" properties
    # elsewhere in this file.
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav", tone_hz=440.0)
    assert "SinOsc" in _strip_line_comments(src)
    assert "SoundIn" not in src, "probe must not read the audio input"


def test_script_sets_the_requested_tone_frequency_and_amplitude():
    # STRUCTURAL, replacing the brief's `assert "440" in src` (satisfied by
    # any occurrence of those digits anywhere -- a bus number, a buffer
    # size, a duration). This extracts the actual numeric values that
    # determine what tone gets generated: `freq =` from the tone SynthDef's
    # default arguments, and tone_amp from the `~tone.set(\amp, ...)` call
    # that switches the tone on for the second recording.
    #
    # amp is read from the .set call, not from a SynthDef default, because
    # the SynthDef's amp default is now deliberately 0 -- the tone synth
    # starts SILENT so the first recording can be a silence probe through
    # exactly the same graph. Asserting on the default here would pin the
    # wrong number and would pass even if tone_amp were never plumbed
    # through at all.
    src = render_probe_script("fx", "/tmp/p.wav", tone_hz=440.0, tone_amp=0.25)
    code = _strip_line_comments(src)
    freq_match = re.search(r"freq\s*=\s*([\d.]+)", code)
    set_amp_match = re.search(r"\.set\(\s*\\amp\s*,\s*([\d.]+)\s*\)", code)
    assert freq_match, "no freq default argument found in the tone SynthDef"
    assert set_amp_match, "the tone is never switched on with .set(\\amp, ...)"
    assert float(freq_match.group(1)) == pytest.approx(440.0)
    assert float(set_amp_match.group(1)) == pytest.approx(0.25)
    # And the tone must START silent, or the "silence" probe records the
    # tone. This is the half of the property the .set assertion cannot see.
    default_amp = re.search(r"\bamp\s*=\s*([\d.]+)", code)
    assert default_amp, "no amp default argument found in the tone SynthDef"
    assert float(default_amp.group(1)) == 0.0, (
        "the tone SynthDef does not default to silent, so the silence probe "
        "would record the tone"
    )


def test_script_records_for_the_requested_duration():
    # STRUCTURAL, replacing the brief's `assert "8" in src` (satisfied by
    # 8192, or any number containing an 8 -- e.g. a bus index or the buffer
    # size). Extracts the actual numeric operand of `.wait`, which is the
    # value that determines how long the recording runs, rather than
    # grepping the whole file for a digit.
    src = render_probe_script("fx", "/tmp/p.wav", seconds=8.0)
    code = _strip_line_comments(src)
    wait_match = re.search(r"([\d.]+)\s*\.\s*wait\b", code)
    assert wait_match, "no `<number>.wait` found -- duration is not wired to anything"
    assert float(wait_match.group(1)) == pytest.approx(8.0)
    assert "DiskOut" in code


def test_different_durations_produce_different_wait_values():
    # Companion to the test above: confirms `seconds` is actually a live
    # parameter of the template, not a constant that happens to equal the
    # default (5.0) plumbed through by coincidence.
    code_a = _strip_line_comments(render_probe_script("fx", "/tmp/p.wav", seconds=3.0))
    code_b = _strip_line_comments(render_probe_script("fx", "/tmp/p.wav", seconds=12.0))
    wait_a = float(re.search(r"([\d.]+)\s*\.\s*wait\b", code_a).group(1))
    wait_b = float(re.search(r"([\d.]+)\s*\.\s*wait\b", code_b).group(1))
    assert wait_a == pytest.approx(3.0)
    assert wait_b == pytest.approx(12.0)


def test_all_three_nodes_are_freed_in_the_cleanup_block():
    # STRUCTURAL-ish: the brief's cleanup block only freed ~rec and ~tone
    # (there was no ~fx to free). Confirms the fix's cleanup block frees
    # all three nodes and both buses -- leaking a Synth or a Bus on every
    # probe run would eventually exhaust the server across repeated before/
    # after captures in a single sclang session.
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav")
    code = _strip_line_comments(src)
    for token in ("~tone.free", "~fx.free", "~rec.free"):
        assert token in code, f"cleanup block never frees {token}"


# --- compare_recordings / NoiseComparison -----------------------------------


def test_comparison_detects_an_improved_noise_floor():
    before = synth_noise(1.0, 48000, -60.0)
    after = synth_noise(1.0, 48000, -75.0, seed=1)
    result = compare_recordings(before, after)
    assert result.floor_delta_db == pytest.approx(-15.0, abs=1.5)
    # Verified empirically (not assumed): uniformly scaling white noise's
    # level shifts both the unweighted floor and the A-weighted figure by
    # ~the same amount, since A-weighting is a fixed spectral shape and
    # white noise's shape doesn't change with level -- only its scale does.
    assert result.floor_improved is True
    assert result.weighted_improved is True
    assert result.verdict == "improved"


def test_comparison_detects_a_worse_noise_floor():
    before = synth_noise(1.0, 48000, -75.0)
    after = synth_noise(1.0, 48000, -60.0, seed=1)
    result = compare_recordings(before, after)
    assert result.floor_improved is False
    assert result.weighted_improved is False
    assert result.verdict == "worse"


def test_comparison_reports_both_weighted_and_unweighted():
    before = synth_noise(1.0, 48000, -60.0)
    after = synth_noise(1.0, 48000, -70.0, seed=1)
    result = compare_recordings(before, after)
    assert result.weighted_delta_db < 0
    assert result.floor_delta_db < 0


def test_comparison_rejects_mismatched_sample_rates():
    a = Audio(np.zeros(1000), 48000)
    b = Audio(np.zeros(1000), 44100)
    with pytest.raises(ValueError, match="sample rate"):
        compare_recordings(a, b)


def _band_noise(seconds, lo_hz, hi_hz, level_dbfs, sample_rate=48000, seed=0):
    """White noise restricted to a frequency band, at a known RMS level.

    Needed because the two "mixed verdict" tests below used PURE SINES,
    and compare_recordings now (correctly) refuses a continuous tone: a
    sine has no quiet windows, so its noise floor cannot be measured at
    all. Those fixtures were themselves an instance of the bug -- they
    fed the function exactly the signal shape that made a true 12 dB
    improvement read as +0.000 dB, and got confident numbers back.

    Band-limited noise keeps the property those tests actually need (most
    energy in one part of the spectrum, so A-weighting and the raw floor
    can be made to disagree) while being genuine noise: it has quiet
    windows in the only sense that matters here -- every window is noise,
    which is what a noise floor IS.
    """
    rng = np.random.default_rng(seed)
    n = int(seconds * sample_rate)
    raw = rng.standard_normal(n)
    spec = np.fft.rfft(raw)
    freqs = np.fft.rfftfreq(n, 1.0 / sample_rate)
    spec[(freqs < lo_hz) | (freqs > hi_hz)] = 0
    out = np.fft.irfft(spec, n)
    out /= np.sqrt(np.mean(out**2))
    return Audio(out * (10 ** (level_dbfs / 20)), sample_rate)


def test_comparison_flags_mixed_when_floor_improves_but_weighted_worsens():
    # BEHAVIOUR. The design question this task asks: `improved` in the
    # brief was `floor_after < floor_before` alone, which would report
    # "improved" here even though the change makes things sound worse.
    # Constants verified empirically before writing this test (not
    # hand-derived and assumed):
    #   floor_delta_db    ~ -11.5  (raw floor genuinely improves)
    #   weighted_delta_db ~  +8.1  (perceptual figure gets worse)
    # both comfortably clear of zero, so this is not a borderline
    # comparison.
    #
    # 30-120 Hz: A-weighting suppresses this band ~30 dB relative to 1 kHz.
    before = _band_noise(1.0, 30, 120, -60.0, seed=0)
    # 2-3 kHz: near A-weighting's +1.27 dB peak. RMS is LOWER than
    # `before`, so the unweighted floor genuinely improves even though the
    # perceptual figure does not.
    after = _band_noise(1.0, 2000, 3000, -74.0, seed=1)

    result = compare_recordings(before, after)

    assert result.floor_delta_db < 0
    assert result.weighted_delta_db > 0
    assert result.floor_improved is True
    assert result.weighted_improved is False
    assert result.verdict == "mixed"


def test_comparison_flags_mixed_when_floor_worsens_but_weighted_improves():
    # Same two fixtures as above with before/after swapped: both deltas
    # negate, giving the opposite disagreement (floor worse, weighted
    # better) -- equally "mixed", not the mirror-image "improved". Confirms
    # `verdict` genuinely depends on both signs rather than picking a fixed
    # "whichever direction floor moves wins" rule under another name.
    quiet_high_band = _band_noise(1.0, 2000, 3000, -74.0, seed=1)
    loud_low_band = _band_noise(1.0, 30, 120, -60.0, seed=0)

    result = compare_recordings(quiet_high_band, loud_low_band)

    assert result.floor_delta_db > 0
    assert result.weighted_delta_db < 0
    assert result.floor_improved is False
    assert result.weighted_improved is True
    assert result.verdict == "mixed"


def test_compare_recordings_raises_on_zero_length_audio():
    # Confirms compare_recordings inherits validate_audio's protection via
    # noise_floor_dbfs/a_weighted_dbfs -- verified directly through
    # compare_recordings itself (both operand positions), not assumed from
    # those functions' own test coverage elsewhere.
    valid = synth_noise(1.0, 48000, -60.0)
    empty = Audio(np.array([]), 48000)
    with pytest.raises(ValueError, match="zero-length"):
        compare_recordings(empty, valid)
    with pytest.raises(ValueError, match="zero-length"):
        compare_recordings(valid, empty)


def test_compare_recordings_raises_on_non_finite_samples():
    valid = synth_noise(1.0, 48000, -60.0)
    bad = synth_noise(1.0, 48000, -60.0, seed=1)
    bad.samples[100] = float("nan")
    with pytest.raises(ValueError, match="non-finite"):
        compare_recordings(bad, valid)
    with pytest.raises(ValueError, match="non-finite"):
        compare_recordings(valid, bad)


# --- CRITICAL 1: the probe the analysis rig can actually measure ------------


def _tone_plus_noise(seconds, hz, amp, noise_dbfs, sample_rate=48000, seed=0):
    """A continuous test tone over a noise floor -- what render_probe_script
    used to be the only generator of, and what compare_recordings must now
    refuse.
    """
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    noise = synth_noise(seconds, sample_rate, noise_dbfs, seed).samples
    return Audio(np.sin(2 * np.pi * hz * t) * amp + noise, sample_rate)


def test_compare_recordings_refuses_a_continuous_tone_instead_of_returning_a_number():
    """THE finding. Fed two tone probes carrying a TRUE 12 dB noise
    improvement, compare_recordings used to return floor_delta_db =
    +0.000 dB and verdict = "worse" -- the project's central question
    (is the effects noise DSP or converters?) decided by float rounding,
    because the tone sits ~50 dB above the noise in every window and both
    metrics therefore measured the tone.

    The fixtures below are constructed to carry exactly that true 12 dB
    improvement, so this test also documents the magnitude of the lie.

    Mutation-checked: delete the two _require_measurable_floor calls from
    compare_recordings and this test fails -- the call returns a
    NoiseComparison with floor_delta_db == 0.0 and verdict == "worse".
    """
    before = _tone_plus_noise(2.0, 1000.0, 0.5, -60.0, seed=7)
    after = _tone_plus_noise(2.0, 1000.0, 0.5, -72.0, seed=7)

    with pytest.raises(ValueError, match="dominated by a single steady tone") as excinfo:
        compare_recordings(before, after)

    message = str(excinfo.value)
    # The message has to be actionable, not just correct: it must say what
    # to use instead, or the first person to hit it in September will
    # assume the guard is overcautious and route around it.
    assert "silence" in message.lower(), "the refusal never names the alternative"
    assert "snr_db" in message, "the refusal never names what a tone probe IS for"
    # And it must carry the evidence that drove it.
    assert "dB above its own floor" in message
    # It must NOT assume the operator is holding a tone probe. The
    # false-refusal case is a SILENCE probe whose noise carries a tonal
    # line -- measured, that starts at a line only ~5 dB above the
    # broadband floor -- and in that case "use the silence probe instead"
    # is advice to fetch the file they already have. Both readings have to
    # be on the page.
    assert "(a)" in message and "(b)" in message, (
        "the refusal offers only one reading of the evidence"
    )
    assert "IS the silence probe" in message, (
        "the refusal never considers that this may already BE the silence probe"
    )


def test_compare_recordings_refuses_a_tone_in_either_operand_position():
    """A tone in `after` alone must be refused too -- otherwise a
    half-correct capture (silence probe before, tone probe after) would
    sail through and produce a number from two incomparable recordings.
    """
    quiet = synth_noise(2.0, 48000, -60.0)
    tone = _tone_plus_noise(2.0, 1000.0, 0.5, -60.0, seed=7)

    with pytest.raises(ValueError, match=r"`after` recording is dominated"):
        compare_recordings(quiet, tone)
    with pytest.raises(ValueError, match=r"`before` recording is dominated"):
        compare_recordings(tone, quiet)


def test_silence_probes_carrying_the_same_12_db_improvement_are_measured_correctly():
    """The other half of the finding, and the reason a silence probe is the
    fix rather than just a stricter check: the SAME 12 dB improvement,
    captured without a tone, is measured accurately. If this failed, the
    guard above would be refusing everything rather than refusing the
    unmeasurable.
    """
    before = synth_noise(2.0, 48000, -60.0, seed=7)
    after = synth_noise(2.0, 48000, -72.0, seed=7)

    result = compare_recordings(before, after)

    assert result.floor_delta_db == pytest.approx(-12.0, abs=0.5)
    assert result.verdict == "improved"


def test_a_recording_with_real_gaps_is_not_refused():
    """A tone followed by silence IS measurable -- the percentile finds the
    gap -- and the review measured it at -11.98 dB against the same true
    12 dB improvement. The guard must not reject it. Without this, "refuse
    anything containing a tone" would satisfy the tests above while
    throwing away a legitimate capture.
    """
    sr = 48000
    tone_half = _tone_plus_noise(1.0, 1000.0, 0.5, -60.0, sample_rate=sr, seed=7).samples
    quiet_half = synth_noise(1.0, sr, -60.0, seed=8).samples
    before = Audio(np.concatenate([tone_half, quiet_half]), sr)

    tone_half_after = _tone_plus_noise(1.0, 1000.0, 0.5, -72.0, sample_rate=sr, seed=7).samples
    quiet_half_after = synth_noise(1.0, sr, -72.0, seed=8).samples
    after = Audio(np.concatenate([tone_half_after, quiet_half_after]), sr)

    result = compare_recordings(before, after)
    assert result.floor_delta_db == pytest.approx(-12.0, abs=0.5)


@pytest.mark.parametrize(
    "make_audio,label",
    [
        (lambda: synth_noise(2.0, 48000, -60.0), "white noise"),
        (lambda: _band_noise(2.0, 30, 120, -60.0), "low-band noise"),
        (lambda: _band_noise(2.0, 2000, 3000, -74.0), "high-band noise"),
        (lambda: _band_noise(2.0, 990, 1010, -60.0), "20 Hz-wide band noise"),
        (
            lambda: Audio(
                np.random.default_rng(3).uniform(-1, 1, 2 * 48000) * 10 ** (-60 / 20), 48000
            ),
            "uniform (quantisation-like) noise",
        ),
    ],
)
def test_legitimate_noise_floor_captures_are_not_refused(make_audio, label):
    """The false-positive sweep. Each of these trips ONE arm of the guard
    and must be acquitted by the other -- uniform noise has a 4.77 dB crest
    factor (crest arm), 20 Hz-wide band noise puts 27% of its power in one
    bin (tonality arm). A guard using either test alone would reject real
    noise-floor captures, so this is what pins the conjunction.
    """
    audio = make_audio()
    assert _continuous_tone_evidence(audio) is None, (
        f"{label} was misclassified as a continuous tone"
    )


def test_the_guard_needs_both_arms_to_indict():
    """Directly pins the AND, rather than inferring it from the sweep: a
    pure sine trips both arms, uniform noise trips only crest, narrow band
    noise trips only tonality. Only the first is refused.
    """
    sr = 48000
    t = np.arange(2 * sr) / sr
    sine = Audio(np.sin(2 * np.pi * 1000 * t) * 0.5, sr)
    uniform = Audio(np.random.default_rng(3).uniform(-1, 1, 2 * sr) * 10 ** (-60 / 20), sr)
    narrow = _band_noise(2.0, 990, 1010, -60.0)

    assert peak_bin_power_fraction(sine) > 0.10
    assert peak_dbfs(sine) - noise_floor_dbfs(sine) < 10.0
    assert _continuous_tone_evidence(sine) is not None  # both arms

    assert peak_bin_power_fraction(uniform) < 0.10  # acquitted here
    assert peak_dbfs(uniform) - noise_floor_dbfs(uniform) < 10.0  # crest arm alone indicts
    assert _continuous_tone_evidence(uniform) is None

    assert peak_bin_power_fraction(narrow) > 0.10  # tonality arm alone indicts
    assert peak_dbfs(narrow) - noise_floor_dbfs(narrow) > 10.0  # acquitted here
    assert _continuous_tone_evidence(narrow) is None


# --- the generated script now emits a silence probe as well -----------------


_RECORDER_RE = re.compile(
    r"Synth\.after\(\s*~(?P<target>\w+)\s*,\s*\\moog_probe_record\s*,\s*\[(?P<args>[^\]]*)\]"
)


def _recorder_call_sites(code: str) -> list[dict]:
    """Every DiskOut recorder instantiation, in source order, with the
    buffer it writes to.

    A dedicated parser rather than _find_synth_nodes, which keys by
    variable name and would collapse the two recorders into one -- they
    deliberately reuse ~rec (the first is freed before the second is
    created, so two are never alive at once).

    This exists because the first version of the ordering test below
    anchored on `code.index("~silenceBuf")`, which finds the BUFFER
    ALLOCATION -- always near the top, always before everything. Deleting
    the entire silence recording block, and separately swapping the two
    recordings into the wrong order, both left that test green. Caught by
    mutation before commit; the assertions below are written against
    actual recorder call sites for exactly that reason.
    """
    sites = []
    for m in _RECORDER_RE.finditer(code):
        sites.append(
            {
                "pos": m.start(),
                "target": m.group("target"),
                "args": _parse_synth_args(m.group("args")),
            }
        )
    return sites


def test_script_records_a_silence_probe_before_the_tone_probe():
    """STRUCTURAL. Both files must be written, and the silence probe must be
    recorded FIRST: a reverb or delay fed a tone rings for seconds after
    the tone stops, so a silence capture taken afterwards would measure
    that tail and call it the effect's noise floor.

    Mutation-checked twice: deleting the silence recording block, and
    swapping the two recordings, each fail this test.
    """
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav")
    code = _strip_line_comments(src)

    silence = silence_probe_path("/tmp/probe.wav")
    assert silence == "/tmp/probe-silence.wav"
    assert silence in code, "the silence probe file is never written"
    assert "/tmp/probe.wav" in code, "the tone probe file is never written"

    sites = _recorder_call_sites(code)
    assert len(sites) == 2, f"expected exactly two recordings, found {len(sites)}"

    first, second = sites
    assert first["args"].get("bufnum") == "~silenceBuf", (
        "the FIRST recording is not the silence probe -- a reverb tail from the "
        "tone would be measured as the effect's own noise floor"
    )
    assert second["args"].get("bufnum") == "~toneBuf"
    # Both must read the bus the fx writes, and be ordered after it.
    for site in sites:
        assert site["target"] == "fx"
        assert site["args"].get("in") == "~probeBus"

    # The tone is switched on strictly between the two recordings.
    amp_on = re.search(r"\.set\(\s*\\amp\s*,\s*(?P<value>[\d.]+)\s*\)", code)
    assert amp_on, "the tone is never switched on"
    assert float(amp_on.group("value")) > 0
    assert first["pos"] < amp_on.start() < second["pos"], (
        "the tone is not switched on between the silence and tone recordings"
    )


def test_script_starts_the_tone_silent_so_the_first_capture_really_is_silent():
    """The silence probe is only silent if the tone synth starts at amp 0.
    Checked on parsed structure: the tone Synth is created with no amp
    argument at all, relying on a SynthDef default that must be 0.
    """
    code = _strip_line_comments(render_probe_script("fx", "/tmp/p.wav", tone_amp=0.5))
    nodes = _find_synth_nodes(code)
    tone_var = next(v for v, n in nodes.items() if n["defname"] == "moog_probe_tone")
    assert "amp" not in nodes[tone_var]["args"], (
        "the tone synth is created with an explicit amp; the silence probe would "
        "record it"
    )
    assert re.search(r"\bamp\s*=\s*0\b", code), "the tone SynthDef does not default to silent"


def test_silence_probe_path_handles_paths_without_an_extension():
    assert silence_probe_path("/tmp/probe") == "/tmp/probe-silence"
    assert silence_probe_path("probe.wav") == "probe-silence.wav"
    # A dot in a directory name must not be mistaken for the extension.
    assert silence_probe_path("/tmp/v1.2/probe") == "/tmp/v1.2/probe-silence"


# --- IMPORTANT 7: the generated sclang has no s.sync -------------------------


def test_generated_script_syncs_before_using_asynchronously_created_objects():
    """SynthDef.add, Buffer.alloc and Buffer.write are all asynchronous.
    Pasted into an IDE by hand, human latency hides that; fed through the
    screen session this file's own header offers, the blocks race, and the
    symptom is "SynthDef not found" for \\moog_probe_tone -- which reads as
    "the fx defname is wrong" and sends the operator hunting in entirely
    the wrong place.

    Checked on comment-stripped source, so a `// remember to sync` comment
    cannot satisfy it, and by ORDER rather than mere presence: a sync must
    occur between each async call and the first use of what it created.
    """
    code = _strip_line_comments(render_probe_script("fx", "/tmp/p.wav"))

    assert "s.sync" in code, "the generated script never syncs at all"
    # s.sync only works inside a Routine; a bare block would raise.
    assert re.search(r"fork\s*\{", code), "s.sync is used outside a fork/Routine"

    last_add = code.rindex(".add;")
    first_sync = code.index("s.sync")
    first_synth = code.index("Synth(")
    assert last_add < first_sync < first_synth, (
        "no s.sync between the last SynthDef.add and the first Synth that uses one"
    )

    alloc = code.rindex("Buffer.alloc")
    first_write = code.index("Buf.write")
    assert alloc < code.index("s.sync", alloc) < first_write, (
        "no s.sync between Buffer.alloc and the Buffer.write that uses the buffer"
    )

    last_write = code.rindex("Buf.write")
    recorder = code.index("moog_probe_record", last_write)
    assert last_write < code.index("s.sync", last_write) < recorder, (
        "no s.sync between opening the files and the DiskOut synth that writes them"
    )


# --- the pairwise guard: a tone through a MODULATED effect -------------------


def _modulated_comb(x, sample_rate, depth_ms, lfo_hz, mix=0.5):
    """Chorus/flanger: dry plus a copy delayed by a slowly swept amount.

    Chorus and flanger are Moog One effects, so this is inside the set the
    project is diagnosing, not a hypothetical. The swept comb notch sliding
    across the tone is what creates the amplitude minima that make the
    10th-percentile window land far below the tone -- and identically so in
    two recordings whose noise differs by 12 dB.
    """
    n = len(x)
    t = np.arange(n) / sample_rate
    delay = (depth_ms / 1000.0) * (1 + np.sin(2 * np.pi * lfo_hz * t)) / 2 * sample_rate
    idx = np.clip(np.arange(n) - delay, 0, n - 1)
    lo = np.floor(idx).astype(int)
    hi = np.minimum(lo + 1, n - 1)
    frac = idx - lo
    return (1 - mix) * x + mix * (x[lo] * (1 - frac) + x[hi] * frac)


def _tremolo(x, sample_rate, rate_hz, depth):
    t = np.arange(len(x)) / sample_rate
    return x * (1 - depth / 2 + depth / 2 * np.sin(2 * np.pi * rate_hz * t))


def _modulated_tone_probe(effect, noise_dbfs, seconds=5.0, sample_rate=48000, seed=7):
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    tone = np.sin(2 * np.pi * 1000.0 * t) * 0.5
    noise = synth_noise(seconds, sample_rate, noise_dbfs, seed).samples
    return Audio(effect(tone) + noise, sample_rate)


_MODULATED_EFFECTS = [
    pytest.param(lambda x: _modulated_comb(x, 48000, 1.0, 0.5), id="chorus-1ms-0.5Hz"),
    pytest.param(lambda x: _modulated_comb(x, 48000, 2.0, 0.5), id="chorus-2ms-0.5Hz"),
    pytest.param(lambda x: _modulated_comb(x, 48000, 5.0, 0.5), id="chorus-5ms-0.5Hz"),
    pytest.param(lambda x: _modulated_comb(x, 48000, 1.0, 3.0), id="chorus-1ms-3Hz"),
    pytest.param(lambda x: _modulated_comb(x, 48000, 1.0, 0.2), id="flanger-1ms-0.2Hz"),
    pytest.param(lambda x: _tremolo(x, 48000, 0.3, 0.9), id="tremolo-0.3Hz"),
]


@pytest.mark.parametrize("effect", _MODULATED_EFFECTS)
def test_modulated_tone_probes_are_refused_by_the_pairwise_check(effect):
    """THE second-cycle finding, and it reproduces the original CRITICAL 1
    signature exactly: a 1 ms / 0.5 Hz chorus -- the most ordinary chorus
    setting there is -- on two recordings carrying a TRUE 12 dB noise
    improvement reported floor_delta_db = +0.000 and verdict = "worse".

    The single-recording guard cannot see this. The sweeping comb notch
    creates amplitude minima, the 10th-percentile window lands in one tens
    of dB below the tone, and the crest test therefore reads a recording
    that looks like it HAS quiet windows (12.4 dB crest, clearing the
    10 dB bar) and acquits it. Each recording looks individually fine; only
    the comparison betrays that neither floor moved.

    Mutation-checked: delete the
    _require_a_comparison_that_resolves_something call from
    compare_recordings and every case here fails, returning
    |floor_delta_db| < 0.01 against a true -12.
    """
    before = _modulated_tone_probe(effect, -60.0)
    after = _modulated_tone_probe(effect, -72.0)

    # The single-recording guard must genuinely NOT catch these -- otherwise
    # this test would be passing via the old guard and proving nothing about
    # the pairwise one.
    assert _continuous_tone_evidence(before) is None, (
        "the single-recording guard already refuses this; the fixture does not "
        "exercise the pairwise check at all"
    )
    assert _continuous_tone_evidence(after) is None

    with pytest.raises(ValueError, match="resolves nothing") as excinfo:
        compare_recordings(before, after)
    message = str(excinfo.value)
    assert "(a)" in message and "(b)" in message, "only one reading is offered"
    assert "chorus" in message.lower(), "the mechanism is never named"
    assert "silence" in message.lower(), "no alternative is offered"


def test_the_chorus_case_reproduces_the_original_signature_without_the_guard():
    """Direct evidence for the claim the test above rests on, rather than
    prose: with the pairwise check bypassed, the 1 ms / 0.5 Hz chorus really
    does report a near-zero delta on a true 12 dB improvement. Uses the
    private measurement path so the numbers are the ones compare_recordings
    would have returned.
    """
    effect = _MODULATED_EFFECTS[0].values[0]
    before = _modulated_tone_probe(effect, -60.0)
    after = _modulated_tone_probe(effect, -72.0)

    delta = noise_floor_dbfs(after) - noise_floor_dbfs(before)
    assert abs(delta) < 0.01, (
        f"fixture no longer reproduces the failure (delta {delta:+.5f}); the test "
        "above would be proving nothing"
    )
    # ...while the true difference is 12 dB, which the silence-probe path
    # measures correctly with the identical noise seeds.
    quiet_before = synth_noise(5.0, 48000, -60.0, seed=7)
    quiet_after = synth_noise(5.0, 48000, -72.0, seed=7)
    assert noise_floor_dbfs(quiet_after) - noise_floor_dbfs(quiet_before) == pytest.approx(
        -12.0, abs=0.1
    )


def test_pairwise_check_needs_both_arms():
    """Pins the AND. A real -12 dB change on tonal recordings must pass on
    the delta arm; broadband noise whose floors agree exactly must pass on
    the tonality arm. Neither arm alone would allow both.
    """
    effect = _MODULATED_EFFECTS[0].values[0]
    tonal_before = _modulated_tone_probe(effect, -60.0)
    tonal_after = _modulated_tone_probe(effect, -72.0)

    # Tonal, delta near zero -> refused (both arms indict).
    assert _floors_agree_implausibly(tonal_before, tonal_after, 0.001) is not None
    # Tonal, but a real delta -> accepted on the delta arm alone.
    assert _floors_agree_implausibly(tonal_before, tonal_after, -12.0) is None
    # Delta near zero, but not tonal -> accepted on the tonality arm alone.
    white_a = synth_noise(2.0, 48000, -60.0, seed=1)
    white_b = synth_noise(2.0, 48000, -60.0, seed=2)
    assert _floors_agree_implausibly(white_a, white_b, 0.0) is None


def test_pairwise_check_requires_both_recordings_to_be_tonal():
    """One tonal recording and one not is a mismatched pair, not the failure
    class this targets. Requiring both is the conservative direction for a
    guard whose false positives cost the operator a measurement they cannot
    retake.
    """
    effect = _MODULATED_EFFECTS[0].values[0]
    tonal = _modulated_tone_probe(effect, -60.0)
    broadband = synth_noise(5.0, 48000, -60.0, seed=1)
    assert _floors_agree_implausibly(tonal, broadband, 0.0) is None
    assert _floors_agree_implausibly(broadband, tonal, 0.0) is None


@pytest.mark.parametrize(
    "make_audio,label",
    [
        (lambda s: synth_noise(5.0, 48000, -60.0, seed=s), "white noise"),
        (lambda s: _band_noise(5.0, 30, 120, -60.0, seed=s), "low-band noise"),
        (lambda s: _band_noise(5.0, 2000, 3000, -74.0, seed=s), "high-band noise"),
        (lambda s: _band_noise(5.0, 990, 1010, -60.0, seed=s), "20 Hz-wide band noise"),
        (
            lambda s: Audio(
                np.random.default_rng(s).uniform(-1, 1, 5 * 48000) * 10 ** (-60 / 20), 48000
            ),
            "uniform (quantisation-like) noise",
        ),
    ],
)
def test_genuine_no_change_comparisons_of_noise_are_not_refused(make_audio, label):
    """The false-refusal sweep for the pairwise arm, which matters as much as
    the true-refusal sweep: the operator gets one hardware window, and a
    guard that refuses a legitimate capture costs them a measurement they
    cannot retake.

    Each of these is a genuine NO-CHANGE comparison -- same level, two
    independent noise realisations -- so the delta arm indicts every one of
    them and only the tonality arm acquits. Measured over 100 seed pairs per
    fixture during derivation: 0/100 refused for all five.
    """
    for seed in range(6):
        before, after = make_audio(3000 + 2 * seed), make_audio(3001 + 2 * seed)
        result = compare_recordings(before, after)
        assert result.floor_delta_db == pytest.approx(0.0, abs=3.0), label


def test_a_real_improvement_on_noise_is_still_measured():
    """The end-to-end direction that matters: adding a second guard must not
    have broken the case the whole rig exists for.
    """
    result = compare_recordings(
        synth_noise(5.0, 48000, -60.0, seed=7), synth_noise(5.0, 48000, -72.0, seed=7)
    )
    assert result.floor_delta_db == pytest.approx(-12.0, abs=0.3)
    assert result.verdict == "improved"


# --- the probe's bus hygiene: ReplaceOut and the clear node ------------------


def test_tone_and_clear_synthdefs_use_replaceout_not_out():
    """SuperCollider zeroes the hardware output buses every block but NOT
    private ones, and Out.ar MIXES into a bus rather than overwriting it.
    Bus.audio allocates from sclang's own allocator, which knows nothing
    about the bus indices Moog's firmware already has in use -- so a silence
    probe read off a bus still carrying someone else's audio would report
    that audio as this effect's self-noise. That is the original wrong
    answer, reached by a different route.

    This is a TEXT-level check on comment-stripped source: the suite cannot
    execute sclang, so it can see the template's structure but not its audio
    semantics. Stated plainly rather than implied -- see the task report.
    """
    code = _strip_line_comments(render_probe_script("fx", "/tmp/p.wav"))

    for defname in ("moog_probe_clear", "moog_probe_tone"):
        match = re.search(
            rf"SynthDef\(\s*\\{defname}\s*,\s*\{{(?P<body>.*?)\}}\s*\)\.add",
            code,
            re.DOTALL,
        )
        assert match, f"no SynthDef body found for {defname}"
        body = match.group("body")
        assert "ReplaceOut.ar" in body, (
            f"{defname} does not use ReplaceOut: Out.ar MIXES into a private bus "
            f"that SuperCollider never zeroes, so stale or foreign audio would be "
            f"recorded as the effect's own noise"
        )
        assert not re.search(r"(?<!Replace)\bOut\.ar", body), (
            f"{defname} still contains a plain Out.ar"
        )


def test_a_clear_node_zeroes_the_probe_bus_ahead_of_the_fx():
    """The clear node is what guarantees ~probeBus starts each block at zero,
    since the FX's own SynthDef is not ours to change and will almost
    certainly use Out.ar. It must exist, be instantiated on ~probeBus, run
    BEFORE the fx, and be freed.
    """
    code = _strip_line_comments(render_probe_script("moog_fx_reverb", "/tmp/p.wav"))
    nodes = _find_synth_nodes(code)

    clear_vars = [v for v, n in nodes.items() if n["defname"] == "moog_probe_clear"]
    assert clear_vars, "no Synth instantiates a clear node outside a comment"
    clear_var = clear_vars[0]
    assert nodes[clear_var]["args"].get("out") == "~probeBus", (
        "the clear node does not write ~probeBus -- the bus the recorder reads -- "
        "so it zeroes nothing that matters"
    )

    # It must run ahead of the fx in node order. The tone is explicitly
    # chained after it, and the fx after the tone.
    tone_var = next(v for v, n in nodes.items() if n["defname"] == "moog_probe_tone")
    fx_var = next(v for v, n in nodes.items() if n["defname"] == "moog_fx_reverb")
    assert nodes[tone_var]["target"] == clear_var, (
        "the tone is not chained after the clear node, so the clear node's position "
        "in the node order is not guaranteed"
    )
    assert nodes[fx_var]["target"] == tone_var

    assert f"~{clear_var}.free" in code, "the clear node is never freed"


def test_a_genuine_no_change_comparison_of_tonal_recordings_is_also_refused():
    """The deliberate consequence of the pairwise criterion, pinned so it
    reads as a decision rather than an accident.

    Two tone-dominated recordings whose floors agree to within a hair admit
    exactly two readings -- "the measurement is blind to the change" and
    "there was no change" -- and nothing in either recording chooses between
    them. Returning a number would assert the second without evidence.

    The cost is asymmetric, which is why this direction was chosen: "nothing
    changed" is recoverable (the floors are printed in the message and
    noise_floor_dbfs still works), while "+0.000 dB, verdict worse" on a real
    12 dB improvement ends the project on the wrong conclusion.

    Mutation-checked: this test fails if the pairwise check is removed --
    compare_recordings then returns verdict "worse" for two identical-level
    recordings.
    """
    effect = _MODULATED_EFFECTS[0].values[0]
    # Same noise level in both: genuinely nothing changed.
    before = _modulated_tone_probe(effect, -60.0, seed=1)
    after = _modulated_tone_probe(effect, -60.0, seed=2)

    with pytest.raises(ValueError, match="resolves nothing") as excinfo:
        compare_recordings(before, after)
    message = str(excinfo.value)
    # The message must not assert the broken reading. It has to offer the
    # "genuinely nothing changed" reading too, and hand back the numbers so
    # the operator is not left with nothing.
    assert "genuinely nothing changed" in message, (
        "the refusal asserts the measurement is broken without admitting the "
        "other reading the evidence equally supports"
    )
    assert "noise_floor_dbfs" in message, "no way forward is offered"
    assert re.search(r"-?\d+\.\d+ and -?\d+\.\d+ dBFS", message), (
        "the measured floors are not handed back"
    )
