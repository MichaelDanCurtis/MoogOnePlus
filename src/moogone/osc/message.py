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
    """Decode a packet into an OscMessage or OscBundle."""
    if buf.startswith(BUNDLE_PREFIX):
        return _decode_bundle(buf)
    return _decode_message(buf)


def _decode_message(buf: bytes) -> OscMessage:
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
    return OscMessage(address, args)


def _decode_bundle(buf: bytes) -> OscBundle:
    off = len(BUNDLE_PREFIX)
    timetag = int.from_bytes(buf[off : off + 8], "big")
    off += 8
    elements = []
    while off < len(buf):
        size, off = codec.dec_int32(buf, off)
        elements.append(decode(buf[off : off + size]))
        off += size
    return OscBundle(timetag, elements)
