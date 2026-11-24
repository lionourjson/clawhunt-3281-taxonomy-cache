import asyncio
import logging
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError, TimeoutError as RedisTimeoutError

from app.config import Settings
from app.taxonomy.schema import CachedSnapshot, Kind, Snapshot

logger = logging.getLogger(__name__)


def cache_key(org_id: UUID, dictionary_id: UUID, generation: UUID, version: int, kind: Kind) -> str:
    return f"taxonomy:{org_id}:{dictionary_id}:g{generation}:v{version}:{kind}"


def redis_client(settings: Settings) -> Redis:
    timeout = settings.cache_timeout_ms / 1000
    return Redis.from_url(
        settings.redis_url,
        socket_timeout=timeout,
        socket_connect_timeout=timeout,
        retry=Retry(NoBackoff(), 0),
    )


@dataclass(frozen=True)
class Lookup:
    data: Snapshot | None = None
    can_fill: bool = False


class TaxonomyCache:
    def __init__(self, redis: Redis, settings: Settings):
        self.redis = redis
        self.timeout = settings.cache_timeout_ms / 1000
        self.ttl = settings.cache_ttl_seconds
        self.last_warning: dict[str, float] = {}

    def warn(self, reason: str, operation: str) -> None:
        now = monotonic()
        if now - self.last_warning.get(reason, float("-inf")) >= 60:
            self.last_warning[reason] = now
            logger.warning("Taxonomy cache %s failed (%s). Using PostgreSQL data.", operation, reason)

    async def get(
        self, key: str, model: type[Snapshot], dictionary_id: UUID, version: int,
    ) -> Lookup:
        try:
            raw = await asyncio.wait_for(self.redis.get(key), self.timeout)
        except (TimeoutError, RedisTimeoutError):
            self.warn("timeout", "GET")
            return Lookup()
        except RedisError:
            self.warn("redis error", "GET")
            return Lookup()
        except UnicodeDecodeError:
            self.warn("invalid value", "GET")
            return Lookup()
        if raw is None:
            return Lookup(can_fill=True)
        try:
            snapshot = CachedSnapshot[model].model_validate_json(raw, strict=True)
            if snapshot.dictionary_id == dictionary_id and snapshot.version == version:
                return Lookup(data=snapshot.data)
        except ValidationError:
            pass
        self.warn("invalid value", "GET")
        return Lookup()

    async def put(self, key: str, dictionary_id: UUID, version: int, data: Snapshot) -> None:
        payload = CachedSnapshot[type(data)](
            dictionary_id=dictionary_id, version=version, data=data,
        ).model_dump_json()
        try:
            await asyncio.wait_for(self.redis.set(key, payload, ex=self.ttl), self.timeout)
        except (TimeoutError, RedisTimeoutError):
            self.warn("timeout", "SET")
        except RedisError:
            self.warn("redis error", "SET")
