import pytest

from moogone.osc import OscMessage


def test_status_returns_parsed_server_state(client):
    status = client.status()
    assert status.num_synths == 0
    assert status.sample_rate == pytest.approx(48000.0)
    assert status.actual_sample_rate == pytest.approx(48000.0, rel=1e-3)


def test_status_reply_wraps_sample_rates_as_osc_doubles(mock_server):
    # decode() erases the wire-level float/double distinction (both become
    # Python `float`), so this checks the pre-encode message directly: the
    # last two /status.reply args must be Float64-wrapped, or the real
    # server's doubles will decode as garbage (see module docstring intent).
    from moogone.osc import Float64

    reply = mock_server.handle(OscMessage("/status", []))
    assert isinstance(reply.args[-2], Float64)
    assert isinstance(reply.args[-1], Float64)


def test_server_records_what_it_received(client, mock_server):
    client.status()
    assert [m.address for m in mock_server.received] == ["/status"]


def test_unknown_command_raises_sc_error(client):
    from moogone.sc.client import ScError

    with pytest.raises(ScError, match="/nonsense"):
        client.request("/nonsense", reply="/never", timeout=1.0)


def test_request_times_out_when_no_reply_arrives(client, mock_server):
    from moogone.sc.client import ScTimeout

    mock_server.silent = True
    with pytest.raises(ScTimeout):
        client.request("/status", reply="/status.reply", timeout=0.2)


def test_send_is_fire_and_forget(client, mock_server):
    client.send("/n_free", 1000)
    # give the server a moment to log it
    mock_server.wait_for_message("/n_free", timeout=1.0)
    assert mock_server.received[-1] == OscMessage("/n_free", [1000])
