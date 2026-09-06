"""Audio *into* the instrument, so its own effects can process it.

Egress was easy: `scsynth` writes its output anywhere a file can go, so a FIFO and
`nc` were enough (`moogone.netaudio`). Ingress is not the mirror image of that, and
the obvious construction -- the same FIFO read by `DiskIn` -- does not work here.
Three measurements, in the order they were made:

* `/b_read` reads a FIFO **honestly**. Given a header and nothing else it blocked
  for 4.02 s until the frames it was asked for arrived. libsndfile parses a WAV
  header from a stream without seeking, exactly as hoped.
* `DiskIn` will **not continue** from one. Cued from a FIFO it plays what `/b_read`
  put in the buffer and never asks for more: twenty seconds of a realtime feed and
  the instrument accepted **0.00x realtime**, with the disk thread idle throughout
  rather than blocked. From an ordinary file on the instrument the same synthdef
  sounds at rms 0.141, so DiskIn and the graph are fine and the pipe is the
  difference.
* Every attempt puts scsynth's **disk thread** behind a read that may never return.
  That thread also serves `/d_recv`, `/b_alloc`, `/sync` and the instrument's own
  preset and sample loading, and an under-fed FIFO left `/sync` unanswered for over
  eight seconds. Blocking it is not a corner case of this path, it is the path.

So this does not use the disk thread at all.

**`/b_setn` into a ring, `BufRd` reading it out.** Samples go straight into a
buffer over OSC; a `Phasor` sweeps it and `BufRd` plays it back as an endless ring.
The traffic rides the same paced UDP transport as every other command in this
project -- `MIN_SEND_INTERVAL`, the §8c interlock -- so the one failure mode that
costs a power cycle is handled by code that already exists and is already tested.

**Mono, and that is arithmetic rather than taste.** Stereo at 48 kHz through
`/b_setn` is about 420 kB/s; running at the same time as the 384 kB/s of egress
that makes the round trip come to more than the 719 kB/s §8c measured as
untroubled. Mono halves the ingress to ~210 kB/s and puts the pair at ~594 kB/s,
inside what was measured. A mono send into a stereo effect is what a send is.

**The effect runs on private buses.** The instrument's own SuperCollider source is
on the device, and every effect in it has the same shape --
`In.ar(inBus, 2) -> LADSPA -> Out.ar(outBus, ...)` with both buses plain controls.
So an effect can be pointed at buses nothing else uses. scsynth here runs with
`-a 129`; the instrument works in 0-16 (8 output, 9 input) and 50-63 (insert
returns 50-55, sends 56-59, masters 60-63). Everything from 64 up is free, and
using it means **no patch is modified and no gain of the user's is touched.**

**An effect must never be `/n_free`d.** Doing it terminates scsynth -- measured
directly, with nothing else running: create `et_plate_1`, `/n_free` it, and the
server stops answering, twice out of two. Moog's effects are made once at boot and
never freed, so the free path is the part of their lifecycle their own firmware
never exercises, and it takes the audio engine with it. Their envelope says as
much: `EnvGen.kr(Env.asr(...), enable, doneAction: 1)`, and doneAction 1 is
*pause*. So this stops an effect with `enable = 0` and leaves the node parked, and
re-arming resumes the same node rather than making a new one.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

SAMPLE_RATE = 48000

#: Ids clear of the sampler (1100+/91000+), the FM engine (93000+) and the
#: outbound stream (1050/94000).
RING_BUFFER = 1054
RING_NODE = 95100
EFFECT_NODE = 96100

#: Private audio buses. See the module docstring for why these are safe.
IN_BUS = 100
FX_BUS = 102

#: Control bus carrying the ring's read pointer, so this side can see where the
#: instrument has got to and hold a distance ahead of it.
POSITION_BUS = 40

#: Floats per /b_setn. 256 keeps the datagram sub-MTU (~1100 bytes) and, at 48 kHz
#: mono, means 188 messages a second against the 1000/s the interlock allows.
BLOCK = 256

RING_DEF = "voxRing"
RING_GRAPH = (
    "|buf = 0, bus = 100, pos = 40, gain = 1| "
    "var phase = Phasor.ar(0, BufRateScale.kr(buf), 0, BufFrames.kr(buf)); "
    "Out.kr(pos, A2K.kr(phase)); "
    "Out.ar(bus, BufRd.ar(1, buf, phase, loop: 1) * gain ! 2)"
)

#: The instrument's own effects, read off /usr/share/las-fx/synthdefs/. The
#: numbered variants are per-slot copies of one definition, so the plain name is
#: the effect and `_1` is the instance this project instantiates.
EFFECTS = (
    "et_blackhole_1",
    "et_hall_1",
    "et_plate_1",
    "et_room_1",
    "et_shimmer_1",
    "bbdDelay_1",
    "bitcrusher_1",
    "chorus_1",
    "delay_1",
    "dualChorus_1",
    "echo_1",
    "ensemble_1",
    "flanger_1",
    "phaser6stage_1",
    "phaser12stage_1",
    "pingpongDelay_1",
    "resonator_1",
    "stereoChorus_1",
    "stereoDelay_1",
    "stereoFlanger_1",
    "tapeDelay_1",
    "timePhaser_1",
    "vocoder10_1",
    "vocoder16_1",
    "vocoder21_1",
)


class IngressError(RuntimeError):
    """The ingress path could not be set up, and why."""


@dataclass(frozen=True)
class Ingress:
    """An armed ingress path: where audio goes in and what comes back out."""

    frames: int
    effect: str | None
    #: The bus to capture. The effect's output if there is one, else the ring's.
    out_bus: int

    @property
    def seconds(self) -> float:
        return self.frames / SAMPLE_RATE


def arm(
    client,
    *,
    effect: str | None = "et_plate_1",
    frames: int = 6000,
    gain: float = 1.0,
) -> Ingress:
    """Allocate the ring, start it playing, and put an effect after it.

    `frames` is the ring, and the ring is the budget for latency: audio is written
    a fixed distance ahead of the read pointer, so a bigger ring buys tolerance for
    network jitter and clock drift and pays for it in delay.

    6000 frames with a 2000-frame lead is what measured best on hardware: a
    **115.2 ms** median round trip with a **5.3 ms** spread, the writer holding
    1.000x realtime and the gap staying within 1232 frames of its target. Doubling
    both took the round trip to 264.9 ms for no gain in stability.

    Nothing here touches the instrument's own graph. The ring plays into a private
    bus, the effect reads that bus and writes another, and both are above anything
    the instrument uses.
    """
    from .synthdef import compile_synthdef

    if effect is not None and effect not in EFFECTS:
        raise IngressError(
            f"{effect!r} is not one of the instrument's effects; "
            f"expected one of {', '.join(EFFECTS)} or None"
        )
    if frames < 2 * BLOCK:
        raise IngressError(f"a {frames}-frame ring is too small to hold a {BLOCK}-frame write")

    # Compiled and received BEFORE anything is allocated, for the reason the
    # probes kept rediscovering: /d_recv and /b_alloc are async commands whose
    # replies cross the network, and a failure here should leave nothing behind.
    synthdef = compile_synthdef(RING_DEF, RING_GRAPH)
    client.d_recv(synthdef, timeout=15.0)
    client.send("/b_free", RING_BUFFER)
    client.send("/b_alloc", RING_BUFFER, frames, 1)
    client.sync(timeout=10.0)

    armed = Ingress(frames, effect, FX_BUS if effect else IN_BUS)
    try:
        # Head of the root group, then the effect after it. Creation order is
        # execution order, and a node behind the recorder writes its bus too late
        # to be read -- silence with no error, the trap in §8b.
        client.send(
            "/s_new",
            RING_DEF,
            RING_NODE,
            0,
            0,
            "buf",
            RING_BUFFER,
            "bus",
            IN_BUS,
            "pos",
            POSITION_BUS,
            "gain",
            gain,
        )
        client.sync(timeout=8.0)
        if effect is not None:
            _start_effect(client, effect)
    except BaseException:
        # Anything at all, including a timeout: a half-armed ingress leaves a synth
        # looping stale buffer contents into a bus with nothing to stop it.
        disarm(client, quiet=True)
        raise
    return armed


def _parked_effect(client) -> str | None:
    """The name of the effect already sitting at EFFECT_NODE, if there is one.

    Asked with /g_queryTree because `/n_query` is not implemented on this firmware
    and answers nothing, and because a speculative `/s_new` on a taken id replies
    with an unsolicited /fail -- which, per the /n_free lesson in
    `moogone.sc.client`, gets blamed on whatever request comes next.
    """
    for node in client.query_tree(0, with_controls=False).walk():
        # Groups have no defname; only a synth can be the parked effect.
        if node.node_id == EFFECT_NODE:
            return getattr(node, "defname", None)
    return None


def _start_effect(client, effect: str) -> None:
    """Create the effect, or resume the one already parked there.

    An effect is never freed, so re-arming finds the previous one paused where
    disarm left it. Resuming is `/n_run 1` to make it execute again and
    `enable = 1` to retrigger the envelope that `enable = 0` released -- setting
    the control alone does nothing, because a paused synth is not running to see
    it. A parked effect of a *different* kind cannot be reused, and cannot be
    freed either, so it is moved aside and left dormant.
    """
    parked = _parked_effect(client)
    if parked == effect:
        client.send("/n_run", EFFECT_NODE, 1)
        client.send("/n_set", EFFECT_NODE, "enable", 1)
        client.send("/n_order", 3, RING_NODE, EFFECT_NODE)
        client.sync(timeout=8.0)
        return
    if parked is not None:
        # Not ours to free, and it must not keep reading our bus: silence it, park
        # it under the root group, and leave it there.
        client.send("/n_set", EFFECT_NODE, "enable", 0)
        client.send("/n_set", EFFECT_NODE, "inBus", 0, "outBus", 0)
        client.send("/n_run", EFFECT_NODE, 0)
        raise IngressError(
            f"node {EFFECT_NODE} already holds {parked!r}, which cannot be freed "
            f"without terminating scsynth. Re-arm with effect={parked!r}, or "
            f"restart the engine to use {effect!r}."
        )
    client.send("/s_new", effect, EFFECT_NODE, 3, RING_NODE, "inBus", IN_BUS, "outBus", FX_BUS)
    client.sync(timeout=8.0)


def disarm(client, *, quiet: bool = False) -> None:
    """Stop the effect, free the ring synth, free the buffer -- in that order.

    The effect is **stopped, never freed.** `/n_free` on one of the instrument's
    LADSPA effects terminates scsynth; see the module docstring. `enable = 0`
    releases its envelope, whose doneAction pauses the synth, and the node is left
    parked for `arm` to resume. It costs an allocation that is never reclaimed and
    no CPU, which is the right trade against killing the audio engine.

    The effect is stopped first because it reads the ring synth's bus: freeing the
    source first would leave a reverb tail feeding on whatever else lands there.
    """
    client.send("/n_set", EFFECT_NODE, "enable", 0)
    client.send("/n_free", RING_NODE)
    client.send("/b_free", RING_BUFFER)
    try:
        client.sync(timeout=5.0)
    except Exception:
        if not quiet:
            raise


def read_position(client, timeout: float = 2.0) -> int:
    """Where the instrument's read pointer is, in frames.

    This is the only feedback there is. The instrument's crystal and the machine
    writing to it are different clocks, so a writer that never looks will drift
    into the reader and click.
    """
    reply = client.request("/c_get", POSITION_BUS, reply="/c_set", timeout=timeout)
    return int(reply.args[1])


def gap(write_position: int, read_position: int, frames: int) -> int:
    """How far the writer is ahead of the reader, in frames, around the ring.

    Wrapped deliberately. The two pointers chase each other forever and the
    absolute values are meaningless; the distance between them is the only thing
    that says whether the next block lands on audio that has already been played
    or on audio that has not been played yet.
    """
    return (write_position - read_position) % frames


#: The most the write rate is allowed to deviate from realtime while chasing the
#: gap. Half a percent is above the ~0.3 % measured between this machine's clock
#: and the instrument's, and small enough that the pitch shift it implies is
#: inaudible. A correction bigger than this is not drift, it is a fault.
MAX_CORRECTION = 0.005

#: How far behind its own schedule the writer will carry a deficit before giving
#: up on it. Twenty milliseconds is four blocks: enough to absorb a slow send or a
#: scheduler hiccup, short enough that making it up stays far below the interlock.
MAX_LAG = 0.020


def correction(gap_frames: int, target: int, frames: int) -> float:
    """Rate multiplier that walks the gap back to `target`, gently.

    Proportional, slow, and clamped. The instrument's clock and this one differ by
    a fraction of a percent, so the correction needed is tiny and permanent -- what
    must not happen is a fast controller that hunts, because every adjustment is a
    change of playback rate and a fast one is audible as pitch.
    """
    if frames <= 0:
        return 1.0
    error = (gap_frames - target) / frames
    return 1.0 + max(-MAX_CORRECTION, min(MAX_CORRECTION, -error * 0.5))


class RingWriter:
    """Writes mono samples into the ring at realtime, holding a lead on the reader.

    `source(n)` supplies the next `n` samples. It is called from this writer's own
    thread and must not block for long: the schedule is absolute, so a slow call is
    caught up by the next one, but a very slow one lets the reader catch up and the
    ring is only as forgiving as its lead.

    **`client` must not be shared with another thread that waits for replies.**
    This writer asks `/c_get` four times a second, and `ScClient` matches replies
    by reading whatever the socket hands it and discarding what does not match --
    so two threads waiting on one socket steal each other's answers. The symptom is
    not an error: both sides simply get slower and start timing out, which is
    exactly how it presented, as an unexplained crawl with the audio still flowing.
    Give the writer its own `ScClient` over its own transport.
    """

    def __init__(
        self,
        client,
        armed: Ingress,
        source,
        *,
        lead: int | None = None,
        poll: float = 0.25,
        poll_timeout: float = 0.05,
    ) -> None:
        self.client = client
        self.armed = armed
        self.source = source
        # A third of the ring, not half: the gap wanders by well under that, and
        # the lead is the dominant term in the round trip.
        self.lead = armed.frames // 3 if lead is None else lead
        self.poll = poll
        #: How long the gap poll may take before it is abandoned. SHORT, and that
        #: is the whole point -- see run().
        self.poll_timeout = poll_timeout
        self.missed_polls = 0
        self.write_position = 0
        self.blocks = 0
        self.rate = 1.0
        self.worst_gap_error = 0
        #: The SMALLEST gap ever seen. This is the one that matters: when it
        #: reaches zero the instrument's reader has caught the writer and is
        #: playing a lap-old block, which is heard as a stutter rather than as an
        #: error. worst_gap_error is symmetric and hides it.
        self.min_gap: int | None = None
        self.resets = 0
        self.error: BaseException | None = None

    def _send(self, samples) -> None:
        """One /b_setn, split if it would run off the end of the ring.

        A buffer write does not wrap. Sending 256 samples starting 100 frames from
        the end writes 156 frames past the buffer, which scsynth rejects -- and the
        rejection is a /fail nothing is waiting for, so it is silent.
        """
        start = self.write_position
        room = self.armed.frames - start
        head, tail = samples[:room], samples[room:]
        if head:
            self.client.send("/b_setn", RING_BUFFER, start, len(head), *head)
        if tail:
            self.client.send("/b_setn", RING_BUFFER, 0, len(tail), *tail)
        self.write_position = (start + len(samples)) % self.armed.frames

    def prime(self) -> None:
        """Fill the lead before the reader reaches it.

        Without this the reader starts on an empty ring and plays silence until the
        writer overtakes it -- which, at exactly realtime, it never does.
        """
        for _ in range(0, self.lead, BLOCK):
            self._send(list(self.source(BLOCK)))

    def run(self, stop) -> None:
        next_at = time.perf_counter()
        polled_at = next_at
        try:
            while not stop.is_set():
                self._send(list(self.source(BLOCK)))
                self.blocks += 1

                now = time.perf_counter()
                if now - polled_at >= self.poll:
                    polled_at = now
                    # A MISSED POLL IS NOT WORTH WAITING FOR. This ran with the
                    # client's 2 s default, on this thread, and one lost reply
                    # stopped the feed for two seconds -- draining a 16000-frame
                    # lead to 3200 and leaving the instrument's reader replaying
                    # lap-old blocks, which is heard as stuttering. Blocking the
                    # writer to ask how the writer is doing is exactly backwards:
                    # the gap moves by a fraction of a percent per second, so
                    # skipping a reading costs nothing and keeping the last rate
                    # is the correct response to no new information.
                    try:
                        where = read_position(self.client, timeout=self.poll_timeout)
                    except Exception:  # noqa: BLE001 -- a missed poll, not a failure
                        self.missed_polls += 1
                    else:
                        ahead = gap(self.write_position, where, self.armed.frames)
                        self.worst_gap_error = max(self.worst_gap_error, abs(ahead - self.lead))
                        self.min_gap = ahead if self.min_gap is None else min(self.min_gap, ahead)
                        self.rate = correction(ahead, self.lead, self.armed.frames)

                # An absolute schedule, and a SMALL deficit is carried rather than
                # forgiven. Resetting the schedule every time a block ran long
                # looked like the safe choice -- catching up means sending faster,
                # and a burst is the one thing that costs a power cycle (§8c) --
                # but it silently threw away every overshoot. Measured: 27.7 s of
                # audio pushed in 28.2 s, 0.982x realtime, and since the reader
                # runs at exactly 1.000x the lead drained at 864 frames a second
                # and the round trip fell from 149 ms to 89 ms over five hits while
                # the rate controller sat pinned at its clamp.
                #
                # Carrying the deficit is not a burst: this loop sends exactly one
                # block per pass whatever happens, so catching up only means not
                # sleeping, and the transport's own 1 ms interlock still caps the
                # rate at 1000 datagrams a second. Only a stall longer than
                # MAX_LAG is given up on, because chasing that really would be a
                # burst and the gap controller is the right thing to fix it.
                next_at += BLOCK / (SAMPLE_RATE * self.rate)
                delay = next_at - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif -delay > MAX_LAG:
                    self.resets += 1
                    next_at = time.perf_counter()
        except BaseException as exc:  # noqa: BLE001 -- handed to the caller, not swallowed
            self.error = exc
