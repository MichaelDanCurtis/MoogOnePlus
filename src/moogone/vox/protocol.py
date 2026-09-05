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
    # Parameter learning, inbound. `begin` names what is about to be moved; `finish`
    # ends the pass and, if one parameter clearly won, records the name.
    "learn.begin": ("label",),
    "learn.finish": (),
    "learn.forget": ("param",),
    "learn.list": (),
    # The panel control catalogue, read from the instrument's own /p namespace.
    "controls.list": (),
    # Binding a spot on the panel photo to a parameter the instrument named.
    "hotspot.bind": ("spot", "param", "name"),
    "hotspot.forget": ("spot",),
    "hotspot.list": (),
    # Browsing the instrument's own preset library, from a copy.
    "library.open": ("path",),
    "library.list": (),
    "library.preset": ("name",),
    "library.diff": ("a", "b"),
    # The sampler: your own audio, in the instrument, played by its own keys.
    "sampler.list": (),
    "sampler.load": ("path", "name", "root"),
    # A file dropped onto the page, base64. Sent over the socket rather than by
    # path because the page also runs on an iPad, which has no paths to give.
    "sampler.upload": ("name", "data", "root"),
    "sampler.assign": ("note", "name"),
    "sampler.spread": ("name",),
    "sampler.live": ("on",),
    "sampler.mode": ("mode",),
    "sampler.stop": (),
    "patch.source": ("patch",),
    # Compile the graph and run it INSIDE the instrument. free takes it back out.
    "patch.run": ("patch",),
    "patch.free": (),
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
    "vector.state": (
        "x", "y", "mode", "corners", "paths", "spans", "duplicates", "orbit", "clock", "motion",
    ),
    "vector.pos": ("x", "y"),  # throttled position while the motion or orbit plays
    # A note the INSTRUMENT played, read off its performance port. Not something Vox
    # sent -- this is the synth reporting, so it covers its own keyboard too.
    "perf.note": ("note", "on", "velocity"),
    # One of the instrument's OLED screens, as a base64 PNG. Reconstructed from the
    # 64x16 tiles it sends its own panel; this is a mirror, not a rendering.
    "panel.frame": ("display", "png", "width", "height"),
    "panel.leds": ("name", "bytes"),
    # The instrument's MAIN display, read off its framebuffer over SSH. Separate
    # from panel.frame, which carries the small OLEDs off the panel bus.
    "panel.screen": ("png", "width", "height"),
    # Parameter learning. `learn.activity` is the live /x feed with names attached;
    # `learn.result` is what one pass concluded, including why it concluded nothing.
    "learn.activity": ("param", "name", "value"),
    "learn.result": ("param", "reason", "candidates", "label"),
    "learn.map": ("names",),
    "controls.all": ("controls",),
    "hotspot.map": ("spots",),
    "library.catalogue": ("library", "presets"),
    "library.detail": ("name", "summary", "count", "tags"),
    "library.difference": ("a", "b", "changed", "total"),
    "sampler.state": ("samples", "spread", "by_note", "live", "mode"),
    "sampler.hit": ("note", "sample", "velocity"),
    "ai.providers": ("providers",),
    "ai.proposal": ("reasoning", "changes", "rejected"),
    "ai.busy": ("busy",),
    "patch.ugens": ("ugens",),
    "patch.problems": ("problems",),
    "patch.scd": ("source", "problems"),
    "patch.running": ("running", "name", "problems"),
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
