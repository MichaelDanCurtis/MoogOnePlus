"""Tests for spectral analysis, A-weighting, and SNR.

Same discipline as test_analysis_noise.py: a wrong measurement here doesn't
crash, it returns a plausible, correctly-formatted dBFS number that happens
to be wrong. Every test below is labelled in its comment as one of:

- Anchored: the expected value comes from mathematics external to this
  codebase (trigonometry, the FFT bin-width identity, or the published IEC
  61672 A-weighting curve) -- independent of whether any function in this
  module or noise.py is implemented correctly.
- Cross-check: two independently-implemented functions in this codebase
  (e.g. spectrum() via FFT+window, rms_dbfs() via time-domain mean-square)
  are compared against each other on the same signal. Weaker than a true
  external anchor (a bug shared by both sides could still pass), but still
  meaningful because the two code paths share essentially no logic.
- Round-trip: one function's stated input against another function's
  measurement of it (e.g. synth_noise's target dBFS against rms_dbfs's
  reading). Confirmed elsewhere (see test_analysis_noise.py) that this
  alone cannot distinguish a correct implementation from one where both
  sides share the same mistake.
- Regression: pins a specific defect found in this task's brief before any
  implementation was written (see the task report). These construct the
  exact failure shape the defect described, not a generic case.
"""

import numpy as np
import pytest
import soundfile as sf

from moogone.analysis.noise import noise_floor_dbfs, peak_dbfs, rms_dbfs
from moogone.analysis.spectrum import a_weight_db, a_weighted_dbfs, snr_db, spectrum
from moogone.analysis.wav import Audio, save_stereo_wav, synth_blip, synth_noise


def _sine(freq: float, seconds: float = 1.0, sample_rate: int = 48000, amp: float = 1.0) -> Audio:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return Audio(np.sin(2 * np.pi * freq * t) * amp, sample_rate)


# --- Brief's tests, kept (spectrum shape / A-weighting definition), plus one
# --- corrected comment: the brief's own draft asserted -30.2 dB at 50 Hz but
# --- commented "~-39 dB" above the assertion -- self-contradictory. Verified
# --- independently against the published IEC 61672 curve (see task report):
# --- -30.2 dB is correct, -39 dB is not this curve's value at 50 Hz (it's
# --- closer to the value at ~31.5 Hz). The assertion is unchanged; only the
# --- misleading comment is fixed.


def test_spectrum_peaks_at_the_tone_frequency():
    # Anchored: a pure tone's energy concentrates in the bin nearest its own
    # frequency; that's a property of the DFT, not of this codebase.
    freqs, mags = spectrum(_sine(1000.0))
    assert freqs[int(np.argmax(mags))] == pytest.approx(1000.0, abs=10.0)


def test_spectrum_length_matches_frequency_axis():
    # Anchored: len(rfftfreq(n_fft)) == n_fft // 2 + 1 is a mathematical
    # fact of the real FFT, independent of this implementation.
    freqs, mags = spectrum(_sine(1000.0), n_fft=4096)
    assert len(freqs) == len(mags) == 4096 // 2 + 1


def test_a_weighting_is_near_zero_at_1khz():
    # Anchored: A-weighting is defined as exactly 0 dB at 1 kHz -- the
    # standard's own normalisation point, not a fact about this codebase.
    assert a_weight_db(np.array([1000.0]))[0] == pytest.approx(0.0, abs=0.1)


def test_a_weighting_attenuates_low_frequencies():
    # Anchored: -30.2 dB at 50 Hz is the published IEC 61672 A-weighting
    # value (confirmed independently in the task report: measured -30.27 dB
    # from the formula, standard references round to -30.2 dB -- a 0.07 dB
    # gap). abs=0.3 leaves ~4x headroom over that measured gap while still
    # being tight enough to catch a wrong pole constant (see the
    # constant-perturbation results in the task report).
    assert a_weight_db(np.array([50.0]))[0] == pytest.approx(-30.2, abs=0.3)
    assert a_weight_db(np.array([50.0]))[0] < a_weight_db(np.array([1000.0]))[0]


