#!/usr/bin/env python3
"""Ask the voice controller what it thinks it is holding, and the buses what is sounding.

Two independent axes, which is the whole point. The mask on port 7772 is the
allocator's own account of which analog voices are gated (`moogone.performance`);
`/api/scan` is what the audio buses actually carry. Neither alone identifies a
stuck note -- together they name which half is lying:

    mask 0, quiet      healthy
    mask 0, LOUD       the allocator lost a voice that is still gated
    mask set, LOUD     the allocator is still holding -- no note-off reached it
    mask set, quiet    leaked map entry, no sound

Before this, the allocator was unobservable from here: las-sc does not answer
queries and the allocator lives behind the XMOS. It was never unobservable -- the
voice controller has been reporting to Linux on 7772 the whole time.

**Bounded twice**: `-c` caps packets, the kill caps wall clock. A `-c` that never
fills waits forever, and an unbounded capture on this instrument preceded an
RT-throttle lockup that needed a power cycle.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "src"))
from moogone import pcap, performance  # noqa: E402

# Anything below this on every bus is silence; the instrument's own floor sits
# around -80 dB with nothing playing.
SILENCE_DB = -70.0


def buses(host: str) -> list[float]:
    try:
        with urllib.request.urlopen(f"http://{host}:8080/api/scan", timeout=20) as r:
            return json.load(r)["buses_db"]
    except Exception as exc:  # noqa: BLE001 - a probe should not die on a dead endpoint
        print(f"  (scan unavailable: {exc})")
        return []


def capture(host: str, seconds: int, sink: dict) -> None:
    script = f"""
