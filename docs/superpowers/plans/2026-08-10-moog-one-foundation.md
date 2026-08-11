# Moog One Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested OSC/SuperCollider toolkit, a mock scsynth, a recon script, and an audio measurement rig — all without access to the Moog One, which is unavailable until September 2026.

**Architecture:** A zero-dependency OSC 1.0 codec underpins a SuperCollider server client, which talks through a pluggable transport (UDP primary, socat-bridged SSH tunnel secondary). A mock scsynth answers enough of the protocol that every layer above it reaches green before hardware exists. The measurement rig is validated against synthetic audio with known noise floors, so September is spent reading numbers rather than debugging parsers.

**Tech Stack:** Python 3.11+, uv, pytest, numpy, soundfile. POSIX shell for the on-device recon script. SuperCollider `.scd` for the test harness scaffold.

## Global Constraints

- Python 3.11 or newer. Dependencies managed with `uv`.
- `moogone.osc`, `moogone.sc`, and `moogone.transport` use **stdlib only** (`struct`, `socket`, `select`). No third-party imports in those packages.
- `numpy` and `soundfile` are permitted **only** under `moogone.analysis`.
- All OSC encoding is **big-endian**, padded to 4-byte boundaries per OSC 1.0.
- The recon script is **POSIX sh** — busybox-compatible, no bashisms, no assumed interpreter beyond `/bin/sh`.
- Recon is **read-only by default**. Anything that transmits to the device sits behind an explicit `--active` flag.
- **No task may require Moog One hardware.** Every test runs against the mock or synthetic fixtures.
- No firmware modification. Nothing writes to `/etc`, replaces system binaries, or touches signed material.
- Errors surface as raised exceptions. A silently swallowed `/fail` during recon is worse than a crash.

---

### Task 1: Project scaffold and OSC primitive codec

**Files:**
- Create: `pyproject.toml`
- Create: `src/moogone/__init__.py`
- Create: `src/moogone/osc/__init__.py`
- Create: `src/moogone/osc/codec.py`
- Test: `tests/test_osc_codec.py`

**Interfaces:**
- Consumes: nothing
- Produces: `pad_to_4(n: int) -> int`, `enc_string(s: str) -> bytes`, `dec_string(buf: bytes, off: int) -> tuple[str, int]`, `enc_int32(v: int) -> bytes`, `dec_int32(buf, off) -> tuple[int, int]`, `enc_float32(v: float) -> bytes`, `dec_float32(buf, off) -> tuple[float, int]`, `enc_float64(v: float) -> bytes`, `dec_float64(buf, off) -> tuple[float, int]`, `enc_blob(b: bytes) -> bytes`, `dec_blob(buf, off) -> tuple[bytes, int]`. Every decoder returns `(value, new_offset)`.

- [ ] **Step 1: Create the project scaffold**

```toml
# pyproject.toml
[project]
name = "moogone"
version = "0.1.0"
description = "OSC tooling for the Moog One's SuperCollider audio engine"
requires-python = ">=3.11"
dependencies = []

[project.optional-dependencies]
analysis = ["numpy>=1.26", "soundfile>=0.12"]
dev = ["pytest>=8.0", "ruff>=0.6"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/moogone"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
```

```bash
mkdir -p src/moogone/osc tests
touch src/moogone/__init__.py src/moogone/osc/__init__.py
uv sync --extra dev --extra analysis
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_osc_codec.py
import pytest
from moogone.osc import codec


def test_pad_to_4_rounds_up_to_multiple_of_four():
    assert codec.pad_to_4(0) == 0
    assert codec.pad_to_4(1) == 4
    assert codec.pad_to_4(4) == 4
    assert codec.pad_to_4(5) == 8


def test_string_encodes_null_terminated_and_padded():
    # "abc" is 3 chars + 1 null = 4, already aligned
    assert codec.enc_string("abc") == b"abc\x00"
    # "test" is 4 chars + 1 null = 5, pads to 8
    assert codec.enc_string("test") == b"test\x00\x00\x00\x00"
    # empty string is just a null, padded to 4
    assert codec.enc_string("") == b"\x00\x00\x00\x00"


def test_string_round_trips_and_reports_offset():
    buf = codec.enc_string("test") + b"TAIL"
    value, off = codec.dec_string(buf, 0)
    assert value == "test"
    assert off == 8
    assert buf[off:] == b"TAIL"


def test_int32_is_big_endian_signed():
    assert codec.enc_int32(1) == b"\x00\x00\x00\x01"
    assert codec.enc_int32(-1) == b"\xff\xff\xff\xff"
    assert codec.dec_int32(b"\x00\x00\x00\x2a", 0) == (42, 4)


def test_float32_round_trips():
    encoded = codec.enc_float32(1.0)
    assert encoded == b"\x3f\x80\x00\x00"
    value, off = codec.dec_float32(encoded, 0)
    assert value == pytest.approx(1.0)
    assert off == 4


def test_float64_round_trips_with_eight_byte_width():
    encoded = codec.enc_float64(44100.0)
    assert len(encoded) == 8
    value, off = codec.dec_float64(encoded, 0)
    assert value == pytest.approx(44100.0)
    assert off == 8


def test_blob_is_size_prefixed_and_padded():
    # 3 bytes of payload pads to 4
    assert codec.enc_blob(b"\x01\x02\x03") == b"\x00\x00\x00\x03\x01\x02\x03\x00"
    value, off = codec.dec_blob(b"\x00\x00\x00\x03\x01\x02\x03\x00", 0)
    assert value == b"\x01\x02\x03"
    assert off == 8


def test_truncated_buffer_raises():
    with pytest.raises(ValueError):
        codec.dec_int32(b"\x00\x00", 0)
    with pytest.raises(ValueError):
        codec.dec_string(b"no-null-here", 0)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_osc_codec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.osc.codec'`

- [ ] **Step 4: Write the implementation**

```python
# src/moogone/osc/codec.py
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_osc_codec.py -v`
Expected: PASS — 8 tests

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/moogone tests/test_osc_codec.py
git commit -m "feat: OSC 1.0 primitive codec with project scaffold"
```

---

### Task 2: OSC message and bundle codec

**Files:**
- Create: `src/moogone/osc/message.py`
- Modify: `src/moogone/osc/__init__.py`
- Test: `tests/test_osc_message.py`

**Interfaces:**
- Consumes: everything from `moogone.osc.codec`
- Produces: `OscMessage(address: str, args: list)` with `.encode() -> bytes`; `OscBundle(timetag: int, elements: list)` with `.encode() -> bytes`; `decode(buf: bytes) -> OscMessage | OscBundle`. Type inference on encode: `int` → `i`, `float` → `f`, `str` → `s`, `bytes` → `b`. `Float64(value)` wrapper forces `d`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_osc_message.py
import pytest
from moogone.osc.message import Float64, OscBundle, OscMessage, decode


def test_message_with_no_args_encodes_address_and_empty_typetag():
    encoded = OscMessage("/status", []).encode()
    assert encoded == b"/status\x00" + b",\x00\x00\x00"


def test_message_infers_types_from_python_values():
    encoded = OscMessage("/n_set", [1000, "amp", 0.5]).encode()
    decoded = decode(encoded)
    assert decoded.address == "/n_set"
    assert decoded.args[0] == 1000
    assert decoded.args[1] == "amp"
    assert decoded.args[2] == pytest.approx(0.5)


def test_float64_wrapper_forces_double_typetag():
    encoded = OscMessage("/x", [Float64(44100.0)]).encode()
    # typetag string is ",d" padded to 4
    assert b",d\x00\x00" in encoded
    decoded = decode(encoded)
    assert decoded.args[0] == pytest.approx(44100.0)


def test_blob_arg_round_trips():
    decoded = decode(OscMessage("/d_recv", [b"\x01\x02\x03"]).encode())
    assert decoded.args[0] == b"\x01\x02\x03"


def test_bundle_round_trips_with_nested_messages():
    bundle = OscBundle(1, [OscMessage("/a", [1]), OscMessage("/b", [2])])
    decoded = decode(bundle.encode())
    assert isinstance(decoded, OscBundle)
    assert decoded.timetag == 1
    assert [e.address for e in decoded.elements] == ["/a", "/b"]
    assert decoded.elements[1].args == [2]


def test_unknown_typetag_raises():
    # ",Q" is not a type tag we support
    bad = b"/x\x00\x00" + b",Q\x00\x00"
    with pytest.raises(ValueError, match="unsupported OSC type tag"):
        decode(bad)


def test_unencodable_arg_type_raises():
    with pytest.raises(TypeError, match="cannot encode"):
        OscMessage("/x", [{"not": "encodable"}]).encode()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_osc_message.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.osc.message'`

- [ ] **Step 3: Write the implementation**

```python
# src/moogone/osc/message.py
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
```

```python
# src/moogone/osc/__init__.py
from .message import Float64, OscBundle, OscMessage, decode

__all__ = ["Float64", "OscBundle", "OscMessage", "decode"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 15 tests total

- [ ] **Step 5: Commit**

```bash
git add src/moogone/osc tests/test_osc_message.py
git commit -m "feat: OSC message and bundle codec"
```

---

### Task 3: Transport interface and UDP transport

**Files:**
- Create: `src/moogone/transport/__init__.py`
- Create: `src/moogone/transport/base.py`
- Create: `src/moogone/transport/udp.py`
- Test: `tests/test_transport_udp.py`

**Interfaces:**
- Consumes: nothing
- Produces: abstract `Transport` with `send(data: bytes) -> None`, `recv(timeout: float) -> bytes | None`, `close() -> None`, and context-manager support. `UdpTransport(host: str, port: int, bind_port: int = 0)` implements it. `recv` returns `None` on timeout rather than raising, because polling for an absent reply is normal.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transport_udp.py
import socket

from moogone.transport.udp import UdpTransport


def _echo_socket() -> tuple[socket.socket, int]:
    """A UDP socket bound to an ephemeral port, for the transport to talk to."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    return sock, sock.getsockname()[1]


def test_send_reaches_the_target():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            t.send(b"hello")
            peer.settimeout(1.0)
            data, _ = peer.recvfrom(4096)
            assert data == b"hello"
    finally:
        peer.close()


def test_recv_returns_reply():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            t.send(b"ping")
            peer.settimeout(1.0)
            _, addr = peer.recvfrom(4096)
            peer.sendto(b"pong", addr)
            assert t.recv(timeout=1.0) == b"pong"
    finally:
        peer.close()


def test_recv_returns_none_on_timeout():
    peer, port = _echo_socket()
    try:
        with UdpTransport("127.0.0.1", port) as t:
            assert t.recv(timeout=0.05) is None
    finally:
        peer.close()


def test_close_is_idempotent():
    _, port = _echo_socket()
    t = UdpTransport("127.0.0.1", port)
    t.close()
    t.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transport_udp.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.transport'`

