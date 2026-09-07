"""Tests for sending the instrument's own sound through its own effects.

Three of these guard rules that cost real damage to learn: an effect is stopped
and never freed, because freeing one terminates scsynth; sources are moved into a
group that runs BEFORE the effect, because a voice made after it is heard dry with
nothing reporting a problem; and a control the chosen effect does not have is
skipped rather than sent, because an unsolicited /fail lands on the next request.
"""

from __future__ import annotations

import pytest

from moogone import effect as effect_mod
from moogone.effect import (
    EFFECT_GROUP,
    FX_BUS,
    IN_BUS,
    MAIN_LEFT,
    MAIN_RIGHT,
    MONITOR_NODE,
    PRESETS,
    SOURCE_GROUP,
    EffectError,
    EffectSend,
    node_for,
    preset,
)

PLATE = node_for("et_plate_1")


class FakeNode:
    def __init__(self, node_id, defname, controls=None):
        self.node_id = node_id
        self.defname = defname
        self.controls = controls or {}


class FakeTree:
    def __init__(self, nodes):
        self._nodes = nodes

    def walk(self):
        return list(self._nodes)


class FakeClient:
    def __init__(self, parked=None, controls=None):
        self.sent: list[tuple] = []
        self.parked = parked
        self.controls = controls or {}
        self.defs = 0

    def send(self, *args):
        self.sent.append(args)

    def sync(self, *a, **k):
        pass

    def d_recv(self, blob, timeout=None):
        self.defs += 1

    def query_tree(self, group=0, **k):
        if self.parked is None:
            return FakeTree([])
        node = getattr(self, "parked_node", None) or node_for(self.parked)
        return FakeTree([FakeNode(node, self.parked, self.controls)])

    def of(self, address):
        return [m for m in self.sent if m and m[0] == address]


class FakeSource:
    """Anything with left, right and group -- the FM engine and the sampler both."""

    def __init__(self):
        self.left, self.right, self.group = MAIN_LEFT, MAIN_RIGHT, 0


@pytest.fixture
def no_sclang(monkeypatch):
    monkeypatch.setattr("moogone.synthdef.compile_synthdef", lambda *a, **k: b"def")


def test_every_preset_names_an_effect_the_instrument_has():
    for p in PRESETS:
        assert p.effect in effect_mod.EFFECTS, p.name


def test_preset_lookup_is_case_insensitive_and_says_what_exists():
    assert preset("plate").name == "Plate"
    with pytest.raises(EffectError, match="no preset named"):
        preset("chorus pedal")


def test_attaching_a_source_routes_it_and_moves_it_into_the_source_group():
    # The group is the half that is easy to forget. Routing the audio without
    # moving the voices leaves every new note landing after the effect, where it
    # is heard dry and nothing reports a problem.
    send = EffectSend(FakeClient())
    source = FakeSource()
    send.attach(source)
    assert (source.left, source.right) == (IN_BUS, IN_BUS + 1)
    assert source.group == SOURCE_GROUP


def test_detaching_puts_the_source_back_on_the_main_outputs():
    send = EffectSend(FakeClient())
    source = FakeSource()
    send.attach(source)
    send.detach(source)
    assert (source.left, source.right) == (MAIN_LEFT, MAIN_RIGHT)
    assert source.group == 0


def test_the_source_group_is_made_at_the_head_and_the_effect_group_at_the_tail():
    client = FakeClient()
    EffectSend(client).ensure_groups()
    groups = client.of("/g_new")
    assert (SOURCE_GROUP, 0, 0) == groups[0][1:]  # addAction 0 = head
    assert (EFFECT_GROUP, 1, 0) == groups[1][1:]  # addAction 1 = tail


def test_groups_are_only_made_once():
    # A group that already exists draws a /fail, and an unsolicited /fail is blamed
    # on whatever request comes next.
    client = FakeClient()
    send = EffectSend(client)
    send.ensure_groups()
    send.ensure_groups()
    assert len(client.of("/g_new")) == 2


def test_engage_creates_the_effect_then_the_monitor_after_it(no_sclang):
    client = FakeClient()
    send = EffectSend(client)
    send.engage("et_plate_1")
    news = client.of("/s_new")
    assert news[0][1] == "et_plate_1"
    assert news[1][1] == effect_mod.MONITOR_DEF
    # Same group, made second, so it runs after the effect and carries this
    # block's output rather than the previous one's.
    assert news[1][4] == EFFECT_GROUP
    assert send.engaged and send.effect == "et_plate_1"


def test_the_monitor_reads_the_effects_output_bus(no_sclang):
    client = FakeClient()
    EffectSend(client).engage("et_plate_1")
    monitor = next(m for m in client.of("/s_new") if m[1] == effect_mod.MONITOR_DEF)
    assert monitor[monitor.index("wet_in") + 1] == FX_BUS


def test_engage_refuses_an_effect_the_instrument_does_not_have(no_sclang):
    with pytest.raises(EffectError, match="not one of the instrument's effects"):
        EffectSend(FakeClient()).engage("reverb")


