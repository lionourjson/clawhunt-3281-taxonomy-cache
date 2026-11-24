import asyncio
import json
import logging
import socket
from contextlib import suppress
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, update

from app.config import Settings
from app.taxonomy.models import dictionary, tag
from conftest import run_app


async def read(client, example, part="tree"):
    result = await client.get(example.path + "/" + part, headers=example.headers)
    assert result.status_code == 200
    return result.json()


async def test_unreachable_redis_returns_database_data_and_throttles_warning(settings, example, caplog):
    caplog.set_level(logging.WARNING, logger="app.taxonomy.cache")
    # A bound, non-listening socket keeps the locally unreachable port reserved during the test.
    with socket.socket() as port:
        port.bind(("127.0.0.1", 0))
        offline = settings.model_copy(update={"redis_url": f"redis://127.0.0.1:{port.getsockname()[1]}/0"})
        async with run_app(offline) as (client, service):
            sample = await read(client, example)
            assert sample["nodes"][str(example.source)]["label"] == "样例甲"
            assert await service.change(example.scope, example.dictionary_id, example.source, "modify", label="降级新值") == 2
            assert (await read(client, example))["nodes"][str(example.source)]["label"] == "降级新值"
            assert (await read(client, example, "aliases"))["aliases"]["甲"] == str(example.source)
    warnings = [item.message for item in caplog.records if item.name == "app.taxonomy.cache"]
    expected = {f"Taxonomy cache GET failed ({reason}). Using PostgreSQL data." for reason in ("timeout", "redis error")}
    assert warnings and set(warnings) <= expected
    assert len(warnings) == len(set(warnings))


