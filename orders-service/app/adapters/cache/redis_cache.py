"""Redis adapter.

Used for two different things, and the distinction matters:

* **Cache** — a disposable copy of data that is already in PostgreSQL. A
  failure here costs latency, never correctness.
* **Idempotency keys** — a short-lived record that a request was already
  handled. A failure here would matter more, so writes are treated as
  authoritative and reads are best effort.
"""

import json
from typing import Any

from redis.asyncio import Redis


class RedisCache:
    """Thin wrapper so the rest of the codebase never imports redis directly."""

    def __init__(self, client: Redis, *, default_ttl_seconds: int = 30) -> None:
        self._client = client
        self._ttl = default_ttl_seconds

    @staticmethod
    def _key(namespace: str, key: str) -> str:
        return f"{namespace}:{key}"

    async def get_json(self, namespace: str, key: str) -> Any | None:
        """Return a cached JSON value, or ``None`` when absent or unreachable."""
        try:
            raw = await self._client.get(self._key(namespace, key))
        except Exception:
            # A cache miss and a cache outage are the same thing to a caller.
            return None
        if raw is None:
            return None
        return json.loads(raw)

    async def set_json(self, namespace: str, key: str, value: Any, *, ttl: int | None = None) -> None:
        """Store a JSON value that expires after ``ttl`` seconds."""
        """Store a JSON value with an expiry."""
        await self._client.set(
            self._key(namespace, key),
            json.dumps(value, default=str),
            ex=ttl if ttl is not None else self._ttl,
        )

    async def delete(self, namespace: str, key: str) -> None:
        """Evict a key, used after a write invalidates the cached copy."""
        await self._client.delete(self._key(namespace, key))

    async def acquire_lock(self, namespace: str, key: str, *, ttl_seconds: int = 30) -> bool:
        """Best-effort mutex, used to stop two workers doing the same job.

        Returns ``False`` when the lock is already held. This is the Redis
        ``SET NX EX`` pattern; it is not a substitute for a real lease if the
        work can take longer than the TTL.
        """
        return bool(await self._client.set(self._key(namespace, key), "1", nx=True, ex=ttl_seconds))

    async def ping(self) -> bool:
        """Return whether Redis answers, used by the readiness probe."""
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        """Release the connection pool on shutdown."""
        await self._client.aclose()
