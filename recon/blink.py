#!/usr/bin/env python3
"""Try to drive the Moog One's panel LEDs, and watch the wire while doing it.

    uv run python3 recon/blink.py            # alternate all-on / all-off
    uv run python3 recon/blink.py --seconds 20

`las-frontend` paints the panel by sending blobs to the controller on port 9100.
`/lsleds` is the big field — 184 bytes — and it refreshes only a couple of times a
second, which is slow enough that an injected frame could hold long enough to see.
`/lfoleds` refreshes about 95 times a second and is hopeless to fight.

**This is a write to the instrument.** Only to its LEDs, which are output and are
repainted by the frontend within about half a second, so the worst case is a flicker
that corrects itself. It is here because whether it works at all is an open
question, and the answer needs a person looking at the panel.

Delivery is confirmed independently: the frames are captured arriving. So a "no"
means the panel ignores them, not that they were lost.

**Answered on 2026-09-03: nothing lights up.** A hundred alternating frames over six
seconds, watched on the instrument, produced no visible change. The panel ignores
LED frames that are not las-frontend's, and it is not deciding that by source port —
las-frontend itself sends from several different ephemeral ports. The likely gate is
the startup cookie its argv and log refer to; see docs/MOOG-ONE-INTERNALS.md.

The tool is kept because the question is worth re-asking after a firmware change,
and because it is the cheapest possible write to try: LEDs are output, repainted
twice a second regardless, with no state to corrupt.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import time

SSH = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=15",
]

#: Byte length of each LED field, measured on the wire.
FIELDS = {"lsleds": 184, "seqleds": 24, "lfoleds": 4, "clkleds": 4}


def osc_blob(address: str, blob: bytes) -> bytes:
    a = address.encode()
    a += b"\x00" * (4 - len(a) % 4 or 4)
    return a + b",b\x00\x00" + struct.pack("!I", len(blob)) + blob


def printf_escape(data: bytes) -> str:
    return "".join(f"\\x{b:02x}" for b in data)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--field", default="lsleds", choices=sorted(FIELDS))
    ap.add_argument("--seconds", type=float, default=12.0)
    ap.add_argument("--countdown", type=float, default=5.0)
    a = ap.parse_args(argv)

    size = FIELDS[a.field]
    on = printf_escape(osc_blob(f"/{a.field}", b"\xff" * size))
    off = printf_escape(osc_blob(f"/{a.field}", b"\x00" * size))

    for n in range(int(a.countdown), 0, -1):
        print(f"  {n} ...", flush=True)
        time.sleep(1.0)
    print(f"\n  >>> WATCH THE PANEL — {a.seconds:.0f}s of /{a.field} on/off <<<\n", flush=True)

    # One nc per datagram, backgrounded and killed: GNU netcat 0.7.1 does not exit on
    # UDP. That caps the rate at roughly 17 alternations a second, which is plenty.
    rounds = max(1, int(a.seconds / 0.28))
    script = f"""
export PATH=/usr/sbin:/sbin:/usr/bin:/bin
blast() {{
  printf "$1" | nc -u 203.0.113.2 9100 >/dev/null 2>&1 &
  p=$!
  sleep 0.14
  kill $p 2>/dev/null
}}
i=0
while [ $i -lt {rounds} ]; do
  blast '{on}'
  blast '{off}'
  i=$((i+1))
done
echo done
"""
    started = time.time()
    subprocess.run(
        SSH + [f"root@{a.host}", "sh"],
        input=script,
        capture_output=True,
        text=True,
        timeout=max(120, a.seconds * 6),
        check=False,  # the panel never answers; a non-zero exit is not the result
    )
    print(f"  {rounds * 2} frames over {time.time() - started:.1f}s")
    print("\n  Did anything flash? If not, the panel ignores frames that are not")
    print("  las-frontend's — which is the same answer /x gave for parameters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
