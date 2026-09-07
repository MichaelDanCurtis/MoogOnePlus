"""Measure what every effect in the rack actually costs, on the instrument.

The CPU_COST table was built from busybox `top`, which on this box reports a
fraction of BOTH cores -- so every figure in it was roughly half the load it
described, and then doubled by hand into something that was neither. This measures
each effect the way the throttle sees it: the busiest scsynth thread's share of one
core, with the effect engaged and with it parked, differenced.

Nothing is freed. A /n_free on a LADSPA node terminates scsynth (isolated 2/2); the
et_ family pauses itself on release and gives the CPU back, which is what makes this
loop possible at all.

    uv run python3 recon/effect-cpu.py --osc 192.168.1.138 --ssh 192.168.1.137
"""

from __future__ import annotations

import argparse
import statistics
import time

from moogone.effect import EFFECTS, EffectSend, stop_effect
from moogone.load import measure
from moogone.sc.client import ScClient
from moogone.transport.udp import UdpTransport


def median_of(ssh: str, n: int) -> float | None:
    seen = [v for v in (measure(ssh) for _ in range(n)) if v]
    return statistics.median(seen) if seen else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--osc", default="192.168.1.138", help="the address scsynth REPLIES from")
    ap.add_argument("--ssh", default="192.168.1.137")
    ap.add_argument("--samples", type=int, default=2)
    args = ap.parse_args()

    client = ScClient(UdpTransport(args.osc, 57110))
    send = EffectSend(client)
    send.ensure_groups()
    send.ensure_monitor()

    idle = client.status().num_ugens
    print(f"instrument: {idle} ugens, nothing of ours engaged\n")
    print(f"{'effect':<20} {'engaged':>9} {'baseline':>9} {'cost':>8}")
    print("-" * 50)

    results: dict[str, float] = {}
    for name in EFFECTS:
        if name == "voxSpring":
            send.ensure_spring()
        base = median_of(args.ssh, args.samples)
        try:
            send.engage(name)
        except Exception as exc:  # noqa: BLE001 -- a rack we cannot engage is data too
            print(f"{name:<20} {'--':>9} {'--':>9}  {exc}")
            continue
        time.sleep(1.0)
        hot = median_of(args.ssh, args.samples)
        stop_effect(client, send.node)
        send.engaged, send.node = False, 0
        time.sleep(1.0)
        if base is None or hot is None:
            print(f"{name:<20} {'--':>9} {'--':>9}   not measured")
            continue
        cost = hot - base
        results[name] = cost
        print(f"{name:<20} {hot * 100:8.1f}% {base * 100:8.1f}% {cost * 100:+7.1f}")

    print("\nCPU_COST = {")
    for name, cost in sorted(results.items(), key=lambda kv: -kv[1]):
        print(f'    "{name}": {max(0.0, round(cost, 2))},')
    print("}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
