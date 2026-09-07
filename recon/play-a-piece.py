#!/usr/bin/env python3
"""A short piece for the Moog One's FM engine, through its own effects rack.

Everything sounding here is made inside the instrument: `moogone.fm` synthesises
the voices in `scsynth`, `moogone.effect` routes them through one of Moog's own
LADSPA effects on private buses, and a monitor sums the result to the main outs.
No audio crosses the network in either direction -- only the notes.

Three sections, each a different pairing, because the point is that the effect is
now something you can *change* rather than something chosen once at boot:

    Cathedral + GLASS      sparse high partials with a four-second decay, in a hall
    Shimmer   + BELL       inharmonic bell tones, pitch-shifted upward as they fade
    Tape Echo + E PIANO    harmonic and rhythmic, so the repeats can be counted

    uv run --extra capture python3 recon/play-a-piece.py
    uv run --extra capture python3 recon/play-a-piece.py --no-record
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

SAMPLE_RATE = 48000

#: A minor, the four chords, low to high.
AM = (57, 60, 64, 69, 72, 76)
F = (53, 57, 60, 65, 69, 72)
C = (48, 55, 60, 64, 67, 72)
G = (55, 59, 62, 67, 71, 74)
PROGRESSION = (AM, F, C, G)


def arpeggio(chord, step: float, velocity: int = 100):
    """Up the chord, one note per `step` seconds."""
    for note in chord:
        yield note, velocity, step


def sparse(chord, step: float, velocity: int = 95):
    """Only the top three, spaced out, so a long tail has room to be heard."""
    for note in chord[3:]:
        yield note, velocity, step


def pulse(chord, step: float, velocity: int = 105):
    """Root, fifth, octave, root -- eighth-note movement under a delay."""
    for note in (chord[0], chord[2], chord[4], chord[2]):
        yield note, velocity, step


SECTIONS = (
    ("Cathedral", "GLASS", arpeggio, 0.55, 1, "a hall, and notes that outlive the chord"),
    ("Shimmer", "BELL", sparse, 1.05, 1, "bells rising as they fade"),
    ("Tape Echo", "E PIANO", pulse, 0.30, 2, "repeats you can count"),
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="192.168.1.138")
    ap.add_argument("--amp", type=float, default=0.18, help="FM voice amplitude")
    ap.add_argument("--no-record", action="store_true")
    ap.add_argument(
        "--out",
        default="captures/moog-fm-through-the-rack.wav",
        help="where to write the recording of the analog outs",
    )
    args = ap.parse_args(argv)

    from moogone.effect import EffectSend
    from moogone.fm import FMEngine
    from moogone.sc.client import ScClient
    from moogone.transport.udp import UdpTransport

    client = ScClient(UdpTransport(args.host, 57110))
    print(f"\n  instrument: {client.status(timeout=5).num_ugens} ugens")

    fm = FMEngine(client)
    fm.ensure_synthdefs()
    send = EffectSend(client)
    send.attach(fm)

    frames: list = []
    stop = threading.Event()
    recorder = None
    if not args.no_record:
        import sounddevice as sd

        def record():
            # Six channels because the instrument's main outs arrive on 3 and 4 of
            # this interface, not 1 and 2; the pair is picked out afterwards.
            with sd.InputStream(
                device="Komplete Audio 6 MK2",
                channels=6,
                samplerate=SAMPLE_RATE,
                blocksize=1024,
            ) as stream:
                while not stop.is_set():
                    block, _ = stream.read(1024)
                    frames.append(block.copy())

        recorder = threading.Thread(target=record, daemon=True)
        recorder.start()
        time.sleep(1.0)
        print("  recording the analog outs\n")

    try:
        for effect_preset, fm_preset, pattern, step, repeats, note in SECTIONS:
            # attach BEFORE the recall: engage() re-applies the routing to
            # whatever is attached at that moment, and switching effects goes
            # through engage().
            send.attach(fm)
            chosen = send.recall(effect_preset)
            fm.recall(fm_preset)
            fm.configure(amp=args.amp, _from_recall=True)
            print(f"  {effect_preset} + {fm_preset} -- {note}")
            for _ in range(repeats):
                for chord in PROGRESSION:
                    for pitch, velocity, hold in pattern(chord, step):
                        fm.note_on(pitch, velocity)
                        time.sleep(hold)
            # Let the tail through before the next effect takes the bus.
            time.sleep(2.5 if chosen.effect.startswith("et_") else 1.5)

        print("\n  closing on A minor, and letting it ring")
        send.attach(fm)
        send.recall("Cathedral")
        fm.recall("GLASS")
        fm.configure(amp=args.amp, _from_recall=True)
        for pitch in (57, 64, 69, 76):
            fm.note_on(pitch, 90)
            time.sleep(0.7)
        # GLASS decays for four seconds and the hall keeps going well past that,
        # and disengage() stops the effect dead. Five seconds cut the last chord
        # off mid-tail -- the final second of the take still read a tenth of the
        # piece's own level. Wait for it to actually finish.
        time.sleep(10.0)
    finally:
        send.disengage()
        try:
            client.sync(timeout=5.0)
        except Exception:  # noqa: BLE001, S110 -- the status line below reports it
            pass
        stop.set()
        if recorder is not None:
            recorder.join(timeout=5)

    if frames:
        import numpy as np
        import soundfile as sf

        audio = np.concatenate(frames)
        levels = [
            float(np.sqrt(np.mean(audio[:, c].astype("float64") ** 2)))
            for c in range(audio.shape[1])
        ]
        best = int(np.argmax(levels))
        pair = (best, best + 1) if best % 2 == 0 else (best - 1, best)
        take = audio[:, list(pair)]
        peak = float(np.max(np.abs(take)))
        sf.write(args.out, take, SAMPLE_RATE, subtype="PCM_24")
        print(
            f"\n  {len(take) / SAMPLE_RATE:.1f}s recorded from inputs "
            f"{pair[0] + 1} and {pair[1] + 1}"
        )
        print(f"  peak {peak:.3f}" + ("  CLIPPING" if peak >= 0.99 else ""))
        print(f"  wrote {args.out}")

    print(f"\n  instrument: {client.status(timeout=5).num_ugens} ugens")
    return 0


if __name__ == "__main__":
    sys.exit(main())
