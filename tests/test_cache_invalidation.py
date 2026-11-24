import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError

from app.taxonomy.models import dictionary, tag
from app.taxonomy.service import InvalidChange, bump_version, dictionary_version, lock_dictionary


async def snapshots(client, example):
    tree = await client.get(example.path + "/tree", headers=example.headers)
    aliases = await client.get(example.path + "/aliases", headers=example.headers)
    assert tree.status_code == aliases.status_code == 200
    return tree.json(), aliases.json()["aliases"]


@pytest.mark.parametrize("action", ["activate", "modify", "deactivate", "merge"])
async def test_four_writes_invalidate_both_keys(action, running, example, redis_instance):
    client, service = running
    before_tree, before_alias = await snapshots(client, example)
    assert before_tree["nodes"][str(example.source)]["label"] == "样例甲"
    assert before_alias["甲"] == str(example.source)
    args = {"label": "样例甲（修改）"} if action == "modify" else {}
    if action == "merge":
        args = {"target_id": example.target}
    tag_id = example.child if action == "activate" else example.source
    assert await service.change(example.scope, example.dictionary_id, tag_id, action, **args) == 2
    tree, aliases = await snapshots(client, example)
    if action == "activate":
        assert str(example.child) not in before_tree["nodes"] and "子" not in before_alias
        assert tree["nodes"][str(example.source)]["children"] == [str(example.child)]
        assert aliases["子"] == str(example.child)
    elif action == "modify":
        assert tree["nodes"][str(example.source)]["label"] == "样例甲（修改）"
    elif action == "deactivate":
        assert tree["nodes"][str(example.source)]["status"] == "inactive"
        assert "甲" not in aliases
    else:
        assert str(example.source) not in tree["nodes"]
        assert aliases["甲"] == str(example.target)
    for part in ("tree", "alias"):
        old_key, new_key = example.key(1, part), example.key(2, part)
        assert await redis_instance.exists(old_key, new_key) == 2
        assert json.loads(await redis_instance.get(new_key))["version"] == 2
        assert 0 < await redis_instance.pttl(old_key) <= service.cache.ttl * 1000


async def test_external_write_hook_publishes_new_alias_snapshot(running, example, engine, redis_instance):
    client, _ = running
    assert (await snapshots(client, example))[1]["甲"] == str(example.source)
    async with engine.begin() as conn:
        await lock_dictionary(conn, example.scope, example.dictionary_id)
        await conn.execute(update(tag).where(tag.c.id == example.source).values(aliases=["新别名"]))
        assert await bump_version(conn, example.scope, example.dictionary_id) == 2
    aliases = (await snapshots(client, example))[1]
    assert "甲" not in aliases and aliases["新别名"] == str(example.source)
    assert await redis_instance.exists(example.key(1, "alias"), example.key(2, "alias")) == 2


async def test_chained_merge_and_disabled_target(running, example):
    client, service = running
    args = (example.scope, example.dictionary_id)
    await service.change(*args, example.child, "activate")
    await service.change(*args, example.source, "merge", target_id=example.target)
    await service.change(*args, example.target, "merge", target_id=example.third)
    tree, aliases = await snapshots(client, example)
    assert aliases["甲"] == aliases["乙"] == str(example.third)
    assert tree["nodes"][str(example.third)]["children"] == [str(example.child)]
    await service.change(*args, example.third, "deactivate")
    assert (await snapshots(client, example))[1] == {"子": str(example.child)}


@pytest.mark.parametrize("target", ["self", "descendant", "missing", "soft_deleted", "inactive"])
async def test_invalid_merge_leaves_version_and_cache(target, running, example, engine, redis_instance):
    client, service = running
    ids = {"self": example.source, "descendant": example.child, "missing": uuid4(),
           "soft_deleted": example.target, "inactive": example.third}
    async with engine.begin() as conn:
        for tag_id, values in (
            (example.child, {"status": "active"}), (example.target, {"deleted_at": func.now()}),
            (example.third, {"status": "inactive"}),
        ):
            await conn.execute(update(tag).where(tag.c.id == tag_id).values(**values))
    original = await snapshots(client, example)
    with pytest.raises(InvalidChange):
        await service.change(example.scope, example.dictionary_id, example.source, "merge", target_id=ids[target])
    async with engine.connect() as conn:
        assert await dictionary_version(conn, example.scope, example.dictionary_id) == 1
    assert await redis_instance.exists(example.key(1, "tree"), example.key(2, "tree")) == 1
    assert await snapshots(client, example) == original


