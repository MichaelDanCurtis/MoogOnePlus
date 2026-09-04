"""Compile SuperCollider source into a `.scsyndef` binary, using a real sclang.

`/d_recv` takes a **compiled** SynthDef. This project deliberately refused to write
a binary encoder for that format while there was no SuperCollider on the machine to
check one against — an unverifiable encoder is the confident-looking wrong answer
this codebase keeps finding. There is one now, so the honest way to get those bytes
is to ask the reference implementation for them.

Nothing here parses or generates the binary format. sclang writes the file; this
reads it. If the source does not compile, that is reported with the compiler's own
error rather than a guess.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_MAC_SCLANG = Path("/Applications/SuperCollider.app/Contents/MacOS/sclang")

#: A SynthDef name has to be a plain identifier, because it is interpolated into
#: generated SuperCollider source and used as a filename.
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class SynthDefError(RuntimeError):
    """Source that would not compile, or an sclang that would not run."""


def sclang_path() -> str | None:
    if _MAC_SCLANG.exists():
        return str(_MAC_SCLANG)
    return shutil.which("sclang")


def available() -> bool:
    return sclang_path() is not None


def compile_synthdef(name: str, ugen_graph: str, timeout: float = 120.0) -> bytes:
    """Compile ``SynthDef(\\name, { ugen_graph })`` and return the .scsyndef bytes.

    `ugen_graph` is the function body — arguments included, e.g.
    ``|bus = 0| DiskOut.ar(...)``. The name is supplied separately because it is both
    the definition's name and the file sclang writes.
    """
    if not _NAME.match(name or ""):
        raise SynthDefError(f"{name!r} is not a usable SynthDef name")
    binary = sclang_path()
    if binary is None:
        raise SynthDefError(
            "no sclang found; install SuperCollider to compile SynthDefs "
            "(the source generator does not need it, only /d_recv does)"
        )

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        script = out_dir / "build.scd"
        # writeDefFile is what produces the exact bytes the server expects. Wrapped so
        # a compile error is printed and the interpreter still exits: an sclang left
        # sitting at its prompt looks identical to one that is working.
        script.write_text(
            "(\nvar def;\ntry {\n"
            f"    def = SynthDef(\\{name}, {{ {ugen_graph} }});\n"
            f'    def.writeDefFile("{out_dir}");\n'
            '    "VOX_DEF_OK".postln;\n'
            '} {{ |e| ("VOX_DEF_FAIL " ++ e.errorString).postln }};\n'
            "0.exit;\n)\n"
        )
        try:
            proc = subprocess.run(
                [binary, str(script)],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SynthDefError("sclang did not exit; the source may not parse") from exc

        if "VOX_DEF_OK" not in proc.stdout:
            fail = re.search(r"VOX_DEF_FAIL (.*)", proc.stdout)
            detail = fail.group(1) if fail else (proc.stdout or proc.stderr)[-400:]
            raise SynthDefError(f"sclang rejected the SynthDef: {detail.strip()}")

        written = out_dir / f"{name}.scsyndef"
        if not written.exists():
            raise SynthDefError(f"sclang reported success but wrote no {name}.scsyndef")
        data = written.read_bytes()

    if not data.startswith(b"SCgf"):
        raise SynthDefError("what sclang wrote is not a SynthDef file")
    return data


#: Records a stereo bus straight to a file on the instrument. `In.ar` on bus 0 reads
#: the main output — what the instrument is actually sending to its jacks — so this
#: measures the noise floor at the end of the chain, past every effect.
RECORDER = "|buf = 0, bus = 0| DiskOut.ar(buf, In.ar(bus, 2))"
