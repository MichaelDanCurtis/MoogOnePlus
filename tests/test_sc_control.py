import pytest

from moogone.sc.tree import SynthNode


def _reverb(root):
    return next(n for n in root.walk() if getattr(n, "defname", None) == "moog_fx_reverb")


def test_n_set_changes_a_control(client):
    node = _reverb(client.query_tree())
    client.n_set(node.node_id, in_trim=2.5)
    assert _reverb(client.query_tree()).controls["in_trim"] == pytest.approx(2.5)


def test_n_set_accepts_multiple_controls(client):
    node = _reverb(client.query_tree())
    client.n_set(node.node_id, in_trim=0.5, mix=0.9)
    controls = _reverb(client.query_tree()).controls
    assert controls["in_trim"] == pytest.approx(0.5)
    assert controls["mix"] == pytest.approx(0.9)


def test_n_set_on_unknown_node_is_silently_ignored_by_server(client, mock_server):
    # Real scsynth logs and moves on; we assert we don't crash and it's recorded.
    client.n_set(999999, in_trim=1.0)
    mock_server.wait_for_message("/n_set", timeout=1.0)


def test_n_query_returns_node_info(client):
    node = _reverb(client.query_tree())
    info = client.n_query(node.node_id)
    assert info.node_id == node.node_id
    assert info.is_group is False


def test_dump_osc_sets_server_mode(client, mock_server):
    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)
    assert mock_server.dump_mode == 1


def test_dump_osc_log_captures_subsequent_messages(client, mock_server):
    client.dump_osc(1)
    mock_server.wait_for_message("/dumpOSC", timeout=1.0)
    client.send("/n_free", 1234)
    mock_server.wait_for_message("/n_free", timeout=1.0)
    assert any(m.address == "/n_free" for m in mock_server.dump_log)
