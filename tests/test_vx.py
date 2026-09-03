"""Tests for the voice-bus query tool.

The property that matters most here is that a **silent** bus, a **404**, and a
**value** stay distinguishable. Collapsing those three is exactly how the first
sweep of this address space produced 37 confident, uniformly wrong answers.
"""

import pytest

from moogone.osc import OscMessage, decode
from moogone.vx import (
    NOT_FOUND,
    VC_HOST,
    VC_PORT,
    VxReply,
    as_printf_escape,
    build_query,
    card_address,
    interpret,
    parse_hexdump,
    render_remote_command,
)


class TestBuildQuery:
    def test_carries_no_arguments(self):
        """A setter cannot store what was never sent."""
        msg = decode(build_query("/hw/mute"))
        assert msg.address == "/hw/mute"
        assert msg.args == []

    def test_encodes_the_typetag_for_zero_args(self):
        # ",\0\0\0" — present and empty, not omitted. A missing type tag is a
        # different packet, and some servers reject it.
        assert b",\x00\x00\x00" in build_query("/info/product")

    def test_round_trips_through_the_codec(self):
        for addr in ("/a", "/info/product", "/vx/15/cal/ladf/x0"):
            assert decode(build_query(addr)).address == addr

    def test_is_four_byte_aligned(self):
        for addr in ("/a", "/ab", "/abc", "/abcd", "/abcde"):
            assert len(build_query(addr)) % 4 == 0

    @pytest.mark.parametrize("bad", ["hw/mute", "", "info/product"])
    def test_rejects_address_without_leading_slash(self, bad):
        with pytest.raises(ValueError, match="must start with"):
            build_query(bad)


class TestPrintfEscape:
    def test_escapes_every_byte(self):
        assert as_printf_escape(b"\x00\x2f\xff") == r"\x00\x2f\xff"

    def test_escapes_bytes_a_shell_would_otherwise_eat(self):
        """Quotes, backslashes and NULs must not survive as literals."""
        esc = as_printf_escape(b"'\\\x00\n")
        assert esc == r"\x27\x5c\x00\x0a"
        assert "'" not in esc and "\n" not in esc

    def test_round_trips(self):
        payload = build_query("/vx/3/info/version")
        recovered = bytes.fromhex(as_printf_escape(payload).replace("\\x", ""))
        assert recovered == payload


class TestRenderRemoteCommand:
    def test_targets_the_voice_bus_by_default(self):
        cmd = render_remote_command("/info/product")
        assert f"{VC_HOST} {VC_PORT}" in cmd

    def test_honours_an_explicit_host_and_port(self):
        cmd = render_remote_command("/info/product", host="127.0.0.1", port=9300)
        assert "127.0.0.1 9300" in cmd
        assert VC_HOST not in cmd

    def test_embeds_the_query_bytes(self):
        cmd = render_remote_command("/info/product")
        assert as_printf_escape(build_query("/info/product")) in cmd

    def test_bounds_the_wait(self):
        """vxping never exits; nc must not inherit that problem."""
        assert "-w 1" in render_remote_command("/a")
        assert "-w 5" in render_remote_command("/a", wait=5)


class TestParseHexdump:
    def test_parses_spaced_and_wrapped_hex(self):
        assert parse_hexdump(" 2f 61 00 00 \n 2c 00 00 00 ") == b"/a\x00\x00,\x00\x00\x00"

    def test_empty_means_empty(self):
        assert parse_hexdump("") == b""
        assert parse_hexdump("   \n  ") == b""

    def test_rejects_odd_length(self):
        with pytest.raises(ValueError, match="odd length"):
            parse_hexdump("2f6100000")

    def test_rejects_even_length_non_hex(self):
        """Exercises the hex branch specifically, not the length branch."""
        with pytest.raises(ValueError, match="not a hexdump"):
            parse_hexdump("nc: bad addr")  # 10 chars once whitespace is stripped

    @pytest.mark.parametrize(
        "junk",
        [
            "nc: bad address",  # odd length  -> length branch
            "nc: bad addr",  # even length -> hex branch
            "connection refused",
            "zz",
        ],
    )
    def test_rejects_any_shell_diagnostic(self, junk):
        """However it is rejected, a diagnostic must never become a packet."""
        with pytest.raises(ValueError):
            parse_hexdump(junk)


