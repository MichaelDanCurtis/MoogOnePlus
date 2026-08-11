"""Tests for WAV loading and noise-floor measurement.

A wrong measurement here doesn't announce itself -- it returns a
plausible, well-formatted number that just happens to be wrong. So this
file leans on two kinds of test, and the comments say which is which:

- Anchored: the expected value is derivable from mathematics or plain
  arithmetic, without reference to any other function in this module.
  test_full_scale_sine_measures_near_minus_three_dbfs is the canonical
  example -- a full-scale sine's RMS is 1/sqrt(2) by trigonometry, a fact
  that owes nothing to this codebase.
- Round-trip: two functions from this same module are checked against
  each other (e.g. synth_noise's requested level against rms_dbfs's
  measurement of it). These pass if the two disagree correctly, but also
  pass if they share a mistake -- e.g. both using 10*log10 where 20*log10
  belongs. They only become trustworthy once at least one side has been
  anchored independently elsewhere in this file.
"""

import numpy as np
import pytest
import soundfile as sf

from moogone.analysis.noise import _dbfs, noise_floor_dbfs, peak_dbfs, rms_dbfs
from moogone.analysis.wav import Audio, load_wav, save_wav, synth_noise

# --- Brief's tests, verbatim except for the soundfile import below, which
# --- is moved to module level to satisfy this project's module-level-
# --- imports-only rule (the brief's own draft had it inside the test
# --- function body).


def test_synth_noise_produces_the_requested_level():
    # Round-trip: synth_noise's target vs rms_dbfs's measurement of it.
    # Confirmed by mutation (see task report) that this alone cannot tell
    # apart a correct implementation from one where both sides share the
    # same 10-vs-20 multiplier mistake. Trustworthy only in combination
    # with the anchored sine test below, which pins down rms_dbfs alone.
    audio = synth_noise(seconds=1.0, sample_rate=48000, level_dbfs=-60.0)
    assert rms_dbfs(audio) == pytest.approx(-60.0, abs=0.5)


def test_full_scale_sine_measures_near_minus_three_dbfs():
    # Anchored: a full-scale sine's RMS is 1/sqrt(2) by trigonometry --
    # 20*log10(1/sqrt(2)) = -3.0103 dBFS -- independent of synth_noise or
    # any other function in this codebase. This is what makes the
    # round-trip test above trustworthy: it pins down rms_dbfs on its own.
    t = np.arange(48000) / 48000
    audio = Audio(np.sin(2 * np.pi * 1000 * t), 48000)
    assert rms_dbfs(audio) == pytest.approx(-3.01, abs=0.1)
    assert peak_dbfs(audio) == pytest.approx(0.0, abs=0.1)


def test_noise_floor_ignores_loud_content():
    # Half a second of silence-with-noise, half a second of loud tone.
    # Mixed: the quiet segment's ground truth comes from synth_noise (a
    # round-trip dependency), but the thing actually under test -- does
    # the percentile/window algorithm isolate the quiet windows from the
    # loud ones -- is a real, independent degree of freedom. Confirmed by
    # mutation: replacing noise_floor_dbfs with plain rms_dbfs fails this
    # test outright (rms_dbfs(audio) > -20.0, nowhere near -70).
    quiet = synth_noise(0.5, 48000, -70.0).samples
    t = np.arange(24000) / 48000
    loud = np.sin(2 * np.pi * 440 * t) * 0.8
    audio = Audio(np.concatenate([quiet, loud]), 48000)
    # Plain RMS is dominated by the tone; the floor measurement is not.
    assert rms_dbfs(audio) > -20.0
    assert noise_floor_dbfs(audio) == pytest.approx(-70.0, abs=2.0)


def test_digital_silence_reports_a_finite_floor_not_negative_infinity():
    # Anchored: 20*log10(0) is mathematically -inf. Any implementation
    # that floors the log before returning must report something finite
    # and very negative instead -- an invariant that doesn't depend on any
    # other function being correct.
    audio = Audio(np.zeros(48000), 48000)
    assert noise_floor_dbfs(audio) < -200.0
    assert np.isfinite(noise_floor_dbfs(audio))


