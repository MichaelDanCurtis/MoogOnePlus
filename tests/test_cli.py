"""The `moogone` console script, exercised as a real subprocess.

Every test here launches `python -m moogone.cli` as a genuine child
process (never imports moogone.cli's internals directly) because the
thing under test IS the process boundary: argv parsing, exit codes, and
what lands on stdout/stderr. See task-14-report.md for the per-test
discrimination check and the mutation used to verify each one.
"""

import ast
import json
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from moogone.mock.server import MockScsynth
from moogone.osc import Float64, OscMessage, decode

CLI_SOURCE = Path("src/moogone/cli.py")


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "moogone.cli", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _find_node(tree: dict, node_id: int) -> dict | None:
    """Depth-first search of a moogone.cli tree --json dict for node_id."""
    if tree["node_id"] == node_id:
        return tree
    for child in tree.get("children", []):
        found = _find_node(child, node_id)
        if found is not None:
            return found
    return None


def _fake_status_reply_bytes() -> bytes:
    return OscMessage(
        "/status.reply",
        [1, 0, 0, 1, 0, 0.02, 0.05, Float64(48000.0), Float64(48000.03)],
    ).encode()


def _free_udp_port() -> int:
    """A port number the OS just confirmed was free, with nothing bound
    to it anymore -- not a fixed low port like 1, whose behavior (bind
    permission, whether anything happens to be listening) isn't the same
    on every machine this suite runs on. See
    test_transport_tunnel.py::test_connecting_to_a_dead_port_raises_with_guidance
    for the same pattern used earlier in this project.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


# --------------------------------------------------------------- baseline
# status / tree / dump / set, each proving a genuine round trip through
# the mock rather than merely "the process exited zero".


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
    # Strengthened over the brief's version, which only checked the
    # root's node_id == 0 -- true of the mock tree regardless of whether
    # children, defnames, or controls actually survive the walk-to-dict
    # conversion. This walks into a real synth node and checks a real
    # control value, so a bug that dropped children or controls during
    # JSON serialisation would be caught here.
    with MockScsynth() as server:
        result = _run("tree", "--port", str(server.port), "--json")
        assert result.returncode == 0, result.stderr
        tree = json.loads(result.stdout)
        assert tree["node_id"] == 0
        reverb = _find_node(tree, 1001)
        assert reverb is not None, "node 1001 missing from the JSON tree"
        assert reverb["defname"] == "moog_fx_reverb"
        assert reverb["controls"]["in_trim"] == 1.0


def test_set_changes_a_control():
    # Defect fix: the brief's version asserted "3.0" in the plain tree
    # dump's text -- a mention-grep that would pass even if `set` wrote
    # to the wrong node or the wrong control, since 1001 (moog_fx_reverb)
    # and 1000 (moog_fx_delay) both start with an in_trim of 1.0. This
    # walks the JSON tree to the exact node and checks the exact control,
    # and additionally checks a sibling node and a sibling control were
    # NOT touched, so a "right value, wrong place" bug can't slip through
    # either.
    with MockScsynth() as server:
        port = str(server.port)
        assert _run("set", "1001", "in_trim=3.0", "--port", port).returncode == 0

        result = _run("tree", "--port", port, "--json")
        tree = json.loads(result.stdout)
        reverb = _find_node(tree, 1001)
        delay = _find_node(tree, 1000)

        assert reverb["controls"]["in_trim"] == 3.0
        assert delay["controls"]["in_trim"] == 1.0  # sibling node untouched
        # pytest.approx: control values travel the wire as OSC float32
        # (see osc/message.py -- only Float64-wrapped args encode as
        # doubles), so 0.3 round-trips as 0.300000011920929. Matches the
        # pytest.approx convention already used for this in
        # test_sc_control.py.
        assert reverb["controls"]["mix"] == pytest.approx(0.3)  # sibling control untouched


def test_set_on_unknown_node_is_a_clean_error_not_a_false_success():
    # Found in self-review, not one of the brief's four flagged defects:
    # /n_set is fire-and-forget and real scsynth (and the mock, matching
    # it) silently no-ops on an unknown node id rather than replying
    # /fail -- see ScClient.n_set's own docstring. Before this fix, the
    # CLI's `set` command took that at face value and printed
    # "set 999999: {...}" regardless of whether the node existed, exit
    # code 0. That specific command is the September checklist's
    # per-voice go/no-go step ("moogone set <voice-node> <param>=<value>,
    # listen. One voice changes, or the project is dead.") -- a stale or
    # mistyped node id there would read as "control is impossible", not
    # "wrong node id", with no error to say otherwise.
    with MockScsynth() as server:
        result = _run("set", "999999", "in_trim=3.0", "--port", str(server.port))
        assert result.returncode != 0
        assert "Traceback" not in result.stderr, f"unhandled exception: {result.stderr!r}"
        # "Node not found" is /n_query's own /fail message (see
        # mock/server.py's /n_query handler); not the node id itself,
        # which the server never echoes back on this path.
        assert "not found" in result.stderr.lower()


def test_set_rejects_a_control_literally_named_node_id():
    # Found in self-review: client.n_set(node_id, **controls) has node_id
    # as a fixed positional parameter. A control pair spelled
    # node_id=VALUE, passed through unchecked into **controls, collides
    # with it as a keyword argument -- TypeError: n_set() got multiple
    # values for argument 'node_id' -- which was not in the CLI's except
    # tuple and would have crashed with a traceback.
    with MockScsynth() as server:
        result = _run("set", "1001", "node_id=5", "--port", str(server.port))
        assert result.returncode != 0
        assert "Traceback" not in result.stderr, f"unhandled exception: {result.stderr!r}"
        assert "node_id" in (result.stdout + result.stderr)


def test_tree_json_stringifies_non_finite_control_values():
    # Found in self-review: json.dumps emits the non-standard NaN token
    # by default rather than raising, so a control value that legitimately
    # goes non-finite on a live audio engine (rare, but real) would
    # previously have produced a captures/tree.json a strict JSON parser
    # elsewhere in the toolchain could choke on. float("nan") parses
    # successfully in Python, so this is reachable through `set` for
    # real, not just constructible by hand.
    with MockScsynth() as server:
        port = str(server.port)
        assert _run("set", "1001", "in_trim=nan", "--port", port).returncode == 0
        result = _run("tree", "--port", port, "--json")
        assert result.returncode == 0, result.stderr
        tree = json.loads(result.stdout)  # would already raise on genuinely broken JSON
        reverb = _find_node(tree, 1001)
        # A bare NaN float would decode back via json.loads as Python's
        # float("nan") (json.loads accepts the same non-standard tokens
        # json.dumps emits), which is never == the string "nan" -- so
        # this only passes if the value was actually stringified before
        # serialising, not merely round-tripped through a lenient parser
        # on both ends.
        assert reverb["controls"]["in_trim"] == "nan"


def test_dump_sets_server_mode():
    # The CLI's dump subcommand wasn't covered by the brief's test file at
    # all. Proves the mode argument actually reaches the server's state,
    # not just that the process exits zero.
    with MockScsynth() as server:
        result = _run("dump", "1", "--port", str(server.port))
        assert result.returncode == 0, result.stderr
        server.wait_for_message("/dumpOSC", timeout=1.0)
        assert server.dump_mode == 1


# ------------------------------------------------------------ error paths


def test_unreachable_server_exits_nonzero_with_a_useful_message():
    # Defect fix: the brief used --port 1, assuming a fixed low port is
    # always unbound and always fails the same way. It might need root to
    # even attempt the bind, might be firewalled differently, or might
    # simply have something listening on an unusual CI box. Binding an
    # ephemeral port and closing it gives a port the OS just confirmed
    # was free, deterministically, on any machine.
    #
    # Also strengthened beyond the brief's own assertion, which checked
    # only "no /status.reply" in combined stdout+stderr. Mutation-tested
    # while writing this test: removing ScTimeout from cli.py's except
    # tuple still left that substring present, because Python's default
    # traceback for an uncaught ScTimeout prints "ScTimeout: no
    # /status.reply within ...s" as its last line -- so the original
    # assertion could not tell a clean handled message apart from a raw
    # crash that happens to echo the same words. The explicit
    # "Traceback" absence check closes that gap.
    dead_port = _free_udp_port()
    result = _run("status", "--port", str(dead_port), "--timeout", "0.2")
    assert result.returncode != 0
    assert "Traceback" not in result.stderr, f"unhandled exception: {result.stderr!r}"
    assert "no /status.reply" in (result.stdout + result.stderr)


def test_timeout_flag_shortens_the_wait_for_tree():
    # tree threads --timeout through to query_tree(timeout=...); this
    # proves that wiring with a wall-clock check. If --timeout were
    # silently ignored, this would take query_tree's own 2.0s default
    # instead of the 0.2s requested here.
    dead_port = _free_udp_port()
    start = time.monotonic()
    result = _run("tree", "--port", str(dead_port), "--timeout", "0.2")
    elapsed = time.monotonic() - start
    assert result.returncode != 0
    assert "no /g_queryTree.reply" in (result.stdout + result.stderr)
    assert elapsed < 1.5, f"took {elapsed:.2f}s -- --timeout doesn't appear wired to tree"


def test_timeout_flag_shortens_the_wait_for_status():
    # Found in self-review: ScClient.status() originally hardcoded its
    # own reply timeout with no parameter to override it, so --timeout
    # was silently a no-op for status specifically -- exactly the
    # September checklist's first go/no-go step ("moogone status.
    # Confirms las-sc speaks SuperCollider. If this fails, everything
    # downstream needs rethinking"), where an operator explicitly asking
    # for a fast failure via --timeout deserves to get one. Fixed by
    # adding an optional timeout parameter to ScClient.status() itself
    # (src/moogone/sc/client.py); this is the wall-clock proof, mirroring
    # test_timeout_flag_shortens_the_wait_for_tree above.
    dead_port = _free_udp_port()
    start = time.monotonic()
    result = _run("status", "--port", str(dead_port), "--timeout", "0.2")
    elapsed = time.monotonic() - start
    assert result.returncode != 0
    assert "no /status.reply" in (result.stdout + result.stderr)
    assert elapsed < 1.5, f"took {elapsed:.2f}s -- --timeout doesn't appear wired to status"


def test_connect_flag_before_the_subcommand_gets_a_clear_hint():
    # Found in self-review: this project's single-registration argparse
    # design (see _build_connect_flags's docstring) requires connect
    # flags after the subcommand. Typed the other way around, argparse's
    # own default error blames the port number and never mentions
    # ordering ("argument command: invalid choice: '1234'") -- reproduced
    # and confirmed against this exact CLI before writing the fix. This
    # proves the friendlier, order-aware hint fires instead.
    result = _run("--port", "1234", "status")
    assert result.returncode != 0
    assert "invalid choice" not in result.stderr
    assert "--port" in result.stderr
    assert "after" in result.stderr.lower()


def test_reply_from_unexpected_sender_is_a_clean_error_not_a_crash():
    # Defect fix: UdpTransport.recv() raises ValueError when a datagram
    # arrives from a sender other than the one configured -- a real
    # possibility on a shared network, and the very diagnostic that would
    # reveal the engine replying from an unexpected port. The original
    # except tuple (ScError, ScTimeout, ConnectionError) didn't include
    # it, so this exact scenario surfaced as an unhandled traceback
    # instead of the clean message the CLI exists to provide.
    #
    # This reproduces the scenario for real -- a genuine ValueError raised
    # by genuine transport code reached by a real subprocess -- rather
    # than asserting on the except tuple's contents directly: "decoy" is
    # what --port targets (nothing ever replies from it), and "impostor"
    # (bound to a different port, guaranteed by the OS since decoy's port
    # is already taken) sends the CLI a datagram once it knows the CLI's
    # return address.
    decoy = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    decoy.bind(("127.0.0.1", 0))
    decoy_port = decoy.getsockname()[1]
    impostor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    impostor.bind(("127.0.0.1", 0))

    proc = None
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "moogone.cli",
                "status", "--host", "127.0.0.1", "--port", str(decoy_port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        decoy.settimeout(5.0)
        _, cli_addr = decoy.recvfrom(4096)  # the CLI's own /status request
        impostor.sendto(b"not from the port you configured", cli_addr)
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
        decoy.close()
        impostor.close()

    assert proc.returncode == 1, f"stdout={stdout!r} stderr={stderr!r}"
    assert "Traceback" not in stderr, f"unhandled exception, not a clean error: {stderr!r}"
    assert "unexpected sender" in (stdout + stderr)


# --------------------------------------------------------------- --tunnel


def test_tunnel_flag_connects_via_the_local_forward_port():
    # With --tunnel and no --local-port, --port doubles as the local
    # forward port (the documented default). A bare TCP listener stands
    # in for the local end of `ssh -L`: the CLI must speak TCP to it (not
    # UDP -- nothing here binds a UDP socket at all) and decode a real
    # reply arriving over that connection.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.settimeout(5.0)
    port = listener.getsockname()[1]

    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "moogone.cli", "status", "--tunnel", "--port", str(port)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        conn, _ = listener.accept()
        try:
            conn.settimeout(5.0)
            conn.recv(4096)
            conn.sendall(_fake_status_reply_bytes())
        finally:
            conn.close()
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
        listener.close()

    assert proc.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"
    assert "48000" in stdout


def test_tunnel_local_port_is_independent_of_port():
    # The disambiguation this task asked for, proven behaviorally: --port
    # and --local-port must name genuinely different sockets. In a real
    # deployment --port is the engine's UDP port on the device and
    # --local-port is the Mac-side end of the ssh -L forward -- reusing
    # one number for both is a coincidence, not a guarantee, and is
    # exactly the confusion flagged for this task. Two listeners, two
    # different ports: --tunnel must reach only the one named by
    # --local-port, and never the one named by --port.
    decoy = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    decoy.bind(("127.0.0.1", 0))
    decoy.listen(1)
    decoy.settimeout(1.0)
    decoy_port = decoy.getsockname()[1]

    tunnel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tunnel.bind(("127.0.0.1", 0))
    tunnel.listen(1)
    tunnel.settimeout(5.0)
    tunnel_port = tunnel.getsockname()[1]
    assert tunnel_port != decoy_port  # degenerate test setup otherwise

    proc = None
    try:
        proc = subprocess.Popen(
            [
                sys.executable, "-m", "moogone.cli", "status", "--tunnel",
                "--port", str(decoy_port), "--local-port", str(tunnel_port),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        conn, _ = tunnel.accept()
        try:
            conn.settimeout(5.0)
            conn.recv(4096)
            conn.sendall(_fake_status_reply_bytes())
        finally:
            conn.close()
        stdout, stderr = proc.communicate(timeout=10)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.communicate()
        tunnel.close()

    assert proc.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"
    assert "48000" in stdout

    with pytest.raises((TimeoutError, OSError)):
        decoy.accept()  # nothing should ever have connected here
    decoy.close()


def test_help_text_disambiguates_port_from_local_port():
    # MENTION-style, and weaker than that label alone suggests: every
    # word asserted below lives in TUNNEL_EPILOG, a plain string constant
    # attached to the top-level parser -- self-review mutation-confirmed
    # that deleting all five connect flags from the parser entirely
    # (a completely broken CLI) still leaves this test green, because the
    # epilog text never references the parser's actual argument objects.
    # This proves the disambiguating vocabulary this task asked for
    # ("make the help text ... say which port is meant") is present in
    # --help's output and nothing more -- not that the flags it describes
    # exist, work, or match what it says. The behavioral proof that the
    # two flags actually connect to different places lives in
    # test_tunnel_local_port_is_independent_of_port above; that test
    # would fail if --local-port's plumbing broke even if every word here
    # stayed byte-for-byte intact.
    result = _run("--help")
    assert result.returncode == 0
    text = result.stdout
    assert "--local-port" in text
    lowered = text.lower()
    assert "engine" in lowered
    assert "ssh" in lowered
    assert "socat" in lowered
    assert "bridge" in lowered


# ---------------------------------------------------------- mock subcommand


def test_mock_subcommand_serves_until_interrupted_then_exits_cleanly():
    # Defect fix (behavioral half): the brief's mock subcommand busy-waited
    # on `while True: import time; time.sleep(0.5)`. This proves the
    # replacement still does its actual job -- serve real SC protocol
    # requests -- and still stops cleanly on SIGINT. -u forces stdout
    # unbuffered so the startup line is observable before we act on it
    # (stdout is block-buffered, not line-buffered, once it's a pipe
    # rather than a tty).
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "moogone.cli", "mock", "--mock-port", "0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        startup_line = proc.stdout.readline()
        match = re.search(r"127\.0\.0\.1:(\d+)", startup_line)
        assert match, f"no port found in startup line {startup_line!r}"
        port = int(match.group(1))

        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.settimeout(5.0)
            probe.sendto(OscMessage("/status", []).encode(), ("127.0.0.1", port))
            data, _ = probe.recvfrom(4096)
            assert decode(data).address == "/status.reply"
        finally:
            probe.close()

        proc.send_signal(signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=5)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    assert proc.returncode == 0, f"stdout={stdout!r} stderr={stderr!r}"


def test_mock_subcommand_reports_a_busy_port_cleanly():
    # Found in self-review: `if args.command == "mock": return
    # _run_mock(args)` originally sat above main()'s try/except, so
    # MockScsynth(port)'s bind failure (OSError: Address already in use)
    # propagated as a raw traceback -- the same class of gap ValueError
    # covers for the other four commands. Realistic on real hardware
    # specifically: an operator instinctively running `moogone mock`
    # while on-device, where port 9300 already belongs to las-sc itself,
    # would hit exactly this.
    blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    blocker.bind(("127.0.0.1", 0))
    busy_port = blocker.getsockname()[1]
    try:
        result = _run("mock", "--mock-port", str(busy_port))
        assert result.returncode != 0
        assert "Traceback" not in result.stderr, f"unhandled exception: {result.stderr!r}"
    finally:
        blocker.close()


# ------------------------------------------------------------- structural


def test_cli_module_has_only_top_level_imports():
    # Defect fix (structural half): "module-level imports only" is a
    # constraint the rest of the project follows; the brief's own mock
    # subcommand violated it (`import time` inside the wait loop, so it
    # re-ran the import machinery every 0.5s). Parses cli.py's own source
    # and checks that every Import/ImportFrom node found anywhere in the
    # tree is also one of the module's direct top-level statements -- so
    # a nested import anywhere in this file, not just in the exact spot
    # the original defect was in, fails this.
    tree = ast.parse(CLI_SOURCE.read_text())
    top_level = {node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))}
    nested = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node not in top_level
    ]
    assert not nested, [ast.dump(n) for n in nested]
