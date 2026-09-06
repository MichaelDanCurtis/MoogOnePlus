"""End to end against the mock: a browser-shaped client sets a value and sees it confirmed."""

import asyncio
import contextlib
import json
import time
import urllib.error
import urllib.request

import pytest
import websockets.asyncio.client as wsc

from moogone.mock.server import MockScsynth
from moogone.vox.bridge import Bridge
from moogone.vox.fx import nodes_from_tree
from moogone.vox.meters import MockMeterSource
from moogone.vox.mpe import NoteEvent

METERS = {"/a/stat/mainl", "/a/stat/mainr", "/a/stat/send1", "/a/stat/send2"}


async def _recv_type(ws, kind, timeout=3.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError(f"never received {kind}")
        msg = json.loads(await asyncio.wait_for(ws.recv(), remaining))
        if msg["type"] == kind:
            return msg


@pytest.fixture
def mock():
    with MockScsynth() as m:
        yield m


async def _serve(bridge):
    task = asyncio.create_task(bridge.serve("127.0.0.1", 0))
    for _ in range(100):
        if bridge.port:
            return task
        await asyncio.sleep(0.02)
    task.cancel()
    raise AssertionError("bridge did not start")


async def _stop(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_fx_list_then_set_then_confirmed(mock):
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "fx.list"}))
            tree = await _recv_type(ws, "fx.tree")
            expected = {n.node_id for n in nodes_from_tree(mock.node_tree)}
            assert {n["id"] for n in tree["nodes"]} == expected
            node = next(
                n
                for n in tree["nodes"]
                if any(c["kind"] == "range" for c in n["controls"].values())
            )
            ctl = next(k for k, c in node["controls"].items() if c["kind"] == "range")
            assert node["controls"][ctl]["badge"]["state"] == "live"

            await ws.send(
                json.dumps({"type": "fx.set", "node": node["id"], "ctl": ctl, "value": 0.61})
            )
            sent = await _recv_type(ws, "fx.value")
            assert sent["state"] == "sent"
            conf = await _recv_type(ws, "fx.value")
            assert conf["state"] == "confirmed"
            assert conf["value"] == pytest.approx(0.61, abs=1e-4)
    finally:
        await _stop(task)


async def test_set_is_unconfirmed_not_confirmed_when_the_server_goes_silent(mock):
    """The bridge must never report 'confirmed' on the strength of having sent."""
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "fx.list"}))
            tree = await _recv_type(ws, "fx.tree")
            node = next(
                n
                for n in tree["nodes"]
                if any(c["kind"] == "range" for c in n["controls"].values())
            )
            ctl = next(k for k, c in node["controls"].items() if c["kind"] == "range")
            mock.silent = True
            await ws.send(
                json.dumps({"type": "fx.set", "node": node["id"], "ctl": ctl, "value": 0.33})
            )
            sent = await _recv_type(ws, "fx.value", timeout=6.0)
            assert sent["state"] == "sent"
            second = await _recv_type(ws, "fx.value", timeout=6.0)
            assert second["state"] == "unconfirmed"
    finally:
        await _stop(task)


async def test_malformed_message_returns_error_not_disconnect(mock):
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send("{not json")
            err = await _recv_type(ws, "error")
            assert "JSON" in err["what"]
            await ws.send(json.dumps({"type": "ping"}))
            await _recv_type(ws, "pong")  # still connected
    finally:
        await _stop(task)


async def test_serves_the_ui_over_http(mock):
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        body = await asyncio.to_thread(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{b.port}/", timeout=3).read()
        )
        assert b"<title>" in body
    finally:
        await _stop(task)


async def test_meters_are_broadcast_with_their_badge(mock):
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=0.05)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            m = await _recv_type(ws, "meters")
            assert set(m["values"]) == METERS
            assert m["badge"]["state"] == "untested"  # the mock must not wear 'live'
    finally:
        await _stop(task)


async def test_blocked_route_is_created_but_flagged(mock):
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(
                json.dumps({"type": "route.add", "src": "mpe.pressure[0]", "dst": "voice.0.cutoff"})
            )
            routes = await _recv_type(ws, "routes")
            assert routes["routes"][0]["dst"] == "voice.0.cutoff"
            badge = await _recv_type(ws, "badge")
            assert badge["state"] == "blocked" and "cutoff" in badge["why"].lower()
    finally:
        await _stop(task)


