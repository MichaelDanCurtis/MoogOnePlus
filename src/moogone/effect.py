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

#: The monitor is a SEND RETURN, and it has to be, because the instrument's
#: effects output **wet only**. Moog's own et_plate reads:
#:
#:     mix = 1;                                    // the control is overwritten
#:     sig = LADSPA.ar(2, 29154, ..., mix, input[0], input[1]);
#:     Out.ar(outBus, ((sig * g_out * ...gain... ).softclip) * env);
#:
#: The `dry` and `wet` arguments are declared and never used, and `mix` is forced
#: to 1 before the plugin call -- so setting it does nothing. In Moog's design
#: that is correct: `outputRouter` mixes the dry path back in downstream. A send
#: that routes sources *into* an effect has no such path, and what comes out is
#: reverb tails with no note attacks at all. It sounds exactly as bad as that
#: description suggests, and it is why this reads both buses.
MONITOR_GRAPH = (
    "|dry_in = 100, wet_in = 102, mix = 0.35, gain = 0.6| "
    "var d = In.ar(dry_in, 2); "
    "var w = In.ar(wet_in, 2); "
    "var sig = ((d * (1 - mix)) + (w * mix)) * gain; "
    "Out.ar(7, sig[0] * -1); "
    "Out.ar(0, sig[1] * -1)"
)

#: `gain` on the et_ effects is not a linear multiplier: the synthdef maps it
#: through `ControlSpec(0.01, 2.25, \exp)`, so the DEFAULT of 1.0 is the top of
#: that range -- 2.25x into a `.softclip`. Unity is 0.85, from
#: 0.01 * (2.25/0.01)**x == 1. Left alone, every effect distorts.
UNITY_GAIN = 0.85

#: The sixth Eventide reverb, which the instrument ships and cannot use.
#:
#: Three faults kept it unreachable, and all three are ours to work around:
#:
#: 1. `init_sc_1.scd` sets `LADSPA_PATH` with `("export ...").systemCmd` -- a
#:    subshell, so it never reaches scsynth, which falls back to `/usr/lib/ladspa`
#:    where five of the six plugins were evidently copied by hand.
#: 2. `et_spring` has SynthDef source but was never compiled to a `.scsyndef`, so
#:    `loadDirectory` never sees it.
#: 3. **And that source would not have worked anyway.** It passes the PLATE's
#:    argument list -- distance, diffusion, tone, preDelay, size -- into a plugin
#:    whose ports are TREM-INTENSITY, TREM-RATE, RESONANCE, NUM SPRINGS and
#:    TENSION. The count matches, so it maps positionally and compiles; every knob
#:    is simply the wrong knob, and `preDelay`'s default of 0.1 lands on NUM
#:    SPRINGS. Instantiated as written it produced silence, measured.
#:
#: The port order below is `ladspalist`'s, read off the plugin itself.
SPRING_DEF = "voxSpring"
SPRING_GRAPH = (
    "|inBus = 100, outBus = 102, enable = 1, g_out = 1, "
    "tremIntensity = 0.2, tremRate = 0.3, modLevel = 0.2, resonance = 0.6, "
    "highDamp = 0.4, lowDamp = 0.3, numSprings = 0.8, tension = 0.5, "
    "decay = 0.6, mix = 1| "
    "var env = EnvGen.kr(Env.asr(0.1, 1, 2), enable, doneAction: 1); "
    "var input = In.ar(inBus, 2); "
    "var sig = LADSPA.ar(2, 29153, tremIntensity, tremRate, modLevel, resonance, "
    "highDamp, lowDamp, numSprings, tension, decay, mix, input[0], input[1]); "
    "Out.ar(outBus, sig * env * g_out)"
)

#: The plugin must be visible to scsynth before any of this works. Copy it into
#: the directory scsynth actually reads and restart the audio engine:
#:
#:     cp /usr/share/las-fx/ladspa/eventide_spring.so /usr/lib/ladspa/
#:     /etc/init.d/S42sc restart
#:
#: Confirmed by scsynth's own boot line: `LADSPA: Found plugin 29153 (Eventide
#: Spring)`.
SPRING_PLUGIN_ID = 29153


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
    # Ours, and only present once ensure_spring() has sent it. Listed so it can be
    # engaged and so it gets a stable node of its own.
    SPRING_DEF,
)


