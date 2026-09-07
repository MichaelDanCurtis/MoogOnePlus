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


def test_the_capture_loop_stops_when_its_ssh_goes_away():
    # Killing the local ssh does NOT stop the remote loop on its own: gzip buffers,
    # so nothing writes to the dead channel, nothing gets SIGPIPE, and the while
    # goes on reading /dev/fb0 forever. Three of these were found running at once
    # after three bridge restarts, together holding a core at 100% on the machine
    # whose CPU is the scarcest thing it has.
    command = MainScreen("h", lambda f: None, period=0.4).command
    assert "cat > /dev/null" in command, "nothing waits on stdin, so nothing notices"
    assert "kill 0" in command, "nothing takes the process group down"
    # The loop must be in the background, or the watchdog never gets to run.
    assert command.index("&") < command.index("cat > /dev/null")


def test_the_watchdog_cannot_corrupt_the_frame_stream():
    # The frames are binary and share stdout with anything else the command prints.
    # cat's output goes to /dev/null, not to the channel.
    assert "cat > /dev/null" in MainScreen("h", lambda f: None).command


def test_the_capture_holds_stdin_open():
    # The watchdog waits for EOF on stdin, so ssh must be given a pipe to hold.
    # DEVNULL would be EOF immediately and the loop would die at birth; inheriting
    # the parent's stdin would have the instrument eat the terminal's input.
    import inspect

    source = inspect.getsource(MainScreen.run)
    assert "stdin=subprocess.PIPE" in source


def test_the_sweep_kills_the_shells_not_only_the_dd():
    # The loop respawns the dd immediately, so killing that alone changes nothing.
    # Matching on the argument catches the shells, whose command lines carry it.
    sweep = MainScreen("h", lambda f: None).sweep_command
    assert "/dev/fb0" in sweep
    assert "kill -9" in sweep


def test_the_sweep_does_not_kill_itself():
    # This command's own line contains the pattern it greps for. A sweep that
    # matches itself kills itself first and leaves every loop running.
    sweep = MainScreen("h", lambda f: None).sweep_command
    assert "me=$$" in sweep
    assert '[ "$p" = "$me" ]' in sweep


def test_a_failed_sweep_does_not_stop_the_feed(monkeypatch):
    # An instrument that cannot be swept is still an instrument worth watching.
    def boom(*a, **k):
        raise OSError("no route to host")

    monkeypatch.setattr("moogone.screen.subprocess.run", boom)
    MainScreen("h", lambda f: None).sweep()  # must not raise


def test_a_dropped_screen_feed_is_rebuilt():
    # MainScreen.run returns whenever the feed ends -- ssh dropped, audio engine
    # restarted underneath it, capture loops swept. The bridge used to call it once,
    # so one hiccup ended the display mirror for the life of the process, silently,
    # while the rest of the panel carried on working.
    import inspect

    from moogone.vox.bridge import SCREEN_RETRY_MAX, SCREEN_RETRY_MIN, Bridge

    body = inspect.getsource(Bridge._screen_loop)
    assert "while True:" in body, "the feed is not rebuilt when it ends"
    assert "MainScreen(" in body[body.index("while True:") :], "reuses a stopped feed"
    assert 0 < SCREEN_RETRY_MIN < SCREEN_RETRY_MAX


def test_a_stalled_feed_is_torn_down_rather_than_waited_on():
    # Killing the capture on the instrument does NOT end the local read: the
    # orphaned cat and gzip hold the ssh channel's pipes open, read1 blocks, and
    # run() never returns -- so a caller's reconnect loop never gets a turn.
    # Measured on hardware: 80s after the remote side was killed, the local ssh was
    # still alive and no frame had arrived. Reading nothing is the only symptom
    # common to every way this breaks, so it is the thing worth watching.
    import inspect

    body = inspect.getsource(MainScreen._watch_for_stall)
    assert "self.stop()" in body, "a stalled feed must be torn down, not waited on"
    assert "_last_frame" in body


def test_the_stall_timeout_is_generous_against_the_frame_period():
    # A slow instrument is not a broken one.
    fast = MainScreen("h", lambda f: None, period=0.4)
    slow = MainScreen("h", lambda f: None, period=2.0)
    assert fast.stall_timeout >= 10.0
    assert slow.stall_timeout > slow.period * 10
    assert MainScreen("h", lambda f: None, stall_timeout=5.0).stall_timeout == 5.0


def test_the_watchdog_starts_the_clock_before_the_first_frame():
    # Otherwise _last_frame is 0.0, monotonic() - 0.0 is enormous, and the watchdog
    # kills the feed on its first tick before a frame could possibly have arrived.
    import inspect

    body = inspect.getsource(MainScreen.run)
    assert body.index("_last_frame = time.monotonic()") < body.index("Popen")
