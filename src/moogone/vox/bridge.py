"""The bridge: one process that the UI talks to and that talks to the instrument.

Browsers cannot send UDP, so this is where OSC lives. It serves the UI over plain HTTP on
the same port it speaks WebSocket on, so an iPad on the LAN needs one URL and nothing
else.

Everything that touches ``scsynth`` runs in a worker thread (the client is blocking) and
under one lock, because two confirms in flight on one UDP socket would read each other's
replies.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import pathlib
import queue
import threading
import time
from http import HTTPStatus
from typing import ClassVar

from websockets.asyncio.server import serve

from ..sc.client import ScClient, ScError, ScTimeout
from ..transport.udp import UdpTransport
from .destinations import Dispatcher, MidiCC, MidiNote, RawOsc, ScParam, VoiceParam
from .fx import FxWorkbench
from .meters import MeterSource, MockMeterSource, SshMeterSource
from .mpe import MpeDecoder, ZoneConfig
from .protocol import LIVE, ProtocolError, decode, encode
from .router import Route, Router

STATIC = pathlib.Path(__file__).parent / "static"
_SC_ERRORS = (ScError, ScTimeout, OSError)


class Bridge:
    def __init__(
        self,
        sc_host: str,
        sc_port: int,
        meters: MeterSource,
        midi_out=None,
        midi_in_name: str | None = None,
        static_dir: pathlib.Path | None = None,
        meter_period: float = 0.5,
        tick_hz: float = 100.0,
    ):
        self.port: int | None = None
        self._static = static_dir or STATIC
        self._meters = meters
        self._meter_period = meter_period
        self._tick = 1.0 / tick_hz
        self._clients: set = set()
        self._sc_ok = False
        self._sc_lock = threading.Lock()

        self._client = ScClient(UdpTransport(sc_host, sc_port))
        self.fx = FxWorkbench(self._client)
        self.mpe = MpeDecoder()
        self.router = Router()
        self.sources: dict[str, float] = {}

        self.dispatcher = Dispatcher()
        self.dispatcher.register("sc.", ScParam(self.fx))
        self.dispatcher.register("voice.", VoiceParam())
        self.dispatcher.register("osc.", RawOsc(self._client.transport.send))
        self._midi_out = midi_out
        if midi_out is not None:
            self.dispatcher.register("midi.cc.", MidiCC(midi_out))
            self.dispatcher.register("midi.note.", MidiNote(midi_out))
        self._midi_in_name = midi_in_name
        self._midi_q: queue.Queue = queue.Queue()

    # -- HTTP for the UI -----------------------------------------------------
    def _http(self, connection, request):
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return None
        path = request.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = (self._static / "index.html").read_bytes()
            resp = connection.respond(HTTPStatus.OK, body.decode("utf-8"))
            resp.headers["Content-Type"] = "text/html; charset=utf-8"
            return resp
        return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")

    # -- lifecycle -----------------------------------------------------------
    async def serve(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        async with serve(self.handle, host, port, process_request=self._http) as server:
            self.port = server.sockets[0].getsockname()[1]
            loops = [
                asyncio.create_task(self._meter_loop()),
                asyncio.create_task(self._router_loop()),
            ]
            if self._midi_in_name:
                loops.append(asyncio.create_task(self._midi_loop()))
            try:
                await server.serve_forever()
            finally:
                for t in loops:
                    t.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await t

    async def handle(self, ws) -> None:
        self._clients.add(ws)
        try:
            await ws.send(encode(self._status()))
            async for text in ws:
                try:
                    msg = decode(text)
                except ProtocolError as exc:
                    await ws.send(encode({"type": "error", "where": "protocol", "what": str(exc)}))
                    continue
                for out in await asyncio.to_thread(self._safe_dispatch, msg):
                    await ws.send(encode(out))
        finally:
            self._clients.discard(ws)

    async def _broadcast(self, msg: dict) -> None:
        text = encode(msg)
        for ws in list(self._clients):
            with contextlib.suppress(Exception):
                await ws.send(text)

    # -- request dispatch (runs in a thread; scsynth I/O is blocking) --------
    def _safe_dispatch(self, msg: dict) -> list[dict]:
        try:
            return self.dispatch(msg)
        except Exception as exc:  # noqa: BLE001 — a bad request must not kill the socket
            return [{"type": "error", "where": msg.get("type", "?"), "what": str(exc)}]

    def dispatch(self, msg: dict) -> list[dict]:
        t = msg["type"]
        if t == "ping":
            return [{"type": "pong"}]
        if t == "fx.list":
            return [self._fx_tree()]
        if t == "fx.set":
            return self._fx_set(int(msg["node"]), str(msg["ctl"]), float(msg["value"]))
        if t == "route.add":
            return self._route_add(msg)
        if t == "route.remove":
            self.router.remove(str(msg["id"]))
            return [self._routes()]
        if t == "route.list":
            return [self._routes()]
        if t == "mpe.config":
            self.mpe = MpeDecoder(
                ZoneConfig(
                    str(msg["zone"]),
                    int(msg.get("members", 15)),
                    float(msg.get("bend_range", 48.0)),
                )
            )
            return [self._status()]
        if t == "midi.note":
            return self._midi_note(int(msg["note"]), bool(msg["on"]))
        return [{"type": "error", "where": "dispatch", "what": f"unhandled {t}"}]

    def _route_add(self, msg: dict) -> list[dict]:
        try:
            r = Route(
                str(msg.get("id", "")),
                str(msg["src"]),
                str(msg["dst"]),
                float(msg.get("lo", 0.0)),
                float(msg.get("hi", 1.0)),
                str(msg.get("curve", "lin")),
                float(msg.get("slew", 0.0)),
                bool(msg.get("invert", False)),
            )
        except ValueError as exc:
            return [{"type": "error", "where": "route.add", "what": str(exc)}]
        self.router.add(r)
        out = [self._routes()]
        if self._has_dest(r.dst):
            b = self.dispatcher.badge_for(r.dst)
            if b.state != "live":
                out.append({"type": "badge", "path": r.dst, **b.as_dict()})
        else:
            out.append(
                {
                    "type": "error",
                    "where": "route.add",
                    "what": f"no destination handles {r.dst!r}; route created but nothing will receive it",
                }
            )
        return out

    def _midi_note(self, note: int, on: bool) -> list[dict]:
        if not self._has_dest("midi.note."):
            return [{"type": "error", "where": "midi.note", "what": "no MIDI out configured"}]
        ok, badge = self.dispatcher.write(f"midi.note.{note}", 1.0 if on else 0.0)
        out = [{"type": "badge", "path": "midi.note", **badge.as_dict()}]
        if not ok:
            out.append({"type": "error", "where": "midi.note", "what": f"refused note {note}"})
        return out

    def _has_dest(self, path: str) -> bool:
        try:
            self.dispatcher.badge_for(path)
            return True
        except KeyError:
            return False

    def _fx_tree(self) -> dict:
        try:
            with self._sc_lock:
                nodes = self.fx.refresh()
            self._sc_ok = True
        except _SC_ERRORS as exc:
            self._sc_ok = False
            return {"type": "error", "where": "scsynth", "what": f"cannot read node tree: {exc}"}
        return {
            "type": "fx.tree",
            "nodes": [
                {
                    "id": n.node_id,
                    "defname": n.defname,
                    "controls": {
                        c.name: {
                            "value": c.value,
                            "lo": c.lo,
                            "hi": c.hi,
                            "kind": c.kind,
                            "badge": LIVE.as_dict(),
                        }
                        for c in n.controls
                    },
                }
                for n in nodes
            ],
        }

    def _fx_set(self, node: int, ctl: str, value: float) -> list[dict]:
        def val(state: str, v: float) -> dict:
            return {"type": "fx.value", "node": node, "ctl": ctl, "value": v, "state": state}

        try:
            with self._sc_lock:
                self.fx.set(node, ctl, value)
        except OSError as exc:
            return [{"type": "error", "where": "scsynth", "what": f"send failed: {exc}"}]
        out = [val("sent", value)]
        try:
            with self._sc_lock:
                ok, seen = self.fx.confirm(node, ctl, value)
        except _SC_ERRORS as exc:
            out.append(val("unconfirmed", value))
            out.append({"type": "error", "where": "scsynth", "what": f"confirm failed: {exc}"})
            return out
        out.append(val("confirmed" if ok else "unconfirmed", seen if seen is not None else value))
        return out

    def _routes(self) -> dict:
        return {"type": "routes", "routes": [r.__dict__ for r in self.router.routes()]}

    def _status(self) -> dict:
        return {
            "type": "status",
            "sc": self._sc_ok,
            "midi_in": bool(self._midi_in_name),
            "midi_out": self._midi_out is not None,
            "meters": self._meters.badge.as_dict(),
        }

    # -- background loops ----------------------------------------------------
    async def _meter_loop(self) -> None:
        while True:
            values = await asyncio.to_thread(self._meters.read)
            if values:
                for a, (lo, hi) in values.items():
                    self.sources[f"meter.{a.rsplit('/', 1)[-1]}"] = min(1.0, max(abs(lo), abs(hi)))
                await self._broadcast(
                    {
                        "type": "meters",
                        "values": {k: list(v) for k, v in values.items()},
                        "badge": self._meters.badge.as_dict(),
                    }
                )
            await asyncio.sleep(self._meter_period)

    async def _router_loop(self) -> None:
        last = time.monotonic()
        while True:
            now = time.monotonic()
            dt, last = now - last, now
            for dst, val in self.router.tick(self.sources, dt, now):
                if not self._has_dest(dst):
                    continue
                ok = await asyncio.to_thread(self._locked_write, dst, val)
                # A routed write the UI cannot see is a control that appears frozen while
                # the server moves. Broadcast it as *sent* — not confirmed: re-reading the
                # tree per rate-limited write would hammer scsynth for no musical gain.
                if ok and dst.startswith("sc."):
                    _, node, ctl = dst.split(".", 2)
                    await self._broadcast(
                        {
                            "type": "fx.value",
                            "node": int(node),
                            "ctl": ctl,
                            "value": val,
                            "state": "sent",
                        }
                    )
            await asyncio.sleep(self._tick)

    #: Where an expression source rests once the note is released. Bend arrives -1..1 and
    #: is remapped to 0..1, so its centre is 0.5.
    RELEASED: ClassVar[dict[str, float]] = {"pressure": 0.0, "slide": 0.0, "bend": 0.5}

    def apply_mpe_event(self, e) -> dict:
        """Fold one decoded event into ``sources`` and return the message for the UI.

        On note-off the expression sources are driven to their **rest** values rather than
        removed. Removing them looks tidier but freezes every routed destination at
        whatever it held when the finger lifted — caught by running it: delay feedback sat
        pinned at 1.000 after the chord released, which on a real delay is a runaway.
        """
        if e.kind == "off":
            for k, rest in self.RELEASED.items():
                self.sources[f"mpe.{k}[{e.voice}]"] = rest
        else:
            value = (e.value + 1.0) / 2.0 if e.kind == "bend" else e.value
            self.sources[f"mpe.{e.kind}[{e.voice}]"] = value
        return {
            "type": "mpe.event",
            "kind": e.kind,
            "voice": e.voice,
            "note": e.note,
            "value": e.value,
        }

    def _locked_write(self, dst: str, val: float) -> bool:
        with self._sc_lock:
            ok, _badge = self.dispatcher.write(dst, val)
        return ok

    async def _midi_loop(self) -> None:
        import rtmidi  # optional dependency; only needed when a port is named

        midi_in = rtmidi.MidiIn()
        names = midi_in.get_ports()
        idx = next((i for i, n in enumerate(names) if self._midi_in_name in n), None)
        if idx is None:
            await self._broadcast(
                {
                    "type": "error",
                    "where": "midi",
                    "what": f"no MIDI in matching {self._midi_in_name!r}; have {names}",
                }
            )
            return
        midi_in.ignore_types(sysex=True, timing=True, active_sense=True)
        midi_in.set_callback(lambda ev, _=None: self._midi_q.put(ev[0]))
        midi_in.open_port(idx)
        try:
            while True:
                try:
                    data = self._midi_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.002)
                    continue
                for e in self.mpe.feed(data):
                    await self._broadcast(self.apply_mpe_event(e))
        finally:
            midi_in.close_port()


def build_parser() -> argparse.ArgumentParser:
    """The CLI, exposed so the README-drift test can read the real flags."""
    p = argparse.ArgumentParser(description="Vox — bridge between a browser and the Moog One")
    p.add_argument("--mock", action="store_true", help="run against an in-process mock scsynth")
    p.add_argument("--sc-host", default="192.168.1.138")
    p.add_argument("--sc-port", type=int, default=57110)
    p.add_argument("--device", default="192.168.1.138", help="synth IP for SSH meter reads")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--midi-in", default=None, help="substring of the MIDI input port name")
    p.add_argument("--midi-out", default=None, help="substring of the MIDI output port name")
    p.add_argument(
        "--live-meters",
        action="store_true",
        help="poll the synth's meters over SSH (untested as a loop)",
    )
    return p


def main() -> None:
    a = build_parser().parse_args()

    mock = None
    if a.mock:
        from ..mock.server import MockScsynth

        mock = MockScsynth()
        mock.start()
        a.sc_host, a.sc_port = "127.0.0.1", mock.port

    midi_out = None
    if a.midi_out:
        import rtmidi

        mo = rtmidi.MidiOut()
        names = mo.get_ports()
        idx = next((i for i, n in enumerate(names) if a.midi_out in n), None)
        if idx is None:
            raise SystemExit(f"no MIDI out matching {a.midi_out!r}; have {names}")
        mo.open_port(idx)
        midi_out = mo

    meters = SshMeterSource(a.device) if a.live_meters else MockMeterSource()
    bridge = Bridge(a.sc_host, a.sc_port, meters=meters, midi_out=midi_out, midi_in_name=a.midi_in)
    print(
        f"Vox bridge on http://0.0.0.0:{a.port}  scsynth={a.sc_host}:{a.sc_port}  "
        f"meters={'ssh' if a.live_meters else 'mock'}"
    )
    try:
        asyncio.run(bridge.serve("0.0.0.0", a.port))
    finally:
        if mock:
            mock.stop()


if __name__ == "__main__":
    main()
