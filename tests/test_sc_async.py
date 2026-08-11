import pytest

from moogone.sc.client import ScTimeout


def test_sync_completes(client):
    client.sync(sync_id=42)  # returns without raising


def test_sync_matches_its_own_id(client, mock_server):
    # The mock echoes the id back; a mismatched id must not satisfy the wait.
    mock_server.sync_id_offset = 1
    with pytest.raises(ScTimeout):
        client.sync(sync_id=7, timeout=0.3)


def test_notify_registers(client, mock_server):
    client.notify(True)
    assert mock_server.notified is True


def test_notify_can_be_disabled(client, mock_server):
    client.notify(True)
    client.notify(False)
    assert mock_server.notified is False
