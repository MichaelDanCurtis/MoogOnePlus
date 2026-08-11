"""Tests for the device reconnaissance script.

This script runs exactly once, on hardware that then goes away for months.
The tests below are written against that constraint: it is far more
important to know a field is genuinely CAPTURED than to know the script
merely MENTIONS it somewhere.

Two test styles appear here, and each test is commented with which one it
is:

  MENTION  -- greps the script's own source text. Cheap, catches wholesale
              deletion of a section, but a comment mentioning a tool name
              satisfies it just as well as real code that runs the tool.
              Kept only as a fast smoke check, never as the sole guard for
              a field.

  COLLECTS -- actually runs the script (via subprocess) against a stubbed
              PATH and/or a fake filesystem root, and asserts that data
              which only a real invocation could produce shows up in the
              right output file. This is the kind of test that fails if
              the corresponding gathering line is deleted.

The brief's own `test_script_gathers_every_required_field` was exactly the
MENTION trap described above -- it would pass against a script that only
ever *talks about* las-sc, socat, and aconnect in comments. It has been
replaced below with one COLLECTS test per field.
"""

import os
import re
import subprocess
from pathlib import Path

SCRIPT = Path("recon/moog-recon.sh")

# Minimal, deterministic PATH: just enough real Unix to run the script
# (mkdir, printf if not builtin, cat, ls, find, head, sed, date, hostname,
# rm, ps, df, uname, tr) without depending on whatever happens to be
# installed on the machine running the tests (a developer's laptop may
# have socat or aconnect installed for unrelated reasons; the target
# device and a bare CI container do not).
REAL_BIN_DIRS = "/bin:/usr/bin"


def make_stub(bin_dir: Path, name: str, body: str) -> None:
    """Write an executable stub named `name` into `bin_dir`."""
    script = bin_dir / name
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)


def argv_echo_stub(bin_dir: Path, name: str, marker: str) -> None:
    """A stub that proves both that it ran and exactly what it was called
    with, by writing "<marker>:<its own argv>" to stdout."""
    make_stub(bin_dir, name, f"printf '{marker}:%s\\n' \"$*\"")


def write_tree(base: Path, files: dict) -> None:
    """Create `base`-relative files from a {relative_path: content} map.
    Content may be str (written as text) or bytes (written raw, for the
    NUL-separated /proc/*/cmdline fixture)."""
    for rel, content in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content)


