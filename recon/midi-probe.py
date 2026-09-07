#!/usr/bin/env python3
"""Play the instrument over MIDI while capturing both of its internal buses.

The question this exists to answer: when a note or an expression gesture arrives,
what do the Moog One's two computers say to each other? Everything the loopback
interface records was caused by the probe, because `lo` is measured completely
silent at idle — zero packets in twelve seconds.

It also fails honestly. If nothing appears on either bus, MIDI did not reach the
instrument, and the script says that rather than reporting an empty capture as a
result. That is not a hypothetical: the first run produced exactly this, and the
cause was upstream of every line of software here.

Usage:
    uv run python3 recon/midi-probe.py [--host H] [--port-index N] [--channel C]
    uv run python3 recon/midi-probe.py --list
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moogone.pcap import datagrams, summarise
from moogone.performance import PERFORMANCE_PORT, Note, decode
from moogone.vox.meters import SshMeterSource, to_dbfs

# Inlined rather than held in a variable: in zsh a string variable does NOT word-split
# when used as a command, so `$SSH host cmd` runs a program literally named
# "ssh -o ...". This project has been bitten by that three times.
SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ConnectTimeout=15",
]


def ssh(host: str, script: str) -> str:
    return subprocess.run(
        ["ssh", *SSH_OPTS, f"root@{host}", script],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    ).stdout


def start_capture(host: str) -> None:
    ssh(
        host,
        """
export PATH=/usr/sbin:/sbin:/usr/bin:/bin
rm -f /tmp/lo.pcap /tmp/vb.pcap /tmp/lo.err /tmp/vb.err
nohup tcpdump -i lo     -n -s 0 -w /tmp/lo.pcap udp >/dev/null 2>/tmp/lo.err &
echo $! > /tmp/lo.pid
nohup tcpdump -i usbint -n -s 0 -w /tmp/vb.pcap udp >/dev/null 2>/tmp/vb.err &
echo $! > /tmp/vb.pid
sleep 1
""",
    )


def stop_capture(host: str) -> str:
    return ssh(
        host,
        """
