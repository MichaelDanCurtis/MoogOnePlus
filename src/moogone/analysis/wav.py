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


def synth_blip(
    seconds: float = 0.35,
    sample_rate: int = 48000,
    pitch: float = 880.0,
    seed: int = 7,
) -> Audio:
    """A short pitched blip with an abrupt start, for timing the audio path.

    The attack is what gets measured, so there is deliberately no fade-in: a
    ramp would put the onset wherever the detector's threshold happened to
    cross rather than where the sound began. The transient at the head makes it
    findable by envelope alone, and the pitch keeps it clear of an analog
    voice's fundamental so the two can be told apart in one recording.
    """
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    body = (
        np.sin(2 * np.pi * pitch * t)
        + 0.5 * np.sin(2 * np.pi * pitch * 2 * t)
        + 0.25 * np.sin(2 * np.pi * pitch * 3 * t)
    )
    click = np.exp(-t * 400.0) * np.random.default_rng(seed).standard_normal(t.size) * 0.7
    return Audio(np.clip((body * np.exp(-t * 14.0) + click) * 0.55, -1.0, 1.0), sample_rate)


def save_stereo_wav(path: str | Path, audio: Audio) -> None:
    """Write mono samples to a two-channel file.

    The sampler's voice reads two channels and refuses anything else, so a mono
    fixture has to be doubled before it can be loaded on the instrument.
    """
    stereo = np.column_stack([audio.samples, audio.samples])
    sf.write(str(path), stereo, audio.sample_rate, subtype="PCM_16")
