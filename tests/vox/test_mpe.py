"""MPE and poly-aftertouch decoding.

The discriminating cases: pressure on the wrong channel, a stolen voice, and a master-channel
message that must fan out to every note in the zone.
"""

import pytest

from moogone.vox.mpe import MpeDecoder, NoteEvent, VoiceTracker, ZoneConfig


def on(ch, note, vel=100):
    return [0x90 | ch, note, vel]


def off(ch, note):
    return [0x80 | ch, note, 0]


def chan_pressure(ch, p):
    return [0xD0 | ch, p]


def poly_pressure(ch, note, p):
    return [0xA0 | ch, note, p]


def cc(ch, num, val):
    return [0xB0 | ch, num, val]


def bend(ch, value14):
    return [0xE0 | ch, value14 & 0x7F, (value14 >> 7) & 0x7F]


class TestVoiceTracker:
    def test_allocates_lowest_free_voice(self):
        t = VoiceTracker(4)
        assert [t.allocate(n) for n in (60, 62, 64)] == [0, 1, 2]
        t.release(62)
        assert t.allocate(65) == 1

    def test_steals_oldest_when_full(self):
        t = VoiceTracker(2)
        t.allocate(60)
        t.allocate(62)
        v = t.allocate(64)
        assert v == 0, "voice 0 held the oldest note and must be the one stolen"
        assert t.voice_for(60) is None
        assert t.voice_for(64) == 0

    def test_oldest_reports_the_next_victim(self):
        t = VoiceTracker(3)
        assert t.oldest() is None
        t.allocate(60)
        t.allocate(62)
        assert t.oldest() == 0
        t.release(60)
        assert t.oldest() == 1

    def test_release_unknown_note_is_none_not_error(self):
        assert VoiceTracker(2).release(99) is None

    def test_retrigger_same_note_keeps_its_voice(self):
        t = VoiceTracker(4)
        assert t.allocate(60) == 0
        assert t.allocate(60) == 0
        assert len(t.active()) == 1


class TestPolyAftertouch:
    def test_pressure_keyed_by_note_on_one_channel(self):
        d = MpeDecoder()
        d.feed(on(0, 60))
        d.feed(on(0, 64))
        ev = d.feed(poly_pressure(0, 64, 127))
        assert ev == [NoteEvent("pressure", 1, 64, 1.0, 0)]

    def test_pressure_for_a_note_not_held_is_dropped(self):
        d = MpeDecoder()
        assert d.feed(poly_pressure(0, 60, 50)) == []


class TestMpeLowerZone:
    def test_member_channel_pressure_goes_to_that_channels_note(self):
        d = MpeDecoder(ZoneConfig("lower", members=15))
        d.feed(on(1, 60))  # member channel 2 (index 1)
        d.feed(on(2, 64))  # member channel 3
        ev = d.feed(chan_pressure(2, 64))
        assert ev == [NoteEvent("pressure", 1, 64, pytest.approx(64 / 127), 2)]

    def test_pressure_on_a_member_with_no_note_is_dropped(self):
        d = MpeDecoder(ZoneConfig("lower"))
        assert d.feed(chan_pressure(5, 100)) == []

    def test_master_channel_pressure_fans_out_to_every_note(self):
        """MPE: the master channel addresses the whole zone."""
        d = MpeDecoder(ZoneConfig("lower"))
        d.feed(on(1, 60))
        d.feed(on(2, 64))
        ev = d.feed(chan_pressure(0, 127))
        assert sorted(e.note for e in ev) == [60, 64]
        assert all(e.kind == "pressure" and e.value == 1.0 for e in ev)

    def test_slide_is_cc74_on_member_channel(self):
        d = MpeDecoder(ZoneConfig("lower"))
        d.feed(on(3, 67))
        assert d.feed(cc(3, 74, 127)) == [NoteEvent("slide", 0, 67, 1.0, 3)]

    def test_other_ccs_are_not_slide(self):
        d = MpeDecoder(ZoneConfig("lower"))
        d.feed(on(3, 67))
        assert d.feed(cc(3, 1, 127)) == []

    def test_bend_is_signed_and_normalised(self):
        d = MpeDecoder(ZoneConfig("lower", bend_range=48))
        d.feed(on(1, 60))
        assert d.feed(bend(1, 8192)) == [NoteEvent("bend", 0, 60, 0.0, 1)]
        assert d.feed(bend(1, 16383))[0].value == pytest.approx(1.0, abs=1e-3)
        assert d.feed(bend(1, 0))[0].value == pytest.approx(-1.0)

    def test_note_off_frees_the_channel(self):
        d = MpeDecoder(ZoneConfig("lower"))
        d.feed(on(1, 60))
        offs = d.feed(off(1, 60))
        assert offs == [NoteEvent("off", 0, 60, 0.0, 1)]
        assert d.feed(chan_pressure(1, 100)) == []

    def test_note_on_velocity_zero_is_off(self):
        d = MpeDecoder(ZoneConfig("lower"))
        d.feed(on(1, 60))
        assert d.feed(on(1, 60, 0))[0].kind == "off"


class TestMpeUpperZone:
    def test_master_is_channel_16_and_members_count_down(self):
        d = MpeDecoder(ZoneConfig("upper", members=3))
        # members are indices 12, 13, 14; master is index 15
        d.feed(on(14, 60))
        d.feed(on(12, 64))
        assert len(d.feed(chan_pressure(15, 127))) == 2
        assert d.feed(chan_pressure(11, 127)) == [], "index 11 is outside the upper zone"


class TestVoiceStealingProducesOffThenOn:
    def test_steal_emits_off_for_the_victim(self):
        d = MpeDecoder(n_voices=2)
        d.feed(on(0, 60))
        d.feed(on(0, 62))
        ev = d.feed(on(0, 64))
        kinds = [(e.kind, e.note, e.voice) for e in ev]
        assert kinds == [("off", 60, 0), ("on", 64, 0)]


class TestGarbage:
    def test_truncated_message_is_ignored(self):
        assert MpeDecoder().feed([0x90]) == []
        assert MpeDecoder().feed([]) == []

    def test_system_messages_are_ignored(self):
        assert MpeDecoder().feed([0xF8]) == []
