"""A patch graph, and the SuperCollider it becomes.

Nodes, cables, and a code generator — the VCV-Rack shape applied to the effects engine
that already runs on the instrument. The graph is validated before a line of source is
written, because a patch that is wrong should be refused here where the reason can be
pointed at, not on a server that answers with a stack trace or with silence.

**Source, not bytes.** ``d_recv`` takes a *compiled* SynthDef, and compiling one is a
well-documented binary format — but this machine has no SuperCollider to check the output
against, and an unverifiable binary encoder is exactly the kind of confident-looking wrong
answer this project keeps finding. So the generator emits readable ``.scd`` you can check
by eye, paste into SuperCollider, or send to the box's own ``sclang``. A binary backend
can slot in behind the same graph once there is a reference compiler to test it against.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ugens import ALL, BINARY_OPS, RATE_SUFFIX, RATES, spec

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PatchError(ValueError):
    """A graph that cannot become valid SuperCollider, with the reason."""


@dataclass
class Node:
    id: str
    kind: str  # a key in ugens.ALL
    rate: str = "audio"  # scalar | control | audio
    params: dict[str, float] = field(default_factory=dict)  # unconnected input values
    name: str = ""  # for `control` nodes: the parameter name
    default: float = 0.0  # for `control` nodes: its initial value

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "rate": self.rate,
            "params": dict(self.params),
            "name": self.name,
            "default": self.default,
        }


#: Outlet meaning "every channel of a multi-output UGen", not one of them. Connecting a
#: stereo Pan2 to Out with outlet 0 sends the left channel alone, which is almost never
#: what someone dragging that cable meant.
ALL_CHANNELS = -1


@dataclass(frozen=True)
class Cable:
    src: str  # node id
    dst: str  # node id
    port: str  # input port name on dst
    outlet: int = 0  # which output of src; ALL_CHANNELS for the whole array

    def as_dict(self) -> dict:
        return {"src": self.src, "dst": self.dst, "port": self.port, "outlet": self.outlet}


@dataclass
class Patch:
    name: str = "voxPatch"
    nodes: list[Node] = field(default_factory=list)
    cables: list[Cable] = field(default_factory=list)

    # -- lookup -------------------------------------------------------------
    def node(self, node_id: str) -> Node:
        for n in self.nodes:
            if n.id == node_id:
                return n
        raise PatchError(f"no node with id {node_id!r}")

    def incoming(self, node_id: str) -> dict[str, Cable]:
        return {c.port: c for c in self.cables if c.dst == node_id}

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "nodes": [n.as_dict() for n in self.nodes],
            "cables": [c.as_dict() for c in self.cables],
        }

    @classmethod
    def from_dict(cls, d: dict) -> Patch:
        nodes = [
            Node(
                id=str(n["id"]),
                kind=str(n["kind"]),
                rate=str(n.get("rate", "audio")),
                params={str(k): float(v) for k, v in (n.get("params") or {}).items()},
                name=str(n.get("name", "")),
                default=float(n.get("default", 0.0)),
            )
            for n in d.get("nodes", [])
        ]
        cables = [
            Cable(str(c["src"]), str(c["dst"]), str(c["port"]), int(c.get("outlet", 0)))
            for c in d.get("cables", [])
        ]
        return cls(str(d.get("name", "voxPatch")), nodes, cables)


# ── validation ─────────────────────────────────────────────────────────────


def validate(patch: Patch) -> list[str]:
    """Every problem with this graph, in reading order. Empty means it will compile.

    Returns problems rather than raising on the first, because a patcher user wants to
    see everything that is wrong at once, not play whack-a-mole.
    """
    problems: list[str] = []

    if not _IDENT.match(patch.name):
        problems.append(
            f"patch name {patch.name!r} is not a valid SuperCollider identifier "
            "(letters, digits and underscore; must not start with a digit)"
        )

    seen: set[str] = set()
    for n in patch.nodes:
        if n.id in seen:
            problems.append(f"duplicate node id {n.id!r}")
        seen.add(n.id)
        if n.kind not in ALL:
            problems.append(f"node {n.id!r}: unknown UGen {n.kind!r}")
            continue
        s = spec(n.kind)
        if n.rate not in RATES:
            problems.append(f"node {n.id!r}: unknown rate {n.rate!r}")
        elif n.rate not in s.rates and n.kind != "control":
            problems.append(
                f"node {n.id!r}: {s.name} does not run at {n.rate} rate "
                f"(it offers {', '.join(s.rates)})"
            )
        if n.kind == "control" and not _IDENT.match(n.name or ""):
            problems.append(
                f"node {n.id!r}: a control needs a valid parameter name, got {n.name!r}"
            )
        for key in n.params:
            if s.port(key) is None:
                problems.append(f"node {n.id!r}: {s.name} has no input called {key!r}")

    # Cables
    for c in patch.cables:
        if c.src not in seen:
            problems.append(f"cable to {c.dst!r}.{c.port}: no node {c.src!r}")
            continue
        if c.dst not in seen:
            problems.append(f"cable from {c.src!r}: no node {c.dst!r}")
            continue
        dst = patch.node(c.dst)
        if dst.kind not in ALL:
            continue
        s = spec(dst.kind)
        if s.port(c.port) is None:
            problems.append(f"{s.name} ({c.dst!r}) has no input called {c.port!r}")
        src_spec = spec(patch.node(c.src).kind)
        if c.outlet == ALL_CHANNELS:
            if src_spec.outputs < 2:
                problems.append(
                    f"cable from {c.src!r}: {src_spec.name} has a single output, so there is "
                    "no channel array to pass whole"
                )
        elif not 0 <= c.outlet < max(1, src_spec.outputs):
            problems.append(
                f"cable from {c.src!r}: outlet {c.outlet} does not exist "
                f"({src_spec.name} has {src_spec.outputs})"
            )

    # One cable per input; a second is ambiguous rather than a mix.
    by_input: dict[tuple[str, str], int] = {}
    for c in patch.cables:
        by_input[(c.dst, c.port)] = by_input.get((c.dst, c.port), 0) + 1
    for (dst, port), count in sorted(by_input.items()):
        if count > 1:
            problems.append(
                f"{dst!r}.{port} has {count} cables into it; connect one, or sum them "
                "with a math node first"
            )

    # Required inputs
    for n in patch.nodes:
        if n.kind not in ALL:
            continue
        s = spec(n.kind)
        connected = set(patch.incoming(n.id))
        for p in s.inputs:
            if p.required and p.name not in connected and p.name not in n.params:
                problems.append(f"{s.name} ({n.id!r}): input {p.name!r} must be connected")

    # Rates: a UGen may not consume something faster than itself.
    for c in patch.cables:
        if c.src not in seen or c.dst not in seen:
            continue
        src, dst = patch.node(c.src), patch.node(c.dst)
        if src.rate not in RATES or dst.rate not in RATES:
            continue
        if RATES.index(src.rate) > RATES.index(dst.rate):
            problems.append(
                f"{src.id!r} runs at {src.rate} rate but feeds {dst.id!r}.{c.port} which runs "
                f"at {dst.rate} — raise {dst.id!r} to {src.rate}, or slow {src.id!r} down"
            )

    problems.extend(_cycles(patch))

    outs = [n for n in patch.nodes if n.kind == "Out"]
    if not outs:
        problems.append("the patch has no Out node, so it would produce no sound")

    return problems


def _cycles(patch: Patch) -> list[str]:
    """Report feedback loops. SuperCollider needs an explicit delay to close one, so an
    accidental loop is a graph that cannot be ordered — better named than silently cut."""
    adj: dict[str, list[str]] = {n.id: [] for n in patch.nodes}
    for c in patch.cables:
        if c.src in adj and c.dst in adj:
            adj[c.src].append(c.dst)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(adj, WHITE)
    stack: list[str] = []
    found: list[str] = []

    def walk(u: str) -> None:
        colour[u] = GREY
        stack.append(u)
        for v in adj[u]:
            if colour[v] == GREY:
                loop = stack[stack.index(v) :] + [v]
                found.append("feedback loop: " + " -> ".join(loop))
            elif colour[v] == WHITE:
                walk(v)
        stack.pop()
        colour[u] = BLACK

    for node_id in adj:
        if colour[node_id] == WHITE:
            walk(node_id)
    # The same loop is reported once per entry point; keep one of each.
    return sorted(set(found))


def order(patch: Patch) -> list[Node]:
    """Nodes in evaluation order. Raises if the graph has a cycle."""
    problems = _cycles(patch)
    if problems:
        raise PatchError(problems[0])
    indeg = {n.id: 0 for n in patch.nodes}
    adj: dict[str, list[str]] = {n.id: [] for n in patch.nodes}
    for c in patch.cables:
        if c.src in adj and c.dst in indeg:
            adj[c.src].append(c.dst)
            indeg[c.dst] += 1
    # Stable: ties resolve in the order nodes were added, so the output does not
    # reshuffle between runs of an unchanged patch.
    position = {n.id: i for i, n in enumerate(patch.nodes)}
    ready = sorted([i for i, d in indeg.items() if d == 0], key=position.get)
    out: list[Node] = []
    while ready:
        nid = ready.pop(0)
        out.append(patch.node(nid))
        for v in adj[nid]:
            indeg[v] -= 1
            if indeg[v] == 0:
                ready.append(v)
                ready.sort(key=position.get)
    if len(out) != len(patch.nodes):
        raise PatchError("graph could not be ordered; it still contains a cycle")
    return out


# ── code generation ────────────────────────────────────────────────────────


def _num(v: float) -> str:
    """Numbers SuperCollider reads back as written — never `1e-05` or a bare `1.`."""
    f = float(v)
    if f == int(f) and abs(f) < 1e15:
        return f"{int(f)}"
    return f"{f:.6f}".rstrip("0").rstrip(".")


def _var(node_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", node_id)
    return f"~x_{safe}" if safe[:1].isdigit() else f"x_{safe}"


def to_source(patch: Patch) -> str:
    """Generate the SynthDef. Raises :class:`PatchError` if the graph is not valid."""
    problems = validate(patch)
    if problems:
        raise PatchError("; ".join(problems))

    nodes = order(patch)
    controls = [n for n in nodes if n.kind == "control"]
    body: list[str] = []
    local_vars = [_var(n.id) for n in nodes if n.kind != "control" and spec(n.kind).outputs > 0]

    for n in nodes:
        if n.kind == "control":
            continue
        s = spec(n.kind)
        incoming = patch.incoming(n.id)
        args: list[str] = []
        for p in s.inputs:
            if p.name in incoming:
                c = incoming[p.name]
                src = patch.node(c.src)
                ref = src.name if src.kind == "control" else _var(c.src)
                if (
                    src.kind != "control"
                    and spec(src.kind).outputs > 1
                    and c.outlet != ALL_CHANNELS
                ):
                    ref = f"{ref}[{c.outlet}]"
                args.append(ref)
            elif p.name in n.params:
                args.append(_num(n.params[p.name]))
            else:
                args.append(_num(p.default if p.default is not None else 0.0))

        if n.kind.startswith("op."):
            sym = BINARY_OPS[n.kind.split(".", 1)[1]]
            expr = f"({args[0]} {sym} {args[1]})"
        elif n.kind == "Out":
            expr = f"Out.{RATE_SUFFIX[n.rate]}({', '.join(args)})"
        else:
            expr = f"{s.name}.{RATE_SUFFIX[n.rate]}({', '.join(args)})"

        if s.outputs == 0:
            body.append(f"    {expr};")
        else:
            body.append(f"    {_var(n.id)} = {expr};")

    arglist = ", ".join(f"{c.name} = {_num(c.default)}" for c in controls)
    header = (
        f"SynthDef(\\{patch.name}, {{ |{arglist}|" if controls else f"SynthDef(\\{patch.name}, {{"
    )
    lines = [
        "// Generated by Vox. Every value below came from the patch graph;",
        "// nothing here was inferred about the instrument.",
        header,
    ]
    if local_vars:
        lines.append(f"    var {', '.join(local_vars)};")
    lines.extend(body)
    lines.append("}).add;")
    return "\n".join(lines) + "\n"