async def test_label_input_boundaries(running, example, engine):
    client, service = running
    for invalid in (None, "", "  ", "甲" * 129, "\x00", 123):
        with pytest.raises(InvalidChange):
            await service.change(example.scope, example.dictionary_id, example.source, "modify", label=invalid)
    assert await service.change(
        example.scope, example.dictionary_id, example.source, "modify", label="甲" * 128,
    ) == 2
    tree, _ = await snapshots(client, example)
    assert tree["nodes"][str(example.source)]["label"] == "甲" * 128


async def test_transaction_failure_rolls_back_payload_and_version(running, example, engine):
    client, _ = running
    original = await snapshots(client, example)
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            await lock_dictionary(conn, example.scope, example.dictionary_id)
            await conn.execute(update(tag).where(tag.c.id == example.source).values(label="临时修改"))
            assert await bump_version(conn, example.scope, example.dictionary_id) == 2
            await conn.execute(update(dictionary).where(dictionary.c.id == example.dictionary_id).values(version=0))
    async with engine.connect() as conn:
        assert await dictionary_version(conn, example.scope, example.dictionary_id) == 1
        assert await conn.scalar(tag.select().with_only_columns(tag.c.label).where(tag.c.id == example.source)) == "样例甲"
    assert await snapshots(client, example) == original


async def test_concurrent_writes_each_increment_and_dictionaries_are_independent(running, example, engine):
    client, service = running
    other = uuid4()
    async with engine.begin() as conn:
        await conn.execute(dictionary.insert().values(
            id=other, org_id=example.scope.org_id, site_id=example.scope.site_id, created_by=uuid4(),
        ))
    try:
        results = await asyncio.gather(
            service.change(example.scope, example.dictionary_id, example.source, "modify", label="并发甲"),
            service.change(example.scope, example.dictionary_id, example.target, "modify", label="并发乙"),
        )
        assert sorted(results) == [2, 3]
        tree, _ = await snapshots(client, example)
        assert tree["nodes"][str(example.source)]["label"] == "并发甲"
        assert tree["nodes"][str(example.target)]["label"] == "并发乙"
        async with engine.connect() as conn:
            assert await dictionary_version(conn, example.scope, other) == 1
    finally:
        async with engine.begin() as conn:
            await conn.execute(dictionary.delete().where(dictionary.c.id == other))


async def test_inflight_miss_cannot_fill_old_key_with_new_rows(running, example, redis_instance, monkeypatch):
    client, service = running
    original_get = service.cache.get
    selected, resume = asyncio.Event(), asyncio.Event()

    async def pause(key, model, dictionary_id, version):
        if version == 1:
            selected.set()
            await asyncio.wait_for(resume.wait(), 5)
        return await original_get(key, model, dictionary_id, version)

    monkeypatch.setattr(service.cache, "get", pause)
    async with asyncio.TaskGroup() as tasks:
        read = tasks.create_task(client.get(example.path + "/tree", headers=example.headers))
        await asyncio.wait_for(selected.wait(), 5)
        await service.change(example.scope, example.dictionary_id, example.source, "modify", label="新快照")
        resume.set()
    tag_id = str(example.source)
    assert read.result().json()["nodes"][tag_id]["label"] == "样例甲"
    assert json.loads(await redis_instance.get(example.key(1, "tree")))["data"]["nodes"][tag_id]["label"] == "样例甲"
    assert (await snapshots(client, example))[0]["nodes"][tag_id]["label"] == "新快照"
