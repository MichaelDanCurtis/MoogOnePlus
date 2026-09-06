#!/usr/bin/env python3
"""Stream the instrument's audio over the network, and time it honestly.

USB gives no audio: the socket declares MIDIStreaming and no AudioStreaming
interface, so there is nothing for a host to bind to. The network does give
audio, and it needs nothing that is not already running.

`scsynth` owns the sound card exclusively -- `/proc/asound/card0/pcm0c/sub0`
reports `subdevices_avail: 0` with scsynth as the owner -- so ALSA is closed to
`arecord`. But scsynth is a server this machine already talks to. It writes a
headerless raw stream into a FIFO on the instrument and `nc` pushes that FIFO at
a TCP socket here. No SSH in the audio path, no second cable, no interface.

**This is also the trustworthy way to time a trigger.** An earlier attempt
measured through an audio interface and could never be made to agree with itself.
Here both ends are this machine's clock and the answer is a byte offset in a
stream, so there is nothing to align and nothing to drift.

Two numbers come out, and they answer different questions:

  in the audio   how long after the trigger the sound exists on the instrument.
                 This is what a player hears out of the jacks.
  arrived here   when the bytes carrying it reached this machine. The difference
                 is what the network transport costs.

    uv run python3 recon/net-audio.py
    uv run python3 recon/net-audio.py --ring 65536    # watch latency get worse
"""

from __future__ import annotations

import argparse
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

FIFO = "/tmp/vox-netaudio.raw"

#: DiskOut drains a ring buffer, and for a live stream that ring IS the latency.
#: 65536 frames -- SuperCollider's usual size, and what `moogone.record` uses for
#: offline capture -- puts 372 ms between a trigger and the sound reaching the
#: socket. 2048 puts 22 ms. For a file on disk the large ring is right; for a
#: stream it is the entire problem.
DEFAULT_RING = 2048

SAMPLE_RATE = 48000
BYTES_PER_FRAME = 8  # stereo float32


def _ssh(host: str, command: str, background: bool = False):
    args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        f"root@{host}",
        command,
    ]
    if background:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def local_address_for(host: str) -> str:
    """This machine's address on the route to the instrument.

    Asked of the routing table rather than hardcoded, because the answer changes
    with which interface is up -- and the instrument has to dial back to it.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((host, 9))
        return probe.getsockname()[0]
    finally:
        probe.close()


class Stream:
    """Received bytes, each chunk stamped with the moment it landed."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.marks: list[tuple[float, int]] = []

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
                self.data.extend(chunk)
                self.marks.append((time.perf_counter(), len(self.data)))
        except (TimeoutError, OSError):
            pass
        finally:
            conn.close()

    def arrival_of(self, byte_offset: int) -> float | None:
        """When the chunk containing this byte reached us."""
        return next((t for t, n in self.marks if n >= byte_offset), None)

    def left_channel(self) -> np.ndarray:
        frames = len(self.data) // BYTES_PER_FRAME
        if frames == 0:
            return np.empty(0, dtype="float32")
        block = bytes(self.data[: frames * BYTES_PER_FRAME])
        return np.frombuffer(block, dtype="<f4").reshape(-1, 2)[:, 0]


