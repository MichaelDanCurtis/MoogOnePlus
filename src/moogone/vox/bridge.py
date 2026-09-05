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
import base64
import contextlib
import pathlib
import queue
import subprocess
import threading
import time
import typing
from dataclasses import replace
from http import HTTPStatus
from typing import ClassVar

from websockets.asyncio.server import serve

from ..controls import for_ui as controls_for_ui
from ..display import DISPLAY_PORT, Framebuffer, decode_tile
from ..performance import PERFORMANCE_PORT, Note
from ..performance import decode as decode_perf
from ..sampler import LiveSampler, Sampler, SamplerError
from ..sc.client import ScClient, ScError, ScTimeout
from ..screen import HEIGHT as SCREEN_H
from ..screen import WIDTH as SCREEN_W
from ..screen import MainScreen, bgra_to_rgb, png_rgb
from ..stream import BusStream
from ..transport.udp import UdpTransport
from ..voicebus import VOICE_BUS_PORT
from ..voicebus import decode as decode_x
from . import ai as ai_mod
from .destinations import Dispatcher, MidiCC, MidiNote, RawOsc, ScParam, VoiceParam
from .fx import FxWorkbench
from .learn import Learner, LearnError, ParamMap
from .meters import MeterSource, MockMeterSource, SshMeterSource
from .mpe import MpeDecoder, ZoneConfig
from .patch import Patch, PatchError, to_source
from .patch import validate as validate_patch
from .protocol import LIVE, ProtocolError, decode, encode
from .router import Route, Router
from .ugens import catalog_for_ui
from .vector import Motion, VectorEngine, surface

