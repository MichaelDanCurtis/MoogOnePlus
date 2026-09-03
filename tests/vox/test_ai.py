"""AskAI. Almost every case here is about the trust boundary: a model must not be able to
turn a hallucinated node, an out-of-range value, or a stray string into a write.
"""

import json

import pytest

from moogone.vox.ai import (
    MockProvider,
    ask_for_patch,
    describe_tree,
    extract_json,
    validate,
)
from moogone.vox.fx import ControlSpec, FxNodeInfo

TREE = [
    FxNodeInfo(
        1035,
        "pingpongDelay_0",
        (
            ControlSpec("mix", 0.24, 0.0, 1.0, "range"),
            ControlSpec("feedback", 0.6, 0.0, 1.0, "range"),
            ControlSpec("gain", 1.0, 0.0, 2.0, "range"),
            ControlSpec("enable", 1.0, 0.0, 1.0, "switch"),
            ControlSpec("inBus", 12.0, 12.0, 12.0, "readonly"),
        ),
    ),
    FxNodeInfo(1036, "delay_0", (ControlSpec("time", 0.03, 0.0, 2.0, "range"),)),
]


def prop_of(changes, reasoning="r"):
    return {"reasoning": reasoning, "changes": changes}


class TestDescribeTree:
    def test_lists_writable_controls_with_ranges(self):
        text = describe_tree(TREE)
        assert "node 1035 (pingpongDelay_0)" in text
        assert "feedback = 0.6   range 0..1" in text

    def test_omits_readonly_controls(self):
        """Cheaper to never show it than to reject it afterwards."""
        assert "inBus" not in describe_tree(TREE)

    def test_empty_tree_says_so_rather_than_being_blank(self):
        assert "no writable controls" in describe_tree([])


class TestExtractJson:
    def test_plain_object(self):
        assert extract_json('{"changes": []}') == {"changes": []}

    def test_ignores_prose_around_it(self):
        raw = 'Sure! Here you go:\n{"reasoning":"x","changes":[]}\nHope that helps.'
        assert extract_json(raw)["reasoning"] == "x"

    def test_handles_a_code_fence(self):
        assert extract_json('```json\n{"changes": [1]}\n```')["changes"] == [1]

    def test_strips_ansi_colour(self):
        assert extract_json('\x1b[32m{"changes": []}\x1b[0m') == {"changes": []}

    def test_skips_an_earlier_object_that_is_not_the_proposal(self):
        """CLIs print status objects first; the proposal is the one with 'changes'."""
        raw = '{"status":"thinking"}\n{"reasoning":"r","changes":[]}'
        assert extract_json(raw)["reasoning"] == "r"

    def test_handles_braces_inside_strings(self):
        raw = '{"reasoning":"use {curly} braces","changes":[]}'
        assert extract_json(raw)["reasoning"] == "use {curly} braces"

    def test_raises_when_there_is_no_proposal(self):
        with pytest.raises(ValueError, match="no JSON object"):
            extract_json("I cannot help with that.")

    def test_raises_on_an_object_without_changes(self):
        with pytest.raises(ValueError, match="no JSON object"):
            extract_json('{"reasoning": "forgot the changes key"}')


