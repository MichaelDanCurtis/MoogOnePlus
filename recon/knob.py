#!/usr/bin/env python3
"""Turn one knob. Learn what the instrument calls it, and watch its screens.

    uv run python3 recon/knob.py "filter cutoff"

It counts you in, records for a few seconds while you move ONE control, and then
says which parameter id moved. It also reports what the OLED displays sent in the
same window, which is how the panel geometry gets checked against reality rather
than against a guess made during a screen saver.

Nothing is written to the instrument. This reads a bus it is already talking on.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moogone.display import DISPLAY_PORT, decode_tile
from moogone.stream import BusStream
from moogone.voicebus import VOICE_BUS_PORT
from moogone.voicebus import decode as decode_x
from moogone.vox.learn import Learner, LearnError, ParamMap

MAP_PATH = Path("presets") / "params.json"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("name", nargs="?", help="what you are about to turn, e.g. 'filter cutoff'")
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--seconds", type=float, default=8.0)
    ap.add_argument("--countdown", type=float, default=3.0)
    ap.add_argument("--screens-only", action="store_true", help="just report display geometry")
    a = ap.parse_args(argv)

    if not a.screens_only and not a.name:
        ap.error("name what you are about to turn, or pass --screens-only")

    learner = Learner()
    tiles: dict[int, Counter] = defaultdict(Counter)
    extent: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    seen_params: Counter = Counter()

    def on_datagram(sport, dport, payload):
        if dport == VOICE_BUS_PORT or sport == VOICE_BUS_PORT:
            write = decode_x(payload)
            if write is not None:
                learner.feed(write.param, write.value)
                seen_params[write.param] += 1
        elif dport == DISPLAY_PORT or sport == DISPLAY_PORT:
            tile = decode_tile(payload)
            if tile is not None:
                tiles[tile.display][(tile.x, tile.width, tile.y, tile.height)] += 1
                e = extent[tile.display]
                e[0] = max(e[0], tile.x + tile.width)
                e[1] = max(e[1], tile.y + tile.height)

    stream = BusStream(a.host, (VOICE_BUS_PORT, DISPLAY_PORT), on_datagram)
    thread = threading.Thread(target=stream.run, daemon=True)
    thread.start()
    time.sleep(2.5)  # let the remote tcpdump come up before counting anyone in

    if not a.screens_only:
        try:
            learner.begin(a.name)
        except LearnError as exc:
            print(f"  {exc}")
            stream.stop()
            return 2

    for n in range(int(a.countdown), 0, -1):
        print(f"  {n} ...", flush=True)
        time.sleep(1.0)
    if a.screens_only:
        print(f"\n  >>> TOUCH THE PANEL — press buttons, change pages — for {a.seconds:.0f}s\n")
    else:
        print(f"\n  >>> TURN '{a.name}' NOW — one control only — for {a.seconds:.0f}s\n")
    time.sleep(a.seconds)
    print("  ... done, reading.\n")
    stream.stop()
    thread.join(timeout=5)

    if tiles:
        print("  SCREENS — what the displays actually sent:")
        for display in sorted(tiles):
            xs = sorted({g[0] for g in tiles[display]})
            ys = sorted({g[2] for g in tiles[display]})
            ws = sorted({g[1] for g in tiles[display]})
            hs = sorted({g[3] for g in tiles[display]})
            total = sum(tiles[display].values())
            print(f"    /od/{display}:  {total} tiles, {len(tiles[display])} distinct")
            print(f"       x {xs}   width {ws}")
            print(f"       y {ys}   height {hs}")
            print(f"       implies a {extent[display][0]} x {extent[display][1]} surface")
    else:
        print("  SCREENS — nothing drew. They are probably asleep; touch the panel.")

    if a.screens_only:
        return 0

    result = learner.finish()
    print()
    if result.ok:
        param_map = ParamMap.load(MAP_PATH)
        try:
            param_map.learn(result.param, a.name)
            param_map.save(MAP_PATH)
        except LearnError as exc:
            print(f"  learned param {result.param}, but not saved: {exc}")
            return 1
        print(f"  LEARNED: '{a.name}' is parameter {result.param}   (saved to {MAP_PATH})")
    else:
        print(f"  NOT LEARNED: {result.reason}")
        if seen_params:
            print("  parameters that moved at all:")
            for param, n in seen_params.most_common(6):
                print(f"     {param:<8}{n} write(s)")
        else:
            print("  Nothing at all came over the voice bus. Either the control was not")
            print("  moved, or it is one the engine does not announce.")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
