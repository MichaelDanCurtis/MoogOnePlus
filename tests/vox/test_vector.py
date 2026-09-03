"""Vector synthesis. The discriminating cases: a corner that omits a control must not
drag it toward zero, and the orbit must stay on the square.
"""

import math

import pytest

from moogone.vox.vector import (
    CORNER_XY,
    CORNERS,
    Clock,
    Motion,
    Orbit,
    VectorEngine,
    blend,
    surface,
    weights,
)


class TestWeights:
    def test_always_sums_to_one(self):
        for x in (0.0, 0.25, 0.5, 0.9, 1.0):
            for y in (0.0, 0.33, 1.0):
                assert sum(weights(x, y).values()) == pytest.approx(1.0)

    @pytest.mark.parametrize("corner", CORNERS)
    def test_each_corner_owns_its_own_position(self, corner):
        x, y = CORNER_XY[corner]
        w = weights(x, y)
        assert w[corner] == pytest.approx(1.0)
        assert sum(v for k, v in w.items() if k != corner) == pytest.approx(0.0)

    def test_centre_is_an_even_quarter_each(self):
        assert all(v == pytest.approx(0.25) for v in weights(0.5, 0.5).values())

    def test_clamps_outside_the_square(self):
        assert weights(-3, 7) == weights(0.0, 1.0)


class TestBlend:
    def test_midpoint_of_two_corners(self):
        c = {"A": {"p": 0.0}, "B": {"p": 1.0}, "C": {"p": 1.0}, "D": {"p": 0.0}}
        assert blend(c, 0.5, 0.5)["p"] == pytest.approx(0.5)
        assert blend(c, 0.0, 0.0)["p"] == pytest.approx(0.0)
        assert blend(c, 1.0, 0.0)["p"] == pytest.approx(1.0)

    def test_a_path_only_one_corner_defines_fades_in_toward_that_corner(self):
        """The property that makes partial corners usable.

        With renormalisation, standing on A gives A's value. Without it, three empty
        corners would drag the result to a quarter of it — a control you set in one corner
        would quietly read wrong everywhere.
        """
        c = {"A": {"only": 0.8}, "B": {}, "C": {}, "D": {}}
        assert blend(c, 0.0, 0.0)["only"] == pytest.approx(0.8)
        assert blend(c, 0.5, 0.5)["only"] == pytest.approx(0.8)  # still 0.8, not 0.2

    def test_two_corners_of_four_blend_only_against_each_other(self):
        c = {"A": {"p": 0.0}, "B": {"p": 1.0}, "C": {}, "D": {}}
        # Halfway along the A-B edge: an even split of the two that define it.
        assert blend(c, 0.5, 0.0)["p"] == pytest.approx(0.5)

    def test_a_path_no_corner_defines_is_absent_not_zero(self):
        assert "ghost" not in blend({"A": {"p": 1.0}}, 0.5, 0.5)

    def test_empty_corners_blend_to_nothing(self):
        assert blend({c: {} for c in CORNERS}, 0.5, 0.5) == {}

    def test_blends_every_path_across_corners(self):
        c = {"A": {"x": 0.0, "y": 1.0}, "B": {"x": 1.0}, "C": {}, "D": {}}
        got = blend(c, 0.5, 0.0)
        assert got["x"] == pytest.approx(0.5)
        assert got["y"] == pytest.approx(1.0)  # only A has it