def test_disengage_stops_the_effect_and_never_frees_it(no_sclang):
    # Freeing one terminates scsynth. Measured directly, and it took the audio
    # engine down three times before it was isolated.
    client = FakeClient()
    send = EffectSend(client)
    send.engage("et_plate_1")
    client.sent.clear()
    send.disengage()
    assert ("/n_set", PLATE, "enable", 0) in client.sent
    assert [m[1] for m in client.of("/n_free")] == [MONITOR_NODE]


def test_disengage_puts_every_attached_source_back(no_sclang):
    client = FakeClient()
    send = EffectSend(client)
    a, b = FakeSource(), FakeSource()
    send.attach(a)
    send.attach(b)
    send.engage("et_plate_1")
    send.disengage()
    for source in (a, b):
        assert (source.left, source.right) == (MAIN_LEFT, MAIN_RIGHT)
        assert source.group == 0


def test_a_control_the_effect_does_not_have_is_skipped_not_sent(no_sclang):
    # The rack is not uniform: a plate has size and decay, a delay has neither.
    # /n_set on a control a synth does not have draws an unsolicited /fail, and
    # that gets blamed on the NEXT request.
    client = FakeClient(parked="tapeDelay_1", controls={"mix": 0.5, "feedback": 0.3})
    send = EffectSend(client)
    send.engage("tapeDelay_1")
    client.sent.clear()
    send.configure(mix=0.4, size=0.9, decay=0.8)
    sets = client.of("/n_set")
    assert sets and "size" not in sets[0] and "decay" not in sets[0]
    assert "mix" in sets[0]


def test_configure_without_an_engaged_effect_is_an_error():
    with pytest.raises(EffectError, match="no effect engaged"):
        EffectSend(FakeClient()).configure(mix=0.5)


def test_editing_by_hand_clears_the_preset_name_but_recall_does_not(no_sclang):
    # A label on the instrument's screen that no longer describes the sound is
    # worse than no label. FMEngine.configure does the same.
    client = FakeClient(
        parked="et_plate_1", controls={"mix": 0.5, "size": 0.5, "decay": 0.5, "diffusion": 0.5}
    )
    send = EffectSend(client)
    send.recall("Plate")
    assert send.preset_name == "Plate"
    send.configure(mix=0.9)
    assert send.preset_name == ""


def test_recall_sets_the_level_as_well_as_the_controls(no_sclang):
    client = FakeClient(
        parked="et_room_1", controls={"mix": 0.5, "size": 0.5, "decay": 0.5, "reflection": 0.5}
    )
    send = EffectSend(client)
    chosen = send.recall("Small Room")
    assert send.level == pytest.approx(chosen.level)
    assert ("/n_set", MONITOR_NODE, "gain", chosen.level) in client.sent


def test_level_is_clamped_to_something_a_gain_can_be():
    client = FakeClient()
    send = EffectSend(client)
    send.set_level(9.0)
    assert send.level == 1.0
    send.set_level(-3.0)
    assert send.level == 0.0


def test_switching_effects_parks_the_old_one_and_never_frees_it(no_sclang):
    # Each effect has its own node, so switching is legal -- which is the point:
    # a shared node could only ever hold the first effect engaged, and "try another
    # one" would mean restarting the audio engine. The outgoing effect is parked,
    # and parking points it away from the shared bus so a tail on its way out
    # cannot be heard through a send that has moved on.
    client = FakeClient()
    send = EffectSend(client)
    send.engage("et_plate_1")
    client.sent.clear()
    send.engage("et_hall_1")

    plate = node_for("et_plate_1")
    assert ("/n_set", plate, "enable", 0) in client.sent
    assert ("/n_set", plate, "inBus", 0, "outBus", 0) in client.sent
    # The monitor is ours and made of plain ugens, so freeing it is fine. No
    # EFFECT node is ever freed, and that is the rule under test.
    freed = [m[1] for m in client.of("/n_free")]
    assert freed == [MONITOR_NODE]
    assert send.node == node_for("et_hall_1")


def test_a_foreign_synth_at_a_reserved_node_is_refused_not_freed(no_sclang):
    # Someone else's synth at an id we reserved. Not ours to free, so say so.
    client = FakeClient()
    client.parked = "stereoChorus_1"
    client.parked_node = node_for("et_plate_1")
    with pytest.raises(EffectError, match="cannot be freed"):
        EffectSend(client).engage("et_plate_1")
    assert client.of("/n_free") == []


def test_re_engaging_the_same_effect_resumes_it_rather_than_making_a_second(no_sclang):
    # It cannot make a second at that id and cannot free the first, so resuming is
    # the only way. /n_run first: a paused synth is not running to see a control set.
    client = FakeClient(parked="et_plate_1")
    send = EffectSend(client)
    send.engage("et_plate_1")
    assert [m for m in client.of("/s_new") if m[1] == "et_plate_1"] == []
    run = client.sent.index(("/n_run", PLATE, 1))
    enable = client.sent.index(("/n_set", PLATE, "enable", 1))
    assert run < enable


