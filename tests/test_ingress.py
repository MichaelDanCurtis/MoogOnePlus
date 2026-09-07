"""Tests for getting audio into the instrument.

Three of these exist because a real attempt failed that way on hardware, and the
failure was silent every time: a write that runs off the end of the ring is
rejected with a /fail nothing is waiting for; a rate controller that over-corrects
is audible as pitch rather than as an error; and a half-armed ingress leaves a
synth looping stale buffer contents into a bus with nothing to stop it.
"""

from __future__ import annotations

import pytest

from moogone import ingress
from moogone.effect import EffectError, node_for
from moogone.ingress import (
    BLOCK,
    RING_BUFFER,
    RING_NODE,
    Ingress,
    IngressError,
    RingWriter,
    arm,
    correction,
    disarm,
    gap,
)


class FakeNode:
    def __init__(self, node_id, defname):
        self.node_id = node_id
        self.defname = defname


class FakeTree:
    def __init__(self, nodes):
        self._nodes = nodes

    def walk(self):
        return list(self._nodes)


class FakeClient:
    def __init__(self, position: int = 0, fail_sync: bool = False, parked: str | None = None):
        self.sent: list[tuple] = []
        self.defs = 0
        self.position = position
        self.fail_sync = fail_sync
        self.syncs = 0
        self.parked = parked

    def send(self, *args):
        self.sent.append(args)

    def sync(self, *a, **k):
        self.syncs += 1
        if self.fail_sync:
            raise TimeoutError("no /synced")

    def d_recv(self, blob, timeout=None):
        self.defs += 1

    def request(self, address, *args, reply=None, timeout=None):
        class Reply:
            pass

        r = Reply()
        r.args = [ingress.POSITION_BUS, float(self.position)]
        return r

    def query_tree(self, group=0, **k):
        if self.parked is None:
            return FakeTree([])
        # Reported at the node the REQUESTED effect would use, which is how a
        # foreign synth squatting on a reserved id presents.
        return FakeTree([FakeNode(node_for("et_plate_1"), self.parked)])

    def of(self, address):
        return [m for m in self.sent if m and m[0] == address]


@pytest.fixture
def no_sclang(monkeypatch):
    monkeypatch.setattr("moogone.synthdef.compile_synthdef", lambda *a, **k: b"def")


def test_gap_is_the_wrapped_distance_from_reader_to_writer():
    assert gap(write_position=500, read_position=100, frames=1000) == 400
    # The writer has wrapped and the reader has not. The absolute values say the
    # writer is behind; the ring says it is 900 frames ahead, which is the truth.
    assert gap(write_position=50, read_position=150, frames=1000) == 900
    assert gap(write_position=100, read_position=100, frames=1000) == 0


def test_correction_is_neutral_when_the_gap_is_on_target():
    assert correction(gap_frames=500, target=500, frames=1000) == 1.0


def test_correction_slows_down_when_too_far_ahead_and_speeds_up_when_too_close():
    # Too far ahead of the reader: write more slowly and let it catch up.
    assert correction(gap_frames=800, target=500, frames=1000) < 1.0
    # Too close to being overtaken: write faster.
    assert correction(gap_frames=200, target=500, frames=1000) > 1.0


def test_correction_never_exceeds_the_clamp():
    # A gap error of a whole ring would ask for a huge rate change. Applying it
    # would be an audible pitch jump, and the drift it is meant to answer is a
    # fraction of a percent -- so it is clamped rather than obeyed.
    assert correction(gap_frames=0, target=999, frames=1000) == pytest.approx(
        1.0 + ingress.MAX_CORRECTION
    )
    assert correction(gap_frames=999, target=0, frames=1000) == pytest.approx(
        1.0 - ingress.MAX_CORRECTION
    )


def test_correction_survives_a_zero_length_ring():
    assert correction(gap_frames=0, target=0, frames=0) == 1.0


def test_a_write_that_would_run_past_the_end_is_split_in_two():
    # Buffer writes do not wrap. Sending 256 samples starting 200 frames from the
    # end writes 56 frames past the buffer, and scsynth answers with a /fail that
    # nothing is waiting for -- so the audio simply goes missing.
    client = FakeClient()
    writer = RingWriter(client, Ingress(1000, None, 100), lambda n: [0.5] * n)
    writer.write_position = 800
    writer._send([0.25] * 256)

    writes = client.of("/b_setn")
    assert len(writes) == 2
    assert writes[0][2] == 800 and writes[0][3] == 200
    assert writes[1][2] == 0 and writes[1][3] == 56
    assert writer.write_position == 56