def run_script(tmp_path, args=None, bin_dir=None, extra_env=None, timeout=30):
    """Run the recon script with a controlled PATH and environment.

    Defaults MOOG_RECON_FSROOT to an empty, isolated directory and
    MOOG_RECON_FIND_TIMEOUT to a small value, so tests that don't care
    about filesystem content stay fast and never walk the real machine's
    "/" (which, unbounded, takes 20-30s per call on an ordinary dev
    laptop -- see test_runs_cleanly_on_a_non_moog_host, which is the one
    test that deliberately exercises the real, unrestricted path and
    bypasses this helper entirely for that reason). Callers that need
    specific filesystem content or timing pass their own values via
    extra_env, which override these defaults.

    Returns (CompletedProcess, out_dir). out_dir is tmp_path/"recon" unless
    args overrides --out itself.
    """
    out = tmp_path / "recon"
    path = f"{bin_dir}:{REAL_BIN_DIRS}" if bin_dir else REAL_BIN_DIRS
    empty_fsroot = tmp_path / "empty-fsroot"
    empty_fsroot.mkdir(exist_ok=True)
    env = {
        "PATH": path,
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "MOOG_RECON_FSROOT": str(empty_fsroot),
        "MOOG_RECON_FIND_TIMEOUT": "3",
    }
    if extra_env:
        env.update(extra_env)
    full_args = ["--out", str(out)] if args is None else args
    result = subprocess.run(
        ["sh", str(SCRIPT), *full_args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        check=False,
    )
    return result, out


# --------------------------------------------------------------- baseline
# Structural checks. Cheap, still worth keeping: they catch a script that
# doesn't parse, uses a bashism, or isn't executable at all. None of these
# prove anything is actually gathered.


def test_script_exists_and_is_executable():
    assert SCRIPT.exists()
    assert SCRIPT.stat().st_mode & 0o111


def test_script_is_valid_posix_sh():
    result = subprocess.run(["sh", "-n", str(SCRIPT)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_script_contains_no_bashisms():
    text = SCRIPT.read_text()
    for pattern in (r"\[\[", r"\$\(\(", r"\bfunction\s+\w+", r"\becho -e\b", r"\blocal\b"):
        assert not re.search(pattern, text), f"bashism {pattern!r} found"


def test_active_mode_documents_the_dumposc_procedure():
    # MENTION. Kept from the brief as a cheap sanity check that the
    # instructions exist in the shipped script at all. See
    # test_active_run_writes_the_dumposc_runbook below for the version
    # that proves they are actually gated and actually written.
    text = SCRIPT.read_text()
    assert "dumpOSC" in text
    assert "front panel" in text.lower()


def test_passive_mode_is_the_default_and_sends_nothing_structurally():
    # MENTION. Cheap regression guard for the gate itself; see
    # test_passive_run_never_writes_active_probes for the runtime version.
    text = SCRIPT.read_text()
    assert "ACTIVE=0" in text
    assert 'if [ "$ACTIVE" -eq 1 ]' in text


# ------------------------------------------------------- must-not-abort
# The brief's own test only proves the script survives commands that are
# MISSING. It never exercises the branch where a command EXISTS but fails
# (try()'s `|| printf '(exited %s)'` fallback) -- a real gap, since a
# present-but-erroring binary is at least as likely on real hardware as an
# absent one. Both are covered here.


def test_runs_cleanly_on_a_non_moog_host(tmp_path):
    # COLLECTS (behavioral survival). Nothing here exists on a Mac or a
    # plain container; it must degrade gracefully rather than abort, or
    # September's run dies at step one. Runs with the REAL, unrestricted
    # PATH and the real filesystem root -- this is the one test standing
    # in for "what actually happens on an unprepared machine," so it must
    # not be given any of the fixture/stub help the other tests use.
    out = tmp_path / "recon"
    result = subprocess.run(
        ["sh", str(SCRIPT), "--out", str(out)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (out / "00-summary.txt").exists()
    assert (out / "01-system.txt").exists()


def test_survives_a_command_that_exists_but_fails(tmp_path):
    # COLLECTS. Mutation check: if try()'s `|| printf '(exited %s)' "$?"`
    # fallback were deleted, a failing-but-present command would propagate
    # its failure text unguarded but the script would still reach the end
    # under `set -u` alone -- so the REAL discriminator here is narrower:
    # it proves the specific exited-N message path fires, not merely that
    # the script survives (test_runs_cleanly_on_a_non_moog_host already
    # covers survival against ABSENT commands; this covers PRESENT-but-
    # failing ones, which try()'s guard is the only thing handling).
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(bin_dir, "uname", "printf 'boom\\n' >&2\nexit 7")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0, result.stderr
    assert (out / "00-summary.txt").exists()
    system_text = (out / "01-system.txt").read_text()
    assert "(exited 7)" in system_text
    assert "boom" in system_text


def test_missing_out_value_fails_cleanly_not_via_shell_crash(tmp_path):
    # COLLECTS. Regression test for a defect found in the brief's own
    # argument parser: `--out) OUT="$2"; shift 2 ;;` under `set -u`
    # crashes with "$2: unbound variable" / "2: parameter not set" if
    # --out is the last token with no value -- an uncontrolled crash
    # before a single byte of recon output is written, on the very first
    # line of argument parsing. Verified against the brief's literal
    # snippet with dash and bash-as-sh before fixing it here.
    result = subprocess.run(
        ["sh", str(SCRIPT), "--out"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "requires a directory argument" in result.stderr
    assert "unbound variable" not in result.stderr
    assert "parameter not set" not in result.stderr


def test_unknown_flag_exits_nonzero_with_a_message(tmp_path):
    result = subprocess.run(
        ["sh", str(SCRIPT), "--not-a-real-flag"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "unknown option" in result.stderr


def test_help_flag_prints_usage_and_exits_zero(tmp_path):
    result = subprocess.run(
        ["sh", str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    # Checked against the explanatory detail lines, not the one-line
    # synopsis ("Usage: ... [--out DIR] [--active]") -- the synopsis alone
    # would satisfy a bare "--out"/"--active" substring check even if the
    # actual explanations beneath it were deleted, which mutation testing
    # confirmed happens in practice.
    assert "where to write results" in result.stdout
    assert "active-probe runbook" in result.stdout


# ------------------------------------------------------- field gathering
# One COLLECTS test per field in the brief's required list, each proving
# actual data flow (a stubbed command's real output, or a fixture
# filesystem's real content) into the specific output file, rather than
# grepping the script's source text.


def test_gathers_kernel_and_arch_via_uname_a(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_echo_stub(bin_dir, "uname", "UNAMESTUB")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "01-system.txt").read_text()
    # Proves uname was invoked with exactly -a, not merely invoked, and
    # not merely named in a comment.
    assert "UNAMESTUB:-a" in text


def test_gathers_free_disk_space_via_df(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_echo_stub(bin_dir, "df", "DFSTUB")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "01-system.txt").read_text()
    assert "DFSTUB:-h" in text


def test_gathers_disk_free_for_the_actual_output_directory(tmp_path):
    # COLLECTS + deliberate improvement over the brief: the brief's script
    # always checked `df -h /tmp` regardless of where --out pointed. If an
    # operator passes --out /media/usb, /tmp free space tells them nothing
    # about where the recording would actually land. This asserts the
    # toolchain check targets $OUT itself.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_echo_stub(bin_dir, "df", "DFSTUB")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "06-toolchain.txt").read_text()
    assert f"DFSTUB:-h {out}" in text


def test_gathers_process_table_that_would_reveal_the_sound_engine(tmp_path):
    # COLLECTS. Deliberately does NOT grep for a hardcoded "las-sc" --
    # doing so would repeat exactly the hypothesis-confirming anti-pattern
    # the task warns against ("greps for 9300 and reports found"). Instead
    # this proves the mechanism that would reveal whatever the process is
    # ACTUALLY named today: a full process-table dump. If las-sc's process
    # got renamed in six firmware releases, a fixed grep would silently
    # find nothing; this stub simulates that name (or any other) simply
    # showing up in the real table.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(
        bin_dir,
        "ps",
        "printf 'PID USER COMMAND\\n'\nprintf '4242 root PSSTUB_SOUND_ENGINE\\n'",
    )
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "02-processes.txt").read_text()
    assert "PSSTUB_SOUND_ENGINE" in text


def test_gathers_full_cmdline_via_proc(tmp_path):
    # COLLECTS. ps often truncates argv on busybox; /proc/*/cmdline does
    # not. NUL-separated, exactly as the kernel writes it -- this also
    # proves the NUL-to-space parsing is correct, not just present.
    fsroot = tmp_path / "fsroot"
    write_tree(fsroot, {"proc/9999/cmdline": b"las-sc\x00--port\x009999\x00"})
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "02-processes.txt").read_text()
    assert "9999: las-sc --port 9999" in text


def test_gathers_init_scripts_directory_listing(tmp_path):
    fsroot = tmp_path / "fsroot"
    write_tree(fsroot, {"etc/init.d/S77-marker-launcher": "exec marker\n"})
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "02-processes.txt").read_text()
    assert "S77-marker-launcher" in text


def test_gathers_las_fx_tree_listing(tmp_path):
    fsroot = tmp_path / "fsroot"
    write_tree(fsroot, {"usr/share/las-fx/SynthDefs/marker-fx-file.txt": "x"})
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "04-fx.txt").read_text()
    assert "marker-fx-file.txt" in text


def test_gathers_scsyndef_and_las_binaries_via_bounded_find(tmp_path):
    # COLLECTS. Exercises the SAME bounded hunt() codepath production
    # uses, just pointed at a tiny fixture tree instead of "/" -- proves
    # the search is both bounded (see the hang test below) AND still
    # actually finds files, which a naively narrow bound could break.
    fsroot = tmp_path / "fsroot"
    write_tree(
        fsroot,
        {
            "a/b/c/marker.scsyndef": "x",
            "opt/vendor/las-sc-marker": "x",
        },
    )
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "04-fx.txt").read_text()
    assert "marker.scsyndef" in text
    assert "las-sc-marker" in text


def test_gathers_alsa_midi_topology_via_aconnect(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_echo_stub(bin_dir, "aconnect", "ACONNECTSTUB")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "05-midi-audio.txt").read_text()
    assert "ACONNECTSTUB:-l" in text


def test_gathers_asound_devices(tmp_path):
    fsroot = tmp_path / "fsroot"
    write_tree(fsroot, {"proc/asound/cards": "0: MoogOneMarkerCard\n"})
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "05-midi-audio.txt").read_text()
    assert "MoogOneMarkerCard" in text


def test_gathers_socat_presence_when_installed(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(bin_dir, "socat", "exit 0")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "06-toolchain.txt").read_text()
    # command -v prints the real resolved path to the stub, not a
    # hardcoded "yes" -- proves genuine resolution.
    assert f"socat: {bin_dir}/socat" in text


def test_reports_socat_absence_rather_than_hiding_it(tmp_path):
    # Uses the deliberately minimal, real PATH with no stub: socat is not
    # on it (verified separately not to be ambiently present -- see
    # REAL_BIN_DIRS comment). This is the negative twin of the test above;
    # together they prove the check is a live command -v, not a canned
    # string in either direction.
    result, out = run_script(tmp_path)
    assert result.returncode == 0
    text = (out / "06-toolchain.txt").read_text()
    assert "socat: (absent)" in text


def test_checks_both_tcp_and_udp_listening_sockets(tmp_path):
    # COLLECTS + deliberate improvement over the brief: the brief only
    # ever asked for -lnup (UDP only), baking in the 2021 writeup's
    # protocol assumption. The task brief for this file is explicit that
    # even that should be treated as a hypothesis, so both protocols are
    # requested.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_echo_stub(bin_dir, "ss", "SSSTUB")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0
    text = (out / "03-sockets.txt").read_text()
    # Combined short options (e.g. "-tulpn"), so check both letters are
    # present in the captured flag token rather than for "-t"/"-u" as
    # separate substrings.
    argv_line = text.split("SSSTUB:")[1].splitlines()[0]
    assert "t" in argv_line
    assert "u" in argv_line


# ------------------------------------------------------------ find bound
# The performance risk called out for this task: `find /` over a real dev
# filesystem is slow, and a real hang (a wedged network mount) must not
# take the whole recon down with it.


def test_bounded_find_does_not_hang_when_find_itself_hangs(tmp_path):
    # COLLECTS. Directly simulates the worst case named in the brief: find
    # refusing to return (a hung network mount). A stub `find` that never
    # exits stands in for that. If the watchdog were deleted, this test's
    # own subprocess timeout would fire and fail it with TimeoutExpired --
    # that failure mode is itself proof the test discriminates.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(bin_dir, "find", "sleep 30")
    result, out = run_script(
        tmp_path,
        bin_dir=bin_dir,
        extra_env={"MOOG_RECON_FIND_TIMEOUT": "2"},
        timeout=20,
    )
    assert result.returncode == 0
    assert (out / "00-summary.txt").exists()


def test_bounded_find_actually_bounds_wall_clock_time(tmp_path):
    # COLLECTS. Same hang simulation, but asserts on elapsed time rather
    # than just "didn't hit pytest's outer timeout" -- proves the bound is
    # roughly the configured value, not just "eventually less than 20s".
    import time

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(bin_dir, "find", "sleep 30")
    start = time.monotonic()
    result, _out = run_script(
        tmp_path,
        bin_dir=bin_dir,
        extra_env={"MOOG_RECON_FIND_TIMEOUT": "2"},
        timeout=20,
    )
    elapsed = time.monotonic() - start
    assert result.returncode == 0
    assert elapsed < 10, f"took {elapsed}s; watchdog should cap the find call near 2s"


def test_find_maxdepth_and_timeout_are_configurable(tmp_path):
    # MENTION-adjacent but on defaults, not behavior: confirms the knobs
    # exist and have sane production defaults. The behavioral proof that
    # they DO something lives in the two tests above.
    text = SCRIPT.read_text()
    assert "MOOG_RECON_FIND_MAXDEPTH" in text
    assert "MOOG_RECON_FIND_TIMEOUT" in text
    assert re.search(r'FIND_TIMEOUT="\$\{MOOG_RECON_FIND_TIMEOUT:-\d+\}"', text)


# ------------------------------------------------------- passive/active


def test_passive_run_never_writes_active_probes(tmp_path):
    # COLLECTS. The behavioral half of the passive/active split: proves
    # nothing active-mode-flavored gets written unless --active is passed,
    # not just that the word ACTIVE=0 appears in the source.
    result, out = run_script(tmp_path)
    assert result.returncode == 0
    assert not (out / "07-active-probes.txt").exists()


def test_active_run_writes_the_dumposc_runbook(tmp_path):
    # COLLECTS. The other half: with --active, the runbook is written,
    # and it is the runbook (dumpOSC + front panel), not just any file.
    result, out = run_script(tmp_path, args=["--out", str(tmp_path / "recon"), "--active"])
    assert result.returncode == 0
    probes = out / "07-active-probes.txt"
    assert probes.exists()
    text = probes.read_text()
    assert "dumpOSC" in text
    assert "front panel" in text.lower()
    assert "03-sockets.txt" in text  # tells the operator to check the real port first


def test_passive_summary_nudges_toward_the_active_dumposc_capture(tmp_path):
    # COLLECTS. The orchestrator's brief calls the dumpOSC capture "the
    # highest-value artifact in the entire project" and asks that the
    # instructions for it be unmissable. This proves the passive run
    # surfaces that on the operator's own terminal, not only in a file
    # they might not open.
    result, _out = run_script(tmp_path)
    assert result.returncode == 0
    assert "dumpOSC" in result.stdout
    assert "--active" in result.stdout


def test_active_flag_is_reflected_in_the_summary_file(tmp_path):
    result, out = run_script(tmp_path, args=["--out", str(tmp_path / "recon"), "--active"])
    assert result.returncode == 0
    text = (out / "00-summary.txt").read_text()
    assert "active probes written: 1" in text
