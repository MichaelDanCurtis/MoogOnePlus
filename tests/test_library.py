"""Tests for the preset library reader.

The database is built here rather than shipped: the real one is 100 MB of Moog's
preset content, and what needs testing is the parsing and the queries, not their data.
"""

from __future__ import annotations

import sqlite3

import pytest

from moogone.library import (
    Library,
    LibraryError,
    diff,
    parse_preset,
    parse_value,
    summarise,
)

SCHEMA = """
create table presets (id integer primary key, timestamp text, name text, comment text,
    synth1Name text, synth2Name text, synth3Name text, data text);
create table tags (id integer primary key, type text, name text);
create table preset_tags (presetId integer, tagId integer);
"""


@pytest.fixture
def library(tmp_path):
    path = tmp_path / "test.db"
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    brass = (
        "/p/part/t/1/p/fa/p 900.5\n"
        "/p/part/t/1/p/fa/r 0.4\n"
        "/p/part/t/1/p/e2/a 0.01\n"
        "/p/clk/rate 120.0\n"
    )
    pad = (
        "/p/part/t/1/p/fa/p 400.0\n"
        "/p/part/t/1/p/fa/r 0.4\n"
        "/p/part/t/1/p/o1/oct 1\n"
    )
    db.execute("insert into presets values (1,'','BRASS','warm','B1','B2','', ?)", (brass,))
    db.execute("insert into presets values (2,'','PAD','','P1','','', ?)", (pad,))
    db.execute("insert into tags values (1,'category','KEYS'),(2,'mood','WARM')")
    db.execute("insert into preset_tags values (1,1),(1,2)")
    db.commit(); db.close()
    return path


class TestParseValue:
    @pytest.mark.parametrize("text,expected", [
        ("900.5", 900.5), ("120", 120), ("-3", -3), ("0.0002", 0.0002),
        ("true", True), ("false", False), ("null", None),
        ('"SONIC BASS"', "SONIC BASS"), ('""', ""),
    ])
    def test_values(self, text, expected):
        assert parse_value(text) == expected

    def test_an_unfamiliar_value_is_kept_as_text(self):
        assert parse_value("0x1f") == "0x1f"

    def test_whitespace_is_trimmed(self):
        assert parse_value("  0.5  ") == 0.5

    def test_a_quoted_string_keeps_its_spaces(self):
        assert parse_value('"  padded  "') == "  padded  "

    def test_true_as_a_quoted_string_is_a_string(self):
        assert parse_value('"true"') == "true"


class TestParsePreset:
    def test_paths_and_values(self):
        got = parse_preset("/p/a 1\n/p/b 2.5\n/p/c true\n")
        assert got == {"/p/a": 1, "/p/b": 2.5, "/p/c": True}

    def test_a_line_it_cannot_read_is_skipped_not_raised(self):
        # 398 presets written by several firmware versions; one odd line must not
        # cost the other three thousand.
        got = parse_preset("/p/a 1\nnonsense without a path\n/p/b 2\n")
        assert got == {"/p/a": 1, "/p/b": 2}

    def test_blank_input(self):
        assert parse_preset("") == {}

    def test_a_value_containing_spaces_survives(self):
        assert parse_preset('/p/name "TWO WORDS"') == {"/p/name": "TWO WORDS"}


class TestLibrary:
    def test_catalogue(self, library):
        with Library(library) as lib:
            cat = {p.name: p for p in lib.catalogue()}
        assert set(cat) == {"BRASS", "PAD"}
        assert cat["BRASS"].comment == "warm"
        assert cat["BRASS"].synths == ("B1", "B2", "")

    def test_multi_timbre_is_more_than_one_synth(self, library):
        with Library(library) as lib:
            cat = {p.name: p for p in lib.catalogue()}
        assert cat["BRASS"].is_multi is True
        assert cat["PAD"].is_multi is False

    def test_tags_are_attached(self, library):
        with Library(library) as lib:
            cat = {p.name: p for p in lib.catalogue()}
        assert cat["BRASS"].tags == ("KEYS", "WARM")
        assert cat["PAD"].tags == ()

    def test_parameters(self, library):
        with Library(library) as lib:
            params = lib.parameters("BRASS")
        assert params["/p/part/t/1/p/fa/p"] == 900.5
        assert params["/p/clk/rate"] == 120.0

    def test_a_missing_preset_says_which(self, library):
        with Library(library) as lib, pytest.raises(LibraryError, match="GHOST"):
            lib.parameters("GHOST")

    def test_a_missing_file_says_so(self, tmp_path):
        with pytest.raises(LibraryError, match="no such library"):
            Library(tmp_path / "absent.db")

    def test_names_are_sorted_case_insensitively(self, library):
        with Library(library) as lib:
            assert lib.names() == ["BRASS", "PAD"]

    def test_it_opens_immutable(self, library):
        """The real library may be a copy of a file the instrument still has open.
        Immutable means sqlite writes no journal beside it."""
        with Library(library) as lib, pytest.raises(sqlite3.OperationalError):
            lib._db.execute("insert into presets values (9,'','X','','','','','')")


class TestDiff:
    def test_only_differences_are_reported(self):
        a = {"x": 1, "same": 5}
        b = {"x": 2, "same": 5}
        assert diff(a, b) == {"x": (1, 2)}

    def test_a_path_on_only_one_side_shows_as_none(self):
        assert diff({"only": 1}, {}) == {"only": (1, None)}
        assert diff({}, {"only": 1}) == {"only": (None, 1)}

    def test_identical_presets_differ_nowhere(self):
        a = {"x": 1.0, "y": "s", "z": True}
        assert diff(a, dict(a)) == {}

    def test_it_is_symmetric_in_keys(self):
        a, b = {"p": 1}, {"q": 2}
        assert set(diff(a, b)) == {"p", "q"}


class TestSummarise:
    def test_picks_the_values_that_describe_a_sound(self):
        params = {
            "/p/part/t/1/p/fa/p": 900.0, "/p/part/t/1/p/fa/r": 0.5,
            "/p/part/t/1/p/fb/p": 400.0, "/p/part/t/1/p/e2/a": 0.01,
            "/p/part/t/1/p/o1/oct": 1,
        }
        got = summarise(params)
        assert got["svf cutoff"] == 900.0
        assert got["ladder cutoff"] == 400.0
        assert got["amp attack"] == 0.01
        assert "oct" not in " ".join(got)

    def test_absent_values_are_omitted_rather_than_none(self):
        assert summarise({"/p/part/t/1/p/fa/p": 1.0}) == {"svf cutoff": 1.0}

    def test_it_follows_the_timbre(self):
        params = {"/p/part/t/3/p/fa/p": 700.0}
        assert summarise(params, timbre=3) == {"svf cutoff": 700.0}
        assert summarise(params, timbre=1) == {}