def test_state_reports_what_the_interface_needs(no_sclang):
    client = FakeClient(
        parked="et_plate_1", controls={"mix": 0.5, "size": 0.5, "decay": 0.5, "diffusion": 0.5}
    )
    send = EffectSend(client)
    send.attach(FakeSource())
    send.recall("Plate")
    state = send.as_dict()
    assert state["engaged"] and state["effect"] == "et_plate_1"
    assert state["preset"] == "Plate" and state["sources"] == 1
    assert state["in_bus"] == IN_BUS and state["out_bus"] == FX_BUS
    assert len(state["presets"]) == len(PRESETS)


def test_state_reports_the_instruments_own_control_values(no_sclang):
    # Not just the ones this process set. Without the live values an interface can
    # only show what it happened to change, and every other control reads as
    # whatever its slider defaulted to -- a panel confidently displaying a number
    # the instrument does not hold.
    live = {"mix": 0.5, "size": 0.25, "decay": 0.2, "reflection": 0.5, "pan": 0.1}
    client = FakeClient(parked="et_room_1", controls=live)
    send = EffectSend(client)
    send.engage("et_room_1")
    assert send.as_dict()["controls"]["pan"] == pytest.approx(0.1)


def test_recall_leaves_the_untouched_controls_reading_the_instrument(no_sclang):
    live = {"mix": 0.5, "size": 0.5, "decay": 0.5, "reflection": 0.5, "pan": 0.1}
    client = FakeClient(parked="et_room_1", controls=live)
    send = EffectSend(client)
    send.recall("Small Room")
    state = send.as_dict()["controls"]
    assert state["size"] == pytest.approx(0.25)  # the preset set this
    assert state["pan"] == pytest.approx(0.1)  # the instrument still holds this


def test_ensure_monitor_compiles_only_once(no_sclang):
    # It shells out to sclang for about ten seconds. The bridge warms it off the
    # request path so the first recall does not freeze the interface.
    client = FakeClient()
    send = EffectSend(client)
    send.ensure_monitor()
    send.ensure_monitor()
    assert client.defs == 1


def test_the_monitor_reads_the_dry_bus_as_well_as_the_wet_one(no_sclang):
    # The instrument's effects output WET ONLY. Moog's et_plate overwrites its own
    # `mix` control with 1 before calling the plugin and writes only the plugin's
    # output, so a send that routes sources into an effect has no dry path at all
    # and you hear reverb tails with no note attacks.
    client = FakeClient()
    EffectSend(client).engage("et_plate_1")
    monitor = next(m for m in client.of("/s_new") if m[1] == effect_mod.MONITOR_DEF)
    assert monitor[monitor.index("dry_in") + 1] == IN_BUS
    assert monitor[monitor.index("wet_in") + 1] == FX_BUS


def test_engaging_sets_the_effect_gain_to_unity(no_sclang):
    # `gain` is mapped through ControlSpec(0.01, 2.25, \exp), so the default of 1.0
    # sits at the TOP of that range -- 2.25x into a softclip. Every effect arrives
    # distorting until this is set.
    client = FakeClient(parked="et_plate_1", controls={"gain": 1.0, "mix": 0.5})
    send = EffectSend(client)
    send.engage("et_plate_1")
    sets = [m for m in client.of("/n_set") if "gain" in m]
    assert sets, "gain was never set"
    assert sets[-1][sets[-1].index("gain") + 1] == pytest.approx(effect_mod.UNITY_GAIN)


def test_mix_goes_to_the_send_when_the_effect_has_no_usable_one(no_sclang):
    # Setting `mix` on an et_ effect does nothing -- the synthdef overwrites it. So
    # a preset asking for mix has to reach the monitor instead.
    client = FakeClient(parked="et_plate_1", controls={"gain": 1.0, "size": 0.5})
    send = EffectSend(client)
    send.engage("et_plate_1")
    client.sent.clear()
    send.configure(mix=0.4)
    assert ("/n_set", MONITOR_NODE, "mix", pytest.approx(0.4)) in [
        (m[0], m[1], m[2], m[3]) for m in client.of("/n_set") if len(m) > 3
    ]


def test_recall_sets_the_sends_mix_from_the_preset(no_sclang):
    client = FakeClient(parked="et_room_1", controls={"gain": 1.0, "size": 0.5, "decay": 0.5})
    send = EffectSend(client)
    chosen = send.recall("Small Room")
    assert send.mix == pytest.approx(chosen.mix)
    assert send.as_dict()["mix"] == pytest.approx(chosen.mix)


def test_mix_is_clamped():
    send = EffectSend(FakeClient())
    send.set_mix(4.0)
    assert send.mix == 1.0
    send.set_mix(-1.0)
    assert send.mix == 0.0