- [ ] **Step 3: Write the implementation**

```python
# src/moogone/transport/base.py
"""Transport abstraction for OSC packets."""

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, data: bytes) -> None:
        """Send one packet."""

    @abstractmethod
    def recv(self, timeout: float) -> bytes | None:
        """Receive one packet, or None if nothing arrives within timeout."""

    @abstractmethod
    def close(self) -> None:
        """Release resources. Must be safe to call more than once."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
```

```python
# src/moogone/transport/udp.py
"""Direct UDP transport.

This is the primary path: used when running on the Moog One itself, talking
to las-sc on localhost. No network hops, no tunnel.
"""

import select
import socket

from .base import Transport

MAX_PACKET = 65536


class UdpTransport(Transport):
    def __init__(self, host: str, port: int, bind_port: int = 0):
        self.host = host
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", bind_port))
        self._closed = False

    @property
    def local_port(self) -> int:
        return self._sock.getsockname()[1]

    def send(self, data: bytes) -> None:
        self._sock.sendto(data, (self.host, self.port))

    def recv(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return None
        data, _ = self._sock.recvfrom(MAX_PACKET)
        return data

    def close(self) -> None:
        if not self._closed:
            self._sock.close()
            self._closed = True
```

```python
# src/moogone/transport/__init__.py
from .base import Transport
from .udp import UdpTransport

__all__ = ["Transport", "UdpTransport"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 19 tests total

- [ ] **Step 5: Commit**

```bash
git add src/moogone/transport tests/test_transport_udp.py
git commit -m "feat: transport interface with UDP implementation"
```

---

### Task 4: Mock scsynth and the first client round trip

**Files:**
- Create: `src/moogone/mock/__init__.py`
- Create: `src/moogone/mock/server.py`
- Create: `src/moogone/sc/__init__.py`
- Create: `src/moogone/sc/client.py`
- Test: `tests/test_mock_status.py`
- Test: `tests/conftest.py`

**Interfaces:**
- Consumes: `OscMessage`, `decode`, `UdpTransport`
- Produces: `MockScsynth(port: int = 0)` with `.start()`, `.stop()`, `.port` (actual bound port), `.received: list[OscMessage]`, and context-manager support. `ScClient(transport: Transport)` with `.send(address, *args)`, `.request(address, *args, reply: str, timeout: float) -> OscMessage`, and `.status() -> ServerStatus`. `ServerStatus` is a dataclass with `num_ugens`, `num_synths`, `num_groups`, `num_synthdefs`, `avg_cpu`, `peak_cpu`, `sample_rate`, `actual_sample_rate`.

**Why this task matters:** this is the first end-to-end round trip, and `/status` is the very first message the real hardware will ever receive. If `las-sc` is a trimmed SuperCollider, this is where we find out.

- [ ] **Step 1: Write the failing tests**

```python
# tests/conftest.py
import pytest

from moogone.mock.server import MockScsynth
from moogone.sc.client import ScClient
from moogone.transport.udp import UdpTransport


@pytest.fixture
def mock_server():
    server = MockScsynth()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def client(mock_server):
    transport = UdpTransport("127.0.0.1", mock_server.port)
    yield ScClient(transport)
    transport.close()
```

```python
# tests/test_mock_status.py
import pytest

from moogone.osc import OscMessage


def test_status_returns_parsed_server_state(client):
    status = client.status()
    assert status.num_synths == 0
    assert status.sample_rate == pytest.approx(48000.0)
    assert status.actual_sample_rate == pytest.approx(48000.0, rel=1e-3)


def test_server_records_what_it_received(client, mock_server):
    client.status()
    assert [m.address for m in mock_server.received] == ["/status"]


def test_unknown_command_raises_sc_error(client):
    from moogone.sc.client import ScError

    with pytest.raises(ScError, match="/nonsense"):
        client.request("/nonsense", reply="/never", timeout=1.0)


def test_request_times_out_when_no_reply_arrives(client, mock_server):
    from moogone.sc.client import ScTimeout

    mock_server.silent = True
    with pytest.raises(ScTimeout):
        client.request("/status", reply="/status.reply", timeout=0.2)


def test_send_is_fire_and_forget(client, mock_server):
    client.send("/n_free", 1000)
    # give the server a moment to log it
    mock_server.wait_for_message("/n_free", timeout=1.0)
    assert mock_server.received[-1] == OscMessage("/n_free", [1000])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mock_status.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.mock'`

- [ ] **Step 3: Write the mock server**

```python
# src/moogone/mock/server.py
"""A mock scsynth, answering enough of the SuperCollider server protocol
to develop against without hardware.

This is the linchpin of the pre-hardware plan: it makes every layer above
it testable, and it encodes our assumptions about las-sc explicitly. When
September's real server behaves differently, it shows up as a failing test
rather than a mystery.
"""

import socket
import threading
import time

from ..osc import Float64, OscMessage, decode


class MockScsynth:
    def __init__(self, port: int = 0):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", port))
        self._sock.settimeout(0.1)
        self.port = self._sock.getsockname()[1]
        self.received: list[OscMessage] = []
        self.silent = False
        self._thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._sock.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

    def wait_for_message(self, address: str, timeout: float) -> OscMessage:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                for message in self.received:
                    if message.address == address:
                        return message
            time.sleep(0.01)
        raise AssertionError(f"mock server never received {address}")

    def _serve(self) -> None:
        while self._running:
            try:
                data, addr = self._sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                return
            message = decode(data)
            with self._lock:
                self.received.append(message)
            if self.silent:
                continue
            reply = self.handle(message)
            if reply is not None:
                self._sock.sendto(reply.encode(), addr)

    def handle(self, message: OscMessage) -> OscMessage | None:
        """Dispatch one message. Subclasses and later tasks extend this."""
        if message.address == "/status":
            return OscMessage(
                "/status.reply",
                [1, 0, 0, 1, 0, 0.02, 0.05, Float64(48000.0), Float64(48000.03)],
            )
        if message.address in _NO_REPLY:
            return None
        return OscMessage("/fail", [message.address, "Command not found"])


# Commands the real server accepts without replying.
_NO_REPLY = {"/n_free", "/n_set", "/dumpOSC"}
```

- [ ] **Step 4: Write the client**

```python
# src/moogone/sc/client.py
"""SuperCollider server client.

Errors are raised, never swallowed. A silently ignored /fail during recon
would be worse than a crash — it would look like success.
"""

from dataclasses import dataclass

from ..osc import OscBundle, OscMessage, decode
from ..transport.base import Transport


class ScError(RuntimeError):
    """The server replied /fail."""


class ScTimeout(TimeoutError):
    """The expected reply did not arrive in time."""


@dataclass
class ServerStatus:
    num_ugens: int
    num_synths: int
    num_groups: int
    num_synthdefs: int
    avg_cpu: float
    peak_cpu: float
    sample_rate: float
    actual_sample_rate: float


class ScClient:
    def __init__(self, transport: Transport):
        self.transport = transport

    def send(self, address: str, *args) -> None:
        """Fire and forget."""
        self.transport.send(OscMessage(address, list(args)).encode())

    def request(self, address: str, *args, reply: str, timeout: float = 2.0) -> OscMessage:
        """Send a command and wait for a specific reply address.

        Raises ScError on /fail, ScTimeout if the reply never arrives.
        Unrelated messages arriving in the meantime are discarded.
        """
        self.send(address, *args)
        return self._await_reply(reply, timeout)

    def _await_reply(self, reply: str, timeout: float) -> OscMessage:
        import time

        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScTimeout(f"no {reply} within {timeout}s")
            data = self.transport.recv(timeout=remaining)
            if data is None:
                continue
            message = decode(data)
            if isinstance(message, OscBundle):
                continue
            if message.address == "/fail":
                raise ScError(f"server rejected {message.args[0]}: {message.args[1]}")
            if message.address == reply:
                return message

    def status(self) -> ServerStatus:
        message = self.request("/status", reply="/status.reply")
        _, ugens, synths, groups, defs, avg, peak, sr, actual_sr = message.args
        return ServerStatus(ugens, synths, groups, defs, avg, peak, sr, actual_sr)
```

```python
# src/moogone/sc/__init__.py
from .client import ScClient, ScError, ScTimeout, ServerStatus

__all__ = ["ScClient", "ScError", "ScTimeout", "ServerStatus"]
```

```python
# src/moogone/mock/__init__.py
from .server import MockScsynth

__all__ = ["MockScsynth"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 24 tests total

- [ ] **Step 6: Commit**

```bash
git add src/moogone/mock src/moogone/sc tests/conftest.py tests/test_mock_status.py
git commit -m "feat: mock scsynth and SC client with /status round trip"
```

---

### Task 5: Async completion — /sync, /done, /notify

**Files:**
- Modify: `src/moogone/sc/client.py`
- Modify: `src/moogone/mock/server.py`
- Test: `tests/test_sc_async.py`

**Interfaces:**
- Consumes: `ScClient`, `MockScsynth`
- Produces: `ScClient.sync(sync_id: int = 1, timeout: float = 2.0) -> None` and `ScClient.notify(enable: bool = True, timeout: float = 2.0) -> None`. Mock gains `/sync` → `/synced` and `/notify` → `/done` handling.

**Why:** `/d_recv` in Task 8 is asynchronous. Without a barrier there is no way to know a SynthDef finished loading before using it, and the failure mode is a race that looks like an intermittent bug.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sc_async.py
import pytest

from moogone.sc.client import ScTimeout


def test_sync_completes(client):
    client.sync(sync_id=42)  # returns without raising


def test_sync_matches_its_own_id(client, mock_server):
    # The mock echoes the id back; a mismatched id must not satisfy the wait.
    mock_server.sync_id_offset = 1
    with pytest.raises(ScTimeout):
        client.sync(sync_id=7, timeout=0.3)


def test_notify_registers(client, mock_server):
    client.notify(True)
    assert mock_server.notified is True


def test_notify_can_be_disabled(client, mock_server):
    client.notify(True)
    client.notify(False)
    assert mock_server.notified is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sc_async.py -v`
Expected: FAIL — `AttributeError: 'ScClient' object has no attribute 'sync'`

- [ ] **Step 3: Extend the mock**

In `src/moogone/mock/server.py`, add to `__init__`:

```python
        self.notified = False
        self.sync_id_offset = 0
```

And add these branches to `handle`, before the `_NO_REPLY` check:

```python
        if message.address == "/sync":
            return OscMessage("/synced", [message.args[0] + self.sync_id_offset])
        if message.address == "/notify":
            self.notified = bool(message.args[0])
            return OscMessage("/done", ["/notify", 0])
```

- [ ] **Step 4: Extend the client**

Add to `ScClient` in `src/moogone/sc/client.py`:

