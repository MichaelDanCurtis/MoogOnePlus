"""Tests for the makeup gain stage."""

from __future__ import annotations

import pytest

from moogone.makeup import (
    DEFAULT_GAIN_DB,
    MAKEUP_GRAPH,
    MEASURED_HEADROOM_DB,
    db_to_gain,
    gain_to_db,
)


class TestConversion:
    @pytest.mark.parametrize("db,gain", [(0, 1.0), (6.0206, 2.0), (20, 10.0), (-6.0206, 0.5)])
    def test_db_to_gain(self, db, gain):
        assert db_to_gain(db) == pytest.approx(gain, rel=1e-4)

    @pytest.mark.parametrize("db", [-24, -6, 0, 6, 12, 20])
    def test_round_trip(self, db):
        assert gain_to_db(db_to_gain(db)) == pytest.approx(db)

    def test_zero_gain_has_no_decibel_value(self):
        with pytest.raises(ValueError, match="must be positive"):
            gain_to_db(0.0)


class TestGraph:
    def test_replaces_rather_than_mixes(self):
        # `Out` would add a louder copy alongside the original. Only `ReplaceOut`
        # makes this a gain stage.
        assert "ReplaceOut" in MAKEUP_GRAPH
        assert "Out.ar(bus" not in MAKEUP_GRAPH.replace("ReplaceOut.ar(bus", "")

    def test_limits_after_the_gain(self):
        # The limiter has to wrap the gained signal, not the raw one, or it protects
        # nothing.
        assert "Limiter.ar(In.ar(bus, 2) * gain" in MAKEUP_GRAPH

    def test_compiles_in_a_real_supercollider(self):
        sc = pytest.importorskip("moogone.synthdef")
        if not sc.available():
            pytest.skip("no sclang on this machine")
        data = sc.compile_synthdef("voxMakeup", MAKEUP_GRAPH)
        assert data.startswith(b"SCgf")
        assert b"voxMakeup" in data


class TestSafety:
    def test_default_stays_inside_the_measured_headroom(self):
        assert DEFAULT_GAIN_DB < MEASURED_HEADROOM_DB

    def test_measured_headroom_is_what_was_measured(self):
        # bus 0 peaked at -20.6 dBFS with the instrument as loud as it goes.
        assert MEASURED_HEADROOM_DB == pytest.approx(20.6)

    def test_more_gain_than_headroom_is_refused(self):
        from moogone.makeup import apply

        class Client:
            def send(self, *a): raise AssertionError("must refuse before sending")
            def sync(self): pass

        with pytest.raises(ValueError, match="exceeds"):
            apply(Client(), gain_db=30.0)

    @pytest.mark.parametrize("ceiling", [0.0, -0.5, 1.5])
    def test_an_impossible_ceiling_is_refused(self, ceiling):
        from moogone.makeup import apply

        class Client:
            def send(self, *a): raise AssertionError("must refuse before sending")
            def sync(self): pass

        with pytest.raises(ValueError, match="ceiling"):
            apply(Client(), gain_db=6.0, ceiling=ceiling)
