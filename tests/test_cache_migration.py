import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.schema import CreateSchema, DropSchema

from app.taxonomy.models import dictionary, tag
from app.taxonomy.schema import Scope
from conftest import run_app


@pytest.fixture
async def isolated_migration(settings, engine, monkeypatch):
    schema = f"migration_{uuid4().hex}"
    async with engine.begin() as conn:
        await conn.execute(CreateSchema(schema))
    url = make_url(settings.database_url)
    options = f"{url.query.get('options', '')} -csearch_path={schema}".strip()
    isolated_url = url.update_query_dict({"options": options}).render_as_string(hide_password=False)
    monkeypatch.setenv("DATABASE_URL", isolated_url)
    alembic = Config(Path(__file__).resolve().parents[1] / "alembic.ini")
    isolated_engine = create_async_engine(isolated_url)
    try:
        yield settings.model_copy(update={"database_url": isolated_url}), alembic, isolated_engine
    finally:
        await isolated_engine.dispose()
        async with engine.begin() as conn:
            await conn.execute(DropSchema(schema, cascade=True))


@pytest.mark.parametrize("rollback_to", ["0001_standalone_schema", "0002_dictionary_version"])
async def test_migration_round_trip_uses_new_keys_with_same_numeric_version(
    isolated_migration, redis_instance, rollback_to,
):
    settings, alembic, engine = isolated_migration
    scope = Scope(uuid4(), uuid4())
    dict_id, tag_id = uuid4(), uuid4()
    fields = dict(org_id=scope.org_id, site_id=scope.site_id, created_by=uuid4())
    prefix = f"taxonomy:{scope.org_id}:{dict_id}"
    headers = {"X-Org-ID": str(scope.org_id), "X-Site-ID": str(scope.site_id)}
    path = f"/taxonomy/dictionaries/{dict_id}"

    async def get_snapshots():
        async with run_app(settings) as (client, _):
            tree = await client.get(path + "/tree", headers=headers)
            aliases = await client.get(path + "/aliases", headers=headers)
        assert tree.status_code == aliases.status_code == 200
        return tree.json()["nodes"][str(tag_id)]["label"], aliases.json()["aliases"]

    async def identity():
        async with engine.connect() as conn:
            return (await conn.execute(
                select(dictionary.c.cache_generation, dictionary.c.version).where(dictionary.c.id == dict_id),
            )).one()

    await asyncio.to_thread(command.upgrade, alembic, "0002_dictionary_version")
    async with engine.begin() as conn:
        await conn.execute(dictionary.insert().values(id=dict_id, **fields))
        await conn.execute(tag.insert().values(
            id=tag_id, dictionary_id=dict_id, code="sample", label="旧值", status="active", aliases=["旧"], **fields,
        ))
    try:
        await asyncio.to_thread(command.upgrade, alembic, "head")
        old_generation, old_version = await identity()
        assert old_version == 1
        assert await get_snapshots() == ("旧值", {"旧": str(tag_id)})
        old_keys = [f"{prefix}:g{old_generation}:v1:{part}" for part in ("tree", "alias")]
        legacy_keys = [f"{prefix}:v1:{part}" for part in ("tree", "alias")]
        for old_key, legacy_key in zip(old_keys, legacy_keys, strict=True):
            await redis_instance.set(legacy_key, await redis_instance.get(old_key), ex=120)

        await asyncio.to_thread(command.downgrade, alembic, rollback_to)
        async with engine.begin() as conn:
            await conn.execute(update(tag).where(tag.c.id == tag_id).values(label="新值", aliases=["新"]))
        await asyncio.to_thread(command.upgrade, alembic, "head")
        new_generation, new_version = await identity()
        assert new_version == old_version == 1
        assert new_generation != old_generation
        assert await get_snapshots() == ("新值", {"新": str(tag_id)})
        new_keys = [f"{prefix}:g{new_generation}:v1:{part}" for part in ("tree", "alias")]
        assert await redis_instance.exists(*old_keys, *legacy_keys, *new_keys) == 6
    finally:
        keys = [key async for key in redis_instance.scan_iter(f"{prefix}:*")]
        if keys:
            await redis_instance.delete(*keys)