```python
    def sync(self, sync_id: int = 1, timeout: float = 2.0) -> None:
        """Block until the server has processed all prior async commands.

        The server echoes sync_id back; a reply carrying a different id
        belongs to someone else's sync and is ignored.
        """
        import time

        self.send("/sync", sync_id)
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScTimeout(f"no /synced for id {sync_id} within {timeout}s")
            message = self._await_reply("/synced", remaining)
            if message.args and message.args[0] == sync_id:
                return

    def notify(self, enable: bool = True, timeout: float = 2.0) -> None:
        """Subscribe to (or unsubscribe from) node lifecycle notifications."""
        self.request("/notify", int(enable), reply="/done", timeout=timeout)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 28 tests total

- [ ] **Step 6: Commit**

```bash
git add src/moogone/sc/client.py src/moogone/mock/server.py tests/test_sc_async.py
git commit -m "feat: /sync barrier and /notify registration"
```

---

### Task 6: Node tree query — /g_queryTree

**Files:**
- Create: `src/moogone/sc/tree.py`
- Create: `src/moogone/mock/tree.py`
- Modify: `src/moogone/sc/client.py`
- Modify: `src/moogone/mock/server.py`
- Test: `tests/test_sc_tree.py`

**Interfaces:**
- Consumes: `ScClient`, `MockScsynth`
- Produces: `SynthNode(node_id: int, defname: str, controls: dict[str, float | str])` and `GroupNode(node_id: int, children: list)`. `parse_query_tree(args: list) -> GroupNode`. `ScClient.query_tree(group_id: int = 0, with_controls: bool = True) -> GroupNode`. `GroupNode.walk() -> Iterator[SynthNode | GroupNode]` yields every node depth-first. `MockScsynth.node_tree` holds a `GroupNode` the mock serialises on request.

**Why:** this is the single most valuable recon call. It enumerates the live FX chain and every control name on it — the raw material for both downstream projects. The reply format is a flattened depth-first tree, which is the fiddliest parse in the codebase and deserves its own task.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sc_tree.py
import pytest

from moogone.sc.tree import GroupNode, SynthNode, parse_query_tree


def test_parses_flat_reply_with_one_synth():
    # flag=1, root group 0, 1 child: synth 1000 "reverb" with 2 controls
    args = [1, 0, 1, 1000, -1, "reverb", 2, "mix", 0.3, "damp", 0.5]
    root = parse_query_tree(args)
    assert root.node_id == 0
    assert len(root.children) == 1
    synth = root.children[0]
    assert isinstance(synth, SynthNode)
    assert synth.defname == "reverb"
    assert synth.controls == {"mix": pytest.approx(0.3), "damp": pytest.approx(0.5)}


def test_parses_nested_groups():
    # root 0 has 1 child: group 1 with 1 child: synth 1000 "delay", 0 controls
    args = [1, 0, 1, 1, 1, 1000, -1, "delay", 0]
    root = parse_query_tree(args)
    group = root.children[0]
    assert isinstance(group, GroupNode)
    assert group.node_id == 1
    assert group.children[0].defname == "delay"


def test_parses_reply_without_controls():
    # flag=0 means no control data follows the defname
    args = [0, 0, 1, 1000, -1, "reverb"]
    root = parse_query_tree(args)
    assert root.children[0].controls == {}


def test_control_mapped_to_a_bus_keeps_its_string_value():
    args = [1, 0, 1, 1000, -1, "reverb", 1, "in", "a0"]
    root = parse_query_tree(args)
    assert root.children[0].controls["in"] == "a0"


def test_walk_yields_every_node_depth_first():
    args = [1, 0, 2, 1, 1, 1000, -1, "delay", 0, 1001, -1, "reverb", 0]
    root = parse_query_tree(args)
    ids = [n.node_id for n in root.walk()]
    assert ids == [0, 1, 1000, 1001]


def test_client_queries_the_mock_tree(client):
    root = client.query_tree()
    names = [n.defname for n in root.walk() if isinstance(n, SynthNode)]
    assert "moog_fx_reverb" in names


def test_mock_tree_exposes_control_names(client):
    root = client.query_tree()
    reverb = next(n for n in root.walk() if getattr(n, "defname", None) == "moog_fx_reverb")
    assert "in_trim" in reverb.controls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sc_tree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.sc.tree'`

- [ ] **Step 3: Write the tree model and parser**

```python
# src/moogone/sc/tree.py
"""Node tree model and /g_queryTree.reply parser.

The reply is a flattened depth-first walk. Each entry is:
    node_id, num_children
and when num_children is -1 the node is a synth, which is followed by:
    defname[, num_controls, (name, value) * num_controls]
"""

from collections.abc import Iterator
from dataclasses import dataclass, field


@dataclass
class SynthNode:
    node_id: int
    defname: str
    controls: dict = field(default_factory=dict)

    def walk(self) -> Iterator["SynthNode"]:
        yield self


@dataclass
class GroupNode:
    node_id: int
    children: list = field(default_factory=list)

    def walk(self) -> Iterator["SynthNode | GroupNode"]:
        yield self
        for child in self.children:
            yield from child.walk()


def parse_query_tree(args: list) -> GroupNode:
    """Parse the argument list of a /g_queryTree.reply into a tree."""
    with_controls = bool(args[0])
    pos = 1

    def read_node():
        nonlocal pos
        node_id = args[pos]
        num_children = args[pos + 1]
        pos += 2
        if num_children == -1:
            defname = args[pos]
            pos += 1
            controls = {}
            if with_controls:
                num_controls = args[pos]
                pos += 1
                for _ in range(num_controls):
                    controls[args[pos]] = args[pos + 1]
                    pos += 2
            return SynthNode(node_id, defname, controls)
        node = GroupNode(node_id)
        for _ in range(num_children):
            node.children.append(read_node())
        return node

    return read_node()
```

- [ ] **Step 4: Give the mock a plausible FX tree**

```python
# src/moogone/mock/tree.py
"""A synthetic node tree shaped like a plausible Moog One FX chain.

This is a guess, not a recording. Its purpose is to exercise the parser and
the client, not to predict what las-sc actually reports. September replaces
it with a real capture.
"""

from ..sc.tree import GroupNode, SynthNode


def default_tree() -> GroupNode:
    return GroupNode(
        0,
        [
            GroupNode(
                1,
                [
                    SynthNode(
                        1000,
                        "moog_fx_delay",
                        {"in_trim": 1.0, "time": 0.35, "feedback": 0.4, "mix": 0.25, "out_gain": 1.0},
                    ),
                    SynthNode(
                        1001,
                        "moog_fx_reverb",
                        {"in_trim": 1.0, "size": 0.6, "damp": 0.5, "mix": 0.3, "out_gain": 1.0},
                    ),
                ],
            )
        ],
    )


def serialise(root: GroupNode, with_controls: bool) -> list:
    """Flatten a tree into /g_queryTree.reply argument order."""
    args: list = [1 if with_controls else 0]

    def emit(node):
        if isinstance(node, SynthNode):
            args.extend([node.node_id, -1, node.defname])
            if with_controls:
                args.append(len(node.controls))
                for name, value in node.controls.items():
                    args.extend([name, value])
        else:
            args.extend([node.node_id, len(node.children)])
            for child in node.children:
                emit(child)

    emit(root)
    return args
```

- [ ] **Step 5: Wire the mock and client**

In `src/moogone/mock/server.py`, add to `__init__`:

```python
        from .tree import default_tree

        self.node_tree = default_tree()
```

And add to `handle`:

```python
        if message.address == "/g_queryTree":
            from .tree import serialise

            with_controls = bool(message.args[1]) if len(message.args) > 1 else False
            return OscMessage("/g_queryTree.reply", serialise(self.node_tree, with_controls))
```

Add to `ScClient` in `src/moogone/sc/client.py`:

```python
    def query_tree(self, group_id: int = 0, with_controls: bool = True, timeout: float = 2.0):
        """Enumerate the live node graph below group_id.

        With with_controls=True the reply includes every control name and
        value, which is what makes this the most useful single recon call.
        """
        from .tree import parse_query_tree

        message = self.request(
            "/g_queryTree",
            group_id,
            int(with_controls),
            reply="/g_queryTree.reply",
            timeout=timeout,
        )
        return parse_query_tree(message.args)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 35 tests total

- [ ] **Step 7: Commit**

```bash
git add src/moogone/sc/tree.py src/moogone/mock/tree.py src/moogone/sc/client.py src/moogone/mock/server.py tests/test_sc_tree.py
git commit -m "feat: /g_queryTree parsing with synthetic FX tree in mock"
```

---

### Task 7: Control and observation — /n_set, /n_query, /dumpOSC

**Files:**
- Modify: `src/moogone/sc/client.py`
- Modify: `src/moogone/mock/server.py`
- Test: `tests/test_sc_control.py`

**Interfaces:**
- Consumes: `ScClient`, `MockScsynth`, `SynthNode`
- Produces: `ScClient.n_set(node_id: int, **controls) -> None`, `ScClient.n_query(node_id: int, timeout: float = 2.0) -> NodeInfo`, `ScClient.dump_osc(mode: int) -> None`. `NodeInfo` dataclass with `node_id`, `parent_id`, `prev_id`, `next_id`, `is_group`. Mock applies `/n_set` to its `node_tree` so changes are observable by re-querying.

**Why:** `/n_set` is the FX project's fix mechanism and the pressure project's per-voice write. `/dumpOSC` is how September's recon captures Moog's real namespace by observation.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sc_control.py
import pytest

from moogone.sc.tree import SynthNode


def _reverb(root):
    return next(n for n in root.walk() if getattr(n, "defname", None) == "moog_fx_reverb")


def test_n_set_changes_a_control(client):
    node = _reverb(client.query_tree())
    client.n_set(node.node_id, in_trim=2.5)
    assert _reverb(client.query_tree()).controls["in_trim"] == pytest.approx(2.5)


def test_n_set_accepts_multiple_controls(client):
    node = _reverb(client.query_tree())
    client.n_set(node.node_id, in_trim=0.5, mix=0.9)
    controls = _reverb(client.query_tree()).controls
    assert controls["in_trim"] == pytest.approx(0.5)
    assert controls["mix"] == pytest.approx(0.9)


def test_n_set_on_unknown_node_is_silently_ignored_by_server(client, mock_server):
    # Real scsynth logs and moves on; we assert we don't crash and it's recorded.
    client.n_set(999999, in_trim=1.0)
    mock_server.wait_for_message("/n_set", timeout=1.0)


def test_n_query_returns_node_info(client):
    node = _reverb(client.query_tree())
    info = client.n_query(node.node_id)
    assert info.node_id == node.node_id
    assert info.is_group is False


def test_dump_osc_sets_server_mode(client, mock_server):
    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)
    assert mock_server.dump_mode == 1


def test_dump_osc_log_captures_subsequent_messages(client, mock_server):
    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)
    client.send("/n_free", 1234)
    mock_server.wait_for_message("/n_free", timeout=1.0)
    assert any(m.address == "/n_free" for m in mock_server.dump_log)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sc_control.py -v`