class TestSurface:
    def test_grid_shape_and_corner_values(self):
        c = {"A": {"p": 0.0}, "B": {"p": 1.0}, "C": {"p": 1.0}, "D": {"p": 0.0}}
        g = surface(c, "p", n=5)
        assert len(g) == 5 and all(len(r) == 5 for r in g)
        assert g[0][0] == pytest.approx(0.0)  # y=0, x=0 -> corner A
        assert g[0][-1] == pytest.approx(1.0)  # y=0, x=1 -> corner B

    def test_row_zero_is_y_zero(self):
        """Renderer depends on this orientation; getting it wrong flips the landscape."""
        c = {"A": {"p": 0.0}, "B": {"p": 0.0}, "C": {"p": 1.0}, "D": {"p": 1.0}}
        g = surface(c, "p", n=3)
        assert g[0][0] == pytest.approx(0.0)  # y=0 edge (A-B)
        assert g[-1][0] == pytest.approx(1.0)  # y=1 edge (D-C)

    def test_undefined_path_is_holes_not_zeros(self):
        g = surface({"A": {"p": 1.0}}, "absent", n=3)
        assert all(cell is None for row in g for cell in row)

    def test_rejects_a_degenerate_grid(self):
        with pytest.raises(ValueError, match="at least 2"):
            surface({"A": {"p": 1.0}}, "p", n=1)


class TestOrbit:
    def test_stays_inside_the_square(self):
        o = Orbit(rate_x=0.7, rate_y=1.1, depth=1.0)
        for i in range(400):
            x, y = o.at(i * 0.05)
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

    def test_zero_depth_sits_still_at_the_centre(self):
        o = Orbit(depth=0.0, centre_x=0.3, centre_y=0.7)
        assert o.at(0.0) == pytest.approx((0.3, 0.7))
        assert o.at(12.5) == pytest.approx((0.3, 0.7))

    def test_equal_rates_and_quarter_phase_trace_a_circle(self):
        o = Orbit(rate_x=1.0, rate_y=1.0, phase_x=0.0, phase_y=0.25, depth=1.0)
        for i in range(24):
            x, y = o.at(i / 24.0)
            r = math.hypot(x - 0.5, y - 0.5)
            assert r == pytest.approx(0.5, abs=1e-6)

    def test_period_repeats(self):
        o = Orbit(rate_x=0.5, rate_y=0.5)
        assert o.at(0.0) == pytest.approx(o.at(2.0))  # 1/0.5 = 2s

    def test_trail_is_oldest_first_and_ends_at_now(self):
        o = Orbit(rate_x=0.3, rate_y=0.4)
        t = 10.0
        trail = o.trail(t, seconds=4.0, n=9)
        assert len(trail) == 9
        assert trail[-1] == pytest.approx(o.at(t))
        assert trail[0] == pytest.approx(o.at(t - 4.0))


class TestVectorEngine:
    def test_move_clamps(self):
        e = VectorEngine()
        e.move(5.0, -2.0)
        assert (e.x, e.y) == (1.0, 0.0)

    def test_set_and_clear_corner(self):
        e = VectorEngine()
        e.set_corner("A", {"sc.1.mix": 0.9})
        assert e.paths() == ["sc.1.mix"]
        e.clear_corner("A")
        assert e.paths() == []

    def test_rejects_an_unknown_corner(self):
        with pytest.raises(ValueError, match="A, B, C, D"):
            VectorEngine().set_corner("E", {})

    def test_values_follow_position(self):
        e = VectorEngine()
        e.set_corner("A", {"p": 0.0})
        e.set_corner("B", {"p": 1.0})
        e.move(0.0, 0.0)
        assert e.values()["p"] == pytest.approx(0.0)
        e.move(1.0, 0.0)
        assert e.values()["p"] == pytest.approx(1.0)

    def test_tick_does_not_move_while_the_orbit_is_stopped(self):
        e = VectorEngine()
        e.move(0.2, 0.8)
        assert e.tick(99.0) == (0.2, 0.8)

    def test_tick_moves_while_the_orbit_runs(self):
        e = VectorEngine()
        e.set_mode("orbit")
        a = e.tick(0.0)
        b = e.tick(1.7)
        assert a != b
        assert (e.x, e.y) == b  # engine position follows the orbit

    def test_paths_are_the_union_across_corners(self):
        e = VectorEngine()
        e.set_corner("A", {"one": 1.0})
        e.set_corner("C", {"two": 2.0, "one": 0.0})
        assert e.paths() == ["one", "two"]