STATIC = pathlib.Path(__file__).parent / "static"
#: How often the moving vector position is pushed to the UI. 20 Hz looks continuous
#: and is a fraction of the 100 Hz tick.
_POS_PERIOD = 0.05
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
        panel_host: str | None = None,
        panel_period: float = 0.1,
        screen_period: float = 0.4,
    ):
        self.port: int | None = None
        self._static = static_dir or STATIC
        self._meters = meters
        self._meter_period = meter_period
        # Mirroring the instrument's own screens: the host to capture from, and
        # how often to push a rebuilt frame. Tiles arrive far faster than the
        # picture actually changes, so frames go out on this timer instead.
        self._panel_host = panel_host
        self._panel_period = panel_period
        self._panel_stream = None
        self._screen = None
        self._screen_period = screen_period
        self.learner = Learner()
        self._live_sampler = None
        self._live_thread = None
        self._loop = None
        self.param_map = ParamMap.load(pathlib.Path('presets') / 'params.json')
        self._tick = 1.0 / tick_hz
        self._clients: set = set()
        self._sc_ok = False
        self._sc_lock = threading.Lock()

        self._client = ScClient(UdpTransport(sc_host, sc_port))
        # Shares the SC client. Its live trigger additionally needs the device
        # host, which only exists when --panel supplied one.
        self.sampler = Sampler(self._client)
        self.fx = FxWorkbench(self._client)
        self.mpe = MpeDecoder()
        self.router = Router()
        self.vector = VectorEngine()
        self.sources: dict[str, float] = {}
        self._ai_busy = False
        self._last_pos_bcast = 0.0
        #: Last value the vector wrote per path, so it only re-sends real changes.
        self._vector_last: dict[str, float] = {}

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
        return self._static_file(connection, path)

    #: What may be served beside the page. An allowlist, not a guess from the
    #: extension: this serves a directory over the LAN, and "everything except the
    #: things I thought of" is the wrong default for that.
    _MEDIA: typing.ClassVar[dict[str, str]] = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".svg": "image/svg+xml",
    }

    def _static_file(self, connection, path: str):
        """Serve one allowlisted file from the static directory, or 404.

        The name is taken as a bare filename, so `..` and any directory part are
        discarded rather than sanitised — there is no arrangement of dots and slashes
        that reaches outside, because nothing but the final component is used.
        """
        name = pathlib.PurePosixPath(path).name
        suffix = pathlib.PurePosixPath(name).suffix.lower()
        if not name or suffix not in self._MEDIA:
            return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
        target = self._static / name
        if not target.is_file():
            return connection.respond(HTTPStatus.NOT_FOUND, "not found\n")
        body = target.read_bytes()
        resp = connection.respond(HTTPStatus.OK, "")
        # Two things bite here, and both fail quietly.
        #
        # `respond` builds the response from TEXT and sets Content-Length to match, so
        # assigning `.body` afterwards ships a correct-looking 200 of zero bytes.
        #
        # And `Headers` is a MULTIDICT: assigning a key APPENDS. Setting
        # Content-Length without removing the old one sends the header twice, which is
        # a malformed response -- the client does not error, it hangs.
        resp.body = body
        for header, value in (
            ("Content-Length", str(len(body))),
            ("Content-Type", self._MEDIA[suffix]),
            ("Cache-Control", "no-cache"),
        ):
            if header in resp.headers:  # Cache-Control is not one `respond` sets
                del resp.headers[header]
            resp.headers[header] = value
        return resp

    # -- lifecycle -----------------------------------------------------------
    async def serve(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        # Dispatch runs on worker threads, which have no running loop of their own.
        # Anything that needs to post back to the event loop has to capture it here.
        self._loop = asyncio.get_running_loop()
        async with serve(self.handle, host, port, process_request=self._http) as server:
            self.port = server.sockets[0].getsockname()[1]
            loops = [
                asyncio.create_task(self._meter_loop()),
                asyncio.create_task(self._router_loop()),
            ]
            if self._midi_in_name:
                loops.append(asyncio.create_task(self._midi_loop()))
            if self._panel_host:
                loops.append(asyncio.create_task(self._panel_loop()))
                loops.append(asyncio.create_task(self._screen_loop()))
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
            # The vector engine's corners live here, not in the page. Without this a
            # reload showed four empty corners while the bridge held four full ones —
            # the same server-moved-while-the-UI-held-a-stale-copy fault as the stale
            # landscape and the frozen routed writes. It is in-memory and free to send;
            # the FX tree is a network round trip to the instrument, so that one stays
            # on request.
            await ws.send(encode(self._vector_state()))
            # Learned parameter names live here too, not in the page. Same reason.
            await ws.send(encode(self._learn_map()))
            await ws.send(encode(self._sampler_state()))
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
        if t.startswith("vector."):
            return self._vector(t, msg)
        if t.startswith("sampler."):
            return self._sampler(t, msg)
        if t == "controls.list":
            return [{"type": "controls.all",
                     "controls": controls_for_ui(int(msg.get("timbre", 1)))}]
        if t.startswith("learn."):
            return self._learn(t, msg)
        if t.startswith("patch."):
            return self._patch(t, msg)
        if t.startswith("ai."):
            return self._ai(t, msg)
        return [{"type": "error", "where": "dispatch", "what": f"unhandled {t}"}]

    # -- sampler ---------------------------------------------------------------
    def _sampler(self, t: str, msg: dict) -> list[dict]:
        """Your own audio, loaded into the instrument and played by its own keys."""
        try:
            if t == "sampler.load":
                path = str(msg["path"])
                name = str(msg.get("name") or pathlib.Path(path).stem)
                root = int(msg.get("root", 60))
                if self._panel_host:
                    path = self.sampler.push(path, self._panel_host)
                self.sampler.load(name, path, root_note=root)
                if self.sampler.map.spread is None:
                    self.sampler.map.spread = self.sampler.samples[name]

            elif t == "sampler.assign":
                name = str(msg["name"])
                if name not in self.sampler.samples:
                    raise SamplerError(f"no sample called {name!r}")
                self.sampler.map.assign(int(msg["note"]), self.sampler.samples[name])

            elif t == "sampler.spread":
                name = msg.get("name")
                self.sampler.map.spread = self.sampler.samples[str(name)] if name else None

            elif t == "sampler.live":
                self._set_live_sampler(bool(msg["on"]))

            elif t == "sampler.stop":
                self.sampler.stop_all()

            elif t != "sampler.list":
                return [{"type": "error", "where": "sampler", "what": f"unhandled {t}"}]

        except (SamplerError, KeyError, ValueError) as exc:
            return [{"type": "error", "where": t, "what": str(exc)}]
        return [self._sampler_state()]

    def _set_live_sampler(self, on: bool) -> None:
        if on and self._live_sampler is None:
            if not self._panel_host:
                raise SamplerError(
                    "live triggering needs the device host; start vox with --panel <ip>"
                )
            loop = self._loop
            if loop is None:
                raise SamplerError("the bridge is not serving yet")

            def on_note(note) -> None:
                # Only a note-ON is a hit. A note-off would flash the key a second
                # time at velocity 0, which reads as a double trigger.
                if note.is_note_off:
                    return
                sample = self.sampler.map.for_note(note.note)
                loop.call_soon_threadsafe(
                    lambda: asyncio.ensure_future(
                        self._broadcast({
                            "type": "sampler.hit",
                            "note": note.note,
                            "sample": sample.name if sample else "",
                            "velocity": note.midi_velocity,
                        })
                    )
                )

            self._live_sampler = LiveSampler(self.sampler, self._panel_host, on_note=on_note)
            self._live_thread = threading.Thread(
                target=self._live_sampler.run, daemon=True
            )
            self._live_thread.start()
        elif not on and self._live_sampler is not None:
            self._live_sampler.stop()
            self._live_sampler = None
            self._live_thread = None

    def _sampler_state(self) -> dict:
        m = self.sampler.map
        return {
            "type": "sampler.state",
            "samples": [
                {"name": s.name, "root": s.root_note, "frames": s.frames,
                 "seconds": round(s.frames / 48000.0, 2)}
                for s in self.sampler.samples.values()
            ],
            "spread": m.spread.name if m.spread else None,
            "by_note": {str(n): s.name for n, s in sorted(m.by_note.items())},
            "live": self._live_sampler is not None,
        }

    # -- parameter learning --------------------------------------------------
    def _learn(self, t: str, msg: dict) -> list[dict]:
        """Learn a parameter id by watching the instrument's own control traffic.

        The engine addresses parameters by 16-bit id and nothing publishes what they
        mean, but every change is announced on the voice bus. So the instrument
        teaches us its own numbering: begin a pass, move one control, end it.
        """
        if t == "learn.begin":
            try:
                self.learner.begin(str(msg["label"]))
            except (LearnError, KeyError) as exc:
                return [{"type": "error", "where": "learn.begin", "what": str(exc)}]
            return [self._learn_map()]

        if t == "learn.finish":
            result = self.learner.finish()
            label = self.learner.label
            if result.ok:
                try:
                    self.param_map.learn(result.param, label)
                    self.param_map.save(pathlib.Path("presets") / "params.json")
                except LearnError as exc:
                    return [{"type": "error", "where": "learn.finish", "what": str(exc)}]
            out = result.as_dict()
            out.update({"type": "learn.result", "label": label})
            return [out, self._learn_map()]

        if t == "learn.forget":
            self.param_map.forget(int(msg["param"]))
            self.param_map.save(pathlib.Path("presets") / "params.json")
            return [self._learn_map()]

        if t == "learn.list":
            return [self._learn_map()]

        return [{"type": "error", "where": "learn", "what": f"unhandled {t}"}]

    def _learn_map(self) -> dict:
        return {"type": "learn.map", "names": self.param_map.as_dict()}

    # -- vector synthesis ----------------------------------------------------
    def _vector(self, t: str, msg: dict) -> list[dict]:
        if t == "vector.corner":
            name, action = str(msg["name"]), str(msg["action"])
            try:
                if action == "clear":
                    self.vector.clear_corner(name)
                else:
                    # Snapshot every writable control currently on the tree.
                    #
                    # Read the tree *fresh and under the lock*. The cached node list is
                    # mutated by fx.set's confirm-refresh, and these arrive as separate
                    # WebSocket messages on separate threads — an unlocked read here
                    # caught the cache mid-update and stored a stale value. Seen in the
                    # browser: corners A and B captured correctly, C and D did not.
                    with self._sc_lock:
                        try:
                            nodes = self.fx.refresh()
                        except _SC_ERRORS as exc:
                            return [
                                {
                                    "type": "error",
                                    "where": "vector.corner",
                                    "what": f"could not read the tree to snapshot: {exc}",
                                }
                            ]
                    snap = {
                        f"sc.{n.node_id}.{c.name}": c.value
                        for n in nodes
                        for c in n.controls
                        if c.kind != "readonly"
                    }
                    if not snap:
                        return [
                            {
                                "type": "error",
                                "where": "vector.corner",
                                "what": "no tree loaded yet — press Refresh on the FX panel first",
                            }
                        ]
                    self.vector.set_corner(name, snap)
            except ValueError as exc:
                return [{"type": "error", "where": "vector.corner", "what": str(exc)}]
            return [self._vector_state()]
        if t == "vector.move":
            # A hand on the pad takes over, unless it is deliberately drawing a path.
            if not self.vector.recording:
                self.vector.set_mode("manual")
            self.vector.move(float(msg["x"]), float(msg["y"]), t=time.monotonic())
            return [self._vector_state(), *self._vector_write()]
        if t == "vector.orbit":
            o = self.vector.orbit
            for k in ("rate_x", "rate_y", "phase_x", "phase_y", "depth"):
                if k in msg:
                    setattr(o, k, float(msg[k]))
            return [self._vector_state()]
        if t == "vector.mode":
            try:
                self.vector.set_mode(str(msg["mode"]))
            except ValueError as exc:
                return [{"type": "error", "where": "vector.mode", "what": str(exc)}]
            self.vector.trigger(time.monotonic())
            return [self._vector_state()]
        if t == "vector.record":
            if str(msg["action"]) == "start":
                self.vector.start_recording(time.monotonic())
                return [self._vector_state()]
            n = self.vector.stop_recording()
            if n < 2:
                return [
                    {
                        "type": "error",
                        "where": "vector.record",
                        "what": "nothing recorded — drag the pad while armed",
                    },
                    self._vector_state(),
                ]
            self.vector.set_mode("motion")
            self.vector.trigger(time.monotonic())
            return [self._vector_state()]
        if t == "vector.clock":
            c = self.vector.clock
            if "mode" in msg:
                try:
                    self.vector.clock = replace(c, mode=str(msg["mode"]))
                    c = self.vector.clock
                except ValueError as exc:
                    return [{"type": "error", "where": "vector.clock", "what": str(exc)}]
            for k in ("period", "bpm", "beats"):
                if k in msg:
                    setattr(c, k, float(msg[k]))
            if "retrigger" in msg:
                c.retrigger = bool(msg["retrigger"])
            if "loop" in msg:
                try:
                    self.vector.motion.loop = str(msg["loop"])
                    Motion(loop=str(msg["loop"]))  # validate the same way
                except ValueError as exc:
                    return [{"type": "error", "where": "vector.clock", "what": str(exc)}]
            self.vector.trigger(time.monotonic())
            return [self._vector_state()]
        if t == "vector.surface":
            path = str(msg["path"])
            return [
                {
                    "type": "vector.surface",
                    "path": path,
                    "grid": surface(self.vector.corners, path, n=17),
                }
            ]
        return [{"type": "error", "where": "vector", "what": f"unhandled {t}"}]

    def _vector_state(self) -> dict:
        o, c, v = self.vector.orbit, self.vector.clock, self.vector
        return {
            "type": "vector.state",
            "x": v.x,
            "y": v.y,
            "mode": v.mode,
            "recording": v.recording,
            "corners": {k: len(val) for k, val in v.corners.items()},
            "paths": v.paths(),
            # The range each control covers, so the UI can say which paths have a
            # landscape and which are flat. A flat surface is a correct drawing of
            # identical corners; without this it reads as a broken renderer.
            "spans": {k: [lo, hi] for k, (lo, hi) in v.spans().items()},
            "duplicates": v.duplicate_corners(),
            "orbit": {
                "rate_x": o.rate_x,
                "rate_y": o.rate_y,
                "phase_x": o.phase_x,
                "phase_y": o.phase_y,
                "depth": o.depth,
            },
            "clock": {
                "mode": c.mode,
                "period": c.period,
                "bpm": c.bpm,
                "beats": c.beats,
                "retrigger": c.retrigger,
                "seconds_per_cycle": c.seconds_per_cycle,
            },
            "motion": v.motion.as_dict(),
        }

    def _vector_write(self) -> list[dict]:
        """Push the blended values out through the dispatcher, as ``sent``.

        Only paths whose blended value actually **changed** are written. Without this the
        vector re-sends all ten controls every tick — a hundred identical ``/n_set``s a
        second that flood the server and race every other writer, which is the same rule
        the router already applies to its own destinations. A vector parked between two
        corners that agree on a control now writes nothing at all for it.
        """
        out = []
        for path, value in self.vector.values().items():
            if not self._has_dest(path):
                continue
            last = self._vector_last.get(path)
            if last is not None and abs(value - last) < 1e-9:
                continue
            self._vector_last[path] = value
            if self._locked_write(path, value) and path.startswith("sc."):
                _, node, ctl = path.split(".", 2)
                out.append(
                    {
                        "type": "fx.value",
                        "node": int(node),
                        "ctl": ctl,
                        "value": value,
                        "state": "sent",
                    }
                )
        return out

    # -- patcher -------------------------------------------------------------
    def _patch(self, t: str, msg: dict) -> list[dict]:
        if t == "patch.catalog":
            return [{"type": "patch.ugens", "ugens": catalog_for_ui()}]
        try:
            graph = Patch.from_dict(msg["patch"])
        except (KeyError, TypeError, ValueError) as exc:
            return [{"type": "error", "where": t, "what": f"malformed patch: {exc}"}]
        problems = validate_patch(graph)
        if t == "patch.validate":
            return [{"type": "patch.problems", "problems": problems}]
        if t == "patch.source":
            if problems:
                return [{"type": "patch.scd", "source": "", "problems": problems}]
            try:
                return [{"type": "patch.scd", "source": to_source(graph), "problems": []}]
            except PatchError as exc:
                return [{"type": "patch.scd", "source": "", "problems": [str(exc)]}]
        return [{"type": "error", "where": "patch", "what": f"unhandled {t}"}]

    # -- AskAI ---------------------------------------------------------------
    def _ai(self, t: str, msg: dict) -> list[dict]:
        if t == "ai.list":
            return [{"type": "ai.providers", "providers": ai_mod.available_providers()}]
        if t == "ai.ask":
            name = str(msg["provider"])
            provider = ai_mod.PROVIDERS.get(name)
            if provider is None or not provider.available():
                return [
                    {
                        "type": "error",
                        "where": "ai.ask",
                        "what": f"{name!r} is not installed; have {ai_mod.available_providers()}",
                    }
                ]
            if not self.fx.nodes:
                return [
                    {
                        "type": "error",
                        "where": "ai.ask",
                        "what": "no tree loaded yet — press Refresh on the FX panel first",
                    }
                ]
            try:
                prop = ai_mod.ask_for_patch(provider, self.fx.nodes, str(msg["request"]))
            except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
                return [{"type": "error", "where": f"ai.{name}", "what": str(exc)[:400]}]
            return [{"type": "ai.proposal", **prop.as_dict()}]
        if t == "ai.apply":
            # Re-validate here rather than trusting what came back from the UI: the only
            # values that reach the synth are ones the live tree still accepts.
            changes = msg["changes"]
            if not isinstance(changes, list):
                return [{"type": "error", "where": "ai.apply", "what": "changes must be a list"}]
            prop = ai_mod.validate({"changes": changes}, self.fx.nodes)
            out: list[dict] = []
            for c in prop.changes:
                out.extend(self._fx_set(c.node, c.ctl, c.value))
            for why in prop.rejected:
                out.append({"type": "error", "where": "ai.apply", "what": why})
            return out
        return [{"type": "error", "where": "ai", "what": f"unhandled {t}"}]

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

        # Someone else is driving this control now; forget what the vector last wrote so
        # it will re-assert its own value rather than skipping it as "unchanged".
        self._vector_last.pop(f"sc.{node}.{ctl}", None)
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
    async def _screen_loop(self) -> None:
        """Mirror the instrument's MAIN display, read from its framebuffer.

        Separate from the panel loop because it is a different mechanism entirely:
        the big screen is an X server drawing into /dev/fb0 on the instrument's own
        Linux, not something sent over the panel bus. Conversion and PNG encoding
        cost about 3 ms a frame, so the limit is the SSH pipe, not the CPU.
        """
        if self._panel_host is None:
            return
        loop = asyncio.get_running_loop()

        def on_frame(frame: bytes) -> None:
            try:
                png = png_rgb(bgra_to_rgb(frame))
            except ValueError:
                return  # a short frame: the display changed mode under us
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self._broadcast(
                        {
                            "type": "panel.screen",
                            "png": base64.b64encode(png).decode("ascii"),
                            "width": SCREEN_W,
                            "height": SCREEN_H,
                        }
                    )
                )
            )

        screen = MainScreen(self._panel_host, on_frame, period=self._screen_period)
        self._screen = screen
        try:
            await asyncio.to_thread(screen.run)
        finally:
            screen.stop()

    async def _panel_loop(self) -> None:
        """Mirror the instrument's own panel: its two OLED screens and its notes.

        One SSH capture serves both, because they arrive on the same bus. Frames are
        rebuilt here from 64x16 tiles and pushed as PNGs on a timer rather than per
        tile: the displays send about 135 tiles a second each, and forwarding every
        one would be some 180 KB/s of websocket for a screen that changes far less
        often than that.
        """
        if self._panel_host is None:
            return
        loop = asyncio.get_running_loop()
        frames = {0: Framebuffer(), 1: Framebuffer()}

        def emit(msg: dict) -> None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._broadcast(msg)))

        def on_datagram(sport: int, dport: int, payload: bytes) -> None:
            if dport == DISPLAY_PORT or sport == DISPLAY_PORT:
                tile = decode_tile(payload)
                if tile is not None and tile.display in frames:
                    frames[tile.display].blit(tile)
                return
            if dport == VOICE_BUS_PORT or sport == VOICE_BUS_PORT:
                write = decode_x(payload)
                if write is not None:
                    self.learner.feed(write.param, write.value)
                    emit(
                        {
                            "type": "learn.activity",
                            "param": write.param,
                            "name": self.param_map.name_for(write.param),
                            "value": write.value,
                        }
                    )
                return
            if dport == PERFORMANCE_PORT or sport == PERFORMANCE_PORT:
                message = decode_perf(payload)
                if isinstance(message, Note):
                    emit(
                        {
                            "type": "perf.note",
                            "note": message.note,
                            "on": not message.is_note_off,
                            "velocity": message.midi_velocity,
                        }
                    )

        stream = BusStream(
            self._panel_host, (PERFORMANCE_PORT, DISPLAY_PORT, VOICE_BUS_PORT), on_datagram
        )
        self._panel_stream = stream
        capture = asyncio.create_task(asyncio.to_thread(stream.run))
        try:
            while not capture.done():
                await asyncio.sleep(self._panel_period)
                for index, frame in frames.items():
                    if frame.dirty:
                        frame.dirty = False
                        await self._broadcast(
                            {
                                "type": "panel.frame",
                                "display": index,
                                "png": base64.b64encode(frame.png()).decode("ascii"),
                                "width": frame.width,
                                "height": frame.height,
                            }
                        )
        finally:
            stream.stop()
            with contextlib.suppress(asyncio.CancelledError):
                capture.cancel()
                await capture

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

            # The orbit moves the vector position, which writes through the dispatcher.
            # Rate limiting lives in the router/dispatcher, so this can tick freely.
            if self.vector.moving():
                self.vector.tick(now)
                for out in await asyncio.to_thread(self._vector_write):
                    await self._broadcast(out)
                self.sources["vector.x"] = self.vector.x
                self.sources["vector.y"] = self.vector.y
                # The dot has to move on screen too. Found by running it: the controls
                # swept correctly while the pad sat frozen, because vector.state is only
                # sent in reply to a command. Position-only, throttled — the full state
                # message carries the corner snapshots and is far too heavy for this.
                if now - self._last_pos_bcast >= _POS_PERIOD:
                    self._last_pos_bcast = now
                    await self._broadcast(
                        {"type": "vector.pos", "x": self.vector.x, "y": self.vector.y}
                    )

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
    p.add_argument(
        "--panel",
        metavar="HOST",
        help="mirror the instrument's OLED screens and note stream, captured over SSH",
    )
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
    bridge = Bridge(
        a.sc_host,
        a.sc_port,
        meters=meters,
        midi_out=midi_out,
        midi_in_name=a.midi_in,
        panel_host=a.panel,
    )
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