export PATH=/usr/sbin:/sbin:/usr/bin:/bin
kill $(cat /tmp/lo.pid) $(cat /tmp/vb.pid) 2>/dev/null
sleep 1
echo "lo $(grep -o '[0-9]* packets captured' /tmp/lo.err)"
echo "usbint $(grep -o '[0-9]* packets captured' /tmp/vb.err)"
""",
    )


def fetch(host: str, remote: str, local: Path) -> None:
    # -O: the instrument has no sftp-server, so scp must use the legacy protocol.
    subprocess.run(
        ["scp", "-O", "-q", *SSH_OPTS, f"root@{host}:{remote}", str(local)],
        timeout=180,
        check=False,
    )


def play(port_index: int, channel: int) -> None:
    import rtmidi

    out = rtmidi.MidiOut()
    names = out.get_ports()
    if not names:
        sys.exit("no MIDI output ports at all")
    out.open_port(port_index)
    print(f"  sending on: {names[port_index]}  (channel {channel + 1})")

    def send(*b):
        out.send_message(list(b))

    def sweep(fn, values, label, dt=0.02):
        for v in values:
            fn(v)
            time.sleep(dt)
        print(f"    {label}")

    updown = list(range(0, 128, 4)) + list(range(127, -1, -4))
    chord = [48, 55, 60, 64]

    for n in chord:
        send(0x90 | channel, n, 100)
        time.sleep(0.12)
    print("    chord on")

    sweep(lambda v: send(0xB0 | channel, 1, v), updown, "CC1 mod wheel")
    sweep(lambda v: send(0xB0 | channel, 74, v), updown, "CC74 brightness")
    sweep(
        lambda v: send(0xE0 | channel, v & 0x7F, (v >> 7) & 0x7F),
        list(range(8192, 16383, 200)) + list(range(16383, 8192, -200)),
        "pitch bend",
    )
    send(0xE0 | channel, 0, 64)
    sweep(lambda v: send(0xD0 | channel, v), updown, "channel aftertouch")
    # Poly aftertouch is the one the per-voice pressure project turns on.
    for v in range(0, 128, 8):
        for n in chord:
            send(0xA0 | channel, n, v)
        time.sleep(0.03)
    print("    POLY aftertouch")

    for n in chord:
        send(0x80 | channel, n, 0)
    print("    chord off")
    # close_port rather than `del out`: the nested send() closes over `out`, so
    # deleting the name leaves a closure referring to something gone.
    out.close_port()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--port-index", type=int, default=0)
    ap.add_argument("--channel", type=int, default=0, help="0-15, i.e. MIDI channel minus one")
    ap.add_argument("--list", action="store_true", help="list MIDI ports and exit")
    ap.add_argument("--baseline", default="captures/voice-bus-idle-2026-09-03.pcap")
    a = ap.parse_args()

    if a.list:
        import rtmidi

        print("outputs:")
        for i, n in enumerate(rtmidi.MidiOut().get_ports()):
            print(f"  [{i}] {n}")
        print("inputs:")
        for i, n in enumerate(rtmidi.MidiIn().get_ports()):
            print(f"  [{i}] {n}")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    caps = Path("captures")
    caps.mkdir(exist_ok=True)
    lo_path, vb_path = caps / f"control-midi-{stamp}.pcap", caps / f"voicebus-midi-{stamp}.pcap"

    print("starting capture on lo and usbint ...")
    start_capture(a.host)
    print("playing ...")
    play(a.port_index, a.channel)
    time.sleep(1.5)
    print(stop_capture(a.host).strip())
    fetch(a.host, "/tmp/lo.pcap", lo_path)
    fetch(a.host, "/tmp/vb.pcap", vb_path)

    lo = summarise(lo_path.read_bytes())[1] if lo_path.exists() else {}
    vb = summarise(vb_path.read_bytes())[1] if vb_path.exists() else {}

    print("\n=== THE CONTROL PATH (lo) — silent at idle, so all of this is the probe ===")
    if lo:
        for (p, addr, tags), n in sorted(lo.items(), key=lambda kv: -kv[1]):
            print(f"  :{p:<6} {addr:<32} ,{tags:<10} n={n}")
    else:
        print("  nothing.")

    print("\n=== THE VOICE BUS (usbint) — what is new against the idle baseline ===")
    base = Path(a.baseline)
    known = set(summarise(base.read_bytes())[1]) if base.exists() else set()
    new = {k: v for k, v in vb.items() if k not in known}
    if new:
        for (p, addr, tags), n in sorted(new.items(), key=lambda kv: -kv[1]):
            flag = "   <-- NOT TEMPERATURE" if not addr.startswith("/therm") else ""
            print(f"  :{p:<6} {addr:<32} ,{tags:<10} n={n}{flag}")
    else:
        print("  nothing the idle capture did not already show.")

    print("\n=== NOTE EVENTS decoded from port 7772 ===")
    notes = [
        m
        for d in datagrams(vb_path.read_bytes())
        if d.src_port == PERFORMANCE_PORT
        for m in [decode(d.payload)]
        if isinstance(m, Note)
    ]
    if notes:
        for n in notes[:12]:
            kind = "off" if n.is_note_off else f"on  vel {n.midi_velocity}"
            print(f"  note {n.note:<4}{kind}")
        if len(notes) > 12:
            print(f"  ... and {len(notes) - 12} more")
    else:
        print("  none.")

    # Bus traffic alone is NOT proof either way, which this script learned the hard
    # way: it once reported "MIDI did not arrive" while the instrument was audibly
    # playing. The meters read the analog output level off the voice bus, so they
    # answer the question the buses cannot -- did a sound actually happen.
    print("\n=== OUTPUT METERS — did a sound actually happen? ===")
    src = SshMeterSource(a.host, wait=1)

    def peak(label):
        r = src.read()
        if not r:
            print(f"  {label:<24} <no reply>")
            return None
        v = max(to_dbfs(*r[k]) for k in ("/a/stat/mainl", "/a/stat/mainr"))
        print(f"  {label:<24} {v:6.1f} dBFS")
        return v

    import rtmidi

    quiet = peak("silent")
    out = rtmidi.MidiOut()
    out.open_port(a.port_index)
    for n in (48, 55, 60, 64):
        out.send_message([0x90 | a.channel, n, 110])
        time.sleep(0.03)
    time.sleep(1.0)
    loud = peak("holding a chord")
    for n in (48, 55, 60, 64):
        out.send_message([0x80 | a.channel, n, 0])
    out.close_port()

    audible = quiet is not None and loud is not None and loud - quiet > 6
    if audible:
        print(f"  rise: {loud - quiet:+.1f} dB")

    print()
    if audible or notes:
        print("VERDICT: MIDI reached the instrument.")
        if notes and not audible:
            print(
                "  Notes were reported on 7772 but the meters did not move — the notes"
                "\n  are being received and allocated, but something downstream is silent"
                "\n  (volume, preset, or output routing)."
            )
        if audible and not notes:
            print(
                "  Audible, but no note events were captured. The capture window and the"
                "\n  playing may simply not have overlapped."
            )
        return 0
    print(
        "VERDICT: no evidence the MIDI arrived — no note events, and no level change.\n"
        "  Check, in this order:\n"
        "    1. Cable direction — the interface's MIDI *OUT* must go to the Moog's\n"
        "       MIDI *IN*. Out-to-out looks identical and does nothing.\n"
        "    2. The Moog's MIDI IN is enabled, and on this channel (--channel).\n"
        "    3. --list, and --port-index if the interface is not [0]."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