def test_a_weighted_level_is_lower_for_rumble_than_for_hiss():
    # Cross-check: both tones have identical amplitude (0.1), so their
    # *unweighted* levels are identical -- any gap here comes purely from
    # a_weight_db's shape (40 Hz: -34.54 dB, deep in the attenuated region;
    # 4 kHz: +0.96 dB, past the ~2.5 kHz peak but still in the curve's
    # elevated region), combined with spectrum() correctly placing each
    # tone's energy in the right bin. Measured gap on this exact fixture:
    # 35.28 dB (see task report) -- ">10.0" leaves ~25 dB of margin while
    # still being far stronger than a bare "<" would be.
    rumble = _sine(40.0, amp=0.1)
    hiss = _sine(4000.0, amp=0.1)
    assert a_weighted_dbfs(hiss) - a_weighted_dbfs(rumble) > 10.0


def test_snr_reflects_the_level_difference():
    # Round-trip: synth_noise's claimed level vs rms_dbfs's measurement of
    # it, for the "noise" side. See test_snr_of_two_independently_leveled_
    # sines_matches_the_exact_difference below for the fully anchored
    # version the task asked for; this one additionally exercises the
    # synth_noise integration path the way a real before/after probe would
    # use snr_db.
    signal = _sine(1000.0, amp=1.0)  # -3.01 dBFS RMS
    noise = synth_noise(1.0, 48000, -63.0)  # -63 dBFS RMS
    assert snr_db(signal, noise) == pytest.approx(60.0, abs=1.0)


# --- Anchors beyond the brief: each closes a gap where the brief's own
# --- suite could pass with a wrong constant (see "Constant-perturbation
# --- results" in the task report for which of these actually catch what).


def test_spectrum_peaks_at_an_exact_bin_with_correct_normalisation():
    # Anchored, tightly: choosing a frequency that lands exactly on a bin
    # (k * sample_rate / n_fft) removes scalloping loss entirely, so both
    # claims in the task's anchor list can be checked precisely in one
    # test: "a pure sine peaks in the bin containing f" (exact index, not
    # just close in Hz) and "a full-scale sine reads near 0 dBFS at its
    # peak" (measured 9e-9 dB from exact on this fixture -- abs=0.05 leaves
    # six orders of magnitude of headroom while still catching a broken
    # window-normalisation constant, which shifts this by several dB).
    sample_rate = 48000
    n_fft = 8192
    bin_width = sample_rate / n_fft
    bin_index = 170
    f_exact = bin_index * bin_width  # 996.09375 Hz
    _freqs, mags = spectrum(_sine(f_exact, seconds=1.0, sample_rate=sample_rate), n_fft=n_fft)
    peak = int(np.argmax(mags))
    assert peak == bin_index
    assert mags[peak] == pytest.approx(0.0, abs=0.05)


def test_spectrum_bin_width_equals_sample_rate_over_n_fft():
    # Anchored: bin width is sample_rate / n_fft by definition of the DFT
    # frequency axis -- independent of anything this module computes beyond
    # constructing that axis.
    freqs, _ = spectrum(_sine(1000.0), n_fft=8192)
    assert freqs[1] - freqs[0] == pytest.approx(48000 / 8192, abs=1e-9)


def test_spectrum_default_n_fft_is_8192():
    # Anchored to the documented interface (n_fft=8192 default). The
    # brief's own length test always passes n_fft explicitly, so it can't
    # catch the *default* value changing; this calls spectrum() with no
    # n_fft argument at all.
    freqs, mags = spectrum(_sine(1000.0))
    assert len(freqs) == len(mags) == 8192 // 2 + 1


