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
_GAIN = {"gain", "g_in", "g_out", "volume"}
_SWITCH = {"enable"}
_READONLY_SUFFIX = ("bus", "in", "out")


@dataclass(frozen=True)
class ControlSpec:
    name: str
    value: float
    lo: float
    hi: float
    kind: str  # "range" | "switch" | "readonly"


@dataclass(frozen=True)
class FxNodeInfo:
    node_id: int
    defname: str
    controls: tuple[ControlSpec, ...]


def infer_range(name: str, value: float) -> tuple[float, float, str]:
    n = name.lower()
    v = float(value)
    if n in _SWITCH:
        return 0.0, 1.0, "switch"
    if n in _UNIT:
        return 0.0, 1.0, "range"
    if n in _GAIN:
        return 0.0, 2.0, "range"
    if n.startswith("time"):
        return 0.0, 2.0, "range"
    if n.endswith(_READONLY_SUFFIX):
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
