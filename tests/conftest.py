import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.main import create_app
from app.taxonomy.cache import redis_client
from app.taxonomy.models import dictionary, tag
from app.taxonomy.schema import Scope


@dataclass(frozen=True)
class Example:
    scope: Scope
    dictionary_id: UUID
    source: UUID
    target: UUID
    child: UUID
    third: UUID

    @property
    def headers(self):
        return {"X-Org-ID": str(self.scope.org_id), "X-Site-ID": str(self.scope.site_id)}

    @property
    def path(self):
        return f"/taxonomy/dictionaries/{self.dictionary_id}"

    def key(self, version, part):
        return f"taxonomy:{self.scope.org_id}:{self.dictionary_id}:v{version}:{part}"


@pytest.fixture(scope="session")
def event_loop_policy():
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def settings():
    return Settings.from_env().model_copy(update={"demo_mode": True})


@pytest.fixture
async def engine(settings):
    db = create_async_engine(settings.database_url)
    try:
        yield db
    finally:
        await db.dispose()


@pytest.fixture
async def redis_instance(settings):
    redis = redis_client(settings)
    try:
        assert await redis.ping()
        yield redis
    finally:
        await redis.aclose()


@pytest.fixture
async def example(engine, redis_instance):
    sample = Example(Scope(uuid4(), uuid4()), uuid4(), uuid4(), uuid4(), uuid4(), uuid4())
    scope_values = dict(org_id=sample.scope.org_id, site_id=sample.scope.site_id, created_by=uuid4())
    rows = [
        dict(id=sample.source, code="a", label="样例甲", status="active", parent_id=None, aliases=["甲"]),
        dict(id=sample.target, code="b", label="样例乙", status="active", parent_id=None, aliases=["乙"]),
        dict(id=sample.child, code="c", label="样例子项", status="pending", parent_id=sample.source, aliases=["子"]),
        dict(id=sample.third, code="d", label="样例丙", status="active", parent_id=None, aliases=["丙"]),
    ]
    async with engine.begin() as conn:
        await conn.execute(insert(dictionary).values(id=sample.dictionary_id, **scope_values))
        await conn.execute(insert(tag), [dict(dictionary_id=sample.dictionary_id, **scope_values, **row) for row in rows])
    try:
        yield sample
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(tag).where(tag.c.dictionary_id == sample.dictionary_id))
            await conn.execute(delete(dictionary).where(dictionary.c.id == sample.dictionary_id))
        keys = [key async for key in redis_instance.scan_iter(sample.key("*", "*"))]
        if keys:
            await redis_instance.delete(*keys)


@asynccontextmanager
async def run_app(settings):
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client, app.state.taxonomy


@pytest.fixture
async def running(settings):
    async with run_app(settings) as clients:
        yield clients