#: What each effect costs, as a fraction of ONE core, measured on hardware by
#: `recon/effect-cpu.py`: engage it, read the busiest scsynth thread's jiffies
#: against the kernel's own jiffy total, difference it against a baseline taken
#: either side.
#:
#: MEASURE THIS ON AN IDLE INSTRUMENT OR THE NUMBERS ARE NONSENSE. Taken with a
#: patch loaded -- an 82% baseline -- every reverb came back at 12-15%, about half
#: its real cost, and consistently enough across all five to look like a result. It
#: was the throttle: 82% plus a real reverb is past 95%, the kernel deschedules the
#: thread, and the measurement records the ceiling rather than the work. An effect's
#: cost can only be measured where there is room for it. On an idle engine (12-13%
#: baseline, 519 ugens) the same five come back at 23-33%.
#:
#: The split is not subtle and it decides whether a send is usable. The Eventide
#: plugins are LADSPA and cost 23-33% each; everything native is 1-10%. The 21-band
#: vocoder at 10% is the one native effect worth watching, and the corrected spring
#: is the dearest thing in the rack -- 33%, level with the shimmer.
#:
#: This matters because `scsynth` runs `SCHED_FIFO` and Linux throttles realtime
#: tasks above `sched_rt_runtime_us / sched_rt_period_us`, 95% here. Past that the
#: kernel forcibly deschedules it, heard as the sound cutting out for about a tenth
#: of a second. The instrument idles at 12% and a loaded patch has been measured at
#: 82%, so whether a reverb fits is a question about the patch, not about the
#: reverb -- which is why the panel measures rather than assumes. See
#: `EffectSend.set_load` and `moogone.load`.
#:
#: CAVEAT (2026-09-08): these were measured while this project had the server at
#: `-z 256`, not at the stock `-z 128` -- the same contamination that made
#: `captures/arch-harvest/runtime-state.txt` read `-z 256`. Per-block cost is
#: roughly half of the total at this graph size, so against a stock instrument
#: these figures are expected to under-read by something like 5-10% relative.
#: They are not re-measurable without the instrument, and the instrument is
#: deliberately back at stock, so they stand as recorded with this warning
#: attached. Treat them as a floor, not a number. See
#: `docs/CORRECTIONS-2026-09-08.md` section 2.
CPU_COST: dict[str, float] = {
    SPRING_DEF: 0.33,
    "et_shimmer_1": 0.33,
    "et_hall_1": 0.28,
    "et_plate_1": 0.26,
    "et_blackhole_1": 0.25,
    "et_room_1": 0.23,
    "vocoder21_1": 0.10,
    "vocoder16_1": 0.09,
    "echo_1": 0.08,
    "vocoder10_1": 0.07,
    "dualChorus_1": 0.05,
    "timePhaser_1": 0.05,
    "phaser12stage_1": 0.04,
    "ensemble_1": 0.04,
    "stereoFlanger_1": 0.04,
    "stereoChorus_1": 0.04,
    "bbdDelay_1": 0.04,
    "phaser6stage_1": 0.04,
    #: Not measured in the idle sweep -- its /g_queryTree.reply did not arrive -- so
    #: this keeps the earlier figure rather than inventing one.
    "pingpongDelay_1": 0.04,
    "stereoDelay_1": 0.03,
    "flanger_1": 0.03,
    "tapeDelay_1": 0.03,
    #: Measured at -0.7 points, which is the noise floor of this method, not a free
    #: effect. Costed with its neighbours.
    "resonator_1": 0.04,
    "chorus_1": 0.02,
    "delay_1": 0.02,
    "bitcrusher_1": 0.01,
}