def test_a_weighting_attenuates_high_frequencies_too():
    # Anchored: -2.5 dB at 10 kHz is a commonly-cited published IEC 61672
    # reference value (measured from this formula: -2.49 dB, a 0.01 dB
    # gap). Added after constant-perturbation testing found a real
    # coverage hole: the 12194.0 Hz pole appears in both the numerator and
    # the high-frequency denominator term, and at every frequency this
    # suite checked elsewhere (<=2.5 kHz, all well below 12194), those two
    # occurrences nearly cancel -- so mutating 12194.0 -> 13000.0
    # everywhere it appears passed all 22 tests before this one was added
    # (see the task report). The cancellation stops holding once f is no
    # longer <<12194; 10 kHz is high enough for the mutation to actually
    # move this value outside tolerance, confirmed directly.
    assert a_weight_db(np.array([10000.0]))[0] == pytest.approx(-2.5, abs=0.3)


def test_a_weighting_is_monotonic_up_to_its_peak_then_down():
    # Anchored: IEC 61672 A-weighting rises monotonically from 20 Hz to a
    # peak near 2.5 kHz, then falls -- stated in the task brief as an
    # external property of the standard, not derived from this codebase.
    # The peak location is *found* within the sampled range rather than
    # hardcoded, so the monotonicity checks on either side are always
    # relative to wherever this implementation's curve actually peaks.
    freqs = np.geomspace(20.0, 20000.0, 500)
    vals = a_weight_db(freqs)
    peak_idx = int(np.argmax(vals))
    assert freqs[peak_idx] == pytest.approx(2500.0, rel=0.15)
    assert np.all(np.diff(vals[: peak_idx + 1]) >= -1e-9)
    assert np.all(np.diff(vals[peak_idx:]) <= 1e-9)


def test_snr_of_two_independently_leveled_sines_matches_the_exact_difference():
    # Anchored, per the task's explicit instruction not to verify snr_db
    # only against synth_noise's own claim: both "signal" and "noise" here
    # are plain sines whose RMS is the trigonometric fact amp/sqrt(2), so
    # neither side depends on synth_noise, spectrum, or a_weight_db at all
    # -- this pins snr_db's subtraction (and its sign/order) directly.
    target_snr_db = 60.0
    signal_amp = 1.0
    signal_rms_db = 20 * np.log10(signal_amp / np.sqrt(2))
    noise_rms_db = signal_rms_db - target_snr_db
    noise_amp = (10 ** (noise_rms_db / 20)) * np.sqrt(2)
    signal = _sine(1000.0, amp=signal_amp)
    noise = _sine(1234.5, amp=noise_amp)  # distinct frequency; snr_db is frequency-blind
    assert snr_db(signal, noise) == pytest.approx(target_snr_db, abs=0.05)


def test_spectrum_total_power_is_consistent_with_time_domain_rms():
    # Cross-check (Parseval-style, per the task's suggested anchor
    # technique): spectrum() (FFT + Hann window) and rms_dbfs() (direct
    # time-domain mean-square) are independent code paths, so agreement
    # between them is meaningful even though neither is an external ground
    # truth here.
    #
    # Not expected to match exactly: spectrum() is calibrated so a
    # bin-centered tone reads its correct *peak* amplitude (coherent-gain
    # calibration -- see test_spectrum_peaks_at_an_exact_bin above), which
    # is a different normalisation goal from a power-conserving PSD
    # estimate for broadband content. The gap decomposes into two
    # independent effects (corrected here after an earlier draft
    # misattributed it to "ENBW plus overlap" -- overlap turns out to
    # contribute almost nothing, see below): ~3.01 dB (10*log10(2)) from
    # squaring an amplitude already doubled for the single-sided fold --
    # correct for one tone's peak, a 2x power overcount when every bin's
    # independent contribution gets the same treatment -- plus ~1.76 dB
    # (10*log10(1.5)) from the Hann window's ENBW. Theoretical total:
    # 10*log10(2*1.5) = 10*log10(3) = 4.77 dB, matching the measured gap on
    # this exact fixture almost exactly. Overlap's contribution was
    # measured directly, not assumed: a zero-overlap single-frame estimate
    # on this same noise gives a 4.72 dB gap, i.e. within 0.05 dB of the
    # default 50%-overlap 22-frame estimate's 4.77 dB. abs=8.0 leaves >3 dB
    # of headroom above the measured gap while still catching a badly
    # broken normalisation (see the task report's constant-perturbation
    # section for what that mutation actually does to this gap).
    noise = synth_noise(2.0, 48000, -20.0)
    time_domain_db = rms_dbfs(noise)
    _freqs, mags = spectrum(noise)
    linear_power = 10 ** (mags / 10.0)
    spectral_total_db = 10.0 * np.log10(np.sum(linear_power))
    assert spectral_total_db == pytest.approx(time_domain_db, abs=8.0)


