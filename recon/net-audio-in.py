#!/usr/bin/env python3
"""Audio *into* the instrument, through one of its own effects, and back out.

This is the test `docs/PLUGIN.md` gates the effect shape on, and it took two
architectures to pass. Both are recorded because the first one looks obviously
right and is not.

**The FIFO route, which does not work.** Egress writes a FIFO and `nc` pushes it
at a socket; the mirror image would be a FIFO fed by `nc` and read by `DiskIn`.
Measured on hardware, in this order:

  * `/b_read` reads a FIFO honestly -- given a header and nothing else it blocked
    for 4.02 s until the frames arrived.
  * `DiskIn` will not continue from one. Cued from a FIFO it plays what `/b_read`
    left in the buffer and never asks again: twenty seconds of a realtime feed and
    the instrument accepted **0.00x realtime**, with the disk thread idle rather
    than blocked. The same synthdef from an ordinary file on the instrument sounds
    at rms 0.141, so DiskIn is fine and the pipe is the difference.
  * Every attempt puts scsynth's disk thread -- which also serves `/d_recv`,
    `/b_alloc`, `/sync` and the instrument's own preset loading -- behind a read
    that may never return. An under-fed FIFO left `/sync` unanswered for over
    eight seconds.

**The route that works** does not touch that thread at all: `/b_setn` writes
samples straight into a ring buffer and a `Phasor` and `BufRd` read them out, over
the same paced UDP transport as every other command in this project. See
`moogone.ingress`.

**The effect runs on private buses.** The instrument's own SuperCollider source is
on the device, and every effect in it is `In.ar(inBus, 2) -> LADSPA ->
Out.ar(outBus, ...)` with both buses plain controls -- so ours points at buses
nothing else uses. No patch is modified and no gain of the user's is touched.

    uv run python3 recon/net-audio-in.py
    uv run python3 recon/net-audio-in.py --effect none      # no effect, just in and out
    uv run python3 recon/net-audio-in.py --effect et_shimmer_1 --soak 60
"""

from __future__ import annotations

import argparse
import math
import socket
import subprocess
import sys
import threading
import time

import numpy as np

SAMPLE_RATE = 48000
OUT_BYTES_PER_FRAME = 8  # the return is stereo float32


def _ssh(host: str, command: str):
    return subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes", f"root@{host}", command],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def local_address_for(host: str) -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


class Source:
    """Silence, and a blip when asked, stamped with when its samples went out.

    The stamp is taken as the samples are handed to the transport, and the other
    end of the measurement is this machine reading the returned stream -- so the
    round trip is timed on one clock and there is nothing to align.
    """

    def __init__(self, amplitude: float = 0.3) -> None:
        self.amplitude = amplitude
        self.blip_at: float | None = None
        self.samples_sent = 0
        self._fire = threading.Event()
        self._phase = 0

    def fire(self) -> None:
        self.blip_at = None
        self._fire.set()

    def __call__(self, n: int) -> list[float]:
        self.samples_sent += n
        if not self._fire.is_set():
            return [0.0] * n
        # A raised-cosine window on 1 kHz, so the onset is unambiguous even after
        # a reverb has smeared it.
        block = [
            math.sin(2 * math.pi * 1000 * i / SAMPLE_RATE)
            * (0.5 - 0.5 * math.cos(2 * math.pi * i / n))
            * self.amplitude
            for i in range(n)
        ]
        self.blip_at = time.perf_counter()
        self._fire.clear()
        return block


