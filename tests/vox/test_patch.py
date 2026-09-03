"""The patcher. Validation is the point: a graph that would fail on a server must be
refused here, with a reason you can act on.

The generated source is checked by reading — there is no SuperCollider on this machine to
compile against, which is exactly why the generator emits source rather than bytes.
"""

import pytest

from moogone.vox.patch import (
    ALL_CHANNELS,
    Cable,
    Node,
    Patch,
    PatchError,
    order,
    to_source,
    validate,
)
from moogone.vox.ugens import ALL, CATALOG, catalog_for_ui, spec


def simple() -> Patch:
    """Saw -> MoogFF -> Out. The smallest patch that makes a sound."""
    return Patch(
        name="simple",
        nodes=[
            Node("s", "Saw", params={"freq": 110.0}),
            Node("f", "MoogFF", params={"freq": 900.0, "gain": 2.5}),
            Node("o", "Out", params={"bus": 0.0}),
        ],
        cables=[Cable("s", "f", "in"), Cable("f", "o", "channelsArray")],
    )


class TestCatalog:
    def test_every_spec_round_trips_to_the_ui_shape(self):
        items = catalog_for_ui()
        assert len(items) == len(ALL)
        for d in items:
            assert set(d) >= {"name", "category", "inputs", "outputs", "rates"}

    def test_required_ports_are_the_ones_without_defaults(self):
        assert spec("LPF").port("in").required
        assert not spec("LPF").port("freq").required

    def test_unknown_ugen_names_itself_in_the_error(self):
        with pytest.raises(KeyError, match="Wobbulator"):
            spec("Wobbulator")

    def test_the_moog_ladder_is_in_the_palette(self):
        """This is a Moog patcher; MoogFF earns its place."""
        assert "MoogFF" in CATALOG

    def test_stereo_ugens_declare_two_outputs(self):
        assert spec("Pan2").outputs == 2
        assert spec("Out").outputs == 0


class TestValidate:
    def test_a_good_patch_has_no_problems(self):
        assert validate(simple()) == []

    def test_missing_out_is_reported(self):
        p = simple()
        p.nodes = [n for n in p.nodes if n.kind != "Out"]
        p.cables = [c for c in p.cables if c.dst != "o"]
        assert any("no Out node" in m for m in validate(p))

    def test_unconnected_required_input_is_reported_by_name(self):
        p = Patch(
            nodes=[Node("f", "LPF"), Node("o", "Out")], cables=[Cable("f", "o", "channelsArray")]
        )
        assert any("'in' must be connected" in m for m in validate(p))

    def test_optional_input_may_be_left_alone(self):
        assert not any("freq" in m for m in validate(simple()))

    def test_unknown_ugen_is_reported(self):
        p = simple()
        p.nodes.append(Node("z", "Bogus"))
        assert any("unknown UGen 'Bogus'" in m for m in validate(p))

    def test_unknown_port_is_reported(self):
        p = simple()
        p.cables.append(Cable("s", "f", "resonance"))
        assert any("no input called 'resonance'" in m for m in validate(p))

    def test_unknown_param_key_is_reported(self):
        p = simple()
        p.node("f").params["squelch"] = 1.0
        assert any("no input called 'squelch'" in m for m in validate(p))

    def test_cable_from_a_missing_node(self):
        p = simple()
        p.cables.append(Cable("ghost", "o", "bus"))
        assert any("no node 'ghost'" in m for m in validate(p))

    def test_two_cables_into_one_input_is_ambiguous_not_a_mix(self):
        """Silently summing would be a guess about intent."""
        p = simple()
        p.nodes.append(Node("s2", "Saw"))
        p.cables.append(Cable("s2", "f", "in"))
        assert any("2 cables into it" in m for m in validate(p))

    def test_outlet_out_of_range(self):
        p = simple()
        p.cables.append(Cable("s", "o", "bus", outlet=1))
        assert any("outlet 1 does not exist" in m for m in validate(p))

    def test_a_stereo_outlet_is_allowed(self):
        p = Patch(
            nodes=[Node("s", "Saw"), Node("p", "Pan2"), Node("o", "Out")],
            cables=[Cable("s", "p", "in"), Cable("p", "o", "channelsArray", outlet=1)],
        )
        assert validate(p) == []

    def test_duplicate_node_ids(self):
        p = simple()
        p.nodes.append(Node("s", "SinOsc"))
        assert any("duplicate node id 's'" in m for m in validate(p))

    def test_patch_name_must_be_an_identifier(self):
        p = simple()
        p.name = "my patch!"
        assert any("not a valid SuperCollider identifier" in m for m in validate(p))

    def test_control_needs_a_valid_parameter_name(self):
        p = simple()
        p.nodes.append(Node("c", "control", rate="control", name="not a name"))
        assert any("valid parameter name" in m for m in validate(p))

    def test_every_problem_is_reported_not_just_the_first(self):
        p = Patch(name="bad name", nodes=[Node("a", "Nope"), Node("a", "Nope")])
        problems = validate(p)
        assert len(problems) >= 3  # name, duplicate id, unknown ugen, no Out