#: Where the kernel starts descheduling scsynth. `sched_rt_runtime_us` is 950000
#: against a `sched_rt_period_us` of 1000000 on this firmware.
THROTTLE_CEILING = 0.95

#: What the instrument's own graph costs before anything is added, used only until
#: something measures the real one -- and it is a poor stand-in, because the figure
#: is a property of the patch and nothing else. Measured at 72% on a normal patch;
#: at 82% on a 752-ugen graph; at 12% on an engine with no patch loaded at all. The
#: panel uses the live figure. See `EffectSend.set_load` and `moogone.load`.
TYPICAL_PATCH_LOAD = 0.72


def cpu_cost(effect: str) -> float:
    """What this effect costs, or the family's typical figure if unmeasured."""
    if effect in CPU_COST:
        return CPU_COST[effect]
    return 0.27 if effect.startswith("et_") else 0.04


def fits(effect: str, patch_load: float = TYPICAL_PATCH_LOAD) -> bool:
    """Whether engaging this leaves scsynth below the throttle."""
    return patch_load + cpu_cost(effect) < THROTTLE_CEILING


class EffectError(RuntimeError):
    """An effect that cannot be engaged as asked, and why."""


def inspect_node(client, node: int) -> tuple[str | None, dict[str, float]]:
    """What is at `node`: its defname, and the controls it currently holds.

    ONE query, deliberately. This was two -- `/g_queryTree` without controls to
    learn the name, then again with controls to read the values -- and back to back
    they COLLIDE. Both replies carry the address `/g_queryTree.reply`, and
    `ScClient` matches a reply by address, so the second call can be handed the
    first call's answer. It surfaces as an error saying the reply's control-values
    flag is not the one that was asked for, raised by a call that did nothing
    wrong. Asking once removes the window rather than papering over it.

    `/n_query` would be the obvious way to ask about a single node, and is not
    implemented on this firmware -- it answers nothing.

    The VALUES matter as much as the names. Without them an interface can only show
    what this process happened to set, and every other control reads as whatever
    its slider defaulted to: a panel confidently displaying a number the instrument
    does not hold. The names matter because the rack is not uniform -- a plate has
    `size` and `decay`, a delay has neither -- and `/n_set` on a control a synth
    does not have answers with an unsolicited `/fail`, which then gets blamed on
    the next request.
    """
    for entry in client.query_tree(0).walk():
        if entry.node_id == node:
            live: dict[str, float] = {}
            for key, value in getattr(entry, "controls", {}).items():
                try:
                    live[str(key)] = float(value)
                except (TypeError, ValueError):
                    continue
            return getattr(entry, "defname", None), live
    return None, {}


def parked_effect(client, node: int) -> str | None:
    """The name of the effect already sitting at `node`, if there is one."""
    return inspect_node(client, node)[0]


def effect_controls(client, node: int) -> dict[str, float]:
    """The controls the effect at `node` has, and what it currently holds."""
    return inspect_node(client, node)[1]