async def test_routed_write_is_broadcast_so_the_ui_can_see_it_move(mock):
    """Found in the browser: the router wrote to the mock but the UI never heard, so the
    control sat frozen while the server moved. A routed write must surface as 'sent'."""
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=0.05)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "fx.list"}))
            tree = await _recv_type(ws, "fx.tree")
            node = next(
                n
                for n in tree["nodes"]
                if any(c["kind"] == "range" for c in n["controls"].values())
            )
            ctl = next(k for k, c in node["controls"].items() if c["kind"] == "range")
            dst = f"sc.{node['id']}.{ctl}"
            await ws.send(json.dumps({"type": "route.add", "src": "meter.mainl", "dst": dst}))
            await _recv_type(ws, "routes")
            moved = await _recv_type(ws, "fx.value", timeout=4.0)
            assert moved["state"] == "sent"
            assert moved["node"] == node["id"] and moved["ctl"] == ctl
    finally:
        await _stop(task)


class TestMpeSources:
    """Found by running it: a released note must not leave routed destinations pinned."""

    def _bridge(self, mock):
        return Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)

    def test_pressure_falls_to_zero_on_note_off_not_frozen(self, mock):
        b = self._bridge(mock)
        b.apply_mpe_event(NoteEvent("on", 0, 60, 0.8, 0))
        b.apply_mpe_event(NoteEvent("pressure", 0, 60, 1.0, 0))
        assert b.sources["mpe.pressure[0]"] == 1.0
        b.apply_mpe_event(NoteEvent("off", 0, 60, 0.0, 0))
        # Not absent — absent means the router skips it and the destination stays at 1.0.
        assert "mpe.pressure[0]" in b.sources
        assert b.sources["mpe.pressure[0]"] == 0.0

    def test_bend_recentres_rather_than_zeroing(self, mock):
        b = self._bridge(mock)
        b.apply_mpe_event(NoteEvent("bend", 3, 64, 1.0, 4))
        assert b.sources["mpe.bend[3]"] == 1.0  # +1 maps to the top of 0..1
        b.apply_mpe_event(NoteEvent("off", 3, 64, 0.0, 4))
        assert b.sources["mpe.bend[3]"] == 0.5  # centre, not zero

    def test_bend_is_remapped_into_the_unit_interval(self, mock):
        b = self._bridge(mock)
        b.apply_mpe_event(NoteEvent("bend", 1, 60, -1.0, 2))
        assert b.sources["mpe.bend[1]"] == 0.0
        b.apply_mpe_event(NoteEvent("bend", 1, 60, 0.0, 2))
        assert b.sources["mpe.bend[1]"] == 0.5

    def test_release_only_touches_that_voice(self, mock):
        b = self._bridge(mock)
        b.apply_mpe_event(NoteEvent("pressure", 0, 60, 0.9, 0))
        b.apply_mpe_event(NoteEvent("pressure", 1, 64, 0.7, 0))
        b.apply_mpe_event(NoteEvent("off", 0, 60, 0.0, 0))
        assert b.sources["mpe.pressure[0]"] == 0.0
        assert b.sources["mpe.pressure[1]"] == 0.7


async def test_midi_note_without_midi_out_is_an_error_not_silence(mock):
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "midi.note", "note": 60, "on": True}))
            err = await _recv_type(ws, "error")
            assert "MIDI out" in err["what"]
    finally:
        await _stop(task)


