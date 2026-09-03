"""Ask an AI for a patch — and refuse to let it touch the synth directly.

Providers are **local agent CLIs already installed and logged in on this machine**, not
API keys. Probed 2026-09-03: ``grok -p`` answers; ``codex exec`` needs
``--skip-git-repo-check`` and a closed stdin; ``gemini -p`` is present; the ``claude``
CLI is installed but its OAuth session was expired. Nothing here stores, reads, or prints
a credential — each CLI uses whatever session its own config directory holds.

**The model never writes to the instrument.** It returns a *proposal*, which is validated
against the live node tree: unknown nodes and controls are dropped, values are clamped to
each control's own range, and read-only controls are refused. A human presses Apply, and
the write then goes through the same ``sent`` → ``confirmed`` path as every other change.

That boundary is the point. Model output is untrusted content — it is data describing a
patch, never an instruction this program obeys.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Protocol

SYSTEM = """You are helping shape sounds on a Moog One synthesiser's SuperCollider effects engine.

You will be given the live effect nodes and their controls, each with its current value and
allowed range. Propose control changes that achieve what the user asks for.

Answer with ONLY a JSON object, no prose, no code fence:

{"reasoning": "one short sentence",
 "changes": [{"node": 1035, "ctl": "feedback", "value": 0.62, "why": "longer tail"}]}

Rules:
- Only use node ids and control names from the list you are given.
- Keep every value inside the stated range.
- Change only what the request needs — 1 to 6 changes is usually right.
- If the request cannot be met with these controls, return an empty changes list and say
  why in reasoning.
"""


@dataclass(frozen=True)
class Change:
    node: int
    ctl: str
    value: float
    why: str = ""

    def as_dict(self) -> dict:
        return {"node": self.node, "ctl": self.ctl, "value": self.value, "why": self.why}


@dataclass
class Proposal:
    reasoning: str = ""
    changes: list[Change] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    raw: str = ""

    def as_dict(self) -> dict:
        return {
            "reasoning": self.reasoning,
            "changes": [c.as_dict() for c in self.changes],
            "rejected": self.rejected,
        }


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def ask(self, system: str, user: str, timeout: float) -> str: ...


@dataclass
class CliProvider:
    """An agent CLI driven single-turn over stdout.

    ``argv`` is built per provider; the prompt is passed as one argument, never through a
    shell, so nothing in it can be interpreted as a command.
    """

    name: str
    binary: str
    args: tuple[str, ...]

    def available(self) -> bool:
        return shutil.which(self.binary) is not None

    def ask(self, system: str, user: str, timeout: float = 120.0) -> str:
        if not self.available():
            raise RuntimeError(f"{self.binary!r} is not on PATH")
        prompt = f"{system}\n\n---\n\n{user}"
        proc = subprocess.run(
            [self.binary, *self.args, prompt],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        if proc.returncode != 0 and not proc.stdout.strip():
            raise RuntimeError(f"{self.name} failed: {proc.stderr.strip()[:300]}")
        return proc.stdout


#: Local CLIs, in the order they were found to work on this machine.
PROVIDERS: dict[str, CliProvider] = {
    "grok": CliProvider("grok", "grok", ("-p",)),
    "codex": CliProvider("codex", "codex", ("exec", "--skip-git-repo-check")),
    "gemini": CliProvider("gemini", "gemini", ("-p",)),
    "claude": CliProvider("claude", "claude", ("-p",)),
}


class MockProvider:
    """Returns a canned reply. Lets every test run with no CLI and no network."""

    name = "mock"

    def __init__(self, reply: str = ""):
        self.reply = reply or json.dumps(
            {"reasoning": "mock", "changes": [{"node": 1035, "ctl": "mix", "value": 0.5}]}
        )
        self.asked: list[tuple[str, str]] = []

    def available(self) -> bool:
        return True

    def ask(self, system: str, user: str, timeout: float = 0.0) -> str:
        self.asked.append((system, user))
        return self.reply


def available_providers() -> list[str]:
    return [n for n, p in PROVIDERS.items() if p.available()]


def describe_tree(nodes) -> str:
    """Render the live tree as the context the model gets.

    Read-only controls are omitted entirely — the model cannot propose what it cannot see,
    which is cheaper than rejecting it afterwards.
    """
    lines = []
    for n in nodes:
        writable = [c for c in n.controls if c.kind != "readonly"]
        if not writable:
            continue
        lines.append(f"node {n.node_id} ({n.defname}):")
        for c in writable:
            lines.append(f"  {c.name} = {c.value:g}   range {c.lo:g}..{c.hi:g} ({c.kind})")
    return "\n".join(lines) if lines else "(no writable controls)"


def extract_json(text: str) -> dict:
    """Pull the proposal object out of whatever the CLI printed.

    Agent CLIs wrap answers in banners, ANSI colour, and sometimes a code fence. Scan for
    the first balanced ``{...}`` that parses and contains ``changes`` — searching for a
    fence alone fails on the ones that do not use it.
    """
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    for start in (m.start() for m in re.finditer(r"\{", cleaned)):
        depth, in_str, esc = 0, False, False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[start : i + 1])
                    except ValueError:
                        break
                    if isinstance(obj, dict) and "changes" in obj:
                        return obj
                    break
    raise ValueError("no JSON object with a 'changes' key in the reply")


def validate(obj: dict, nodes) -> Proposal:
    """Check a proposal against the live tree. This is the trust boundary.

    Anything the tree does not contain is dropped with a reason, and every surviving value
    is clamped into the control's own range. A model that hallucinates a node, invents a
    control, or asks for a value out of range cannot produce a write.
    """
    index = {}
    for n in nodes:
        for c in n.controls:
            index[(n.node_id, c.name)] = c

    prop = Proposal(reasoning=str(obj.get("reasoning", ""))[:400])
    raw_changes = obj.get("changes")
    if not isinstance(raw_changes, list):
        prop.rejected.append("'changes' was not a list")
        return prop

    for entry in raw_changes[:32]:
        if not isinstance(entry, dict):
            prop.rejected.append(f"not an object: {entry!r:.60}")
            continue
        try:
            node = int(entry["node"])
            ctl = str(entry["ctl"])
            value = float(entry["value"])
        except (KeyError, TypeError, ValueError):
            prop.rejected.append(f"missing or malformed node/ctl/value: {entry!r:.60}")
            continue
        spec = index.get((node, ctl))
        if spec is None:
            prop.rejected.append(f"no control {ctl!r} on node {node} in the live tree")
            continue
        if spec.kind == "readonly":
            prop.rejected.append(f"{ctl!r} on node {node} is read-only")
            continue
        if not math.isfinite(value):
            prop.rejected.append(f"{ctl!r} on node {node}: value is not finite")
            continue
        clamped = min(spec.hi, max(spec.lo, value))
        why = str(entry.get("why", ""))[:200]
        if clamped != value:
            why = (why + f" [clamped from {value:g}]").strip()
        prop.changes.append(Change(node, ctl, clamped, why))
    return prop


def ask_for_patch(provider: Provider, nodes, request: str, timeout: float = 120.0) -> Proposal:
    """One round trip: describe the tree, ask, parse, validate."""
    user = f"Live effect nodes:\n\n{describe_tree(nodes)}\n\nRequest: {request.strip()}"
    raw = provider.ask(SYSTEM, user, timeout)
    prop = validate(extract_json(raw), nodes)
    prop.raw = raw[-4000:]
    return prop
