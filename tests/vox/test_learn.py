"""Tests for parameter learning.

The design problem these pin down: a control is never the only thing moving. A learn
pass has to pick the knob that was turned out of whatever else happened to be busy,
and refuse when nothing stands out rather than name the loudest coincidence.
"""

from __future__ import annotations

import json

import pytest

from moogone.vox.learn import (
    KNOWN,
    MARGIN,
    MIN_COUNT,
    MIN_SPAN,
    Learner,
    LearnError,
    ParamMap,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.01
        return self.t


def sweep(learner, param, n=40, lo=0.0, hi=1.0):
    for i in range(n):
        learner.feed(param, lo + (hi - lo) * i / (n - 1))


class TestLearner:
    def test_a_swept_parameter_is_identified(self):
        learn = Learner(Clock())
        learn.begin("cutoff")
        sweep(learn, 412)
        assert learn.finish().param == 412

    def test_a_sweep_beats_incidental_traffic(self):
        # The realistic case: a knob is turned while a note tail and an LFO tick.
        learn = Learner(Clock())
        learn.begin("cutoff")
        sweep(learn, 412)
        for _ in range(3):
            learn.feed(358, 0.5)      # unchanging, span 0
            learn.feed(99, 0.50)
            learn.feed(99, 0.51)      # tiny span
        assert learn.finish().param == 412

    def test_two_controls_moving_together_is_ambiguous_not_a_coin_flip(self):
        learn = Learner(Clock())
        learn.begin("something")
        sweep(learn, 412)
        sweep(learn, 413)
        r = learn.finish()
        assert not r.ok
        assert "ambiguous" in r.reason
        assert "412" in r.reason and "413" in r.reason

    def test_nothing_moving_is_refused(self):
        learn = Learner(Clock())
        learn.begin("cutoff")
        r = learn.finish()
        assert not r.ok and r.reason == "nothing moved"

    def test_a_single_stray_write_is_not_a_knob_turn(self):
        learn = Learner(Clock())
        learn.begin("cutoff")
        learn.feed(412, 0.0)
        learn.feed(412, 1.0)          # full span, but only 2 writes
        r = learn.finish()
        assert not r.ok
        assert "nothing moved enough" in r.reason
        assert MIN_COUNT == 3

    def test_a_parameter_that_barely_moves_is_refused(self):
        learn = Learner(Clock())
        learn.begin("cutoff")
        for i in range(50):
            learn.feed(412, 0.5 + i * 1e-5)
        r = learn.finish()
        assert not r.ok
        assert MIN_SPAN > 1e-5 * 50

    def test_a_clear_winner_needs_to_beat_the_runner_up_by_the_margin(self):
        learn = Learner(Clock())
        learn.begin("x")
        sweep(learn, 1, n=40)                    # score ~40
        sweep(learn, 2, n=40, lo=0.0, hi=0.2)    # score ~8, well under 40/MARGIN
        assert MARGIN == 2.0
        assert learn.finish().param == 1

    def test_feeding_before_begin_is_ignored(self):
        learn = Learner(Clock())
        learn.feed(412, 0.5)
        learn.begin("cutoff")
        r = learn.finish()
        assert not r.ok, "writes from before the pass must not count"

    def test_finish_ends_the_pass(self):
        learn = Learner(Clock())
        learn.begin("x")
        sweep(learn, 1)
        learn.finish()
        assert learn.active is False
        learn.feed(1, 0.9)
        assert learn.finish().param is None, "a finished pass accepts nothing more"

    def test_begin_clears_the_previous_pass(self):
        learn = Learner(Clock())
        learn.begin("first")
        sweep(learn, 1)
        learn.begin("second")
        sweep(learn, 2)
        assert learn.finish().param == 2

    @pytest.mark.parametrize("bad", ["", " lead", "a" * 65, "semi;colon", "quote'"])
    def test_unusable_labels_are_refused(self, bad):
        with pytest.raises(LearnError):
            Learner(Clock()).begin(bad)

    @pytest.mark.parametrize("good", ["cutoff", "LFO 2 rate", "filter/res", "osc-1 (fine)"])
    def test_usable_labels(self, good):
        learn = Learner(Clock())
        learn.begin(good)
        assert learn.label == good

    def test_candidates_are_reported_even_when_the_pass_fails(self):
        learn = Learner(Clock())
        learn.begin("x")
        learn.feed(7, 0.5)
        r = learn.finish()
        assert [c.param for c in r.candidates] == [7]
        assert r.as_dict()["candidates"][0]["param"] == 7


class TestParamMap:
    def test_starts_with_what_is_already_known(self):
        assert ParamMap().name_for(358) == "master volume"
        assert 358 in KNOWN

    def test_unknown_ids_name_themselves(self):
        assert ParamMap().name_for(999) == "param 999"

    def test_learn_and_forget(self):
        m = ParamMap()
        m.learn(412, "cutoff")
        assert m.name_for(412) == "cutoff"
        m.forget(412)
        assert m.name_for(412) == "param 412"

    def test_forgetting_something_absent_is_harmless(self):
        ParamMap().forget(12345)

    def test_a_duplicate_name_is_refused_with_the_id_that_has_it(self):
        m = ParamMap()
        m.learn(412, "cutoff")
        with pytest.raises(LearnError, match="already param 412"):
            m.learn(413, "cutoff")

    def test_renaming_the_same_id_is_allowed(self):
        m = ParamMap()
        m.learn(412, "cutoff")
        m.learn(412, "cutoff")           # same id, same name
        m.learn(412, "filter cutoff")    # same id, new name
        assert m.name_for(412) == "filter cutoff"

    def test_round_trip(self, tmp_path):
        m = ParamMap()
        m.learn(412, "cutoff")
        m.learn(413, "resonance")
        path = m.save(tmp_path / "params.json")
        back = ParamMap.load(path)
        assert back.name_for(412) == "cutoff"
        assert back.name_for(413) == "resonance"
        assert back.name_for(358) == "master volume", "the known ids survive"

    def test_loading_an_absent_file_gives_the_known_ids(self, tmp_path):
        assert ParamMap.load(tmp_path / "nope.json").names == KNOWN

    def test_a_corrupt_file_raises_rather_than_starting_empty(self, tmp_path):
        p = tmp_path / "params.json"
        p.write_text("{not json")
        with pytest.raises(LearnError, match="not readable JSON"):
            ParamMap.load(p)

    def test_a_file_that_is_not_an_object_is_refused(self, tmp_path):
        p = tmp_path / "params.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(LearnError, match="object of id"):
            ParamMap.load(p)

    def test_a_non_numeric_key_is_refused(self, tmp_path):
        p = tmp_path / "params.json"
        p.write_text(json.dumps({"cutoff": "412"}))
        with pytest.raises(LearnError, match="not a parameter id"):
            ParamMap.load(p)

    def test_saved_json_is_readable(self, tmp_path):
        m = ParamMap()
        m.learn(412, "cutoff")
        raw = json.loads(m.save(tmp_path / "p.json").read_text())
        assert raw["412"] == "cutoff" and raw["358"] == "master volume"
