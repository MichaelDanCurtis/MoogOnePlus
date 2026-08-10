"""OSC 1.0 primitive encoding and decoding.

All values are big-endian and padded to 4-byte boundaries. Every decoder
returns (value, new_offset) so callers can walk a buffer without tracking
widths themselves.
"""

import struct


def pad_to_4(n: int) -> int:
    """Round n up to the next multiple of 4."""
    return (n + 3) & ~3


def enc_string(s: str) -> bytes:
    raw = s.encode("ascii") + b"\x00"
    return raw.ljust(pad_to_4(len(raw)), b"\x00")


def dec_string(buf: bytes, off: int) -> tuple[str, int]:
    end = buf.find(b"\x00", off)
    if end == -1:
        raise ValueError(f"unterminated OSC string at offset {off}")
    value = buf[off:end].decode("ascii")
    return value, off + pad_to_4(end - off + 1)


def _dec_fixed(buf: bytes, off: int, width: int, fmt: str):
    if len(buf) < off + width:
        raise ValueError(f"buffer too short for {fmt} at offset {off}")
    (value,) = struct.unpack_from(fmt, buf, off)
    return value, off + width


def enc_int32(v: int) -> bytes:
    return struct.pack(">i", v)


def dec_int32(buf: bytes, off: int) -> tuple[int, int]:
    return _dec_fixed(buf, off, 4, ">i")


def enc_float32(v: float) -> bytes:
    return struct.pack(">f", v)


def dec_float32(buf: bytes, off: int) -> tuple[float, int]:
    return _dec_fixed(buf, off, 4, ">f")


def enc_float64(v: float) -> bytes:
    return struct.pack(">d", v)


def dec_float64(buf: bytes, off: int) -> tuple[float, int]:
    return _dec_fixed(buf, off, 8, ">d")


def enc_blob(b: bytes) -> bytes:
    return enc_int32(len(b)) + bytes(b).ljust(pad_to_4(len(b)), b"\x00")


def dec_blob(buf: bytes, off: int) -> tuple[bytes, int]:
    size, off = dec_int32(buf, off)
    if len(buf) < off + size:
        raise ValueError(f"blob claims {size} bytes but buffer is short")
    return buf[off : off + size], off + pad_to_4(size)
