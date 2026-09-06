"""Tests for streaming the instrument's audio over the network.

The cleanup behaviour is the point. A stream armed and then abandoned keeps
running: there is no error, nothing stops on its own, and the first symptom is
that everything else on the network gets slow. That happened, and these tests
exist so it cannot happen quietly again.
"""

from __future__ import annotations

import pytest

from moogone import netaudio
from moogone.netaudio import STREAM_BUFFER, STREAM_NODE, Stream, arm, disarm, follow


class FakeClient:
    def __init__(self, fail_on: str | None = None):
        self.sent: list[tuple] = []
        self.defs = 0
        self.fail_on = fail_on

    def send(self, *args):
        if self.fail_on and args and args[0] == self.fail_on:
            raise TimeoutError("network went away")
        self.sent.append(args)

    def sync(self, *a, **k):
        pass

    def d_recv(self, blob, timeout=None):
        self.defs += 1

    def of(self, address):
        return [m for m in self.sent if m and m[0] == address]


@pytest.fixture
def no_ssh(monkeypatch):
    calls: list[tuple[str, bool]] = []

    def fake(host, command, background=False):
        calls.append((command, background))

    monkeypatch.setattr(netaudio, "_ssh", fake)
    monkeypatch.setattr(netaudio, "compile_synthdef", lambda *a: b"", raising=False)
    return calls


@pytest.fixture
def no_compile(monkeypatch):
    import moogone.synthdef as sd

    monkeypatch.setattr(sd, "compile_synthdef", lambda name, graph: b"SCgf-stub")


class TestArming:
    def test_it_starts_the_writer_before_the_synth(self, no_ssh, no_compile):
        client = FakeClient()
        arm(client, "dev", "10.0.0.1", 14150)
        # The FIFO and its reader must exist before scsynth opens it for writing.
        assert "mkfifo" in no_ssh[0][0]
        assert "nc 10.0.0.1 14150" in no_ssh[1][0]
        assert no_ssh[1][1] is True, "the writer must be backgrounded"

    def test_the_writer_is_piped_through_cat(self, no_ssh, no_compile):
        # `nc ... > FIFO` never binds: the shell opens the FIFO for writing before
        # exec'ing nc, and that open blocks until a reader appears.
        client = FakeClient()
        arm(client, "dev", "10.0.0.1", 14150)
        assert "| cat >" not in no_ssh[1][0]
        assert no_ssh[1][0].startswith("cat "), no_ssh[1][0]

    def test_the_buffer_is_opened_raw_not_wav(self, no_ssh, no_compile):
        # A WAV header carries a length that must be seeked back and written at
        # close, and a stream has no end to seek to.
        client = FakeClient()
        arm(client, "dev", "10.0.0.1", 14150)
        write = client.of("/b_write")[0]
        assert "raw" in write and "float" in write
        assert write[-1] == 1, "leaveOpen must be set or nothing streams"

    def test_the_default_ring_is_the_low_latency_one(self):
        # 65536 frames -- SuperCollider's usual size -- costs 372 ms. 2048 costs 22.
        assert netaudio.STREAM_RING <= 4096

    def test_ids_do_not_collide_with_the_sampler_or_fm(self):
        from moogone.fm import FIRST_NODE as FM_NODE
        from moogone.sampler import FIRST_BUFFER
        from moogone.sampler import FIRST_NODE as SAMPLER_NODE

        assert STREAM_NODE not in range(SAMPLER_NODE, SAMPLER_NODE + 64)
        assert STREAM_NODE not in range(FM_NODE, FM_NODE + 48)
        assert STREAM_BUFFER < FIRST_BUFFER


class TestCleanup:
    def test_a_failure_partway_through_disarms(self, no_ssh, no_compile):
        """The bug this pins: a stream armed and then abandoned keeps running.

        There is no error and nothing stops on its own. The first symptom was
        every other request to the instrument getting slow.
        """
        client = FakeClient(fail_on="/s_new")
        with pytest.raises(TimeoutError):
            arm(client, "dev", "10.0.0.1", 14150)
        assert client.of("/n_free"), "the synth must be freed on the failure path"
        assert client.of("/b_free"), "and the buffer released"
        assert any("kill" in c for c, _ in no_ssh), "and the writer killed"

    def test_disarm_kills_the_writer(self, no_ssh, no_compile):
        # Freeing the synth stops scsynth writing, but `nc` is a separate process
        # and outlives it, holding the FIFO and the connection open.
        client = FakeClient()
        stream = arm(client, "dev", "10.0.0.1", 14150)
        no_ssh.clear()
        disarm(client, stream)
        assert any("kill" in c for c, _ in no_ssh)
        assert any("rm -f" in c for c, _ in no_ssh)

    def test_the_quiet_path_does_not_wait(self, no_ssh, no_compile):
        # On the failure path the network is usually why we are here; waiting for a
        # reply that may never come would raise over the top of the real error.
        client = FakeClient()
        stream = Stream("dev", "10.0.0.1", 14150, 0, 2048)
        synced = []
        client.sync = lambda *a, **k: synced.append(1)
        disarm(client, stream, quiet=True)
        assert synced == []


def test_follow_puts_the_recorder_back_at_the_tail():
    # Nodes run in creation order, so a voice made after the recorder writes the
    # bus too late to be heard -- and the stream goes SILENT with no error.
    client = FakeClient()
    follow(client)
    assert client.of("/g_tail")[0][1:] == (0, STREAM_NODE)
