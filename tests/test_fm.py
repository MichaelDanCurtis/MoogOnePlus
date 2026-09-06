"""Tests for FM synthesis inside the instrument.

The Bessel tests are ANCHORED: expected values come from published tables, not
from this codebase, so they cannot be satisfied by a self-consistent wrong
implementation. That matters more here than usual — the sidebands are what the
interface draws, and a display that confidently shows the wrong spectrum is worse
than one that shows nothing.
"""

from __future__ import annotations

import math

import pytest

from moogone.fm import (
    ANALOG_IN_BUSES,
    BASELINE_CPU,
    CROSS_DEF,
    CROSS_GRAPH,
    FIRST_NODE,
    FM_DEF,
    FM_GRAPH,
    MAX_INDEX,
    MAX_VOICES,
    VOICE_CPU_COST,
    FMEngine,
    FMError,
    bessel_j,
    cpu_estimate,
    note_to_freq,
    sidebands,
)


class FakeClient:
    def __init__(self):
        self.sent = []
        self.defs = []

    def send(self, *args):
        self.sent.append(args)

    def sync(self):
        pass

    def d_recv(self, data):
        self.defs.append(data)

    def of(self, address):
        return [m for m in self.sent if m[0] == address]


class TestBesselAnchoredToPublishedValues:
    # Abramowitz & Stegun / standard tables. External to this codebase.
    @pytest.mark.parametrize(
        "n,x,expected",
        [
            (0, 0.0, 1.0),
            (1, 0.0, 0.0),
            (0, 1.0, 0.7651976866),
            (1, 1.0, 0.4400505857),
            (1, 2.0, 0.5767248078),
            (2, 3.0, 0.4860912606),
            (0, 5.0, -0.1775967713),
            (3, 5.0, 0.3648312306),
        ],
    )
    def test_matches_published_tables(self, n, x, expected):
        assert bessel_j(n, x) == pytest.approx(expected, abs=1e-8)

    def test_first_zero_of_j0(self):
        # J0 has its first zero at x = 2.404825557...
        assert bessel_j(0, 2.404825557695773) == pytest.approx(0.0, abs=1e-9)

    def test_negative_order_reflects(self):
        # J(-n, x) = (-1)^n J(n, x)
        for n in (1, 2, 3):
            assert bessel_j(-n, 2.5) == pytest.approx(
                ((-1) ** n) * bessel_j(n, 2.5), abs=1e-12
            )

    def test_energy_is_conserved(self):
        # An identity independent of this code: J0^2 + 2*sum(Jn^2) == 1.
        for index in (0.5, 2.0, 5.0, 9.0):
            total = bessel_j(0, index) ** 2
            total += 2 * sum(bessel_j(n, index) ** 2 for n in range(1, 60))
            assert total == pytest.approx(1.0, abs=1e-6), f"index {index}"


class TestSidebands:
    def test_zero_index_is_a_pure_tone(self):
        bands = sidebands(ratio=2.0, index=0.0)
        assert len(bands) == 1
        assert bands[0].order == 0
        assert bands[0].amplitude == pytest.approx(1.0, abs=1e-9)

    def test_partials_land_where_theory_says(self):
        bands = {s.order: s for s in sidebands(ratio=3.0, index=2.0)}
        # fc +/- n*fm, as multiples of the carrier
        assert bands[1].ratio == pytest.approx(4.0)
        assert bands[-1].ratio == pytest.approx(-2.0)
        assert bands[2].ratio == pytest.approx(7.0)

    def test_amplitudes_are_the_bessel_values(self):
        for s in sidebands(ratio=1.5, index=4.0):
            assert s.amplitude == pytest.approx(abs(bessel_j(s.order, 4.0)), abs=1e-9)

    def test_reflection_is_reported_not_hidden(self):
        # ratio below 1 puts lower sidebands through zero and back up
        bands = sidebands(ratio=0.5, index=3.0)
        reflected = [s for s in bands if s.is_reflected]
        assert reflected, "negative-frequency partials must be visible to the caller"
        assert all(s.ratio < 0 for s in reflected)

    def test_a_higher_index_spreads_energy_wider(self):
        narrow = sidebands(ratio=2.0, index=1.0)
        wide = sidebands(ratio=2.0, index=8.0)
        assert max(abs(s.order) for s in wide) > max(abs(s.order) for s in narrow)

    def test_refuses_what_it_cannot_compute_honestly(self):
        with pytest.raises(FMError, match="not computed"):
            sidebands(ratio=2.0, index=MAX_INDEX + 1)
        with pytest.raises(FMError, match="negative"):
            sidebands(ratio=2.0, index=-1)
        with pytest.raises(FMError, match="positive"):
            sidebands(ratio=0.0, index=1.0)


class TestPitch:
    def test_a440(self):
        assert note_to_freq(69) == pytest.approx(440.0)

    def test_octaves(self):
        assert note_to_freq(81) == pytest.approx(880.0)
        assert note_to_freq(57) == pytest.approx(220.0)


class TestCpuBudget:
    def test_uses_the_measured_numbers(self):
        assert cpu_estimate(0) == pytest.approx(BASELINE_CPU)
        assert cpu_estimate(16) == pytest.approx(BASELINE_CPU + 16 * VOICE_CPU_COST)

    def test_sixty_four_voices_matches_what_the_hardware_did(self):
        # Measured: 64 voices reached 87% of a core, from a 55.2% baseline.
        assert cpu_estimate(64) == pytest.approx(0.872, abs=0.02)


