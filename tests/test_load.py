"""The load probe. See `moogone.load` for why the figure cannot come from scsynth."""

from __future__ import annotations

from moogone import load


def test_the_busiest_thread_is_the_figure():
    # scsynth does its DSP on one thread and the throttle deschedules that thread,
    # so the process total is the wrong number -- the awk takes the maximum.
    assert "if(d>m) m=d" in load.script()


def test_both_samples_are_taken_before_anything_is_parsed():
    # An earlier version ran awk and grep per thread BETWEEN the two samples and
    # spent longer measuring than the interval it measured over, which reported a
    # single thread at 119% of a core. Nothing but sleep may separate the cats.
    body = load.script()
    first = body.index(".voxload0")
    second = body.index(".voxload1")
    between = body[first:second]
    assert "sleep" in between
    assert "awk" not in between


def test_the_clock_is_the_kernels_own_jiffy_count():
    # Reading wall time from /proc/uptime put one thread at 107% of a core: the
    # uptime and the thread counters are not sampled at the same instant and the
    # skew biases high. /proc/stat is read in the same pass as the threads, so the
    # busy total and the thread total cannot drift apart -- and CLK_TCK cancels,
    # which matters because this box has no getconf to ask.
    body = load.script()
    assert "/proc/stat" in body
    assert "/proc/uptime" not in body


def test_the_awk_program_survives_being_a_python_string():
    # `\n` in a plain literal is a real newline by the time awk sees it, and awk
    # reports an unterminated string and prints nothing at all -- which arrives here
    # as "the instrument could not be measured", not as a syntax error.
    assert "\\n" in load.script()


def test_the_sample_interval_is_whole_seconds():
    # busybox sleep rejects "2.0" outright, and the script goes on to diff two
    # samples taken microseconds apart.
    assert "sleep 2\n" in load.script(2)
    assert "sleep 3\n" in load.script(3)


def test_a_reading_parses_to_a_fraction_of_one_core():
    assert load.parse("0.8190\n") == 0.819


def test_a_box_with_no_scsynth_is_not_a_measurement():
    assert load.parse("NOPID\n") is None


def test_silence_is_not_a_measurement():
    assert load.parse("") is None
    assert load.parse("\n\n") is None


def test_zero_is_not_a_measurement():
    # This instrument's /status.reply reports exactly 0.000 while a thread of its
    # own does 82% of a core. A zero here is the same failure wearing a number, and
    # accepting it would tell the panel every effect fits.
    assert load.parse("0.0000\n") is None


def test_noise_before_the_reading_is_ignored():
    # sh on this box writes its own complaints to stdout.
    assert load.parse("sh: getconf: not found\n0.7500\n") == 0.75
