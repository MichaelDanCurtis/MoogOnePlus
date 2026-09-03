"""A synthetic node tree shaped like a plausible Moog One FX chain.

This is a guess, not a recording. Its purpose is to exercise the parser and
the client, not to predict what las-sc actually reports. September replaces
it with a real capture.
"""

from ..sc.tree import GroupNode, SynthNode


def default_tree() -> GroupNode:
    return GroupNode(
        0,
        [
            GroupNode(
                1,
                [
                    SynthNode(
                        1000,
                        "moog_fx_delay",
                        {
                            "in_trim": 1.0,
                            "time": 0.35,
                            "feedback": 0.4,
                            "mix": 0.25,
                            "out_gain": 1.0,
                        },
                    ),
                    SynthNode(
                        1001,
                        "moog_fx_reverb",
                        {"in_trim": 1.0, "size": 0.6, "damp": 0.5, "mix": 0.3, "out_gain": 1.0},
                    ),
                    # The real instrument's `inputRouter` carries 53 controls the
                    # SynthDef never named, and scsynth reports each by its integer
                    # index instead of a string. The mock lacked one, so code that
                    # assumed a string name passed every test and then broke on
                    # hardware. Two of them live here now so it cannot happen twice.
                    SynthNode(
                        1002,
                        "inputRouter",
                        {"enable": 1.0, 2: 0.0, 3: 0.532},
                    ),
                ],
            )
        ],
    )


def serialise(root: GroupNode, with_controls: bool) -> list:
    """Flatten a tree into /g_queryTree.reply argument order."""
    args: list = [1 if with_controls else 0]

    def emit(node):
        if isinstance(node, SynthNode):
            args.extend([node.node_id, -1, node.defname])
            if with_controls:
                args.append(len(node.controls))
                for name, value in node.controls.items():
                    args.extend([name, value])
        else:
            args.extend([node.node_id, len(node.children)])
            for child in node.children:
                emit(child)

    emit(root)
    return args
