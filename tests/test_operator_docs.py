"""The top-level README is the operator's September checklist.

Until now the eight-step sequence existed only inside
docs/superpowers/plans/2026-08-10-moog-one-foundation.md, under a heading
that says "Print it." -- and it was never printed. There was no top-level
README at all, and 07-active-probes.txt (the file that actually lands on
the device) covered three of the eight steps.

These tests are deliberately NOT of the "the README mentions dumpOSC"
kind. This project has shipped eleven assertions that could not fail
against the bug they claimed to cover, and a documentation mention-grep is
the purest form of that. What is checked here is DRIFT: that every command
and flag the README tells the operator to type is a command the CLI
actually has, and that the exact output strings the README tells them to
distinguish are the strings the CLI actually prints. Those are the
assertions that fail when the code moves and the document does not -- which
is the only failure mode a checklist has once it exists.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from moogone.cli import _SUBCOMMANDS, _build_parser

README = Path("README.md")


def test_readme_exists_at_the_top_level():
    assert README.is_file(), (
        "no top-level README: the operator sequence lives only in the plan document"
    )


@pytest.mark.parametrize(
    "heading",
    [
        "### 1. Establish access",
        "### 2. Passive recon",
        "### 3. Read `03-sockets.txt`",
        "### 4. `moogone status`",
        "### 5. `moogone tree`",
        "### 6. dumpOSC capture",
        "### 7. Go/no-go for per-voice pressure",
        "### 8. FX probe",
    ],
)
def test_readme_covers_every_step_of_the_september_sequence(heading):
    """All eight steps, including 7 and 8, which appeared in no
    operator-facing document at all before this.

    Anchored on the numbered HEADING, not on a phrase from the step's
    prose. The first version of this test checked for "per-voice
    pressure", which also appears in step 6's text -- so deleting step 7's
    heading outright left the test green. Caught by mutation before
    commit; this project has shipped eleven assertions with that shape and
    a checklist test is the last place to add a twelfth.
    """
    assert heading in README.read_text(), f"the checklist is missing {heading!r}"


def test_every_moogone_command_the_readme_names_actually_exists():
    """Drift guard. A checklist that tells the operator to run a command
    the CLI does not have is worse than no checklist, because it is read in
    front of hardware with no time to debug it.
    """
    # (?<![\w/]) so `scp -r src/moogone root@<ip>` is not read as a
    # `moogone root` invocation -- the first version of this test did
    # exactly that and failed on its own regex rather than on drift.
    named = set(re.findall(r"(?<![\w/])moogone (\w+)", README.read_text()))
    # `moogone --help` and prose like "moogone starts neither" are not
    # subcommand references.
    named = {n for n in named if n not in {"starts", "does", "is", "and", "on", "to"}}
    unknown = named - set(_SUBCOMMANDS)
    assert not unknown, f"README names commands the CLI does not have: {sorted(unknown)}"
    # And the reverse would be a gap rather than an error, so it is only
    # checked for the four that carry the checklist.
    for required in ("status", "tree", "dump", "set"):
        assert required in named, f"the checklist never tells the operator to run {required}"


def test_every_flag_the_readme_names_is_a_real_flag():
    """Same drift guard for options. Parsed out of the real parser rather
    than hardcoded, so renaming a flag fails here.
    """
    text = README.read_text()
    parser = _build_parser()
    known = set()
    for action in parser._actions:
        known.update(action.option_strings)
    # Subparser options live on the subparsers, not the top-level parser.
    for action in parser._actions:
        for sub in (getattr(action, "choices", None) or {}).values():
            for sub_action in sub._actions:
                known.update(sub_action.option_strings)

    # The README also documents the `vox` bridge. Read its flags from its real parser too,
    # so renaming a vox flag fails here the same way renaming a moogone flag does.
    from moogone.vox.bridge import build_parser as build_vox_parser
    from moogone.vox.presets import build_parser as build_presets_parser

    builders = [build_vox_parser, build_presets_parser]

    # recon/ scripts are not importable as a package, so load knob.py by path. The
    # README documents its flags, so the same drift guard has to cover them.
    knob = Path("recon/knob.py")
    if knob.exists():
        import importlib.util

        spec = importlib.util.spec_from_file_location("_knob", knob)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        builders.append(module.build_parser)

    for build in builders:
        for action in build()._actions:
            known.update(action.option_strings)

    named = set(re.findall(r"(--[a-z][a-z-]+)", text))
    # Flags belonging to other tools the checklist drives: the recon script's --out and
    # --active, and `uv sync --extra`.
    # Flags belonging to the INSTRUMENT's own binaries, quoted in the README as
    # evidence rather than as instructions. --host-oleds is las-frontend's, and it is
    # the reason the main display is read from a framebuffer instead of the panel bus.
    theirs = {"--host-oleds"}
    other_tools = {"--out", "--active", "--extra"} | theirs
    unknown = named - known - other_tools
    assert not unknown, f"README names flags moogone/vox do not have: {sorted(unknown)}"
    assert "--tunnel" in named and "--port" in named


@pytest.mark.parametrize(
    "fragment",
    [
        "(synth): ",
        "(synth), UNCONFIRMED: ",
    ],
)
def test_readme_quotes_the_set_outcomes_the_cli_actually_prints(fragment):
    """Step 7 tells the operator to read `set`'s output and distinguish
    three outcomes, because the distinction between "sent and confirmed",
    "sent but unconfirmed" and "not sent" is the difference between
    "per-voice control works" and "the project is dead". If the CLI's
    wording changes and this table does not, the operator is matching
    against a string that no longer appears.

    Mutation-checked: change either message in cli.py and this fails.
    """
    cli_source = Path("src/moogone/cli.py").read_text()
    assert fragment in cli_source, f"cli.py no longer prints {fragment!r}"
    assert fragment in README.read_text(), f"README no longer documents {fragment!r}"


def test_readme_install_instruction_matches_a_dependency_free_package():
    """The README tells the operator they can scp src/moogone onto the
    device and run it with nothing installed. That is true only while the
    core package has no third-party dependencies -- and it is the claim
    most likely to quietly stop being true.

    Verified by actually importing the CLI with third-party packages
    hidden, not by reading pyproject.toml: a dependency added to the code
    without being declared would satisfy a pyproject check and still break
    on the device.
    """
    assert "dependencies = []" in Path("pyproject.toml").read_text()

    # Import the CLI in a subprocess whose sys.path excludes site-packages,
    # so numpy/soundfile are genuinely unavailable.
    probe = (
        "import sys, sysconfig;"
        "purelib = sysconfig.get_paths()['purelib'];"
        "platlib = sysconfig.get_paths()['platlib'];"
        "sys.path = [p for p in sys.path if p not in (purelib, platlib)];"
        "sys.path.insert(0, 'src');"
        "import moogone.cli;"
        "import numpy"  # must FAIL, proving site-packages really was removed
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert "ModuleNotFoundError: No module named 'numpy'" in result.stderr, (
        f"the probe did not actually hide site-packages, so it proves nothing: {result.stderr!r}"
    )
    assert "moogone" not in result.stderr, (
        "moogone.cli does not import with third-party packages unavailable, so it "
        f"cannot be scp'd to the device and run as the README claims: {result.stderr!r}"
    )