class TestRates:
    def test_audio_into_control_is_refused(self):
        p = Patch(
            nodes=[
                Node("s", "Saw", rate="audio"),
                Node("l", "Lag", rate="control"),
                Node("o", "Out"),
            ],
            cables=[Cable("s", "l", "in"), Cable("l", "o", "channelsArray")],
        )
        assert any("runs at audio rate but feeds" in m for m in validate(p))

    def test_control_into_audio_is_fine(self):
        p = Patch(
            nodes=[
                Node("n", "LFNoise1", rate="control"),
                Node("s", "SinOsc", rate="audio"),
                Node("o", "Out"),
            ],
            cables=[Cable("n", "s", "freq"), Cable("s", "o", "channelsArray")],
        )
        assert validate(p) == []

    def test_a_ugen_that_does_not_offer_a_rate_is_refused(self):
        p = simple()
        p.node("s").rate = "scalar"
        assert any("does not run at scalar rate" in m for m in validate(p))


class TestCycles:
    def test_a_loop_is_named_with_its_path(self):
        p = Patch(
            nodes=[Node("a", "LPF"), Node("b", "LPF"), Node("o", "Out")],
            cables=[Cable("a", "b", "in"), Cable("b", "a", "in"), Cable("b", "o", "channelsArray")],
        )
        problems = validate(p)
        assert any(m.startswith("feedback loop:") for m in problems)
        assert any("a -> b -> a" in m or "b -> a -> b" in m for m in problems)

    def test_a_self_loop_is_a_loop(self):
        p = simple()
        p.cables.append(Cable("f", "f", "in"))
        assert any("feedback loop" in m for m in validate(p))

    def test_ordering_refuses_a_cyclic_graph(self):
        p = Patch(
            nodes=[Node("a", "LPF"), Node("b", "LPF")],
            cables=[Cable("a", "b", "in"), Cable("b", "a", "in")],
        )
        with pytest.raises(PatchError, match="feedback loop"):
            order(p)

    def test_a_diamond_is_not_a_cycle(self):
        p = Patch(
            nodes=[
                Node("s", "Saw"),
                Node("l", "LPF"),
                Node("h", "HPF"),
                Node("m", "op.add"),
                Node("o", "Out"),
            ],
            cables=[
                Cable("s", "l", "in"),
                Cable("s", "h", "in"),
                Cable("l", "m", "a"),
                Cable("h", "m", "b"),
                Cable("m", "o", "channelsArray"),
            ],
        )
        assert validate(p) == []


class TestOrder:
    def test_sources_come_before_what_consumes_them(self):
        ids = [n.id for n in order(simple())]
        assert ids.index("s") < ids.index("f") < ids.index("o")

    def test_ordering_is_stable_across_runs(self):
        p = simple()
        assert [n.id for n in order(p)] == [n.id for n in order(p)]


