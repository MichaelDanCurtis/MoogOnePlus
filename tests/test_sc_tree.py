import pytest

from moogone.sc.tree import GroupNode, SynthNode, parse_query_tree


def test_parses_flat_reply_with_one_synth():
    # flag=1, root group 0, 1 child: synth 1000 "reverb" with 2 controls
    args = [1, 0, 1, 1000, -1, "reverb", 2, "mix", 0.3, "damp", 0.5]
    root = parse_query_tree(args)
    assert root.node_id == 0
    assert len(root.children) == 1
    synth = root.children[0]
    assert isinstance(synth, SynthNode)
    assert synth.defname == "reverb"
    assert synth.controls == {"mix": pytest.approx(0.3), "damp": pytest.approx(0.5)}


def test_parses_nested_groups():
    # root 0 has 1 child: group 1 with 1 child: synth 1000 "delay", 0 controls
    args = [1, 0, 1, 1, 1, 1000, -1, "delay", 0]
    root = parse_query_tree(args)
    group = root.children[0]
    assert isinstance(group, GroupNode)
    assert group.node_id == 1
    assert group.children[0].defname == "delay"


def test_parses_reply_without_controls():
    # flag=0 means no control data follows the defname
    args = [0, 0, 1, 1000, -1, "reverb"]
    root = parse_query_tree(args)
    assert root.children[0].controls == {}


def test_control_mapped_to_a_bus_keeps_its_string_value():
    args = [1, 0, 1, 1000, -1, "reverb", 1, "in", "a0"]
    root = parse_query_tree(args)
    assert root.children[0].controls["in"] == "a0"


def test_walk_yields_every_node_depth_first():
    args = [1, 0, 2, 1, 1, 1000, -1, "delay", 0, 1001, -1, "reverb", 0]
    root = parse_query_tree(args)
    ids = [n.node_id for n in root.walk()]
    assert ids == [0, 1, 1000, 1001]


def test_client_queries_the_mock_tree(client):
    root = client.query_tree()
    names = [n.defname for n in root.walk() if isinstance(n, SynthNode)]
    assert "moog_fx_reverb" in names


def test_mock_tree_exposes_control_names(client):
    root = client.query_tree()
    reverb = next(n for n in root.walk() if getattr(n, "defname", None) == "moog_fx_reverb")
    assert "in_trim" in reverb.controls