def test_a_write_that_fits_is_sent_as_one_message():
    client = FakeClient()
    writer = RingWriter(client, Ingress(1000, None, 100), lambda n: [0.5] * n)
    writer._send([0.25] * 100)
    assert len(client.of("/b_setn")) == 1
    assert writer.write_position == 100


def test_priming_fills_the_lead_before_the_reader_gets_there():
    client = FakeClient()
    writer = RingWriter(client, Ingress(4096, None, 100), lambda n: [0.1] * n, lead=1024)
    writer.prime()
    written = sum(m[3] for m in client.of("/b_setn"))
    assert written == 1024


def test_arm_refuses_an_effect_the_instrument_does_not_have(no_sclang):
    client = FakeClient()
    with pytest.raises(IngressError, match="not one of the instrument's effects"):
        arm(client, effect="reverb")
    assert client.sent == []


def test_arm_refuses_a_ring_too_small_for_one_write(no_sclang):
    client = FakeClient()
    with pytest.raises(IngressError, match="too small"):
        arm(client, frames=BLOCK)


def test_arm_puts_the_effect_after_the_ring_and_captures_its_output(no_sclang):
    client = FakeClient()
    armed = arm(client, effect="et_plate_1", frames=4096)

    news = client.of("/s_new")
    assert news[0][1] == ingress.RING_DEF
    assert news[1][1] == "et_plate_1"
    # addAction 3 is addAfter, and the target is the ring synth: creation order is
    # execution order, so an effect made before its source reads a stale bus.
    assert news[1][3] == 3 and news[1][4] == RING_NODE
    assert armed.out_bus == ingress.FX_BUS


def test_without_an_effect_the_ring_bus_is_what_comes_back(no_sclang):
    client = FakeClient()
    armed = arm(client, effect=None, frames=4096)
    assert client.of("/s_new") == [c for c in client.of("/s_new") if c[1] == ingress.RING_DEF]
    assert armed.out_bus == ingress.IN_BUS


def test_arm_unwinds_when_it_fails_partway(no_sclang, monkeypatch):
    # A half-armed ingress is worse than none: the ring synth loops whatever is in
    # the buffer into a bus, forever, and nothing stops it.
    client = FakeClient()
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise TimeoutError("no /synced")

    monkeypatch.setattr(client, "sync", flaky)
    with pytest.raises(TimeoutError):
        arm(client, effect="et_plate_1", frames=4096)

    assert RING_NODE in [m[1] for m in client.of("/n_free")]
    assert client.of("/b_free")[-1][1] == RING_BUFFER


def test_the_effect_is_never_freed_because_freeing_one_kills_scsynth():
    # Measured directly on hardware: create et_plate_1, /n_free it, and the server
    # stops answering. Moog make these once at boot and never free them, so the
    # free path is the part of their lifecycle their own firmware never runs.
    client = FakeClient()
    disarm(client, effect="et_plate_1")
    assert [m[1] for m in client.of("/n_free")] == [RING_NODE]
    assert (("/n_set", node_for("et_plate_1"), "enable", 0)) in client.sent


def test_disarm_stops_the_effect_before_freeing_its_source():
    client = FakeClient()
    # The effect reads the ring synth's bus, so it is parked before the source is
    # freed -- otherwise a reverb tail feeds on whatever else lands there.
    disarm(client, effect="et_plate_1")
    stop = client.sent.index(("/n_set", node_for("et_plate_1"), "enable", 0))
    free = client.sent.index(("/n_free", RING_NODE))
    assert stop < free


def test_re_arming_resumes_the_parked_effect_rather_than_making_a_second(no_sclang):
    # It cannot make a second one at that id, and it cannot free the first, so the
    # only way to arm twice is to resume. /n_run first: a paused synth is not
    # running to notice a control being set.
    client = FakeClient(parked="et_plate_1")
    arm(client, effect="et_plate_1", frames=4096)
    assert client.of("/s_new") == [c for c in client.of("/s_new") if c[1] == ingress.RING_DEF]
    run = client.sent.index(("/n_run", node_for("et_plate_1"), 1))
    enable = client.sent.index(("/n_set", node_for("et_plate_1"), "enable", 1))
    assert run < enable


def test_a_foreign_synth_at_the_reserved_node_is_refused_not_freed(no_sclang):
    # Each effect now has its own node, so an ordinary effect switch is legal.
    # What is still refused is someone else's synth sitting at an id we reserved.
    client = FakeClient(parked="stereoChorus_1")
    with pytest.raises(EffectError, match="cannot be freed"):
        arm(client, effect="et_plate_1", frames=4096)
    assert client.of("/n_free") == [c for c in client.of("/n_free") if c[1] == RING_NODE]
