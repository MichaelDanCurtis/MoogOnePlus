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


def test_final_directory_listing_has_a_fallback_when_ls_fails(tmp_path):
    # COLLECTS. Review finding: the summary's `ls -la "$OUT"` and the
    # final bare `ls "$OUT"` had no fallback at all, unlike every other
    # ls call-site in the script -- if ls failed, the "files written"
    # confirmation an operator relies on to know the run produced
    # anything would go silently blank. Stubs ls to exist but fail (exit
    # 1, no output) and checks both spots now say something instead.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(bin_dir, "ls", "exit 1")
    result, out = run_script(tmp_path, bin_dir=bin_dir)
    assert result.returncode == 0, result.stderr
    summary_text = (out / "00-summary.txt").read_text()
    assert "unable to list" in summary_text
    assert "unable to list" in result.stdout


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


def test_out_value_that_looks_like_a_flag_is_rejected_clearly(tmp_path):
    # COLLECTS. Review finding: `--out --active` previously took the
    # literal string "--active" as the directory, then died on mkdir's
    # own "illegal option" error -- a clean nonzero exit, but a confusing
    # one, from a tool other than this script, for what's almost always a
    # missing-value typo at 2am. Now rejected by the parser itself with
    # its own message, before mkdir ever runs.
    result = subprocess.run(
        ["sh", str(SCRIPT), "--out", "--active"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert "--out requires a directory argument" in result.stderr
    assert "--active" in result.stderr
    assert "illegal option" not in result.stderr
    assert "mkdir" not in result.stderr


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


def test_hunt_excludes_directories_from_results(tmp_path):
    # COLLECTS. Review finding: without -type filtering, a directory named
    # las-* (including las-fx itself) lands in the results and eats into
    # the 200-line cap on information the ls -laR two lines above already
    # captured. Plants both a matching directory and a matching file;
    # only the file should appear.
    fsroot = tmp_path / "fsroot"
    write_tree(fsroot, {"opt/las-actual-binary": "x"})
    (fsroot / "opt" / "las-vendor-dir").mkdir(parents=True)
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "04-fx.txt").read_text()
    assert "las-actual-binary" in text
    assert "las-vendor-dir" not in text


# --------------------------------------------------- truncation marking
# The Important review finding: a search killed by the watchdog and a
# search that legitimately found nothing produce byte-identical output
# otherwise. hunt() now distinguishes them (via bounded()'s exit status
# for a timeout-kill, and a raw line count for the 200-line display cap)
# and marks BOTH cases visibly in 04-fx.txt, 00-summary.txt, and stdout.
# These two tests are a matched pair by design: the "legitimately empty"
# one is what would catch a marker emitted unconditionally, which is
# exactly what the review asked to be provable, and what the mutation
# below proves.


def _truncation_marker_locations(out, stdout_text):
    """Return (in 04-fx.txt, in 00-summary.txt, in stdout) for 'TRUNCATED'."""
    fx_text = (out / "04-fx.txt").read_text()
    summary_text = (out / "00-summary.txt").read_text()
    return (
        "TRUNCATED" in fx_text,
        "TRUNCATED" in summary_text,
        "TRUNCATED" in stdout_text,
    )


def test_truncation_marker_appears_everywhere_when_the_watchdog_kills_the_search(tmp_path):
    # COLLECTS. Reproduces the review's own repro: a find that hangs past
    # its timeout. Asserts the marker in all three places an operator
    # might look -- the file itself, the summary they'd read first, and
    # the terminal they were watching when the run finished -- since the
    # review's ask was specifically "something an operator scanning the
    # file cannot miss."
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
    in_fx, in_summary, in_stdout = _truncation_marker_locations(out, result.stdout)
    assert in_fx, "04-fx.txt should carry the truncation marker"
    assert in_summary, "00-summary.txt should carry the truncation marker"
    assert in_stdout, "stdout should carry the truncation marker"
    # The marker names the timeout that was hit, not just that one fired.
    assert "2s" in (out / "04-fx.txt").read_text()


def test_truncation_marker_absent_on_a_legitimately_empty_search(tmp_path):
    # COLLECTS. The other half of the pair: find actually runs to
    # completion (a real, unstubbed find against an empty fixture root,
    # well inside the default timeout) and finds nothing. No marker
    # anywhere -- an empty result and a cut-short one must read
    # differently, which is the entire point of this fix.
    result, out = run_script(tmp_path)
    assert result.returncode == 0
    in_fx, in_summary, in_stdout = _truncation_marker_locations(out, result.stdout)
    assert not in_fx, "04-fx.txt should not claim truncation for a genuinely complete search"
    assert not in_summary
    assert not in_stdout


def test_truncation_marker_would_not_pass_if_emitted_unconditionally(tmp_path):
    # Mutation proof, run live rather than asserted in prose: patches
    # hunt() so the timeout-kill marker prints unconditionally (the exact
    # regression this pair of tests exists to catch), then confirms the
    # legitimately-empty test above fails against that mutation and the
    # real script is restored and still green afterward. This is the same
    # method used elsewhere in this file's review history, run here so
    # the specific claim in the task instructions -- "make sure the test
    # would fail if the marker were emitted unconditionally" -- is
    # demonstrated, not just asserted.
    original = SCRIPT.read_text()
    marker_line = '    if [ "$_hstatus" -eq 143 ]; then\n'
    assert marker_line in original, "hunt()'s timeout-kill check has moved; update this test"
    mutated = original.replace(marker_line, "    if true; then\n", 1)
    assert mutated != original
    try:
        SCRIPT.write_text(mutated)
        result, out = run_script(tmp_path)
        assert result.returncode == 0
        text = (out / "04-fx.txt").read_text()
        assert "TRUNCATED" in text, "mutation should make the marker unconditional"
    finally:
        SCRIPT.write_text(original)
    # Confirm the restore actually took and the real script is unaffected.
    assert SCRIPT.read_text() == original
    result, out = run_script(tmp_path)
    assert result.returncode == 0
    assert "TRUNCATED" not in (out / "04-fx.txt").read_text()


def test_truncation_marker_when_matches_exceed_the_two_hundred_line_cap(tmp_path):
    # COLLECTS. The second, independent way results can be incomplete
    # without looking it: more matches than the display cap. Plants 250
    # matching files and checks the marker states the real count and that
    # exactly 200 lines were actually shown (not 250).
    fsroot = tmp_path / "fsroot"
    many_dir = fsroot / "many"
    many_dir.mkdir(parents=True)
    for i in range(250):
        (many_dir / f"f{i}.scsyndef").write_text("x")
    result, out = run_script(tmp_path, extra_env={"MOOG_RECON_FSROOT": str(fsroot)})
    assert result.returncode == 0
    text = (out / "04-fx.txt").read_text()
    assert "TRUNCATED" in text
    assert "250" in text
    assert text.count(".scsyndef") == 200


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


# ------------------------------------- seams found in the whole-branch review


def test_socket_capture_survives_both_ss_and_netstat_being_absent(tmp_path):
    """COLLECTS. 03-sockets.txt rested entirely on ss and netstat, which are
    BOTH optional: on a stripped buildroot ARM device ss is frequently
    absent outright, and busybox netstat only reports the owning process
    with a build flag that is often off. With neither present the file
    answered neither of the spec's two open questions -- which port the
    engine uses, and whether it binds loopback or 0.0.0.0.

    /proc/net/udp and /proc/net/tcp need no binary at all. This test runs
    with a PATH that contains neither ss nor netstat and asserts the
    answers are still captured.

    Mutation-checked: delete the four `show .../proc/net/...` lines and
    this test fails.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()  # empty: no ss, no netstat, no iptables
    fsroot = tmp_path / "fsroot"
    # 0100007F:2454 -- 127.0.0.1 port 9300, byte-reversed hex, exactly the
    # shape the kernel writes.
    write_tree(
        fsroot,
        {
            "proc/net/udp": (
                "  sl  local_address rem_address   st tx_queue rx_queue\n"
                "  512: 0100007F:2454 00000000:0000 07 00000000:00000000\n"
            ),
            "proc/net/tcp": (
                "  sl  local_address rem_address   st tx_queue rx_queue\n"
                "  0: 00000000:0016 00000000:0000 0A 00000000:00000000\n"
            ),
        },
    )
    result, out = run_script(
        tmp_path, bin_dir=bin_dir, extra_env={"MOOG_RECON_FSROOT": str(fsroot)}
    )
    assert result.returncode == 0
    text = (out / "03-sockets.txt").read_text()
    # The binaries really were unavailable -- otherwise this test would be
    # passing via ss and proving nothing about the fallback path.
    assert "(command not available: ss)" in text
    assert "(command not available: netstat)" in text
    # ...and the answer is captured anyway.
    assert "0100007F:2454" in text, "the UDP socket table was not captured"
    assert "00000000:0016" in text, "the TCP socket table was not captured"
    # The operator has to be able to READ that hex without a second trip.
    assert "9300" in text and "127.0.0.1" in text, (
        "no guidance on decoding local_address; the capture is unreadable at 2am"
    )
    assert "0.0.0.0" in text, "nothing explains what a 00000000 local_address means"


def test_runbook_drives_the_cli_rather_than_routing_around_it(tmp_path):
    """COLLECTS. 07-active-probes.txt used raw `python3 -c` snippets calling
    ScClient directly, which BYPASSES every protection the CLI provides --
    including the group-node guard on `set`, whose whole purpose is to stop
    the per-voice go/no-go reading as "voices are not individually
    addressable" when the real problem is a wrong node id.
    """
    result, out = run_script(tmp_path, args=["--out", str(tmp_path / "recon"), "--active"])
    assert result.returncode == 0
    text = (out / "07-active-probes.txt").read_text()

    for command in ("moogone status", "moogone tree", "moogone dump 1", "moogone set"):
        assert command in text, f"the runbook never tells the operator to run `{command}`"
    # The raw-client snippets must be GONE, not merely supplemented.
    assert "python3 -c" not in text or "render_probe_script" in text
    assert "ScClient(t)" not in text, "a raw ScClient snippet still bypasses the CLI"
    assert "UdpTransport(" not in text, "a raw transport snippet still bypasses the CLI"
    # And it must say how to get moogone onto the device at all -- it works
    # (no third-party dependencies) but was documented nowhere.
    assert "scp" in text, "nothing explains how to get moogone onto the device"


def test_runbook_captures_dumposc_to_a_log_file_not_the_scrollback(tmp_path):
    """COLLECTS. `screen -X hardcopy -h` dumps the scrollback buffer, which
    defaults to 100 lines. Thirty seconds of knob motion is plausibly
    thousands, so the operator would get a file that looks complete and
    holds only the tail -- silent truncation of the artifact the spec calls
    the highest-value in the project, the exact failure class already fixed
    for `find` in this same script.

    Also pins the selector spelling: `screen -S <session> -X` is the
    documented form for sending a command to a session. `-r` is the
    reattach flag.
    """
    result, out = run_script(tmp_path, args=["--out", str(tmp_path / "recon"), "--active"])
    assert result.returncode == 0
    text = (out / "07-active-probes.txt").read_text()

    assert "-X logfile" in text, "the runbook never enables screen's disk logging"
    assert "-X log on" in text
    assert "-X log off" in text
    assert "screen -r <session> -X" not in text, "still uses the -r selector spelling"
    assert "screen -S <session> -X" in text

    # Logging must be started BEFORE dump mode is enabled, or the first
    # seconds of the sweep are lost.
    assert text.index("-X log on") < text.index("moogone dump 1"), (
        "logging is enabled after dump mode; the start of the sweep is lost"
    )
    # And hardcopy, if mentioned at all, must be labelled as truncated
    # rather than offered as an equivalent.
    if "hardcopy" in text:
        assert "TRUNCATED" in text or "100 lines" in text, (
            "hardcopy is offered without saying it silently truncates"
        )
