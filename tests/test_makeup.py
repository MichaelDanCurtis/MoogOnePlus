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
        assert MAKEUP_GRAPH.count("ReplaceOut.ar") == 2
        assert "Out.ar(" not in MAKEUP_GRAPH.replace("ReplaceOut.ar(", "")

    def test_limits_after_the_gain(self):
        # The limiter has to wrap the gained signal, not the raw one, or it protects
        # nothing. Once per channel.
        assert "Limiter.ar(In.ar(left, 1) * gain" in MAKEUP_GRAPH
        assert "Limiter.ar(In.ar(right, 1) * gain" in MAKEUP_GRAPH

    def test_touches_both_main_buses_and_only_those(self):
        # This used to read `In.ar(bus, 2)` from bus 0, which is buses 0 AND 1 --
        # main right and SUB right. It raised the right channel of two different
        # outputs and never touched main left. The main pair is 7 and 0, which are
        # not adjacent, so two consecutive channels cannot address it.
        from moogone.effect import MAIN_LEFT, MAIN_RIGHT

        assert (MAIN_LEFT, MAIN_RIGHT) == (7, 0)
        assert "left = 7" in MAKEUP_GRAPH and "right = 0" in MAKEUP_GRAPH
        assert ", 2)" not in MAKEUP_GRAPH, "a 2-channel read would pull in a sub bus"

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


class TestIdempotentFree:
    """scsynth answers /n_free for an absent node with /fail.

    Catching that where it is raised is not enough — the datagram stays in the socket
    and the NEXT request reads it instead of its own reply. That is exactly how a
    tidy-up before loading a SynthDef surfaced as "server rejected /n_free" coming
    out of d_recv, one call later.
    """

    class Transport:
        def __init__(self, queued=0):
            self.queued = queued
            self.recv_calls = 0

        def recv(self, timeout):
            self.recv_calls += 1
            if self.queued > 0:
                self.queued -= 1
                return b"\x00"          # some datagram; contents do not matter
            return None

    class Client:
        def __init__(self, queued=0):
            self.sent = []
            self.transport = TestIdempotentFree.Transport(queued)

        def send(self, *args):
            self.sent.append(args)

    def test_frees_the_right_node(self):
        from moogone.makeup import MAKEUP_NODE, remove

        c = self.Client()
        remove(c)
        assert c.sent == [("/n_free", MAKEUP_NODE)]

    def test_drains_a_pending_fail_so_the_next_request_is_not_poisoned(self):
        from moogone.makeup import remove

        c = self.Client(queued=1)
        remove(c)
        assert c.transport.recv_calls >= 2, "must keep reading until the socket is empty"
        assert c.transport.queued == 0

    def test_an_empty_socket_returns_promptly(self):
        from moogone.makeup import remove

        c = self.Client(queued=0)
        remove(c)
        assert c.transport.recv_calls == 1, "one empty read is enough"


class TestLoadCaching:
    """Compiling spawns an sclang; the server keeps a definition once it has it."""

    class Client:
        def __init__(self, fail_times=0):
            self.recv_calls = self.d_recv_calls = 0
            self.fail_times = fail_times
            self.sent = []
            self.transport = type("T", (), {"recv": lambda _self, timeout: None})()

        def send(self, *a): self.sent.append(a)
        def sync(self): pass
        def d_recv(self, data):
            self.d_recv_calls += 1
            if self.d_recv_calls <= self.fail_times:
                from moogone.sc.client import ScTimeout
                raise ScTimeout("no /done within 5.0s")

    def test_a_transient_timeout_is_retried_once(self):
        import moogone.makeup as m

        m._COMPILED = b"SCgf-pretend"
        c = self.Client(fail_times=1)
        m._load(c)
        assert c.d_recv_calls == 2

    def test_a_persistent_failure_still_raises(self):
        import moogone.makeup as m
        from moogone.sc.client import ScTimeout

        m._COMPILED = b"SCgf-pretend"
        c = self.Client(fail_times=99)
        with pytest.raises(ScTimeout):
            m._load(c)

    def test_the_definition_is_compiled_only_once(self):
        import moogone.makeup as m

        m._COMPILED = None
        if not __import__("moogone.synthdef", fromlist=["available"]).available():
            pytest.skip("no sclang on this machine")
        m._load(self.Client())
        first = m._COMPILED
        m._load(self.Client())
        assert m._COMPILED is first, "recompiling spawns another sclang for no reason"