def test_wav_round_trips_through_disk(tmp_path):
    # Integration round-trip: save_wav + load_wav + synth_noise + rms_dbfs
    # all have to cooperate. The sample_rate check is a structural anchor
    # (48000 in, 48000 out, no other value would do). The level check is a
    # round-trip that, on its own, would not notice a shared scale-factor
    # mistake between save_wav and load_wav (e.g. both applying and
    # un-applying the same wrong gain). test_save_wav_writes_amplitude_*
    # and test_load_wav_preserves_a_directly_authored_mono_signal below
    # close that gap by anchoring each side independently.
    original = synth_noise(0.25, 48000, -50.0)
    path = tmp_path / "probe.wav"
    save_wav(path, original)
    loaded = load_wav(path)
    assert loaded.sample_rate == 48000
    assert rms_dbfs(loaded) == pytest.approx(-50.0, abs=0.5)


def test_stereo_is_downmixed_to_mono(tmp_path):
    # Anchored for shape only: an all-zeros fixture can't distinguish a
    # correct mean from a bug that just takes one channel and drops the
    # other, since every plausible downmix of all-zero channels is also
    # all zero. test_stereo_downmix_averages_channels_with_known_values
    # below closes that gap with distinct per-channel values.
    path = tmp_path / "stereo.wav"
    sf.write(path, np.zeros((48000, 2)), 48000)
    assert load_wav(path).samples.ndim == 1


# --- Supplementary tests, added beyond the brief. Each closes a specific
# --- anchoring gap identified above, or exercises one of the two
# --- documented consequences of the percentile design (see noise.py).


def test_stereo_downmix_averages_channels_with_known_values(tmp_path):
    # Anchored: mean(0.6, 0.2) = 0.4 is hand-computable arithmetic,
    # independent of save_wav / rms_dbfs / synth_noise entirely. Written
    # directly with soundfile (not save_wav), so this isolates load_wav's
    # downmix. Catches bugs like "take channel 0 only" or "sum instead of
    # average" that an all-zeros fixture cannot.
    path = tmp_path / "stereo_known.wav"
    left = np.full(4800, 0.6)
    right = np.full(4800, 0.2)
    sf.write(path, np.column_stack([left, right]), 48000, subtype="FLOAT")
    loaded = load_wav(path)
    assert loaded.samples.ndim == 1
    assert np.allclose(loaded.samples, 0.4, atol=1e-6)


def test_load_wav_preserves_a_directly_authored_mono_signal(tmp_path):
    # Anchored: checks load_wav's mono path against a file it never wrote
    # itself (bypasses save_wav, unlike test_wav_round_trips_through_disk)
    # and against a ramp rather than a constant, so a bug that reorders or
    # truncates samples -- not just one that gets the average wrong --
    # would also be caught.
    path = tmp_path / "mono_known.wav"
    ramp = np.linspace(-0.5, 0.5, 4800)
    sf.write(path, ramp, 48000, subtype="FLOAT")
    loaded = load_wav(path)
    assert loaded.samples.ndim == 1
    assert loaded.sample_rate == 48000
    assert np.allclose(loaded.samples, ramp, atol=1e-6)


def test_save_wav_writes_amplitude_soundfile_can_read_back_exactly(tmp_path):
    # Anchored: reads the file back with soundfile directly, not through
    # load_wav, so this isolates save_wav -- closing the shared-mistake
    # gap noted in test_wav_round_trips_through_disk. atol=1e-6 accounts
    # for FLOAT32-on-disk rounding (relative error ~1.2e-7, i.e. way
    # smaller than 1e-6 for samples in this range); the value is chosen
    # from that error bound, not picked to make the test pass.
    original = synth_noise(0.1, 48000, -50.0)
    path = tmp_path / "probe_save.wav"
    save_wav(path, original)
    raw, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    assert sample_rate == 48000
    assert raw.shape[1] == 1
    assert np.allclose(raw[:, 0], original.samples, atol=1e-6)


