"""Tests for the panel control catalogue.

The catalogue is curated by hand — the firmware's abbreviations expanded into what
the panel legend calls things — so the risk is inventing a control that sounds right
and does not exist. `tests/fixtures/panel-paths.txt` is the real thing, read out of a
preset on the instrument, and every catalogue path has to be in it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from moogone.controls import CATALOG, TIMBRES, Control, find, for_ui, sections

FIXTURE = Path(__file__).parent / "fixtures" / "panel-paths.txt"
REAL_PATHS = set(FIXTURE.read_text().split())


class TestAgainstTheInstrument:
    def test_the_fixture_is_the_real_namespace(self):
        assert len(REAL_PATHS) > 200
        assert all(p.startswith("/p/part/t/1/p/") for p in REAL_PATHS)

    @pytest.mark.parametrize("control", CATALOG, ids=lambda c: f"{c.group}/{c.control}")
    def test_every_catalogue_path_exists_on_the_instrument(self, control):
        assert control.path(1) in REAL_PATHS, (
            f"{control.section} / {control.label} claims {control.path(1)}, which the "
            "instrument does not have"
        )

    def test_leaf_only_controls_have_no_trailing_slash(self):
        # `pan` and `pan-spread` are leaves of the group itself. Formatting those
        # through the template used to leave a path ending in "/", which exists
        # nowhere.
        pan = next(c for c in CATALOG if c.group == "pan")
        assert pan.path(1) == "/p/part/t/1/p/pan"
        assert not any(c.path(1).endswith("/") for c in CATALOG)


class TestPaths:
    @pytest.mark.parametrize("timbre", TIMBRES)
    def test_each_timbre_gets_its_own_path(self, timbre):
        c = Control("fa", "p", "Cutoff", "State Variable Filter")
        assert c.path(timbre) == f"/p/part/t/{timbre}/p/fa/p"

    @pytest.mark.parametrize("bad", [0, 4, -1])
    def test_a_timbre_that_does_not_exist_is_refused(self, bad):
        with pytest.raises(ValueError, match="timbre must be"):
            CATALOG[0].path(bad)

    def test_there_are_three_timbres_like_the_three_small_screens(self):
        assert TIMBRES == (1, 2, 3)


class TestCatalogue:
    def test_covers_the_panel_sections(self):
        got = sections()
        for expected in (
            "Oscillator 1", "Oscillator 2", "Oscillator 3",
            "State Variable Filter", "Ladder Filter",
            "Filter Envelope", "Amplifier Envelope", "Modulation Envelope",
            "LFO 1", "LFO 4", "Mixer", "Noise", "Output",
        ):
            assert expected in got

    def test_sections_are_unique_and_in_catalogue_order(self):
        got = sections()
        assert len(got) == len(set(got))
        assert got.index("Oscillator 1") < got.index("State Variable Filter")
        assert got.index("State Variable Filter") < got.index("Filter Envelope")

    def test_both_filters_have_a_cutoff_and_they_differ(self):
        cutoffs = [c for c in CATALOG if c.label == "Cutoff"]
        assert len(cutoffs) == 2
        assert {c.group for c in cutoffs} == {"fa", "fb"}

    def test_each_envelope_has_a_full_adsr(self):
        for group in ("e1", "e2", "e3"):
            labels = {c.label for c in CATALOG if c.group == group}
            assert {"Attack", "Decay", "Sustain", "Release"} <= labels

    def test_the_mixer_routes_every_oscillator_to_both_filters(self):
        for osc in ("o1", "o2", "o3"):
            paths = {c.control for c in CATALOG if c.group == "mix"}
            assert f"{osc}/fa" in paths and f"{osc}/fb" in paths

    def test_kinds_are_known(self):
        assert {c.kind for c in CATALOG} <= {"knob", "switch", "button"}

    def test_no_duplicate_paths(self):
        paths = [c.path(1) for c in CATALOG]
        assert len(paths) == len(set(paths))


class TestFind:
    def test_matches_a_label(self):
        assert {c.group for c in find("cutoff")} == {"fa", "fb"}

    def test_matches_a_section(self):
        assert all(c.section == "Ladder Filter" for c in find("ladder filter"))

    def test_matches_a_raw_path_fragment(self):
        assert all(c.group == "l3" for c in find("l3/"))

    def test_is_case_insensitive(self):
        assert find("CUTOFF") == find("cutoff")

    def test_empty_returns_everything(self):
        assert len(find("  ")) == len(CATALOG)

    def test_no_match_is_empty_not_an_error(self):
        assert find("theremin") == []


def test_for_ui_carries_the_path_for_the_chosen_timbre():
    rows = for_ui(2)
    assert len(rows) == len(CATALOG)
    assert all(r["path"].startswith("/p/part/t/2/") for r in rows)
    assert {"label", "section", "kind", "group", "control", "path"} == set(rows[0])
