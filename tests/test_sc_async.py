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


def test_sync_timeout_message_reports_the_caller_budget_not_a_shrunk_remainder(client, mock_server):
    """_await_reply's deadline always expires a hair before sync()'s own
    `remaining <= 0` check can fire, so the message that used to reach the
    operator was built from the SHRUNK remaining it was handed rather than
    the budget that was actually requested: "no /synced within
    1.9999996250262484s" for a 2.0s call. /sync gates both /d_recv and
    `moogone set`, so this is a string that gets read in front of hardware.

    Mutation-checked: remove the `except ScTimeout: raise ... from None`
    wrapper in ScClient.sync and this test fails on the float-noise
    assertion (the message reads 0.499999... rather than 0.5).
    """
    mock_server.sync_id_offset = 1  # every /synced carries someone else's id
    with pytest.raises(ScTimeout) as excinfo:
        client.sync(sync_id=7, timeout=0.5)
    text = str(excinfo.value)
    assert "within 0.5s" in text, f"budget not restated in caller's terms: {text!r}"
    assert "id 7" in text, f"the sync id is the one thing _await_reply cannot know: {text!r}"
    # No float noise: the digits between "within " and "s" must be exactly
    # the formatted budget, not a shrunk remainder like 0.4999996250262484.
    assert "0.4999" not in text and "0.5000" not in text