class TestMotion:
    """The vector envelope — a recorded gesture, not a shape."""

    def _square(self):
        m = Motion()
        m.record([(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 1.0, 1.0), (3.0, 0.0, 1.0)])
        return m

    def test_records_normalised_time_so_playback_rate_is_free(self):
        """A 4s gesture and a 40s one must play back identically on the same clock."""
        slow = Motion()
        slow.record([(0, 0, 0), (20, 1, 0), (40, 1, 1)])
        fast = Motion()
        fast.record([(0, 0, 0), (2, 1, 0), (4, 1, 1)])
        assert [p.t for p in slow.points] == [p.t for p in fast.points]

    def test_interpolates_between_knots(self):
        m = self._square()
        # knots at t = 0, 1/3, 2/3, 1 — halfway along the first leg
        assert m.at(1 / 6) == pytest.approx((0.5, 0.0))

    def test_hits_its_knots(self):
        m = self._square()
        assert m.at(0.0) == pytest.approx((0.0, 0.0))
        assert m.at(1 / 3) == pytest.approx((1.0, 0.0))
        assert m.at(2 / 3) == pytest.approx((1.0, 1.0))

    def test_loop_wraps(self):
        m = self._square()
        assert m.at(1.5) == pytest.approx(m.at(0.5))
        assert m.at(7.25) == pytest.approx(m.at(0.25))

    def test_loop_off_holds_the_last_point(self):
        m = self._square()
        m.loop = "off"
        assert m.at(5.0) == pytest.approx((0.0, 1.0))

    def test_pingpong_runs_backwards_on_the_return(self):
        m = self._square()
        m.loop = "pingpong"
        assert m.phase(0.25) == pytest.approx(0.25)
        assert m.phase(1.25) == pytest.approx(0.75)  # coming back
        assert m.phase(2.25) == pytest.approx(0.25)  # and out again

    def test_a_single_sample_is_not_a_path(self):
        m = Motion()
        m.record([(1.0, 0.3, 0.4)])
        assert m.empty and m.at(0.5) == (0.5, 0.5)

    def test_zero_duration_recording_is_discarded(self):
        """Every sample at the same instant has no time axis to normalise against."""
        m = Motion()
        m.record([(2.0, 0.1, 0.2), (2.0, 0.9, 0.8)])
        assert m.empty

    def test_out_of_order_samples_are_sorted(self):
        m = Motion()
        m.record([(2.0, 1.0, 1.0), (0.0, 0.0, 0.0), (1.0, 1.0, 0.0)])
        assert [round(p.t, 3) for p in m.points] == [0.0, 0.5, 1.0]

    def test_positions_are_clamped_to_the_square(self):
        m = Motion()
        m.record([(0, -5, 9), (1, 0.5, 0.5)])
        assert m.points[0].x == 0.0 and m.points[0].y == 1.0

    def test_rejects_an_unknown_loop_mode(self):
        with pytest.raises(ValueError, match="off, loop, pingpong"):
            Motion(loop="boomerang")

    def test_serialises_for_the_wire(self):
        d = self._square().as_dict()
        assert d["loop"] == "loop" and len(d["points"]) == 4
        assert set(d["points"][0]) == {"t", "x", "y"}