class TestVectorAndAiDispatch:
    """The bridge-side halves of the two new panels."""

    def _bridge(self, mock):
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        b.fx.refresh()  # load the mock tree so corners have something to snapshot
        return b

    def test_storing_a_corner_snapshots_writable_controls_only(self, mock):
        b = self._bridge(mock)
        out = b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        assert out[0]["type"] == "vector.state"
        assert out[0]["corners"]["A"] > 0
        assert all(p.startswith("sc.") for p in b.vector.corners["A"])
        writable = {
            f"sc.{n.node_id}.{c.name}"
            for n in b.fx.nodes
            for c in n.controls
            if c.kind != "readonly"
        }
        assert set(b.vector.corners["A"]) == writable

    def test_storing_a_corner_reads_the_tree_fresh_so_no_refresh_is_needed_first(self, mock):
        """The snapshot re-reads under the lock rather than trusting the cache — which
        also means a corner can be stored the moment you connect."""
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        out = b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        assert out[0]["type"] == "vector.state"
        assert out[0]["corners"]["A"] > 0

    def test_storing_a_corner_errors_when_the_tree_cannot_be_read(self, mock):
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        b.fx.refresh()
        mock.silent = True
        out = b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        assert out[0]["type"] == "error" and "snapshot" in out[0]["what"]

    def test_a_corner_captures_the_value_just_set_not_a_stale_cache(self, mock):
        """The race that put 0.413 in corner C in the browser: fx.set and vector.corner
        arrive as separate messages on separate threads, and the snapshot used to read
        the cache unlocked while confirm-refresh was rewriting it."""
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        b.fx.refresh()
        node = b.fx.nodes[0]
        ctl = next(c for c in node.controls if c.kind == "range")
        key = f"sc.{node.node_id}.{ctl.name}"
        for name, value in (("A", 0.05), ("B", 0.85), ("C", 0.95), ("D", 0.30)):
            b.dispatch({"type": "fx.set", "node": node.node_id, "ctl": ctl.name, "value": value})
            b.dispatch({"type": "vector.corner", "name": name, "action": "store"})
            assert b.vector.corners[name][key] == pytest.approx(value, abs=1e-4), name

    def test_clear_empties_a_corner(self, mock):
        b = self._bridge(mock)
        b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        out = b.dispatch({"type": "vector.corner", "name": "A", "action": "clear"})
        assert out[0]["corners"]["A"] == 0

    def test_bad_corner_name_is_an_error_not_a_crash(self, mock):
        out = self._bridge(mock).dispatch({"type": "vector.corner", "name": "Z", "action": "store"})
        assert out[0]["type"] == "error" and "A, B, C, D" in out[0]["what"]

    def test_moving_writes_the_blend_and_reports_it(self, mock):
        b = self._bridge(mock)
        b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        out = b.dispatch({"type": "vector.move", "x": 0.5, "y": 0.5})
        assert out[0]["type"] == "vector.state"
        assert any(m["type"] == "fx.value" and m["state"] == "sent" for m in out[1:])

    def test_moving_by_hand_stops_the_orbit(self, mock):
        """Otherwise the LFO fights your finger."""
        b = self._bridge(mock)
        b.dispatch({"type": "vector.mode", "mode": "orbit"})
        b.dispatch({"type": "vector.move", "x": 0.2, "y": 0.3})
        assert b.vector.mode == "manual"

    def test_orbit_params_round_trip(self, mock):
        """Running is now a mode on the engine, not a flag on the orbit shape."""
        b = self._bridge(mock)
        out = b.dispatch({"type": "vector.orbit", "rate_x": 0.4, "depth": 0.5})
        o = out[0]["orbit"]
        assert o["rate_x"] == 0.4 and o["depth"] == 0.5
        assert "running" not in o
        assert b.dispatch({"type": "vector.mode", "mode": "orbit"})[0]["mode"] == "orbit"

    def test_surface_returns_a_grid(self, mock):
        b = self._bridge(mock)
        b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        path = b.vector.paths()[0]
        out = b.dispatch({"type": "vector.surface", "path": path})
        assert out[0]["type"] == "vector.surface"
        assert len(out[0]["grid"]) == 17 and len(out[0]["grid"][0]) == 17

    def test_ai_list_reports_installed_providers(self, mock):
        out = self._bridge(mock).dispatch({"type": "ai.list"})
        assert out[0]["type"] == "ai.providers"
        assert isinstance(out[0]["providers"], list)

    def test_ai_ask_with_an_unknown_provider_is_an_error(self, mock):
        out = self._bridge(mock).dispatch(
            {"type": "ai.ask", "provider": "nope", "request": "warmer"}
        )
        assert out[0]["type"] == "error" and "not installed" in out[0]["what"]

    def test_ai_apply_revalidates_and_refuses_a_hallucinated_node(self, mock):
        """The UI is not trusted either — apply re-checks against the live tree."""
        b = self._bridge(mock)
        out = b.dispatch(
            {"type": "ai.apply", "changes": [{"node": 999999, "ctl": "mix", "value": 0.5}]}
        )
        assert all(m["type"] == "error" for m in out)
        assert "999999" in out[0]["what"]

    def test_ai_apply_writes_a_valid_change(self, mock):
        b = self._bridge(mock)
        node = b.fx.nodes[0]
        ctl = next(c for c in node.controls if c.kind == "range")
        out = b.dispatch(
            {
                "type": "ai.apply",
                "changes": [{"node": node.node_id, "ctl": ctl.name, "value": 0.42}],
            }
        )
        states = [m["state"] for m in out if m["type"] == "fx.value"]
        assert "sent" in states and "confirmed" in states

    def test_ai_apply_rejects_a_non_list(self, mock):
        out = self._bridge(mock).dispatch({"type": "ai.apply", "changes": "everything"})
        assert out[0]["type"] == "error" and "must be a list" in out[0]["what"]


