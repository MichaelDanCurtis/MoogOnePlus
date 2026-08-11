"""Level and noise-floor measurement."""

import numpy as np

from .wav import Audio, validate_audio

# Floor for the log, so digital silence yields a large negative number
# rather than -inf. -400 dBFS is far below any real signal.
_EPS = 1e-20


def _dbfs(value: float) -> float:
    """Convert a linear amplitude/RMS value to dBFS, flooring near-zero
    values so digital silence reads as a large negative number instead of
    -inf.

    Raises ValueError for NaN or +/-inf rather than letting either
    propagate. This is a *secondary* backstop against a non-finite
    aggregate (e.g. overflow while squaring an unrealistically large
    sample) -- the primary defence is validate_audio (wav.py), which checks
    every input sample before any aggregation runs. Checking only here,
    downstream of the computation, is not sufficient on its own: see
    validate_audio's docstring for why.
    """
    value = float(value)
    if not np.isfinite(value):
        raise ValueError(
            f"cannot compute a dBFS level from a non-finite value ({value!r}). "
            "The audio contains an invalid sample -- e.g. NaN from a dropped "
            "sample during capture -- rather than actual silence. Treat the "
            "capture as invalid instead of trusting a level computed from it."
        )
    return 20.0 * np.log10(max(_EPS, value))


def rms_dbfs(audio: Audio) -> float:
    """Overall RMS level. On a recording with content, this measures the
    content -- use noise_floor_dbfs for the floor."""
    validate_audio(audio)
    return _dbfs(np.sqrt(np.mean(audio.samples**2)))


def peak_dbfs(audio: Audio) -> float:
    validate_audio(audio)
    return _dbfs(np.max(np.abs(audio.samples)))


def noise_floor_dbfs(audio: Audio, percentile: float = 10.0, window_ms: float = 50.0) -> float:
    """RMS of the quietest windows.

    A recording of a synth is mostly signal, so plain RMS measures the note.
    Taking a low percentile of short-window RMS values measures the gaps,
    which is what 'noise floor' means when someone complains about hiss.

    Two known limitations, worth knowing rather than discovering by
    surprise on real hardware:

    - On a recording that is all signal with no quiet gaps at all (a
      sustained drone, a continuous test tone), every window has close to
      the same RMS as the whole signal, so this measures the quietest part
      of the signal, not noise. There is no gap for the percentile to find.
    - The window length has to suit the content. Too short relative to the
      noise's own correlation time makes the per-window RMS estimate
      noisy; too long relative to the gaps between notes means no window
      can land purely inside a gap, so the estimate gets pulled toward
      whatever signal shares the window -- the default 50ms is longer than
      many staccato gaps and will under-report how quiet a recording
      really is in that case. Pass a shorter window_ms for material with
      short gaps.
    """
    validate_audio(audio)
    window = max(1, int(audio.sample_rate * window_ms / 1000))
    usable = len(audio.samples) - (len(audio.samples) % window)
    if usable == 0:
        return rms_dbfs(audio)
    frames = audio.samples[:usable].reshape(-1, window)
    frame_rms = np.sqrt(np.mean(frames**2, axis=1))
    return _dbfs(np.percentile(frame_rms, percentile))