# --- Regressions: each test below constructs the exact failure shape one of
# --- the four defects found in this task's brief (before any code was
# --- written) would have produced. See the task report for the confirmed,
# --- pre-fix numbers each comment cites.


def test_spectrum_validates_the_full_signal_not_just_the_first_frame():
    # Defect 1 regression: the brief's spectrum() did `audio.samples[:n_fft]`,
    # so a +inf sample beyond the first 8192 samples was never read, and
    # a_weighted_dbfs returned a plausible -67.98 dBFS on this exact kind of
    # corrupted input (confirmed by the reviewer who found this defect).
    # validate_audio must run over the *entire* input array before any
    # n_fft-sized slicing -- this places the bad sample at index 40000, well
    # beyond both n_fft=8192 and several multiples of the 4096-sample hop.
    t = np.arange(48000) / 48000
    samples = np.sin(2 * np.pi * 1000.0 * t)
    samples[40000] = float("inf")
    audio = Audio(samples, 48000)
    with pytest.raises(ValueError, match="non-finite"):
        spectrum(audio)


def test_a_weighted_dbfs_validates_the_full_signal_not_just_the_first_frame():
    # Same defect-1 corruption, through the composed a_weighted_dbfs ->
    # spectrum path -- confirms the guard isn't bypassed by the composition.
    t = np.arange(48000) / 48000
    samples = np.sin(2 * np.pi * 1000.0 * t)
    samples[40000] = float("-inf")
    audio = Audio(samples, 48000)
    with pytest.raises(ValueError, match="non-finite"):
        a_weighted_dbfs(audio)


def test_spectrum_raises_on_zero_length_audio():
    # Defect 2 regression: the brief's zero-padding silently produced an
    # all-(-400 dBFS) spectrum for zero-length input instead of raising.
    audio = Audio(np.array([]), 48000)
    with pytest.raises(ValueError, match="zero-length"):
        spectrum(audio)


def test_a_weighted_dbfs_raises_on_zero_length_audio():
    # Same defect, through a_weighted_dbfs -- the brief's version returned
    # a plausible -200.0 dBFS for empty input.
    audio = Audio(np.array([]), 48000)
    with pytest.raises(ValueError, match="zero-length"):
        a_weighted_dbfs(audio)


def test_all_five_measurements_share_the_exact_same_validation_messages():
    # Defect 3: validate_audio now lives once (wav.py, alongside Audio) and
    # every measurement function across both noise.py and spectrum.py
    # delegates to it rather than defining its own copy. Byte-identical
    # messages -- not just "some ValueError" from each -- is the proof: if
    # spectrum.py had grown its own duplicate check with even slightly
    # different wording, this would catch that drift immediately.
    fns = (rms_dbfs, peak_dbfs, noise_floor_dbfs, spectrum, a_weighted_dbfs)

    zero_length = Audio(np.array([]), 48000)
    zero_length_messages = []
    for fn in fns:
        with pytest.raises(ValueError) as exc_info:
            fn(zero_length)
        zero_length_messages.append(str(exc_info.value))
    assert len(set(zero_length_messages)) == 1
    assert "zero-length" in zero_length_messages[0]

    t = np.arange(48000) / 48000
    bad_samples = np.sin(2 * np.pi * 1000.0 * t)
    bad_samples[100] = float("nan")
    bad_audio = Audio(bad_samples, 48000)
    non_finite_messages = []
    for fn in fns:
        with pytest.raises(ValueError) as exc_info:
            fn(bad_audio)
        non_finite_messages.append(str(exc_info.value))
    assert len(set(non_finite_messages)) == 1
    assert "non-finite" in non_finite_messages[0]