Expected: FAIL — `AttributeError: 'ScClient' object has no attribute 'n_set'`

- [ ] **Step 3: Extend the mock**

In `src/moogone/mock/server.py`, add to `__init__`:

```python
        self.dump_mode = 0
        self.dump_log: list[OscMessage] = []
```

In `_serve`, immediately after appending to `self.received`:

```python
            if self.dump_mode and message.address != "/dumpOSC":
                self.dump_log.append(message)
```

Add to `handle`:

```python
        if message.address == "/dumpOSC":
            self.dump_mode = message.args[0]
            return None
        if message.address == "/n_set":
            self._apply_n_set(message.args)
            return None
        if message.address == "/n_query":
            node = self._find_node(message.args[0])
            if node is None:
                return OscMessage("/fail", ["/n_query", "Node not found"])
            is_group = not isinstance(node, SynthNode)
            return OscMessage("/n_info", [node.node_id, 1, -1, -1, int(is_group)])
```

And these helpers on the class:

```python
    def _find_node(self, node_id: int):
        for node in self.node_tree.walk():
            if node.node_id == node_id:
                return node
        return None

    def _apply_n_set(self, args: list) -> None:
        node = self._find_node(args[0])
        if not isinstance(node, SynthNode):
            return
        for i in range(1, len(args) - 1, 2):
            node.controls[args[i]] = args[i + 1]
```

Add the import at the top of the file:

```python
from ..sc.tree import SynthNode
```

- [ ] **Step 4: Extend the client**

Add to `ScClient`:

```python
    def n_set(self, node_id: int, **controls) -> None:
        """Set one or more controls on a live node. Fire and forget.

        scsynth does not acknowledge /n_set. To confirm a change took, query
        the node afterwards rather than assuming.
        """
        args: list = [node_id]
        for name, value in controls.items():
            args.extend([name, float(value)])
        self.send("/n_set", *args)

    def n_query(self, node_id: int, timeout: float = 2.0) -> "NodeInfo":
        message = self.request("/n_query", node_id, reply="/n_info", timeout=timeout)
        node, parent, prev, nxt, is_group = message.args[:5]
        return NodeInfo(node, parent, prev, nxt, bool(is_group))

    def dump_osc(self, mode: int) -> None:
        """0 = off, 1 = parsed, 2 = hex, 3 = both.

        Mode 1 makes the server log every message it receives, which is how
        recon captures Moog's own OSC namespace by observation.
        """
        if mode not in (0, 1, 2, 3):
            raise ValueError(f"dumpOSC mode must be 0-3, got {mode}")
        self.send("/dumpOSC", mode)
```

And this dataclass alongside `ServerStatus`:

```python
@dataclass
class NodeInfo:
    node_id: int
    parent_id: int
    prev_id: int
    next_id: int
    is_group: bool
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 41 tests total

- [ ] **Step 6: Commit**

```bash
git add src/moogone/sc/client.py src/moogone/mock/server.py tests/test_sc_control.py
git commit -m "feat: /n_set, /n_query and /dumpOSC"
```

---

### Task 8: SynthDef loading — /d_recv

**Files:**
- Modify: `src/moogone/sc/client.py`
- Modify: `src/moogone/mock/server.py`
- Test: `tests/test_sc_synthdef.py`

**Interfaces:**
- Consumes: `ScClient`, `MockScsynth`
- Produces: `ScClient.d_recv(synthdef: bytes, timeout: float = 5.0) -> None`, which blocks until `/done` and raises `ScError` on `/fail`. `MockScsynth.loaded_synthdefs: list[bytes]`.

**Why:** this is the FX project's escalation path — loading a corrected SynthDef at runtime. It is asynchronous, so it depends on Task 5's barrier work.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sc_synthdef.py
import pytest

from moogone.sc.client import ScError

# A real .scsyndef begins with the magic bytes "SCgf".
VALID_SYNTHDEF = b"SCgf\x00\x00\x00\x02" + b"\x00" * 32
INVALID_SYNTHDEF = b"NOPE" + b"\x00" * 32


def test_d_recv_loads_a_synthdef(client, mock_server):
    client.d_recv(VALID_SYNTHDEF)
    assert mock_server.loaded_synthdefs == [VALID_SYNTHDEF]


def test_d_recv_rejects_malformed_synthdef(client):
    with pytest.raises(ScError, match="/d_recv"):
        client.d_recv(INVALID_SYNTHDEF)


def test_d_recv_rejects_empty_payload_before_sending(client, mock_server):
    with pytest.raises(ValueError, match="empty"):
        client.d_recv(b"")
    assert mock_server.loaded_synthdefs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sc_synthdef.py -v`
Expected: FAIL — `AttributeError: 'ScClient' object has no attribute 'd_recv'`

- [ ] **Step 3: Extend the mock**

In `__init__`:

```python
        self.loaded_synthdefs: list[bytes] = []
```

In `handle`:

```python
        if message.address == "/d_recv":
            payload = message.args[0]
            if not payload.startswith(b"SCgf"):
                return OscMessage("/fail", ["/d_recv", "not a synthdef file"])
            self.loaded_synthdefs.append(payload)
            return OscMessage("/done", ["/d_recv"])
```

- [ ] **Step 4: Extend the client**

```python
    def d_recv(self, synthdef: bytes, timeout: float = 5.0) -> None:
        """Load a compiled SynthDef into the running server.

        This is runtime data, not firmware — nothing signed is touched and
        nothing survives a reboot unless deliberately arranged.
        """
        if not synthdef:
            raise ValueError("cannot send an empty synthdef")
        self.request("/d_recv", synthdef, reply="/done", timeout=timeout)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 44 tests total

- [ ] **Step 6: Commit**

```bash
git add src/moogone/sc/client.py src/moogone/mock/server.py tests/test_sc_synthdef.py
git commit -m "feat: /d_recv SynthDef loading"
```

---

### Task 9: Tunnel transport with socat bridge

**Files:**
- Create: `src/moogone/transport/tunnel.py`
- Modify: `src/moogone/transport/__init__.py`
- Test: `tests/test_transport_tunnel.py`

**Interfaces:**
- Consumes: `Transport`, `UdpTransport`
- Produces: `TunnelTransport(local_port: int)` implementing `Transport`. Module-level `build_ssh_command(host, local_port, remote_port, user="root") -> list[str]` and `build_remote_bridge_command(remote_port, bridge_port) -> str`, both pure functions returning the exact commands, so they are testable without SSH.

**Why this exists and why it is secondary:** `ssh -L` forwards **TCP**, while scsynth listens on **UDP**. A plain forward carries nothing at all. A working tunnel needs socat bridging UDP↔TCP at both ends. This is development convenience only — if the device lacks socat we run on-box and lose nothing that matters.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transport_tunnel.py
import pytest

from moogone.transport.tunnel import (
    TunnelTransport,
    build_remote_bridge_command,
    build_ssh_command,
)


def test_ssh_command_forwards_tcp_to_the_bridge_port():
    cmd = build_ssh_command("192.168.0.204", local_port=9300, remote_port=9301)
    assert cmd[0] == "ssh"
    assert "-L" in cmd
    assert "9300:127.0.0.1:9301" in cmd
    assert "root@192.168.0.204" in cmd


def test_ssh_command_accepts_a_non_root_user():
    cmd = build_ssh_command("host", local_port=1, remote_port=2, user="pi")
    assert "pi@host" in cmd


def test_remote_bridge_listens_tcp_and_forwards_udp():
    cmd = build_remote_bridge_command(remote_port=9300, bridge_port=9301)
    assert "socat" in cmd
    assert "TCP-LISTEN:9301" in cmd
    assert "UDP:127.0.0.1:9300" in cmd


def test_tunnel_transport_talks_to_a_local_tcp_listener():
    # The tunnel's local end is a TCP socket; stand one up and check framing.
    import socket
    import threading

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    received = []

    def serve():
        conn, _ = listener.accept()
        received.append(conn.recv(4096))
        conn.sendall(b"reply")
        conn.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    try:
        with TunnelTransport(port) as t:
            t.send(b"hello")
            assert t.recv(timeout=2.0) == b"reply"
        thread.join(timeout=2.0)
        assert received == [b"hello"]
    finally:
        listener.close()


def test_recv_returns_none_on_timeout():
    import socket

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        with TunnelTransport(port) as t:
            assert t.recv(timeout=0.05) is None
    finally:
        listener.close()


def test_connecting_to_a_dead_port_raises_with_guidance():
    with pytest.raises(ConnectionError, match="socat"):
        TunnelTransport(1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transport_tunnel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.transport.tunnel'`

- [ ] **Step 3: Write the implementation**

```python
# src/moogone/transport/tunnel.py
"""SSH-tunnelled transport, for development from off-box.

ssh -L forwards TCP. scsynth listens on UDP. A plain forward therefore
carries nothing, and this is the single easiest way to waste an afternoon
on this project. The working shape needs socat at both ends:

    Mac                          Moog One
    ---                          --------
    TunnelTransport  -- TCP -->  sshd -- TCP --> socat -- UDP --> las-sc
                                 (bridge_port)              (9300)

Set up, in two terminals:

    ssh root@<ip> 'socat TCP-LISTEN:9301,reuseaddr,fork UDP:127.0.0.1:9300'
    ssh -N -L 9300:127.0.0.1:9301 root@<ip>

If socat is absent from the device, do not fight this. Run on-box instead.
"""

import select
import socket

from .base import Transport


def build_ssh_command(host: str, local_port: int, remote_port: int, user: str = "root") -> list[str]:
    """The local SSH forward. remote_port is the bridge port, not scsynth's."""
    return ["ssh", "-N", "-L", f"{local_port}:127.0.0.1:{remote_port}", f"{user}@{host}"]


def build_remote_bridge_command(remote_port: int, bridge_port: int) -> str:
    """The socat bridge to run on the device. remote_port is scsynth's UDP port."""
    return f"socat TCP-LISTEN:{bridge_port},reuseaddr,fork UDP:127.0.0.1:{remote_port}"


class TunnelTransport(Transport):
    def __init__(self, local_port: int, host: str = "127.0.0.1"):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._closed = False
        try:
            self._sock.connect((host, local_port))
        except OSError as exc:
            self._sock.close()
            self._closed = True
            raise ConnectionError(
                f"could not reach {host}:{local_port}. Is the ssh -L forward up, "
                f"and is socat running on the device? See this module's docstring."
            ) from exc

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def recv(self, timeout: float) -> bytes | None:
        ready, _, _ = select.select([self._sock], [], [], timeout)
        if not ready:
            return None
        data = self._sock.recv(65536)
        return data or None

    def close(self) -> None:
        if not self._closed:
            self._sock.close()
            self._closed = True
```