class TestSource:
    def test_generates_the_expected_synthdef(self):
        src = to_source(simple())
        assert "SynthDef(\\simple, {" in src
        assert "Saw.ar(110, 0)" not in src  # Saw takes only freq
        assert "Saw.ar(110)" in src
        assert "MoogFF.ar(x_s, 900, 2.5, 0)" in src
        assert "Out.ar(0, x_f)" in src
        assert src.rstrip().endswith("}).add;")

    def test_declares_its_locals(self):
        assert "var x_s, x_f;" in to_source(simple())

    def test_controls_become_named_arguments(self):
        p = simple()
        p.nodes.insert(0, Node("c", "control", rate="control", name="cutoff", default=800.0))
        p.cables.append(Cable("c", "f", "freq"))
        src = to_source(p)
        assert "|cutoff = 800|" in src
        assert "MoogFF.ar(x_s, cutoff," in src

    def test_several_controls_are_all_declared(self):
        p = simple()
        p.nodes.insert(0, Node("c1", "control", rate="control", name="cutoff", default=800.0))
        p.nodes.insert(1, Node("c2", "control", rate="control", name="drive", default=1.5))
        p.cables += [Cable("c1", "f", "freq"), Cable("c2", "f", "gain")]
        assert "|cutoff = 800, drive = 1.5|" in to_source(p)

    def test_math_nodes_are_written_infix(self):
        p = Patch(
            nodes=[Node("a", "Saw"), Node("b", "SinOsc"), Node("m", "op.mul"), Node("o", "Out")],
            cables=[Cable("a", "m", "a"), Cable("b", "m", "b"), Cable("m", "o", "channelsArray")],
        )
        assert "(x_a * x_b)" in to_source(p)

    def test_a_stereo_outlet_is_indexed(self):
        p = Patch(
            nodes=[Node("s", "Saw"), Node("p", "Pan2"), Node("o", "Out")],
            cables=[Cable("s", "p", "in"), Cable("p", "o", "channelsArray", outlet=1)],
        )
        assert "Out.ar(0, x_p[1])" in to_source(p)

    def test_control_rate_ugens_use_kr(self):
        p = Patch(
            nodes=[
                Node("n", "LFNoise1", rate="control"),
                Node("s", "SinOsc", rate="audio"),
                Node("o", "Out"),
            ],
            cables=[Cable("n", "s", "freq"), Cable("s", "o", "channelsArray")],
        )
        src = to_source(p)
        assert "LFNoise1.kr(" in src and "SinOsc.ar(" in src

    def test_numbers_are_written_so_supercollider_reads_them_back(self):
        """`1e-05` and `2.` are both valid floats in Python and wrong in the source."""
        p = simple()
        p.node("f").params["freq"] = 0.00001
        p.node("s").params["freq"] = 2.0
        src = to_source(p)
        assert "e-" not in src
        assert "Saw.ar(2)" in src

    def test_refuses_to_generate_from_an_invalid_graph(self):
        p = simple()
        p.cables = []
        with pytest.raises(PatchError, match="must be connected"):
            to_source(p)

    def test_the_error_carries_every_problem_not_just_one(self):
        p = Patch(name="no good", nodes=[Node("x", "LPF")])
        with pytest.raises(PatchError) as exc:
            to_source(p)
        assert "identifier" in str(exc.value) and "Out node" in str(exc.value)

    def test_node_ids_that_are_not_identifiers_still_produce_valid_source(self):
        p = Patch(
            nodes=[Node("osc-1", "Saw"), Node("out!", "Out")],
            cables=[Cable("osc-1", "out!", "channelsArray")],
        )
        src = to_source(p)
        assert "x_osc_1" in src and "-" not in src.split("var")[1].split(";")[0]


class TestRoundTrip:
    def test_patch_survives_dict_round_trip(self):
        p = simple()
        p.nodes.append(Node("c", "control", rate="control", name="cutoff", default=440.0))
        again = Patch.from_dict(p.as_dict())
        assert again.as_dict() == p.as_dict()

    def test_round_trip_produces_identical_source(self):
        p = simple()
        assert to_source(Patch.from_dict(p.as_dict())) == to_source(p)


class TestAllChannels:
    """Passing a whole stereo output on, rather than one channel of it."""

    def _stereo(self, outlet):
        return Patch(
            nodes=[Node("s", "Saw"), Node("p", "Pan2"), Node("o", "Out")],
            cables=[Cable("s", "p", "in"), Cable("p", "o", "channelsArray", outlet=outlet)],
        )

    def test_all_channels_passes_the_array_unindexed(self):
        assert "Out.ar(0, x_p);" in to_source(self._stereo(ALL_CHANNELS))

    def test_a_specific_outlet_is_still_indexed(self):
        assert "Out.ar(0, x_p[1]);" in to_source(self._stereo(1))

    def test_all_channels_from_a_mono_ugen_is_refused(self):
        """There is no array to pass, and silently treating it as outlet 0 would hide
        a cable the user drew wrong."""
        p = Patch(
            nodes=[Node("s", "Saw"), Node("o", "Out")],
            cables=[Cable("s", "o", "channelsArray", outlet=ALL_CHANNELS)],
        )
        assert any("single output" in m for m in validate(p))

    def test_round_trips_through_a_dict(self):
        p = self._stereo(ALL_CHANNELS)
        assert Patch.from_dict(p.as_dict()).cables[1].outlet == ALL_CHANNELS
