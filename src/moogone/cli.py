"""Command-line entry point.

In front of the synth you want to type one command, not compose a Python
session. All imports are module-level, including the ones only the `mock`
subcommand needs -- none of this project's modules are expensive enough to
import to justify deferring them, and a deferred import re-run on every
loop iteration is exactly the shape of a defect this project has already
shipped once (see the `mock` subcommand below and its docstring).
"""

import argparse
import dataclasses
import json
import math
import sys
import threading

from .mock.server import MockScsynth
from .sc.client import ScClient, ScError, ScTimeout
from .sc.tree import SynthNode
from .transport.tunnel import TunnelTransport
from .transport.udp import UdpTransport


class CliError(RuntimeError):
    """The CLI itself refuses an operation, based on live server state it
    already has in hand -- distinct from ScError (the server replied
    /fail) and ScTimeout (no reply arrived in time). Used for exactly one
    case today: refusing /n_set on a node confirmed to be a group, which
    scsynth (and the mock matching it) would otherwise silently no-op
    with no error at all. This is the same false-success shape as an
    unknown node id (which n_query's own /fail already turns into
    ScError) -- one node type over, and the only one n_query answers
    successfully for while still being a write /n_set cannot honor.
    """


# --tunnel routes through three different ports, not one, and reusing
# --port's number for the wrong one is the single easiest way to lose an
# evening on this project (see moogone.transport.tunnel's module
# docstring). Spelled out in full here, in the one place an operator
# actually looks at 2am: `moogone --help`.
TUNNEL_EPILOG = """\
--tunnel topology (three different ports, not one):

  1. You start, in another terminal, the local half of the forward:
       ssh -N -L <local-port>:127.0.0.1:<bridge-port> root@<device-ip>
     This opens <local-port> on THIS Mac. moogone does not start this
     for you -- see moogone.transport.tunnel.build_ssh_command.
  2. On the device, socat bridges <bridge-port> (TCP) to the engine's
     real UDP port:
       socat TCP-LISTEN:<bridge-port>,reuseaddr,fork UDP:127.0.0.1:<engine-port>
     Also not started by moogone -- see
     moogone.transport.tunnel.build_remote_bridge_command.
  3. moogone --tunnel then connects to 127.0.0.1:<local-port> from step 1
     and nothing else. It never touches <bridge-port> or the engine's
     port directly -- ssh and socat do that hop for it.

  --port         the engine's real OSC port on --host (las-sc). Used
                 directly for a plain UDP connection when --tunnel is
                 not given. With --tunnel, this ALSO doubles as the
                 default --local-port -- correct only if step 1's ssh
                 command happened to use matching numbers.
  --local-port   step 1's <local-port>: the Mac-side end of the ssh
                 forward. Only meaningful with --tunnel. This is NOT
                 the engine's port and NOT the socat bridge port --
                 mixing these up sends packets nowhere useful.

If socat is absent from the device, do not fight this: run on-box with a
plain UDP connection (no --tunnel) instead.
"""


def _open_transport(args):
    if args.tunnel:
        local_port = args.local_port if args.local_port is not None else args.port
        return TunnelTransport(local_port, host=args.host)
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


