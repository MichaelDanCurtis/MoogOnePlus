#!/usr/bin/env python3
"""Find the knobs in a photo of the panel, and write them as clickable hotspots.

    uv run python3 recon/hotspots.py src/moogone/vox/static/moog_one_01_3.webp

The photo itself is not in this repository — panel photography is Moog's — so this
generates the coordinates from whatever image you supply rather than shipping them.

**It does not try to work out which control each knob is.** Guessing that from a
photograph would produce a map that looks authoritative and is wrong in places nobody
would check. The instrument names its own parameters when you turn them, so a hotspot
is bound by clicking it and moving the real knob: see the Learn card.

Detection is deliberately dull: bright, colourless, roughly circular blobs inside the
dark control surface. Knob caps are light grey; the panel is black; LEDs are coloured;
the background is white but outside the surface. Those four facts are the whole method.
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

import numpy as np

#: A knob cap, in pixels, in a photo about 1350 wide. Anything much smaller is a
#: screw or a letter; anything much larger is a screen or a wooden cheek.
MIN_PX, MAX_PX = 9, 34
MIN_AREA = 55


def load_rgb(path: Path) -> np.ndarray:
    """Any format `sips` can read, via BMP because it needs no image library."""
    with tempfile.TemporaryDirectory() as tmp:
        bmp = Path(tmp) / "panel.bmp"
        subprocess.run(["sips", "-s", "format", "bmp", str(path), "--out", str(bmp)],
                       capture_output=True, check=False)
        if not bmp.exists():
            raise SystemExit(f"could not convert {path} (is sips available?)")
        data = bmp.read_bytes()
    offset = struct.unpack("<I", data[10:14])[0]
    width, height = struct.unpack("<ii", data[18:26])
    h = abs(height)
    stride = ((width * 3) + 3) & ~3
    img = np.frombuffer(data[offset : offset + stride * h], dtype=np.uint8)
    img = img[: stride * h].reshape(h, stride)[:, : width * 3].reshape(h, width, 3)
    if height > 0:           # BMP rows run bottom-up unless the height is negative
        img = img[::-1]
    return img[:, :, ::-1].copy()          # BGR -> RGB


def control_surface(lum: np.ndarray) -> tuple[int, int, int, int]:
    """The dark band above the keyboard: where knobs are, and the white page is not."""
    dark = lum < 70
    rows = np.nonzero(dark.mean(axis=1) > 0.35)[0]
    cols = np.nonzero(dark.mean(axis=0) > 0.25)[0]
    if not len(rows) or not len(cols):
        raise SystemExit("found no dark control surface; is this a photo of the panel?")
    upper = rows[rows < lum.shape[0] * 0.60]
    return int(cols.min()), int(upper.min()), int(cols.max()), int(upper.max())


def find_knobs(rgb: np.ndarray, bounds: tuple[int, int, int, int]) -> list[dict]:
    r, g, b = (rgb[:, :, 0].astype(int), rgb[:, :, 1].astype(int), rgb[:, :, 2].astype(int))
    lum = (r * 299 + g * 587 + b * 114) // 1000
    x0, y0, x1, y1 = bounds
    grey = (np.abs(r - g) < 30) & (np.abs(g - b) < 30) & (np.abs(r - b) < 30)
    mask = np.zeros(lum.shape, bool)
    mask[y0:y1, x0:x1] = True
    mask &= grey & (lum > 120)

    seen = np.zeros(mask.shape, bool)
    found = []
    for sy, sx in zip(*np.nonzero(mask)):
        if seen[sy, sx]:
            continue
        queue = deque([(sy, sx)])
        seen[sy, sx] = True
        points = []
        while queue:
            y, x = queue.popleft()
            points.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if y0 <= ny < y1 and x0 <= nx < x1 and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
        if len(points) < MIN_AREA:
            continue
        pts = np.array(points)
        top, bottom = pts[:, 0].min(), pts[:, 0].max()
        left, right = pts[:, 1].min(), pts[:, 1].max()
        w, h = right - left + 1, bottom - top + 1
        if not (MIN_PX <= w <= MAX_PX and MIN_PX <= h <= MAX_PX):
            continue
        if not 0.65 < w / h < 1.55:          # round, not a strip of label text
            continue
        if len(points) / (w * h) < 0.55:     # solid, not a ring or an outline
            continue
        found.append({"cx": int((left + right) / 2), "cy": int((top + bottom) / 2),
                      "w": int(w), "h": int(h)})
    # Reading order: rows down the panel, left to right within a row.
    found.sort(key=lambda k: (k["cy"] // 22, k["cx"]))
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("image", help="a top-down photo of the panel")
    ap.add_argument("--out", default="src/moogone/vox/static/hotspots.json")
    a = ap.parse_args(argv)

    rgb = load_rgb(Path(a.image))
    height, width = rgb.shape[:2]
    lum = (rgb[:, :, 0].astype(int) * 299 + rgb[:, :, 1].astype(int) * 587
           + rgb[:, :, 2].astype(int) * 114) // 1000
    bounds = control_surface(lum)
    knobs = find_knobs(rgb, bounds)

    spots = [
        {"id": f"k{i:02d}",
         "x": round(k["cx"] / width, 5),
         "y": round(k["cy"] / height, 5),
         "r": round(max(k["w"], k["h"]) / 2 / width, 5)}
        for i, k in enumerate(knobs)
    ]
    Path(a.out).write_text(json.dumps({
        "image": Path(a.image).name,
        "width": width, "height": height,
        "surface": {"x0": bounds[0], "y0": bounds[1], "x1": bounds[2], "y1": bounds[3]},
        "note": "positions only; which control each one is comes from Learn",
        "spots": spots,
    }, indent=1))
    print(f"  control surface: x {bounds[0]}-{bounds[2]}, y {bounds[1]}-{bounds[3]}")
    print(f"  {len(spots)} knobs -> {a.out}")
    return 0 if spots else 1


if __name__ == "__main__":
    sys.exit(main())
