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

from moogone.analysis.wav import Audio, synth_noise
from moogone.harness import compare_recordings, render_probe_script

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
    # size, a duration). This extracts the actual `freq =`/`amp =` default
    # arguments of the tone SynthDef and checks the numeric value that
    # landed there, which is the thing that actually determines what tone
    # gets generated.
    src = render_probe_script("fx", "/tmp/p.wav", tone_hz=440.0, tone_amp=0.25)
    code = _strip_line_comments(src)
    freq_match = re.search(r"freq\s*=\s*([\d.]+)", code)
    amp_match = re.search(r"\bamp\s*=\s*([\d.]+)", code)
    assert freq_match, "no freq default argument found in the tone SynthDef"
    assert amp_match, "no amp default argument found in the tone SynthDef"
    assert float(freq_match.group(1)) == pytest.approx(440.0)
    assert float(amp_match.group(1)) == pytest.approx(0.25)


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


def test_comparison_flags_mixed_when_floor_improves_but_weighted_worsens():
    # BEHAVIOUR. The design question this task asks: `improved` in the
    # brief was `floor_after < floor_before` alone, which would report
    # "improved" here even though the change makes things sound worse.
    # Constants verified empirically before writing this test (not
    # hand-derived and assumed) -- see the task report:
    #   floor_delta_db  ~ -14.0  (raw floor genuinely improves)
    #   weighted_delta_db ~ +17.4 (perceptual figure gets much worse)
    # both comfortably clear of zero, so this is not a borderline/flaky
    # comparison.
    sr = 48000
    t = np.arange(sr) / sr
    # 50 Hz: A-weighting suppresses this ~30 dB relative to 1 kHz.
    before = Audio(np.sin(2 * np.pi * 50 * t) * 0.1, sr)
    # 2500 Hz: near A-weighting's +1.27 dB peak. Raw amplitude is LOWER
    # than `before`, so the unweighted floor genuinely improves even
    # though the perceptual figure does not.
    after = Audio(np.sin(2 * np.pi * 2500 * t) * 0.02, sr)

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
    sr = 48000
    t = np.arange(sr) / sr
    quiet_2500hz = Audio(np.sin(2 * np.pi * 2500 * t) * 0.02, sr)
    loud_50hz = Audio(np.sin(2 * np.pi * 50 * t) * 0.1, sr)

    result = compare_recordings(quiet_2500hz, loud_50hz)

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
