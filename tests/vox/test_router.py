"""Routing. The discriminating cases: no change means no write; a rate limit that actually limits."""

import pytest

from moogone.vox.router import CURVES, Route, Router


class TestCurves:
    def test_endpoints_are_fixed_for_every_curve(self):
        for name, fn in CURVES.items():
            assert fn(0.0) == pytest.approx(0.0), name
            assert fn(1.0) == pytest.approx(1.0), name

    def test_exp_is_below_linear_in_the_middle_and_log_above(self):
        assert CURVES["exp"](0.5) < 0.5 < CURVES["log"](0.5)

    def test_s_curve_is_symmetric(self):
        assert CURVES["s"](0.25) == pytest.approx(1 - CURVES["s"](0.75))

    def test_unknown_curve_is_rejected_at_construction(self):
        with pytest.raises(ValueError, match="curve"):
            Route("a", "x", "d", curve="wiggly")


class TestRouting:
    def test_scales_into_range(self):
        r = Router()
        r.add(Route("a", "x", "d", lo=10, hi=20))
        assert r.tick({"x": 0.5}, 0.01, 0.0) == [("d", 15.0)]

    def test_invert(self):
        r = Router()
        r.add(Route("a", "x", "d", invert=True))
        assert r.tick({"x": 1.0}, 0.01, 0.0) == [("d", 0.0)]

    def test_clamps_source_to_unit_interval(self):
        r = Router()
        r.add(Route("a", "x", "d", lo=0, hi=1))
        assert r.tick({"x": 7.0}, 0.01, 0.0) == [("d", 1.0)]

    def test_unchanged_value_produces_no_write(self):
        """The core property. Writing the same value at 200 Hz floods the server for nothing."""
        r = Router()
        r.add(Route("a", "x", "d"))
        assert r.tick({"x": 0.3}, 0.01, 0.0) == [("d", 0.3)]
        assert r.tick({"x": 0.3}, 0.01, 0.1) == []

    def test_missing_source_is_skipped_not_zeroed(self):
        r = Router()
        r.add(Route("a", "x", "d"))
        assert r.tick({}, 0.01, 0.0) == []

    def test_remove(self):
        r = Router()
        rid = r.add(Route("a", "x", "d"))
        assert r.remove(rid) is True
        assert r.remove(rid) is False
        assert r.tick({"x": 0.5}, 0.01, 0.0) == []

    def test_auto_id_when_blank(self):
        r = Router()
        rid = r.add(Route("", "x", "d"))
        assert rid and r.routes()[0].id == rid


class TestRateLimit:
    def test_second_write_inside_interval_is_held_and_coalesced(self):
        r = Router(min_interval=0.05)
        r.add(Route("a", "x", "d"))
        assert r.tick({"x": 0.1}, 0.01, 0.00) == [("d", 0.1)]
        assert r.tick({"x": 0.2}, 0.01, 0.01) == []  # inside the window: held
        assert r.tick({"x": 0.3}, 0.01, 0.02) == []  # still held, latest value replaces
        assert r.tick({"x": 0.3}, 0.01, 0.06) == [("d", 0.3)]  # window over: one write, latest

    def test_held_value_is_flushed_when_the_source_goes_quiet(self):
        """A value held by the rate limit must still land once the window expires,
        even if no newer source value arrives to trigger it."""
        r = Router(min_interval=0.05)
        r.add(Route("a", "x", "d"))
        r.tick({"x": 0.1}, 0.01, 0.00)
        r.tick({"x": 0.9}, 0.01, 0.01)  # held
        assert r.tick({}, 0.01, 0.06) == [("d", 0.9)]

    def test_two_destinations_limited_independently(self):
        r = Router(min_interval=0.05)
        r.add(Route("a", "x", "d1"))
        r.add(Route("b", "x", "d2"))
        w = r.tick({"x": 0.5}, 0.01, 0.0)
        assert sorted(w) == [("d1", 0.5), ("d2", 0.5)]


class TestSlew:
    def test_slew_limits_rate_of_change_from_the_bottom_of_the_range(self):
        r = Router(min_interval=0.0)
        r.add(Route("a", "x", "d", slew=1.0))  # full range takes 1 s
        assert r.tick({"x": 1.0}, 0.1, 0.0) == [("d", pytest.approx(0.1))]
        assert r.tick({"x": 1.0}, 0.1, 0.1) == [("d", pytest.approx(0.2))]

    def test_zero_slew_is_immediate(self):
        r = Router(min_interval=0.0)
        r.add(Route("a", "x", "d", slew=0.0))
        assert r.tick({"x": 1.0}, 0.001, 0.0) == [("d", 1.0)]