class TestVectorMotion:
    """Motion — the vector envelope, on a free or tempo-locked clock."""

    def _bridge(self, mock):
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        b.fx.refresh()
        b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        return b

    def test_mode_switches_and_reports(self, mock):
        b = self._bridge(mock)
        out = b.dispatch({"type": "vector.mode", "mode": "orbit"})
        assert out[0]["mode"] == "orbit"
        assert b.vector.moving() is True

    def test_bad_mode_is_an_error(self, mock):
        out = self._bridge(mock).dispatch({"type": "vector.mode", "mode": "wormhole"})
        assert out[0]["type"] == "error" and "manual, orbit, motion" in out[0]["what"]

    def test_record_start_then_stop_with_a_drag_makes_a_path(self, mock):
        b = self._bridge(mock)
        b.dispatch({"type": "vector.record", "action": "start"})
        assert b.vector.recording is True
        for x, y in ((0.1, 0.1), (0.9, 0.2), (0.8, 0.9)):
            b.dispatch({"type": "vector.move", "x": x, "y": y})
            time.sleep(0.01)  # the recorder needs distinct timestamps
        out = b.dispatch({"type": "vector.record", "action": "stop"})
        assert b.vector.recording is False
        assert len(out[0]["motion"]["points"]) >= 2
        assert out[0]["mode"] == "motion"  # stopping arms playback

    def test_recording_a_drag_does_not_knock_the_mode_back_to_manual(self, mock):
        """vector.move normally seizes manual control; while armed it must not."""
        b = self._bridge(mock)
        b.dispatch({"type": "vector.mode", "mode": "orbit"})
        b.dispatch({"type": "vector.record", "action": "start"})
        b.dispatch({"type": "vector.move", "x": 0.3, "y": 0.4})
        assert b.vector.mode == "orbit"

    def test_stopping_with_nothing_recorded_is_an_error_not_an_empty_path(self, mock):
        b = self._bridge(mock)
        b.dispatch({"type": "vector.record", "action": "start"})
        out = b.dispatch({"type": "vector.record", "action": "stop"})
        assert out[0]["type"] == "error" and "nothing recorded" in out[0]["what"]

    def test_clock_switches_to_tempo_and_reports_seconds_per_cycle(self, mock):
        b = self._bridge(mock)
        out = b.dispatch({"type": "vector.clock", "mode": "tempo", "bpm": 120, "beats": 4})
        assert out[0]["clock"]["mode"] == "tempo"
        assert out[0]["clock"]["seconds_per_cycle"] == pytest.approx(2.0)

    def test_clock_rejects_an_unknown_mode(self, mock):
        out = self._bridge(mock).dispatch({"type": "vector.clock", "mode": "moon-phase"})
        assert out[0]["type"] == "error" and "free, tempo" in out[0]["what"]

    def test_loop_mode_round_trips_and_rejects_nonsense(self, mock):
        b = self._bridge(mock)
        assert (
            b.dispatch({"type": "vector.clock", "loop": "pingpong"})[0]["motion"]["loop"]
            == "pingpong"
        )
        out = b.dispatch({"type": "vector.clock", "loop": "boomerang"})
        assert out[0]["type"] == "error"

    def test_manual_move_stops_the_orbit(self, mock):
        b = self._bridge(mock)
        b.dispatch({"type": "vector.mode", "mode": "orbit"})
        b.dispatch({"type": "vector.move", "x": 0.2, "y": 0.2})
        assert b.vector.mode == "manual"


async def test_moving_vector_broadcasts_its_position(mock):
    """Found by running it: controls swept correctly while the pad sat frozen, because
    vector.state is only sent in reply to a command."""
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "fx.list"}))
            await _recv_type(ws, "fx.tree")
            await ws.send(json.dumps({"type": "vector.corner", "name": "A", "action": "store"}))
            await _recv_type(ws, "vector.state")
            await ws.send(json.dumps({"type": "vector.mode", "mode": "orbit"}))
            await _recv_type(ws, "vector.state")
            a = await _recv_type(ws, "vector.pos", timeout=3.0)
            b2 = await _recv_type(ws, "vector.pos", timeout=3.0)
            assert (a["x"], a["y"]) != (b2["x"], b2["y"]), "the dot must actually move"
    finally:
        await _stop(task)


async def test_position_is_not_broadcast_while_the_vector_is_manual(mock):
    """20 Hz of traffic for a dot nobody is moving is waste."""
    b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
    task = await _serve(b)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{b.port}") as ws:
            await ws.send(json.dumps({"type": "ping"}))
            await _recv_type(ws, "pong")
            # Drain for a while; nothing of this type should ever arrive.
            seen = []
            with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
                while True:
                    raw = await asyncio.wait_for(ws.recv(), 0.8)
                    seen.append(json.loads(raw)["type"])
            assert "vector.pos" not in seen
    finally:
        await _stop(task)


