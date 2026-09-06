"""Tests for the on-instrument heads-up display.

The HUD draws onto a hardware overlay plane above the Moog's own interface, so a
rendering bug is not cosmetic -- it puts wrong information on the instrument's
screen while you are playing it. The spectrum in particular is a claim about what
you are about to hear, verified against real audio elsewhere.
"""

from __future__ import annotations

import numpy as np
import pytest

from moogone.hud import (
    BYTES_PER_PIXEL,
    CARRIER,
    FONT,
    GLYPH_H,
    GLYPH_W,
    HEIGHT,
    REFLECTED,
    SIDEBAND,
    WIDTH,
    Canvas,
    render_fm,
    text_width,
)


class TestFont:
    def test_every_glyph_is_five_by_seven(self):
        for char, glyph in FONT.items():
            rows = glyph.split()
            assert len(rows) == GLYPH_H, f"{char!r} has {len(rows)} rows"
            for row in rows:
                assert len(row) == GLYPH_W, f"{char!r} row {row!r}"
                assert set(row) <= {"0", "1"}, f"{char!r} row {row!r}"

    def test_it_covers_what_the_hud_writes(self):
        needed = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ .:-+/%")
        assert needed <= set(FONT), f"missing: {sorted(needed - set(FONT))}"

    def test_space_is_blank_and_others_are_not(self):
        assert set(FONT[" "].replace(" ", "")) == {"0"}
        for char in "0AZ#":
            assert "1" in FONT[char], f"{char!r} would render as nothing"

    def test_digits_are_distinguishable(self):
        # A font where two digits render identically would misreport a ratio.
        shapes = {d: FONT[d] for d in "0123456789"}
        assert len(set(shapes.values())) == 10, "two digits share a glyph"


class TestCanvas:
    def test_starts_opaque_and_black(self):
        c = Canvas(16, 8)
        assert c.buf.shape == (8, 16, BYTES_PER_PIXEL)
        assert (c.buf[:, :, 3] == 255).all(), "alpha must be opaque"
        assert (c.buf[:, :, 0:3] == 0).all()

    def test_rect_draws_where_asked(self):
        c = Canvas(20, 10)
        c.rect(5, 2, 4, 3, (10, 20, 30))
        assert tuple(c.buf[2, 5, 0:3]) == (10, 20, 30)
        assert tuple(c.buf[4, 8, 0:3]) == (10, 20, 30)
        assert tuple(c.buf[1, 5, 0:3]) == (0, 0, 0), "must not bleed above"
        assert tuple(c.buf[5, 5, 0:3]) == (0, 0, 0), "must not bleed below"

    def test_rect_clips_instead_of_raising(self):
        # A HUD that vanishes because one value grew is worse than a clipped bar.
        c = Canvas(10, 10)
        c.rect(-5, -5, 8, 8, (1, 2, 3))
        c.rect(8, 8, 100, 100, (4, 5, 6))
        c.rect(50, 50, 4, 4, (7, 8, 9))  # entirely outside: a no-op
        assert tuple(c.buf[0, 0, 0:3]) == (1, 2, 3)
        assert tuple(c.buf[9, 9, 0:3]) == (4, 5, 6)

    def test_text_advances_by_its_width(self):
        c = Canvas(200, 20)
        end = c.text(10, 2, "ABC")
        assert end == 10 + text_width("ABC")

    def test_text_actually_marks_pixels(self):
        c = Canvas(60, 20)
        c.text(2, 2, "8")
        assert (c.buf[:, :, 0:3].sum(axis=2) > 0).sum() > 10

    def test_unknown_characters_advance_without_drawing(self):
        c = Canvas(60, 20)
        end = c.text(0, 0, "§§")
        assert end == text_width("§§")
        assert (c.buf[:, :, 0:3] == 0).all(), "unknown glyphs must draw nothing"

    def test_scale_makes_glyphs_bigger(self):
        small, big = Canvas(80, 40), Canvas(80, 40)
        small.text(1, 1, "8", scale=1)
        big.text(1, 1, "8", scale=2)

        def lit(c):
            return (c.buf[:, :, 0:3].sum(axis=2) > 0).sum()

        assert lit(big) > lit(small) * 3

    def test_to_bytes_is_the_framebuffer_size(self):
        c = Canvas(832, 120)
        assert len(c.to_bytes()) == 832 * 120 * BYTES_PER_PIXEL


def _state(**kw):
    base = {
        "mode": "self",
        "ratio": 2.0,
        "index": 3.0,
        "cpu_estimate": 0.6,
        "voices": [{"note": 60, "freq": 261.63, "mode": "self", "age": 0.1}],
        "spectrum": [
            {"order": 0, "ratio": 1.0, "amplitude": 0.26, "reflected": False},
            {"order": 1, "ratio": 3.0, "amplitude": 0.34, "reflected": False},
            {"order": -1, "ratio": -1.0, "amplitude": 0.34, "reflected": True},
        ],
    }
    base.update(kw)
    return base


class TestRenderFm:
    def test_default_size_matches_the_overlay(self):
        c = render_fm(_state())
        assert (c.width, c.height) == (WIDTH, HEIGHT)

    def test_it_draws_something(self):
        c = render_fm(_state())
        assert (c.buf[:, :, 0:3].sum(axis=2) > 0).sum() > 500

    def test_each_partial_kind_gets_its_own_colour(self):
        c = render_fm(_state())
        px = c.buf[:, :, 0:3].reshape(-1, 3)
        present = {tuple(p) for p in np.unique(px, axis=0)}
        assert CARRIER in present, "the carrier must be distinguishable"
        assert SIDEBAND in present, "ordinary sidebands must be drawn"
        assert REFLECTED in present, (
            "reflected partials fold onto other partials and change the timbre; "
            "drawing them the same colour hides the most surprising thing FM does"
        )

    def test_analog_mode_says_it_cannot_predict(self):
        # The modulator is a live analog voice, so no spectrum can be computed.
        # Drawing an empty axis with no explanation would look like a bug.
        c = render_fm(_state(mode="analog", spectrum=[]))
        assert (c.buf[:, :, 0:3].sum(axis=2) > 0).sum() > 200

    def test_no_voices_still_renders(self):
        c = render_fm(_state(voices=[], spectrum=[]))
        assert (c.buf[:, :, 0:3].sum(axis=2) > 0).sum() > 100

    def test_cpu_meter_grows_with_load(self):
        def filled(cpu):
            c = render_fm(_state(cpu_estimate=cpu))
            return (c.buf[:, :, 0:3].sum(axis=2) > 0).sum()

        assert filled(0.9) > filled(0.1)

    def test_a_heavy_load_is_coloured_as_a_warning(self):
        from moogone.hud import WARN

        c = render_fm(_state(cpu_estimate=0.95))
        px = {tuple(p) for p in np.unique(c.buf[:, :, 0:3].reshape(-1, 3), axis=0)}
        assert WARN in px

    def test_it_survives_a_state_missing_everything(self):
        # The bridge builds this dict; a HUD that raises would take the screen with it.
        render_fm({})

    @pytest.mark.parametrize("size", [(320, 60), (832, 120), (400, 200)])
    def test_it_renders_at_other_sizes(self, size):
        c = render_fm(_state(), width=size[0], height=size[1])
        assert (c.width, c.height) == size
        assert len(c.to_bytes()) == size[0] * size[1] * BYTES_PER_PIXEL