def test_snr_db_raises_on_non_finite_signal_via_inherited_rms_dbfs_guard():
    # Confirms (rather than assumes) that snr_db inherits validation from
    # rms_dbfs for free: snr_db defines no guard of its own.
    t = np.arange(48000) / 48000
    bad = np.sin(2 * np.pi * 1000.0 * t)
    bad[10] = float("inf")
    signal = Audio(bad, 48000)
    noise = synth_noise(1.0, 48000, -60.0)
    with pytest.raises(ValueError, match="non-finite"):
        snr_db(signal, noise)


def test_snr_db_raises_on_non_finite_noise_via_inherited_rms_dbfs_guard():
    t = np.arange(48000) / 48000
    bad = np.sin(2 * np.pi * 1000.0 * t)
    bad[10] = float("inf")
    signal = synth_noise(1.0, 48000, -20.0)
    noise = Audio(bad, 48000)
    with pytest.raises(ValueError, match="non-finite"):
        snr_db(signal, noise)


def test_snr_db_raises_on_zero_length_signal_or_noise():
    valid = synth_noise(1.0, 48000, -40.0)
    empty = Audio(np.array([]), 48000)
    with pytest.raises(ValueError, match="zero-length"):
        snr_db(empty, valid)
    with pytest.raises(ValueError, match="zero-length"):
        snr_db(valid, empty)


def test_spectrum_reflects_content_throughout_the_recording_not_just_the_first_frame():
    # Defect 4 regression: a single 8192-sample frame is ~170 ms of a much
    # longer recording -- the brief's spectrum() silently ignored the rest.
    # On a fixture where the first second is silence and the second second
    # is a full-scale 1 kHz tone, the brief's `samples[:n_fft]` slice reads
    # only silence (confirmed: samples[:8192] is all zero for this exact
    # fixture), so it would report the epsilon floor (~-400 dBFS)
    # everywhere despite the file containing a loud tone. Averaging frames
    # across the whole signal (this implementation: Welch's method, 50%
    # overlap) must show the tone.
    sr = 48000
    t = np.arange(sr) / sr
    silence = np.zeros(sr)
    tone = np.sin(2 * np.pi * 1000.0 * t)
    audio = Audio(np.concatenate([silence, tone]), sr)

    freqs, mags = spectrum(audio)
    tone_bin = int(np.argmin(np.abs(freqs - 1000.0)))
    other_bin = int(np.argmin(np.abs(freqs - 500.0)))

    # Measured with frame-averaging on this exact fixture: -3.79 dBFS at
    # the tone bin (roughly half the frames are pure tone, half pure
    # silence, so ~-3 dB from full scale is the right order of magnitude).
    # -10.0 cleanly separates "some frames saw the tone" (correct) from
    # "no frame ever did" (the old bug, ~-400 dBFS) with ~390 dB of margin
    # on the buggy side and ~6 dB of margin on the correct side.
    assert mags[tone_bin] > -10.0
    # Not just "the whole spectrum went up": an unrelated bin stays down
    # near the leakage floor (measured: -61.06 dBFS).
    assert mags[other_bin] < -40.0
    # Tighter bound, added after constant-perturbation testing found that
    # ">-10.0" alone doesn't discriminate *how* frames get combined:
    # averaging linear magnitude across frames instead of power (a
    # plausible-looking alternative -- and wrong, since power is the
    # additive/averageable quantity, not magnitude or dB) measures -6.80
    # dBFS on this exact fixture, which still satisfies ">-10.0". Measured
    # across several legitimate hop-size choices (50% overlap, no overlap,
    # and a deliberately coarse hop), correct power-averaging stays in
    # [-4.05, -3.64] dBFS on this fixture regardless of hop -- so -5.0
    # cleanly separates "combined by power" (~1 dB of margin on the
    # correct side, across all three hop variants measured) from "combined
    # by magnitude" (~1.8 dB of margin on the wrong side) without pinning
    # the hop size itself, which is a free implementation choice (see the
    # task report).
    assert mags[tone_bin] > -5.0