class TestApplyExactness:
    """ai.apply must land the proposed value exactly. A browser session once showed every
    value landing about halfway between its prior and the proposal; that was never
    reproduced, so this guards the property rather than a known mechanism."""

    def _bridge(self, mock):
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        b.fx.refresh()
        return b

    def test_every_applied_change_lands_exactly(self, mock):
        b = self._bridge(mock)
        n0, n1 = b.fx.nodes[0], b.fx.nodes[1]
        wanted = [
            (n0.node_id, "time", 0.520),
            (n0.node_id, "feedback", 0.970),
            (n1.node_id, "size", 1.050),
            (n1.node_id, "damp", 0.280),
            (n1.node_id, "mix", 0.520),
        ]
        b.dispatch(
            {
                "type": "ai.apply",
                "changes": [{"node": n, "ctl": c, "value": v} for n, c, v in wanted],
            }
        )
        live = {(n.node_id, c.name): c.value for n in b.fx.refresh() for c in n.controls}
        for node, ctl, value in wanted:
            got = live[(node, ctl)]
            assert got == pytest.approx(value, abs=1e-4), (
                f"{ctl}: wanted {value}, got {got} (fraction {(got - value) / value:+.3f} off)"
            )


class TestVectorWriteChangeDetection:
    def _ready(self, mock):
        b = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)
        b.fx.refresh()
        b.dispatch({"type": "vector.corner", "name": "A", "action": "store"})
        return b

    def test_a_stationary_vector_writes_nothing_the_second_time(self, mock):
        """It used to re-send all ten controls every tick — 100 identical /n_set a second."""
        b = self._ready(mock)
        first = b._vector_write()
        assert first, "the first pass must actually write"
        assert b._vector_write() == [], "an unmoved vector must write nothing"

    def test_it_writes_again_once_the_position_moves(self, mock):
        b = self._ready(mock)
        # The corners must actually differ, or moving between them changes nothing and
        # writing nothing is the correct answer.
        node = b.fx.nodes[0]
        ctl = next(c for c in node.controls if c.kind == "range")
        b.dispatch({"type": "fx.set", "node": node.node_id, "ctl": ctl.name, "value": 0.9})
        b.dispatch({"type": "vector.corner", "name": "C", "action": "store"})
        b.vector.move(0.0, 0.0)
        b._vector_write()
        b.vector.move(1.0, 1.0)
        assert b._vector_write() != [], "a moved vector must write the new blend"

    def test_identical_corners_mean_nothing_to_write_however_far_you_move(self, mock):
        """Two corners holding the same values describe a flat blend; moving across it
        is not a change, and re-sending it every tick is what this guard prevents."""
        b = self._ready(mock)
        b.dispatch({"type": "vector.corner", "name": "C", "action": "store"})
        b.vector.move(0.0, 0.0)
        b._vector_write()
        b.vector.move(1.0, 1.0)
        assert b._vector_write() == []

    def test_an_external_write_lets_the_vector_re_assert_its_value(self, mock):
        """Otherwise a control someone else moved would stay moved, because the vector
        still believed it had already sent that value."""
        b = self._ready(mock)
        b._vector_write()
        node = b.fx.nodes[0]
        ctl = next(c for c in node.controls if c.kind == "range")
        path = f"sc.{node.node_id}.{ctl.name}"
        b.dispatch({"type": "fx.set", "node": node.node_id, "ctl": ctl.name, "value": 0.123})
        assert path not in b._vector_last
        assert any(m.get("ctl") == ctl.name for m in b._vector_write())


class TestPatcherDispatch:
    def _bridge(self, mock):
        return Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), meter_period=10.0)

    def _good(self):
        return {
            "name": "simple",
            "nodes": [
                {"id": "s", "kind": "Saw", "params": {"freq": 110}},
                {"id": "f", "kind": "MoogFF"},
                {"id": "o", "kind": "Out"},
            ],
            "cables": [
                {"src": "s", "dst": "f", "port": "in"},
                {"src": "f", "dst": "o", "port": "channelsArray"},
            ],
        }

    def test_catalog_lists_the_palette(self, mock):
        out = self._bridge(mock).dispatch({"type": "patch.catalog"})
        assert out[0]["type"] == "patch.ugens"
        names = {u["name"] for u in out[0]["ugens"]}
        assert {"MoogFF", "CombC", "Out", "control", "op.mul"} <= names

    def test_a_valid_patch_has_no_problems(self, mock):
        out = self._bridge(mock).dispatch({"type": "patch.validate", "patch": self._good()})
        assert out[0]["problems"] == []

    def test_source_is_generated_for_a_valid_patch(self, mock):
        out = self._bridge(mock).dispatch({"type": "patch.source", "patch": self._good()})
        assert out[0]["type"] == "patch.scd"
        assert "SynthDef(\\simple" in out[0]["source"]
        assert "MoogFF.ar(x_s" in out[0]["source"]

    def test_an_invalid_patch_returns_problems_and_no_source(self, mock):
        """It must not emit half-formed SuperCollider that fails on a server instead."""
        bad = self._good()
        bad["cables"] = []
        out = self._bridge(mock).dispatch({"type": "patch.source", "patch": bad})
        assert out[0]["source"] == ""
        assert any("must be connected" in m for m in out[0]["problems"])

    def test_a_malformed_patch_object_is_an_error_not_a_crash(self, mock):
        out = self._bridge(mock).dispatch({"type": "patch.validate", "patch": {"nodes": "lots"}})
        assert out[0]["type"] == "error" and "malformed patch" in out[0]["what"]

    def test_a_patch_that_would_loop_is_refused_with_the_path(self, mock):
        bad = self._good()
        bad["cables"].append({"src": "f", "dst": "f", "port": "in"})
        out = self._bridge(mock).dispatch({"type": "patch.source", "patch": bad})
        assert out[0]["source"] == ""
        assert any("feedback loop" in m for m in out[0]["problems"])


