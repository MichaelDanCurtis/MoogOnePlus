#!/usr/bin/env python3
"""Listen on every MIDI input and report what the instrument actually sends.

Play notes hard and soft, press into held keys, move wheels and pedals.
"""
import sys, time
from collections import Counter
import rtmidi

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
NOTE = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]

mi = rtmidi.MidiIn()
ports = mi.get_ports()
if not ports:
    print("no MIDI inputs"); sys.exit(1)

ins = []
for n in range(len(ports)):
    m = rtmidi.MidiIn(); m.open_port(n)
    m.ignore_types(sysex=False, timing=False, active_sense=True)
    ins.append((ports[n], m))
    print(f"listening on [{n}] {ports[n]}")

print(f"\n>>> PLAY for {SECS:.0f}s — hard and soft, press INTO held keys, "
      f"move wheels/pedals <<<\n", flush=True)

kinds, ccs, chans, notes, vels = Counter(), Counter(), Counter(), [], []
polyAT, chanAT, bend, sysex = 0, 0, 0, []
t0 = time.time()
while time.time() - t0 < SECS:
    for name, m in ins:
        msg = m.get_message()
        while msg:
            d, _ = msg
            if d:
                s = d[0]
                if s == 0xF0: sysex.append(d); kinds["sysex"] += 1
                else:
                    st, ch = s & 0xF0, (s & 0x0F) + 1
                    chans[ch] += 1
                    if st == 0x90 and len(d) > 2 and d[2] > 0:
                        kinds["note on"] += 1; notes.append(d[1]); vels.append(d[2])
                    elif st in (0x80, 0x90): kinds["note off"] += 1
                    elif st == 0xA0: kinds["POLY aftertouch"] += 1; polyAT += 1
                    elif st == 0xD0: kinds["channel aftertouch"] += 1; chanAT += 1
                    elif st == 0xE0: kinds["pitch bend"] += 1; bend += 1
                    elif st == 0xB0: kinds["control change"] += 1; ccs[d[1]] += 1
                    elif st == 0xC0: kinds["program change"] += 1
            msg = m.get_message()
    time.sleep(0.001)

print("=" * 58)
print("  WHAT IT SENDS")
print("=" * 58)
for k, v in kinds.most_common(): print(f"  {k:22s} {v}")
if notes:
    lo, hi = min(notes), max(notes)
    print(f"\n  note range: {NOTE[lo%12]}{lo//12-1} ({lo}) .. {NOTE[hi%12]}{hi//12-1} ({hi})"
          f"   = {hi-lo+1} semitones")
    print(f"  velocity:   {min(vels)} .. {max(vels)}   ({len(set(vels))} distinct)")
if chans: print(f"  channels:   {sorted(chans)}")
if ccs:   print(f"  CCs seen:   {sorted(ccs)}")
print()
print("  === CAPABILITY ===")
print(f"  polyphonic aftertouch : {'YES — per-note pressure!' if polyAT else 'no'}")
print(f"  channel aftertouch    : {'yes' if chanAT else 'no'}")
print(f"  pitch bend            : {'yes' if bend else 'no'}")
print(f"  MPE-style multi-chan  : {'LIKELY' if len(chans) > 3 else 'no'}")
if sysex:
    print(f"\n  sysex ({len(sysex)}): first bytes {' '.join(f'{b:02X}' for b in sysex[0][:12])}")
