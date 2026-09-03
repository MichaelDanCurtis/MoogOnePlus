"""The JSON messages that cross the WebSocket between bridge and UI.

Every message is one JSON object with a ``type``. ``REQUIRED`` lists the keys each type
must carry; a message missing one is rejected here rather than becoming a half-formed
command downstream. The UI is a browser on an iPad — it will send whatever it sends, and
the bridge is the last place a malformed request can be refused cleanly.

Badges are part of the protocol on purpose. Every control the UI shows carries one, and
``live`` is assigned only to what this session verified on hardware. A badge that says
``untested`` or ``blocked`` must say *why* — that reason is what the UI displays, and an
empty one would be the exact failure this project keeps writing down.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

BADGE_STATES = ("live", "untested", "blocked")


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class Badge:
    """What this session actually verified about a control. See the spec's Decisions table."""

    state: str
    why: str = ""

    def __post_init__(self) -> None:
        if self.state not in BADGE_STATES:
            raise ValueError(
                f"badge state must be one of live, untested, blocked; got {self.state!r}"
            )
        if self.state != "live" and not self.why.strip():
            raise ValueError(f"a {self.state!r} badge must say why")

    def as_dict(self) -> dict:
        return {"state": self.state, "why": self.why}


LIVE = Badge("live", "")


def UNTESTED(why: str) -> Badge:
    return Badge("untested", why)


def BLOCKED(why: str) -> Badge:
    return Badge("blocked", why)


#: Required keys per message type, both directions. Anything else is rejected.
REQUIRED: dict[str, tuple[str, ...]] = {
    # UI -> bridge
    "fx.list": (),
    "fx.set": ("node", "ctl", "value"),
    "route.add": ("src", "dst"),
    "route.remove": ("id",),
    "route.list": (),
    "mpe.config": ("zone",),
    "midi.note": ("note", "on"),
    "ping": (),
    # vector synthesis
    "vector.corner": ("name", "action"),  # action: "store" | "clear"
    "vector.move": ("x", "y"),
    "vector.orbit": (),  # any of rate_x/rate_y/phase_x/phase_y/depth/running
    "vector.surface": ("path",),  # request; the reply adds "grid"
    "vector.mode": ("mode",),  # manual | orbit | motion
    "vector.record": ("action",),  # start | stop
    "vector.clock": (),  # mode/period/bpm/beats/retrigger/loop
    # patcher
    "patch.catalog": (),
    "patch.validate": ("patch",),
    "patch.source": ("patch",),
    # AskAI
    "ai.list": (),
    "ai.ask": ("provider", "request"),
    "ai.apply": ("changes",),
    # bridge -> UI
    "fx.tree": ("nodes",),
    "fx.value": ("node", "ctl", "value", "state"),
    "meters": ("values",),
    "mpe.event": ("kind", "voice", "note", "value"),
    "routes": ("routes",),
    "badge": ("path", "state", "why"),
    "status": ("sc", "midi_in", "midi_out", "meters"),
    "error": ("where", "what"),
    "pong": (),
    "vector.state": ("x", "y", "mode", "corners", "paths", "orbit", "clock", "motion"),
    "vector.pos": ("x", "y"),  # throttled position while the motion or orbit plays
    "ai.providers": ("providers",),
    "ai.proposal": ("reasoning", "changes", "rejected"),
    "ai.busy": ("busy",),
    "patch.ugens": ("ugens",),
    "patch.problems": ("problems",),
    "patch.scd": ("source", "problems"),
}


def encode(msg: dict) -> str:
    if "type" not in msg:
        raise ProtocolError("message has no type")
    if msg["type"] not in REQUIRED:
        raise ProtocolError(f"unknown message type {msg['type']!r}")
    _check_finite(msg)
    return json.dumps(msg, separators=(",", ":"))


def decode(text: str) -> dict:
    try:
        obj = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"not JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise ProtocolError("message must be a JSON object")
    kind = obj.get("type")
    if not isinstance(kind, str):
        raise ProtocolError("message has no string 'type'")
    if kind not in REQUIRED:
        raise ProtocolError(f"unknown message type {kind!r}")
    missing = [k for k in REQUIRED[kind] if k not in obj]
    if missing:
        raise ProtocolError(f"{kind} is missing required field(s): {', '.join(missing)}")
    return obj


def _check_finite(obj) -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ProtocolError("numbers must be finite; NaN/Infinity are not valid JSON")
    if isinstance(obj, dict):
        for v in obj.values():
            _check_finite(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _check_finite(v)