async def test_vector_state_is_sent_on_connect(mock):
    """A reload must not show empty corners while the bridge holds full ones.

    The corners live in the engine, not the page. Sending only `status` on connect
    meant every refresh showed four empty corners and an empty landscape, while the
    bridge still held every snapshot — the same class of fault as the stale landscape
    and the frozen routed writes.
    """
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    bridge.vector.corners["A"] = {"sc.1.mix": 0.25}
    bridge.vector.corners["B"] = {"sc.1.mix": 0.75}
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            state = await _recv_type(ws, "vector.state")
        assert state["corners"] == {"A": 1, "B": 1, "C": 0, "D": 0}
        assert state["spans"]["sc.1.mix"] == [0.25, 0.75]
        assert state["duplicates"] == {}, "different values are not duplicates"
    finally:
        await _stop(task)


async def test_connect_state_reports_duplicate_corners(mock):
    """Four identical snapshots make every landscape flat; the state has to say so."""
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    for name in "ABCD":
        bridge.vector.corners[name] = {"sc.1.mix": 0.5}
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            state = await _recv_type(ws, "vector.state")
        assert state["duplicates"] == {"B": "A", "C": "A", "D": "A"}
        assert state["spans"]["sc.1.mix"] == [0.5, 0.5], "a flat control, reported as flat"
    finally:
        await _stop(task)


async def test_the_learned_parameter_map_is_sent_on_connect(mock):
    """Learned names live in the bridge, so a reload must not show an empty table."""
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    bridge.param_map.learn(412, "cutoff")
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            m = await _recv_type(ws, "learn.map")
        assert m["names"]["412"] == "cutoff"
        assert m["names"]["358"] == "master volume", "the known ids are there too"
    finally:
        await _stop(task)


async def test_a_learn_pass_that_sees_nothing_records_nothing(mock):
    """Arming and disarming without moving a control must not name a parameter."""
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    before = dict(bridge.param_map.names)
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            await ws.send(json.dumps({"type": "learn.begin", "label": "nothing"}))
            await ws.send(json.dumps({"type": "learn.finish"}))
            r = await _recv_type(ws, "learn.result")
        assert r["param"] is None
        assert r["reason"] == "nothing moved"
        assert bridge.param_map.names == before
    finally:
        await _stop(task)


async def test_an_unusable_learn_label_is_an_error_not_a_crash(mock):
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            await ws.send(json.dumps({"type": "learn.begin", "label": ""}))
            e = await _recv_type(ws, "error")
        assert e["where"] == "learn.begin"
    finally:
        await _stop(task)


async def test_a_static_image_is_served_with_its_real_length(mock, tmp_path):
    """A 200 of zero bytes is worse than a 404: it looks like the file is empty.

    Two ways this fails quietly. `respond()` sets Content-Length from the text it is
    given, so assigning `.body` afterwards ships a correct-looking empty 200. And
    `Headers` is a multidict, so setting Content-Length without deleting the old one
    sends it twice — a malformed response the client does not reject, it hangs on.
    """
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>vox</h1>")
    blob = b"\x89PNG\r\n\x1a\n" + b"pretend pixels" * 40
    (static / "panel.png").write_bytes(blob)

    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), static_dir=static)
    task = await _serve(bridge)
    try:
        # to_thread, always: a blocking urlopen on this loop starves the server that
        # is meant to answer it, and the test times out against its own event loop.
        def fetch():
            with urllib.request.urlopen(
                f"http://127.0.0.1:{bridge.port}/panel.png", timeout=5
            ) as r:
                return r.read(), dict(r.headers)

        body, headers = await asyncio.to_thread(fetch)
        assert body == blob
        assert headers["Content-Type"] == "image/png"
        assert int(headers["Content-Length"]) == len(blob)
    finally:
        await _stop(task)


