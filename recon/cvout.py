"""Ask the voice controller whether /hw/cvout/0 is real.

The firmware's string table carries `/hw/cvout/0` next to `/hw/.../bclk`, `din0`
and `usb` -- the hardware-peripheral namespace -- and nothing on the panel or in
`las-frontend` exposes it. The controller answers queries with a status vocabulary
(`404 Not found`, `503 Unavailable`), so an address that exists can be told from one
that does not without writing anything.

Every query is zero-argument. The harness self-tests against a known-good and a
known-bad address first, because a query mechanism that silently returns nothing is
indistinguishable from an address that does not exist -- which is the single easiest
way to conclude something false here.

    uv run python3 recon/cvout.py --host 192.168.1.137
"""

from __future__ import annotations

import argparse
import subprocess

from moogone.vx import interpret, parse_hexdump, render_remote_command

#: Known-good and known-bad, to prove the harness before believing a sweep.
CONTROL_GOOD = "/info/product"
CONTROL_BAD = "/no/such/address/at/all"

TARGETS = (
    # The leaves las-sc itself sends to. If these answer, /hw/ is live and any 404
    # beside them is that leaf's own absence, not a dead namespace.
    "/hw/mute",
    "/hw/hpf",
    "/hw/autoroute",
    "/hw/autor",
    # The target, and the shapes it might really take.
    "/hw/cvout/0",
    "/hw/cvout",
    "/hw/cvin/0",
    # Other leaves the firmware string table puts beside cvout.
    "/hw/hs/start-offset",
)


def ask(host: str, address: str, wait: int = 1) -> str:
    cmd = render_remote_command(address, wait=wait)
    proc = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes",
         "-o", "ConnectTimeout=8", f"root@{host}", "sh"],
        input=cmd, capture_output=True, text=True, check=False, timeout=wait + 25,
    )
    try:
        raw = parse_hexdump(proc.stdout)
    except ValueError:
        return f"unreadable reply: {proc.stdout.strip()[:80]!r} {proc.stderr.strip()[:80]!r}"
    try:
        reply = interpret(address, raw)
    except (ValueError, TypeError) as exc:
        return f"{len(raw)} bytes, {exc}"
    detail = f"  args={reply.args}" if reply.args else ""
    return f"{reply.kind:<12} ({len(raw)} bytes){detail}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="192.168.1.137")
    args = ap.parse_args()

    print("harness self-test")
    good = ask(args.host, CONTROL_GOOD)
    bad = ask(args.host, CONTROL_BAD)
    print(f"  {CONTROL_GOOD:<26} {good}")
    print(f"  {CONTROL_BAD:<26} {bad}")
    if good.startswith(("silent", "unreadable")):
        print("\n  the known-good address answered nothing: the harness is broken,")
        print("  and every result below would read as 'does not exist'. Stopping.")
        return 1
    print()

    print("targets")
    for address in TARGETS:
        print(f"  {address:<26} {ask(args.host, address)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