```python
# src/moogone/transport/__init__.py
from .base import Transport
from .tunnel import TunnelTransport, build_remote_bridge_command, build_ssh_command
from .udp import UdpTransport

__all__ = [
    "Transport",
    "TunnelTransport",
    "UdpTransport",
    "build_remote_bridge_command",
    "build_ssh_command",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 50 tests total

- [ ] **Step 5: Commit**

```bash
git add src/moogone/transport tests/test_transport_tunnel.py
git commit -m "feat: SSH tunnel transport with socat UDP bridge"
```

---

### Task 10: WAV loading and noise floor measurement

**Files:**
- Create: `src/moogone/analysis/__init__.py`
- Create: `src/moogone/analysis/wav.py`
- Create: `src/moogone/analysis/noise.py`
- Test: `tests/test_analysis_noise.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces: `load_wav(path) -> Audio` where `Audio` has `samples: np.ndarray` (mono float64, −1..1), `sample_rate: int`. `synth_noise(seconds, sample_rate, level_dbfs, seed=0) -> Audio` for fixtures. `rms_dbfs(audio) -> float`, `noise_floor_dbfs(audio, percentile=10.0) -> float`, `peak_dbfs(audio) -> float`.

**Why the percentile:** a recording of a synth playing is mostly signal, so plain RMS measures the note, not the floor. Taking a low percentile of short-window RMS values measures the quiet parts, which is what "noise floor" means in practice.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_noise.py
import numpy as np
import pytest

from moogone.analysis.noise import noise_floor_dbfs, peak_dbfs, rms_dbfs
from moogone.analysis.wav import Audio, load_wav, save_wav, synth_noise


def test_synth_noise_produces_the_requested_level():
    audio = synth_noise(seconds=1.0, sample_rate=48000, level_dbfs=-60.0)
    assert rms_dbfs(audio) == pytest.approx(-60.0, abs=0.5)


def test_full_scale_sine_measures_near_minus_three_dbfs():
    # An amplitude-1.0 sine has RMS of 1/sqrt(2), which is -3.01 dBFS.
    t = np.arange(48000) / 48000
    audio = Audio(np.sin(2 * np.pi * 1000 * t), 48000)
    assert rms_dbfs(audio) == pytest.approx(-3.01, abs=0.1)
    assert peak_dbfs(audio) == pytest.approx(0.0, abs=0.1)


def test_noise_floor_ignores_loud_content():
    # Half a second of silence-with-noise, half a second of loud tone.
    quiet = synth_noise(0.5, 48000, -70.0).samples
    t = np.arange(24000) / 48000
    loud = np.sin(2 * np.pi * 440 * t) * 0.8
    audio = Audio(np.concatenate([quiet, loud]), 48000)
    # Plain RMS is dominated by the tone; the floor measurement is not.
    assert rms_dbfs(audio) > -20.0
    assert noise_floor_dbfs(audio) == pytest.approx(-70.0, abs=2.0)


def test_digital_silence_reports_a_finite_floor_not_negative_infinity():
    audio = Audio(np.zeros(48000), 48000)
    assert noise_floor_dbfs(audio) < -200.0
    assert np.isfinite(noise_floor_dbfs(audio))


def test_wav_round_trips_through_disk(tmp_path):
    original = synth_noise(0.25, 48000, -50.0)
    path = tmp_path / "probe.wav"
    save_wav(path, original)
    loaded = load_wav(path)
    assert loaded.sample_rate == 48000
    assert rms_dbfs(loaded) == pytest.approx(-50.0, abs=0.5)


def test_stereo_is_downmixed_to_mono(tmp_path):
    import soundfile as sf

    path = tmp_path / "stereo.wav"
    sf.write(path, np.zeros((48000, 2)), 48000)
    assert load_wav(path).samples.ndim == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis_noise.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.analysis'`

- [ ] **Step 3: Write the WAV layer**

```python
# src/moogone/analysis/wav.py
"""Audio loading, saving, and synthetic fixtures.

Everything downstream works in mono float64 normalised to -1..1, so the
measurement code never has to care about source bit depth or channel count.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


@dataclass
class Audio:
    samples: np.ndarray  # mono, float64, -1..1
    sample_rate: int

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate


def load_wav(path: str | Path) -> Audio:
    samples, sample_rate = sf.read(str(path), dtype="float64", always_2d=True)
    return Audio(samples.mean(axis=1), sample_rate)


def save_wav(path: str | Path, audio: Audio) -> None:
    sf.write(str(path), audio.samples, audio.sample_rate, subtype="FLOAT")


def synth_noise(seconds: float, sample_rate: int, level_dbfs: float, seed: int = 0) -> Audio:
    """White noise at a known RMS level. The fixture that validates the rig:
    if the analyser reports -60 dBFS for this at level_dbfs=-60, it is honest.
    """
    rng = np.random.default_rng(seed)
    raw = rng.standard_normal(int(seconds * sample_rate))
    raw /= np.sqrt(np.mean(raw**2))  # normalise to unit RMS
    return Audio(raw * (10 ** (level_dbfs / 20)), sample_rate)
```

- [ ] **Step 4: Write the measurement layer**

```python
# src/moogone/analysis/noise.py
"""Level and noise-floor measurement."""

import numpy as np

from .wav import Audio

# Floor for the log, so digital silence yields a large negative number
# rather than -inf. -400 dBFS is far below any real signal.
_EPS = 1e-20


def _dbfs(value: float) -> float:
    return 20.0 * np.log10(max(float(value), _EPS))


def rms_dbfs(audio: Audio) -> float:
    """Overall RMS level. On a recording with content, this measures the
    content — use noise_floor_dbfs for the floor."""
    return _dbfs(np.sqrt(np.mean(audio.samples**2)))


def peak_dbfs(audio: Audio) -> float:
    return _dbfs(np.max(np.abs(audio.samples)))


def noise_floor_dbfs(audio: Audio, percentile: float = 10.0, window_ms: float = 50.0) -> float:
    """RMS of the quietest windows.

    A recording of a synth is mostly signal, so plain RMS measures the note.
    Taking a low percentile of short-window RMS values measures the gaps,
    which is what 'noise floor' means when someone complains about hiss.
    """
    window = max(1, int(audio.sample_rate * window_ms / 1000))
    usable = len(audio.samples) - (len(audio.samples) % window)
    if usable == 0:
        return rms_dbfs(audio)
    frames = audio.samples[:usable].reshape(-1, window)
    frame_rms = np.sqrt(np.mean(frames**2, axis=1))
    return _dbfs(np.percentile(frame_rms, percentile))
```

```python
# src/moogone/analysis/__init__.py
from .noise import noise_floor_dbfs, peak_dbfs, rms_dbfs
from .wav import Audio, load_wav, save_wav, synth_noise

__all__ = [
    "Audio",
    "load_wav",
    "noise_floor_dbfs",
    "peak_dbfs",
    "rms_dbfs",
    "save_wav",
    "synth_noise",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 56 tests total

- [ ] **Step 6: Commit**

```bash
git add src/moogone/analysis tests/test_analysis_noise.py
git commit -m "feat: WAV loading and noise floor measurement"
```

---

### Task 11: SNR, spectrum, and A-weighting

**Files:**
- Create: `src/moogone/analysis/spectrum.py`
- Modify: `src/moogone/analysis/__init__.py`
- Test: `tests/test_analysis_spectrum.py`

**Interfaces:**
- Consumes: `Audio`, `synth_noise`, `_dbfs` conventions from Task 10
- Produces: `spectrum(audio, n_fft=8192) -> tuple[np.ndarray, np.ndarray]` returning `(freqs_hz, magnitude_dbfs)`; `snr_db(signal: Audio, noise: Audio) -> float`; `a_weight_db(freqs_hz: np.ndarray) -> np.ndarray`; `a_weighted_dbfs(audio) -> float`.

**Why A-weighting:** hiss is a perceptual complaint. An unweighted figure counts inaudible rumble the same as the 2–5 kHz band where hiss actually lives, so it will under-report improvements that matter and over-report ones that don't.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis_spectrum.py
import numpy as np
import pytest

from moogone.analysis.spectrum import a_weight_db, a_weighted_dbfs, snr_db, spectrum
from moogone.analysis.wav import Audio, synth_noise


def _sine(freq: float, seconds: float = 1.0, sample_rate: int = 48000, amp: float = 1.0) -> Audio:
    t = np.arange(int(seconds * sample_rate)) / sample_rate
    return Audio(np.sin(2 * np.pi * freq * t) * amp, sample_rate)


def test_spectrum_peaks_at_the_tone_frequency():
    freqs, mags = spectrum(_sine(1000.0))
    assert freqs[int(np.argmax(mags))] == pytest.approx(1000.0, abs=10.0)


def test_spectrum_length_matches_frequency_axis():
    freqs, mags = spectrum(_sine(1000.0), n_fft=4096)
    assert len(freqs) == len(mags) == 4096 // 2 + 1


def test_a_weighting_is_near_zero_at_1khz():
    # A-weighting is defined as 0 dB at 1 kHz.
    assert a_weight_db(np.array([1000.0]))[0] == pytest.approx(0.0, abs=0.1)


def test_a_weighting_attenuates_low_frequencies():
    # ~-39 dB at 50 Hz by definition of the curve.
    assert a_weight_db(np.array([50.0]))[0] == pytest.approx(-30.2, abs=2.0)
    assert a_weight_db(np.array([50.0]))[0] < a_weight_db(np.array([1000.0]))[0]


def test_a_weighted_level_is_lower_for_rumble_than_for_hiss():
    rumble = _sine(40.0, amp=0.1)
    hiss = _sine(4000.0, amp=0.1)
    assert a_weighted_dbfs(rumble) < a_weighted_dbfs(hiss)


def test_snr_reflects_the_level_difference():
    signal = _sine(1000.0, amp=1.0)          # -3.01 dBFS RMS
    noise = synth_noise(1.0, 48000, -63.0)   # -63 dBFS RMS
    assert snr_db(signal, noise) == pytest.approx(60.0, abs=1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analysis_spectrum.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.analysis.spectrum'`

- [ ] **Step 3: Write the implementation**

