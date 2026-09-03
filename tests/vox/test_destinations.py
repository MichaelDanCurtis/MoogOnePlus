"""Destinations. The discriminating cases: a blocked destination must refuse, a MIDI
message must be well-formed bytes, and the dispatcher must route by prefix not by luck."""

import pytest

from moogone.osc import decode
from moogone.vox.destinations import (
    GO_NO_GO,
    Dispatcher,
    MidiCC,
    MidiNote,
    RawOsc,
    ScParam,
    VoiceParam,
)


class FakeFx:
    def __init__(self):
        self.calls = []

    def set(self, node_id, name, value):
        self.calls.append((node_id, name, value))


class FakeMidiOut:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(list(msg))


class TestScParam:
    def test_routes_to_fx_set(self):
        fx = FakeFx()
        d = ScParam(fx)
        assert d.write("sc.1035.mix", 0.4) is True
        assert fx.calls == [(1035, "mix", 0.4)]
        assert d.badge.state == "live"

    def test_rejects_malformed_path(self):
        assert ScParam(FakeFx()).write("sc.notanumber.mix", 0.4) is False
        assert ScParam(FakeFx()).write("sc.1035", 0.4) is False


class TestMidi:
    def test_cc_bytes(self):
        p = FakeMidiOut()
        d = MidiCC(p, channel=2)
        assert d.write("midi.cc.74", 1.0) is True
        assert p.sent == [[0xB2, 74, 127]]
        assert d.badge.state == "untested"

    def test_cc_clamps(self):
        p = FakeMidiOut()
        MidiCC(p).write("midi.cc.1", 7.0)
        assert p.sent[-1][2] == 127

    def test_note_on_and_off(self):
        p = FakeMidiOut()
        d = MidiNote(p, channel=0)
        d.write("midi.note.60", 1.0)
        d.write("midi.note.60", 0.0)
        assert p.sent == [[0x90, 60, 100], [0x80, 60, 0]]

    def test_bad_cc_number_is_refused(self):
        assert MidiCC(FakeMidiOut()).write("midi.cc.200", 0.5) is False

    def test_bad_note_number_is_refused(self):
        assert MidiNote(FakeMidiOut()).write("midi.note.128", 1.0) is False


class TestRawOsc:
    def test_encodes_a_float_message(self):
        out = []
        d = RawOsc(out.append)
        assert d.write("osc.lc.kbd.oct", 0.5) is True
        msg = decode(out[0])
        assert msg.address == "/lc/kbd/oct" and msg.args == [0.5]
        assert d.badge.state == "untested"

    def test_wrong_prefix_is_refused(self):
        out = []
        assert RawOsc(out.append).write("sc.1.mix", 0.5) is False
        assert out == []


class TestVoiceParam:
    def test_always_refuses_and_names_the_experiment(self):
        d = VoiceParam()
        assert d.write("voice.3.cutoff", 0.5) is False
        assert d.badge.state == "blocked"
        assert "hold" in d.badge.why.lower() and "cutoff" in d.badge.why.lower()
        assert d.badge.why == GO_NO_GO


class TestDispatcher:
    def test_routes_by_prefix_and_reports_badge(self):
        fx, p = FakeFx(), FakeMidiOut()
        disp = Dispatcher()
        disp.register("sc.", ScParam(fx))
        disp.register("midi.cc.", MidiCC(p))
        disp.register("voice.", VoiceParam())
        assert disp.write("sc.1035.mix", 0.2) == (True, disp.badge_for("sc.1035.mix"))
        ok, badge = disp.write("voice.1.cutoff", 0.2)
        assert ok is False and badge.state == "blocked"

    def test_unknown_prefix_is_not_silently_dropped(self):
        with pytest.raises(KeyError, match="no destination"):
            Dispatcher().write("nowhere.x", 0.1)

    def test_longest_prefix_wins(self):
        disp = Dispatcher()
        a, b = FakeMidiOut(), FakeMidiOut()
        disp.register("midi.", MidiCC(a))
        disp.register("midi.cc.", MidiCC(b))
        disp.write("midi.cc.1", 1.0)
        assert b.sent and not a.sent
