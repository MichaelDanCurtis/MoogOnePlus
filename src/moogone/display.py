"""The Moog One's two OLED displays, reconstructed from the wire.

The instrument redraws its own screens constantly — two thirds of all traffic on the
internal bus at idle — by sending 64x16 tiles to `/od/{0,1}/l8m` on port 9876. Each
tile is 1024 bytes, one byte of luminance per pixel, with its position in the
message. Three columns by six rows makes each display **192x96**.

Decoded from a capture rather than from documentation:

    /od/N/l8m  ,iiiiiib   x  width  y  height  -1  255  <1024 bytes>
                          |    |    |    |
                    0,64,128  64  0..80  16

The two constant integers (-1 and 255) never varied across a thousand messages and
are recorded, not interpreted. They look like a colour mask and an alpha, but that
is a guess and nothing here depends on it.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

DISPLAY_PORT = 9876

#: Both displays are three 64-wide columns by six 16-high rows.
WIDTH = 192
HEIGHT = 96
TILE_W = 64
TILE_H = 16


@dataclass(frozen=True)
class Tile:
    display: int  # 0 or 1
    x: int
    y: int
    width: int
    height: int
    pixels: bytes  # width*height bytes, 8-bit luminance, row-major


def decode_tile(payload: bytes) -> Tile | None:
    """One `/od/N/l8m` message, or None if this is not one.

    None rather than raising: this is fed from a live capture that also carries
    `/od/s` and `/od/N/cp`, and the note and panel protocols besides.
    """
    if not payload.startswith(b"/od/"):
        return None
    try:
        end = payload.index(b"\x00")
        address = payload[:end].decode("ascii")
        i = (end + 4) & ~3
        tag_end = payload.index(b"\x00", i)
        tag = payload[i:tag_end].decode("ascii")
        args = payload[i + (((tag_end - i) + 4) & ~3) :]
    except (ValueError, UnicodeDecodeError):
        return None
    if tag != ",iiiiiib" or not address.endswith("/l8m") or len(args) < 28:
        return None
    try:
        display = int(address.split("/")[2])
    except (IndexError, ValueError):
        return None
    x, width, y, height, _mask, _alpha = struct.unpack("!6i", args[:24])
    (blob_len,) = struct.unpack("!I", args[24:28])
    pixels = args[28 : 28 + blob_len]
    if len(pixels) != blob_len or blob_len != width * height:
        return None  # truncated, or a geometry this decoder has never seen
    if width <= 0 or height <= 0 or x < 0 or y < 0:
        return None
    return Tile(display, x, y, width, height, pixels)


class Framebuffer:
    """One display, assembled from tiles as they arrive.

    Starts black. A tile that would fall outside the display is clipped rather than
    rejected, because a wrong guess about the screen size should show up as a visibly
    misplaced tile, not as an exception that stops the feed.
    """

    def __init__(self, width: int = WIDTH, height: int = HEIGHT):
        self.width = width
        self.height = height
        self.pixels = bytearray(width * height)
        self.dirty = False

    def blit(self, tile: Tile) -> None:
        for row in range(tile.height):
            dy = tile.y + row
            if not (0 <= dy < self.height):
                continue
            src = row * tile.width
            take = min(tile.width, self.width - tile.x)
            if take <= 0:
                continue
            dst = dy * self.width + tile.x
            self.pixels[dst : dst + take] = tile.pixels[src : src + take]
        self.dirty = True

    def png(self) -> bytes:
        return png_grayscale(bytes(self.pixels), self.width, self.height)


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack("!I", len(data)) + body + struct.pack("!I", zlib.crc32(body))


def png_grayscale(pixels: bytes, width: int, height: int) -> bytes:
    """An 8-bit grayscale PNG, using only the standard library.

    Written rather than pulled in, because the alternative is a native image
    dependency on both the Mac and anything else that runs this, to encode the
    simplest PNG that exists. Each row is prefixed with filter type 0 (none): these
    are small screens and zlib handles the redundancy well enough that filtering
    would buy little.
    """
    if len(pixels) != width * height:
        raise ValueError(f"expected {width * height} bytes, got {len(pixels)}")
    raw = b"".join(
        b"\x00" + pixels[y * width : (y + 1) * width] for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack("!IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )
