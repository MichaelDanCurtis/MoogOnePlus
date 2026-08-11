"""Every layer, working together, against the mock.

These two tests are taken from the task brief essentially unchanged: both
already prove a genuine round trip (a value set is the value later read
back, and traffic sent is traffic later found in a log) rather than merely
"no exception was raised". See task-14-report.md's discrimination table for
the mutation check confirming that for each assertion here.
"""

from moogone.mock.server import MockScsynth
from moogone.sc.client import ScClient
from moogone.sc.tree import SynthNode
from moogone.transport.udp import UdpTransport


def test_full_stack_query_modify_verify():
    with MockScsynth() as server, UdpTransport("127.0.0.1", server.port) as transport:
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
    with MockScsynth() as server, UdpTransport("127.0.0.1", server.port) as transport:
        client = ScClient(transport)
        client.dump_osc(1)
        server.wait_for_message("/dumpOSC", timeout=1.0)
        client.query_tree()
        assert any(m.address == "/g_queryTree" for m in server.dump_log)
