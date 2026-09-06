"""Stream the instrument's audio off it, in real time, over the network.

USB carries no audio on this instrument — the socket declares MIDIStreaming and
no AudioStreaming interface — so the network is the audio path. `scsynth` owns
the sound card exclusively, which does not matter: it is a server this machine
already talks to, and it will write its output bus anywhere a file can go.

So: a FIFO on the instrument, `nc` pushing that FIFO at a TCP socket here, and a
`DiskOut` synth writing into it. No SSH in the audio path.

**Raw, not WAV.** A WAV header carries a length that has to be seeked back and
written at close, and a stream has no end to seek to. Raw float32 has no header
to finalise.

**The FIFO must never lose its reader.** `scsynth` neither ignores nor handles
SIGPIPE — its `SigIgn` mask is `0x4` (SIGQUIT alone) and `SigCgt` is
`0x180000000` (pthread internals), and bit 12 is in neither — so the default
action applies and **a write to a pipe with no reader kills the audio engine.**

That is not hypothetical. A capture harness exited while a stream was still
armed, `nc` went with it, `DiskOut` wrote into the orphaned FIFO, and scsynth
died: the instrument lost every effect until the service was restarted. Any user
whose DAW quit mid-capture would hit the same thing.

So the writer is `cat FIFO | { nc HOST PORT; cat > /dev/null; }`. When `nc` ends
— cleanly or not — the trailing `cat` inherits the pipe and drains it, so the
FIFO always has a reader and `DiskOut` never sees a broken pipe. Disarming
promptly is still right; this is what makes forgetting survivable.

**The ring buffer is the latency.** `DiskOut` drains a ring, and for a live
stream that ring *is* the delay: 65536 frames — SuperCollider's usual size, and
what `moogone.record` uses for writing files — puts 372 ms between a trigger and
the sound reaching the socket. 2048 frames puts 22 ms. Right for a file,
catastrophic for a stream.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

#: Frames of DiskOut ring. See the module docstring: this is the latency.
STREAM_RING = 2048

#: Buffer and node ids, clear of the sampler (1100+/91000+) and the FM engine.
STREAM_BUFFER = 1050
STREAM_NODE = 94000

FIFO = "/tmp/vox-netaudio.raw"

#: Writes the instrument's output bus into a buffer that DiskOut drains.
STREAM_DEF = "voxNetOut"
STREAM_GRAPH = "|buf = 0, bus = 0| DiskOut.ar(buf, In.ar(bus, 2))"


class NetAudioError(RuntimeError):
    """The stream could not be set up, and why."""


@dataclass(frozen=True)
class Stream:
    device: str
    dest_host: str
    dest_port: int
    bus: int
    ring: int


def _ssh(host: str, command: str, background: bool = False):
    args = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "BatchMode=yes",
        f"root@{host}",
        command,
    ]
    if background:
        return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def arm(
    client, device: str, dest_host: str, dest_port: int, *, bus: int = 0, ring: int = STREAM_RING
) -> Stream:
    """Start streaming `bus` to `dest_host:dest_port`. Returns a handle for `disarm`.

    `nc` is piped through `cat` deliberately. Written as `nc ... > FIFO` the shell
    opens the FIFO for writing *before* exec'ing nc, and that open blocks until a
    reader appears — so nc never binds and the connection is refused. Piping defers
    the blocking open to a separate process and lets nc bind immediately.
    """
    from .synthdef import compile_synthdef

    # Compiled BEFORE anything starts on the instrument: it shells out to sclang
    # and can be slow, and a half-armed stream is worse than an unarmed one.
    synthdef = compile_synthdef(STREAM_DEF, STREAM_GRAPH)
    stream = Stream(device, dest_host, dest_port, bus, ring)

    _ssh(device, f"rm -f {FIFO}; mkfifo {FIFO}")
    _ssh(
        device, f"cat {FIFO} | {{ nc {dest_host} {dest_port}; cat > /dev/null; }}", background=True
    )
    try:
        client.d_recv(synthdef)
        client.send("/b_alloc", STREAM_BUFFER, ring, 2)
        client.sync()
        client.send("/b_write", STREAM_BUFFER, FIFO, "raw", "float", 0, 0, 1)
        client.sync()
        client.send("/s_new", STREAM_DEF, STREAM_NODE, 1, 0, "buf", STREAM_BUFFER, "bus", bus)
        client.sync()
    except BaseException:
        # Anything at all, including a timeout. Failing partway through used to
        # leave the instrument streaming audio into a socket nobody reads, with no
        # error and nothing that stops on its own -- found when a network timeout
        # landed at exactly the wrong moment and the stream ran on unnoticed.
        disarm(client, stream, quiet=True)
        raise
    return stream


def follow(client) -> None:
    """Put the recorder back at the tail of the root group.

    Nodes execute in creation order, so a voice created *after* the recorder writes
    the bus too late to be heard — and the symptom is a silent stream with no error
    anywhere, not a late one. Call this after adding voices.
    """
    client.send("/g_tail", 0, STREAM_NODE)


#: Kills whatever is holding the FIFO open. Freeing the synth stops scsynth
#: writing, but the `nc` on the other end is a separate process and outlives it.
_KILL_WRITER = (
    # `me=$$` is not defensive programming, it is required. This command names the
    # FIFO, so the shell RUNNING it has "vox-netaudio" in its own command line and
    # matches its own pattern -- it killed itself before reaching the `rm`, and the
    # FIFO survived every disarm until someone looked at why.
    "me=$$; for p in /proc/[0-9]*; do "
    'pid=$(basename $p); [ "$pid" = "$me" ] && continue; '
    "n=$(tr '\\0' ' ' < $p/cmdline 2>/dev/null); "
    'case "$n" in *vox-netaudio*) kill $pid 2>/dev/null;; esac; '
    "done"
)


def disarm(client, stream: Stream, *, quiet: bool = False) -> None:
    """Stop the stream and put the instrument back as it was.

    `quiet` is for the failure path, where the network is usually why we are here:
    a failure to confirm is not re-raised over the top of the original error.

    **It does not mean "skip the confirmation".** It used to, and that was a race
    with teeth: the kill below removes the `cat` reading the FIFO, and if `/n_free`
    has not been processed by then, `DiskOut` writes into a pipe with no reader --
    which, per the module docstring, terminates scsynth. Freeing and killing are
    two messages to two different machines over two different protocols, and only
    the sync orders them. So the sync always happens; only whether its failure is
    raised depends on `quiet`.
    """
    try:
        client.send("/n_free", STREAM_NODE)
        client.send("/b_close", STREAM_BUFFER)
        client.send("/b_free", STREAM_BUFFER)
        try:
            client.sync()
        except Exception:
            if not quiet:
                raise
    finally:
        # ALWAYS, even if the sync above timed out. Freeing the synth stops
        # scsynth writing, but `nc` is a separate process holding the FIFO and the
        # connection open, and it outlives the synth. Skipping this because a
        # confirmation did not arrive leaves the very thing disarm exists to stop.
        _ssh(stream.device, f"{_KILL_WRITER}; rm -f {FIFO}")