class TestValidateIsTheTrustBoundary:
    def test_accepts_a_good_change(self):
        p = validate(prop_of([{"node": 1035, "ctl": "mix", "value": 0.4, "why": "w"}]), TREE)
        assert len(p.changes) == 1 and not p.rejected
        assert p.changes[0].value == 0.4

    def test_drops_a_hallucinated_node(self):
        p = validate(prop_of([{"node": 9999, "ctl": "mix", "value": 0.4}]), TREE)
        assert p.changes == []
        assert "9999" in p.rejected[0]

    def test_drops_an_invented_control(self):
        p = validate(prop_of([{"node": 1035, "ctl": "warmth", "value": 0.4}]), TREE)
        assert p.changes == []
        assert "warmth" in p.rejected[0]

    def test_refuses_a_readonly_control(self):
        p = validate(prop_of([{"node": 1035, "ctl": "inBus", "value": 3}]), TREE)
        assert p.changes == []
        assert "read-only" in p.rejected[0]

    def test_clamps_above_range_and_says_so(self):
        p = validate(prop_of([{"node": 1035, "ctl": "mix", "value": 7.5}]), TREE)
        assert p.changes[0].value == 1.0
        assert "clamped" in p.changes[0].why

    def test_clamps_below_range(self):
        p = validate(prop_of([{"node": 1035, "ctl": "mix", "value": -3}]), TREE)
        assert p.changes[0].value == 0.0

    def test_respects_a_wider_range_for_gain(self):
        """A blanket 0..1 clamp would quietly cap gain at half its real range."""
        p = validate(prop_of([{"node": 1035, "ctl": "gain", "value": 1.8}]), TREE)
        assert p.changes[0].value == 1.8

    def test_rejects_non_finite_values(self):
        for bad in (float("nan"), float("inf")):
            p = validate(prop_of([{"node": 1035, "ctl": "mix", "value": bad}]), TREE)
            assert p.changes == [] and "finite" in p.rejected[0]

    def test_rejects_a_non_numeric_value(self):
        p = validate(prop_of([{"node": 1035, "ctl": "mix", "value": "loud"}]), TREE)
        assert p.changes == [] and "malformed" in p.rejected[0]

    def test_rejects_a_string_where_a_change_object_belongs(self):
        p = validate(prop_of(["rm -rf /"]), TREE)
        assert p.changes == [] and "not an object" in p.rejected[0]

    def test_rejects_changes_that_is_not_a_list(self):
        p = validate({"reasoning": "x", "changes": "everything"}, TREE)
        assert p.changes == [] and "not a list" in p.rejected[0]

    def test_keeps_good_changes_alongside_bad_ones(self):
        p = validate(
            prop_of(
                [
                    {"node": 1035, "ctl": "mix", "value": 0.3},
                    {"node": 4242, "ctl": "mix", "value": 0.3},
                    {"node": 1036, "ctl": "time", "value": 0.5},
                ]
            ),
            TREE,
        )
        assert [(c.node, c.ctl) for c in p.changes] == [(1035, "mix"), (1036, "time")]
        assert len(p.rejected) == 1

    def test_caps_the_number_of_changes(self):
        many = [{"node": 1035, "ctl": "mix", "value": 0.1}] * 100
        assert len(validate(prop_of(many), TREE).changes) <= 32

    def test_truncates_long_reasoning(self):
        p = validate(prop_of([], "x" * 5000), TREE)
        assert len(p.reasoning) <= 400

    def test_empty_tree_accepts_nothing(self):
        p = validate(prop_of([{"node": 1035, "ctl": "mix", "value": 0.4}]), [])
        assert p.changes == [] and p.rejected


class TestAskForPatch:
    def test_round_trip_with_the_mock(self):
        mock = MockProvider(
            json.dumps(prop_of([{"node": 1036, "ctl": "time", "value": 0.25, "why": "w"}]))
        )
        p = ask_for_patch(mock, TREE, "make it slower")
        assert len(p.changes) == 1 and p.changes[0].ctl == "time"

    def test_the_request_and_the_tree_both_reach_the_provider(self):
        mock = MockProvider(json.dumps(prop_of([])))
        ask_for_patch(mock, TREE, "dreamy pad")
        _system, user = mock.asked[0]
        assert "dreamy pad" in user
        assert "pingpongDelay_0" in user

    def test_a_model_that_answers_prose_raises_rather_than_writing_nothing_silently(self):
        with pytest.raises(ValueError, match="no JSON object"):
            ask_for_patch(MockProvider("I'd suggest turning up the reverb!"), TREE, "x")

    def test_proposal_serialises_for_the_wire(self):
        p = ask_for_patch(MockProvider(json.dumps(prop_of([]))), TREE, "x")
        d = p.as_dict()
        assert set(d) == {"reasoning", "changes", "rejected"}
