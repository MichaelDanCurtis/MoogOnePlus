"""The four output meters — the one continuous read the synth genuinely gives us.

``/a/stat/{mainl,mainr,send1,send2}`` each return two floats: min and max sample excursion
over the window. Verified live this session, idle floor −90 to −118 dBFS. They are on the
voice bus, reachable only from the box, so the real source is an SSH batch — which has
not been run as a loop and is badged accordingly. :class:`MockMeterSource` exists so the
UI can be built and previewed tonight without pretending.
"""

from __future__ import annotations

import math
import random
import subprocess
from typing import Protocol

from ..vx import interpret, parse_hexdump, render_remote_command
from .protocol import LIVE, UNTESTED, Badge

METER_ADDRESSES = ("/a/stat/mainl", "/a/stat/mainr", "/a/stat/send1", "/a/stat/send2")


class MeterSource(Protocol):
    badge: Badge

    def read(self) -> dict[str, tuple[float, float]] | None: ...


def to_dbfs(lo: float, hi: float) -> float:
    peak = max(abs(lo), abs(hi))
    return -math.inf if peak == 0 else 20.0 * math.log10(peak)


def parse_meter_batch(text: str) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for row in text.splitlines():
        if "\t" not in row:
            continue
        addr, _, hexdump = row.partition("\t")
        addr = addr.strip()
        try:
            reply = interpret(addr, parse_hexdump(hexdump))
        except (ValueError, TypeError):
            continue
        if reply.kind != "value" or len(reply.args) < 2:
            continue
        try:
            out[addr] = (float(reply.args[0]), float(reply.args[1]))
        except (TypeError, ValueError):
            continue
    return out


class MockMeterSource:
    badge = UNTESTED("synthetic meter data for building the UI; not the instrument")

    def __init__(self, seed: int = 0):
        self._rng = random.Random(seed)
        self._level = dict.fromkeys(METER_ADDRESSES, 0.001)

    def read(self) -> dict[str, tuple[float, float]]:
        out = {}
        for a in METER_ADDRESSES:
            self._level[a] = max(1e-6, min(0.9, self._level[a] * self._rng.uniform(0.7, 1.4)))
            v = self._level[a]
            out[a] = (-v * self._rng.uniform(0.6, 1.0), v * self._rng.uniform(0.6, 1.0))
        return out


class SshMeterSource:
    #: Verified on the instrument 2026-09-03: the four getters answer, the values
    #: track the audio, and a held chord moved mainl/mainr by +11 dB against silence
    #: across repeated alternating trials.
    #:
    #: The rate is the caveat, and it is measured rather than asserted: **0.17 Hz**,
    #: one frame roughly every 5.8 seconds. Of a 4.5 s read, only 0.37 s is the SSH
    #: round trip; the rest is four sequential one-second listens. Running the four
    #: queries concurrently on the device is 2.9x faster and returned **nothing
    #: parseable** — their output interleaves into a single stream, which is the same
    #: failure that once corrupted a calibration backup in this project. Doing it
    #: properly needs a distinct reply port per query, and misattributing a reply to
    #: the wrong meter is precisely the silent wrongness this codebase exists to
    #: avoid. Not attempted for a 3x gain on a number that is already too slow to be
    #: a VU meter.
    #:
    #: So: a level indicator, honestly. Not a meter.
    badge = LIVE

    def __init__(self, device: str, wait: int = 1):
        self._device = device
        self._wait = wait

    def script(self) -> str:
        lines = []
        for a in METER_ADDRESSES:
            cmd = render_remote_command(a, wait=self._wait)
            lines.append(f'printf "%s\\t" "{a}"; {cmd}; echo')
        return "\n".join(lines)

    def read(self) -> dict[str, tuple[float, float]] | None:
        """One batch of all four addresses. **Only one reader at a time.**

        Two of these running concurrently against the same instrument return partial
        results — seen as a missing address while the bridge's own meter loop was
        polling. The queries listen on a fixed reply port, so a second reader steals
        replies from the first. To show meters elsewhere, read the bridge's broadcast
        rather than opening a second source.
        """
        try:
            proc = subprocess.run(
                [
                    "ssh",
                    "-o",
                    "StrictHostKeyChecking=no",
                    "-o",
                    "UserKnownHostsFile=/dev/null",
                    "-o",
                    "ConnectTimeout=5",
                    f"root@{self._device}",
                    "sh",
                ],
                input=self.script(),
                capture_output=True,
                text=True,
                check=False,
                timeout=len(METER_ADDRESSES) * (self._wait + 1) + 10,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None
        got = parse_meter_batch(proc.stdout)
        return got or None
