"""Spectral analysis, A-weighting, and SNR.

This is the module that answers *where* noise sits spectrally: a flat rise
across the band points at converters (a hardware ceiling), a shaped one
usually points at a digital effects algorithm (fixable). Getting this wrong
doesn't crash -- it returns a confident, correctly-formatted dBFS number
that happens to be measuring the wrong thing, so every function here
validates its full input before it starts analysing it (see
wav.validate_audio) rather than discovering corruption partway through.
"""

import numpy as np

from .noise import _dbfs, rms_dbfs
from .wav import Audio, validate_audio


def spectrum(audio: Audio, n_fft: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """Single-sided magnitude spectrum in dBFS, Hann-windowed and averaged
    across frames (Welch's method).

    Returns (frequencies_hz, magnitudes_dbfs). Use this to see *where* the
    noise sits -- a flat rise is converter noise, a shaped one is usually
    algorithmic.

    A single n_fft=8192 frame is ~170 ms at 48 kHz -- a small fraction of a
    multi-second capture, and liable to land on whatever transient happens
    to sit at the start of the file. Instead of analysing one frame, this
    slides an n_fft-sized, 50%-overlapping Hann window across the *entire*
    input and averages *power* (not dB, and not linear magnitude -- power
    is the physically correct quantity to average) across all of them. For
    audio no longer than n_fft, this reduces to a single zero-padded frame,
    same as analysing one frame directly.

    Trade-off worth knowing: averaging is the right choice for a steady
    noise floor (which is what this toolkit is for -- see the harness in
    Task 13), but it smooths over one-off transients the same way a long
    exposure photo blurs a moving object. A spectrum computed this way
    cannot tell you *when* within the recording something happened, only
    that it did. If you need to localise an event in time, use a shorter
    recording or a spectrogram (not provided here) instead of this
    function.

    Calibration note: the window-loss correction below (fold / sum(window))
    is a *coherent-gain* calibration -- it makes a bin-centered full-scale
    sine read ~0 dBFS at its peak, which is the anchor this function is
    checked against. That is a different normalisation goal from a
    power-conserving PSD estimate for broadband content: summing every
    bin's power under this calibration systematically overstates total
    signal power relative to the time-domain RMS by ~4.77 dB (measured; see
    test_spectrum_total_power_is_consistent_with_time_domain_rms), which
    decomposes into two independent effects, not one: ~3.01 dB
    (10*log10(2)) from squaring an amplitude that was already doubled for
    the single-sided fold -- correct for reading one tone's peak, but a 2x
    overcount in power once every bin's independent contribution gets the
    same treatment -- plus ~1.76 dB (10*log10(1.5)) from the Hann window's
    ENBW (its coherent gain and its power gain differ by a factor of 1.5).
    Overlap contributes negligibly to this gap: measured directly, a
    zero-overlap single-frame estimate and the default 50%-overlap
    multi-frame estimate land within ~0.1 dB of each other. This function
    optimises for "where does a tone/hiss band sit and how loud does it
    read at its peak", not for "reconstruct total power exactly" -- the
    former is what a noise-floor diagnosis needs.
    """
    validate_audio(audio)
    samples = audio.samples
    window = np.hanning(n_fft)
    window_sum = np.sum(window)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / audio.sample_rate)

    # Single-sided conversion: fold each bin's negative-frequency mirror by
    # doubling its amplitude -- except bins that have no distinct mirror to
    # fold, which are their own mirror instead. DC (bin 0) always is. The
    # last rfft bin is too, but *only* when n_fft is even: that's exactly
    # when it sits at the true Nyquist frequency (n_fft/2, an integer bin
    # index only for even n_fft). For odd n_fft, rfft's last bin is one
    # step short of Nyquist and its mirror is a distinct, adjacent bin, so
    # it must still be doubled like any interior bin. Doubling a
    # self-mirrored bin is a pure +6.02 dB (20*log10(2)) error with no
    # signal behind it -- confirmed by direct construction (full-scale DC
    # and full-scale Nyquist-rate content both read exactly this much high
    # before this fix; see the task report's fix-report section).
    fold = np.full(n_fft // 2 + 1, 2.0)
    fold[0] = 1.0
    if n_fft % 2 == 0:
        fold[-1] = 1.0

    if len(samples) <= n_fft:
        frames = [np.pad(samples, (0, n_fft - len(samples)))]
    else:
        hop = n_fft // 2  # 50% overlap: standard for Hann-windowed Welch averaging
        n_frames = 1 + (len(samples) - n_fft) // hop
        frames = [samples[i * hop : i * hop + n_fft] for i in range(n_frames)]

    # Average *power* across frames, not dB and not linear magnitude -- power
    # is additive/averageable; dB and linear magnitude are not (averaging dB
    # values understates level, since dB compresses the top of the range).
    power_sum = np.zeros(n_fft // 2 + 1)
    for frame in frames:
        spec_lin = np.abs(np.fft.rfft(frame * window)) * fold / window_sum
        power_sum += spec_lin**2
    magnitude = np.sqrt(power_sum / len(frames))

    return freqs, np.array([_dbfs(m) for m in magnitude])


def a_weight_db(freqs_hz: np.ndarray) -> np.ndarray:
    """IEC 61672 A-weighting curve, normalised to 0 dB at 1 kHz.

    Standard pole frequencies (20.6, 107.7, 737.9, 12194.0 Hz) and the
    +2.0 dB normalisation constant, independently verified against the
    published curve: 0.0001 dB at 1 kHz, -30.27 dB at 50 Hz (published
    reference: -30.2 dB), peak +1.27 dB at ~2513 Hz (published: "near
    2.5 kHz") -- see the task report for the full verification sweep.
    """
    f = np.asarray(freqs_hz, dtype=float)
    f2 = f**2
    numerator = (12194.0**2) * (f2**2)
    denominator = (f2 + 20.6**2) * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2)) * (f2 + 12194.0**2)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(denominator > 0, numerator / denominator, 1e-20)
    return 20.0 * np.log10(np.maximum(ratio, 1e-20)) + 2.0


def a_weighted_dbfs(audio: Audio, n_fft: int = 8192) -> float:
    """Overall level with A-weighting applied.

    Hiss is a perceptual complaint. An unweighted figure counts inaudible
    rumble as heavily as the 2-5 kHz band where hiss actually lives.

    No separate validate_audio call here: spectrum() validates the full
    input before this function does anything else with it, so that
    protection is inherited rather than duplicated (confirmed by test,
    not merely assumed -- see test_a_weighted_dbfs_validates_the_full_
    signal_not_just_the_first_frame and
    test_a_weighted_dbfs_raises_on_zero_length_audio).
    """
    freqs, mags = spectrum(audio, n_fft)
    weighted = mags + a_weight_db(freqs)
    power = np.sum(10 ** (weighted / 10.0))
    return 10.0 * np.log10(max(power, 1e-20))


def snr_db(signal: Audio, noise: Audio) -> float:
    """Signal-to-noise ratio from two recordings: one with content, one
    without.

    No validate_audio call here either: rms_dbfs validates each of its own
    arguments before this subtraction runs, so a non-finite or zero-length
    `signal` or `noise` raises from within the corresponding rms_dbfs call,
    not from any check local to this function. Confirmed by test, not
    assumed -- see test_snr_db_raises_on_non_finite_signal_via_inherited_
    rms_dbfs_guard and its siblings.
    """
    return rms_dbfs(signal) - rms_dbfs(noise)