@pytest.mark.parametrize("command", ["GET", "SET"])
async def test_disconnect_mid_command_and_automatic_recovery(command, settings, running, example, redis_instance, caplog):
    caplog.set_level(logging.WARNING, logger="app.taxonomy.cache")
    client, service = running
    backend = redis_instance.connection_pool.connection_kwargs
    dropped = asyncio.Event()
    marker = f"${len(command)}\r\n{command}\r\n".encode()

    async def relay(incoming, outgoing):
        upstream, writer = await asyncio.open_connection(backend["host"], backend["port"])

        async def to_redis():
            window = b""
            while chunk := await incoming.read(65536):
                if not dropped.is_set() and marker in window + chunk:
                    dropped.set()
                    return
                window = chunk[-len(marker):]
                writer.write(chunk)
                await writer.drain()

        async def from_redis():
            while chunk := await upstream.read(65536):
                outgoing.write(chunk)
                await outgoing.drain()

        tasks = {asyncio.create_task(to_redis()), asyncio.create_task(from_redis())}
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            outgoing.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
                await outgoing.wait_closed()

    server = await asyncio.start_server(relay, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    proxied = settings.model_copy(update={"redis_url": f"redis://127.0.0.1:{port}/{backend.get('db', 0)}"})
    original = await read(client, example)
    assert await service.change(example.scope, example.dictionary_id, example.source, "modify", label="恢复后") == 2
    new_key = example.key(2, "tree")
    async with server, run_app(proxied) as (proxy_client, _):
        first = await read(proxy_client, example)
        assert first != original and first["nodes"][str(example.source)]["label"] == "恢复后"
        assert dropped.is_set() and not await redis_instance.exists(new_key)
        assert await read(proxy_client, example) == first
        assert await redis_instance.exists(new_key)
    assert any(item.name == "app.taxonomy.cache" and f"{command} failed" in item.message for item in caplog.records)


async def test_timeout_falls_back_without_attempting_cache_fill(running, example, redis_instance, monkeypatch, caplog):
    client, service = running
    cancelled = asyncio.Event()

    async def hung_get(key):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    monkeypatch.setattr(service.cache.redis, "get", hung_get)
    service.cache.timeout = 0.02
    response = await asyncio.wait_for(read(client, example), timeout=2)
    assert response["nodes"] and cancelled.is_set()
    assert not await redis_instance.exists(example.key(1, "tree"))
    assert "GET failed (timeout)" in caplog.text


@pytest.mark.parametrize("corruption", [b"\xff", b"{", b'{"data":{"nodes":{}},"version":1}', "wrong_version"])
async def test_corrupt_values_fall_back_without_overwriting(corruption, running, redis_instance, example, caplog):
    client, _ = running
    key = example.key(1, "tree")
    if corruption == "wrong_version":
        corruption = json.dumps({"version": 2, "dictionary_id": str(example.dictionary_id), "data": {"roots": [], "nodes": {}}}).encode()
    await redis_instance.set(key, corruption, ex=30)
    assert (await read(client, example))["nodes"][str(example.source)]["label"] == "样例甲"
    assert await redis_instance.get(key) == corruption
    assert "GET failed (invalid value)" in caplog.text


async def test_invalid_utf8_with_redis_response_decoding(settings, example, redis_instance, caplog):
    key = example.key(1, "tree")
    await redis_instance.set(key, b"\xff", ex=30)
    separator = "&" if "?" in settings.redis_url else "?"
    decoded = settings.model_copy(update={"redis_url": f"{settings.redis_url}{separator}decode_responses=true"})
    async with run_app(decoded) as (client, _):
        assert (await read(client, example))["nodes"][str(example.source)]["label"] == "样例甲"
    assert "GET failed (invalid value)" in caplog.text


async def test_keys_defaults_empty_snapshots_cache_hits_and_configured_expiry(settings, example, engine, redis_instance):
    assert Settings(database_url="db", redis_url="redis").cache_ttl_seconds == 86400
    assert Settings(database_url="db", redis_url="redis").cache_timeout_ms == 200
    short_lived = settings.model_copy(update={"cache_ttl_seconds": 1})
    async with engine.begin() as conn:
        await conn.execute(update(tag).where(tag.c.dictionary_id == example.dictionary_id).values(deleted_at=func.now()))
    async with run_app(short_lived) as (client, _):
        keys = [example.key(1, "tree"), example.key(1, "alias")]
        expected = {"tree": {"roots": [], "nodes": {}}, "aliases": {"aliases": {}}}
        for part, payload in expected.items():
            assert await read(client, example, part) == payload
        assert await redis_instance.exists(*keys) == 2
        for key in keys:
            assert 0 < await redis_instance.pttl(key) <= 1000
        # Deliberate out-of-band write to distinguish a cache hit from a new DB query.
        async with engine.begin() as conn:
            await conn.execute(update(tag).where(tag.c.id == example.source).values(deleted_at=None))
        for part, payload in expected.items():
            assert await read(client, example, part) == payload
        for _ in range(30):
            if not await redis_instance.exists(*keys):
                break
            await asyncio.sleep(0.05)
        assert not await redis_instance.exists(*keys)
        assert (await read(client, example))["nodes"]
        assert (await read(client, example, "aliases"))["aliases"]["甲"] == str(example.source)


async def test_request_scope_and_soft_deleted_dictionary(running, settings, example, engine):
    client, _ = running
    path = example.path + "/tree"
    assert (await client.get(path)).status_code == 403
    assert (await client.get(path, headers=example.headers | {"X-Org-ID": "invalid"})).status_code == 403
    assert (await client.get("/taxonomy/dictionaries/invalid/tree", headers=example.headers)).status_code == 422
    for field in ("X-Org-ID", "X-Site-ID"):
        assert (await client.get(path, headers=example.headers | {field: str(uuid4())})).status_code == 404
    async with run_app(settings.model_copy(update={"demo_mode": False})) as (production, _):
        assert (await production.get(path, headers=example.headers)).status_code == 403
    await read(client, example)
    async with engine.begin() as conn:
        await conn.execute(update(dictionary).where(dictionary.c.id == example.dictionary_id).values(deleted_at=func.now()))
    assert (await client.get(path, headers=example.headers)).status_code == 404


@pytest.mark.parametrize("field,limit", [("cache_ttl_seconds", 2_147_483_647), ("cache_timeout_ms", 60_000)])
def test_config_bounds_and_bad_types(field, limit):
    baseline = {"database_url": "db", "redis_url": "redis"}
    assert getattr(Settings(**baseline, **{field: limit}), field) == limit
    assert getattr(Settings(**baseline, **{field: 1}), field) == 1
    for invalid in (0, limit + 1, "invalid", 1.5):
        with pytest.raises(ValidationError):
            Settings(**baseline, **{field: invalid})
