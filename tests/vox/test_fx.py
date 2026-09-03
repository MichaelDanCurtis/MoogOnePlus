"""FX workbench. The discriminating cases: a range guessed wrong, and a 'confirmed' that lied."""

import pytest

from moogone.mock.server import MockScsynth
from moogone.sc.client import ScClient, ScTimeout
from moogone.sc.tree import GroupNode, SynthNode
from moogone.transport.udp import UdpTransport
from moogone.vox.fx import FxWorkbench, infer_range, nodes_from_tree


class TestInferRange:
    @pytest.mark.parametrize(
        "name,value,expected",
        [
            ("mix", 0.24, (0.0, 1.0, "range")),
            ("feedback", 0.6, (0.0, 1.0, "range")),
            ("tone", 0.75, (0.0, 1.0, "range")),
            ("pan", 0.5, (0.0, 1.0, "range")),
            ("gain", 1.0, (0.0, 2.0, "range")),
            ("g_out", 0.98, (0.0, 2.0, "range")),
            ("g_in", 1.0, (0.0, 2.0, "range")),
            ("timeL", 0.0416, (0.0, 2.0, "range")),
            ("time", 0.031, (0.0, 2.0, "range")),
            ("enable", 1.0, (0.0, 1.0, "switch")),
            ("inBus", 12.0, (12.0, 12.0, "readonly")),
            ("ctlOut", 0.0, (0.0, 0.0, "readonly")),
        ],
    )
    def test_known_names(self, name, value, expected):
        assert infer_range(name, value) == expected

    def test_unknown_name_brackets_the_current_value(self):
        """An unknown control must still be adjustable, and must include its current value."""
        lo, hi, kind = infer_range("wobble", 3.0)
        assert kind == "range"
        assert lo <= 3.0 <= hi
        assert hi >= 6.0  # room to go up, not a range that pins the value at its ceiling

    def test_unknown_name_with_zero_value_is_not_a_zero_width_range(self):
        lo, hi, _kind = infer_range("wobble", 0.0)
        assert hi > lo


class TestNodesFromTree:
    def test_flattens_nested_groups_and_keeps_order(self):
        root = GroupNode(
            0,
            [
                GroupNode(1, [SynthNode(1035, "pingpongDelay_0", {"mix": 0.24, "enable": 1.0})]),
                SynthNode(1036, "delay_0", {"time": 0.031}),
            ],
        )
        nodes = nodes_from_tree(root)
        assert [n.node_id for n in nodes] == [1035, 1036]
        assert nodes[0].defname == "pingpongDelay_0"
        specs = {c.name: c for c in nodes[0].controls}
        assert specs["mix"].kind == "range" and specs["enable"].kind == "switch"

    def test_groups_are_not_nodes(self):
        """A group is not a synth; presenting it as one would offer controls that do not exist."""
        assert nodes_from_tree(GroupNode(0, [GroupNode(1, [])])) == []


def _first_range_control(mock: MockScsynth):
    for n in nodes_from_tree(mock.node_tree):
        for c in n.controls:
            if c.kind == "range":
                return n.node_id, c.name, c.value
    raise AssertionError("mock tree has no range control")


class TestFxWorkbenchAgainstMock:
    def test_refresh_returns_the_mock_tree(self):
        with MockScsynth() as mock:
            wb = FxWorkbench(ScClient(UdpTransport("127.0.0.1", mock.port)))
            nodes = wb.refresh()
            assert {n.node_id for n in nodes} == {
                n.node_id for n in nodes_from_tree(mock.node_tree)
            }

    def test_set_then_confirm_reads_back_the_new_value(self):
        with MockScsynth() as mock:
            wb = FxWorkbench(ScClient(UdpTransport("127.0.0.1", mock.port)))
            node, ctl, old = _first_range_control(mock)
            new = 0.5 if abs(old - 0.5) > 0.1 else 0.25
            wb.set(node, ctl, new)
            ok, seen = wb.confirm(node, ctl, new)
            assert ok is True
            assert seen == pytest.approx(new, abs=1e-4)

    def test_confirm_never_says_yes_when_the_server_is_silent(self):
        """The property that matters: confirm must not say yes because we *sent* something.

        A server that does not answer cannot have confirmed anything, so this must raise
        rather than return (True, 0.77).
        """
        with MockScsynth() as mock:
            wb = FxWorkbench(ScClient(UdpTransport("127.0.0.1", mock.port)))
            node, ctl, _old = _first_range_control(mock)
            mock.silent = True
            wb.set(node, ctl, 0.77)
            with pytest.raises(ScTimeout):
                wb.confirm(node, ctl, 0.77, timeout=0.3)

    def test_confirm_detects_a_different_value(self):
        with MockScsynth() as mock:
            wb = FxWorkbench(ScClient(UdpTransport("127.0.0.1", mock.port)))
            node, ctl, old = _first_range_control(mock)
            ok, seen = wb.confirm(node, ctl, old + 0.31)
            assert ok is False
            assert seen == pytest.approx(old, abs=1e-6)

    def test_confirm_on_unknown_node_is_false_not_error(self):
        with MockScsynth() as mock:
            wb = FxWorkbench(ScClient(UdpTransport("127.0.0.1", mock.port)))
            assert wb.confirm(999999, "mix", 0.5) == (False, None)