def stop_effect(client, node: int) -> None:
    """Park an effect without freeing it. See the module docstring: freeing kills.

    `enable = 0` releases the envelope. What that envelope then does is **not the
    same across the rack**, and both behaviours are fine:

        et_plate, et_hall, et_room, et_shimmer, et_blackhole   doneAction: 1  pause
        chorus, stereoChorus, delay, stereoDelay, tapeDelay,
        flanger, phaser, bitcrusher ...                        doneAction: 2  FREE

    The Eventide ones are the LADSPA plugins, and pausing is what keeps `/n_free`
    away from them. The rest are native SuperCollider and free themselves, which is
    harmless -- re-engaging simply builds a new one.

    THIS SENDS NOTHING ELSE, and that is the point. It used to follow up with
    `/n_set node inBus 0 outBus 0` to stop a departing tail bleeding into the send.
    On a doneAction-2 effect the node is already gone by then, so the write drew an
    unsolicited `/fail` -- and an unsolicited `/fail` is blamed on the NEXT request.
    It presented as every effect after the first chorus failing to engage with
    "Node 96117 not found", naming a node that had nothing to do with the request
    that failed.
    """
    client.send("/n_set", node, "enable", 0)


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
    #: How much of the return is the effect. The effects themselves are wet-only,
    #: so this is the only wet/dry there is.
    mix: float = 0.35
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
        0.3,
        "The Eventide plate, close and bright. The default for hearing what an effect does.",
    ),
    EffectPreset(
        "Cathedral",
        "et_hall_1",
        {"size": 0.8, "decay": 0.7, "mix": 0.6, "highDecay": 0.4},
        0.5,
        0.42,
        "A long hall. Notes stop belonging to the note that made them.",
    ),
    EffectPreset(
        "Shimmer",
        "et_shimmer_1",
        {"size": 0.6, "decay": 0.5, "mix": 0.5, "aPitch": 0.75, "bPitch": 0.5},
        0.45,
        0.38,
        "Pitch-shifted reverb. Two operators and this is most of an ambient record.",
    ),
    EffectPreset(
        "Blackhole",
        "et_blackhole_1",
        {"size": 0.7, "mix": 0.6, "feedback": 0.5, "invGravity": 0.4},
        0.45,
        0.4,
        "Eventide's signature. Inverted gravity, so the tail swells instead of decaying.",
    ),
    EffectPreset(
        "Small Room",
        "et_room_1",
        {"size": 0.25, "decay": 0.2, "mix": 0.35, "reflection": 0.5},
        0.7,
        0.22,
        "Tight and early. Puts a voice in a space without making it a texture.",
    ),
    EffectPreset(
        "Tape Echo",
        "tapeDelay_1",
        {"mix": 0.4, "feedback": 0.35},
        0.65,
        0.32,
        "The delay line, not a reverb -- so the effect arrives as repeats you can count.",
    ),
    EffectPreset(
        "Spring",
        SPRING_DEF,
        {"numSprings": 0.8, "tension": 0.5, "decay": 0.6, "resonance": 0.6},
        0.75,
        0.42,
        "The sixth Eventide -- shipped with the instrument and unreachable on it "
        "until now. Short, boingy, and unmistakably a spring.",
    ),
    EffectPreset(
        "Ensemble",
        "stereoChorus_1",
        {"mix": 0.5},
        0.7,
        0.5,
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
        #: The send's wet/dry. The effects are wet-only, so this is the only one.
        self.mix = 0.35
        self.controls: dict[str, float] = {}
        self.available: set[str] = set()
        self._attached: list = []
        self._groups = False
        self._monitor_loaded = False
        self._spring_loaded = False
        #: The instrument's own CPU load, refreshed from the server whenever nothing
        #: of ours is running. Seeded with the shipped figure so the first state
        #: request has something honest to say before the first measurement lands.
        self._patch_load = TYPICAL_PATCH_LOAD

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

    def ensure_spring(self) -> None:
        """Compile and send the corrected spring definition, once.

        Needs `LadspaUGen.sc` on the compiling machine so `sclang` knows the
        `LADSPA` class -- the UGen's own class file, which only has to exist to
        COMPILE a definition; resolving it is the server's job. See SPRING_GRAPH
        for why the instrument's own version does not work.
        """
        from .synthdef import compile_synthdef

        if self._spring_loaded:
            return
        self.client.d_recv(compile_synthdef(SPRING_DEF, SPRING_GRAPH), timeout=20.0)
        self._spring_loaded = True

    def set_load(self, load: float | None) -> None:
        """Record a measured baseline: the busiest scsynth thread's share of a core.

        The headroom warning was built on a constant measured at the shipped block
        size of 128, and the instrument now runs at 256. A wrong constant here is not
        cosmetic -- it is the panel refusing a reverb that fits, or promising one
        that does not.

        The figure cannot come from the server: this scsynth's `/status.reply` puts
        both CPU fields at exactly 0.000 while a thread of its own is doing 82% of a
        core. `moogone.load` measures it on the instrument's kernel instead, off this
        thread, because an SSH round trip on the request path is how the HUD once
        froze the panel for ten seconds.

        `None` means the instrument could not be asked, and leaves the last figure
        alone -- unlike 0.0, which would be a measurement saying "idle" and is
        precisely the lie the dead counters tell.

        Ignored while an effect of ours is engaged: its cost is inside the same
        measurement, and a baseline that already contains the effect would report
        headroom for a second one that is not there.
        """
        if load is None or self.engaged:
            return
        self._patch_load = load

    def ensure_monitor(self) -> None:
        """Compile and send the monitor synthdef, once.

        Separate from `engage` so it can be warmed off the request path: compiling
        shells out to sclang and takes about ten seconds.
        """
        from .synthdef import compile_synthdef

        if self._monitor_loaded:
            return
        self.client.d_recv(compile_synthdef(MONITOR_DEF, MONITOR_GRAPH))
        self._monitor_loaded = True

    def engage(self, effect: str) -> None:
        self.ensure_groups()
        self.ensure_monitor()
        if effect == SPRING_DEF:
            self.ensure_spring()
        if self.engaged and self.node and self.effect != effect:
            # Park the outgoing one: leaving it running on the shared bus would sum
            # two effects into the same output.
            stop_effect(self.client, self.node)
            # And forget it, so it is never stopped twice. Half the rack frees
            # itself on release (doneAction 2), so a second `enable = 0` lands on a
            # node that is gone -- an unsolicited /fail, blamed on the next request.
            self.node = 0
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
            "dry_in",
            IN_BUS,
            "wet_in",
            FX_BUS,
            "mix",
            self.mix,
            "gain",
            self.level,
        )
        self.client.sync(timeout=8.0)
        self.effect = effect
        self.engaged = True
        # Seeded from the instrument, so the interface opens showing what the
        # effect actually holds rather than what a slider defaulted to.
        _, live = inspect_node(self.client, self.node)
        self.available = set(live)
        self.controls = live
        # Unity, not the default. See UNITY_GAIN: the synthdef maps `gain` through
        # an exponential spec whose top is 2.25, the default of 1.0 sits AT that
        # top, and the result goes through a softclip. Every effect arrives
        # distorting until this is set.
        if "gain" in self.available:
            self.configure(gain=UNITY_GAIN, _from_recall=True)
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
        if self.engaged and self.node:
            stop_effect(self.client, self.node)
            self.node = 0
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
            if key == "mix" and "mix" not in self.available:
                # The send's own wet/dry when the effect has no usable mix of its
                # own -- which is all of the et_ family, since they overwrite it.
                self.set_mix(float(value))
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

    def set_mix(self, mix: float) -> None:
        """How much of the return is effect rather than source.

        Not the effect's own `mix` control, which these synthdefs overwrite and
        ignore. This one is real.
        """
        self.mix = max(0.0, min(1.0, float(mix)))
        self.client.send("/n_set", MONITOR_NODE, "mix", self.mix)

    def recall(self, name: str) -> EffectPreset:
        chosen = preset(name)
        if not self.engaged or self.effect != chosen.effect:
            self.engage(chosen.effect)
        self.configure(**chosen.controls, _from_recall=True)
        self.set_mix(chosen.mix)
        self.set_level(chosen.level)
        self.preset_name = chosen.name
        return chosen

    def as_dict(self) -> dict:
        load = self._patch_load
        return {
            "engaged": self.engaged,
            "effect": self.effect,
            "preset": self.preset_name,
            "level": round(self.level, 3),
            "mix": round(self.mix, 3),
            "controls": {k: round(v, 3) for k, v in sorted(self.controls.items())},
            "available": sorted(self.available),
            "node": self.node,
            "in_bus": IN_BUS,
            "out_bus": FX_BUS,
            "sources": len(self._attached),
            "effects": [
                {"name": name, "cpu": cpu_cost(name), "fits": fits(name, load)} for name in EFFECTS
            ],
            "throttle": THROTTLE_CEILING,
            "patch_load": round(load, 3),
            "presets": [
                {"name": p.name, "effect": p.effect, "description": p.description} for p in PRESETS
            ],
        }
