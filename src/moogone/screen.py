"""The Moog One's main screen, read straight off its framebuffer.

The big display is not on the panel bus at all. `las-frontend` runs with
`--host-oleds=203.0.113.2`, so the small OLED screens go over the network, while the
main display is an X server drawing into `/dev/fb0` on the instrument's own Linux —
832x480, 32 bits per pixel, `DISP3 BG`. Which means it can simply be read.

A frame is 1.6 MB raw and about 28 KB gzipped, so the capture pipes `dd` through
`gzip` on the device and this end slices frames out of the decompressed stream. One
SSH session for the whole feed, not one per frame: at two frames a second, per-frame
connections would spend more time in SSH handshakes than in pixels.

Read-only. Nothing is written to the instrument or to its display.
"""

from __future__ import annotations

import subprocess
import threading
import zlib

from .stream import SSH_OPTIONS

#: Read off `/sys/class/graphics/fb0`: `modes` says 832x480, `stride` says 3328,
#: which is exactly 832 * 4 — so rows are tightly packed and no padding to skip.
WIDTH = 832
HEIGHT = 480
BYTES_PER_PIXEL = 4
STRIDE = WIDTH * BYTES_PER_PIXEL
FRAME_BYTES = STRIDE * HEIGHT


def bgra_to_rgb(frame: bytes, width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """Convert one BGRA framebuffer to packed RGB.

    Done with strided slice assignment rather than a per-pixel loop: this runs on
    400,000 pixels several times a second, and the loop version is roughly two orders
    of magnitude slower for the same result.
    """
    expected = width * height * BYTES_PER_PIXEL
    if len(frame) != expected:
        raise ValueError(f"expected {expected} bytes, got {len(frame)}")
    out = bytearray(width * height * 3)
    out[0::3] = frame[2::4]  # R
    out[1::3] = frame[1::4]  # G
    out[2::3] = frame[0::4]  # B
    return bytes(out)


def png_rgb(pixels: bytes, width: int = WIDTH, height: int = HEIGHT) -> bytes:
    """A 24-bit RGB PNG, standard library only."""
    import struct

    if len(pixels) != width * height * 3:
        raise ValueError(f"expected {width * height * 3} bytes, got {len(pixels)}")
    raw = b"".join(
        b"\x00" + pixels[y * width * 3 : (y + 1) * width * 3] for y in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack("!I", len(data)) + body + struct.pack("!I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


def frames_from(read, frame_bytes: int = FRAME_BYTES, chunk: int = 65536):
    """Yield whole frames from a gzip stream of concatenated framebuffer dumps.

    The remote loop writes one frame after another into a single `gzip`, so there are
    no delimiters — frames are found by counting, which works because every frame is
    exactly the same size. A partial frame is held rather than emitted short.
    """
    inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)  # 16 = expect a gzip header
    buf = bytearray()
    while True:
        data = read(chunk)
        if not data:
            return
        buf += inflate.decompress(data)
        while len(buf) >= frame_bytes:
            yield bytes(buf[:frame_bytes])
            del buf[:frame_bytes]


class MainScreen:
    """A live feed of the instrument's main display."""

    def __init__(self, host: str, on_frame, period: float = 0.5, on_error=None):
        self.host = host
        self.period = period
        self._on_frame = on_frame
        self._on_error = on_error
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()

    @property
    def command(self) -> str:
        # One gzip across the whole loop, so the header appears once and the frames
        # concatenate inside a single compressed stream.
        return (
            "export PATH=/usr/sbin:/sbin:/usr/bin:/bin; "
            f"while :; do dd if=/dev/fb0 bs={STRIDE} count={HEIGHT} 2>/dev/null; "
            f"sleep {self.period}; done | gzip -1"
        )

    def run(self) -> None:
        self._proc = subprocess.Popen(
            ["ssh", *SSH_OPTIONS, f"root@{self.host}", self.command],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            for frame in frames_from(self._proc.stdout.read1):
                if self._stop.is_set():
                    break
                self._on_frame(frame)
        except (OSError, zlib.error) as exc:  # pragma: no cover - transport failures
            if self._on_error:
                self._on_error(exc)
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:  # pragma: no cover
                proc.kill()
