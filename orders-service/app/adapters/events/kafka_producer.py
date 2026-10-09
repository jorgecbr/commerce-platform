"""Kafka producer.

Two settings here are the difference between a broker that works and one that
loses data under load:

* ``acks="all"`` - the leader waits for every in-sync replica to acknowledge.
  With the default ``"1"`` a leader that dies right after acknowledging loses
  the message.
* ``enable_idempotence=True`` - the producer deduplicates its own retries, so
  a network timeout that resends cannot create a duplicate.

Together they give effectively-once *production*. Consumers still have to be
idempotent, because this only covers the producer's side.
"""

import json
from typing import Any

from aiokafka import AIOKafkaProducer


class KafkaEventPublisher:
    """Publishes integration events to a topic."""

    def __init__(
        self,
        producer: AIOKafkaProducer,
        *,
        topic: str,
    ) -> None:
        self._producer = producer
        self._topic = topic

    async def publish(self, *, key: str, event_type: str, payload: dict[str, Any]) -> None:
        """Send one event, keyed so that a given aggregate keeps its ordering.

        Kafka guarantees order *within a partition*, and the partition is
        chosen by the key. Keying by aggregate id means all events about one
        order land on the same partition and arrive in order.
        """
        envelope = {"event_type": event_type, **payload}
        await self._producer.send_and_wait(
            self._topic,
            value=json.dumps(envelope, default=str).encode(),
            key=key.encode(),
            headers=[("event_type", event_type.encode())],
        )


def create_producer(bootstrap_servers: str) -> AIOKafkaProducer:
    """Build a producer configured for durability over raw throughput."""
    # enable_idempotence=True already implies acks="all" and caps in-flight
    # requests at 5, which is what keeps per-partition ordering while allowing
    # the retries to be deduplicated by the broker.
    return AIOKafkaProducer(
        bootstrap_servers=bootstrap_servers,
        acks="all",
        enable_idempotence=True,
        linger_ms=10,
    )
