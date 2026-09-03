"""The wire protocol between bridge and UI. Malformed input must be rejected, not guessed at."""

import json

import pytest

from moogone.vox.protocol import (
    BLOCKED,
    LIVE,
    UNTESTED,
    Badge,
    ProtocolError,
    decode,
    encode,
)


class TestBadge:
    def test_three_states_only(self):
        assert LIVE.state == "live"
        assert UNTESTED("never run").state == "untested"
        assert BLOCKED("needs go/no-go").state == "blocked"
        with pytest.raises(ValueError, match="live, untested, blocked"):
            Badge("verified", "")

    def test_untested_and_blocked_require_a_reason(self):
        """A badge that says 'blocked' with no why is the thing the spec forbids."""
        with pytest.raises(ValueError, match="why"):
            Badge("blocked", "")
        with pytest.raises(ValueError, match="why"):
            Badge("untested", "   ")

    def test_serialises_flat(self):
        assert UNTESTED("x").as_dict() == {"state": "untested", "why": "x"}


class TestEncodeDecode:
    def test_round_trip(self):
        msg = {"type": "fx.set", "node": 1035, "ctl": "feedback", "value": 0.42}
        assert decode(encode(msg)) == msg

    def test_rejects_missing_type(self):
        with pytest.raises(ProtocolError, match="type"):
            decode(json.dumps({"node": 1}))

    def test_rejects_unknown_type(self):
        with pytest.raises(ProtocolError, match="unknown message type"):
            decode(json.dumps({"type": "fx.explode"}))

    def test_rejects_missing_required_field(self):
        """fx.set without a value must not become fx.set with value=None."""
        with pytest.raises(ProtocolError, match="value"):
            decode(json.dumps({"type": "fx.set", "node": 1, "ctl": "mix"}))

    def test_rejects_non_json(self):
        with pytest.raises(ProtocolError, match="not JSON"):
            decode("{nope")

    def test_rejects_non_object(self):
        with pytest.raises(ProtocolError, match="object"):
            decode("[1, 2]")

    def test_encode_refuses_nan(self):
        """NaN serialises to a token JSON parsers in browsers reject silently."""
        with pytest.raises(ProtocolError, match="finite"):
            encode(
                {
                    "type": "fx.value",
                    "node": 1,
                    "ctl": "mix",
                    "value": float("nan"),
                    "state": "sent",
                }
            )
