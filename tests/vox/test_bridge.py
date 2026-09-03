"""End to end against the mock: a browser-shaped client sets a value and sees it confirmed."""

import asyncio
import contextlib
import json
import time
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
