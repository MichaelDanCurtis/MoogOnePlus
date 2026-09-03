#!/usr/bin/env python3
"""Emit a shell one-liner that sends an OSC message to las-sc on the device.

las-sc listens on 127.0.0.1:9300 (loopback only) and replies to las-frontend
on :7775, never to us — so we send and observe the effect, we don't read back.

  python3 lassc_send.py /lc/kbd/tr i 7
  python3 lassc_send.py /lc/kbd/tr f 7.0
"""
import sys
from moogone.osc import OscMessage

addr, typ = sys.argv[1], sys.argv[2]
raw = sys.argv[3] if len(sys.argv) > 3 else None
args = []
if raw is not None:
    args = [int(raw)] if typ == "i" else [float(raw)]

pkt = OscMessage(addr, args).encode()
hexesc = "".join(f"\\x{b:02x}" for b in pkt)
print(f"# {addr} {typ}={raw}   ({len(pkt)} bytes)")
print(f"# {' '.join(f'{b:02x}' for b in pkt)}")
print(f'printf "{hexesc}" > /tmp/o.bin && '
      f'( nc -u -w 1 127.0.0.1 9300 < /tmp/o.bin >/dev/null 2>&1 & ) ; '
      f'sleep 2 ; killall nc 2>/dev/null ; echo sent')
