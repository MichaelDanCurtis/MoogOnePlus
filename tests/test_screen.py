"""Tests for the main-screen feed.

The instrument's big display is an X server drawing into /dev/fb0 on its own Linux,
so it is read rather than reconstructed. What can go wrong is the plumbing: channel
order, and slicing frames out of a stream that has no delimiters.
"""

from __future__ import annotations

import gzip
import struct
import zlib

import pytest

from moogone.screen import (
    BYTES_PER_PIXEL,
    FRAME_BYTES,
    HEIGHT,
    STRIDE,
    WIDTH,
    MainScreen,
    bgra_to_rgb,
    frames_from,
    png_rgb,
)


def reader_for(data: bytes, chunk: int):
    pos = 0

    def read(_n):
        nonlocal pos
        out = data[pos : pos + chunk]
        pos += len(out)
        return out

    return read


class TestGeometry:
    def test_stride_is_tightly_packed(self):
        # Read off the device: stride 3328 == 832 * 4, so there is no row padding to
        # skip. If that ever stops being true, every row after the first shears.
        assert STRIDE == WIDTH * BYTES_PER_PIXEL == 3328
        assert FRAME_BYTES == STRIDE * HEIGHT

    def test_the_mode_the_device_reports(self):
        assert (WIDTH, HEIGHT) == (832, 480)


class TestBgraToRgb:
    def test_channel_order(self):
        # One pixel: B=1, G=2, R=3, A=255 -> RGB 3,2,1. Getting this backwards gives a
        # picture that looks plausible and has red and blue swapped.
        assert bgra_to_rgb(bytes([1, 2, 3, 255]), 1, 1) == bytes([3, 2, 1])

    def test_alpha_is_dropped(self):
        assert len(bgra_to_rgb(bytes(4 * 10), 10, 1)) == 30

    def test_several_pixels_keep_their_order(self):
        src = bytes([10, 20, 30, 0]) + bytes([40, 50, 60, 0])
        assert bgra_to_rgb(src, 2, 1) == bytes([30, 20, 10, 60, 50, 40])

    def test_a_short_frame_is_refused(self):
        with pytest.raises(ValueError, match="expected"):
            bgra_to_rgb(bytes(10), 8, 8)


class TestPng:
    def test_is_a_truecolour_png_of_the_right_size(self):
        png = png_rgb(bytes(WIDTH * HEIGHT * 3))
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        ihdr = png[png.index(b"IHDR") + 4 :][:10]
        w, h, depth, colour = struct.unpack("!IIBB", ihdr)
        assert (w, h, depth, colour) == (WIDTH, HEIGHT, 8, 2), "8-bit RGB"

    def test_pixels_round_trip(self):
        pixels = bytes(range(256)) * 3  # 768 bytes = 16x16 RGB
        png = png_rgb(pixels, 16, 16)
        start = png.index(b"IDAT") + 4
        (length,) = struct.unpack("!I", png[start - 8 : start - 4])
        raw = zlib.decompress(png[start : start + length])
        rows = [raw[i * 49 + 1 : (i + 1) * 49] for i in range(16)]
        assert b"".join(rows) == pixels

    def test_size_mismatch_is_refused(self):
        with pytest.raises(ValueError):
            png_rgb(bytes(10), 8, 8)


class TestFramesFrom:
    @staticmethod
    def stream(*frames: bytes) -> bytes:
        return gzip.compress(b"".join(frames))

    def test_yields_whole_frames(self):
        a, b = bytes([1]) * 100, bytes([2]) * 100
        got = list(frames_from(reader_for(self.stream(a, b), 4096), frame_bytes=100))
        assert got == [a, b]

    @pytest.mark.parametrize("chunk", [1, 7, 64, 1024])
    def test_a_frame_split_across_reads_is_held_until_complete(self, chunk):
        a, b = bytes([1]) * 100, bytes([2]) * 100
        got = list(frames_from(reader_for(self.stream(a, b), chunk),
                               frame_bytes=100, chunk=chunk))
        assert got == [a, b], "a partial frame must never be emitted short"

    def test_a_trailing_partial_frame_is_not_emitted(self):
        a = bytes([1]) * 100
        data = self.stream(a + bytes([2]) * 40)
        got = list(frames_from(reader_for(data, 4096), frame_bytes=100))
        assert got == [a]

    def test_empty_stream(self):
        assert list(frames_from(reader_for(b"", 4096), frame_bytes=100)) == []

    def test_frames_are_independent_of_gzip_block_boundaries(self):
        # The remote side writes one gzip across the whole loop, so frame edges and
        # compression block edges have no relationship at all.
        frames = [bytes([i]) * 1000 for i in range(5)]
        got = list(frames_from(reader_for(self.stream(*frames), 333),
                               frame_bytes=1000, chunk=333))
        assert got == frames


class TestCommand:
    def test_reads_the_framebuffer_in_a_loop_through_one_gzip(self):
        cmd = MainScreen("192.0.2.1", on_frame=lambda f: None, period=0.5).command
        assert "/dev/fb0" in cmd
        assert f"bs={STRIDE}" in cmd and f"count={HEIGHT}" in cmd
        assert cmd.count("gzip") == 1, "one gzip for the whole stream, not one per frame"
        assert "while" in cmd

    def test_the_period_is_in_the_command(self):
        assert "sleep 0.25" in MainScreen("h", on_frame=lambda f: None, period=0.25).command

    def test_stop_is_safe_before_run(self):
        MainScreen("192.0.2.1", on_frame=lambda f: None).stop()
