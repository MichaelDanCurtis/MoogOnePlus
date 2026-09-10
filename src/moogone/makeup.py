"""A makeup gain stage for the instrument's main output.

Measured on the instrument, 2026-09-04, at maximum MIDI volume with eight notes at
velocity 127 — the loudest it can be made to go:

    voices arriving from the ADC (bus 12)   peak  -7.4 dBFS, floor  -93.9
    main output leaving to the DAC (bus 0)  peak -20.6 dBFS, floor -112.9

**Correction, 2026-09-09.** That measurement is of bus 0, which is main
**right** -- not "the main output". Worse, this module used to read `In.ar(bus,
2)` from bus 0, which is buses 0 and 1: main right and *sub* right. It raised
the right channel of two different outputs and left main left alone. The main
pair is buses **7 and 0**, non-adjacent, per `synthdefs.scd:564-565`:

    Out.ar(7, main[0] * -1);   // left
    Out.ar(0, main[1] * -1);   // right

so a single `In.ar(bus, 2)` cannot express it and the graph now reads and
replaces the two buses separately.

The input stage is staged well. The output is not: it drives the converter **20 dB
below full scale**, which puts the DAC's own analog noise 20 dB closer to the music
than it needs to be. That is the gain-staging half of the complaint this project was
opened about, and unlike the effects noise it is real and measurable.

This inserts a gain stage at the tail of the root group. Two details matter:

- **`ReplaceOut`, not `Out`.** `Out` mixes into the bus; this has to replace what is
  there, or the result is the original signal plus a louder copy of itself.
- **A limiter after the gain.** The makeup cannot clip the converter no matter what
  it is set to, which is what makes it safe to try on an instrument you care about.

What this does **not** fix: the noise already present on the way in. Bus 12 arrives
with a -93.9 dBFS floor from the analog voice path and its ADC, and raising the
output lifts that with everything else. The gain here improves the ratio against the
**DAC** and the analog stages after it — you then turn the physical volume down by
the same amount, and what you have bought is that much less output-side noise at the
same listening level. Whether that is audible depends on which end dominates, and
answering that means recording the analog outputs, which nothing here does yet.

It is a runtime insert. A reboot removes it.
"""

from __future__ import annotations

from dataclasses import dataclass

from .effect import MAIN_LEFT, MAIN_RIGHT
from .synthdef import compile_synthdef

#: Node id for the gain stage. High, to sit clear of the instrument's own graph.
MAKEUP_NODE = 90300

#: `ReplaceOut` so this is a gain stage rather than a second copy mixed in, and a
#: `Limiter` so no setting of `gain` can send the converter past `ceiling`.
#: The two main buses are 7 (left) and 0 (right) -- not adjacent -- so this reads
#: and replaces each on its own rather than taking two consecutive channels.
MAKEUP_GRAPH = (
    "|left = 7, right = 0, gain = 1, ceiling = 0.95| "
    "ReplaceOut.ar(left, Limiter.ar(In.ar(left, 1) * gain, ceiling, 0.005)); "
    "ReplaceOut.ar(right, Limiter.ar(In.ar(right, 1) * gain, ceiling, 0.005))"
)

#: Measured headroom on the main bus. The default target leaves a few dB spare
#: rather than driving to the ceiling and relying on the limiter to catch every peak.
MEASURED_HEADROOM_DB = 20.6
DEFAULT_GAIN_DB = 12.0


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def gain_to_db(gain: float) -> float:
    import math

    if gain <= 0:
        raise ValueError("gain must be positive")
    return 20.0 * math.log10(gain)


@dataclass(frozen=True)
class Makeup:
    node: int
    left: int
    right: int
    gain_db: float
    ceiling: float


def apply(client, gain_db: float = DEFAULT_GAIN_DB, left: int = MAIN_LEFT,
          right: int = MAIN_RIGHT, ceiling: float = 0.95,
          node: int = MAKEUP_NODE) -> Makeup:
    """Insert the gain stage, replacing any previous one.

    Freeing first makes this idempotent: applying twice gives the second gain, not
    the product of both, which is the difference between adjusting a control and
    silently stacking gain stages on an instrument.
    """
    if gain_db > MEASURED_HEADROOM_DB:
        raise ValueError(
            f"{gain_db} dB exceeds the {MEASURED_HEADROOM_DB} dB of headroom measured "
            "on this instrument; the limiter would be doing the work"
        )
    if not 0.0 < ceiling <= 1.0:
        raise ValueError(f"ceiling must be within (0, 1], not {ceiling}")
    _free_quietly(client, node)
    _load(client)
    # addAction 1 = tail of the root group: after everything the instrument does.
    client.send("/s_new", "voxMakeup", node, 1, 0,
                "left", left, "right", right,
                "gain", db_to_gain(gain_db), "ceiling", ceiling)
    client.sync()
    return Makeup(node, left, right, gain_db, ceiling)


def set_gain(client, gain_db: float, node: int = MAKEUP_NODE) -> None:
    client.n_set(node, gain=db_to_gain(gain_db))


#: The compiled definition, built once. Compiling spawns an sclang, and the server
#: keeps a definition once it has it, so re-sending on every apply() costs half a
#: second and a round trip to say something the server already knows.
_COMPILED: bytes | None = None


def _load(client, retries: int = 1) -> None:
    """Send the definition, once per process, retrying a transient timeout.

    `/d_recv` is answered with `/done`, and a busy server can miss the window. One
    retry distinguishes "the server was busy" from "this will never work" without
    hiding the second.
    """
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = compile_synthdef("voxMakeup", MAKEUP_GRAPH)
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            client.d_recv(_COMPILED)
            return
        except Exception as exc:  # noqa: BLE001 - retried, then re-raised
            last = exc
    raise last


def _free_quietly(client, node: int, settle: float = 0.25) -> None:
    """Free a node that may not exist, leaving no reply behind.

    scsynth answers `/n_free` for an absent node with `/fail`. Catching that where it
    is raised is not enough: the datagram is still in the socket, and the NEXT
    request picks it up instead of its own reply — which is how a tidy-up before
    loading a SynthDef turned into "server rejected /n_free" from `d_recv`.

    So the socket is drained afterwards rather than merely guarded. Anything already
    queued is discarded, which is safe here because nothing else is in flight.
    """
    import time as _time

    client.send("/n_free", node)
    deadline = _time.monotonic() + settle
    while _time.monotonic() < deadline:
        remaining = deadline - _time.monotonic()
        if client.transport.recv(timeout=remaining) is None:
            break


def remove(client, node: int = MAKEUP_NODE) -> None:
    """Take the gain stage out. Safe whether or not one is running."""
    _free_quietly(client, node)
