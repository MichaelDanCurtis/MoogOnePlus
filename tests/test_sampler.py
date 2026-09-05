"""Tests for the sampler.

No instrument needed: a fake client records the OSC that would have gone out, which
is where the interesting mistakes live — a wrong playback rate, a voice id that
collides, a stereo write to the wrong bus.
"""

from __future__ import annotations

import pytest

from moogone.sampler import (
    FIRST_NODE,
    MAIN_LEFT,
    MAIN_RIGHT,
    MAX_VOICES,
    VOICE_GRAPH,
    Sample,
    SampleMap,
    Sampler,
    SamplerError,
    velocity_to_amp,
)


class FakeClient:
    def __init__(self, frames=48000, channels=2):
        self.sent = []
        self.frames = frames
        self.channels = channels
        self.defs = 0

    def send(self, *args):
        self.sent.append(args)

    def sync(self):
        pass

    def d_recv(self, data):
        self.defs += 1

    def request(self, address, *args, reply=None, timeout=None):
        class R:
            pass
        r = R()
        r.args = [args[0], self.frames, self.channels, 48000.0]
        return r

    def news(self):
        return [a for a in self.sent if a[0] == "/s_new"]

    def arg(self, message, key):
        rest = list(message)
        return rest[rest.index(key) + 1]


class TestRate:
    def test_the_root_note_plays_at_unity(self):
        assert Sample("s", 1, root_note=60).rate_for(60) == pytest.approx(1.0)

    def test_an_octave_up_is_double_speed(self):
        assert Sample("s", 1, root_note=60).rate_for(72) == pytest.approx(2.0)

    def test_an_octave_down_is_half(self):
        assert Sample("s", 1, root_note=60).rate_for(48) == pytest.approx(0.5)

    def test_a_semitone_is_the_twelfth_root_of_two(self):
        assert Sample("s", 1, root_note=60).rate_for(61) == pytest.approx(2 ** (1 / 12))

    def test_a_different_root_shifts_everything(self):
        assert Sample("s", 1, root_note=48).rate_for(60) == pytest.approx(2.0)


class TestVelocity:
    def test_full_velocity_is_unity(self):
        assert velocity_to_amp(127) == pytest.approx(1.0)

    def test_zero_is_silent(self):
        assert velocity_to_amp(0) == 0.0

    def test_quiet_notes_stay_audible(self):
        # Linear velocity buries everything under ~40. The floor is the point.
        amp = velocity_to_amp(20)
        assert amp > 10 ** (-40 / 20), "a soft note must not vanish"
        assert amp < velocity_to_amp(64) < velocity_to_amp(127)

    def test_the_curve_is_monotonic(self):
        values = [velocity_to_amp(v) for v in range(0, 128, 8)]
        assert values == sorted(values)

    @pytest.mark.parametrize("v", [-10, 200])
    def test_out_of_range_velocity_is_clamped_not_an_error(self, v):
        assert 0.0 <= velocity_to_amp(v) <= 1.0


class TestSampleMap:
    def test_a_spread_sample_covers_every_note(self):
        m = SampleMap(spread=Sample("piano", 1))
        assert m.for_note(21) is m.for_note(108) is m.spread

    def test_an_assignment_overrides_the_spread(self):
        spread, kick = Sample("piano", 1), Sample("kick", 2)
        m = SampleMap(spread=spread)
        m.assign(36, kick)
        assert m.for_note(36) is kick
        assert m.for_note(37) is spread

    def test_nothing_mapped_is_none_not_an_error(self):
        assert SampleMap().for_note(60) is None

    def test_clearing_falls_back_to_the_spread(self):
        m = SampleMap(spread=Sample("piano", 1))
        m.assign(36, Sample("kick", 2))
        m.clear(36)
        assert m.for_note(36) is m.spread

    @pytest.mark.parametrize("note", [-1, 128])
    def test_an_impossible_note_is_refused(self, note):
        with pytest.raises(SamplerError, match="outside 0-127"):
            SampleMap().assign(note, Sample("x", 1))


