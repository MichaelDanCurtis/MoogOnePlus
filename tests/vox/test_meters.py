"""Meters. Parsing must reject garbage; dBFS must be right; the mock must actually vary."""

import math

import pytest

from moogone.osc import OscMessage
from moogone.vox.meters import (
    METER_ADDRESSES,
    MockMeterSource,
    SshMeterSource,
    parse_meter_batch,
    to_dbfs,
)


def _hex(addr, lo, hi):
    return OscMessage(addr, [lo, hi]).encode().hex()


class TestParse:
    def test_parses_four_channels(self):
        text = "\n".join(f"{a}\t{_hex(a, -1e-5, 2e-5)}" for a in METER_ADDRESSES)
        got = parse_meter_batch(text)
        assert set(got) == set(METER_ADDRESSES)
        assert got["/a/stat/mainl"] == pytest.approx((-1e-5, 2e-5), rel=1e-4)

    def test_missing_channel_is_absent_not_zero(self):
        """A dropped reply must not render as silence — silence is a real reading."""
        text = f"/a/stat/mainl\t{_hex('/a/stat/mainl', 0.1, 0.2)}\n/a/stat/mainr\t"
        got = parse_meter_batch(text)
        assert "/a/stat/mainl" in got and "/a/stat/mainr" not in got

    def test_garbage_row_is_skipped(self):
        assert parse_meter_batch("/a/stat/mainl\tzz") == {}

    def test_404_is_not_a_reading(self):
        raw = OscMessage("/a/stat/mainl", ["404", "Not found"]).encode().hex()
        assert parse_meter_batch(f"/a/stat/mainl\t{raw}") == {}

    def test_ack_with_no_args_is_not_a_reading(self):
        raw = OscMessage("/a/stat/mainl", []).encode().hex()
        assert parse_meter_batch(f"/a/stat/mainl\t{raw}") == {}


class TestDbfs:
    def test_full_scale_is_zero(self):
        assert to_dbfs(-1.0, 1.0) == pytest.approx(0.0)

    def test_idle_floor_matches_the_session_numbers(self):
        # measured idle: ~3e-5 peak -> about -90 dBFS
        assert to_dbfs(-3e-5, 3e-5) == pytest.approx(-90.5, abs=0.5)

    def test_silence_is_minus_infinity_not_an_error(self):
        assert to_dbfs(0.0, 0.0) == -math.inf


class TestMock:
    def test_varies_between_reads(self):
        m = MockMeterSource(seed=1)
        a, b = m.read(), m.read()
        assert a != b
        assert set(a) == set(METER_ADDRESSES)

    def test_is_badged_untested_not_live(self):
        """Synthetic numbers must never wear the live badge."""
        assert MockMeterSource().badge.state == "untested"


class TestSsh:
    def test_is_badged_untested_and_builds_four_queries(self):
        s = SshMeterSource("192.0.2.1")
        assert s.badge.state == "untested"
        script = s.script()
        assert all(a in script for a in METER_ADDRESSES)
        assert script.count("nc -u") == 4