class Returned:
    """What comes back off the effect's bus, each chunk stamped on arrival."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.marks: list[tuple[float, int]] = []
        self.lock = threading.Lock()

    def serve(self, sock: socket.socket, stop: threading.Event) -> None:
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
                    self.marks.append((time.perf_counter(), len(self.data)))
        except (TimeoutError, OSError):
            pass
        finally:
            conn.close()

    def frames(self) -> int:
        with self.lock:
            return len(self.data) // OUT_BYTES_PER_FRAME

    def left_from(self, first_frame: int) -> np.ndarray:
        with self.lock:
            blob = bytes(self.data[first_frame * OUT_BYTES_PER_FRAME :])
        usable = len(blob) // OUT_BYTES_PER_FRAME * OUT_BYTES_PER_FRAME
        if usable == 0:
            return np.empty(0, dtype="float32")
        return np.frombuffer(blob[:usable], dtype="<f4").reshape(-1, 2)[:, 0]

    def arrival_of(self, byte_offset: int) -> float | None:
        with self.lock:
            return next((t for t, n in self.marks if n >= byte_offset), None)


def find_onset(samples: np.ndarray, floor: float = 2e-3) -> int | None:
    if samples.size == 0:
        return None
    envelope = np.convolve(np.abs(samples), np.ones(48) / 48, mode="same")
    if envelope.max() < floor:
        return None
    return int(np.argmax(envelope > envelope.max() * 0.3))


def counters(host: str) -> dict[str, tuple[int, int]]:
    """`ethext` and `usbint` packet and error counts, straight from procfs.

    Both, deliberately. §8c's finding is that flooding the LAN stalls the *voice
    controller's* transmit queue, because they are two functions of one USB
    gadget -- so watching only the interface in use would miss the failure.
    """
    got = _ssh(host, "cat /proc/net/dev")
    out: dict[str, tuple[int, int]] = {}
    for line in (got.stdout or "").splitlines():
        name, _, rest = line.partition(":")
        fields = rest.split()
        if name.strip() in ("ethext", "usbint") and len(fields) >= 12:
            errors = int(fields[2]) + int(fields[3]) + int(fields[10]) + int(fields[11])
            out[name.strip()] = (int(fields[1]) + int(fields[9]), errors)
    return out


def health(client, host: str, label: str) -> bool:
    """Is the network up, is scsynth answering, and is its disk thread free?

    Three questions, because this path can break all three separately. A wedged
    USB gadget takes the network. A dead scsynth leaves the network fine and stops
    /status. A blocked disk thread leaves BOTH of those looking perfect and stops
    only the async commands -- which is why /sync is asked here at all.
    """
    ping = subprocess.run(
        ["ping", "-c", "2", "-W", "1000", host], capture_output=True, text=True, check=False
    )
    alive = ping.returncode == 0
    ugens = None
    disk = "?"
    try:
        ugens = client.status(timeout=3.0).num_ugens
    except Exception:  # noqa: BLE001, S110 -- "did it answer" is the question
        pass
    if ugens is not None:
        at = time.perf_counter()
        try:
            client.sync(sync_id=7, timeout=2.0)
            disk = f"{(time.perf_counter() - at) * 1000:.0f}ms"
        except Exception:  # noqa: BLE001
            disk = "STALLED"
    ok = alive and ugens is not None and disk not in ("STALLED", "?")
    engine = f"{ugens} ugens" if ugens is not None else "scsynth silent"
    print(
        f"    {label:<20} {'ok' if ok else 'PROBLEM':<8} ping {'yes' if alive else 'NO':<4} "
        f"{engine:<16} disk {disk:<8}"
    )
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--port", type=int, default=14152)
    ap.add_argument("--effect", default="et_plate_1", help="an effect name, or 'none'")
    ap.add_argument("--ring", type=int, default=12000, help="ring frames; this is the latency")
    ap.add_argument("--lead", type=int, default=0, help="frames of lead; 0 means half the ring")
    ap.add_argument("--hits", type=int, default=5)
    ap.add_argument("--soak", type=float, default=30.0)
    args = ap.parse_args(argv)

    from moogone import ingress, netaudio
    from moogone.sc.client import ScClient
    from moogone.transport.udp import UdpTransport

    client = ScClient(UdpTransport(args.host, 57110))
    mac = local_address_for(args.host)
    effect = None if args.effect == "none" else args.effect
    print(f"\n  this machine is {mac}, the instrument is {args.host}\n")
    print("  health")
    if not health(client, args.host, "before anything"):
        print("\n  the instrument is not answering; nothing to test against")
        return 1
    before = counters(args.host)

    returned = Returned()
    stop = threading.Event()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", args.port))
    server.listen(1)
    server.settimeout(25)
    threading.Thread(target=returned.serve, args=(server, stop), daemon=True).start()

    source = Source()
    stream = None
    armed = None
    writer = None
    pump_stop = threading.Event()
    trips: list[float] = []
    try:
        print("\n  ingress")
        armed = ingress.arm(client, effect=effect, frames=args.ring)
        print(
            f"    {args.ring} frames of ring ({armed.seconds * 1000:.0f} ms), "
            f"{effect or 'no effect'}, returning on bus {armed.out_bus}"
        )
        # Its own client over its own socket: the writer polls /c_get four times a
        # second and this thread asks for /status and /synced, and one ScClient
        # cannot keep two threads' replies apart -- it reads whatever arrives and
        # discards what does not match, so each steals the other's answers.
        writer_client = ScClient(UdpTransport(args.host, 57110))
        writer = ingress.RingWriter(writer_client, armed, source, lead=args.lead or None)
        writer.prime()
        threading.Thread(target=writer.run, args=(pump_stop,), daemon=True).start()
        print(f"    primed {writer.lead} frames and writing at realtime")
        if not health(client, args.host, "ingress armed"):
            return 1

        stream = netaudio.arm(client, args.host, mac, args.port, bus=armed.out_bus)
        print(f"    bus {armed.out_bus} is streaming back\n")
        time.sleep(1.5)

        print("  round trip")
        for hit in range(1, args.hits + 1):
            base = returned.frames()
            source.fire()
            for _ in range(300):
                if source.blip_at is not None:
                    break
                time.sleep(0.005)
            sent = source.blip_at
            time.sleep(1.2)
            onset = find_onset(returned.left_from(base))
            if sent is None or onset is None:
                print(f"    hit {hit}: nothing came back")
                continue
            arrival = returned.arrival_of((base + onset) * OUT_BYTES_PER_FRAME)
            if arrival is None:
                continue
            trips.append((arrival - sent) * 1000)
            print(f"    hit {hit}: {trips[-1]:6.1f} ms out and back")

        print(f"\n  soak -- {args.soak:.0f}s of sustained ingress")
        started = time.perf_counter()
        blocks_at_start = writer.blocks
        while time.perf_counter() - started < args.soak:
            time.sleep(min(6.0, args.soak))
            if not health(client, args.host, f"at {time.perf_counter() - started:4.0f}s"):
                return 1
            if writer.error is not None:
                raise writer.error
        elapsed = time.perf_counter() - started
        pushed = (writer.blocks - blocks_at_start) * ingress.BLOCK / SAMPLE_RATE
        print(
            f"    pushed {pushed:.1f}s of audio in {elapsed:.1f}s "
            f"({pushed / elapsed:.3f}x realtime), rate now {writer.rate:.5f}"
        )
        print(
            f"    gap held to within {writer.worst_gap_error} frames "
            f"({writer.worst_gap_error / SAMPLE_RATE * 1000:.0f} ms) of the "
            f"{writer.lead}-frame lead"
        )
    finally:
        pump_stop.set()
        time.sleep(0.3)
        if stream is not None:
            netaudio.disarm(client, stream, quiet=True)
        if armed is not None:
            ingress.disarm(client, quiet=True)
        stop.set()
        server.close()

    print("\n  health")
    ok = health(client, args.host, "after teardown")
    after = counters(args.host)
    for name in sorted(after):
        was, now = before.get(name, (0, 0))[1], after[name][1]
        moved = after[name][0] - before.get(name, (0, 0))[0]
        print(f"    {name}: {moved} packets, errors {was} -> {now}")

    print(
        f"\n  {source.samples_sent / SAMPLE_RATE:.1f}s of audio pushed into the instrument, "
        f"{returned.frames() / SAMPLE_RATE:.1f}s came back"
    )
    if trips:
        print(
            f"  round trip: median {sorted(trips)[len(trips) // 2]:.1f} ms over "
            f"{len(trips)} hits, spread {max(trips) - min(trips):.1f} ms"
        )
        print(f"\n  AUDIO WENT THROUGH THE INSTRUMENT'S {effect or 'GRAPH'} AND CAME BACK")
    else:
        print("\n  nothing came back")
    return 0 if (ok and trips) else 1


if __name__ == "__main__":
    sys.exit(main())
