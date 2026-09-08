"""The SuperCollider effects as a control surface.

This is the one part of Vox that stands on a path verified on hardware this session:
``/g_queryTree`` and ``/n_set`` against ``scsynth`` on 57110. Everything here is badged
``live`` for that reason and no other.

``/n_set`` is fire-and-forget. :meth:`FxWorkbench.confirm` re-reads the tree and compares;
a value is *confirmed* only when the server says it holds it. That distinction — sent
versus confirmed — is carried all the way to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..sc.client import ScClient
from ..sc.tree import GroupNode, SynthNode

# Range inference by control name. Values observed on the live tree: mix/feedback/tone/pan
# sit in 0..1; gain-family controls have been seen at 0.98 and 1.0 with headroom expected;
# times are seconds (timeL 0.0416 = 41.6 ms). Bus indices are not for turning.
_UNIT = {"mix", "wet", "dry", "feedback", "tone", "ctl", "pan", "offset"}
_GAIN = {"g_in", "g_out", "volume"}  # plus anything containing "gain"
#: EMPTY, DELIBERATELY. `enable` looks like a switch and is not one.
#:
#: On this instrument `enable` gates an envelope whose `doneAction` decides what
#: happens on release, and the two cases are not comparable:
#:
#:   inputRouter, outputRouter, and every native effect
#:       EnvGen.kr(Env.asr(0.1, 1, 0.1), enable, doneAction: 2)   -- FREES the node
#:   the ten et_* Eventide wrappers
#:       ... doneAction: 1                                        -- pauses it
#:
#: So writing `enable = 0` to the input router does not mute the send, it destroys
#: it, and nothing short of restarting the audio engine brings it back. Offering
#: that as a toggle in a UI is a trap; the panel's own `/fx` messages change effects
#: through the engine's state machine instead, which parks rather than frees.
#:
#: Kept as a named empty set rather than deleted, so this reasoning survives.
_SWITCH: set[str] = set()
# Bus/routing indices are not for turning. Matched by exact name or a "bus" suffix — NOT
# by an "in"/"out" suffix, which would also catch "gain", "sustain", and "out_gain".
_READONLY = {"in", "out", "ctlin", "ctlout", "enable"}


@dataclass(frozen=True)
class ControlSpec:
    name: str | int  # int when scsynth names a control only by its index
    value: float
    lo: float
    hi: float
    kind: str  # "range" | "switch" | "readonly"


@dataclass(frozen=True)
class FxNodeInfo:
    node_id: int
    defname: str
    controls: tuple[ControlSpec, ...]


def infer_range(name: str | int, value: float) -> tuple[float, float, str]:
    v = float(value)
    # scsynth sends a control's INDEX, as an int, when the SynthDef gave it no name.
    # The real instrument does this 53 times in one synth (`inputRouter`); the mock
    # never did, so this arrived only on hardware. There is no name to reason from, so
    # do not pretend to a range: show the value and refuse to write. Guessing at an
    # unnamed control on a live audio router is how this project locked the synth up.
    if not isinstance(name, str):
        return v, v, "readonly"
    n = name.lower()
    if n in _SWITCH:
        return 0.0, 1.0, "switch"
    if n in _UNIT:
        return 0.0, 1.0, "range"
    if n in _GAIN or "gain" in n:
        return 0.0, 2.0, "range"
    if n.startswith("time"):
        return 0.0, 2.0, "range"
    if n in _READONLY or n.endswith("bus"):
        return v, v, "readonly"
    # Unknown: bracket the current value with room above it, never a zero-width range.
    return min(0.0, v), max(1.0, 2.0 * abs(v)), "range"


def nodes_from_tree(root: GroupNode) -> list[FxNodeInfo]:
    out: list[FxNodeInfo] = []

    def walk(node) -> None:
        if isinstance(node, SynthNode):
            specs = tuple(
                ControlSpec(name, float(v), *infer_range(name, float(v)))
                for name, v in node.controls.items()
            )
            out.append(FxNodeInfo(node.node_id, node.defname, specs))
        elif isinstance(node, GroupNode):
            for child in node.children:
                walk(child)

    walk(root)
    return out


class FxWorkbench:
    def __init__(self, client: ScClient):
        self._client = client
        self._nodes: list[FxNodeInfo] = []

    def refresh(self, timeout: float = 2.0) -> list[FxNodeInfo]:
        self._nodes = nodes_from_tree(self._client.query_tree(timeout=timeout))
        return self._nodes

    @property
    def nodes(self) -> list[FxNodeInfo]:
        return self._nodes

    def set(self, node_id: int, name: str, value: float) -> None:
        """Send. This proves nothing about the server; see :meth:`confirm`."""
        self._client.n_set(node_id, **{name: float(value)})

    def confirm(
        self,
        node_id: int,
        name: str,
        expected: float,
        tol: float = 1e-4,
        timeout: float = 2.0,
    ) -> tuple[bool, float | None]:
        """Re-read the tree. Returns ``(took, value_seen)``.

        Raises if the server cannot be read — a server that does not answer is not a
        server that confirmed anything.
        """
        for n in self.refresh(timeout=timeout):
            if n.node_id != node_id:
                continue
            for c in n.controls:
                if c.name == name:
                    return abs(c.value - float(expected)) <= tol, c.value
            return False, None
        return False, None
