"""Tests for FX snapshots.

The central risk this module exists to manage: the instrument reallocates node ids
whenever a preset is loaded on its front panel. A snapshot keyed by id would happily
write a delay's settings into a chorus that inherited its number.
"""

from __future__ import annotations

import json

import pytest

from moogone.sc.tree import SynthNode
from moogone.vox.presets import (
    STRUCTURAL,
    PresetError,
    Slot,
    Snapshot,
    capture,
    load,
    names,
    plan,
    save,
)


def node(nid, defname, **controls):
    return SynthNode(nid, defname, dict(controls))


def chain():
    return [
        node(1035, "pingpongDelay_0", mix=0.24, feedback=0.60, inBus=12.0, outBus=50.0),
        node(1036, "delay_0", mix=0.33, feedback=0.33, inBus=13.0, outBus=52.0),
        node(1037, "delay_0", mix=0.10, feedback=0.90, inBus=14.0, outBus=54.0),
    ]


class TestCapture:
    def test_captures_named_controls(self):
        snap = capture(chain(), "as found")
        assert [s.defname for s in snap.slots] == ["pingpongDelay_0", "delay_0", "delay_0"]
        assert snap.slots[0].controls["mix"] == 0.24

    def test_repeated_defnames_are_numbered_in_tree_order(self):
        snap = capture(chain(), "x")
        assert [(s.defname, s.index) for s in snap.slots][1:] == [("delay_0", 0), ("delay_0", 1)]
        assert snap.slots[1].controls["feedback"] == 0.33
        assert snap.slots[2].controls["feedback"] == 0.90

    def test_structural_controls_are_not_captured(self):
        snap = capture(chain(), "x")
        for s in snap.slots:
            assert not (set(s.controls) & STRUCTURAL), "routing is not a setting"

    def test_unnamed_integer_controls_are_skipped(self):
        # The real inputRouter reports 53 controls by integer index. There is no name
        # to restore them by, so they are left alone rather than guessed at.
        snap = capture([node(1012, "inputRouter", enable=1.0)] , "x")
        snap2 = capture([SynthNode(1012, "inputRouter", {2: 0.0, 3: 1.0, "enable": 1.0})], "y")
        assert snap2.slots[0].controls == {"enable": 1.0}
        assert snap.slots[0].controls == {"enable": 1.0}

    @pytest.mark.parametrize("bad", ["", " leading", "a" * 65, "sla/sh", "../escape", "dot.dot"])
    def test_unusable_names_are_refused(self, bad):
        with pytest.raises(PresetError):
            capture(chain(), bad)

    @pytest.mark.parametrize("good", ["clean", "As Found", "test-1", "a_b", "9lives"])
    def test_usable_names(self, good):
        assert capture(chain(), good).name == good


class TestPlan:
    def test_only_differences_are_written(self):
        snap = capture(chain(), "x")
        assert plan(chain(), snap).writes == [], "nothing changed, nothing to write"

    def test_a_changed_value_is_written(self):
        snap = capture(chain(), "x")
        live = chain()
        live[0].controls["mix"] = 0.9
        p = plan(live, snap)
        assert p.writes == [(1035, "mix", 0.24)]

    def test_node_ids_may_change_entirely_and_it_still_matches(self):
        # The failure this module exists to prevent, as a test.
        snap = capture(chain(), "x")
        renumbered = [
            node(2001, "pingpongDelay_0", mix=0.9, feedback=0.60, inBus=12.0, outBus=50.0),
            node(2002, "delay_0", mix=0.33, feedback=0.33, inBus=13.0, outBus=52.0),
            node(2003, "delay_0", mix=0.10, feedback=0.90, inBus=14.0, outBus=54.0),
        ]
        p = plan(renumbered, snap)
        assert p.writes == [(2001, "mix", 0.24)], "matched by identity, not by number"
        assert p.ok

    def test_a_different_chain_is_reported_not_partially_applied(self):
        snap = capture(chain(), "x")
        other = [node(1055, "stereoChorus_0", mix=0.066), node(1056, "delay_0", mix=0.5)]
        p = plan(other, snap)
        assert not p.ok
        assert "pingpongDelay_0[0]" in p.missing
        assert "delay_0[1]" in p.missing
        assert p.writes == [(1056, "mix", 0.33)], "the one that matched is still planned"

    def test_extra_live_nodes_are_reported(self):
        snap = capture(chain()[:1], "x")
        p = plan(chain(), snap)
        assert "delay_0[0]" in p.extra and "delay_0[1]" in p.extra

    def test_structural_controls_are_never_written(self):
        # Even a snapshot that somehow contains one -- hand-edited, or written by an
        # older version -- must not move audio between buses on the way back in.
        snap = Snapshot("x", [Slot("delay_0", 0, {"inBus": 99.0, "mix": 0.5})])
        live = [node(1036, "delay_0", mix=0.1, inBus=13.0)]
        assert plan(live, snap).writes == [(1036, "mix", 0.5)]

    def test_a_control_the_live_node_lacks_is_skipped(self):
        snap = capture([node(1, "delay_0", mix=0.5, exotic=1.0)], "x")
        assert plan([node(1, "delay_0", mix=0.1)], snap).writes == [(1, "mix", 0.5)]


class TestRoundTrip:
    def test_save_and_load(self, tmp_path):
        snap = capture(chain(), "as found", note="before touching anything")
        p = save(snap, tmp_path)
        assert p.name == "as found.json"
        back = load("as found", tmp_path)
        assert back.name == snap.name
        assert back.note == "before touching anything"
        assert [s.key for s in back.slots] == [s.key for s in snap.slots]
        assert back.slots[0].controls == snap.slots[0].controls

    def test_names_lists_what_is_there(self, tmp_path):
        save(capture(chain(), "clean"), tmp_path)
        save(capture(chain(), "as found"), tmp_path)
        assert names(tmp_path) == ["as found", "clean"]

    def test_names_of_a_missing_directory_is_empty(self, tmp_path):
        assert names(tmp_path / "nope") == []

    def test_loading_an_absent_preset_says_so(self, tmp_path):
        with pytest.raises(PresetError, match="no preset called"):
            load("ghost", tmp_path)

    def test_a_traversal_name_cannot_reach_outside_the_directory(self, tmp_path):
        with pytest.raises(PresetError):
            load("../../etc/passwd", tmp_path)

    def test_the_file_is_readable_json(self, tmp_path):
        save(capture(chain(), "clean"), tmp_path)
        d = json.loads((tmp_path / "clean.json").read_text())
        assert d["name"] == "clean" and len(d["slots"]) == 3
