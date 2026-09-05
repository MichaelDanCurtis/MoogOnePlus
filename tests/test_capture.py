"""Tests for the analog capture side.

No interface is needed: what can go wrong here is the arithmetic and the framing, and
those are checked against signals built to have a known answer.
"""

from __future__ import annotations

import numpy as np
import pytest

from moogone.capture import CaptureError, Levels, levels


def tone(seconds=1.0, sr=48000, amp=0.5, freq=1000.0):
    t = np.arange(int(sr * seconds)) / sr
    return amp * np.sin(2 * np.pi * freq * t), sr


class TestLevels:
    def test_peak_of_a_known_sine(self):
        x, sr = tone(amp=0.5)
        assert levels(x, sr).peak_dbfs == pytest.approx(-6.02, abs=0.05)

    def test_rms_of_a_sine_is_3dB_below_its_peak(self):
        x, sr = tone(amp=1.0)
        lv = levels(x, sr)
        assert lv.rms_dbfs == pytest.approx(-3.01, abs=0.05)

    def test_floor_ignores_the_loud_part(self):
        # Half a second of tone, half of quiet noise: the floor must find the quiet.
        sr = 48000
        loud, _ = tone(0.5, sr, amp=0.5)
        quiet = np.random.default_rng(0).normal(0, 10 ** (-80 / 20), sr // 2)
        lv = levels(np.concatenate([loud, quiet]), sr)
        assert lv.peak_dbfs == pytest.approx(-6.02, abs=0.1)
        assert -85 < lv.floor_dbfs < -70, lv.floor_dbfs

    def test_a_single_quiet_window_does_not_set_the_floor(self):
        # One digital-silence window among noise. A minimum would report -inf; a
        # percentile reports the noise, which is the honest answer.
        sr = 48000
        x = np.random.default_rng(1).normal(0, 10 ** (-60 / 20), sr)
        x[: sr // 20] = 0.0
        assert levels(x, sr).floor_dbfs > -75

    def test_stereo_is_mixed_not_rejected(self):
        x, sr = tone(amp=0.5)
        assert levels(np.stack([x, x], axis=1), sr).peak_dbfs == pytest.approx(-6.02, abs=0.05)

    def test_empty_input_is_refused(self):
        with pytest.raises(CaptureError, match="nothing was recorded"):
            levels(np.array([]), 48000)

    def test_a_recording_shorter_than_a_window_is_refused(self):
        with pytest.raises(CaptureError, match="shorter than one"):
            levels(np.zeros(10), 48000)

    def test_digital_silence_does_not_produce_negative_infinity(self):
        assert levels(np.zeros(48000), 48000).peak_dbfs == pytest.approx(-240, abs=1)


class TestSnr:
    def test_snr_is_peak_over_a_quiet_recordings_floor(self):
        loud = Levels(peak_dbfs=-6.0, rms_dbfs=-9.0, floor_dbfs=-40.0)
        quiet = Levels(peak_dbfs=-80.0, rms_dbfs=-90.0, floor_dbfs=-94.0)
        assert loud.snr_against(quiet) == pytest.approx(88.0)

    def test_snr_is_level_independent(self):
        """The whole reason SNR is the comparison and level is not.

        A recording made 12 dB louder with the same noise has a better SNR; one where
        the noise came up with it does not. Comparing peaks alone cannot tell those
        apart, which is the trap this measurement exists to avoid.
        """
        quiet = Levels(-80, -90, -94.0)
        louder_all = Levels(-6, -9, -40.0)
        assert louder_all.snr_against(quiet) == pytest.approx(88.0)