async def test_static_serving_refuses_anything_not_allowlisted(mock, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>vox</h1>")
    (static / "secrets.txt").write_text("not for the network")
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), static_dir=static)
    task = await _serve(bridge)

    def status_of(path):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{bridge.port}{path}", timeout=5)
            return 200
        except urllib.error.HTTPError as exc:
            return exc.code

    try:
        for path in ("/secrets.txt", "/index.py", "/etc/passwd", "/missing.png"):
            assert await asyncio.to_thread(status_of, path) == 404, path
    finally:
        await _stop(task)


async def test_a_traversal_cannot_escape_the_static_directory(mock, tmp_path):
    """Only the final path component is used, so there is nothing to escape with."""
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<h1>vox</h1>")
    (tmp_path / "outside.png").write_bytes(b"\x89PNG\r\n\x1a\nnope")
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource(), static_dir=static)
    task = await _serve(bridge)

    def fetch(path):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{bridge.port}{path}", timeout=5
            ) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, b""

    try:
        # urllib normalises ".." before sending, so the server also sees the bare
        # name; the guarantee is that either spelling reaches nothing outside.
        for path in ("/../outside.png", "/%2e%2e/outside.png", "/outside.png"):
            code, body = await asyncio.to_thread(fetch, path)
            assert code == 404, f"{path} returned {code}"
            assert b"nope" not in body
    finally:
        await _stop(task)


async def test_live_sampler_without_a_panel_host_is_an_error_not_a_crash(mock):
    """Live triggering needs the device host, which only --panel supplies.

    It also runs from a worker thread, where asyncio.get_running_loop() raises
    RuntimeError — which is not a SamplerError and so escaped the handler entirely,
    surfacing as a reply with no fields rather than a message saying what was wrong.
    """
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            await ws.send(json.dumps({"type": "sampler.live", "on": True}))
            e = await _recv_type(ws, "error")
        assert e["where"] == "sampler.live"
        assert "--panel" in e["what"]
    finally:
        await _stop(task)


async def test_sampler_state_is_sent_on_connect(mock):
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            m = await _recv_type(ws, "sampler.state")
        assert m["samples"] == [] and m["live"] is False and m["spread"] is None
    finally:
        await _stop(task)


async def test_assigning_an_unknown_sample_is_refused(mock):
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            await ws.send(json.dumps({"type": "sampler.assign", "note": 60, "name": "ghost"}))
            e = await _recv_type(ws, "error")
        assert "ghost" in e["what"]
    finally:
        await _stop(task)


