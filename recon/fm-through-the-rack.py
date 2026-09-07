#!/usr/bin/env python3
"""Play the FM engine through one of the instrument's own effects, and prove it.

`moogone.ingress` sends audio from this machine through the Moog's effects rack.
This is the other half and needs no audio from anywhere: the FM engine is already
making sound inside `scsynth`, so engaging a send only changes where it writes and
puts an effect in front of the jacks.

**Dry and wet are the same notes.** The phrase is identical in both halves; the
only difference is whether the send is engaged. So whatever arrives when it is
engaged is the effect and nothing else.

    uv run python3 recon/fm-through-the-rack.py
    uv run python3 recon/fm-through-the-rack.py --preset Shimmer
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

import numpy as np

SAMPLE_RATE = 48000
NOTES = (57, 64, 69, 72, 69, 64)


class Mains:
    """The instrument's main outs, streamed back so the demo can be measured."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.lock = threading.Lock()

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

    def measure(self, since: int) -> tuple[float, float]:
        """rms, and how high the quiet passages sit against the loud ones.

        The second is the one that distinguishes a reverb from a gain stage: a
        tail holds the gaps between notes open, and being a ratio within the
        section it cannot be won by simply being louder.
        """
        with self.lock:
            blob = bytes(self.data[since * 8 :])
        usable = len(blob) // 8 * 8
        if usable < 8192:
            return (0.0, 0.0)
        left = np.frombuffer(blob[:usable], dtype="<f4").reshape(-1, 2)[:, 0].astype("float64")
        rms = float(np.sqrt(np.mean(left**2)))
        env = np.convolve(np.abs(left), np.ones(960) / 960, mode="valid")
        loud = float(np.percentile(env, 95))
        return (rms, float(np.percentile(env, 10)) / loud if loud > 0 else 0.0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--port", type=int, default=14180)
    ap.add_argument("--preset", default="Plate")
    ap.add_argument("--rounds", type=int, default=2)
    args = ap.parse_args(argv)

    from moogone import netaudio
    from moogone.effect import PRESETS, EffectSend
    from moogone.fm import FMEngine
    from moogone.sc.client import ScClient
    from moogone.transport.udp import UdpTransport

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.connect((args.host, 9))
    mac = probe.getsockname()[0]
    probe.close()

    client = ScClient(UdpTransport(args.host, 57110))
    print(f"\n  instrument: {client.status(timeout=5).num_ugens} ugens")
    print(f"  presets: {', '.join(p.name for p in PRESETS)}\n")

    fm = FMEngine(client)
    fm.ensure_synthdefs()
    send = EffectSend(client)
    send.attach(fm)

    mains = Mains()
    stop = threading.Event()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", args.port))
    srv.listen(1)
    srv.settimeout(25)
    threading.Thread(target=mains.serve, args=(srv, stop), daemon=True).start()

    stream = None
    results: dict[str, list] = {}
    try:
        # Engaged first so the groups and the effect exist before the recorder is
        # armed: the recorder is made last and therefore runs last, which is what
        # lets it hear everything in front of it.
        chosen = send.recall(args.preset)
        print(f"  {chosen.name}: {chosen.description}")
        print(
            f"  {chosen.effect}, bus {send.as_dict()['in_bus']} -> "
            f"{send.as_dict()['out_bus']}, level {send.level}\n"
        )
        stream = netaudio.arm(client, args.host, mac, args.port, bus=0)
        time.sleep(1.5)

        def phrase(label: str) -> None:
            base = mains.frames()
            for note in NOTES:
                fm.note_on(note, 110)
                # The recorder sits at the tail of the root group. With the send
                # BYPASSED the voices go back there too, and a voice made after the
                # recorder writes its bus too late to be read -- so the capture
                # reads silence while the jacks are perfectly loud. Measured at
                # rms 0.00002 for a phrase that was audibly playing. Engaged, the
                # voices are in the source group at the head and the problem
                # cannot arise; this keeps the dry half honest.
                netaudio.follow(client)
                time.sleep(0.5)
            time.sleep(1.5)
            results.setdefault(label, []).append(mains.measure(base))
            rms, tail = results[label][-1]
            print(f"    {label:<8} rms {rms:.5f}   quiet passages at {tail * 100:4.1f}% of loud")

        for i in range(1, args.rounds + 1):
            print(f"  round {i}")
            # disengage() detaches every source, so the FM voices go straight to
            # the jacks for the dry half. Attaching again BEFORE the recall is what
            # puts them back: engage() re-applies the routing to whatever is
            # attached at that moment, and the detach emptied that list.
            send.disengage()
            phrase("dry")
            send.attach(fm)
            send.recall(args.preset)
            phrase("wet")
    finally:
        if stream is not None:
            netaudio.disarm(client, stream, quiet=True)
        send.disengage()
        try:
            client.sync(timeout=5.0)
        except Exception:  # noqa: BLE001, S110 -- reported by the line below
            pass
        stop.set()
        srv.close()

    print()
    for label in ("dry", "wet"):
        got = results.get(label, [])
        if got:
            print(
                f"  {label}: rms {sum(r for r, _ in got) / len(got):.5f}, "
                f"tail {sum(t for _, t in got) / len(got) * 100:.1f}%"
            )
    print(f"\n  instrument: {client.status(timeout=5).num_ugens} ugens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
