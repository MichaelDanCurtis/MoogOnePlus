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
    """
    for token in argv:
        bare = token.split("=", 1)[0]
        if bare in _SUBCOMMANDS:
            return None  # subcommand already seen: normal usage
        if bare in _CONNECT_FLAGS:
            return (
                f"{bare} must come after the subcommand, not before it. "
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
    both, `moogone --port 1234 status` parses to port=9300, the default,
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
        default=9300,
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
        "tree, and set. dump never waits for a reply at all, so this has "
        "no effect there.",
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
    dump.add_argument(
        "mode", type=int, choices=[0, 1, 2, 3], help="0=off 1=parsed 2=hex 3=both"
    )

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
    print(f"mock scsynth listening on 127.0.0.1:{server.port}  (ctrl-c to stop)")
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
                    if name == "node_id":
                        # client.n_set(node_id, **controls) has node_id as
                        # a fixed positional parameter; a control pair
                        # spelled node_id=VALUE would collide with it as
                        # a keyword argument below (TypeError: got
                        # multiple values for argument 'node_id') if let
                        # through unchecked.
                        parser.error("'node_id' is not a settable control -- it names the node itself")
                    controls[name] = float(value)
                # /n_set is fire-and-forget and silently no-ops on an
                # unknown node id (matching real scsynth, which logs and
                # moves on -- see ScClient.n_set's docstring). Querying
                # first turns a stale or mistyped node id into a clean
                # error instead of a false "set N: {...}" success message
                # -- this is the September checklist's per-voice go/no-go
                # step, where that false positive would read as "control
                # is impossible" instead of "wrong node id".
                client.n_query(args.node_id, timeout=args.timeout)
                client.n_set(args.node_id, **controls)
                client.sync(timeout=args.timeout)
                print(f"set {args.node_id}: {controls}")
    except (ScError, ScTimeout, OSError, ValueError) as exc:
        # OSError (which ScTimeout and ConnectionError both already are,
        # as subclasses -- kept explicit above for readability) covers
        # any other low-level socket/environment failure, such as mock's
        # bind-in-use case above. ValueError covers UdpTransport.recv()'s
        # unexpected-sender check -- a real possibility on a shared
        # network, and the diagnostic that would reveal the engine
        # replying from a port other than the one configured -- and
        # float(value) above, on a non-numeric control value. Every one
        # of these becomes a clean exit-1 message here, not a traceback,
        # which is this boundary's entire job.
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
