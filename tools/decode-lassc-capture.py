#!/usr/bin/env python3
"""Decode a loopback capture of las-frontend talking to las-sc.

`las-sc` owns the `/p` namespace and listens on 127.0.0.1:9300. Everything the
front panel changes goes over that socket, so a capture of it is the protocol,
observed rather than inferred.

The specific question this exists to answer: **how is
`matrix_expression_slots` actually encoded on the wire?** The preset file
stores it as a flat JSON array with integer id columns and float amount
columns, and `moogd/lassc.go` infers from that an OSC message carrying 7N
arguments typed `i` and `f`. Nobody has ever looked. This looks.

    # on the instrument -- passive, writes nothing, exits by itself
    tcpdump -i lo -s 0 -c 40 -w /tmp/lassc.pcap udp port 9300

    # then, here
    python3 tools/decode-lassc-capture.py /tmp/lassc.pcap

`--predict` prints what moogd would send for the same matrix, so the two can be
compared directly. `--self-test` checks the decoder against a packet built to
that prediction, which is worth doing before trusting it on real bytes.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from moogone.pcap import Datagram, datagrams, parse_osc

SCHEMA = ROOT / "docs" / "arch" / "p-namespace.json"
SLOT_TOKENS = 7


def load_names() -> dict[str, dict[int, str]]:
    """Id -> name for each column, so a decoded row reads in words."""
    if not SCHEMA.exists():
        return {"src": {}, "tr": {}, "dst": {}}
    slots = json.loads(SCHEMA.read_text())["modmatrix_expression_slots"]
    return {
        "src": {int(k): v["name"] for k, v in slots["src_ctl_ids"].items()},
        "tr": {int(k): v["name"] for k, v in slots["transform_ids"].items()},
        "dst": {int(k): v["name"] for k, v in slots["dest_ids"].items()},
    }


def decode_args(tags: str, blob: bytes) -> list[object]:
    """Decode an OSC argument block against its type tag string.

    Unknown tags stop the walk rather than guessing a width -- a wrong guess
    would silently resynchronise onto garbage and the whole point here is to
    find out what the real encoding is.
    """
    out: list[object] = []
    i = 0
    for t in tags:
        if t in "if" and i + 4 <= len(blob):
            (v,) = struct.unpack("!i" if t == "i" else "!f", blob[i : i + 4])
            out.append(v)
            i += 4
        elif t == "d" and i + 8 <= len(blob):
            (v,) = struct.unpack("!d", blob[i : i + 8])
            out.append(v)
            i += 8
        elif t in "sS":
            end = blob.index(b"\x00", i)
            out.append(blob[i:end].decode("ascii", "replace"))
            i += (end + 1 - i + 3) & ~3
        elif t == "b" and i + 4 <= len(blob):
            (n,) = struct.unpack("!I", blob[i : i + 4])
            i += 4
            out.append(blob[i : i + n])
            i += (n + 3) & ~3
        elif t in "TFNI":
            out.append({"T": True, "F": False, "N": None, "I": "inf"}[t])
        else:
            out.append(f"<unhandled tag {t!r} at byte {i}>")
            break
    return out


def render_matrix(args: list[object], names: dict[str, dict[int, str]]) -> str:
    """Group a decoded argument list into seven-token rows and name the ids."""
    if len(args) % SLOT_TOKENS:
        return (f"    !! {len(args)} arguments is not a multiple of "
                f"{SLOT_TOKENS} -- the row width is not what we assumed")
    #: The sentinels map to empty names in the corpus, which reads as a hole.
    SENTINEL = {("src", 48): "(none)", ("tr", 43): "(none)",
                ("dst", 137): "(unrouted)", ("dst", 141): "(unrouted)"}

    def nm(tbl: str, v: object) -> str:
        if not isinstance(v, (int, float)):
            return str(v)
        i = int(v)
        if (tbl, i) in SENTINEL:
            return SENTINEL[(tbl, i)]
        got = names[tbl].get(i)
        return got if got else f"#{i}"

    lines = []
    for r in range(0, len(args), SLOT_TOKENS):
        src, srca, ctl, ctla, tr, tra, dst = args[r : r + SLOT_TOKENS]
        lines.append(
            f"    row {r // SLOT_TOKENS + 1}: "
            f"{nm('src', src)}×{srca} · {nm('src', ctl)}×{ctla} "
            f"→ {nm('tr', tr)}({tra}) ⇒ {nm('dst', dst)}"
        )
    return "\n".join(lines)


def report(grams: list[Datagram], names: dict, only: str | None) -> int:
    seen = 0
    for d in grams:
        for m in parse_osc(d.payload):
            if only and only not in m.address:
                continue
            seen += 1
            args = decode_args(m.tags, m.args)
            print(f"\n[{d.ts:.6f}] {d.src}:{d.src_port} -> {d.dst}:{d.dst_port}"
                  f"  {len(d.payload)} bytes")
            print(f"  {m.address}")
            print(f"  type tags: ,{m.tags or '(none)'}   ({len(args)} arguments)")
            if "matrix_expression_slots" in m.address:
                print(render_matrix(args, names))
            else:
                shown = ", ".join(repr(a) for a in args[:16])
                if len(args) > 16:
                    shown += f", … {len(args) - 16} more"
                print(f"  args: {shown}")
    return seen


# -- what moogd would send, for comparison -----------------------------------


def _pad(n: int) -> bytes:
    return b"\x00" * ((4 - n % 4) % 4)


def osc_encode(addr: str, tokens: list[float], is_int) -> bytes:
    out = addr.encode() + b"\x00"
    out += _pad(len(out))
    tags = b","
    body = b""
    for i, t in enumerate(tokens):
        if is_int(i):
            tags += b"i"
            body += struct.pack("!i", int(t))
        else:
            tags += b"f"
            body += struct.pack("!f", float(t))
    tags += b"\x00"
    return out + tags + _pad(len(tags)) + body


#: One real row, lifted from a factory preset (LISA BELLA DONNA, "FM BELLS OF
#: EVENING SKIES"): mod wheel to LFO 1 pitch offset.
SAMPLE_ROW = [48, 1.0, 6, 0.009999999776482582, 43, 0.0, 52]


def prediction() -> bytes:
    return osc_encode(
        "/p/part/t/1/p/modmatrix/matrix_expression_slots",
        SAMPLE_ROW,
        lambda i: i % SLOT_TOKENS % 2 == 0,
    )


def self_test(names: dict) -> int:
    """Decode a packet built to our own prediction. Proves the decoder, not the
    protocol -- if the instrument disagrees, that is the finding."""
    pkt = prediction()
    msgs = parse_osc(pkt)
    if len(msgs) != 1:
        print("FAIL: prediction did not parse as one message")
        return 1
    m = msgs[0]
    args = decode_args(m.tags, m.args)
    # Ids sit in the even columns of a row, amounts in the odd ones.
    want_tags = "".join("i" if i % 2 == 0 else "f" for i in range(SLOT_TOKENS))
    print(f"  address:   {m.address}")
    print(f"  type tags: ,{m.tags}")
    print(f"  arguments: {args}")
    print(render_matrix(args, names))

    fails = []
    if not m.address.endswith("matrix_expression_slots"):
        fails.append(f"address came back as {m.address!r}")
    if m.tags != want_tags:
        fails.append(f"type tags {m.tags!r}, expected {want_tags!r}")
    if len(args) != SLOT_TOKENS:
        fails.append(f"{len(args)} arguments, expected {SLOT_TOKENS}")
    for i, (got, want) in enumerate(zip(args, SAMPLE_ROW)):
        if abs(float(got) - float(want)) > 1e-6:
            fails.append(f"argument {i}: {got} != {want}")
    if fails:
        for f in fails:
            print(f"  FAIL: {f}")
        return 1

    print("\n  self-test OK -- the decoder reproduces the row it encoded.")
    print("  This says nothing about whether las-sc agrees; that is what the")
    print("  capture is for.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pcap", nargs="?", help="capture file")
    ap.add_argument("--only", default=None,
                    help="only show addresses containing this substring")
    ap.add_argument("--predict", action="store_true",
                    help="print the message moogd would send, as hex")
    ap.add_argument("--self-test", action="store_true",
                    help="decode our own prediction, to check the decoder")
    a = ap.parse_args()
    names = load_names()

    if a.predict:
        pkt = prediction()
        print(f"moogd would send {len(pkt)} bytes to 127.0.0.1:9300:\n")
        for off in range(0, len(pkt), 16):
            chunk = pkt[off : off + 16]
            hexs = " ".join(f"{b:02x}" for b in chunk)
            txt = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(f"  {off:04x}  {hexs:<47}  {txt}")
        return 0
    if a.self_test:
        return self_test(names)
    if not a.pcap:
        ap.error("give a capture file, or --predict / --self-test")

    data = Path(a.pcap).read_bytes()
    grams = [d for d in datagrams(data) if 9300 in (d.src_port, d.dst_port)]
    print(f"{len(grams)} datagram(s) on port 9300")
    if not grams:
        print("\nNothing on 9300. Either the panel was not touched during the "
              "capture,\nor las-frontend reaches las-sc some other way -- which "
              "would itself be\nthe answer.")
        return 1
    n = report(grams, names, a.only)
    print(f"\n{n} OSC message(s) shown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
