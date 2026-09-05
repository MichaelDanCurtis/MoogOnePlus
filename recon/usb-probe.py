#!/usr/bin/env python3
"""What the Moog One's USB socket offers, and what it does not.

Answers, without touching the instrument's settings:

  * does it present a USB audio device, the way an Elektron Digitone does?
  * does it present USB MIDI, in which directions?
  * is anything actually arriving from it?

Read-only. Nothing is sent to the instrument unless --play is given, which
sends a short chord so the input direction can be confirmed by ear.

    uv run python3 recon/usb-probe.py
    uv run python3 recon/usb-probe.py --play
"""

from __future__ import annotations

import argparse
import sys
import time

from moogone.usb import probe


def _midi_ports() -> tuple[list[str], list[str]]:
    import rtmidi

    return rtmidi.MidiOut().get_ports(), rtmidi.MidiIn().get_ports()


def _listen(name: str, seconds: float) -> int:
    """How many MIDI messages arrive from the instrument in a window."""
    import rtmidi

    mi = rtmidi.MidiIn()
    ports = mi.get_ports()
    match = next((i for i, p in enumerate(ports) if name in p), None)
    if match is None:
        return -1
    mi.open_port(match)
    # Clock and active sensing are filtered by default, and their absence is part
    # of what is being measured -- ask for everything.
    mi.ignore_types(sysex=False, timing=False, active_sense=False)
    seen, deadline = 0, time.time() + seconds
    while time.time() < deadline:
        if mi.get_message():
            seen += 1
        time.sleep(0.001)
    mi.close_port()
    return seen


def _play(name: str) -> None:
    import rtmidi

    out = rtmidi.MidiOut()
    ports = out.get_ports()
    match = next((i for i, p in enumerate(ports) if name in p), None)
    if match is None:
        print("  no USB MIDI output to play through")
        return
    out.open_port(match)
    print("  playing a chord over USB MIDI -- listen to the instrument")
    for n in (48, 52, 55, 60):
        out.send_message([0x90, n, 100])
        time.sleep(0.12)
    time.sleep(1.2)
    for n in (48, 52, 55, 60):
        out.send_message([0x80, n, 0])
    out.close_port()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--play", action="store_true", help="send a chord over USB MIDI")
    ap.add_argument("--listen", type=float, default=3.0, metavar="SECONDS")
    ap.add_argument("--name", default="Moog One", help="MIDI port name to match")
    args = ap.parse_args(argv)

    devices = probe()
    if not devices:
        print("No Moog One on USB. Is the cable in, and the instrument powered?")
        return 1

    for d in devices:
        print(f"{d.vendor_name} {d.name}   {d.vendor:#06x}:{d.product:#06x}")
        print(f"  configurations: {d.configurations}", end="")
        if d.unread_configurations:
            print(f"  ({d.unread_configurations} not selected by the host, contents unknown)")
        else:
            print()
        for i in d.interfaces:
            print(f"    if#{i.number} alt{i.alternate}  {i.label:<14} endpoints={i.endpoints}")
        print()
        print(f"  USB MIDI  : {'yes' if d.has_midi else 'no'}")
        print(f"  USB audio : {'yes' if d.has_audio else 'no'}", end="")
        print("" if d.has_audio else "   <- no AudioStreaming interface, so none exists")

    outs, ins = _midi_ports()
    print()
    print(f"  CoreMIDI out ports: {outs}")
    print(f"  CoreMIDI in  ports: {ins}")

    if args.play:
        print()
        _play(args.name)

    print()
    print(f"  listening {args.listen:g}s for anything from {args.name!r}...")
    n = _listen(args.name, args.listen)
    if n < 0:
        print("    no such input port")
    elif n == 0:
        print("    nothing. MIDI out is off in the preset -- see docs §8a:")
        print("    /p/part/t/{1,2,3}/in/midi_out/en is False in all 398 factory presets.")
    else:
        print(f"    {n} messages -- MIDI out is enabled, so the keys reach the host.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
