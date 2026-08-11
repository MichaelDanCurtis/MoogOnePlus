"""Node tree model and /g_queryTree.reply parser.

The reply is a flattened depth-first walk. Each entry is:
    node_id, num_children
and when num_children is -1 the node is a synth, which is followed by:
    defname[, num_controls, (name, value) * num_controls]
"""

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass
class SynthNode:
    node_id: int
    defname: str
    controls: dict = field(default_factory=dict)

    def walk(self) -> Iterator["SynthNode"]:
        yield self


@dataclass
class GroupNode:
    node_id: int
    children: list = field(default_factory=list)

    def walk(self) -> Iterator["SynthNode | GroupNode"]:
        yield self
        for child in self.children:
            yield from child.walk()


def parse_query_tree(args: list) -> GroupNode:
    """Parse the argument list of a /g_queryTree.reply into a tree."""
    with_controls = bool(args[0])
    pos = 1

    def read_node():
        nonlocal pos
        node_id = args[pos]
        num_children = args[pos + 1]
        pos += 2
        if num_children == -1:
            defname = args[pos]
            pos += 1
            controls = {}
            if with_controls:
                num_controls = args[pos]
                pos += 1
                for _ in range(num_controls):
                    controls[args[pos]] = args[pos + 1]
                    pos += 2
            return SynthNode(node_id, defname, controls)
        if num_children < 0:
            # -1 is the only negative value with meaning (the synth
            # marker, handled above). Anything else negative is malformed
            # input: falling through to the group branch below would let
            # range(num_children) silently yield zero children, producing
            # a plausible-looking empty group instead of surfacing the
            # bad reply.
            raise ValueError(
                f"node {node_id}: invalid child count {num_children} (only -1 marks a synth)"
            )
        node = GroupNode(node_id)
        for _ in range(num_children):
            node.children.append(read_node())
        return node

    return read_node()