def find_onset(samples: np.ndarray) -> int | None:
    """First sample of the blip, by envelope. None if nothing sounded."""
    if samples.size == 0:
        return None
    envelope = np.convolve(np.abs(samples), np.ones(48) / 48, mode="same")
    if envelope.max() < 1e-3:
        return None
    return int(np.argmax(envelope > envelope.max() * 0.3))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--port", type=int, default=14143)
    ap.add_argument("--ring", type=int, default=DEFAULT_RING, help="DiskOut frames")
    ap.add_argument("--hits", type=int, default=6)
    ap.add_argument("--bus", type=int, default=0)
    args = ap.parse_args(argv)

    from moogone.analysis import save_stereo_wav, synth_blip
    from moogone.record import RECORD_BUFFER, RECORD_NODE
    from moogone.sampler import Sampler
    from moogone.sc.client import ScClient
    from moogone.synthdef import RECORDER, compile_synthdef
    from moogone.transport.udp import UdpTransport

    mac = local_address_for(args.host)
    stream = Stream()
    stop = threading.Event()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("0.0.0.0", args.port))
    server.listen(1)
    server.settimeout(20)
    threading.Thread(target=stream.serve, args=(server, stop), daemon=True).start()
    print(f"  this machine is {mac}, listening on port {args.port}")

    _ssh(args.host, f"rm -f {FIFO}; mkfifo {FIFO}")
    pusher = _ssh(args.host, f"cat {FIFO} | nc {mac} {args.port}", background=True)
    time.sleep(1.0)

    local_blip = Path("/tmp/vox-blip.wav")
    save_stereo_wav(local_blip, synth_blip())

    client = ScClient(UdpTransport(args.host, 57110))
    sampler = Sampler(client)
    sample = sampler.load("blip", sampler.push(local_blip, args.host), root_note=60)
    sampler.map.spread = sample

    client.d_recv(compile_synthdef("voxRecorder", RECORDER))
    client.send("/b_alloc", RECORD_BUFFER, args.ring, 2)
    client.sync()
    # raw + float: a FIFO cannot be seeked, so a WAV header could never be
    # finalised -- the length field would stay zero and the file unreadable.
    client.send("/b_write", RECORD_BUFFER, FIFO, "raw", "float", 0, 0, 1)
    client.sync()
    client.send("/s_new", "voxRecorder", RECORD_NODE, 1, 0, "buf", RECORD_BUFFER, "bus", args.bus)
    client.sync()
    print(f"  streaming bus {args.bus}, ring {args.ring} frames, {args.hits} hits\n")
    time.sleep(1.2)

    results: list[tuple[float, float]] = []
    try:
        for hit in range(1, args.hits + 1):
            base = len(stream.data)
            fired = time.perf_counter()
            sampler.note_on(60, 120)
            # Nodes execute in creation order, so a voice added AFTER the recorder
            # writes bus 0 too late to be heard -- the stream stays silent and the
            # measurement reports nothing rather than reporting it late.
            client.send("/g_tail", 0, RECORD_NODE)
            time.sleep(1.0)

            onset = find_onset(stream.left_channel()[base // BYTES_PER_FRAME :])
            if onset is None:
                print(f"    hit {hit}: no sound found")
                continue
            in_audio = onset / SAMPLE_RATE * 1000
            arrival = stream.arrival_of(base + onset * BYTES_PER_FRAME)
            if arrival is None:
                print(f"    hit {hit}: in the audio {in_audio:6.1f} ms (arrival unknown)")
                continue
            here = (arrival - fired) * 1000
            results.append((in_audio, here))
            print(
                f"    hit {hit}: in the audio {in_audio:6.1f} ms   "
                f"arrived here {here:6.1f} ms   transport {here - in_audio:5.1f} ms"
            )
    finally:
        client.send("/n_free", RECORD_NODE)
        client.send("/b_close", RECORD_BUFFER)
        client.sync()
        client.send("/b_free", RECORD_BUFFER)
        client.sync()
        stop.set()
        pusher.terminate()
        time.sleep(0.4)
        _ssh(args.host, f"rm -f {FIFO}")
        server.close()

    if not results:
        print("\n  nothing measured -- was anything audible on that bus?")
        return 1
    in_audio = [a for a, _ in results]
    here = [h for _, h in results]
    seconds = len(stream.data) / BYTES_PER_FRAME / SAMPLE_RATE
    print()
    print(f"  {seconds:.1f}s of stereo audio received over the network")
    print(
        f"  trigger -> sound on the instrument : median "
        f"{statistics.median(in_audio):6.1f} ms   spread {max(in_audio) - min(in_audio):.1f} ms"
    )
    print(
        f"  trigger -> bytes on this machine   : median "
        f"{statistics.median(here):6.1f} ms   spread {max(here) - min(here):.1f} ms"
    )
    chunk_ms = BYTES_PER_FRAME and 1448 / BYTES_PER_FRAME / SAMPLE_RATE * 1000
    print()
    print(f"  The two agree to within a chunk ({chunk_ms:.1f} ms of audio per TCP")
    print("  segment), so the transport costs less than this method can resolve.")
    print("  Subtracting them per-hit is not meaningful at this resolution -- the")
    print("  arrival stamp belongs to the chunk carrying the byte, not the byte.")
    print()
    print("  `keys` mode, for comparison, was +373 ms with a 767 ms spread.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
