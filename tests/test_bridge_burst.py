"""What a freshly connected page is told, before it asks anything.

The effect panel stayed empty while every other tab filled in, with no error
anywhere. The panel asked for its state in the socket's `onopen` handler, which
looked equivalent to how the other tabs work and is not: the request arrives while
the server is still working through its opening sends and is lost. Measured by
counting message types in the page -- status, fm.state, vector.state, learn.map,
sampler.state and hotspot.map all arrived, and effect.state never did.

So a panel that needs state to draw has to be in the burst, and this is the test
that says so.
"""

from __future__ import annotations

import asyncio
import json

from moogone.mock.server import MockScsynth
from moogone.vox.bridge import Bridge
from moogone.vox.meters import MockMeterSource


class FakeSocket:
    """Enough of a websocket for `Bridge.handle`: it records the opening sends
    and then ends the connection without the client ever saying anything."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, text: str) -> None:
        self.sent.append(json.loads(text))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def opening_messages() -> list[str]:
    with MockScsynth() as server:
        bridge = Bridge("127.0.0.1", server.port, MockMeterSource())
        ws = FakeSocket()
        asyncio.run(bridge.handle(ws))
        return [m.get("type") for m in ws.sent]


def test_a_new_client_is_told_the_effect_send_state_without_asking():
    assert "effect.state" in opening_messages()


def test_the_other_panels_that_draw_from_state_are_still_in_the_burst():
    # Guarding the whole set, because the failure mode is one line going missing
    # from a function nothing else exercises.
    sent = opening_messages()
    for kind in ("status", "fm.state", "vector.state", "learn.map", "sampler.state"):
        assert kind in sent, kind
