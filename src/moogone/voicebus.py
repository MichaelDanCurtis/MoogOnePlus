"""The `/x` parameter protocol on the Moog One's voice bus.

`las-frontend` sets a voice-engine parameter by sending `/x` to the voice controller
on port 7770 with an eight-byte blob:

    /x  ,b   <u16 param_id> <u16 zero> <f32 value>

**The blob is little-endian inside a big-endian OSC message.** Address, type tag and
blob length follow OSC and are big-endian; the payload is the XMOS's own byte order.
Reading it as big-endian yields denormal floats around 1e-36 that look like garbage
rather than like a wrong guess, which is a large part of why this protocol went
unrecognised through an entire address-space sweep — and the sweep could not have
found it anyway, because `/x` carries no address to sweep for.

Decoded by sweeping MIDI CC 7 across known values and reading the float back:

    CC7   0 -> 0.00000      64 -> 0.50394     127 -> 1.00000
    CC7   1 -> 0.00787     100 -> 0.78740

which is exactly `value / 127`, on parameter 358 — master volume.

## Writes are delivered and ignored

Sending a byte-identical `/x` to the voice controller **does not change anything**.
This was measured, not assumed: the packet was captured arriving at
`203.0.113.2:7770`, and four alternating trials of 0.05 against 0.90 on master
volume produced readings that overlap randomly. The same message sent to
`las-frontend` itself also arrives and also does nothing.

The voice controller appears to act only on parameters from the socket
`las-frontend` registered with at startup — the `/auto` message and the LTRQ/LTRS
exchange on 9501. So this module encodes and decodes; it does not pretend to
command. **Reading this bus is how you learn a parameter's id; the way to change one
is still the instrument's own control path.**
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

VOICE_BUS_PORT = 7770

#: Master volume. The only id confirmed against a known control so far; others are
#: discovered by moving a control and watching what `/x` carries.
PARAM_MASTER_VOLUME = 358

_ADDRESS = b"/x\x00\x00"
_TAG = b",b\x00\x00"
BLOB_LEN = 8


@dataclass(frozen=True)
class ParamWrite:
    param: int
    value: float

    @property
    def as_midi(self) -> int:
        """The 0-127 value this corresponds to, for parameters scaled that way."""
        return round(self.value * 127)


def encode(param: int, value: float) -> bytes:
    """The exact bytes `las-frontend` sends. Big-endian OSC, little-endian payload."""
    if not 0 <= param <= 0xFFFF:
        raise ValueError(f"param id {param} does not fit in 16 bits")
    blob = struct.pack("<HHf", param, 0, value)
    return _ADDRESS + _TAG + struct.pack("!I", len(blob)) + blob


def decode(payload: bytes) -> ParamWrite | None:
    """One `/x` message, or None. None rather than raising: this is fed from a live
    capture carrying several unrelated protocols."""
    if not payload.startswith(_ADDRESS) or len(payload) < 12:
        return None
    if payload[4:8] != _TAG:
        return None
    (blob_len,) = struct.unpack("!I", payload[8:12])
    blob = payload[12 : 12 + blob_len]
    if len(blob) != blob_len or blob_len < BLOB_LEN:
        return None
    param, _zero = struct.unpack("<HH", blob[0:4])
    (value,) = struct.unpack("<f", blob[4:8])
    return ParamWrite(param, value)
