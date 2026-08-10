"""OSC 1.0 messages and bundles."""

from dataclasses import dataclass, field

from . import codec

BUNDLE_PREFIX = b"#bundle\x00"


@dataclass
class Float64:
    """Wrapper forcing an argument to encode as an OSC double ('d')."""

    value: float


@dataclass
class OscMessage:
    address: str
    args: list = field(default_factory=list)

    def encode(self) -> bytes:
        tags = ","
        body = b""
        for arg in self.args:
            if isinstance(arg, Float64):
                tags += "d"
                body += codec.enc_float64(arg.value)
            elif isinstance(arg, bool):
                raise TypeError(f"cannot encode {type(arg)!r} as an OSC argument")
            elif isinstance(arg, int):
                tags += "i"
                body += codec.enc_int32(arg)
            elif isinstance(arg, float):
                tags += "f"
                body += codec.enc_float32(arg)
            elif isinstance(arg, str):
                tags += "s"
                body += codec.enc_string(arg)
            elif isinstance(arg, (bytes, bytearray)):
                tags += "b"
                body += codec.enc_blob(bytes(arg))
            else:
                raise TypeError(f"cannot encode {type(arg)!r} as an OSC argument")
        return codec.enc_string(self.address) + codec.enc_string(tags) + body


@dataclass
class OscBundle:
    timetag: int
    elements: list = field(default_factory=list)

    def encode(self) -> bytes:
        out = BUNDLE_PREFIX + self.timetag.to_bytes(8, "big")
        for element in self.elements:
            payload = element.encode()
            out += codec.enc_int32(len(payload)) + payload
        return out


_DECODERS = {
    "i": codec.dec_int32,
    "f": codec.dec_float32,
    "d": codec.dec_float64,
    "s": codec.dec_string,
    "b": codec.dec_blob,
}


def decode(buf: bytes):
    """Decode a packet into an OscMessage or OscBundle.

    Public API: lenient about trailing bytes in the overall packet.
    Extracts and discards the offset returned by the internal decoder.
    """
    value, _ = _decode_internal(buf)
    return value


def _decode_internal(buf: bytes) -> tuple:
    """Internal decoder dispatcher. Returns (value, offset_after_parsing).

    Used by _decode_bundle to verify full element consumption.
    """
    if buf.startswith(BUNDLE_PREFIX):
        return _decode_bundle(buf)
    return _decode_message(buf)


def _decode_message(buf: bytes) -> tuple:
    """Decode a message. Returns (message, offset_after_parsing)."""
    address, off = codec.dec_string(buf, 0)
    tags, off = codec.dec_string(buf, off)
    if not tags.startswith(","):
        raise ValueError(f"malformed type tag string {tags!r}")
    args = []
    for tag in tags[1:]:
        decoder = _DECODERS.get(tag)
        if decoder is None:
            raise ValueError(f"unsupported OSC type tag {tag!r}")
        value, off = decoder(buf, off)
        args.append(value)
    return OscMessage(address, args), off


def _decode_bundle(buf: bytes) -> tuple:
    """Decode a bundle. Returns (bundle, offset_after_parsing).

    Strictly verifies that each element consumes exactly its declared size.

    Known limitation: consumption checks cannot validate nested bundles. A bundle
    element always consumes exactly the bytes it's handed, making it impossible to
    distinguish between legitimate nesting and an inflated size that relocates a
    following sibling into the bundle. This is inherent to OSC's length-prefixed
    framing and was a deliberate design trade-off prioritizing robustness over
    complete corruption detection.
    """
    off = len(BUNDLE_PREFIX)
    if len(buf) < off + 8:
        raise ValueError(f"truncated bundle timetag: need 8 bytes, got {len(buf) - off}")
    timetag = int.from_bytes(buf[off : off + 8], "big")
    off += 8
    elements = []
    while off < len(buf):
        size, off = codec.dec_int32(buf, off)
        if size < 0:
            raise ValueError(f"bundle element size cannot be negative: {size}")
        if off + size > len(buf):
            raise ValueError(
                f"bundle element size {size} at offset {off - 4} overruns buffer of length {len(buf)}"
            )
        element_buf = buf[off : off + size]
        element, element_end = _decode_internal(element_buf)
        if element_end != size:
            raise ValueError(
                f"bundle element size {size} declared but only {element_end} bytes consumed"
            )
        elements.append(element)
        off += size
    return OscBundle(timetag, elements), off