```python
# src/moogone/analysis/spectrum.py
"""Spectral analysis, A-weighting, and SNR."""

import numpy as np

from .noise import _dbfs, rms_dbfs
from .wav import Audio


def spectrum(audio: Audio, n_fft: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """Single-sided magnitude spectrum in dBFS, Hann-windowed.

    Returns (frequencies_hz, magnitudes_dbfs). Use this to see *where* the
    noise sits — a flat rise is converter noise, a shaped one is usually
    algorithmic.
    """
    samples = audio.samples[:n_fft]
    if len(samples) < n_fft:
        samples = np.pad(samples, (0, n_fft - len(samples)))
    window = np.hanning(n_fft)
    # Normalise for window loss so a full-scale sine reads near 0 dBFS.
    spec = np.abs(np.fft.rfft(samples * window)) * 2.0 / np.sum(window)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / audio.sample_rate)
    return freqs, np.array([_dbfs(m) for m in spec])


def a_weight_db(freqs_hz: np.ndarray) -> np.ndarray:
    """IEC 61672 A-weighting curve, normalised to 0 dB at 1 kHz."""
    f = np.asarray(freqs_hz, dtype=float)
    f2 = f**2
    numerator = (12194.0**2) * (f2**2)
    denominator = (
        (f2 + 20.6**2)
        * np.sqrt((f2 + 107.7**2) * (f2 + 737.9**2))
        * (f2 + 12194.0**2)
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(denominator > 0, numerator / denominator, 1e-20)
    return 20.0 * np.log10(np.maximum(ratio, 1e-20)) + 2.0


def a_weighted_dbfs(audio: Audio, n_fft: int = 8192) -> float:
    """Overall level with A-weighting applied.

    Hiss is a perceptual complaint. An unweighted figure counts inaudible
    rumble as heavily as the 2-5 kHz band where hiss actually lives.
    """
    freqs, mags = spectrum(audio, n_fft)
    weighted = mags + a_weight_db(freqs)
    power = np.sum(10 ** (weighted / 10.0))
    return 10.0 * np.log10(max(power, 1e-20))


def snr_db(signal: Audio, noise: Audio) -> float:
    """Signal-to-noise ratio from two recordings: one with content, one without."""
    return rms_dbfs(signal) - rms_dbfs(noise)
```

Add to `src/moogone/analysis/__init__.py`:

```python
from .spectrum import a_weight_db, a_weighted_dbfs, snr_db, spectrum
```

and extend `__all__` with `"a_weight_db"`, `"a_weighted_dbfs"`, `"snr_db"`, `"spectrum"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 62 tests total

- [ ] **Step 5: Commit**

```bash
git add src/moogone/analysis tests/test_analysis_spectrum.py
git commit -m "feat: spectrum, A-weighting and SNR measurement"
```

---

### Task 12: Device reconnaissance script

**Files:**
- Create: `recon/moog-recon.sh`
- Create: `recon/README.md`
- Test: `tests/test_recon_script.py`

**Interfaces:**
- Consumes: nothing
- Produces: `recon/moog-recon.sh`, a POSIX shell script taking `--out DIR` (default `/tmp/moog-recon`) and `--active` (default off). Writes numbered files into the output directory and prints a summary.

**Why it is shaped this way:** this script runs once, in front of hardware that then goes away again. A missing field means either a second session or a guess we build on. It therefore gathers everything both downstream projects need in a single pass, and it reads actual values rather than trusting the 2021 writeup — six firmware releases separate that writeup from current units.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recon_script.py
import re
import subprocess
from pathlib import Path

SCRIPT = Path("recon/moog-recon.sh")


def test_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111


def test_script_is_valid_posix_sh():
    result = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_script_contains_no_bashisms():
    text = SCRIPT.read_text()
    for pattern in (r"\[\[", r"\$\(\(", r"\bfunction\s+\w+", r"\becho -e\b", r"\blocal\b"):
        assert not re.search(pattern, text), f"bashism {pattern!r} found"


def test_passive_mode_is_the_default_and_sends_nothing():
    text = SCRIPT.read_text()
    assert "ACTIVE=0" in text
    # Every OSC-sending block must be gated on ACTIVE.
    assert 'if [ "$ACTIVE" -eq 1 ]' in text


def test_script_gathers_every_required_field():
    text = SCRIPT.read_text()
    required = [
        "uname -a",           # arch and kernel
        "/etc/init.d",        # launch scripts
        "las-sc",             # the sound engine
        "/usr/share/las-fx",  # effects home
        "scsyndef",           # compiled synthdefs
        "aconnect",           # ALSA MIDI topology (S88 path)
        "/proc/asound",       # audio devices
        "socat",              # tunnel feasibility
        "df ",                # free space for recordings
    ]
    for field in required:
        assert field in text, f"recon script never gathers {field!r}"


def test_active_mode_documents_the_dumposc_procedure():
    text = SCRIPT.read_text()
    assert "dumpOSC" in text
    assert "front panel" in text.lower()


def test_runs_cleanly_on_a_non_moog_host(tmp_path):
    # Nothing here exists on a Mac or a plain container; it must degrade
    # gracefully rather than abort, or September's run dies at step one.
    out = tmp_path / "recon"
    result = subprocess.run(
        ["sh", str(SCRIPT), "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert (out / "00-summary.txt").exists()
    assert (out / "01-system.txt").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_recon_script.py -v`
Expected: FAIL — `AssertionError` on `test_script_exists_and_is_executable`

- [ ] **Step 3: Write the recon script**

```sh
#!/bin/sh
# Moog One reconnaissance — single pass, read-only by default.
#
# Gathers what BOTH downstream projects need at once, because the hardware
# window is finite and a second pass is expensive. Reads actual values
# rather than trusting published findings: roughly six firmware releases
# separate the 2021 teardown writeups from current units.
#
# Usage:
#   sh moog-recon.sh [--out DIR] [--active]
#
#   --out DIR   where to write results (default /tmp/moog-recon)
#   --active    also send OSC to the sound engine. Off by default.
#
# Every command is guarded: this must degrade gracefully on a host where
# none of it exists, or the September run dies at step one.

set -u

OUT=/tmp/moog-recon
ACTIVE=0

while [ $# -gt 0 ]; do
    case "$1" in
        --out) OUT="$2"; shift 2 ;;
        --active) ACTIVE=1; shift ;;
        -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

mkdir -p "$OUT" || exit 1

# Run a command if it exists, capturing both streams. Never fails the script.
try() {
    _label="$1"
    shift
    printf '\n===== %s =====\n' "$_label"
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || printf '(exited %s)\n' "$?"
    else
        printf '(command not available: %s)\n' "$1"
    fi
}

# Show a file if it exists.
show() {
    printf '\n===== %s =====\n' "$1"
    if [ -r "$1" ]; then
        cat "$1" 2>&1
    else
        printf '(not readable)\n'
    fi
}

# ---------------------------------------------------------------- system
{
    try "kernel and architecture" uname -a
    try "os release" cat /etc/os-release
    show /etc/version
    show /proc/cpuinfo
    try "memory" free
    try "disk free" df -h
    try "uptime" uptime
} > "$OUT/01-system.txt" 2>&1

# ------------------------------------------------------------- processes
{
    try "process table" ps
    printf '\n===== init scripts =====\n'
    ls -la /etc/init.d 2>&1 || printf '(no /etc/init.d)\n'
    show /etc/init.d/S42sc
    show /etc/init.d/S43gui
    show /etc/init.d/S50dropbear
    try "screen sessions" screen -ls
} > "$OUT/02-processes.txt" 2>&1

# --------------------------------------------------------------- sockets
# Resolves the two questions the writeup leaves open: which port las-sc
# actually uses, and whether it binds loopback (which would explain why
# remote OSC failed for earlier explorers without invoking iptables).
{
    try "listening sockets (ss)" ss -lnup
    try "listening sockets (netstat)" netstat -lnup
    try "firewall rules" iptables -L -n
} > "$OUT/03-sockets.txt" 2>&1

# ------------------------------------------------------------------- fx
{
    printf '\n===== /usr/share/las-fx tree =====\n'
    ls -laR /usr/share/las-fx 2>&1 || printf '(not present)\n'
    show /usr/share/las-fx/launch-sc-1
    show /usr/share/las-fx/util/cpu.rtf
    printf '\n===== synthdef and supercollider sources =====\n'
    find / -name '*.scsyndef' -o -name '*.scd' -o -name '*.sc' 2>/dev/null | head -200
    printf '\n===== las binaries =====\n'
    find / -name 'las-*' -o -name 'lasfwu' 2>/dev/null | head -50
} > "$OUT/04-fx.txt" 2>&1

# ------------------------------------------------------------------ midi
# The S88 path for the per-voice pressure project: can this box see a
# class-compliant controller, and on which ALSA device?
{
    try "alsa midi clients" aconnect -l
    try "alsa midi devices" amidi -l
    try "playback devices" aplay -l
    try "capture devices" arecord -l
    printf '\n===== /proc/asound =====\n'
    ls -la /proc/asound 2>&1 || printf '(not present)\n'
    show /proc/asound/cards
    try "usb devices" lsusb
    printf '\n===== usb host controllers =====\n'
    ls -la /sys/bus/usb/devices 2>&1 || printf '(not present)\n'
} > "$OUT/05-midi-audio.txt" 2>&1

# ------------------------------------------------------------- toolchain
# Decides the on-box runtime and whether the tunnel is even possible.
{
    for tool in socat python python3 perl screen tcpdump nc scsynth sclang; do
        printf '%s: ' "$tool"
        command -v "$tool" 2>/dev/null || printf '(absent)\n'
    done
    printf '\n===== writable locations =====\n'
    for dir in /tmp /var/tmp /media /home /root; do
        if [ -w "$dir" ]; then printf '%s: writable\n' "$dir"; fi
    done
    try "disk free (for recordings)" df -h /tmp
} > "$OUT/06-toolchain.txt" 2>&1

# ---------------------------------------------------------------- active
# Everything below transmits. Off unless --active was passed.
if [ "$ACTIVE" -eq 1 ]; then
    {
        printf 'Active probes require the OSC client from the moogone package.\n'
        printf 'Run these from the Mac, or on-box if python is present:\n\n'
        printf '  1. status   — confirms las-sc speaks SuperCollider protocol.\n'
        printf '                This is the cheapest possible compatibility check\n'
        printf '                and the first thing to run.\n\n'
        printf '  2. tree     — /g_queryTree, the full live node graph with every\n'
        printf '                control name. The single most valuable artifact here.\n\n'
        printf '  3. dumpOSC  — set mode 1, then move the front panel FX knobs for\n'
        printf '                30 seconds, then set mode 0 and capture the screen\n'
        printf '                session log. This hands over Moog own OSC namespace\n'
        printf '                by observation rather than guesswork, and serves both\n'
        printf '                the FX and per-voice pressure projects at once.\n\n'
        printf 'Capture the screen session with:\n'
        printf '  screen -ls\n'
        printf '  screen -r <session> -X hardcopy -h %s/08-dumposc.txt\n' "$OUT"
    } > "$OUT/07-active-probes.txt" 2>&1
fi

# --------------------------------------------------------------- summary
{
    printf 'Moog One recon\n'
    printf 'date: %s\n' "$(date 2>/dev/null || printf unknown)"
    printf 'host: %s\n' "$(hostname 2>/dev/null || printf unknown)"
    printf 'active probes: %s\n' "$ACTIVE"
    printf '\nfiles written:\n'
    ls -la "$OUT" 2>&1
} > "$OUT/00-summary.txt" 2>&1

printf 'recon complete: %s\n' "$OUT"
ls "$OUT"
```

