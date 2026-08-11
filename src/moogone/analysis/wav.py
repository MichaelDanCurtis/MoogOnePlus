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