def test_rms_and_peak_dbfs_are_also_finite_on_digital_silence():
    # Anchored, extending the brief's own silence test: rms_dbfs and
    # peak_dbfs share noise_floor_dbfs's _dbfs epsilon floor, but "they
    # share the helper" is a claim worth checking, not assuming. Confirms
    # neither collapses to -inf or NaN either -- the task's explicit ask.
    audio = Audio(np.zeros(48000), 48000)
    assert np.isfinite(rms_dbfs(audio))
    assert np.isfinite(peak_dbfs(audio))


def test_noise_floor_on_continuous_tone_measures_signal_not_true_noise():
    # Documents a real, deliberately-not-fixed limitation: on a recording
    # that is all signal with no quiet gaps, every short window has
    # essentially the same RMS as the whole signal, so the percentile
    # reports the signal's own level, not a noise floor. Measured, not
    # assumed: for this exact algorithm the two values differ by ~5e-15
    # (float noise only). abs=1e-6 leaves six orders of magnitude of
    # headroom over that measurement while still proving the two are the
    # same value, not merely close.
    t = np.arange(48000) / 48000
    audio = Audio(np.sin(2 * np.pi * 440 * t) * 0.5, 48000)
    assert noise_floor_dbfs(audio) == pytest.approx(rms_dbfs(audio), abs=1e-6)


def test_noise_floor_degrades_when_window_exceeds_the_gaps_between_notes():
    # Documents the other consequence named in the task: window length
    # interacts with the content. 25 repetitions of a 20ms loud burst plus
    # a 20ms quiet-with-noise gap (-70 dBFS, deterministic via seed=1) = 1
    # second total. A 10ms window fits inside a 20ms gap; the default 50ms
    # window (longer than the whole 40ms period) never can -- every
    # default-sized window straddles some of the loud burst.
    period = 960  # 20ms @ 48000Hz
    n_periods = 25
    t = np.arange(period) / 48000
    loud_burst = np.sin(2 * np.pi * 1000 * t) * 0.8
    quiet = synth_noise(n_periods * period / 48000, 48000, -70.0, seed=1).samples
    pieces = []
    for i in range(n_periods):
        pieces.append(loud_burst)
        pieces.append(quiet[i * period : (i + 1) * period])
    audio = Audio(np.concatenate(pieces), 48000)

    short_window = noise_floor_dbfs(audio, window_ms=10.0)
    default_window = noise_floor_dbfs(audio)  # window_ms=50.0

    # 10ms fits inside the 20ms gap: recovers close to the true -70 dBFS
    # floor. Tolerance matches test_noise_floor_ignores_loud_content's own
    # abs=2.0 for the same synth_noise(-70) ground truth.
    assert short_window == pytest.approx(-70.0, abs=2.0)
    # The default window can't land purely in a gap. Measured value is
    # -8.93 dBFS -- off by about 61 dB. ">-20.0" mirrors the brief's own
    # style for "clearly contaminated" (test_noise_floor_ignores_loud_
    # content's rms_dbfs bound) rather than pinning an exact number.
    assert default_window > -20.0


def test_noise_floor_percentile_selects_the_exact_order_statistic():
    # Fully deterministic anchor for the percentile parameter -- no RNG
    # involved. 11 back-to-back 50ms windows (the default window_ms), each
    # a *constant* amplitude at a known dB level from -100 to 0 in steps
    # of 10. A constant block's RMS equals its amplitude exactly, so
    # sorted frame_rms == the 11 levels in order. percentile=10 over 11
    # values lands exactly on index 1 (no interpolation needed:
    # 0.10*(11-1) = 1.0), so -90.0 dBFS is the exact answer, not an
    # approximation of one.
    #
    # This does not, by itself, discriminate every window_ms mutation: it
    # catches window_ms growing (e.g. 50->100, confirmed by mutation), but
    # not window_ms shrinking to an exact divisor (e.g. 50->25 halves each
    # 2400-sample block into two still-equal-valued sub-windows, which
    # coincidentally still selects -90.0 at percentile=10). No test in
    # this file catches 50->25 either -- see the task report for why that
    # constant doesn't have a single hand-derivable correct value the way
    # percentile does, and what was tried.
    window = 2400  # 50ms @ 48000Hz, the default window
    levels = list(range(-100, 1, 10))  # -100, -90, ..., 0 (11 values)
    blocks = [np.full(window, 10 ** (level / 20)) for level in levels]
    audio = Audio(np.concatenate(blocks), 48000)

    assert noise_floor_dbfs(audio) == pytest.approx(-90.0, abs=1e-6)


