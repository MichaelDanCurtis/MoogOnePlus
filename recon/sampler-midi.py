#!/usr/bin/env python3
"""Play the sampler from the Moog's own keyboard over USB MIDI.

This is the `midi` trigger mode with nothing plugged in but the USB cable. It
needs **MIDI Out enabled on the instrument**, which no factory preset does: the
switch is per-preset at `/p/part/t/{1,2,3}/in/midi_out/en`, and the port
selection at `/p/part/midi_io/midi_out_ports` has to include USB. See
`docs/MOOG-ONE-INTERNALS.md` §8a.

Run it, then play. Every note that arrives is printed and triggers a sample, so
silence on screen means the notes are not reaching this machine -- which is a
setting on the instrument, not a fault here.

    uv run python3 recon/sampler-midi.py
    uv run python3 recon/sampler-midi.py --seconds 60 --sample /tmp/vox-blip.wav
"""

from __future__ import annotations

import argparse
import sys
import time
import wave
from pathlib import Path

import numpy as np


def default_sample(path: Path) -> Path:
    """A short pitched blip, so a triggered sample is obvious against the voice."""
    if path.exists():
        return path
    sr, seconds = 48000, 0.35
    t = np.arange(int(sr * seconds)) / sr
    env = np.exp(-t * 14.0)
    body = (
        np.sin(2 * np.pi * 880 * t)
        + 0.5 * np.sin(2 * np.pi * 1760 * t)
        + 0.25 * np.sin(2 * np.pi * 2640 * t)
    )
    click = np.exp(-t * 400.0) * np.random.default_rng(7).normal(0, 1, t.size) * 0.7
    x = np.clip((body * env + click) * 0.55, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.repeat((x * 32767).astype("<i2"), 2).tobytes())
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--port", default="Moog One", help="MIDI input name to match")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--sample", default="/tmp/vox-blip.wav")
    args = ap.parse_args(argv)

    import rtmidi

    from moogone.sampler import Sampler, trigger_from_midi
    from moogone.sc.client import ScClient
    from moogone.transport.udp import UdpTransport

    local = default_sample(Path(args.sample))
    client = ScClient(UdpTransport(args.host, 57110))
    sampler = Sampler(client)
    sample = sampler.load("blip", sampler.push(local, args.host), root_note=60)
    sampler.map.spread = sample
    print(f"  sample loaded on the instrument: {sample.frames} frames")

    midi_in = rtmidi.MidiIn()
    ports = midi_in.get_ports()
    index = next((i for i, p in enumerate(ports) if args.port in p), None)
    if index is None:
        print(f"  no MIDI input matching {args.port!r}. Available: {ports}")
        return 1
    midi_in.open_port(index)
    # Clock and active sensing would drown the print; notes are what matter here.
    midi_in.ignore_types(sysex=True, timing=True, active_sense=True)

    print(f"  listening on {ports[index]!r} for {args.seconds:g}s")
    print("  >>> PLAY THE KEYBOARD <<<\n")

    notes = 0
    deadline = time.time() + args.seconds
    while time.time() < deadline:
        message = midi_in.get_message()
        if message is None:
            time.sleep(0.0005)
            continue
        data = message[0]
        node = trigger_from_midi(sampler, data)
        if len(data) >= 3 and (data[0] & 0xF0) in (0x80, 0x90):
            notes += 1
            on = (data[0] & 0xF0) == 0x90 and data[2] > 0
            print(
                f"    {'on ' if on else 'off'} note {data[1]:>3} vel {data[2]:>3} "
                f"ch{(data[0] & 0x0F) + 1}" + (f"  -> node {node}" if node else "")
            )
    midi_in.close_port()

    print(f"\n  {notes} note events")
    if notes == 0:
        print("  Nothing arrived. On the instrument, check that MIDI Out is enabled")
        print("  for the timbre you played AND that the MIDI out port selection")
        print("  includes USB rather than DIN alone.")
        return 1
    print("  midi mode works: those notes triggered samples with no capture in the path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