def test_spectrum_of_a_long_stationary_tone_is_still_near_full_scale_when_averaged():
    # Anchored: averaging across many frames must not systematically bias a
    # stationary signal's reported level. 2 seconds at the default n_fft
    # runs the multi-frame path throughout (22 overlapping frames), not
    # just the single-frame path a short fixture would exercise. Uses a
    # bin-exact frequency (see test_spectrum_peaks_at_an_exact_bin above)
    # so the expected peak is 0 dBFS, not "near 0 dBFS modulo scalloping".
    sr = 48000
    n_fft = 8192
    bin_width = sr / n_fft
    f_exact = 170 * bin_width
    audio = _sine(f_exact, seconds=2.0, sample_rate=sr)
    freqs, mags = spectrum(audio, n_fft=n_fft)
    peak = int(np.argmax(mags))
    assert freqs[peak] == pytest.approx(f_exact, abs=0.01)
    assert mags[peak] == pytest.approx(0.0, abs=0.1)


# --- Post-review fix: independent review found that spectrum()'s single-
# --- sided `* 2.0` fold, applied uniformly to every bin, is wrong for DC
# --- and (when n_fft is even) Nyquist -- neither has a distinct negative-
# --- frequency mirror to fold, so doubling either is a pure +6.02 dB
# --- (20*log10(2)) error with no signal behind it. This bug was inherited
# --- unchanged from the brief's own formula; it wasn't among the four
# --- defects the brief's own review had already found. See the task
# --- report's fix-report section for before/after numbers and the
# --- mutation confirming these tests catch it.


def test_spectrum_dc_content_is_not_doubled():
    # Regression: DC (bin 0) is its own negative-frequency mirror, so it
    # must not be folded via doubling like an interior bin. Full-scale
    # constant input isolates bin 0 cleanly; 1 second at the default
    # n_fft=8192 exercises the multi-frame averaging path (10 frames), not
    # just a single frame, confirming the fix survives averaging.
    sr = 48000
    audio = Audio(np.ones(sr), sr)
    freqs, mags = spectrum(audio)
    assert freqs[0] == 0.0
    assert mags[0] == pytest.approx(0.0, abs=0.05)


def test_spectrum_nyquist_content_is_not_doubled_when_n_fft_is_even():
    # Same defect, the other self-mirrored bin: for even n_fft (8192, the
    # default), the last rfft bin sits exactly at the Nyquist frequency and
    # is also its own mirror, so it must not be doubled either. A
    # full-scale alternating +1/-1 square wave at the Nyquist frequency
    # isolates the last bin cleanly.
    sr = 48000
    n = np.arange(sr)
    audio = Audio(np.where(n % 2 == 0, 1.0, -1.0), sr)
    freqs, mags = spectrum(audio)
    assert freqs[-1] == sr / 2
    assert mags[-1] == pytest.approx(0.0, abs=0.05)