# --- Fix-report tests, added after independent review found that a single
# --- NaN sample silently poisons rms_dbfs/peak_dbfs/noise_floor_dbfs (they
# --- returned NaN instead of raising), that zero-length audio produced
# --- three different behaviours across the three functions, that no test
# --- pinned window_ms's default against its one confirmed-uncaught
# --- mutation (50 -> 25), and that no test exercised a non-FLOAT source
# --- WAV despite "absorbs source bit depth" being stated design intent.
# --- See the "Fix report" section of the task report for the reasoning
# --- behind each decision.


def test_dbfs_raises_on_nan_rather_than_returning_nan():
    # Direct unit test of the chokepoint all three public functions funnel
    # through. This is the closest possible test to the bug the reviewer
    # found: Python's max() returns its first argument on a NaN comparison
    # (max(nan, eps) is nan; max(eps, nan) is eps), so argument order to
    # max() used to be load-bearing and wrong. The fix uses an explicit
    # isfinite guard instead of relying on max()'s argument order at all,
    # which is why this test targets the *behaviour* (raises, doesn't
    # return NaN) rather than the specific line -- see the task report's
    # mutation results for why that is the more robust thing to pin down.
    with pytest.raises(ValueError, match="non-finite"):
        _dbfs(float("nan"))


def test_all_three_measurements_raise_when_a_sample_is_nan_instead_of_returning_nan():
    # Reproduces the reviewer's exact scenario: one corrupted sample inside
    # an otherwise full-scale sine. Before the fix, all three of these
    # returned nan silently -- worst of all for noise_floor_dbfs, whose
    # entire rationale is percentile-based robustness to atypical samples;
    # NaN poisons the per-window *mean* before the percentile step ever
    # runs, so one bad sample bypassed that robustness completely. A
    # silently-returned NaN is worse than a crash here: `if measured <
    # -60.0` evaluates False on NaN without raising, so a corrupted
    # capture could pass a noise-floor gate unnoticed -- the exact failure
    # mode this task was framed around.
    t = np.arange(48000) / 48000
    samples = np.sin(2 * np.pi * 1000 * t)
    samples[12345] = np.nan
    audio = Audio(samples, 48000)

    with pytest.raises(ValueError, match="non-finite"):
        rms_dbfs(audio)
    with pytest.raises(ValueError, match="non-finite"):
        peak_dbfs(audio)
    with pytest.raises(ValueError, match="non-finite"):
        noise_floor_dbfs(audio)


def test_zero_length_audio_raises_the_same_error_from_all_three_functions():
    # Before the fix: rms_dbfs and noise_floor_dbfs returned NaN (from
    # np.mean of an empty array, with only a RuntimeWarning easy to miss),
    # while peak_dbfs raised ValueError from np.max's own "zero-size array
    # to reduction operation" message. Three functions, one degenerate
    # input, three different behaviours. Asserting the *exact same*
    # message from all three (not just "some ValueError") pins them to a
    # single shared decision (_validate_audio) rather than three
    # independent, driftable ones.
    audio = Audio(np.array([]), 48000)
    messages = []
    for fn in (rms_dbfs, peak_dbfs, noise_floor_dbfs):
        with pytest.raises(ValueError) as exc_info:
            fn(audio)
        messages.append(str(exc_info.value))
    assert messages[0] == messages[1] == messages[2]
    assert "zero-length" in messages[0]