class TestEngine:
    def test_synthdefs_load_once(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.note_on(60)
        engine.note_on(62)
        assert len(client.defs) == 2, "one for each of the two graphs, loaded once"

    def test_a_note_writes_both_output_buses(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.note_on(69)
        new = client.of("/s_new")[0]
        args = dict(zip(new[5::2], new[6::2], strict=False))
        # Out.ar writes consecutive buses, so the right channel is a separate write
        assert args["left"] == 0
        assert args["right"] == 7
        assert args["freq"] == pytest.approx(440.0)

    def test_analog_mode_uses_the_cross_synth_and_an_input_bus(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.configure(mode="analog", inbus=12)
        engine.note_on(60)
        new = client.of("/s_new")[0]
        assert new[1] == CROSS_DEF
        args = dict(zip(new[5::2], new[6::2], strict=False))
        assert args["inbus"] == 12

    def test_self_mode_uses_the_plain_synth(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.note_on(60)
        assert client.of("/s_new")[0][1] == FM_DEF

    def test_it_does_not_free_voices_that_already_ended(self):
        # The bug that cost hours in the sampler: /n_free for a finished node draws
        # a /fail nobody awaits, which then poisons the NEXT request.
        client = FakeClient()
        engine = FMEngine(client)
        engine.configure(attack=0.001, decay=0.001)
        for _ in range(4):
            engine.note_on(60)
            time_sleep = 0.01
            import time as _t
            _t.sleep(time_sleep)
        assert client.of("/n_free") == [], "freed voices that had already ended"

    def test_it_does_free_a_slot_it_is_about_to_reuse(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.configure(attack=0.0, decay=60.0)   # long, so nothing expires
        for _ in range(MAX_VOICES + 1):
            engine.note_on(60)
        assert len(client.of("/n_free")) == 1, "the recycled slot must be cut"

    def test_note_off_forgets_without_cutting(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.configure(decay=30.0)
        engine.note_on(60)
        engine.note_off(60)
        assert client.of("/n_free") == [], "a one-shot tail must not be cut short"
        assert engine.active() == []

    def test_active_reports_what_is_sounding(self):
        client = FakeClient()
        engine = FMEngine(client)
        engine.configure(decay=30.0)
        engine.note_on(60)
        engine.note_on(64)
        notes = sorted(v.note for v in engine.active())
        assert notes == [60, 64]

    def test_nodes_stay_clear_of_the_sampler(self):
        from moogone.sampler import FIRST_NODE as SAMPLER_FIRST
        from moogone.sampler import MAX_VOICES as SAMPLER_MAX

        assert FIRST_NODE >= SAMPLER_FIRST + SAMPLER_MAX, (
            "FM and sampler voices must not share node ids, or one frees the other's"
        )

    def test_configure_rejects_nonsense(self):
        engine = FMEngine(FakeClient())
        for bad in ({"mode": "sideways"}, {"inbus": 99}, {"ratio": 0},
                    {"index": MAX_INDEX + 1}, {"wobble": 1}):
            with pytest.raises(FMError):
                engine.configure(**bad)

    def test_input_bus_choices_are_the_measured_ones(self):
        assert 12 in ANALOG_IN_BUSES, "bus 12 was the loudest analog feed"
        assert 13 not in ANALOG_IN_BUSES, "13-15 measured silent"

    def test_as_dict_carries_the_spectrum_for_the_ui(self):
        engine = FMEngine(FakeClient())
        engine.configure(ratio=2.0, index=3.0, decay=30.0)
        engine.note_on(60)
        d = engine.as_dict()
        assert d["voices"][0]["note"] == 60
        assert d["spectrum"], "the interface needs partials to draw"
        assert d["cpu_estimate"] > BASELINE_CPU

    def test_analog_mode_offers_no_predicted_spectrum(self):
        # The modulator is a live analog voice, so its spectrum is not predictable
        # from ratio and index. Showing one would be a fabrication.
        engine = FMEngine(FakeClient())
        engine.configure(mode="analog")
        assert engine.as_dict()["spectrum"] == []


class TestSynthdefSource:
    def test_the_modulator_deviation_uses_the_modulator_frequency(self):
        # I = deviation / f_modulator. Writing `index * freq` instead of
        # `index * freq * ratio` makes the true index wrong by a factor of ratio,
        # and the drawn spectrum would then not match the sound.
        assert "index * freq * ratio" in FM_GRAPH

    def test_both_graphs_write_two_separate_buses(self):
        for graph in (FM_GRAPH, CROSS_GRAPH):
            assert graph.count("Out.ar") == 2

    def test_voices_free_themselves(self):
        for graph in (FM_GRAPH, CROSS_GRAPH):
            assert "doneAction: 2" in graph

    def test_the_cross_graph_reads_an_input_bus(self):
        assert "In.ar(inbus" in CROSS_GRAPH


def test_bessel_series_stays_finite_at_the_cap():
    assert math.isfinite(bessel_j(0, MAX_INDEX))
    assert math.isfinite(bessel_j(20, MAX_INDEX))