class TestPlaying:
    def sampler(self):
        c = FakeClient()
        s = Sampler(c)
        s.map.spread = Sample("bell", 1100, root_note=60)
        return s, c

    def test_note_on_writes_to_both_main_buses(self):
        s, c = self.sampler()
        s.note_on(60, 100)
        msg = c.news()[0]
        assert c.arg(msg, "left") == MAIN_LEFT
        assert c.arg(msg, "right") == MAIN_RIGHT
        assert (MAIN_LEFT, MAIN_RIGHT) == (0, 7), "the mapped main outs, not 0 and 1"

    def test_the_graph_writes_the_two_buses_separately(self):
        # Out.ar writes CONSECUTIVE buses, so one stereo Out.ar cannot reach 0 and 7.
        assert "Out.ar(left, sig[0])" in VOICE_GRAPH
        assert "Out.ar(right, sig[1])" in VOICE_GRAPH

    def test_the_voice_frees_itself_when_the_buffer_ends(self):
        assert "doneAction: 2" in VOICE_GRAPH

    def test_rate_follows_the_note(self):
        s, c = self.sampler()
        s.note_on(72, 100)
        assert c.arg(c.news()[0], "rate") == pytest.approx(2.0)
        assert c.arg(c.news()[0], "buf") == 1100

    def test_an_unmapped_note_plays_nothing(self):
        c = FakeClient()
        s = Sampler(c)
        assert s.note_on(60) is None
        assert c.news() == []

    def test_voice_ids_cycle_rather_than_growing(self):
        s, _c = self.sampler()
        nodes = [s.note_on(60 + (i % 12)) for i in range(MAX_VOICES + 4)]
        assert min(nodes) >= FIRST_NODE
        assert max(nodes) < FIRST_NODE + MAX_VOICES

    def test_retriggering_the_same_note_frees_the_previous_voice(self):
        s, c = self.sampler()
        first = s.note_on(60)
        c.sent.clear()
        s.note_on(60)
        assert ("/n_free", first) in c.sent, "a repeated key must not stack voices"

    def test_note_off_does_not_cut_the_sample(self):
        """One-shots run to their end. Freeing on note-off would clip percussion."""
        s, c = self.sampler()
        s.note_on(60)
        c.sent.clear()
        s.note_off(60)
        assert not any(m[0] == "/n_free" for m in c.sent)

    def test_stop_all_frees_what_is_sounding(self):
        s, c = self.sampler()
        a, b = s.note_on(60), s.note_on(64)
        c.sent.clear()
        s.stop_all()
        freed = {m[1] for m in c.sent if m[0] == "/n_free"}
        assert freed == {a, b}

    def test_the_synthdef_is_sent_once(self):
        s, c = self.sampler()
        s.ensure_synthdef(); s.ensure_synthdef()
        assert c.defs == 1


class TestLoading:
    def test_a_mono_file_is_refused_with_a_reason(self):
        c = FakeClient(channels=1)
        with pytest.raises(SamplerError, match="channel"):
            Sampler(c).load("mono", "/tmp/x.wav")

    def test_an_empty_buffer_is_refused(self):
        c = FakeClient(frames=0)
        with pytest.raises(SamplerError, match="empty buffer"):
            Sampler(c).load("bad", "/tmp/x.wav")

    def test_buffers_do_not_collide(self):
        c = FakeClient()
        s = Sampler(c)
        a = s.load("one", "/tmp/a.wav")
        b = s.load("two", "/tmp/b.wav")
        assert a.buffer != b.buffer

    def test_pushing_a_missing_file_says_so(self):
        with pytest.raises(SamplerError, match="no such file"):
            Sampler(FakeClient()).push("/nope/missing.wav", "192.0.2.1")
