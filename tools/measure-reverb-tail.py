#!/usr/bin/env python3
"""Measure what a reverb control actually does, and print it as catalogue data.

A slider that reads `0.80` tells a musician nothing. This renders an impulse
through the real UGen at a series of control values, measures the decay to
-60 dB, and prints the pairs that `moogd/engine/catalogue.json` carries so the
page can read out in seconds.

It exists because the alternative was guessing. On 2026-09-12 a reverb was
blamed for a note that would not stop, and a default was about to be changed on
that suspicion. Rendering it showed `room = 0.8` is a 2.4 second tail -- an
ordinary hall -- and that every setting, up to and including 1.0, decays to
numerical silence. The reverb could not have done what it was accused of. The
real cause was a latched sustain.

    python3 tools/measure-reverb-tail.py

Needs SuperCollider for the render (non-realtime, no audio device, nothing
touches the instrument) and numpy/soundfile for the measurement.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from moogone.synthdef import sclang_path

#: The control values to render. Dense where the curve bends.
ROOMS = [0.3, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
DURATION = 30
RATE = 48000

SCORE = """(
var rooms = %(rooms)s;
var dur = %(dur)d, sr = %(sr)d;
var def = SynthDef(\\tail, { |room = 0.8, damp = 0.4|
    var imp = Impulse.ar(0) * 0.5;
    Out.ar(0, FreeVerb2.ar(imp, imp, 1.0, room, damp));
});
var bytes = def.asBytes;
var go = { |f|
    var room = rooms.removeAt(0);
    var path = "%(dir)s/room_%%.wav".format(room.asString.replace(".", "p"));
    Score([
        [0.0, ['/d_recv', bytes]],
        [0.0, ['/s_new', \\tail, 1000, 0, 0, 'room', room, 'damp', 0.4]],
        [dur, ['/c_set', 0, 0]]
    ]).recordNRT(
        outputFilePath: path, sampleRate: sr, headerFormat: "WAV",
        sampleFormat: "float", duration: dur,
        action: { if (rooms.size > 0) { f.value(f) } { 0.exit } }
    );
};
go.value(go);
)
"""


def t60(path: str) -> float | None:
    """Seconds until the tail is 60 dB down and stays there."""
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(path)
    mono = x.mean(axis=1) if x.ndim > 1 else x
    n = int(sr * 0.02)
    blocks = mono[: len(mono) // n * n].reshape(-1, n)
    rms = np.sqrt((blocks**2).mean(axis=1)) + 1e-12
    db = 20 * np.log10(rms / rms.max())
    for i in range(len(db)):
        # The first block after which it never rises above -60 again. A simple
        # first-crossing would be fooled by the gaps between early reflections.
        if db[i] < -60 and (db[i:] < -60).all():
            return i * 0.02
    return None


def main() -> int:
    sc = sclang_path()
    if not sc:
        print("no sclang; install SuperCollider to re-measure", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        scd = os.path.join(tmp, "render.scd")
        Path(scd).write_text(SCORE % {
            "rooms": "[" + ", ".join(str(r) for r in ROOMS) + "]",
            "dur": DURATION, "sr": RATE, "dir": tmp,
        })
        subprocess.run([sc, scd], capture_output=True, timeout=900)
        pairs = []
        for f in sorted(glob.glob(os.path.join(tmp, "room_*.wav"))):
            m = re.search(r"room_(\d)p(\d)", f)
            room = float(f"{m.group(1)}.{m.group(2)}")
            t = t60(f)
            pairs.append((room, t))
        if not pairs:
            print("nothing rendered", file=sys.stderr)
            return 1
        print(f"{'room':>5} {'T60 (s)':>9}")
        for room, t in sorted(pairs):
            print(f"{room:>5.1f} {('%.1f' % t) if t else '  >%d' % DURATION:>9}")
        print("\ncatalogue readout:")
        print("  " + str([[r, round(t, 1)] for r, t in sorted(pairs) if t]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
