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

    def test_the_quiet_path_still_waits_for_the_free_to_land(self, no_ssh, no_compile):
        """`quiet` means "do not raise", NOT "do not confirm".

        It used to mean both, and that was a race with teeth. The kill below
        removes the `cat` reading the FIFO; if `/n_free` has not been processed by
        then, `DiskOut` writes into a pipe with no reader, and scsynth handles
        neither SIGPIPE nor ignores it -- the audio engine dies and the instrument
        loses every effect until the service is restarted. Freeing and killing are
        two messages to two different machines over two different protocols, and
        the sync is the only thing that orders them.
        """
        client = FakeClient()
        stream = Stream("dev", "10.0.0.1", 14150, 0, 2048)
        synced = []
        client.sync = lambda *a, **k: synced.append(1)
        disarm(client, stream, quiet=True)
        assert synced == [1]

    def test_the_quiet_path_does_not_raise_when_the_confirmation_never_comes(
        self, no_ssh, no_compile
    ):
        # On the failure path the network is usually why we are here, and raising
        # over the top of the original error hides it.
        client = FakeClient()
        stream = Stream("dev", "10.0.0.1", 14150, 0, 2048)

        def never(*a, **k):
            raise TimeoutError("no /synced")

        client.sync = never
        disarm(client, stream, quiet=True)
        assert any("kill" in c for c, _ in no_ssh)
        with pytest.raises(TimeoutError):
            disarm(client, stream)


def test_follow_puts_the_recorder_back_at_the_tail():
    # Nodes run in creation order, so a voice made after the recorder writes the
    # bus too late to be heard -- and the stream goes SILENT with no error.
    client = FakeClient()
    follow(client)
    assert client.of("/g_tail")[0][1:] == (0, STREAM_NODE)


def test_disarm_cleans_up_even_when_the_sync_times_out(no_ssh, no_compile):
    """Found by a real run: disarm sent the frees, then raised on client.sync(),
    and the `rm -f`/kill after it never executed -- leaving the FIFO and the writer
    behind, which is the exact thing disarm exists to remove.
    """

    class SyncFails(FakeClient):
        def sync(self, *a, **k):
            raise TimeoutError("no /synced")

    client = SyncFails()
    stream = Stream("dev", "10.0.0.1", 14150, 0, 2048)
    with pytest.raises(TimeoutError):
        disarm(client, stream)
    assert any("kill" in c for c, _ in no_ssh), "the writer must still be killed"
    assert any("rm -f" in c for c, _ in no_ssh), "and the fifo removed"


def test_the_fifo_keeps_a_reader_after_the_network_goes(no_ssh, no_compile):
    """scsynth does not handle SIGPIPE -- SigIgn is 0x4, SigCgt is 0x180000000,
    and bit 12 is in neither -- so writing to a FIFO with no reader KILLS the
    instrument's audio engine. It happened: a harness exited while a stream was
    armed, nc went with it, and every effect on the instrument went away until the
    service was restarted.

    So the writer must drain the FIFO even after nc is gone.
    """
    client = FakeClient()
    arm(client, "dev", "10.0.0.1", 14150)
    writer = no_ssh[1][0]
    assert "nc 10.0.0.1 14150" in writer
    assert "cat > /dev/null" in writer, (
        "nothing drains the FIFO once nc exits; scsynth will take SIGPIPE and die"
    )
    # The drain must run after nc ENDS, not instead of it, and unconditionally --
    # `||` would skip it when nc exits cleanly, which is the common case.
    assert "||" not in writer, "the drain must not be conditional on nc failing"


def test_the_cleanup_command_does_not_kill_itself(no_ssh, no_compile):
    """The command names the FIFO, so the shell running it matches its own pattern.

    Without excluding `$$` the loop killed its own shell before reaching the `rm`,
    and every disarm silently left the FIFO behind -- which looked like the remove
    failing rather than the shell dying halfway through it.
    """
    client = FakeClient()
    stream = Stream("dev", "10.0.0.1", 14150, 0, 2048)
    disarm(client, stream)
    cleanup = next(c for c, _ in no_ssh if "kill" in c)
    assert "me=$$" in cleanup, "the loop must know its own pid"
    assert '[ "$pid" = "$me" ] && continue' in cleanup, "and skip itself"
    assert cleanup.index("kill") < cleanup.index("rm -f"), "the rm comes last"