class TestSamplerUpload:
    """A dropped file arrives over the socket. The browser is not the authority on
    what may be written here, so the name and the contents are both checked."""

    @staticmethod
    async def upload(bridge, name, data, root=60):
        """Upload one file and return the reply to THAT, not the connect greeting.

        The bridge sends status, vector.state, learn.map and sampler.state as soon as
        a client connects. Reading the first sampler.state that arrives returns the
        greeting and calls every rejection a success.
        """
        import base64

        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            # Drain the greeting: read until the socket goes quiet.
            while True:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.4)
                except TimeoutError:
                    break
            await ws.send(json.dumps({
                "type": "sampler.upload",
                "name": name,
                "data": base64.b64encode(data).decode(),
                "root": root,
            }))
            loop = asyncio.get_event_loop()
            deadline = loop.time() + 4.0
            while loop.time() < deadline:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=4.0))
                if m["type"] in ("error", "sampler.state"):
                    return m
        raise AssertionError("no reply to the upload")

    async def test_a_traversal_name_is_refused(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            m = await self.upload(bridge, "../../etc/passwd.wav", b"RIFF" + b"\x00" * 40)
            assert m["type"] == "error"
        finally:
            await _stop(task)

    async def test_a_non_audio_extension_is_refused(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            m = await self.upload(bridge, "payload.sh", b"RIFF" + b"\x00" * 40)
            assert m["type"] == "error" and "wav" in m["what"].lower()
        finally:
            await _stop(task)

    async def test_something_that_is_not_a_wav_is_refused(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            m = await self.upload(bridge, "trick.wav", b"MZ\x90\x00not audio at all")
            assert m["type"] == "error" and "begin like" in m["what"]
        finally:
            await _stop(task)

    async def test_an_empty_file_is_refused(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            m = await self.upload(bridge, "nothing.wav", b"")
            assert m["type"] == "error" and "empty" in m["what"]
        finally:
            await _stop(task)

    async def test_bad_base64_is_reported_not_crashed_on(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
                await ws.send(json.dumps({"type": "sampler.upload", "name": "x.wav",
                                          "data": "!!!not base64!!!", "root": 60}))
                m = await _recv_type(ws, "error")
            assert "base64" in m["what"]
        finally:
            await _stop(task)


class TestPatchRun:
    """Compiling a canvas and running it inside the instrument."""

    @staticmethod
    def tone_patch(bus=0):
        return {
            "name": "voxTone",
            "nodes": [
                {"id": "s", "kind": "SinOsc", "rate": "audio", "params": {"freq": 300.0}},
                {"id": "o", "kind": "Out", "rate": "audio", "params": {"bus": float(bus)}},
            ],
            "cables": [{"src": "s", "dst": "o", "port": "channelsArray", "outlet": 0}],
        }

    @staticmethod
    async def ask(bridge, message):
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            while True:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=0.4)
                except TimeoutError:
                    break
            await ws.send(json.dumps(message))
            return await _recv_type(ws, "patch.running", timeout=90.0)

    async def test_an_invalid_graph_is_refused_before_anything_is_compiled(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            broken = self.tone_patch()
            broken["cables"] = []            # Out's channelsArray now unconnected
            m = await self.ask(bridge, {"type": "patch.run", "patch": broken})
            assert m["running"] is False
            assert any("channelsArray" in p for p in m["problems"])
        finally:
            await _stop(task)

    async def test_free_is_safe_when_nothing_is_running(self, mock):
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            m = await self.ask(bridge, {"type": "patch.free"})
            assert m["running"] is False
        finally:
            await _stop(task)

    async def test_a_valid_graph_compiles_and_runs(self, mock):
        sc = pytest.importorskip("moogone.synthdef")
        if not sc.available():
            pytest.skip("no sclang on this machine")
        bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
        task = await _serve(bridge)
        try:
            m = await self.ask(bridge, {"type": "patch.run", "patch": self.tone_patch()})
            assert m["problems"] == []
            assert m["running"] is True
            assert m["name"].startswith("voxPatch")
            # And it actually reached the (mock) server as a new synth.
            assert any(msg.address == "/s_new" for msg in mock.received)
        finally:
            await _stop(task)


async def test_midi_trigger_mode_needs_a_midi_input(mock):
    """The low-latency path is only available when there is something to listen to."""
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            await ws.send(json.dumps({"type": "sampler.mode", "mode": "midi"}))
            e = await _recv_type(ws, "error")
        assert "--midi-in" in e["what"]
    finally:
        await _stop(task)


async def test_an_unknown_trigger_mode_is_refused(mock):
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            await ws.send(json.dumps({"type": "sampler.mode", "mode": "telepathy"}))
            e = await _recv_type(ws, "error")
        assert "telepathy" in e["what"]
    finally:
        await _stop(task)


async def test_sampler_state_reports_its_trigger_mode(mock):
    bridge = Bridge("127.0.0.1", mock.port, meters=MockMeterSource())
    task = await _serve(bridge)
    try:
        async with wsc.connect(f"ws://127.0.0.1:{bridge.port}/") as ws:
            m = await _recv_type(ws, "sampler.state")
        assert m["mode"] == "keys"
    finally:
        await _stop(task)


def test_the_hud_redraw_is_throttled(monkeypatch):
    """A frame is ~400 kB over SSH. One per note of a chord is a burst, and bursts
    take this instrument off the network hard enough to need a power cycle
    (docs/MOOG-ONE-INTERNALS.md section 8c). The screen must follow the playing
    without becoming the thing that kills it.
    """
    from moogone.vox.bridge import Bridge

    drawn = []

    class Stub(Bridge):
        def _fm_hud(self, on: bool) -> None:
            drawn.append(on)
            import time as _t

            self._fm_hud_drawn = _t.monotonic()

    bridge = Stub.__new__(Stub)
    bridge._fm_hud_on = True
    bridge._fm_hud_drawn = 0.0

    for _ in range(12):          # a fast chord
        bridge._fm_hud_follow()
    assert len(drawn) == 1, f"redrew {len(drawn)} times for one burst of notes"


def test_the_hud_does_not_redraw_when_it_is_not_showing():
    from moogone.vox.bridge import Bridge

    drawn = []

    class Stub(Bridge):
        def _fm_hud(self, on: bool) -> None:
            drawn.append(on)

    bridge = Stub.__new__(Stub)
    bridge._fm_hud_on = False
    bridge._fm_hud_drawn = 0.0
    bridge._fm_hud_follow()
    assert drawn == [], "must not touch the instrument's screen when hidden"