rm -f /tmp/voices.pcap
/usr/sbin/tcpdump -p -i usbint -c 1500 -s 512 -w /tmp/voices.pcap 'udp port 7772' >/tmp/voices.log 2>&1 &
TP=$!
sleep {seconds}
kill $TP 2>/dev/null; sleep 1; kill -9 $TP 2>/dev/null; wait $TP 2>/dev/null; sync
"""
    subprocess.run(["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes",
                    f"root@{host}", script], check=False, timeout=seconds + 60)
    got = subprocess.run(["ssh", "-o", "ConnectTimeout=6", "-o", "BatchMode=yes", f"root@{host}",
                          "cat /tmp/voices.pcap; rm -f /tmp/voices.pcap"],
                         capture_output=True, timeout=60)
    sink["raw"] = got.stdout


def panic_now(out, log, heavy: bool = False):
    """Clear held voices. The light form is 32 messages, not 2080.

    The exhaustive per-note sweep drowns a 7772 capture in its own note-offs, and
    it turns out not to be needed: CC120 alone clears the leaked voice.
    """
    for ch in range(16):
        for cc in (64, 66, 123, 120):
            out.send_message([0xB0 | ch, cc, 0]); time.sleep(0.002)
    if heavy:
        for ch in range(16):
            for note in range(128):
                out.send_message([0x80 | ch, note, 0]); time.sleep(0.001)
    log.append((time.time(), "PANIC"))
    print(f"  PANIC ({'exhaustive' if heavy else 'light: CC64/66/123/120 x16'})", flush=True)


def send(out, msg, label, log):
    out.send_message(msg)
    log.append((time.time(), label))
    print(f"  {label}", flush=True)
    # 1 ms minimum between datagrams anywhere near this instrument.
    time.sleep(0.005)


SCRIPTS = {
    "control": "one note, held 2 s, released",
    "pc-while-held": "note held, program change under it, then note-off",
    "pc-then-play": "program change, then a note played and released",
    "chord-pc": "three notes held, program change under them, then note-offs",
    "churn": "notes and program changes interleaved fast",
    "sustain-pc": "sustain on, note, program change, sustain off, note-off",
    "idle": "nothing sent -- just observe",
    "hunt-channel": "leak one voice, then note-off the same note on each channel in turn",
    "hunt-note": "leak one voice, then note-off every note on ch1 to find which one owns it",
    "twice": "a note, then a full panic, then another note: does the leak need a preset load?",
    "ladder-low": "five DIFFERENT notes in the lower split zone (Moog C0-E4 = MIDI 0-52)",
    "ladder-high": "five DIFFERENT notes in the upper split zone (Moog F4-G10 = MIDI 53-127)",
    "repeat": "the same single note played and released five times over",
}


def run_script(name: str, out, log) -> None:
    if name == "control":
        send(out, [0x90, 48, 100], "note 48 ON", log); time.sleep(2.0)
        send(out, [0x80, 48, 0], "note 48 OFF", log); time.sleep(3.0)
    elif name == "pc-while-held":
        send(out, [0x90, 48, 100], "note 48 ON", log); time.sleep(1.5)
        send(out, [0xC0, 5], "PROGRAM CHANGE 5", log); time.sleep(2.0)
        send(out, [0x80, 48, 0], "note 48 OFF", log); time.sleep(3.0)
    elif name == "pc-then-play":
        send(out, [0xC0, 7], "PROGRAM CHANGE 7", log); time.sleep(2.5)
        send(out, [0x90, 48, 100], "note 48 ON", log); time.sleep(1.5)
        send(out, [0x80, 48, 0], "note 48 OFF", log); time.sleep(3.0)
    elif name == "chord-pc":
        for n in (48, 52, 55, 60):
            send(out, [0x90, n, 100], f"note {n} ON", log); time.sleep(0.2)
        time.sleep(1.0)
        send(out, [0xC0, 9], "PROGRAM CHANGE 9", log); time.sleep(1.5)
        for n in (48, 52, 55, 60):
            send(out, [0x80, n, 0], f"note {n} OFF", log); time.sleep(0.2)
        time.sleep(3.0)
    elif name == "churn":
        for i, n in enumerate((48, 52, 55, 59, 62, 65)):
            send(out, [0x90, n, 100], f"note {n} ON", log); time.sleep(0.15)
            if i % 2 == 0:
                send(out, [0xC0, 10 + i], f"PROGRAM CHANGE {10+i}", log)
            time.sleep(0.15)
        time.sleep(0.8)
        for n in (48, 52, 55, 59, 62, 65):
            send(out, [0x80, n, 0], f"note {n} OFF", log); time.sleep(0.12)
        time.sleep(3.0)
    elif name == "sustain-pc":
        send(out, [0xB0, 64, 127], "CC64 sustain ON", log); time.sleep(0.3)
        send(out, [0x90, 48, 100], "note 48 ON", log); time.sleep(0.5)
        send(out, [0x80, 48, 0], "note 48 OFF (pedal holds)", log); time.sleep(1.0)
        send(out, [0xC0, 11], "PROGRAM CHANGE 11", log); time.sleep(1.5)
        send(out, [0xB0, 64, 0], "CC64 sustain OFF", log); time.sleep(3.0)
    elif name == "repeat":
        for i in range(5):
            send(out, [0x90, 48, 100], f"[{i}] note 48 ON", log); time.sleep(1.0)
            send(out, [0x80, 48, 0], f"[{i}] note 48 OFF", log); time.sleep(1.4)
    elif name in ("ladder-low", "ladder-high"):
        # Different notes each time. Replaying one note cannot distinguish a per-note
        # leak from a timbre that is still holding that same note and so never asks
        # for a second voice for it.
        notes = (36, 40, 43, 47, 50) if name == "ladder-low" else (60, 64, 67, 71, 74)
        for n in notes:
            send(out, [0x90, n, 100], f"note {n} ON", log); time.sleep(1.0)
            send(out, [0x80, n, 0], f"note {n} OFF", log); time.sleep(1.4)
    elif name == "twice":
        send(out, [0x90, 40, 100], "note 40 ON", log); time.sleep(1.0)
        send(out, [0x80, 40, 0], "note 40 OFF", log); time.sleep(1.5)
        panic_now(out, log); time.sleep(3.0)
        send(out, [0x90, 43, 100], "note 43 ON", log); time.sleep(1.0)
        send(out, [0x80, 43, 0], "note 43 OFF", log); time.sleep(3.0)
    elif name == "hunt-note":
        # CC120 does not release the leaked voice but the exhaustive sweep does, so
        # the voice is registered under some note number. Walk them and watch the mask.
        send(out, [0x90, 40, 100], "note 40 ON", log); time.sleep(1.0)
        send(out, [0x80, 40, 0], "note 40 OFF", log); time.sleep(1.5)
        print("  sweeping note-offs 0..127 on channel 1", flush=True)
        for n in range(128):
            out.send_message([0x80, n, 0]); time.sleep(0.03)
        time.sleep(2.5)
    elif name == "hunt-channel":
        # 128 note-offs on channel 1 do not release it, but the exhaustive panic --
        # which differs only by covering all 16 channels -- does. So the phantom
        # voice answers on some other channel.
        send(out, [0x90, 40, 100], "note 40 ON", log); time.sleep(1.0)
        send(out, [0x80, 40, 0], "note 40 OFF", log); time.sleep(1.5)
        for ch in range(1, 16):
            send(out, [0x80 | ch, 40, 0], f"note 40 OFF on channel {ch + 1}", log)
            time.sleep(0.45)
        time.sleep(2.5)
    elif name == "idle":
        time.sleep(6.0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog="scripts:\n" + "\n".join(f"  {k:14} {v}" for k, v in SCRIPTS.items()))
    ap.add_argument("script", choices=sorted(SCRIPTS))
    ap.add_argument("--host", default="192.168.1.136")
    ap.add_argument("--seconds", type=int, default=18)
    ap.add_argument("--program", type=int, default=None,
                    help="load this program first: voice count per note is a property of the preset")
    ap.add_argument("--panic-first", action="store_true",
                    help="clear every held voice before measuring, so the run starts from a known floor")
    ap.add_argument("--settle", type=float, default=6.0, help="seconds to wait before the after-reading")
    args = ap.parse_args()
    if args.seconds > 60:
        ap.error("refusing an effectively unbounded capture on this instrument")

    if args.program is not None or args.panic_first:
        import rtmidi as _rt
        _o = _rt.MidiOut()
        _p = [i for i, n in enumerate(_o.get_ports()) if "moog one" in n.lower()]
        if _p:
            _o.open_port(_p[0])
            if args.program is not None:
                _o.send_message([0xC0, args.program])
                print(f"loaded program {args.program}")
                time.sleep(3.0)
            if args.panic_first:
                for ch in range(16):
                    for cc in (64, 66, 123, 120):
                        _o.send_message([0xB0 | ch, cc, 0]); time.sleep(0.002)
                for ch in range(16):
                    for note in range(128):
                        _o.send_message([0x80 | ch, note, 0]); time.sleep(0.001)
                print("panicked; waiting for the tail to decay")
            _o.close_port()
            time.sleep(8.0)

    print(f"before: buses {fmt(buses(args.host))}")
    sink: dict = {}
    t = threading.Thread(target=capture, args=(args.host, args.seconds, sink))
    t.start()
    time.sleep(4.0)  # tcpdump needs to be up before the first note

    import rtmidi
    out = rtmidi.MidiOut()
    ports = [i for i, n in enumerate(out.get_ports()) if "moog one" in n.lower()]
    if not ports:
        print("no 'Moog One' MIDI output found"); return 1
    out.open_port(ports[0])
    log: list = []
    run_script(args.script, out, log)
    out.close_port()
    t.join()

    dg = pcap.datagrams(sink.get("raw", b""))
    print()
    held = None
    if not dg:
        print("no datagrams captured")
    else:
        t0 = dg[0].ts
        last = None
        for x in dg:
            m = performance.decode(x.payload)
            if m is None:
                continue
            dt = x.ts - t0
            if isinstance(m, performance.Note):
                print(f"{dt:7.3f}  note {m.note:3d}  {'OFF' if m.is_note_off else f'ON  vel {m.midi_velocity}'}")
                last = None
            elif isinstance(m, performance.Voices):
                held = m
                # A preset load emits the same all-clear many times over; collapse it.
                if last == m.mask:
                    continue
                last = m.mask
                print(f"{dt:7.3f}     -> mask 0x{m.mask:04x}  {m.count} sounding {list(m.voices)}")

    time.sleep(args.settle)
    after = buses(args.host)
    print(f"\nafter:  buses {fmt(after)}")

    loud = [(i, v) for i, v in enumerate(after) if v > SILENCE_DB]
    print()
    # The port is silent at idle, so seeing no mask is not the same as seeing a mask
    # of zero. Conflating them once produced a confident "orphaned voice" verdict from
    # a capture that contained no allocator data at all.
    if held is None:
        state = "allocator state unknown -- no mask was emitted in this window"
        print(f"VERDICT: {state}; buses {'are loud: ' + fmtloud(loud) if loud else 'at the floor'}")
        if loud:
            print("         play and release one note to elicit a fresh mask")
        return 0
    n_held = held.count
    if n_held == 0 and not loud:
        print("VERDICT: healthy -- allocator holds nothing, buses at the floor")
    elif n_held == 0 and loud:
        print(f"VERDICT: *** ORPHANED VOICE *** allocator holds nothing, but {fmtloud(loud)}")
        print("         a gated voice the allocator has lost track of: no note-off can reach it")
    elif n_held and loud:
        print(f"VERDICT: *** STILL HELD *** allocator holds {n_held} ({list(held.voices)}), and {fmtloud(loud)}")
        print("         the note-off never reached the allocator, or it was told to hold")
    else:
        print(f"VERDICT: allocator holds {n_held} ({list(held.voices)}) but the buses are quiet")
    return 0


def fmt(b: list[float]) -> str:
    return "quiet" if b and max(b) <= SILENCE_DB else (f"max {max(b):.1f} dB" if b else "?")


def fmtloud(loud) -> str:
    return "buses " + ", ".join(f"{i}={v:.1f}dB" for i, v in loud)


if __name__ == "__main__":
    raise SystemExit(main())