def _json_safe(value):
    """json.dumps emits the non-standard NaN/Infinity/-Infinity tokens by
    default rather than raising -- valid Python, but not portable JSON,
    and many strict parsers (including non-Python ones an operator might
    pipe captures/tree.json through later) choke on them. A live audio
    engine control blowing up to a non-finite value is rare but real, and
    this capture is meant to be irreplaceable hardware data, so losing
    the whole file to allow_nan=False is worse than stringifying just the
    values that need it.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)  # "nan", "inf", "-inf"
    return value


def _tree_to_dict(node) -> dict:
    if isinstance(node, SynthNode):
        controls = {name: _json_safe(v) for name, v in node.controls.items()}
        return {"node_id": node.node_id, "defname": node.defname, "controls": controls}
    return {"node_id": node.node_id, "children": [_tree_to_dict(c) for c in node.children]}


_CONNECT_FLAGS = ("--host", "--port", "--tunnel", "--local-port", "--timeout")
_SUBCOMMANDS = ("status", "tree", "dump", "set", "mock")


def _flag_order_hint(argv: list[str]) -> str | None:
    """A connect flag only works after the subcommand -- `moogone status
    --port 1234`, not `moogone --port 1234 status` -- because of the
    parents= structure explained in _build_connect_flags's docstring.
    Typed the other way around, this project's code never even runs:
    argparse rejects it unaided, but by default with a message that
    blames the port number and never mentions ordering, e.g. "argument
    command: invalid choice: '1234'" -- confusing for a mistake this
    easy to make. Scanned for here, before argparse gets a chance to
    produce that message.

    Matches argparse's own unambiguous-prefix abbreviation too (--po for
    --port), not just the exact spelling -- a bare string-equality check
    let an abbreviated flag straight through to the same confusing
    argparse message this exists to prevent. A token that's a genuine
    --help abbreviation (e.g. --h) is deliberately excluded: --help is
    registered on every parser, top-level included, so argparse resolves
    it correctly regardless of where it appears, and nothing here should
    override that.
    """
    for token in argv:
        bare = token.split("=", 1)[0]
        if bare in _SUBCOMMANDS:
            return None  # subcommand already seen: normal usage
        if not bare.startswith("--") or len(bare) <= 2:
            continue
        if "--help".startswith(bare):
            continue  # a genuine --help abbreviation; not our concern
        matches = [flag for flag in _CONNECT_FLAGS if flag.startswith(bare)]
        if not matches:
            continue
        detail = bare if matches == [bare] else f"{bare} (matching {'/'.join(matches)})"
        return (
            f"{detail} must come after the subcommand, not before it. "
            f"Try `moogone <command> {bare} ...`."
        )
    return None


def _build_connect_flags() -> argparse.ArgumentParser:
    """A parents= template for the flags shared by every subcommand that
    connects somewhere (status/tree/dump/set -- not mock, which hosts
    instead of connecting).

    These live ONLY here, added to each subcommand via parents=, and
    deliberately NOT also added to the top-level parser. argparse
    subparsers parse into a fresh sub-namespace and then copy every one
    of its attributes onto the parent namespace -- so a flag defined at
    BOTH levels lets the subparser's own default silently overwrite a
    value the top-level parser already parsed. Verified live against this
    project's argparse before choosing this structure: with --port on
    both, `moogone --port 1234 status` parses to port=57110, the default,
    not the 1234 the operator typed, with no warning that it happened.
    One definition avoids that trap entirely, and it also matches the
    invocation shape this project's tests (and the task brief) use:
    `moogone status --port 1234`, subcommand first.
    """
    connect = argparse.ArgumentParser(add_help=False)
    connect.add_argument(
        "--host",
        default="127.0.0.1",
        help="address to connect to: the engine's host for a direct UDP "
        "connection, or the machine running the ssh -L forward for "
        "--tunnel (usually 127.0.0.1 either way)",
    )
    connect.add_argument(
        "--port",
        type=int,
        # This tool speaks the SuperCollider server protocol, so its default is
        # scsynth's port. 9300 -- the old default, taken from a public writeup -- is
        # `las-sc`, a DIFFERENT service on the same box: the voice-card controller,
        # speaking a Moog-specific OSC dialect and bound to loopback, so unreachable
        # from another machine even when you do want it. Measured on hardware
        # 2026-09-03: /proc/net/udp lists 00000000:DF16 (0.0.0.0:57110) and /status
        # answers there, while queries to 9300 timed out with no packet arriving at
        # all. See docs/MOOG-ONE-INTERNALS.md, "A correction worth inheriting".
        default=57110,
        help="the engine's real OSC port on --host. Used directly for UDP. "
        "With --tunnel this also becomes the default --local-port -- see "
        "`moogone --help`'s epilog for why that is only sometimes what "
        "you want.",
    )
    connect.add_argument(
        "--tunnel",
        action="store_true",
        help="connect via the local end of an ssh -L forward (see "
        "--local-port) instead of a direct UDP connection. ssh -L and the "
        "device-side socat bridge must already be running -- this does "
        "not start either of them. See `moogone --help`'s epilog.",
    )
    connect.add_argument(
        "--local-port",
        type=int,
        default=None,
        metavar="PORT",
        help="local TCP port of the ssh -L forward. Only used with "
        "--tunnel, and NOT the engine's port. Defaults to --port.",
    )
    connect.add_argument(
        "--timeout",
        type=float,
        default=2.0,
        help="how long to wait for a reply, in seconds. Applies to status, "
        "tree, set, and dump (which follows the fire-and-forget /dumpOSC "
        "with a /sync, so a server that rejects it is caught rather than "
        "reported as success).",
    )
    return connect


def _build_parser() -> argparse.ArgumentParser:
    connect = _build_connect_flags()

    parser = argparse.ArgumentParser(
        prog="moogone",
        description=__doc__,
        epilog=TUNNEL_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", parents=[connect], help="query server state (run this first)")

    tree = sub.add_parser("tree", parents=[connect], help="dump the live node graph")
    tree.add_argument("--json", action="store_true", help="machine-readable output")

    dump = sub.add_parser("dump", parents=[connect], help="set dumpOSC mode on the server")
    dump.add_argument("mode", type=int, choices=[0, 1, 2, 3], help="0=off 1=parsed 2=hex 3=both")

    setter = sub.add_parser("set", parents=[connect], help="set controls on a node")
    setter.add_argument("node_id", type=int, help="node id, e.g. from `moogone tree`")
    setter.add_argument(
        "controls", nargs="+", metavar="NAME=VALUE", help="one or more control=value pairs"
    )

    mock = sub.add_parser("mock", help="run a mock scsynth for development")
    mock.add_argument(
        "--mock-port",
        type=int,
        default=9300,
        help="UDP port to bind for the mock server (0 = pick any free port)",
    )

    return parser


def _run_mock(args) -> int:
    server = MockScsynth(args.mock_port)
    server.start()
    # flush=True: with --mock-port 0 this line is the ONLY place the
    # kernel-assigned port is reported, and Python block-buffers stdout
    # whenever it is not a tty. Redirected to a log (`moogone mock
    # --mock-port 0 > mock.log &`), the line would sit in an unflushed
    # buffer until the process exits -- so the port never appears while
    # the server is running, which is the entire window in which anyone
    # needs it.
    print(
        f"mock scsynth listening on 127.0.0.1:{server.port}  (ctrl-c to stop)",
        flush=True,
    )
    try:
        # Block until interrupted, without polling. threading.Event.wait()
        # with no timeout sleeps the thread until something sets the
        # event or a signal arrives -- nothing here ever calls .set(), so
        # KeyboardInterrupt is the only way out, and it gets there without
        # the wake-every-N-seconds busy loop (and its per-iteration
        # `import time`) this replaced.
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    hint = _flag_order_hint(sys.argv[1:] if argv is None else argv)
    if hint is not None:
        print(f"error: {hint}", file=sys.stderr)
        return 2

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "mock":
            # Inside the try: MockScsynth(...)'s bind can raise OSError
            # (e.g. "Address already in use") before _run_mock reaches
            # its own KeyboardInterrupt handling -- on-device this is the
            # likely case, since real hardware's port 9300 already
            # belongs to las-sc. Without this, that specific failure was
            # the one command left that still crashed instead of
            # producing the clean, actionable message this boundary
            # exists to provide -- the same class of gap ValueError below
            # closes for the other four commands.
            return _run_mock(args)
        with _open_transport(args) as transport:
            client = ScClient(transport)
            if args.command == "status":
                status = client.status(timeout=args.timeout)
                for field in dataclasses.fields(status):
                    print(f"{field.name}: {getattr(status, field.name)}")
            elif args.command == "tree":
                root = client.query_tree(timeout=args.timeout)
                print(
                    json.dumps(_tree_to_dict(root), indent=2) if args.json else _format_tree(root)
                )
            elif args.command == "dump":
                # dump_osc follows the fire-and-forget /dumpOSC with a
                # /sync, so a server that rejects the command raises
                # ScError here instead of letting this print a success
                # line over a /fail nobody read. See ScClient.dump_osc.
                client.dump_osc(args.mode, timeout=args.timeout)
                print(f"dumpOSC mode set to {args.mode}")
            elif args.command == "set":
                controls = {}
                for pair in args.controls:
                    if "=" not in pair:
                        parser.error(f"expected NAME=VALUE, got {pair!r}")
                    name, value = pair.split("=", 1)
                    if name == "node_id":
                        # client.n_set(node_id, **controls) has node_id as
                        # a fixed positional parameter; a control pair
                        # spelled node_id=VALUE would collide with it as
                        # a keyword argument below (TypeError: got
                        # multiple values for argument 'node_id') if let
                        # through unchecked.
                        parser.error(
                            "'node_id' is not a settable control -- it names the node itself"
                        )
                    try:
                        controls[name] = float(value)
                    except ValueError:
                        # Bare float() doesn't say which of potentially
                        # several NAME=VALUE pairs on the command line was
                        # at fault -- naming it here, not just the value,
                        # matters most exactly when there's more than one
                        # pair to search through.
                        raise ValueError(
                            f"control {name!r}: value {value!r} is not a number"
                        ) from None
                # n_query first, closing the same false-success shape for
                # two different node states /n_set itself can't
                # distinguish, since it never acknowledges anything:
                #   - an unknown node id raises ScError here (from
                #     n_query's own /fail), rather than silently
                #     no-opping through to a false "sent" message -- the
                #     September checklist's per-voice go/no-go step,
                #     where that must not read as "control is impossible"
                #     instead of "wrong node id".
                #   - a node that exists but is a GROUP, not a synth, is
                #     caught below via is_group and refused explicitly:
                #     scsynth (and this mock, matching it -- see
                #     mock/server.py's _apply_n_set, which only ever
                #     mutates a SynthNode's controls) applies /n_set to a
                #     group with no effect and no /fail either, so only
                #     n_query's own is_group flag, not the write itself,
                #     can catch it before the write is even sent.
                node_info = client.n_query(args.node_id, timeout=args.timeout)
                if node_info.is_group:
                    raise CliError(
                        f"node {args.node_id} is a group, not a synth -- /n_set "
                        f"silently no-ops on groups (scsynth included), so nothing was sent"
                    )
                client.n_set(args.node_id, **controls)
                # The write has now left the socket. /n_set is
                # fire-and-forget: scsynth never acknowledges it, and
                # nothing downstream can un-send it. /sync below is a
                # CONFIRMATION step, not a precondition -- so a /sync that
                # times out must not be reported as if the write failed.
                #
                # Verified against a server with no /sync at all: the
                # device applied the write, then this command printed
                # "error: no /synced within 2.0s" and exited 1, never
                # printing the "sent" line. An operator holding a note
                # sees "error", hears the change they were listening for,
                # and has to decide which to believe -- and the September
                # checklist's per-voice go/no-go is exactly this command.
                # "Error" there yields "voices are not individually
                # addressable, project dead", which is the same wrong
                # conclusion the group-node guard above exists to prevent,
                # reached through a different door.
                #
                # Only ScTimeout is caught, and only around sync(): an
                # ScError (the server actively replied /fail to something)
                # is a real refusal and still propagates to the handler
                # below.
                try:
                    client.sync(timeout=args.timeout)
                except ScTimeout as exc:
                    # Deliberately exit 0. The command's job -- send the
                    # write -- completed; only the optional confirmation
                    # did not. A nonzero exit here would train the
                    # operator (and any script) to read a trimmed-/sync
                    # server as "control is impossible". The wording
                    # carries the uncertainty instead, on both streams so
                    # it survives stdout being redirected to a capture
                    # file.
                    print(
                        f"warning: sent to node {args.node_id}, but delivery is "
                        f"UNCONFIRMED -- {exc}. /n_set is fire-and-forget and this "
                        f"server did not answer the /sync that would have confirmed "
                        f"it was processed; the write may well have landed.",
                        file=sys.stderr,
                    )
                    print(
                        f"sent to node {args.node_id} (synth), UNCONFIRMED: {controls} "
                        f"-- run `moogone tree` to check whether it took"
                    )
                    return 0
                # "sent", not "set": /n_set is fire-and-forget and
                # scsynth never acknowledges it. n_query above confirms
                # the node exists and is a synth; sync confirms the
                # server has processed everything up to and including the
                # write. Neither confirms the specific value actually
                # took -- that's the honest limit of what this command
                # can know without a second query, so it doesn't claim
                # more than that.
                print(
                    f"sent to node {args.node_id} (synth): {controls} -- "
                    f"run `moogone tree` to confirm it took"
                )
    except (ScError, ScTimeout, OSError, ValueError, CliError) as exc:
        # OSError (which ScTimeout and ConnectionError both already are,
        # as subclasses -- kept explicit above for readability) covers
        # any other low-level socket/environment failure, such as mock's
        # bind-in-use case above. ValueError covers UdpTransport.recv()'s
        # unexpected-sender check -- a real possibility on a shared
        # network, and the diagnostic that would reveal the engine
        # replying from a port other than the one configured -- and
        # float(value) above, on a non-numeric control value. CliError
        # covers set's own refusal to write to a group node. Every one
        # of these becomes a clean exit-1 message here, not a traceback,
        # which is this boundary's entire job.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
