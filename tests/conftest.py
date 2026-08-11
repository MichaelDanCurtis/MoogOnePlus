import pytest

from moogone.mock.server import MockScsynth
from moogone.sc.client import ScClient
from moogone.transport.udp import UdpTransport


@pytest.fixture
def mock_server():
    server = MockScsynth()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def client(mock_server):
    transport = UdpTransport("127.0.0.1", mock_server.port)
    yield ScClient(transport)
    transport.close()
