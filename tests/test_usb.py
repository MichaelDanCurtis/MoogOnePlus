"""Tests for reading the instrument's USB descriptors.

The fixture is a real `ioreg -a` property list, trimmed to the Moog One's own
registry entries and recorded 2026-09-05 from the instrument over a USB-B cable.
It is kept because the finding it encodes — MIDIStreaming present, AudioStreaming
absent — is the answer to "does this present like a Digitone", and a regression
that started reporting audio would otherwise only show up with hardware attached.
"""

from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from moogone.usb import (
    CLASS_AUDIO,
    PRODUCT_MOOG_ONE,
    SUBCLASS_AUDIO_STREAMING,
    SUBCLASS_MIDI_STREAMING,
    VENDOR_MOOG,
    Device,
    Interface,
    parse_ioreg,
)

FIXTURE = Path("tests/fixtures/ioreg-moog-one.plist")


@pytest.fixture
def moog() -> Device:
    devices = parse_ioreg(FIXTURE.read_bytes())
    assert len(devices) == 1
    return devices[0]


class TestTheRecordedInstrument:
    def test_it_is_the_moog_one(self, moog):
        assert (moog.vendor, moog.product) == (VENDOR_MOOG, PRODUCT_MOOG_ONE)
        assert moog.name == "Moog One"
        assert moog.vendor_name == "Moog Music, Inc"

    def test_it_speaks_midi(self, moog):
        assert moog.has_midi is True
        midi = [i for i in moog.interfaces if i.subclass == SUBCLASS_MIDI_STREAMING]
        assert len(midi) == 1
        # Bulk IN and bulk OUT: the hardware can transmit as well as receive, which
        # is why silence on the port is a settings question and not a wiring one.
        assert midi[0].endpoints == 2

    def test_it_carries_no_audio(self, moog):
        assert moog.has_audio is False
        assert not [i for i in moog.interfaces if i.subclass == SUBCLASS_AUDIO_STREAMING]

    def test_audio_control_interfaces_are_not_audio(self, moog):
        # Every interface on this device is class AUDIO, including the MIDI one --
        # USB-MIDI lives under the audio class. Testing the class rather than the
        # subclass reports an audio device that does not exist.
        assert all(i.cls == CLASS_AUDIO for i in moog.interfaces)
        assert moog.has_audio is False

    def test_one_configuration_was_never_read(self, moog):
        assert moog.configurations == 2
        assert moog.unread_configurations == 1


class TestParsing:
    def test_absent_device_gives_no_devices(self):
        assert parse_ioreg(FIXTURE.read_bytes(), vendor=0x0001, product=0x0002) == []

    def test_a_bare_plist_is_not_a_crash(self):
        assert parse_ioreg(plistlib.dumps([])) == []

    def test_interfaces_come_back_in_order(self, moog):
        numbers = [i.number for i in moog.interfaces]
        assert numbers == sorted(numbers)


class TestCapabilityFlags:
    def _dev(self, *subclasses: int) -> Device:
        return Device(
            vendor=VENDOR_MOOG,
            product=PRODUCT_MOOG_ONE,
            interfaces=tuple(Interface(n, 0, CLASS_AUDIO, s, 2) for n, s in enumerate(subclasses)),
        )

    def test_audio_streaming_is_what_makes_it_an_audio_device(self):
        assert self._dev(SUBCLASS_AUDIO_STREAMING).has_audio is True
        assert self._dev(SUBCLASS_MIDI_STREAMING).has_audio is False

    def test_a_device_can_be_both(self):
        both = self._dev(SUBCLASS_AUDIO_STREAMING, SUBCLASS_MIDI_STREAMING)
        assert both.has_audio and both.has_midi

    def test_label_names_the_subclass(self):
        assert Interface(0, 0, CLASS_AUDIO, SUBCLASS_MIDI_STREAMING, 2).label == ("MIDIStreaming")
        assert Interface(0, 0, 3, 0, 1).label == "class 3"
