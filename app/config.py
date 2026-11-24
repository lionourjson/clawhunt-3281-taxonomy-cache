from os import environ

from pydantic import BaseModel, Field


class Settings(BaseModel):
    database_url: str
    redis_url: str
    cache_ttl_seconds: int = Field(default=86400, gt=0, le=2_147_483_647)
    cache_timeout_ms: int = Field(default=200, gt=0, le=60_000)
    demo_mode: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            database_url=environ["DATABASE_URL"],
            redis_url=environ["REDIS_URL"],
            cache_ttl_seconds=environ.get("TAXONOMY_CACHE_TTL_SECONDS", 86400),
            cache_timeout_ms=environ.get("TAXONOMY_CACHE_TIMEOUT_MS", 200),
            demo_mode=environ.get("TAXONOMY_DEMO_MODE", "false"),
        )