```bash
chmod +x recon/moog-recon.sh
```

- [ ] **Step 4: Write the operator README**

```markdown
<!-- recon/README.md -->
# Recon

One pass, in front of hardware that then goes away again. Read this before running it.

## Order of operations

1. **Verify access first.** USB drive with the `k` file, ethernet connected, boot, then
   `ssh root@<ip>`. Nothing else matters until this holds. If it fails, the firmware
   closed the gate and the whole plan needs rethinking.
2. **Copy the script over and run it passive.**
   ```sh
   scp recon/moog-recon.sh root@<ip>:/tmp/
   ssh root@<ip> 'sh /tmp/moog-recon.sh --out /tmp/moog-recon'
   scp -r root@<ip>:/tmp/moog-recon ./captures/
   ```
3. **Read `03-sockets.txt` before sending anything.** It tells you the real port and
   whether las-sc binds loopback.
4. **Then, and only then, run the active probes** in the order listed in
   `07-active-probes.txt`: status, tree, dumpOSC.

## The dumpOSC capture

This is the highest-value artifact in the project. Set mode 1, spend a full 30 seconds
moving *every* FX-related front-panel control, then set mode 0 and grab the log. Play a
few chords while it is running too — that capture is what the per-voice pressure project
needs to learn how notes map to voices.

Do it once, do it thoroughly. You are not back in front of this instrument tomorrow.

## What not to do

- Do not update the firmware. Development continued past discontinuation (v1.8.2,
  September 2025), and an update could close the `k` gate.
- Do not write to `/etc` or replace system binaries. Nothing here needs to.
- Do not skip the passive pass because the active one looks more interesting.
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS — 69 tests total

- [ ] **Step 6: Commit**

```bash
git add recon tests/test_recon_script.py
git commit -m "feat: single-pass device reconnaissance script"
```

---

### Task 13: SuperCollider FX test harness scaffold

**Files:**
- Create: `harness/fx_noise_test.scd`
- Create: `harness/README.md`
- Create: `src/moogone/harness.py`
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: `ScClient`, `Audio`, `noise_floor_dbfs`, `a_weighted_dbfs`
- Produces: `render_probe_script(fx_defname: str, out_path: str, seconds: float = 5.0, tone_hz: float = 1000.0, tone_amp: float = 0.5) -> str` returning ready-to-paste sclang source; `compare_recordings(before: Audio, after: Audio) -> NoiseComparison` with fields `floor_before_dbfs`, `floor_after_dbfs`, `floor_delta_db`, `weighted_before_dbfs`, `weighted_after_dbfs`, `weighted_delta_db`, `improved: bool`.

**This task is deliberately incomplete.** The scaffold and the comparison logic are fully built and tested now. Final wiring — the real SynthDef name, the actual bus layout — needs recon output that does not exist yet. That is a consequence of the problem, not a gap in the plan.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_harness.py
import numpy as np
import pytest

from moogone.analysis.wav import Audio, synth_noise
from moogone.harness import compare_recordings, render_probe_script


def test_script_embeds_the_target_defname_and_output_path():
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav")
    assert "moog_fx_reverb" in src
    assert "/tmp/probe.wav" in src


def test_script_generates_its_tone_internally():
    # The whole diagnostic rests on the signal never touching the ADC.
    src = render_probe_script("moog_fx_reverb", "/tmp/probe.wav", tone_hz=440.0)
    assert "SinOsc" in src
    assert "440" in src
    assert "SoundIn" not in src, "probe must not read the audio input"


def test_script_records_for_the_requested_duration():
    src = render_probe_script("fx", "/tmp/p.wav", seconds=8.0)
    assert "8" in src
    assert "DiskOut" in src


def test_comparison_detects_an_improved_noise_floor():
    before = synth_noise(1.0, 48000, -60.0)
    after = synth_noise(1.0, 48000, -75.0, seed=1)
    result = compare_recordings(before, after)
    assert result.floor_delta_db == pytest.approx(-15.0, abs=1.5)
    assert result.improved is True


def test_comparison_detects_a_worse_noise_floor():
    before = synth_noise(1.0, 48000, -75.0)
    after = synth_noise(1.0, 48000, -60.0, seed=1)
    assert compare_recordings(before, after).improved is False


def test_comparison_reports_both_weighted_and_unweighted():
    before = synth_noise(1.0, 48000, -60.0)
    after = synth_noise(1.0, 48000, -70.0, seed=1)
    result = compare_recordings(before, after)
    assert result.weighted_delta_db < 0
    assert result.floor_delta_db < 0


def test_comparison_rejects_mismatched_sample_rates():
    a = Audio(np.zeros(1000), 48000)
    b = Audio(np.zeros(1000), 44100)
    with pytest.raises(ValueError, match="sample rate"):
        compare_recordings(a, b)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_harness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.harness'`

- [ ] **Step 3: Write the harness module**

```python
# src/moogone/harness.py
"""FX noise probe: script generation and before/after comparison.

The decisive experiment. A tone generated inside SuperCollider is routed
through the FX and recorded on-box, so the signal never passes through the
ADC. If that recording is hissy the noise is DSP-side and reachable from
software; if it is clean while real playing is hissy, the noise enters at
the converters and no amount of OSC will fix it.
"""

from dataclasses import dataclass

from .analysis.noise import noise_floor_dbfs
from .analysis.spectrum import a_weighted_dbfs
from .analysis.wav import Audio

# ############################################################################
# DEFECTIVE AS WRITTEN — DO NOT COPY THIS TEMPLATE. Kept for the record only.
#
# Superseded twice: once for the missing fx node described below, and again by
# the final whole-branch review, which found that even the corrected template
# emitted only a CONTINUOUS TONE — a signal noise_floor_dbfs cannot measure,
# because it takes a low percentile of windowed RMS and a sustained tone leaves
# no quiet window for that percentile to find. The shipped template in
# src/moogone/harness.py now records a SILENCE probe as well.
#
# The effect is never in the signal path. ~tone writes ~probeBus, ~rec reads
# ~probeBus, and {defname} appears ONLY inside comments — no Synth is ever
# created for the effect. The generated script would record a bare test tone,
# come back clean, and support the conclusion "the DSP is quiet, so the noise
# must be the converters" — a false negative from the one experiment built to
# prevent exactly that.
#
# Caught before implementation; the shipped version in src/moogone/harness.py
# instantiates the effect between the tone and the recorder with explicit
# Synth.after ordering. See tests/test_harness.py for a standing regression
# test that fails against this exact template.
# ############################################################################
_TEMPLATE = """// Moog One FX noise probe — generated, do not edit by hand.
//
// Generates a test tone INSIDE SuperCollider and routes it through {defname}.
// The signal never touches the ADC, which is what makes this diagnostic.
//
// Paste into the running sclang session, or feed it via the screen session.

(
SynthDef(\\moog_probe_tone, {{ |out = 0, freq = {tone_hz}, amp = {tone_amp}|
    Out.ar(out, SinOsc.ar(freq) * amp ! 2);
}}).add;

SynthDef(\\moog_probe_record, {{ |in = 0, bufnum = 0|
    DiskOut.ar(bufnum, In.ar(in, 2));
}}).add;
);

(
// TODO-ON-HARDWARE: replace probeBus and the {defname} instantiation with the
// real bus indices and argument names from the recon /g_queryTree capture.
// Everything else in this file is final.
~probeBus = Bus.audio(s, 2);
~buf = Buffer.alloc(s, 65536, 2);
~buf.write("{out_path}", "wav", "float", 0, 0, true);

~tone = Synth(\\moog_probe_tone, [\\out, ~probeBus]);
~rec  = Synth.tail(s, \\moog_probe_record, [\\in, ~probeBus, \\bufnum, ~buf]);

{{
    {seconds}.wait;
    ~rec.free; ~tone.free;
    ~buf.close; ~buf.free; ~probeBus.free;
    "probe written to {out_path}".postln;
}}.fork;
);
"""


def render_probe_script(
    fx_defname: str,
    out_path: str,
    seconds: float = 5.0,
    tone_hz: float = 1000.0,
    tone_amp: float = 0.5,
) -> str:
    """Generate the sclang source for one noise probe."""
    return _TEMPLATE.format(
        defname=fx_defname,
        out_path=out_path,
        seconds=seconds,
        tone_hz=tone_hz,
        tone_amp=tone_amp,
    )


@dataclass
class NoiseComparison:
    floor_before_dbfs: float
    floor_after_dbfs: float
    floor_delta_db: float
    weighted_before_dbfs: float
    weighted_after_dbfs: float
    weighted_delta_db: float
    improved: bool


def compare_recordings(before: Audio, after: Audio) -> NoiseComparison:
    """Compare two probe recordings. Negative deltas mean quieter, i.e. better.

    Both weighted and unweighted figures are reported: the unweighted number
    is the honest physical measurement, the A-weighted one tracks what you
    actually hear.
    """
    if before.sample_rate != after.sample_rate:
        raise ValueError(
            f"sample rate mismatch: {before.sample_rate} vs {after.sample_rate}"
        )
    floor_before = noise_floor_dbfs(before)
    floor_after = noise_floor_dbfs(after)
    weighted_before = a_weighted_dbfs(before)
    weighted_after = a_weighted_dbfs(after)
    return NoiseComparison(
        floor_before_dbfs=floor_before,
        floor_after_dbfs=floor_after,
        floor_delta_db=floor_after - floor_before,
        weighted_before_dbfs=weighted_before,
        weighted_after_dbfs=weighted_after,
        weighted_delta_db=weighted_after - weighted_before,
        improved=floor_after < floor_before,
    )
```

- [ ] **Step 4: Write the harness README and a rendered example**

```markdown
<!-- harness/README.md -->
# FX noise harness

The decisive experiment for the gain-staging project.

## What it does

Generates a test tone inside SuperCollider, routes it through an FX SynthDef, records the
result to a file on the Moog One. The signal never passes through the ADC.

## Reading the result

| Probe recording | Real playing | Verdict |
|---|---|---|
| Hissy | Hissy | Noise is DSP-side — **fixable** via `/n_set` or `/d_recv` |
| Clean | Hissy | Noise enters at the converters — **hardware ceiling**, project ends in a diagnosis |
| Hissy | Worse | Both contribute; fix what is reachable and accept the rest |

SuperCollider runs 32-bit float internally, putting its quantisation floor near -140 dBFS.
Audible hiss in the probe recording is therefore not "digital resolution" — it is a real
signal-level or algorithm problem, and real problems have fixes.

## Generating a probe

```python
from moogone.harness import render_probe_script

print(render_probe_script("moog_fx_reverb", "/tmp/probe_before.wav", seconds=5.0))
```

Paste the output into the running sclang session. Then `scp` the WAV off and:

```python
from moogone.analysis.wav import load_wav
from moogone.harness import compare_recordings

