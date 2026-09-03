"""End to end against the mock: a browser-shaped client sets a value and sees it confirmed."""

import asyncio
import contextlib
import json
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
