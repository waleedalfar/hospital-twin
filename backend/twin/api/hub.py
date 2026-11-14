"""Fan-out of WebSocket messages to connected browsers. Each client has a bounded queue; a client that falls
too far behind is disconnected and resyncs from a fresh snapshot when it reconnects (§10.6)."""

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)
QUEUE_LIMIT = 256
NETWORK = "__network__"


@dataclass(eq=False)
class Client:
    channel: str
    queue: asyncio.Queue[str | None] = field(default_factory=lambda: asyncio.Queue(QUEUE_LIMIT))


class Hub:
    def __init__(self) -> None:
        self._clients: dict[str, set[Client]] = {}

    def subscribe(self, channel: str) -> Client:
        client = Client(channel)
        self._clients.setdefault(channel, set()).add(client)
        return client

    def unsubscribe(self, client: Client) -> None:
        self._clients.get(client.channel, set()).discard(client)

    def count(self, channel: str) -> int:
        return len(self._clients.get(channel, ()))

    def has_hospital_clients(self, hospital_id: str) -> bool:
        return self.count(hospital_id) > 0

    def has_network_clients(self) -> bool:
        return self.count(NETWORK) > 0

    def publish_hospital(self, hospital_id: str, text: str) -> None:
        self._publish(hospital_id, text)

    def publish_network(self, text: str) -> None:
        self._publish(NETWORK, text)

    def _publish(self, channel: str, text: str) -> None:
        for client in list(self._clients.get(channel, ())):
            try:
                client.queue.put_nowait(text)
            except asyncio.QueueFull:
                logger.warning("WebSocket client on %s is too slow; disconnecting it", channel)
                self.unsubscribe(client)
                client.queue.get_nowait()
                client.queue.put_nowait(None)
