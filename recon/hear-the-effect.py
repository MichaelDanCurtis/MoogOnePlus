#!/usr/bin/env python3
"""Play something through one of the instrument's own effects, out of its own jacks.

`recon/net-audio-in.py` proves the round trip by measuring it. This one is for
listening: it sends a phrase into the instrument, through an effect running on
private buses, and up to the **main outputs**, alternating dry and wet so the
effect arriving is the thing you hear.

**Dry and wet are the same audio.** Only the monitor's input bus changes -- one
`/n_set` between the ring's bus and the effect's output. Nothing about the source,
the level or the timing moves, so what changes when it switches is the instrument's
reverb and nothing else.

**The main outs, from Moog's own source rather than inference:**

    Out.ar(7, main[0] * -1);
    Out.ar(0, main[1] * -1);   // good

So bus 7 carries the left channel and bus 0 the right -- the opposite way round
from what section 8 of the internals recorded from a tone sweep -- and **both are
phase-inverted**. This monitor inverts too, so what it adds to the jacks has the
same polarity as everything the instrument puts there itself. Without that, the
two would partially cancel wherever they carried the same material.

Nothing here touches the patch: the ring and the effect live on buses 100-103, and
the only thing that reaches the instrument's own signal path is a sum into the
output buses, which stops the moment the monitor node is freed.

    uv run python3 recon/hear-the-effect.py
    uv run python3 recon/hear-the-effect.py --effect et_shimmer_1
    uv run python3 recon/hear-the-effect.py --gain 0.35
"""

from __future__ import annotations

import argparse
import math
import socket
import sys
import threading
import time

SAMPLE_RATE = 48000

MONITOR_NODE = 95500
MONITOR_DEF = "voxMonitor"
#: Left to bus 7, right to bus 0, both inverted -- see the module docstring. Two
#: writes because `Out.ar` writes CONSECUTIVE buses, and the main outs are not.
MONITOR_GRAPH = (
    "|in = 102, gain = 0.2| "
    "var sig = In.ar(in, 2) * gain; "
    "Out.ar(7, sig[0] * -1); "
    "Out.ar(0, sig[1] * -1)"
)


class Phrase:
    """A plucked arpeggio, generated a block at a time.

    Deliberately percussive and spaced out: a reverb is inaudible under a sustained
    tone and obvious under something with silence after it. The decay is short so
    the tail you hear is the instrument's, not the source's.
    """

    #: A minor pentatonic that wanders, so the ear is not tracking a loop instead
    #: of the effect.
    NOTES = (57, 60, 62, 64, 67, 69, 72, 69, 67, 64, 62, 60)

    def __init__(self, note_seconds: float = 0.45) -> None:
        self.note_seconds = note_seconds
        self.samples_sent = 0

    def __call__(self, n: int) -> list[float]:
        out = []
        for _ in range(n):
            t = self.samples_sent / SAMPLE_RATE
            index = int(t / self.note_seconds) % len(self.NOTES)
            since = t - int(t / self.note_seconds) * self.note_seconds
            freq = 440.0 * 2 ** ((self.NOTES[index] - 69) / 12)
            envelope = math.exp(-since * 7.0)
            body = (
                math.sin(2 * math.pi * freq * since)
                + 0.4 * math.sin(2 * math.pi * freq * 2 * since)
                + 0.2 * math.sin(2 * math.pi * freq * 3 * since)
            )
            out.append(body * envelope * 0.3)
            self.samples_sent += 1
        return out


def local_address_for(host: str) -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


