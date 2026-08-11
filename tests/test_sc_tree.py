import pytest

from moogone.mock.server import MockScsynth
from moogone.mock.tree import default_tree, serialise
from moogone.osc import OscMessage
from moogone.sc.client import ScClient, ScError
from moogone.sc.tree import GroupNode, SynthNode, parse_query_tree
from moogone.transport.udp import UdpTransport


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


def test_negative_child_count_other_than_minus_one_raises():
    """Only -1 marks a synth; any other negative child count is malformed.

    Without this guard, num_children == -2 (or any other negative-but-not
    -1 value) falls through to the group branch, where range(-2) silently
    yields zero children -- producing a plausible-looking empty group
    instead of surfacing the malformed input. Truncated input already
    raises IndexError loudly; this closes the other way a bad reply could
    be silently misparsed into a wrong-but-plausible tree.
    """
    args = [1, 0, -2]
    with pytest.raises(ValueError, match="invalid child count -2"):
        parse_query_tree(args)


def test_serialise_produces_the_exact_expected_argument_list():
    """serialise() must match the documented flat argument order exactly.

    The tests below that exercise serialise() indirectly (through the mock
    and the client) only check membership -- that a particular defname or
    control name is present *somewhere* in the result. None of them would
    catch a dropped node, a wrong node_id, or a corrupted control value
    for anything other than the one name/key they happen to inspect. This
    test compares the whole output list against a literal expectation for
    a small, hand-built tree, including a bus-mapped (string-valued)
    control, so a corrupted value has nowhere to hide.
    """
    tree = GroupNode(0, [SynthNode(1000, "delay", {"mix": 0.3, "in": "a0"})])
    args = serialise(tree, with_controls=True)
    assert args == [1, 0, 1, 1000, -1, "delay", 2, "mix", 0.3, "in", "a0"]


def test_serialise_and_parse_round_trip_with_controls():
    """serialise() -> parse_query_tree() must reproduce the original tree
    exactly, not just share a few visible names.

    Checked with whole-tree equality (dataclass equality composes
    recursively through GroupNode.children), not membership: a dropped
    node, wrong node_id, or corrupted control value anywhere in the tree
    would break this comparison. This alone can't catch a bug shared by
    serialise() and parse_query_tree() that misunderstands the wire
    format the same way in both directions -- that's what the literal
    argument-list test above is for, checked against the spec instead of
    against the other function.
    """
    tree = default_tree()
    round_tripped = parse_query_tree(serialise(tree, with_controls=True))
    assert round_tripped == tree


def test_serialise_and_parse_round_trip_without_controls_drops_only_controls():
    """flag=0 intentionally drops control data; everything else must survive.

    Asserts the specific, intentional information loss -- node ids,
    defnames and nesting identical to the original, controls collapsed to
    {} -- rather than skipping the flag=False case entirely.
    """
    tree = default_tree()
    round_tripped = parse_query_tree(serialise(tree, with_controls=False))

    def strip_controls(node):
        if isinstance(node, SynthNode):
            return SynthNode(node.node_id, node.defname, {})
        return GroupNode(node.node_id, [strip_controls(child) for child in node.children])

    assert round_tripped == strip_controls(tree)
    # Not vacuous: the original tree actually has controls to lose.
    assert any(n.controls for n in tree.walk() if isinstance(n, SynthNode))


def test_client_queries_the_mock_tree(client):
    root = client.query_tree()
    names = [n.defname for n in root.walk() if isinstance(n, SynthNode)]
    assert "moog_fx_reverb" in names


def test_mock_tree_exposes_control_names(client):
    root = client.query_tree()
    reverb = next(n for n in root.walk() if getattr(n, "defname", None) == "moog_fx_reverb")
    assert "in_trim" in reverb.controls


# --- IMPORTANT 3: a reply that drops the controls we asked for --------------


class _FlagLyingScsynth(MockScsynth):
    """Answers /g_queryTree with a structure-only reply (flag 0) no matter
    what the request asked for. This is what a las-sc build that ignores
    the control-values flag would look like on the wire: a well-formed,
    successfully-parsing reply in which every synth simply has no controls.
    """

    def handle(self, message):
        if message.address == "/g_queryTree":
            return OscMessage("/g_queryTree.reply", serialise(self.node_tree, False))
        return super().handle(message)


def _client_for(server):
    transport = UdpTransport("127.0.0.1", server.port)
    return ScClient(transport), transport


def test_query_tree_raises_when_the_reply_drops_the_controls_it_asked_for():
    """Capturing every control name is this call's entire purpose --
    harness/README.md names the capture "the source of truth" for the FX
    SynthDef's control names, and the harness template's one TODO-ON-HARDWARE
    marker points at it. A reply framed without controls parses perfectly
    into a tree where every synth has controls={}, which reads on the page
    as "this effect exposes no controls".

    Mutation-checked: delete the reply_with_controls comparison in
    ScClient.query_tree and this test fails -- query_tree returns a tree
    whose reverb synth has controls == {}, no exception at all.
    """
    with _FlagLyingScsynth() as server:
        client, transport = _client_for(server)
        try:
            with pytest.raises(ScError, match="control-values flag"):
                client.query_tree(with_controls=True)
        finally:
            transport.close()


def test_query_tree_accepts_a_matching_structure_only_reply():
    """The other direction: asking for a structure-only walk and getting one
    is not an error. Without this, 'always raise' would satisfy the test
    above.
    """
    with _FlagLyingScsynth() as server:
        client, transport = _client_for(server)
        try:
            root = client.query_tree(with_controls=False)
            assert isinstance(root, GroupNode)
            synths = [n for n in root.walk() if isinstance(n, SynthNode)]
            assert synths, "reply parsed to a tree with no synths at all"
            assert all(n.controls == {} for n in synths)
        finally:
            transport.close()


def test_query_tree_returns_controls_on_a_well_behaved_server(client):
    """And the normal path still works -- the guard must not reject a
    correct reply. Pins the positive case the two tests above bracket.
    """
    root = client.query_tree(with_controls=True)
    synths = [n for n in root.walk() if isinstance(n, SynthNode)]
    assert synths
    assert any(n.controls for n in synths), "no synth came back with any controls"
