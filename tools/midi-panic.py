#!/usr/bin/env python3
"""Stop a stuck note or a latched sustain.

    uv run --extra vox python3 tools/midi-panic.py

Diagnosed live: with both sustain pedals physically unplugged, the instrument held
every note indefinitely. The Moog was sending no MIDI at all -- listened for six
seconds, zero messages -- so it was not an outgoing loop. Something upstream had sent
sustain-on and never sent the off. This cleared it immediately.

The usual culprit is a controller powering up, changing mode, or a DAW being stopped
mid-phrase, any of which can leave CC64 latched. The instrument is behaving
correctly: it was told to hold, and it held.

Sends, on all 16 channels:

    CC64  = 0    sustain off          <- the usual cause
    CC66  = 0    sostenuto off
    CC123 = 0    all notes off
    CC120 = 0    all sound off

then an explicit note-off for all 128 notes, because CC123 is advisory and some
instruments ignore it while holding a note that arrived before it.

Sending these is safe and ordinary -- it is what every DAW sends on stop.
"""

from __future__ import annotations

import sys
import time


def panic(port_match: str = "Moog") -> int:
    try:
        import rtmidi
    except ImportError:
        print("python-rtmidi is missing. Run with:  uv run --extra vox python3 …")
        return 1

    out = rtmidi.MidiOut()
    ports = out.get_ports()
    matches = [i for i, n in enumerate(ports) if port_match.lower() in n.lower()]
    if not matches:
        print(f"No MIDI output matching {port_match!r}. Ports seen:")
        for i, n in enumerate(ports):
            print(f"  {i}: {n}")
        return 1

    idx = matches[0]
    out.open_port(idx)
    print(f"panicking {ports[idx]!r}")

    for ch in range(16):
        for cc in (64, 66, 123, 120):
            out.send_message([0xB0 | ch, cc, 0])
            time.sleep(0.002)
    for ch in range(16):
        for note in range(128):
            out.send_message([0x80 | ch, note, 0])

    out.close_port()
    print("  sustain off, sostenuto off, all notes off, all sound off, 16 channels")
    print("  plus an explicit note-off for every note")
    return 0


if __name__ == "__main__":
    raise SystemExit(panic(sys.argv[1] if len(sys.argv) > 1 else "Moog"))
