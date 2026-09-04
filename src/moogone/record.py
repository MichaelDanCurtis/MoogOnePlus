"""Record the instrument's own output to a file on the instrument.

The meters answer "is there sound" but not much else: they are a peak value read
over SSH at about 0.17 Hz, and repeated reads of the same silence have spanned ten
decibels. A noise floor cannot be characterised with that. This records real audio
instead, from inside `scsynth`, and brings back a WAV to analyse properly.

The signal never leaves the digital domain: `In.ar(0, 2)` reads the main output bus
inside the server, at the end of the chain, past every effect. So what this captures
is what the DSP produced — not what the converters did to it afterwards. **That
distinction is the whole question this repository was opened to answer.**

Nothing in the instrument's own graph is touched. A recorder synth is added to the
tail of the root group, and freed afterwards.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .synthdef import RECORDER, compile_synthdef

#: Node and buffer ids for the recorder. High and specific, to sit clear of the
#: instrument's own graph, which uses node ids in the 1000s.
RECORD_NODE = 90210
RECORD_BUFFER = 1000

#: A disk-writing buffer is a ring the server drains, not the whole recording. This
#: is SuperCollider's usual size for the job.
RING_FRAMES = 65536

_SAFE_REMOTE = re.compile(r"^/[A-Za-z0-9_./-]{1,200}$")


class RecordError(RuntimeError):
    """A recording that could not be set up, and why."""


@dataclass(frozen=True)
class Recording:
    remote_path: str
    seconds: float
    bus: int
    started: float


def _check_free(client, bufnum: int) -> None:
    """Refuse to record over a buffer the instrument is already using.

    `/b_query` answers `/b_info` with a frame count; an unallocated buffer reports
    zero. Writing into a live buffer would corrupt whatever owns it.
    """
    try:
        info = client.request("/b_query", bufnum, reply="/b_info", timeout=2.0)
    except Exception as exc:
        raise RecordError(f"could not query buffer {bufnum}: {exc}") from exc
    frames = info.args[1] if len(info.args) > 1 else 0
    if frames:
        raise RecordError(
            f"buffer {bufnum} is already allocated ({frames} frames); "
            "the instrument is using it"
        )


def start(client, remote_path: str, bus: int = 0, bufnum: int = RECORD_BUFFER,
          node: int = RECORD_NODE) -> Recording:
    """Load the recorder, open the file and start writing. Returns immediately."""
    if not _SAFE_REMOTE.match(remote_path):
        raise RecordError(f"{remote_path!r} is not a usable absolute path on the device")

    _check_free(client, bufnum)
    client.d_recv(compile_synthdef("voxRecorder", RECORDER))

    client.send("/b_alloc", bufnum, RING_FRAMES, 2)
    client.sync()
    # leaveOpen = 1: the server keeps the file open and streams into it. Without it
    # this writes an empty header and nothing else.
    client.send("/b_write", bufnum, remote_path, "wav", "int24", 0, 0, 1)
    client.sync()
    # addAction 1 = add to the TAIL of the root group, so the recorder runs after
    # everything the instrument does and hears the finished mix.
    client.send("/s_new", "voxRecorder", node, 1, 0, "buf", bufnum, "bus", bus)
    client.sync()
    return Recording(remote_path, 0.0, bus, time.monotonic())


def stop(client, rec: Recording, bufnum: int = RECORD_BUFFER,
         node: int = RECORD_NODE) -> Recording:
    """Free the recorder and close the file. Safe to call even if start half-failed."""
    client.send("/n_free", node)
    client.send("/b_close", bufnum)
    client.sync()
    client.send("/b_free", bufnum)
    client.sync()
    return Recording(rec.remote_path, time.monotonic() - rec.started, rec.bus, rec.started)


def record(client, remote_path: str, seconds: float, bus: int = 0) -> Recording:
    """Record `seconds` of the given bus. Always stops, even if the wait is cut short."""
    rec = start(client, remote_path, bus=bus)
    try:
        time.sleep(seconds)
    finally:
        rec = stop(client, rec)
    return rec