print(compare_recordings(load_wav("probe_before.wav"), load_wav("probe_after.wav")))
```

## The one thing still open

The template carries a single `TODO-ON-HARDWARE` marker: the bus indices and the FX
instantiation arguments. Those come from the recon `/g_queryTree` capture and cannot be
guessed. Everything else in the file is final.
```

Generate the example, so a real rendered script is in the repo:

```bash
uv run python -c "
from moogone.harness import render_probe_script
open('harness/fx_noise_test.scd','w').write(
    render_probe_script('moog_fx_reverb', '/tmp/probe.wav', seconds=5.0))
"
```

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS — 76 tests total

- [ ] **Step 6: Commit**

```bash
git add harness src/moogone/harness.py tests/test_harness.py
git commit -m "feat: SuperCollider FX noise probe harness and comparison"
```

---

### Task 14: End-to-end smoke test and operator entry point

**Files:**
- Create: `src/moogone/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_cli.py`
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything
- Produces: a `moogone` console script with subcommands `status`, `tree`, `dump`, `set`, and `mock`. Shared flags `--host` (default `127.0.0.1`), `--port` (default `9300`), `--tunnel` (use `TunnelTransport` instead of UDP).

**Why:** in September you want to type one command, not compose a Python session in front of a synth. This also proves every layer works together against the mock.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_end_to_end.py
"""Every layer, working together, against the mock."""

from moogone.mock.server import MockScsynth
from moogone.sc.client import ScClient
from moogone.sc.tree import SynthNode
from moogone.transport.udp import UdpTransport


def test_full_stack_query_modify_verify():
    with MockScsynth() as server:
        with UdpTransport("127.0.0.1", server.port) as transport:
            client = ScClient(transport)

            assert client.status().sample_rate == 48000.0

            root = client.query_tree()
            reverb = next(
                n for n in root.walk()
                if isinstance(n, SynthNode) and n.defname == "moog_fx_reverb"
            )
            assert reverb.controls["in_trim"] == 1.0

            client.n_set(reverb.node_id, in_trim=2.0)
            client.sync()

            refreshed = client.query_tree()
            updated = next(
                n for n in refreshed.walk()
                if isinstance(n, SynthNode) and n.defname == "moog_fx_reverb"
            )
            assert updated.controls["in_trim"] == 2.0


def test_dump_osc_captures_traffic_during_a_session():
    with MockScsynth() as server:
        with UdpTransport("127.0.0.1", server.port) as transport:
            client = ScClient(transport)
            client.dump_osc(1)
            server.wait_for_message("/dumpOSC", timeout=1.0)
            client.query_tree()
            assert any(m.address == "/g_queryTree" for m in server.dump_log)
```

```python
# tests/test_cli.py
import json
import subprocess
import sys

from moogone.mock.server import MockScsynth


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "moogone.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_status_reports_server_state():
    with MockScsynth() as server:
        result = _run("status", "--port", str(server.port))
        assert result.returncode == 0, result.stderr
        assert "48000" in result.stdout


def test_tree_lists_synths():
    with MockScsynth() as server:
        result = _run("tree", "--port", str(server.port))
        assert result.returncode == 0, result.stderr
        assert "moog_fx_reverb" in result.stdout


def test_tree_json_is_machine_readable():
    with MockScsynth() as server:
        result = _run("tree", "--port", str(server.port), "--json")
        assert json.loads(result.stdout)["node_id"] == 0


def test_set_changes_a_control():
    with MockScsynth() as server:
        port = str(server.port)
        assert _run("set", "1001", "in_trim=3.0", "--port", port).returncode == 0
        assert "3.0" in _run("tree", "--port", port).stdout


def test_unreachable_server_exits_nonzero_with_a_useful_message():
    result = _run("status", "--port", "1", "--timeout", "0.2")
    assert result.returncode != 0
    assert "no /status.reply" in (result.stdout + result.stderr)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py tests/test_end_to_end.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'moogone.cli'`

- [ ] **Step 3: Write the CLI**

```python
# src/moogone/cli.py
"""Command-line entry point.

In front of the synth you want to type one command, not compose a Python
session.
"""

import argparse
import dataclasses
import json
import sys

from .sc.client import ScClient, ScError, ScTimeout
from .sc.tree import SynthNode
from .transport.tunnel import TunnelTransport
from .transport.udp import UdpTransport


def _open_transport(args):
    if args.tunnel:
        return TunnelTransport(args.port, host=args.host)
    return UdpTransport(args.host, args.port)


def _format_tree(node, depth: int = 0) -> str:
    pad = "  " * depth
    if isinstance(node, SynthNode):
        lines = [f"{pad}synth {node.node_id}  {node.defname}"]
        lines.extend(f"{pad}    {k} = {v}" for k, v in node.controls.items())
        return "\n".join(lines)
    lines = [f"{pad}group {node.node_id}"]
    lines.extend(_format_tree(child, depth + 1) for child in node.children)
    return "\n".join(lines)


def _tree_to_dict(node) -> dict:
    if isinstance(node, SynthNode):
        return {"node_id": node.node_id, "defname": node.defname, "controls": node.controls}
    return {"node_id": node.node_id, "children": [_tree_to_dict(c) for c in node.children]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="moogone", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9300)
    parser.add_argument("--tunnel", action="store_true", help="connect via TCP tunnel, not UDP")
    parser.add_argument("--timeout", type=float, default=2.0)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="query server state (run this first)")

    tree = sub.add_parser("tree", help="dump the live node graph")
    tree.add_argument("--json", action="store_true")

    dump = sub.add_parser("dump", help="set dumpOSC mode on the server")
    dump.add_argument("mode", type=int, choices=[0, 1, 2, 3])

    setter = sub.add_parser("set", help="set controls on a node")
    setter.add_argument("node_id", type=int)
    setter.add_argument("controls", nargs="+", metavar="NAME=VALUE")

    mock = sub.add_parser("mock", help="run a mock scsynth for development")
    mock.add_argument("--mock-port", type=int, default=9300)

    args = parser.parse_args(argv)

    if args.command == "mock":
        from .mock.server import MockScsynth

        server = MockScsynth(args.mock_port)
        server.start()
        print(f"mock scsynth listening on 127.0.0.1:{server.port}  (ctrl-c to stop)")
        try:
            while True:
                import time

                time.sleep(0.5)
        except KeyboardInterrupt:
            server.stop()
        return 0

    try:
        with _open_transport(args) as transport:
            client = ScClient(transport)
            if args.command == "status":
                status = client.status()
                for field in dataclasses.fields(status):
                    print(f"{field.name}: {getattr(status, field.name)}")
            elif args.command == "tree":
                root = client.query_tree(timeout=args.timeout)
                print(json.dumps(_tree_to_dict(root), indent=2) if args.json else _format_tree(root))
            elif args.command == "dump":
                client.dump_osc(args.mode)
                print(f"dumpOSC mode set to {args.mode}")
            elif args.command == "set":
                controls = {}
                for pair in args.controls:
                    if "=" not in pair:
                        parser.error(f"expected NAME=VALUE, got {pair!r}")
                    name, value = pair.split("=", 1)
                    controls[name] = float(value)
                client.n_set(args.node_id, **controls)
                client.sync(timeout=args.timeout)
                print(f"set {args.node_id}: {controls}")
    except (ScError, ScTimeout, ConnectionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add to `pyproject.toml`:

```toml
[project.scripts]
moogone = "moogone.cli:main"
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS — 83 tests total

- [ ] **Step 5: Lint**

Run: `uv run ruff check src tests`
Expected: no findings

- [ ] **Step 6: Commit**

```bash
git add src/moogone/cli.py pyproject.toml tests/test_cli.py tests/test_end_to_end.py
git commit -m "feat: CLI entry point and end-to-end smoke tests"
```

---

## September checklist

Not a task — the operator sequence this plan exists to serve. Print it.

> **SHIPPED AS `README.md`.** The final whole-branch review found this checklist had never
> actually been printed, or moved anywhere an operator would find it: it lived only here, no
> top-level README existed, and `07-active-probes.txt` (the file that reaches the device)
> covered three of the eight steps using raw `python3 -c` snippets that bypassed the CLI's
> guards. The version an operator should follow is now the top-level `README.md`, which is
> drift-tested against the real CLI (`tests/test_operator_docs.py`). Steps 6-8 below are also
> superseded in detail: step 6's capture must be logged to disk rather than read out of
> `screen`'s 100-line scrollback, and step 8's harness now produces a silence probe as well as
> a tone probe — see `harness/README.md`. Treat the list below as the historical record.

1. **Establish access.** USB `k` file, ethernet, boot, `ssh root@<ip>`. **Nothing else matters until this holds.**
2. **Passive recon.** `sh moog-recon.sh --out /tmp/moog-recon`, copy the bundle off.
3. **Read `03-sockets.txt`.** Confirm the real port and the bind address before transmitting anything.
4. **`moogone status`.** Confirms `las-sc` speaks SuperCollider. If this fails, everything downstream needs rethinking.
5. **`moogone tree --json > captures/tree.json`.** The FX chain and every control name.
6. **dumpOSC capture.** Mode 1, move every FX control for 30 seconds, play chords, mode 0, grab the screen log. **Do this thoroughly — you are not back tomorrow.**
7. **Go/no-go for per-voice pressure.** Hold a note, `moogone set <voice-node> <param>=<value>`, listen. One voice changes, or the project is dead.
8. **FX probe.** Render the harness script with real bus indices, run before/after, compare.

---

## Self-Review

**Spec coverage.** All six Foundation components map to tasks: OSC codec + SC client (1, 2, 4–8), mock scsynth (4, 6, 7, 8), recon script (12), measurement rig (10, 11), SC test harness (13), transport (3, 9). Task 14 adds the operator entry point the spec implies but does not name — justified, since the spec's whole premise is a finite hardware window.

**Placeholder scan.** One intentional marker: `TODO-ON-HARDWARE` in the harness template, flagged in the spec and in Task 13's preamble as a consequence of the problem rather than a gap. No other placeholders; every step carries real code.

**Type consistency.** `Audio`, `ServerStatus`, `NodeInfo`, `SynthNode`, `GroupNode`, `NoiseComparison` are defined once and used consistently. Decoders uniformly return `(value, new_offset)`. `noise_floor_dbfs` and `a_weighted_dbfs` keep their signatures from Tasks 10–11 into Task 13. `_dbfs` is defined in `noise.py` and imported by `spectrum.py` rather than duplicated.

**Deliberate deviation from the spec.** The spec left the Mac-side runtime open; the plan fixes it as Python 3.11+ with stdlib-only core packages. A plan cannot contain real code without choosing a language. The *on-box* runtime remains open as specified — recon Task 12 reports what is installed.