class TestClock:
    def test_free_mode_uses_the_period(self):
        c = Clock(mode="free", period=4.0)
        assert c.seconds_per_cycle == 4.0
        assert c.cycles(2.0) == pytest.approx(0.5)

    def test_tempo_mode_locks_a_cycle_to_beats(self):
        """One bar at 120 bpm is 2 seconds; the path must span exactly that."""
        c = Clock(mode="tempo", bpm=120.0, beats=4.0)
        assert c.seconds_per_cycle == pytest.approx(2.0)
        assert c.cycles(2.0) == pytest.approx(1.0)

    def test_doubling_the_tempo_halves_the_cycle(self):
        slow = Clock(mode="tempo", bpm=60, beats=4).seconds_per_cycle
        fast = Clock(mode="tempo", bpm=120, beats=4).seconds_per_cycle
        assert slow == pytest.approx(2 * fast)

    def test_never_divides_by_zero(self):
        assert Clock(mode="tempo", bpm=0, beats=0).seconds_per_cycle > 0
        assert Clock(mode="free", period=0).seconds_per_cycle > 0

    def test_rejects_an_unknown_mode(self):
        with pytest.raises(ValueError, match="free, tempo"):
            Clock(mode="midi-somehow")


class TestEngineMotion:
    def _engine_with_path(self):
        e = VectorEngine()
        e.start_recording(10.0)
        e.move(0.0, 0.0, t=10.0)
        e.move(1.0, 0.0, t=11.0)
        e.move(1.0, 1.0, t=12.0)
        n = e.stop_recording()
        return e, n

    def test_recording_captures_the_drag(self):
        e, n = self._engine_with_path()
        # The arming knot shares its instant with the first move and collapses into it.
        assert n == 3
        assert not e.motion.empty
        assert e.recording is False

    def test_moves_outside_recording_are_not_captured(self):
        e = VectorEngine()
        e.move(0.2, 0.2, t=1.0)
        e.start_recording(2.0)
        e.move(0.9, 0.9, t=3.0)
        e.stop_recording()
        assert all(p.x >= 0.2 for p in e.motion.points)

    def test_manual_mode_does_not_move_on_its_own(self):
        e, _ = self._engine_with_path()
        e.move(0.3, 0.7)
        assert e.moving() is False
        assert e.tick(999.0) == (0.3, 0.7)

    def test_motion_mode_plays_the_path(self):
        e, _ = self._engine_with_path()
        e.set_mode("motion")
        e.clock = Clock(mode="free", period=4.0)
        e.trigger(100.0)
        assert e.moving() is True
        assert e.tick(100.0) == pytest.approx((0.0, 0.0))  # start of the path
        assert e.tick(102.0) == pytest.approx(e.motion.at(0.5))

    def test_motion_mode_with_no_path_does_not_move(self):
        e = VectorEngine()
        e.set_mode("motion")
        e.move(0.4, 0.6)
        assert e.moving() is False
        assert e.tick(50.0) == (0.4, 0.6)

    def test_trigger_restarts_the_path(self):
        """Note-on behaviour: the gesture begins again from its first knot."""
        e, _ = self._engine_with_path()
        e.set_mode("motion")
        e.clock = Clock(mode="free", period=4.0)
        e.trigger(0.0)
        e.tick(3.0)
        e.trigger(3.0)
        assert e.tick(3.0) == pytest.approx(e.motion.at(0.0))

    def test_tempo_sync_makes_a_bar_a_cycle(self):
        e, _ = self._engine_with_path()
        e.set_mode("motion")
        e.clock = Clock(mode="tempo", bpm=120.0, beats=4.0)  # 2s per cycle
        e.trigger(0.0)
        assert e.tick(2.0) == pytest.approx(e.tick(4.0))  # one bar apart, same place

    def test_orbit_mode_still_works(self):
        e = VectorEngine()
        e.set_mode("orbit")
        assert e.moving() is True
        assert e.tick(0.0) != e.tick(1.7)

    def test_rejects_an_unknown_mode(self):
        with pytest.raises(ValueError, match="manual, orbit, motion"):
            VectorEngine().set_mode("telepathy")

    def test_same_instant_samples_collapse_to_the_later_one(self):
        """Arming seeds a knot where the dot sits; a drag in the same millisecond wins."""
        m = Motion()
        m.record([(0.0, 0.5, 0.5), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)])
        assert len(m.points) == 2
        assert m.at(0.0) == pytest.approx((0.0, 0.0))
