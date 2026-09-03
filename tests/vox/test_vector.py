"""Vector synthesis. The discriminating cases: a corner that omits a control must not
drag it toward zero, and the orbit must stay on the square.
"""

import math

import pytest

from moogone.vox.vector import (
    CORNER_XY,
    CORNERS,
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
        e.orbit.running = True
        a = e.tick(0.0)
        b = e.tick(1.7)
        assert a != b
        assert (e.x, e.y) == b  # engine position follows the orbit

    def test_paths_are_the_union_across_corners(self):
        e = VectorEngine()
        e.set_corner("A", {"one": 1.0})
        e.set_corner("C", {"two": 2.0, "one": 0.0})
        assert e.paths() == ["one", "two"]
