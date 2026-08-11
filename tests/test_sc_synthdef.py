import pytest

from moogone.sc.client import ScError

# A real .scsyndef begins with the magic bytes "SCgf".
VALID_SYNTHDEF = b"SCgf\x00\x00\x00\x02" + b"\x00" * 32
INVALID_SYNTHDEF = b"NOPE" + b"\x00" * 32


def test_d_recv_loads_a_synthdef(client, mock_server):
    client.d_recv(VALID_SYNTHDEF)
    assert mock_server.loaded_synthdefs == [VALID_SYNTHDEF]


def test_d_recv_rejects_malformed_synthdef(client):
    with pytest.raises(ScError, match="/d_recv"):
        client.d_recv(INVALID_SYNTHDEF)


def test_d_recv_rejects_empty_payload_before_sending(client, mock_server):
    with pytest.raises(ValueError, match="empty"):
        client.d_recv(b"")
    assert mock_server.loaded_synthdefs == []