def test_noise_floor_window_ms_default_is_pinned_between_25_and_50ms():
    # Closes a gap the reviewer confirmed: window_ms mutated from 50.0 to
    # 25.0 was caught by nothing in this file, including the two tests
    # that already existed to probe window_ms (the order-statistic test's
    # constant blocks coincidentally survive an exact-halving of the
    # window; the 20ms-gap demonstration explicitly overrides window_ms
    # for its "short" side, so it never sees the function's default at
    # all, and its "default" side stays contaminated whether the default
    # is 50 or 25, since both exceed that fixture's 20ms gap).
    #
    # This test's gap is deliberately sized *between* the two candidate
    # values -- 40ms, strictly greater than 25 and strictly less than 50 --
    # so the two window lengths land on opposite sides of a real physical
    # boundary: a window longer than the gap always straddles some of the
    # loud burst either side of it and reads high; a window that fits
    # inside the gap reads the true quiet level. That boundary, not
    # statistical noise, is what separates the two answers, so the
    # tolerance below doesn't need to be loose to stay non-flaky.
    #
    # Measured (not assumed) on this exact fixture: window_ms=25.0 (fits
    # inside the 40ms gap) -> -70.02 dBFS, a near-exact recovery of the
    # true -70 dBFS floor. window_ms=50.0, the current default (does not
    # fit) -> -11.94 dBFS, off by about 58 dB. If the default constant
    # were ever mutated to 25.0 (or anything <= 40ms), the second
    # assertion below would flip from failing-to-fail to failing outright,
    # since the result would land near -70, not above -20.
    gap_ms = 40
    period_samples = int(48000 * gap_ms / 1000) * 2  # burst length == gap length
    half = period_samples // 2
    n_periods = 48000 // period_samples
    t = np.arange(half) / 48000
    loud_burst = np.sin(2 * np.pi * 1000 * t) * 0.8
    quiet = synth_noise(n_periods * half / 48000, 48000, -70.0, seed=1).samples
    pieces = []
    for i in range(n_periods):
        pieces.append(loud_burst)
        pieces.append(quiet[i * half : (i + 1) * half])
    audio = Audio(np.concatenate(pieces), 48000)

    # Control: a 25ms window fits inside the 40ms gap and recovers the
    # true floor. Confirms the fixture itself is sound, independent of
    # whatever the function's current default happens to be.
    assert noise_floor_dbfs(audio, window_ms=25.0) == pytest.approx(-70.0, abs=2.0)
    # The actual pin: the *default* window (no window_ms argument at all)
    # must be too long to fit this 40ms gap. Only true while the default
    # stays > 40ms -- i.e. this fails if the default constant regresses
    # to 25.0, or to anything else <= 40ms.
    assert noise_floor_dbfs(audio) > -20.0


def test_load_wav_absorbs_pcm16_source_bit_depth(tmp_path):
    # "The loader must handle... source bit depth" is stated design
    # intent (task interfaces), but every prior disk-round-trip test wrote
    # subtype="FLOAT" -- nothing exercised a fixed-point source. Written
    # directly with soundfile (not save_wav), consistent with this file's
    # established pattern of testing load_wav against files it never
    # wrote itself. Tolerance is PCM_16's quantization half-step
    # (1/32768 = 3.0518e-5), measured directly rather than assumed: the
    # actual max error on this fixture was 3.0511e-5, i.e. the tolerance
    # below already has headroom, not room carved out to make it pass.
    path = tmp_path / "mono_pcm16.wav"
    ramp = np.linspace(-0.5, 0.5, 4800)
    sf.write(path, ramp, 48000, subtype="PCM_16")
    loaded = load_wav(path)
    assert loaded.samples.ndim == 1
    assert loaded.sample_rate == 48000
    assert np.allclose(loaded.samples, ramp, atol=5e-5)


def test_load_wav_absorbs_pcm24_source_bit_depth(tmp_path):
    # Second bit depth, same rationale as the PCM_16 test above. Tolerance
    # is PCM_24's quantization half-step (1/8388608 = 1.192e-7); measured
    # max error on this fixture was 1.190e-7.
    path = tmp_path / "mono_pcm24.wav"
    ramp = np.linspace(-0.5, 0.5, 4800)
    sf.write(path, ramp, 48000, subtype="PCM_24")
    loaded = load_wav(path)
    assert loaded.samples.ndim == 1
    assert loaded.sample_rate == 48000
    assert np.allclose(loaded.samples, ramp, atol=2e-7)


