"""Record the instrument's ANALOG output, through an audio interface on the Mac.

Everything else in this project measures inside the digital domain, which is what
made the DSP verdict trustworthy — the signal never touched a converter. That is
also its limit. The noise a person actually hears has been through the DAC, the
analog output stage and the cable, and none of those appear in a recording taken
from inside `scsynth`.

This closes that gap. Moog One main outs into an interface, interface into here.

The number that matters is **SNR, not level**. Comparing a recording with a makeup
gain applied against one without it is meaningless in absolute terms — the second is
simply louder. What settles which end of the instrument dominates is whether the
ratio between signal and noise improves:

    unchanged SNR   the noise arrives with the signal, from the analog voice path
                    and its ADC, and driving the output harder cannot help it
    improved SNR    the noise is being added after the digital domain, by the DAC
                    or the output stage, and the makeup gain is worth keeping
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


class CaptureError(RuntimeError):
    """No interface, or one that will not record, and why."""


@dataclass(frozen=True)
class Levels:
    peak_dbfs: float
    rms_dbfs: float
    floor_dbfs: float

    def snr_against(self, quiet: Levels) -> float:
        """Signal-to-noise: this recording's peak over a quiet one's floor."""
        return self.peak_dbfs - quiet.floor_dbfs


def _dbfs(value: float) -> float:
    return 20.0 * math.log10(max(float(value), 1e-12))


def levels(samples: np.ndarray, sample_rate: int, window_ms: float = 50.0,
           percentile: float = 10.0) -> Levels:
    """Peak, rms, and a floor taken as a low percentile of short-window rms.

    The floor is a percentile rather than a minimum because one anomalously quiet
    window — a buffer glitch, a gap between blocks — would otherwise set it, and a
    noise floor read off a single sample is not a measurement.
    """
    x = np.asarray(samples, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    if x.size == 0:
        raise CaptureError("nothing was recorded")
    w = max(1, int(sample_rate * window_ms / 1000.0))
    usable = x[: x.size // w * w]
    if usable.size < w:
        raise CaptureError(f"recording is shorter than one {window_ms} ms window")
    frames = usable.reshape(-1, w)
    rms = np.sqrt((frames**2).mean(axis=1))
    return Levels(
        peak_dbfs=_dbfs(np.max(np.abs(x))),
        rms_dbfs=_dbfs(np.sqrt((x**2).mean())),
        floor_dbfs=_dbfs(np.percentile(rms, percentile)),
    )


def input_devices() -> list[dict]:
    import sounddevice as sd

    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"],
         "samplerate": d["default_samplerate"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def find_device(substring: str) -> int:
    """The index of the first input device whose name contains `substring`."""
    needle = substring.lower()
    for d in input_devices():
        if needle in d["name"].lower():
            return d["index"]
    names = ", ".join(d["name"] for d in input_devices())
    raise CaptureError(f"no input device matching {substring!r}; found: {names}")


def record(seconds: float, device: int, channels: int = 2,
           sample_rate: int = 48000) -> tuple[np.ndarray, int]:
    """Record from an interface. Returns (samples, sample_rate)."""
    import sounddevice as sd

    if seconds <= 0:
        raise CaptureError("seconds must be positive")
    try:
        data = sd.rec(int(sample_rate * seconds), samplerate=sample_rate,
                      channels=channels, device=device, dtype="float32")
        sd.wait()
    except Exception as exc:
        raise CaptureError(f"could not record from device {device}: {exc}") from exc
    return np.asarray(data, dtype=np.float64), sample_rate


def scan_channels(seconds: float, device: int, channels: int,
                  sample_rate: int = 48000) -> list[Levels]:
    """Level per input channel — which sockets the instrument is actually plugged into."""
    data, sr = record(seconds, device, channels=channels, sample_rate=sample_rate)
    return [levels(data[:, ch], sr) for ch in range(data.shape[1])]