class TestInterpret:
    def test_no_bytes_is_silent_not_absent(self):
        r = interpret("/hw/mute", b"")
        assert r.kind == "silent"
        assert not r.is_value

    def test_404_is_not_found_as_two_strings(self):
        """The wire form the instrument actually sends: s:404 s:"Not found"."""
        raw = OscMessage("/info/fwrev", ["404", "Not found"]).encode()
        r = interpret("/info/fwrev", raw)
        assert r.kind == "not_found"
        assert not r.is_value

    def test_404_is_not_found_as_int_and_string(self):
        """The form one would assume. Accepted too, so neither surprises later."""
        raw = OscMessage("/info/fwrev", [NOT_FOUND[0], NOT_FOUND[1]]).encode()
        assert interpret("/info/fwrev", raw).kind == "not_found"

    def test_a_value_is_a_value(self):
        raw = OscMessage("/info/product", ["lasvc"]).encode()
        r = interpret("/info/product", raw)
        assert r.kind == "value"
        assert r.is_value
        assert r.args == ("lasvc",)

    def test_silent_and_not_found_are_distinguishable(self):
        """The distinction the first sweep destroyed."""
        raw = OscMessage("/x", [NOT_FOUND[0], NOT_FOUND[1]]).encode()
        assert interpret("/x", b"").kind != interpret("/x", raw).kind

    def test_404_shaped_value_is_still_a_value(self):
        """An address legitimately holding 404 must not be read as absent.

        Both fields have to match the sentinel, not just the number.
        """
        assert interpret("/p/cutoff", OscMessage("/p/cutoff", [404]).encode()).kind == "value"
        assert (
            interpret("/p/cutoff", OscMessage("/p/cutoff", [404, "Found"]).encode()).kind == "value"
        )
        assert (
            interpret("/p/cutoff", OscMessage("/p/cutoff", ["404", "OK"]).encode()).kind == "value"
        )

    def test_mismatched_reply_address_raises(self):
        """Attributing one address's data to another is worse than no answer."""
        raw = OscMessage("/info/version", ["v2.1.2"]).encode()
        with pytest.raises(ValueError, match="mismatch"):
            interpret("/info/product", raw)

    def test_multi_argument_value_keeps_every_argument(self):
        """The /a/stat meters return two floats; dropping one halves the reading."""
        raw = OscMessage("/a/stat/mainl", [-1.5e-05, 2.5e-05]).encode()
        r = interpret("/a/stat/mainl", raw)
        assert len(r.args) == 2
        assert r.args[0] != r.args[1]


class TestRendering:
    def test_shows_types(self):
        assert "s:lasvc" in str(VxReply("/info/product", "value", ("lasvc",)))
        assert "i:16" in str(VxReply("/v/voices", "value", (16,)))

    def test_silent_and_404_render_differently(self):
        assert str(VxReply("/a", "silent")) != str(VxReply("/a", "not_found"))


class TestCardAddress:
    def test_scopes_to_a_card(self):
        assert card_address(0, "/info/product") == "/vx/0/info/product"
        assert card_address(15, "/cal/o1") == "/vx/15/cal/o1"

    @pytest.mark.parametrize("bad", [-1, 16, 99])
    def test_rejects_cards_outside_the_sixteen(self, bad):
        with pytest.raises(ValueError, match="0-15"):
            card_address(bad, "/info/product")

    def test_rejects_path_without_leading_slash(self):
        with pytest.raises(ValueError, match="must start with"):
            card_address(0, "info/product")


class TestRemoteCommandIsBounded:
    """GNU netcat does not exit on UDP; nothing may depend on it doing so."""

    def test_bounds_the_process_by_pid_not_job_control(self):
        cmd = render_remote_command("/info/product")
        assert "$!" in cmd
        assert "%1" not in cmd, "job control silently discards output here"

    def test_captures_to_a_file_so_output_survives_the_kill(self):
        cmd = render_remote_command("/info/product")
        assert "> /tmp/vxq.bin" in cmd
        # The reply must be read from the file, not straight down a pipe into od.
        assert "< /tmp/vxq.bin" in cmd

    def test_clears_the_temp_file_first(self):
        """Otherwise a silent address inherits the previous address's reply."""
        cmd = render_remote_command("/a")
        assert cmd.index("rm -f") < cmd.index("printf")

    def test_never_passes_dash_c(self):
        """`-c` closes on stdin EOF; printf EOFs at once, so the reply is lost.

        Measured on the instrument: `nc -u` and `nc -u -w 1` return the 28-byte
        reply to /info/product; `nc -u -c` and `nc -u -c -w 1` return zero bytes,
        which is indistinguishable from the address not existing.
        """
        cmd = render_remote_command("/info/product")
        assert " -c " not in cmd and not cmd.endswith(" -c")


class TestReplyKinds:
    """The instrument answers in five distinguishable ways. Keep them apart."""

    def test_no_arguments_is_ack_not_value(self):
        """The common case: 121 of 303 addresses answered with nothing at all."""
        r = interpret("/hw/mute", OscMessage("/hw/mute", []).encode())
        assert r.kind == "ack"
        assert not r.is_value, "an empty answer must not read as a measurement"
        assert r.exists

    def test_503_is_unavailable_not_absent(self):
        """Per-card paths answer 503 to a zero-arg query but exist."""
        raw = OscMessage("/vx/0/info/hwrev", ["503", "Unavailable"]).encode()
        r = interpret("/vx/0/info/hwrev", raw)
        assert r.kind == "unavailable"
        assert r.exists, "503 means present-but-unwilling, not missing"
        assert not r.is_value

    def test_404_does_not_exist(self):
        raw = OscMessage("/nope", ["404", "Not found"]).encode()
        assert not interpret("/nope", raw).exists

    def test_all_five_kinds_render_distinctly(self):
        kinds = [
            interpret("/x", b""),
            interpret("/x", OscMessage("/x", ["404", "Not found"]).encode()),
            interpret("/x", OscMessage("/x", ["503", "Unavailable"]).encode()),
            interpret("/x", OscMessage("/x", []).encode()),
            interpret("/x", OscMessage("/x", [1.5]).encode()),
        ]
        assert len({r.kind for r in kinds}) == 5
        assert len({str(r) for r in kinds}) == 5

    def test_value_still_wins_when_args_are_present(self):
        raw = OscMessage("/a/stat/mainl", [-1.5e-05, 2.5e-05]).encode()
        r = interpret("/a/stat/mainl", raw)
        assert r.kind == "value" and r.is_value and r.exists
