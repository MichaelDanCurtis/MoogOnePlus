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
    def sampler(self, voices_per_note=4):
        c = FakeClient()
        s = Sampler(c, voices_per_note=voices_per_note)
        # frames matters: the sampler uses it to work out when a voice frees itself,
        # and a zero-length sample is one that has already finished.
        s.map.spread = Sample("bell", 1100, root_note=60, frames=48000)
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

    def test_retriggering_a_key_layers_rather_than_cutting(self):
        """A hardware sampler lets a repeated note ring over itself. So does this."""
        s, c = self.sampler(voices_per_note=4)
        first = s.note_on(60)
        c.sent.clear()
        second = s.note_on(60)
        assert second != first
        assert not any(m[0] == "/n_free" for m in c.sent), "the first copy keeps ringing"

    def test_layering_stops_at_voices_per_note(self):
        s, c = self.sampler(voices_per_note=3)
        nodes = [s.note_on(60) for _ in range(3)]
        c.sent.clear()
        s.note_on(60)
        freed = [m[1] for m in c.sent if m[0] == "/n_free"]
        assert freed == [nodes[0]], "the oldest layer is the one that goes"

    def test_a_reused_slot_is_freed_only_while_it_could_still_sound(self):
        """`/n_free` for a node that already freed itself is answered with `/fail`,
        which the NEXT request reads instead of its own reply. So a slot is only
        cleared when the arithmetic says it can still be playing."""
        s, c = self.sampler()
        s.map.spread = Sample("blip", 1100, root_note=60, frames=1)   # over immediately
        for _ in range(MAX_VOICES + 1):
            s.note_on(60)
        assert not any(m[0] == "/n_free" and m[1] >= FIRST_NODE + MAX_VOICES
                       for m in c.sent)
        # A long sample, all slots used: now the wrap-around must free.
        s2, c2 = self.sampler(voices_per_note=MAX_VOICES)
        s2.map.spread = Sample("long", 1100, root_note=60, frames=48000 * 600)
        for _ in range(MAX_VOICES + 1):
            s2.note_on(60)
        assert any(m[0] == "/n_free" for m in c2.sent), "a live slot must be cleared"

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

    def test_stop_all_does_not_free_voices_that_have_already_ended(self):
        import time as _t

        s, c = self.sampler()
        # 480 frames is 10 ms; sleeping past it makes the expiry unambiguous rather
        # than racing the microseconds between two function calls.
        s.map.spread = Sample("blip", 1100, root_note=60, frames=480)
        s.note_on(60)
        _t.sleep(0.05)
        c.sent.clear()
        s.stop_all()
        assert not any(m[0] == "/n_free" for m in c.sent)

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


class TestLiveTrigger:
    """The note stream drives the sampler; note-offs must not read as hits."""

    def test_a_note_on_plays_and_a_note_off_does_not_free(self):
        from moogone.performance import encode_note, encode_note_off

        c = FakeClient()
        s = Sampler(c)
        s.map.spread = Sample("bell", 1100, root_note=60)

        class Live:
            def __init__(self, sampler):
                self.sampler = sampler
                self.notes = []

            _feed = None

        # Drive the decode path directly, which is what LiveSampler._feed does.
        from moogone.performance import Note, decode

        on = decode(encode_note(64, 0.75))
        off = decode(encode_note_off(64))
        assert isinstance(on, Note) and not on.is_note_off
        assert off.is_note_off

        s.note_on(on.note, on.midi_velocity)
        assert len(c.news()) == 1
        c.sent.clear()
        s.note_off(off.note)
        assert not any(m[0] == "/n_free" for m in c.sent), "a one-shot runs to its end"

    def test_velocity_from_the_stream_reaches_the_voice(self):
        from moogone.performance import decode, encode_note

        c = FakeClient()
        s = Sampler(c)
        s.map.spread = Sample("bell", 1100, root_note=60)
        note = decode(encode_note(60, 40 / 127))
        s.note_on(note.note, note.midi_velocity)
        amp = c.arg(c.news()[0], "amp")
        assert amp == pytest.approx(velocity_to_amp(40), rel=1e-3)


class TestTriggerFromMidi:
    """The low-latency path: MIDI arriving at this machine, not the captured stream.

    Measured on hardware, the captured path adds +373 ms with a 767 ms spread. This
    one skips the SSH hop entirely, which is the whole reason it exists.
    """

    def sampler(self):
        c = FakeClient()
        s = Sampler(c)
        s.map.spread = Sample("bell", 1100, root_note=60, frames=48000)
        return s, c

    def test_note_on_plays(self):
        from moogone.sampler import trigger_from_midi

        s, c = self.sampler()
        assert trigger_from_midi(s, [0x90, 64, 100]) is not None
        assert c.arg(c.news()[0], "rate") == pytest.approx(2 ** (4 / 12))

    def test_a_note_on_at_velocity_zero_is_a_release(self):
        """Half the controllers ever made send note-off this way. Treating only 0x80
        as a release leaves notes hanging on the other half."""
        from moogone.sampler import trigger_from_midi

        s, c = self.sampler()
        trigger_from_midi(s, [0x90, 64, 100])
        c.sent.clear()
        assert trigger_from_midi(s, [0x90, 64, 0]) is None
        assert not c.news(), "velocity 0 must not start a voice"

    def test_note_off_plays_nothing(self):
        from moogone.sampler import trigger_from_midi

        s, c = self.sampler()
        assert trigger_from_midi(s, [0x80, 64, 0]) is None
        assert not c.news()

    def test_the_channel_is_ignored(self):
        from moogone.sampler import trigger_from_midi

        s, _c = self.sampler()
        assert trigger_from_midi(s, [0x95, 60, 90]) is not None

    @pytest.mark.parametrize("message", [[], [0x90], [0x90, 60], [0xB0, 7, 100], [0xF8]])
    def test_anything_that_is_not_a_note_is_ignored(self, message):
        from moogone.sampler import trigger_from_midi

        s, c = self.sampler()
        assert trigger_from_midi(s, message) is None
        assert not c.news()

    def test_velocity_reaches_the_voice(self):
        from moogone.sampler import trigger_from_midi

        s, c = self.sampler()
        trigger_from_midi(s, [0x90, 60, 40])
        assert c.arg(c.news()[0], "amp") == pytest.approx(velocity_to_amp(40))

    def test_the_modes_are_the_two_that_exist(self):
        from moogone.sampler import TRIGGER_MODES

        assert TRIGGER_MODES == ("keys", "midi")
