"""Tests for the OLED display decoder.

The geometry here — 192x96 as a 3x6 grid of 64x16 tiles — was read off a capture of
a thousand messages, not from documentation. These tests pin what was observed and
guard the ways a tile decoder quietly goes wrong: a wrong offset, a truncated blob,
a tile that does not fit.
"""

from __future__ import annotations

import struct
import zlib

import pytest

from moogone.display import (
    HEIGHT,
    TILE_H,
    TILE_W,
    WIDTH,
    Framebuffer,
    Tile,
    decode_tile,
    png_grayscale,
)


def l8m(display=0, x=0, y=0, w=TILE_W, h=TILE_H, pixels=None, tag=b",iiiiiib"):
    addr = f"/od/{display}/l8m".encode()
    addr += b"\x00" * (4 - len(addr) % 4 or 4)
    tag = tag + b"\x00" * (4 - len(tag) % 4 or 4)
    px = pixels if pixels is not None else bytes(w * h)
    args = struct.pack("!6i", x, w, y, h, -1, 255) + struct.pack("!I", len(px)) + px
    return addr + tag + args


class TestDecodeTile:
    def test_decodes_geometry_and_pixels(self):
        t = decode_tile(l8m(display=1, x=128, y=48, pixels=bytes([7]) * (TILE_W * TILE_H)))
        assert t == Tile(1, 128, 48, TILE_W, TILE_H, bytes([7]) * (TILE_W * TILE_H))

    @pytest.mark.parametrize("x", [0, 64, 128])
    @pytest.mark.parametrize("y", [0, 16, 32, 48, 64, 80])
    def test_every_observed_tile_position(self, x, y):
        # The full 3x6 grid seen on the wire.
        t = decode_tile(l8m(x=x, y=y))
        assert t is not None and (t.x, t.y) == (x, y)

    def test_a_blob_shorter_than_its_geometry_is_refused(self):
        # Truncated capture. Blitting this would smear the previous frame's pixels.
        bad = l8m(pixels=bytes(10))
        assert decode_tile(bad) is None

    def test_a_non_l8m_od_message_is_none(self):
        assert decode_tile(b"/od/s\x00\x00\x00,i\x00\x00\x00\x00\x00\x00") is None

    def test_a_note_message_is_none(self):
        assert decode_tile(b"/\x00\x00\x00,iifi\x00\x00\x00" + bytes(16)) is None

    def test_empty_and_garbage(self):
        assert decode_tile(b"") is None
        assert decode_tile(b"/od/0/l8m") is None

    def test_wrong_type_tag_is_none(self):
        assert decode_tile(l8m(tag=b",iiiiii")) is None


class TestFramebuffer:
    def test_starts_black(self):
        fb = Framebuffer()
        assert len(fb.pixels) == WIDTH * HEIGHT
        assert not any(fb.pixels)
        assert fb.dirty is False

    def test_blit_lands_at_the_right_offset(self):
        fb = Framebuffer()
        fb.blit(Tile(0, 64, 16, TILE_W, TILE_H, bytes([255]) * (TILE_W * TILE_H)))
        assert fb.pixels[16 * WIDTH + 64] == 255
        assert fb.pixels[16 * WIDTH + 63] == 0, "must not bleed left"
        assert fb.pixels[15 * WIDTH + 64] == 0, "must not bleed up"
        assert fb.pixels[(16 + TILE_H) * WIDTH + 64] == 0, "must not bleed down"
        assert fb.dirty is True

    def test_the_full_grid_covers_every_pixel(self):
        fb = Framebuffer()
        for x in (0, 64, 128):
            for y in (0, 16, 32, 48, 64, 80):
                fb.blit(Tile(0, x, y, TILE_W, TILE_H, bytes([1]) * (TILE_W * TILE_H)))
        assert all(fb.pixels), "3x6 tiles of 64x16 is exactly 192x96"

    def test_a_tile_off_the_right_edge_is_clipped_not_wrapped(self):
        fb = Framebuffer()
        fb.blit(Tile(0, WIDTH - 4, 0, TILE_W, TILE_H, bytes([255]) * (TILE_W * TILE_H)))
        assert fb.pixels[WIDTH - 1] == 255
        assert fb.pixels[WIDTH] == 0, "row 1 column 0 must not receive the overflow"

    def test_a_tile_below_the_bottom_is_ignored(self):
        fb = Framebuffer()
        fb.blit(Tile(0, 0, HEIGHT, TILE_W, TILE_H, bytes([255]) * (TILE_W * TILE_H)))
        assert not any(fb.pixels)

    def test_a_later_tile_replaces_an_earlier_one(self):
        fb = Framebuffer()
        fb.blit(Tile(0, 0, 0, TILE_W, TILE_H, bytes([255]) * (TILE_W * TILE_H)))
        fb.blit(Tile(0, 0, 0, TILE_W, TILE_H, bytes([9]) * (TILE_W * TILE_H)))
        assert fb.pixels[0] == 9


class TestPng:
    def test_is_a_png(self):
        assert png_grayscale(bytes(4), 2, 2).startswith(b"\x89PNG\r\n\x1a\n")

    def test_header_declares_grayscale_at_the_right_size(self):
        png = png_grayscale(bytes(192 * 96), 192, 96)
        ihdr = png[png.index(b"IHDR") + 4 :][:13]
        w, h, depth, colour = struct.unpack("!IIBB", ihdr[:10])
        assert (w, h, depth, colour) == (192, 96, 8, 0), "8-bit greyscale"

    def test_pixels_survive_a_round_trip(self):
        pixels = bytes(range(256)) * 4  # 1024 bytes
        png = png_grayscale(pixels, 64, 16)
        start = png.index(b"IDAT") + 4
        length = struct.unpack("!I", png[start - 8 : start - 4])[0]
        raw = zlib.decompress(png[start : start + length])
        # Each row is prefixed with filter byte 0.
        rows = [raw[i * 65 + 1 : (i + 1) * 65] for i in range(16)]
        assert b"".join(rows) == pixels

    def test_every_chunk_carries_a_valid_crc(self):
        png = png_grayscale(bytes(64), 8, 8)
        i = 8
        seen = []
        while i < len(png):
            (n,) = struct.unpack("!I", png[i : i + 4])
            kind = png[i + 4 : i + 8]
            body = png[i + 4 : i + 8 + n]
            (crc,) = struct.unpack("!I", png[i + 8 + n : i + 12 + n])
            assert crc == zlib.crc32(body), f"{kind!r} chunk CRC"
            seen.append(kind)
            i += 12 + n
        assert seen == [b"IHDR", b"IDAT", b"IEND"]

    def test_size_mismatch_is_refused(self):
        with pytest.raises(ValueError, match="expected 100 bytes"):
            png_grayscale(bytes(10), 10, 10)

    def test_a_real_screen_compresses_small_enough_to_stream(self):
        # A mostly-dark 192x96 screen must not cost much per frame over the websocket.
        fb = Framebuffer()
        fb.blit(Tile(0, 64, 32, TILE_W, TILE_H, bytes([255]) * (TILE_W * TILE_H)))
        assert len(fb.png()) < 2000
