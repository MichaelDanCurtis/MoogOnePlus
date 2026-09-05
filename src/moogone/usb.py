"""What the instrument's USB socket actually offers, read from its descriptors.

The question this answers is whether the Moog One presents itself the way an
Elektron Digitone does — audio and MIDI over one cable. It does not. The socket
declares a MIDIStreaming interface and no AudioStreaming interface, so no audio
device appears on the host, and that is the descriptors being honest rather than
a driver failing.

Descriptors are read from `ioreg`, not libusb, for two reasons: it needs no
dependency and no device open, and on macOS libusb reports the *active*
configuration for every configuration index, which silently turns "I read both
configurations" into "I read the first one twice".

The parsing here is pure so it can be tested against a recorded property list;
`probe()` is the only part that shells out.
"""

from __future__ import annotations

import plistlib
import subprocess
from dataclasses import dataclass, field

#: Moog Music, Inc.
VENDOR_MOOG = 0x2662
#: The Moog One.
PRODUCT_MOOG_ONE = 0x000D

CLASS_AUDIO = 1

SUBCLASS_AUDIO_CONTROL = 1
#: The interface that would carry samples. Its absence is the whole finding.
SUBCLASS_AUDIO_STREAMING = 2
SUBCLASS_MIDI_STREAMING = 3

_SUBCLASS_NAMES = {
    SUBCLASS_AUDIO_CONTROL: "AudioControl",
    SUBCLASS_AUDIO_STREAMING: "AudioStreaming",
    SUBCLASS_MIDI_STREAMING: "MIDIStreaming",
}


@dataclass(frozen=True)
class Interface:
    number: int
    alternate: int
    cls: int
    subclass: int
    endpoints: int
    configuration: int = 1

    @property
    def label(self) -> str:
        if self.cls != CLASS_AUDIO:
            return f"class {self.cls}"
        return _SUBCLASS_NAMES.get(self.subclass, f"subclass {self.subclass}")


@dataclass(frozen=True)
class Device:
    vendor: int
    product: int
    name: str = ""
    vendor_name: str = ""
    configurations: int = 1
    interfaces: tuple[Interface, ...] = field(default_factory=tuple)

    def _has(self, subclass: int) -> bool:
        return any(i.cls == CLASS_AUDIO and i.subclass == subclass for i in self.interfaces)

    @property
    def has_midi(self) -> bool:
        """The device can carry MIDI over USB."""
        return self._has(SUBCLASS_MIDI_STREAMING)

    @property
    def has_audio(self) -> bool:
        """The device can carry audio samples over USB.

        False for the Moog One. Note that AudioControl interfaces are present
        without it — they are the topology descriptors an audio function would
        hang off, so testing for `CLASS_AUDIO` alone reports audio that does not
        exist. The subclass is what matters.
        """
        return self._has(SUBCLASS_AUDIO_STREAMING)

    @property
    def unread_configurations(self) -> int:
        """Configurations the host did not select, whose contents are unknown."""
        return max(0, self.configurations - 1)


def _walk(node):
    yield node
    for child in node.get("IORegistryEntryChildren", []) or []:
        yield from _walk(child)


def parse_ioreg(data: bytes, vendor: int = VENDOR_MOOG, product: int = PRODUCT_MOOG_ONE):
    """Every matching device in an `ioreg -a` property list.

    Interfaces are separate registry entries rather than children of the device
    entry, so they are matched by vendor and product rather than by position.
    """
    roots = plistlib.loads(data)
    if not isinstance(roots, list):
        roots = [roots]

    devices: dict[tuple[int, int], dict] = {}
    interfaces: list[Interface] = []
    for root in roots:
        for node in _walk(root):
            if node.get("idVendor") != vendor or node.get("idProduct") != product:
                continue
            if "bInterfaceClass" in node:
                interfaces.append(
                    Interface(
                        number=node.get("bInterfaceNumber", 0),
                        alternate=node.get("bAlternateSetting", 0),
                        cls=node["bInterfaceClass"],
                        subclass=node.get("bInterfaceSubClass", 0),
                        endpoints=node.get("bNumEndpoints", 0),
                        configuration=node.get("bConfigurationValue", 1),
                    )
                )
            elif "bNumConfigurations" in node:
                devices.setdefault((vendor, product), node)

    if not devices and not interfaces:
        return []
    node = devices.get((vendor, product), {})
    return [
        Device(
            vendor=vendor,
            product=product,
            name=node.get("USB Product Name", ""),
            vendor_name=node.get("USB Vendor Name", ""),
            configurations=node.get("bNumConfigurations", 1),
            interfaces=tuple(sorted(interfaces, key=lambda i: (i.number, i.alternate))),
        )
    ]


def probe(vendor: int = VENDOR_MOOG, product: int = PRODUCT_MOOG_ONE) -> list[Device]:
    """Read the live descriptors. macOS only; returns [] if the device is absent."""
    out = subprocess.run(
        ["ioreg", "-w", "0", "-l", "-a", "-c", "IOUSBHostInterface"],
        capture_output=True,
        timeout=30,
        check=False,
    )
    if out.returncode != 0 or not out.stdout:
        return []
    return parse_ioreg(out.stdout, vendor, product)
