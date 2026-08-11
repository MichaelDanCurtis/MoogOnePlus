"""Audio loading, saving, and synthetic fixtures.

Everything downstream works in mono float64 normalised to -1..1, so the
measurement code never has to care about source bit depth or channel count.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class Audio:
    samples: np.ndarray  # mono, float64, -1..1
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def validate_audio(audio: Audio) -> None:
    """Raise before any analysis touches the samples: zero-length audio, or
    any non-finite sample (NaN or +/-inf) anywhere in the array.

    This has to run over the *input* samples, before any windowing,
    slicing, or aggregation -- not just on a final scalar handed to a
    dB-conversion helper. A single +inf sample can be silently discarded by
    a downstream computation before any output-side check ever sees it:
    noise_floor_dbfs's percentile step excludes it (it's always the maximum
    of its window, and a low percentile is built to exclude the maximum),
    and spectrum()'s single-frame slice excludes it entirely if it falls
    beyond the first n_fft samples. Both are the same shape of bug --
    evidence discarded before inspection -- so the guard belongs once, here,
    on the input every analysis function shares, rather than duplicated (and
    potentially forgotten) per module.

    Lives alongside Audio rather than in noise.py or spectrum.py: it
    validates the *type*, not any one module's metrics, and every module
    that consumes an Audio needs the same guarantee before it starts
    computing. noise.py and spectrum.py both import this rather than
    defining their own copy.
    """
    if len(audio.samples) == 0:
        raise ValueError("cannot compute a level from zero-length audio")
    if not np.all(np.isfinite(audio.samples)):
        raise ValueError(
            "cannot compute a level: the audio contains a non-finite sample "
            "(NaN or +/-inf) -- e.g. from a dropped sample during capture -- "
            "rather than actual silence. Treat the capture as invalid "
            "instead of trusting a level computed from it."
        )


def load_wav(path: str | Path) -> Audio:
    samples, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    return Audio(samples.mean(axis=1), sample_rate)


def save_wav(path: str | Path, audio: Audio) -> None:
    sf.write(str(path), audio.samples, audio.sample_rate, subtype="FLOAT")


def synth_noise(seconds: float, sample_rate: int, level_dbfs: float, seed: int = 0) -> Audio:
    """White noise at a known RMS level. The fixture that validates the rig:
    if the analyser reports -60 dBFS for this at level_dbfs=-60, it is honest.
    """
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal(int(seconds * sample_rate))
    raw /= np.sqrt(np.mean(raw**2))  # normalise to unit RMS
    return Audio(raw * (10 ** (level_dbfs / 20)), sample_rate)
