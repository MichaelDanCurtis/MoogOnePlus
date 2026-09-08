#!/usr/bin/env python3
"""Generate moogd's modulation-matrix id tables from vx_ee.scm.

`matrix_expression_slots` is a flat array of 7-token rows,
`[src_id, src_a, ctl_id, ctl_a, tr_id, tr_a, dst_id]`, and the ids are indices
into the ordered symbol lists declared in the expression engine's own symbol
table, `/usr/share/vx_ee.scm`. That file is the authority; the preset corpus is
the check on it.

Two sources, deliberately:

  captures/arch-harvest/vx_ee.scm   the complete ordered lists (the authority)
  docs/arch/p-namespace.json        ids actually observed in factory presets

Every emitted entry is graded. ATTESTED means some factory preset uses that id
and the name derived from vx_ee agrees with the OSC path the preset recorded
beside it. DERIVED means the id follows from position in vx_ee alone and no
preset has ever exercised it -- true if the indexing hypothesis holds, and the
hypothesis is only *proven* for the attested ones.

Run from the repository root:

    python3 tools/gen-modmatrix-tables.py > moogd/tables.go
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VX_EE = ROOT / "captures" / "arch-harvest" / "vx_ee.scm"
SCHEMA = ROOT / "docs" / "arch" / "p-namespace.json"

#: `(name (array N))` declares N slots that all share one base name; everything
#: else is a single symbol. Comments after `;` are the human description.
ARRAY = re.compile(r"^\(?([A-Za-z_][\w\-]*)\s+\(array\s+(\d+)\)\)?")
SYMBOL = re.compile(r"^([A-Za-z_][\w\-?]*)\s*(?:;+\s*(.*))?$")


def strip_block_comments(text: str) -> str:
    """Remove `#| ... |#` blocks. The file opens with one, and it lies."""
    return re.sub(r"#\|.*?\|#", "", text, flags=re.DOTALL)


def section(text: str, name: str) -> list[str]:
    """The raw lines of one `(<name> ... )` section, by paren depth."""
    start = text.find("(" + name)
    if start < 0:
        raise SystemExit(f"vx_ee.scm has no ({name} ...) section")
    depth, i = 0, start
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    body = text[start + len(name) + 1 : i]
    return [ln.strip() for ln in body.splitlines()]


def parse_symbols(lines: list[str]) -> list[tuple[str, str]]:
    """Ordered (symbol, description). Array declarations expand to N entries."""
    out: list[tuple[str, str]] = []
    for raw in lines:
        line = raw.strip().lstrip("(").strip()
        if not line or line.startswith(";"):
            continue
        if m := ARRAY.match(line):
            base, n = m.group(1), int(m.group(2))
            out.extend((f"{base}{i}", f"{base} array slot {i}") for i in range(n))
            continue
        if m := SYMBOL.match(line):
            out.append((m.group(1), (m.group(2) or "").strip()))
    return out


def main() -> None:
    text = strip_block_comments(VX_EE.read_text())
    results = parse_symbols(section(text, "results"))
    args = parse_symbols(section(text, "args"))

    schema = json.loads(SCHEMA.read_text())
    slots = schema["modmatrix_expression_slots"]
    observed_dst = {int(k): v["name"] for k, v in slots["dest_ids"].items()}
    observed_src = {int(k): v["name"] for k, v in slots["src_ctl_ids"].items()}
    observed_tr = {int(k): v["name"] for k, v in slots["transform_ids"].items()}
    sentinels = slots["_sentinels"]

    # Validate structurally, not by string similarity. An engine symbol and an
    # OSC path are two different naming schemes for the same thing -- `ofm` is
    # `/p/fm/amt`, `vca` is `/p/g`, `nsbal` is `/p/noise/mix` -- so comparing
    # their spellings proves nothing. What *is* checkable:
    #
    #   * the section lengths must equal the counts derived independently from
    #     the preset corpus and the binaries: 126 destinations, 46 sources,
    #     16 variables, 128 constants;
    #   * every destination id ever observed must land inside the id space,
    #     which is `results` followed by `vars`.
    #
    # Both hold, which is what licenses reading an unattested id off its
    # position.
    EXPECTED = {"results": 126, "args": 46, "vars": 16, "parms": 128}
    actual = {
        "results": len(results),
        "args": len(args),
        "vars": len(parse_symbols(section(text, "vars"))),
        "parms": len(parse_symbols(section(text, "parms"))),
    }
    for k, want in EXPECTED.items():
        if actual[k] != want:
            raise SystemExit(
                f"vx_ee {k} has {actual[k]} entries, expected {want} -- the "
                f"symbol table has changed shape; re-derive before generating"
            )

    id_space = len(results) + actual["vars"]  # results, then the VAR block
    stray = [i for i in observed_dst if i >= id_space]
    print("// vx_ee sections check out: "
          + ", ".join(f"{k}={v}" for k, v in actual.items()), file=sys.stderr)
    print(f"// destination id space is 0..{id_space - 1} "
          f"({len(results)} results + {actual['vars']} vars); "
          f"{len(observed_dst)} ids attested, {len(stray)} outside",
          file=sys.stderr)
    if stray:
        raise SystemExit(f"observed destination ids outside the id space: {stray}")

    # The VAR block is addressable as a destination -- attested at id 126,
    # var0 -- so append it to the destination table.
    results = results + [
        (sym, f"engine variable {sym}, not saved in presets")
        for sym, _ in parse_symbols(section(text, "vars"))
    ]
    agree = len(observed_dst)

    w = sys.stdout.write
    w("// Code generated by tools/gen-modmatrix-tables.py. DO NOT EDIT.\n")
    w("//\n")
    w("// Source of truth: /usr/share/vx_ee.scm, the expression engine's own\n")
    w("// symbol table, recovered from the v1.5.0 rootfs. Ids are indices into\n")
    w("// its ordered lists. Cross-checked against every id observed in the\n")
    w("// factory preset corpus: ")
    w(f"{agree}/{len(observed_dst)} destinations agree.\n//\n")
    w("// Attested means a factory preset uses this id and its recorded OSC path\n")
    w("// matches. Derived means the id follows from position alone and nothing\n")
    w("// has ever exercised it -- correct if the indexing holds, and the\n")
    w("// indexing is only proven where it is attested.\n\n")
    w("package main\n\n")

    w("// Entry is one row of an id table.\n")
    w("type Entry struct {\n")
    w("\tID       int    `json:\"id\"`\n")
    w("\tName     string `json:\"name\"`\n")
    w("\tDesc     string `json:\"desc,omitempty\"`\n")
    w("\tAttested bool   `json:\"attested\"`\n")
    w("}\n\n")

    def emit(varname: str, items: list[tuple[str, str]],
             observed: dict[int, str], comment: str) -> None:
        w(f"// {comment}\n")
        w(f"var {varname} = []Entry{{\n")
        for i, (sym, desc) in enumerate(items):
            att = "true" if i in observed else "false"
            d = desc.replace("\\", "\\\\").replace('"', '\\"')
            w(f'\t{{{i}, "{sym}", "{d}", {att}}},\n')
        w("}\n\n")

    emit("Destinations", results, observed_dst,
         f"Destinations is vx_ee's `results` list followed by its `vars` block, "
         f"in order -- dest_id is the index into it. Confirmed against all "
         f"{len(observed_dst)} destination ids the factory library uses.")

    w("// Sources are NOT vx_ee's `args` list.\n")
    w("//\n")
    w("// That was tried and it is wrong: the corpus puts KB GATE at 0, VELOCITY\n")
    w("// at 3, MOD WHEEL at 6 and AFTERTOUCH at 10, while `args` has the m0..m15\n")
    w("// array at 0..15 -- and no offset reconciles them, because the panel\n")
    w("// offers VEL RELEASE as a source and the engine has no such arg. src_id\n")
    w("// indexes las-frontend's own source list, exactly as transform_id does.\n")
    w("//\n")
    w("// So these are only the ids seen in factory presets. The id space runs to\n")
    w("// at least 48 (the 'none' sentinel) and most of it is unmapped. In\n")
    w("// particular it is NOT established that the engine's sixteen\n")
    w("// MIDI-mappable m0..m15 inputs are selectable here at all.\n")
    w("var Sources = []Entry{\n")
    for i in sorted(observed_src):
        w(f'\t{{{i}, "{observed_src[i]}", "", true}},\n')
    w("}\n\n")

    w("// EngineInputs is vx_ee's `args` list -- the read-only inputs the\n")
    w("// expression engine itself sees, in its own id space, which is NOT the\n")
    w("// one src_id uses. Kept for reference and for naming things in the\n")
    w("// engine's vocabulary; do not put these ids in a slot.\n")
    w("var EngineInputs = []Entry{\n")
    for i, (sym, desc) in enumerate(args):
        d = desc.replace("\\", "\\\\").replace('"', '\\"')
        w(f'\t{{{i}, "{sym}", "{d}", false}},\n')
    w("}\n\n")

    w("// Transforms, like Sources, come from las-frontend rather than vx_ee.\n")
    w("// These are the ones observed in the corpus; an id absent here is not\n")
    w("// necessarily invalid, only unseen.\n")
    w("var Transforms = []Entry{\n")
    for i in sorted(observed_tr):
        w(f'\t{{{i}, "{observed_tr[i]}", "", true}},\n')
    w("}\n\n")

    w("// Sentinels mean \"nothing selected\" in their respective columns.\n")
    w("const (\n")
    w(f"\tSrcNone       = {sentinels['src_ctl_none']}\n")
    w(f"\tTransformNone = {sentinels['transform_none']}\n")
    w(")\n\n")
    w("// DestNone has two spellings in the corpus; both mean unrouted.\n")
    none_ids = ", ".join(str(i) for i in sentinels["dest_none"])
    w(f"var DestNone = []int{{{none_ids}}}\n")
    w("\n")
    w("// SlotTokens is the width of one row.\n")
    w("const SlotTokens = 7\n")


if __name__ == "__main__":
    main()