class MainsTap:
    """The instrument's main outs, streamed back, so the demo can be measured.

    Two numbers, and the second took three attempts to get right. Loudness alone
    is weak evidence: a reverb adds energy, so a higher rms only says something was
    added, not what. The interesting question is whether the gaps between plucks
    are being held open, which is what a reverb does and a gain stage does not.

    Counting samples above a silence floor does NOT answer it, absolute or
    relative. Both were tried and both read ~95 % for dry and wet alike, because
    this source decays to 0.043 of its peak within a note and never reaches either
    floor -- the metric was measuring the pluck, not the tail.

    What does answer it is the VALLEY relative to the PEAK: the quiet tenth of the
    section against its loud end. Dry, the gaps fall away from the plucks. Wet,
    the tail lifts them. Being a ratio within each section, it cannot be won by
    simply being louder, which is the trap the first two attempts fell into.
    """

    def __init__(self) -> None:
        self.data = bytearray()
        self.lock = threading.Lock()
        self.last_glitches = 0

    def serve(self, sock, stop) -> None:
        try:
            conn, _ = sock.accept()
        except (TimeoutError, OSError):
            return
        conn.settimeout(30)
        try:
            while not stop.is_set():
                chunk = conn.recv(65536)
                if not chunk:
                    break
                with self.lock:
                    self.data.extend(chunk)
        except (TimeoutError, OSError):
            pass
        finally:
            conn.close()

    def frames(self) -> int:
        with self.lock:
            return len(self.data) // 8

    def measure(self, since_frame: int) -> tuple[float, float]:
        import numpy as np

        with self.lock:
            blob = bytes(self.data[since_frame * 8 :])
        usable = len(blob) // 8 * 8
        if usable == 0:
            return (0.0, 0.0)
        left = np.frombuffer(blob[:usable], dtype="<f4").reshape(-1, 2)[:, 0]
        rms = float(np.sqrt(np.mean(left**2)))
        if left.size < 2048:
            return (rms, 0.0)
        # A 20 ms moving average: the envelope, not the waveform. Comparing raw
        # samples would measure zero crossings, which every signal has.
        window = 960
        envelope = np.convolve(np.abs(left), np.ones(window) / window, mode="valid")
        loud = float(np.percentile(envelope, 95))
        quiet = float(np.percentile(envelope, 10))
        self.last_glitches = self._glitches(left)
        return (rms, quiet / loud if loud > 0 else 0.0)

    @staticmethod
    def _glitches(left) -> int:
        """Count sample-to-sample steps far larger than this material contains.

        A plucked note is smooth; the ring being lapped is not. When the
        instrument's read pointer catches the writer it plays a block from the
        previous lap, and the seam is a step discontinuity -- which is what a
        stutter sounds like and what nothing in the source can produce.
        """
        import numpy as np

        delta = np.abs(np.diff(left))
        if delta.size == 0:
            return 0
        # Against the material's own typical step, so it scales with level.
        typical = float(np.percentile(delta, 99))
        if typical <= 0:
            return 0
        return int(np.count_nonzero(delta > typical * 8))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--effect", default="et_plate_1")
    ap.add_argument("--gain", type=float, default=0.2, help="level into the main outs")
    ap.add_argument("--dry", type=float, default=5.0, help="seconds of each dry section")
    ap.add_argument("--wet", type=float, default=8.0, help="seconds of each wet section")
    ap.add_argument("--rounds", type=int, default=2)
    # A SECOND of ring with half a second of lead. `net-audio-in.py` uses a tenth
    # of that because it is measuring the round trip and the lead is most of it --
    # but nothing here is racing a DAW, and a lead that small does not survive
    # this writer being a Python thread. Measured at a 2000-frame lead: the gap
    # fell to 256 frames, five milliseconds from the instrument's reader catching
    # the writer and replaying a lap-old block, which is heard as a stutter.
    ap.add_argument("--ring", type=int, default=48000)
    ap.add_argument("--lead", type=int, default=24000)
    ap.add_argument(
        "--settings",
        default="size=0.55,decay=0.4,mix=0.5",
        help="controls to set on the effect; its own defaults are a very small room",
    )
    ap.add_argument(
        "--capture",
        type=int,
        default=0,
        help="port to stream the main outs back on, to measure what was actually played",
    )
    args = ap.parse_args(argv)

    from moogone import ingress, netaudio
    from moogone.sc.client import ScClient
    from moogone.synthdef import compile_synthdef
    from moogone.transport.udp import UdpTransport

    client = ScClient(UdpTransport(args.host, 57110))
    print(f"\n  instrument: {client.status(timeout=5).num_ugens} ugens\n")

    monitor = compile_synthdef(MONITOR_DEF, MONITOR_GRAPH)
    client.d_recv(monitor, timeout=15.0)
    client.sync(timeout=8.0)

    armed = ingress.arm(client, effect=args.effect, frames=args.ring)
    print(f"  {args.effect} on private buses {ingress.IN_BUS} -> {ingress.FX_BUS}")

    # The instrument's effects come up at defaults that are deliberately tiny --
    # et_plate_1 idles at size 0.1 and decay 0.2, which is a small room rather than
    # a plate. Left there, the difference between dry and wet is mostly level, and
    # level is the one thing a reverb shares with a gain stage.
    #
    # But not far up either. size=0.9 with decay=0.85 drives the plate into a
    # self-sustaining wash: recorded off the analog outs it read a crest factor of
    # 2.1, which is a saturated drone rather than plucked notes, and it clipped the
    # interface at six times less send level. These values keep the tail obvious
    # and the transients intact.
    if args.settings:
        controls: list = []
        for pair in args.settings.split(","):
            name, _, value = pair.partition("=")
            controls += [name.strip(), float(value)]
        client.send("/n_set", ingress.EFFECT_NODE, *controls)
        client.sync(timeout=8.0)
        print(f"  set to {args.settings}")

    stop = threading.Event()
    started = False
    captured: dict[str, list] = {}
    glitches: list[tuple[str, int]] = []
    writer = None
    stream = None
    listener = None
    try:
        # Its own client on its own socket: this thread polls the instrument's read
        # pointer four times a second, and one ScClient cannot keep two threads'
        # replies apart -- each consumes and discards the other's.
        writer = ingress.RingWriter(
            ScClient(UdpTransport(args.host, 57110)), armed, Phrase(), lead=args.lead
        )
        writer.prime()
        threading.Thread(target=writer.run, args=(stop,), daemon=True).start()
        started = True

        client.send(
            "/s_new", MONITOR_DEF, MONITOR_NODE, 1, 0, "in", ingress.IN_BUS, "gain", args.gain
        )
        client.sync(timeout=8.0)
        print(f"  monitor on the main outs at gain {args.gain}\n")

        tap = None
        if args.capture:
            # The recorder is armed AFTER the monitor deliberately: nodes execute in
            # creation order, and one made first would read bus 0 before the monitor
            # had written it. The symptom is silence, not lateness.
            tap = MainsTap()
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("0.0.0.0", args.capture))
            listener.listen(1)
            listener.settimeout(25)
            threading.Thread(target=tap.serve, args=(listener, stop), daemon=True).start()
            stream = netaudio.arm(
                client, args.host, local_address_for(args.host), args.capture, bus=0
            )
            print("  measuring bus 0 -- the right channel of the main outs\n")
            time.sleep(1.0)

        print("  ---- listen ----\n")

        for round_number in range(1, args.rounds + 1):
            client.send("/n_set", MONITOR_NODE, "in", ingress.IN_BUS)
            print(f"  {round_number}. DRY  -- straight through, no effect")
            mark = tap.frames() if tap else 0
            time.sleep(args.dry)
            if tap:
                captured.setdefault("dry", []).append(tap.measure(mark))
                glitches.append(("dry", tap.last_glitches))
            client.send("/n_set", MONITOR_NODE, "in", ingress.FX_BUS)
            print(f"     WET  -- the same audio through {args.effect}")
            mark = tap.frames() if tap else 0
            time.sleep(args.wet)
            if tap:
                captured.setdefault("wet", []).append(tap.measure(mark))
                glitches.append(("wet", tap.last_glitches))

        # Let the tail ring out rather than chopping it, which is the part worth
        # hearing.
        client.send("/n_set", MONITOR_NODE, "in", ingress.FX_BUS)
        print("\n  letting the tail ring out")
        time.sleep(3.0)
    finally:
        if stream is not None:
            netaudio.disarm(client, stream, quiet=True)
        stop.set()
        time.sleep(0.3)
        # The monitor is ours and made of plain ugens, so freeing it is safe. The
        # EFFECT is not: /n_free on one of the instrument's LADSPA effects
        # terminates scsynth, and ingress.disarm stops it with enable=0 instead.
        client.send("/n_free", MONITOR_NODE)
        ingress.disarm(client, quiet=True)
        try:
            client.sync(timeout=5.0)
        except Exception:  # noqa: BLE001, S110 -- reported by the status line below
            pass

        if listener is not None:
            listener.close()

    if captured:
        print("\n  what actually came out of the main outs")
        for label in ("dry", "wet"):
            for i, (rms, filled) in enumerate(captured.get(label, []), 1):
                print(
                    f"    {label:<4} {i}: rms {rms:.5f}   "
                    f"quiet passages sit at {filled * 100:5.1f}% of the loud ones"
                )
        dry = captured.get("dry") or [(0.0, 0.0)]
        wet = captured.get("wet") or [(0.0, 0.0)]
        dry_fill = sum(f for _, f in dry) / len(dry)
        wet_fill = sum(f for _, f in wet) / len(wet)
        dry_rms = sum(r for r, _ in dry) / len(dry)
        wet_rms = sum(r for r, _ in wet) / len(wet)
        print(
            f"\n  the same notes at the same level: rms {dry_rms:.5f} dry -> "
            f"{wet_rms:.5f} wet ({wet_rms / max(dry_rms, 1e-9):.1f}x),"
        )
        print(
            f"  and the quiet passages sit at {dry_fill * 100:.1f}% of the peaks dry "
            f"against {wet_fill * 100:.1f}% wet."
        )
        print("  That second number is the tail -- the part a gain stage cannot fake.")
    if glitches:
        total = sum(n for _, n in glitches)
        print(f"\n  discontinuities in what came back: {total}")
        if writer is not None:
            print(
                f"  gap to the instrument's reader: smallest {writer.min_gap} frames "
                f"of a {writer.lead}-frame lead, {writer.resets} stalls given up on"
            )
        if total:
            print("  A step the source cannot produce. The reader caught the writer.")
    if started:
        print(f"\n  done. instrument: {client.status(timeout=5).num_ugens} ugens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
