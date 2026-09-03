#!/usr/bin/env python3
"""Query the Moog One voice-card bus with zero-argument OSC messages.

  uv run python3 vxq.py /info/product /v/voices
  uv run python3 vxq.py --card 0 /info/version /info/hwrev
  uv run python3 vxq.py --file addresses.txt
  uv run python3 vxq.py --self-test

Unlike `vxping`, this sends no argument at all, so there is no value in the
packet for a setter to store. See src/moogone/vx.py for why that matters.

Every sweep begins with a self-test against a known-good and a known-bad address.
If that fails the sweep does not run — a harness that reports "silent" for
everything is indistinguishable from a dead bus, and that mistake has already
been made once on this instrument.
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from moogone.vx import (
    VC_HOST,
    VC_PORT,
    card_address,
    interpret,
    parse_hexdump,
    render_remote_command,
)

DEVICE = "192.168.1.138"
SSH = [
    "ssh",
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "ConnectTimeout=10",
]

# An address known to answer, and one known to 404. A sweep whose harness cannot
# tell these apart is not measuring the instrument.
CANARY_VALUE = "/info/product"
CANARY_404 = "/definitely/not/an/address/here"


def run_batch(addresses: list[str], host: str, port: int, wait: int, device: str) -> dict[str, str]:
    """Run every query in one SSH session. Returns {address: hexdump}."""
    lines = []
    for a in addresses:
        cmd = render_remote_command(a, host=host, port=port, wait=wait)
        # Tab-separated so an empty hexdump still yields a parsable row.
        lines.append(f'printf "%s\\t" "{a}"; {cmd}; echo')
    script = "\n".join(lines)

    # Each query costs `wait` plus netcat startup — measured at roughly 1.2x the
    # nominal wait. Budget for that, or a long sweep times out at the very end
    # and every result is lost, because the batch only returns once.
    budget = max(120, int((wait + 0.6) * len(addresses)) + 60)
    try:
        proc = subprocess.run(
            [*SSH, f"root@{device}", "sh"],
            input=script,
            capture_output=True,
            text=True,
            check=False,
            timeout=budget,
        )
    except subprocess.TimeoutExpired:
        sys.exit(
            f"ssh timed out after {budget}s with {len(addresses)} addresses queued.\n"
            f"The batch returns all at once, so nothing was recovered. Split the "
            f"address list into smaller files and sweep them separately."
        )
    if proc.returncode != 0 and not proc.stdout.strip():
        sys.exit(f"ssh failed: {proc.stderr.strip()[:400]}")

    out: dict[str, str] = {}
    for row in proc.stdout.splitlines():
        if "\t" not in row:
            continue
        addr, _, hexdump = row.partition("\t")
        out[addr.strip()] = hexdump.strip()
    return out


def query(addresses: list[str], host: str, port: int, wait: int, device: str):
    raw = run_batch(addresses, host, port, wait, device)
    for a in addresses:
        if a not in raw:
            yield None, a, "no row returned for this address"
            continue
        try:
            yield interpret(a, parse_hexdump(raw[a])), a, None
        except (ValueError, TypeError) as exc:
            yield None, a, str(exc)


def self_test(host: str, port: int, wait: int, device: str) -> bool:
    """Prove the harness can tell a value from a 404 before trusting a sweep."""
    results = {}
    for reply, addr, err in query([CANARY_VALUE, CANARY_404], host, port, wait, device):
        results[addr] = (reply, err)

    good, good_err = results.get(CANARY_VALUE, (None, "missing"))
    bad, bad_err = results.get(CANARY_404, (None, "missing"))

    ok_good = good is not None and good.is_value
    ok_bad = bad is not None and bad.kind == "not_found"

    print("  self-test")
    print(f"    known-good {CANARY_VALUE:<36} {good if good else 'ERROR: ' + str(good_err)}")
    print(f"    known-bad  {CANARY_404:<36} {bad if bad else 'ERROR: ' + str(bad_err)}")
    if ok_good and ok_bad:
        print("    -> harness discriminates value from 404\n")
        return True
    print("    -> HARNESS FAILED; refusing to sweep (results would be meaningless)\n")
    return False


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("addresses", nargs="*", help="OSC addresses to query")
    p.add_argument("--file", help="file of addresses, one per line (# comments ok)")
    p.add_argument("--card", type=int, help="scope each address to voice card 0-15")
    p.add_argument("--device", default=DEVICE, help=f"synth IP (default {DEVICE})")
    p.add_argument("--host", default=VC_HOST, help=f"bus host (default {VC_HOST})")
    p.add_argument("--port", type=int, default=VC_PORT, help=f"bus port (default {VC_PORT})")
    p.add_argument("--wait", type=int, default=1, help="seconds to wait per reply")
    p.add_argument("--self-test", action="store_true", help="run only the self-test")
    p.add_argument("--values-only", action="store_true", help="hide 404s and silences")
    p.add_argument("--no-self-test", action="store_true", help="skip the self-test (not advised)")
    args = p.parse_args()

    if args.self_test:
        sys.exit(0 if self_test(args.host, args.port, args.wait, args.device) else 1)

    addrs = list(args.addresses)
    if args.file:
        with open(args.file) as fh:
            addrs += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    if args.card is not None:
        addrs = [card_address(args.card, a) for a in addrs]
    if not addrs:
        p.error("no addresses given")

    if not args.no_self_test and not self_test(args.host, args.port, args.wait, args.device):
        sys.exit(1)

    counts = {"value": 0, "ack": 0, "unavailable": 0, "not_found": 0, "silent": 0, "error": 0}
    for reply, addr, err in query(addrs, args.host, args.port, args.wait, args.device):
        if err:
            counts["error"] += 1
            print(f"  ERROR      {addr}   {err}")
            continue
        counts[reply.kind] += 1
        if args.values_only and not reply.is_value:
            continue
        print(f"  {reply}")

    print(
        f"\n  {counts['value']} value, {counts['ack']} ack, "
        f"{counts['unavailable']} unavailable, {counts['not_found']} absent, "
        f"{counts['silent']} silent, {counts['error']} error   "
        f"({len(addrs)} queried)"
    )
    print(
        "  'ack' = the handler exists and answered with no arguments. "
        "That proves presence, not a reading."
    )
    if counts["silent"]:
        print("  note: silent != absent. The bus drops replies; re-query before concluding.")


if __name__ == "__main__":
    main()
