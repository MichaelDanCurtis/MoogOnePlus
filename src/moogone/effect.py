"""The instrument's own effects, as something you can send its own sound through.

`moogone.ingress` puts audio from this machine through one of the instrument's
effects. This is the other half: routing what the instrument is *already making* --
the FM engine, the sampler -- through the same rack, so "run the FM engine through
the Moog's Eventide plate" is one action rather than a patch job.

**Private buses, so no patch of the user's is touched.** Every effect in Moog's
`synthdefs.scd` has the same shape, `In.ar(inBus, 2) -> LADSPA -> Out.ar(outBus)`
with both buses plain controls, so ours is pointed at buses nothing else uses.
scsynth runs with `-a 129`; the instrument works in 0-16 and 50-63, so everything
from 64 up is free.

**An effect must never be `/n_free`d.** It terminates scsynth -- measured directly,
and it took the audio engine down three times before it was isolated. Moog create
their effects once at boot and stop them with `enable = 0`, whose envelope is
`EnvGen.kr(Env.asr(0.1, 1, 2), enable, doneAction: 1)`, and doneAction 1 is
*pause*. That rule lives here, once, and `moogone.ingress` imports it rather than
keeping a second copy that could drift.

**Groups, not re-tailing.** Nodes execute in creation order, and both the FM engine
and the sampler add voices to the *tail* of the root group -- which would put every
new note after the effect, so the effect would process the previous block's silence
and the note would arrive dry. Sending `/g_tail` after every note would fix the
order and cost two datagrams per note on a machine where bursts are the one fatal
mistake. So the sources get a group at the head and the effect chain a group at the
tail, and the ordering is then structural and free.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: The effect nodes and the monitor. Clear of the sampler (1100+/91000+), the FM
#: engine (93000+) and the outbound stream (1050/94000).
#:
#: ONE NODE PER EFFECT, not one shared node. An effect can never be freed, so a
#: shared id could only ever hold the first effect engaged and switching would
#: mean restarting the audio engine -- which is not a feature, it is a defect with
#: a workaround. Giving each its own id means each is created at most once in the
#: engine's lifetime, parked when unused, and resumed when chosen again, which is
#: exactly what the never-free rule wants.
EFFECT_NODE_BASE = 96100
MONITOR_NODE = 95500


def node_for(effect: str) -> int:
    """The node id this effect always uses. Stable, so parking and resuming work."""
    if effect not in EFFECTS:
        raise EffectError(
            f"{effect!r} is not one of the instrument's effects; expected one of "
            f"{', '.join(EFFECTS)}"
        )
    return EFFECT_NODE_BASE + EFFECTS.index(effect)


#: Where sources play and where the effect chain lives. Creation order is execution
#: order, so the source group is made at the head and the effect group at the tail.
SOURCE_GROUP = 90100
EFFECT_GROUP = 90200

#: Private audio buses: the effect's input and its output.
IN_BUS = 100
FX_BUS = 102

#: The main outputs, from Moog's own `outputRouter`:
#:     Out.ar(7, main[0] * -1);
#:     Out.ar(0, main[1] * -1);   // good
#: Left is bus 7 and right is bus 0 -- the opposite way round from a tone sweep's
#: reading of which jack lit up -- and both are phase-inverted. The monitor inverts
#: to match, so what it adds has the same polarity as the instrument's own output
#: rather than partially cancelling it.
MAIN_LEFT = 7
MAIN_RIGHT = 0

MONITOR_DEF = "voxEffectMonitor"
MONITOR_GRAPH = (
    "|in = 102, gain = 0.6| "
    "var sig = In.ar(in, 2) * gain; "
    "Out.ar(7, sig[0] * -1); "
    "Out.ar(0, sig[1] * -1)"
)

#: The instrument's own effects, read off /usr/share/las-fx/synthdefs/. The
#: numbered variants are per-slot copies of one definition; `_1` is the instance
#: this project instantiates.
EFFECTS = (
    "et_blackhole_1",
    "et_hall_1",
    "et_plate_1",
    "et_room_1",
    "et_shimmer_1",
    "bbdDelay_1",
    "bitcrusher_1",
    "chorus_1",
    "delay_1",
    "dualChorus_1",
    "echo_1",
    "ensemble_1",
    "flanger_1",
    "phaser6stage_1",
    "phaser12stage_1",
    "pingpongDelay_1",
    "resonator_1",
    "stereoChorus_1",
    "stereoDelay_1",
    "stereoFlanger_1",
    "tapeDelay_1",
    "timePhaser_1",
    "vocoder10_1",
    "vocoder16_1",
    "vocoder21_1",
)


class EffectError(RuntimeError):
    """An effect that cannot be engaged as asked, and why."""


def parked_effect(client, node: int) -> str | None:
    """The name of the effect already sitting at `node`, if there is one.

    Asked with `/g_queryTree` because `/n_query` is not implemented on this
    firmware and answers nothing, and because a speculative `/s_new` on a taken id
    replies with an unsolicited `/fail` -- which, per the `/n_free` lesson in
    `moogone.sc.client`, gets blamed on whatever request comes next.
    """
    for entry in client.query_tree(0, with_controls=False).walk():
        if entry.node_id == node:
            return getattr(entry, "defname", None)
    return None


def effect_controls(client, node: int) -> set[str]:
    """The control names the engaged effect actually has.

    Needed because the rack is not uniform: a plate has `size` and `decay`, a delay
    has neither. `/n_set` on a control a synth does not have answers with an
    unsolicited `/fail`, and an unsolicited `/fail` is blamed on the next request --
    which is how a preset recall would surface as an unrelated command failing.
    """
    for entry in client.query_tree(0).walk():
        if entry.node_id == node:
            return {str(k) for k in getattr(entry, "controls", {})}
    return set()


def stop_effect(client, node: int) -> None:
    """Park an effect without freeing it. See the module docstring: freeing kills.

    `enable = 0` releases the envelope, whose doneAction pauses the synth. It is
    also pointed away from the shared buses, so that a tail still ringing out on
    its way to paused cannot be heard through a send that has moved on.
    """
    client.send("/n_set", node, "enable", 0)
    client.send("/n_set", node, "inBus", 0, "outBus", 0)


def start_effect(client, effect: str, target: int = EFFECT_GROUP, add_action: int = 1) -> int:
    """Create the effect, or resume the one already parked at its id.

    Returns the node it lives at. An effect is never freed, so re-engaging finds
    the previous instance paused where it was left. Resuming is `/n_run 1` to make
    it execute again and `enable = 1` to retrigger the envelope that `enable = 0`
    released -- setting the control alone does nothing, because a paused synth is
    not running to see it.
    """
    node = node_for(effect)
    parked = parked_effect(client, node)
    if parked == effect:
        client.send("/n_run", node, 1)
        client.send("/n_set", node, "enable", 1)
        client.send("/n_set", node, "inBus", IN_BUS, "outBus", FX_BUS)
        client.send("/n_order", add_action, target, node)
        return node
    if parked is not None:
        # Someone else's synth at an id we reserved. Not ours to free, so say so
        # rather than doing something clever.
        raise EffectError(
            f"node {node} already holds {parked!r}, which cannot be freed without "
            f"terminating scsynth. Restart the audio engine to use {effect!r}."
        )
    client.send("/s_new", effect, node, add_action, target, "inBus", IN_BUS, "outBus", FX_BUS)
    return node


@dataclass(frozen=True)
class EffectPreset:
    """One effect and a setting for it, named for what it sounds like.

    `controls` is filtered against the controls the chosen effect actually has
    before anything is sent. The rack is not uniform -- a plate has `size` and
    `decay`, a delay has neither -- and `/n_set` on a control a synth does not have
    draws an unsolicited `/fail` that lands on the NEXT request.
    """

    name: str
    effect: str
    controls: dict[str, float] = field(default_factory=dict)
    level: float = 0.6
    description: str = ""


#: Chosen so each one demonstrates a different part of the rack rather than the
#: same reverb at five sizes. The values are deliberately short of the extremes:
#: et_plate_1 at size 0.9 with decay 0.85 is a self-sustaining wash rather than a
#: plate -- recorded off the analog outs it read a crest factor of 2.1, a saturated
#: drone rather than plucked notes, and it clipped an interface at six times less
#: send level.
PRESETS: tuple[EffectPreset, ...] = (
    EffectPreset(
        "Plate",
        "et_plate_1",
        {"size": 0.55, "decay": 0.4, "mix": 0.5, "diffusion": 0.6},
        0.6,
        "The Eventide plate, close and bright. The default for hearing what an effect does.",
    ),
    EffectPreset(
        "Cathedral",
        "et_hall_1",
        {"size": 0.8, "decay": 0.7, "mix": 0.6, "highDecay": 0.4},
        0.5,
        "A long hall. Notes stop belonging to the note that made them.",
    ),
    EffectPreset(
        "Shimmer",
        "et_shimmer_1",
        {"size": 0.6, "decay": 0.5, "mix": 0.5, "aPitch": 0.75, "bPitch": 0.5},
        0.45,
        "Pitch-shifted reverb. Two operators and this is most of an ambient record.",
    ),
    EffectPreset(
        "Blackhole",
        "et_blackhole_1",
        {"size": 0.7, "mix": 0.6, "feedback": 0.5, "invGravity": 0.4},
        0.45,
        "Eventide's signature. Inverted gravity, so the tail swells instead of decaying.",
    ),
    EffectPreset(
        "Small Room",
        "et_room_1",
        {"size": 0.25, "decay": 0.2, "mix": 0.35, "reflection": 0.5},
        0.7,
        "Tight and early. Puts a voice in a space without making it a texture.",
    ),
    EffectPreset(
        "Tape Echo",
        "tapeDelay_1",
        {"mix": 0.4, "feedback": 0.35},
        0.65,
        "The delay line, not a reverb -- so the effect arrives as repeats you can count.",
    ),
    EffectPreset(
        "Ensemble",
        "stereoChorus_1",
        {"mix": 0.5},
        0.7,
        "Chorus, for width rather than space. Try it on the FM presets that beat.",
    ),
)


def preset(name: str) -> EffectPreset:
    for p in PRESETS:
        if p.name.lower() == name.lower():
            return p
    raise EffectError(f"no preset named {name!r}; have {', '.join(p.name for p in PRESETS)}")


class EffectSend:
    """One of the instrument's effects, with the instrument's own sound going in.

    Sources are *attached*: their output buses are pointed at this send's input and
    their voices are made in the source group, which runs before the effect group.
    Detaching puts them back on the main outputs. Nothing else on the instrument is
    touched at any point.
    """

    def __init__(self, client) -> None:
        self.client = client
        self.engaged = False
        self.effect = ""
        #: The node the currently engaged effect lives at, so switching can park
        #: the old one instead of trying to free it.
        self.node = 0
        self.preset_name = ""
        self.level = 0.6
        self.controls: dict[str, float] = {}
        self.available: set[str] = set()
        self._attached: list = []
        self._groups = False
        self._monitor_loaded = False

    # -- wiring ---------------------------------------------------------------

    def ensure_groups(self) -> None:
        """Sources before the effect, permanently.

        `/g_new <id> <addAction> <target>`: the source group at the head of the root
        group and the effect group at its tail. Made once; a group that already
        exists draws a `/fail`, so this does not send them twice.
        """
        if self._groups:
            return
        self.client.send("/g_new", SOURCE_GROUP, 0, 0)
        self.client.send("/g_new", EFFECT_GROUP, 1, 0)
        self._groups = True

    def attach(self, source) -> None:
        """Point a source's output at this send and put its voices in order.

        Works on anything with `left`, `right` and `group` -- the FM engine and the
        sampler both qualify. The group is the half that is easy to forget: routing
        the audio without moving the voices leaves every new note landing after the
        effect, where it is heard dry and nothing reports a problem.
        """
        source.left, source.right = IN_BUS, IN_BUS + 1
        source.group = SOURCE_GROUP
        if source not in self._attached:
            self._attached.append(source)

    def detach(self, source) -> None:
        source.left, source.right = MAIN_LEFT, MAIN_RIGHT
        source.group = 0
        if source in self._attached:
            self._attached.remove(source)

    # -- the effect -----------------------------------------------------------

    def engage(self, effect: str) -> None:
        from .synthdef import compile_synthdef

        self.ensure_groups()
        if not self._monitor_loaded:
            self.client.d_recv(compile_synthdef(MONITOR_DEF, MONITOR_GRAPH))
            self._monitor_loaded = True
        if self.engaged and self.effect != effect:
            # Park the outgoing one. It cannot be freed, and leaving it running on
            # the shared bus would sum two effects into the same output.
            stop_effect(self.client, self.node)
        self.node = start_effect(self.client, effect, target=EFFECT_GROUP)
        # The monitor is made AFTER the effect and in the same group, so it runs
        # after it and carries this block's output rather than the last one's.
        self.client.send("/n_free", MONITOR_NODE)
        self.client.send(
            "/s_new",
            MONITOR_DEF,
            MONITOR_NODE,
            1,
            EFFECT_GROUP,
            "in",
            FX_BUS,
            "gain",
            self.level,
        )
        self.client.sync(timeout=8.0)
        self.effect = effect
        self.engaged = True
        self.available = effect_controls(self.client, self.node)
        for source in self._attached:
            self.attach(source)

    def disengage(self) -> None:
        """Give the sound back to the main outputs.

        The monitor is ours and made of plain ugens, so freeing it is safe. The
        EFFECT is not -- see the module docstring -- so it is stopped and parked.
        """
        for source in list(self._attached):
            self.detach(source)
        self.client.send("/n_free", MONITOR_NODE)
        if self.engaged:
            stop_effect(self.client, self.node)
        self.engaged = False
        self.preset_name = ""

    def configure(self, **controls) -> None:
        """Set controls on the engaged effect, skipping any it does not have.

        Editing by hand clears the preset name, for the reason `FMEngine.configure`
        does the same: a label on the instrument's screen that no longer describes
        the sound is worse than no label.
        """
        if not self.engaged:
            raise EffectError("no effect engaged")
        if controls and not controls.pop("_from_recall", False):
            self.preset_name = ""
        args: list = []
        for key, value in controls.items():
            if key == "level":
                self.set_level(float(value))
                continue
            if self.available and key not in self.available:
                continue
            self.controls[key] = float(value)
            args += [key, float(value)]
        if args:
            self.client.send("/n_set", self.node, *args)

    def set_level(self, level: float) -> None:
        self.level = max(0.0, min(1.0, float(level)))
        self.client.send("/n_set", MONITOR_NODE, "gain", self.level)

    def recall(self, name: str) -> EffectPreset:
        chosen = preset(name)
        if not self.engaged or self.effect != chosen.effect:
            self.engage(chosen.effect)
        self.controls = {}
        self.configure(**chosen.controls, _from_recall=True)
        self.set_level(chosen.level)
        self.preset_name = chosen.name
        return chosen

    def as_dict(self) -> dict:
        return {
            "engaged": self.engaged,
            "effect": self.effect,
            "preset": self.preset_name,
            "level": round(self.level, 3),
            "controls": {k: round(v, 3) for k, v in sorted(self.controls.items())},
            "available": sorted(self.available),
            "node": self.node,
            "in_bus": IN_BUS,
            "out_bus": FX_BUS,
            "sources": len(self._attached),
            "presets": [
                {"name": p.name, "effect": p.effect, "description": p.description} for p in PRESETS
            ],
        }