# --- Fix report round 2: independent review found that the round-1 fix
# --- checked the wrong place. _dbfs's guard inspects the *aggregate*
# --- scalar, which happens to work for rms_dbfs/peak_dbfs (mean and max
# --- both propagate a non-finite sample straight through) but not for
# --- noise_floor_dbfs: a single +inf sample makes its window the
# --- unambiguous *maximum* window RMS, and a low percentile is built to
# --- exclude the maximum -- so the percentile step discards the evidence
# --- of corruption before _dbfs's guard ever sees it. Measured before the
# --- fix: 0/20 window positions raised at the default percentile, and the
# --- realistic case (synth_noise(-70dBFS) plus one +inf sample) silently
# --- returned -70.13 dBFS. See the task report's "Fix report round 2"
# --- section for the full sweep and the reasoning for validating input
# --- samples instead of the output scalar.


def test_noise_floor_dbfs_raises_on_infinite_sample_at_every_window_position():
    # The central finding: at the default percentile=10.0, a +inf sample
    # is *never* selected by the percentile (it's always the maximum of
    # its window, and a low percentile specifically excludes the
    # maximum), so the old output-scalar guard in _dbfs never saw it,
    # regardless of which window the bad sample landed in. Swept across
    # several window positions -- not just one -- because position is
    # exactly what determined whether the old behaviour happened to catch
    # it (it never did, at any of the 20 positions, confirmed directly
    # before writing this test). Uses noise_floor_dbfs with no percentile
    # or window_ms argument, i.e. the exact default configuration the
    # review flagged as silently wrong.
    sample_rate = 48000
    window_samples = 2400  # 50ms @ 48000Hz, the default window
    window_positions = (0, 1, 5, 10, 15, 19)  # spread across all 20 windows
    for w in window_positions:
        for bad_value in (float("inf"), float("-inf")):
            audio = synth_noise(1.0, sample_rate, -70.0, seed=1)
            audio.samples[w * window_samples] = bad_value
            with pytest.raises(ValueError, match="non-finite"):
                noise_floor_dbfs(audio)  # default percentile=10.0, window_ms=50.0


def test_rms_and_peak_dbfs_raise_on_an_infinite_sample():
    # rms_dbfs and peak_dbfs never had noise_floor_dbfs's blind spot --
    # mean and max both propagate +/-inf straight through to the old
    # output-scalar guard -- but nothing in this file had exercised inf
    # specifically (only NaN) before this fix round, and that propagation
    # was true by how those two aggregations happen to behave, not by any
    # guarantee this module made. Confirms both still raise, for both
    # signs, via the new input-level guard.
    t = np.arange(48000) / 48000
    for bad_value in (float("inf"), float("-inf")):
        samples = np.sin(2 * np.pi * 1000 * t).copy()
        samples[100] = bad_value
        audio = Audio(samples, 48000)
        with pytest.raises(ValueError, match="non-finite"):
            rms_dbfs(audio)
        with pytest.raises(ValueError, match="non-finite"):
            peak_dbfs(audio)


def test_validate_audio_does_not_reject_legitimate_edge_inputs():
    # The new input-level guard sweeps np.isfinite over the whole array on
    # every call -- confirms that doesn't have a false-positive edge case
    # that would reject genuinely valid, if unusual, audio: all zeros, a
    # single sample, a nonzero DC constant, and samples sitting at exactly
    # the +/-1.0 full-scale boundary.
    edge_cases = {
        "all_zeros": np.zeros(48000),
        "single_sample": np.array([0.5]),
        "constant_dc": np.full(48000, 0.3),
        "positive_full_scale": np.ones(48000),
        "negative_full_scale": -np.ones(48000),
    }
    for name, samples in edge_cases.items():
        audio = Audio(samples, 48000)
        assert np.isfinite(rms_dbfs(audio)), name
        assert np.isfinite(peak_dbfs(audio)), name
        assert np.isfinite(noise_floor_dbfs(audio)), name
