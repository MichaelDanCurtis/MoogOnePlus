#!/usr/bin/env python3
"""What the sampler's `midi` trigger mode costs, and what is still unexplained.

`keys` mode was measured at +373 ms with a 767 ms spread, because a note travels
keyboard, voice controller, port 7772, tcpdump, an SSH pipe and back. `midi` mode
skips all of that. This measures what is left.

**The OSC round trip is the number to trust here.** It is timed directly against
this machine's clock with no audio in the path, and it is the network and server
component of every trigger.

**The onset spacing is not yet trustworthy, and the script says so rather than
printing a confident number.** Firing at exact one-second intervals and reading
the bursts back gives gaps near 900 ms, not 1000, and the implied delay falls
monotonically across a run. Three explanations were tested and eliminated:

  * the capture is not dropping frames -- differencing a 2 s and an 8 s recording
    isolates the fixed ~0.42 s stream start-up and leaves 6.000 s of audio taking
    5.97 s of wall clock, with or without concurrent OSC traffic;
  * the capture's timeline is uniform -- the instrument's idle 375 Hz block-rate
    tone reads 374.94-374.96 Hz in every window of a six-second recording;
  * the sends are exact -- a spin wait puts them within 0.01 ms of nominal, and
    `note_on` itself returns in 0.1 ms.

Hunting it did find two real bugs, both fixed and both worth more than the
measurement was: `Sampler.note_on` freed the oldest layer without the expiry test
it applied to the slot it was reusing, and `ScClient` raised a `/fail` belonging
to a fire-and-forget `/n_free` as though it were the next request's. Fixing them
cut the run-to-run spread from 127 ms to 99 ms. The residual is recorded as open.

    uv run python3 recon/sampler-latency.py --host 192.168.1.138
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 48_000
BURST_HZ = 6_000.0
BURST_MS = 40.0

#: How far apart the triggers are placed. Comfortably longer than the burst, so
#: onsets cannot merge, and short enough that ten fit in one recording.
INTERVAL_S = 0.4


def make_burst(path: Path) -> Path:
    """A short stereo burst with no fade-in: the attack is the measurement."""
    n = int(SAMPLE_RATE * BURST_MS / 1000)
    t = np.arange(n) / SAMPLE_RATE
    env = np.ones(n)
    fade = int(SAMPLE_RATE * 0.002)
    env[-fade:] = np.linspace(1.0, 0.0, fade)
    mono = (np.sin(2 * np.pi * BURST_HZ * t) * env * 0.6 * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(np.repeat(mono, 2).tobytes())
    return path


def _matched(track: np.ndarray, rate: int) -> np.ndarray:
    """Correlate against the burst itself.

    A threshold on a smoothed envelope was tried first and was not good enough: it
    fired several times inside one burst and moved its estimate by tens of
    milliseconds depending on where the amplitude happened to cross. Correlating
    against the known waveform puts the peak at the burst's start regardless of
    level, and gives sub-sample precision for free.
    """
    n = int(rate * BURST_MS / 1000)
    t = np.arange(n) / rate
    template = np.sin(2 * np.pi * BURST_HZ * t)

    spectrum = np.fft.rfft(track)
    freqs = np.fft.rfftfreq(track.size, 1 / rate)
    spectrum[(freqs < BURST_HZ * 0.8) | (freqs > BURST_HZ * 1.2)] = 0
    band = np.fft.irfft(spectrum, track.size)

    # Envelope of the correlation, so the carrier's own cycles do not put the peak
    # on an arbitrary zero crossing 1/6000 s away from the true start.
    corr = np.correlate(band, template, mode="valid")
    win = max(1, int(rate * 0.002))
    return np.sqrt(np.convolve(corr**2, np.ones(win) / win, mode="same"))


def find_onsets(track: np.ndarray, rate: int, expected: int) -> list[float]:
    """Every burst start, in seconds, by matched filter peak."""
    score = _matched(track, rate)
    if not score.any():
        return []
    threshold = score.max() * 0.4
    refractory = int(rate * INTERVAL_S * 0.6)
    onsets: list[float] = []
    i, n = 0, score.size
    while i < n:
        if score[i] > threshold:
            # The peak within this burst, not the first sample over the line.
            window = score[i : i + refractory]
            onsets.append((i + int(np.argmax(window))) / rate)
            i += refractory
        else:
            i += 1
    return onsets


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--interface", default="Komplete")
    ap.add_argument("--channel", type=int, default=0, help="1-based; 0 finds the loudest")
    ap.add_argument("--hits", type=int, default=10)
    ap.add_argument("--pings", type=int, default=40)
    args = ap.parse_args(argv)

    from moogone.capture import find_device, input_devices, record
    from moogone.sampler import Sampler
    from moogone.sc.client import ScClient
    from moogone.transport.udp import UdpTransport

    client = ScClient(UdpTransport(args.host, 57110))

    # -- the hop ----------------------------------------------------------------
    hops = []
    for _ in range(args.pings):
        t0 = time.perf_counter()
        client.status()
        hops.append((time.perf_counter() - t0) * 1000)
    print(f"  OSC round trip to scsynth over {args.pings} requests:")
    print(
        f"    median {statistics.median(hops):.2f} ms   min {min(hops):.2f}   max {max(hops):.2f}"
    )
    print()

    # -- the jitter -------------------------------------------------------------
    burst = make_burst(Path(tempfile.gettempdir()) / "vox-latency-burst.wav")
    sampler = Sampler(client)
    remote = sampler.push(burst, args.host)
    sample = sampler.load("latency", remote, root_note=60)
    sampler.map.spread = sample

    device = find_device(args.interface)
    inputs = next((d["channels"] for d in input_devices() if d["index"] == device), 2)
    channel = args.channel - 1
    if channel < 0:
        # The instrument is not necessarily on inputs 1-2 -- on the interface this
        # was written against it is on 3-4, and the first pair returns the noise
        # floor, which reads exactly like a silent instrument.
        probe, _ = record(0.6, device, channels=inputs)
        channel = int(np.argmax([np.max(np.abs(probe[:, c])) for c in range(inputs)]))
    print(
        f"  input device {device}, channel {channel + 1}, {args.hits} hits "
        f"{INTERVAL_S * 1000:g} ms apart"
    )

    import threading

    seconds = args.hits * INTERVAL_S + 1.5
    result: dict = {}

    def grab() -> None:
        result["audio"], result["rate"] = record(seconds, device, channels=inputs)

    rec = threading.Thread(target=grab)
    rec.start()
    time.sleep(0.7)

    sent = []
    start = time.perf_counter()
    for i in range(args.hits):
        target = start + i * INTERVAL_S
        while time.perf_counter() < target:
            pass  # spin: sleep() granularity is the thing being measured
        sent.append(time.perf_counter() - start)
        sampler.note_on(60, 110)
    rec.join()

    track = result["audio"][:, channel]
    rate = result["rate"]
    onsets = find_onsets(track, rate, args.hits)
    print(f"  found {len(onsets)} of {args.hits} onsets")
    if len(onsets) < 3:
        print("  not enough to measure. Is the instrument audible on that channel?")
        return 1

    gaps = [(b - a) * 1000 for a, b in itertools.pairwise(onsets)]
    nominal = INTERVAL_S * 1000
    errors = [g - nominal for g in gaps]
    print()
    for i, (g, e) in enumerate(zip(gaps, errors, strict=False), start=1):
        print(f"    gap {i:>2}: {g:7.2f} ms   error {e:+7.2f} ms")
    print()
    print(
        f"  send jitter (this machine) : "
        f"{max(abs((s - i * INTERVAL_S) * 1000) for i, s in enumerate(sent)):.2f} ms worst"
    )
    print(f"  gap median  : {statistics.median(gaps):.2f} ms  (nominal {nominal:g})")
    print(f"  gap spread  : {max(gaps) - min(gaps):.2f} ms")
    if len(errors) > 1:
        print(f"  stdev       : {statistics.stdev(errors):.2f} ms")
    print()
    print("  For comparison, `keys` mode was measured at +373 ms with a 767 ms spread.")
    print()
    print("  CAVEAT: the gaps above read short of nominal and the implied delay")
    print("  falls across a run. The capture was ruled out as the cause (see the")
    print("  module docstring); the residual is unexplained, so treat the spread")
    print("  as comparable between runs and the absolute values as provisional.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