def test_spectrum_last_bin_is_still_doubled_when_n_fft_is_odd():
    # The other half of the same property: for ODD n_fft, rfft's last bin
    # is one step short of the true Nyquist frequency, and its
    # negative-frequency mirror is a genuinely different (if adjacent) bin
    # -- so it must still be doubled, unlike the even-n_fft case above.
    #
    # Not tested via a "reads near 0 dBFS" tone, unlike the interior-bin
    # anchors elsewhere in this file: a tone placed exactly at this bin has
    # its own negative-frequency image only one bin away (rather than far
    # away, as for every other bin), and Hann-window leakage between the
    # two measurably contaminates a naive peak reading even when the fold
    # factor is correct -- confirmed directly while writing this test
    # (measured ~1 dB of contamination on that construction; see task
    # report). That's a separate, narrower effect from the fold decision
    # itself, so this test isolates the fold decision instead: it compares
    # spectrum()'s last-bin reading directly against an independently
    # computed raw FFT magnitude for that same bin, doubled by hand.
    sr = 48000
    n_fft = 8193  # odd
    rng = np.random.default_rng(0)
    samples = rng.standard_normal(n_fft) * 0.1  # arbitrary content, exactly one frame
    audio = Audio(samples, sr)

    window = np.hanning(n_fft)
    raw_last_bin = np.abs(np.fft.rfft(samples * window))[-1]
    expected_dbfs = 20 * np.log10(raw_last_bin * 2.0 / np.sum(window))

    freqs, mags = spectrum(audio, n_fft=n_fft)
    assert freqs[-1] < sr / 2  # confirms this bin is genuinely not Nyquist
    assert mags[-1] == pytest.approx(expected_dbfs, abs=1e-9)


def test_package_level_imports_expose_every_documented_name():
    # Every other test in this file (and in test_analysis_noise.py) imports
    # from submodules directly (moogone.analysis.spectrum, moogone.analysis
    # .wav, ...), so __init__.py's own re-export statements and __all__
    # list were never actually exercised -- a typo there (a misspelled name
    # in the import, or in __all__) would go uncaught. This imports every
    # name from the package level instead.
    import moogone.analysis as ma

    assert set(ma.__all__) == {
        "Audio",
        "a_weight_db",
        "a_weighted_dbfs",
        "load_wav",
        "noise_floor_dbfs",
        "peak_dbfs",
        "rms_dbfs",
        "save_stereo_wav",
        "save_wav",
        "snr_db",
        "spectrum",
        "synth_blip",
        "synth_noise",
        "validate_audio",
    }
    for name in ma.__all__:
        assert hasattr(ma, name), name

    # Exercise a sample of them end-to-end through the package-level names
    # only, not just "the attribute exists" -- catches e.g. a name
    # accidentally bound to the wrong object of the same name.
    audio = ma.synth_noise(0.1, 48000, -40.0, seed=0)
    assert ma.rms_dbfs(audio) == pytest.approx(-40.0, abs=0.5)
    freqs, mags = ma.spectrum(audio)
    assert len(freqs) == len(mags) == 8192 // 2 + 1
    assert ma.snr_db(audio, audio) == pytest.approx(0.0, abs=1e-6)


class TestSynthBlip:
    """The timing fixture. Its attack is the thing being measured, so the shape of
    the first few milliseconds is a property worth pinning, not an implementation
    detail.
    """

    def test_it_starts_abruptly(self):
        blip = synth_blip()
        head = abs(blip.samples[: int(0.001 * blip.sample_rate)]).max()
        assert head > 0.3, (
            "a fade-in would put the measured onset wherever the detector's "
            f"threshold crossed rather than where the sound began; got {head:.3f}"
        )

    def test_it_decays_rather_than_sustaining(self):
        blip = synth_blip()
        n = len(blip.samples)
        first = abs(blip.samples[: n // 8]).max()
        last = abs(blip.samples[-n // 8:]).max()
        assert last < first * 0.2, "must not sustain, or hits would run together"

    def test_it_stays_inside_full_scale(self):
        assert abs(synth_blip().samples).max() <= 1.0

    def test_it_is_deterministic(self):
        assert np.array_equal(synth_blip().samples, synth_blip().samples)

    def test_zero_length_is_refused(self):
        with pytest.raises(ValueError, match="positive"):
            synth_blip(seconds=0)

    def test_saved_stereo_is_what_the_voice_will_accept(self, tmp_path):
        path = tmp_path / "blip.wav"
        save_stereo_wav(path, synth_blip(seconds=0.05))
        info = sf.info(str(path))
        # Sampler.load rejects anything that is not two channels, by name.
        assert info.channels == 2
        assert info.samplerate == 48000
