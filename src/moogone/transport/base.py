"""Transport abstraction for OSC packets."""

from abc import ABC, abstractmethod


class Transport(ABC):
    @abstractmethod
    def send(self, data: bytes) -> None:
        """Send one packet."""

    @abstractmethod
    def recv(self, timeout: float) -> bytes | None:
        """Receive one packet, or None if nothing arrives within timeout."""

    @abstractmethod
    def close(self) -> None:
        """Release resources. Must be safe to call more than once."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
