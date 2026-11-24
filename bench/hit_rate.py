"""Measure two read routes against a dedicated Redis and a migrated PostgreSQL database."""
import argparse
import asyncio
import math
import platform
from time import perf_counter
from uuid import uuid4

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, insert, text

from app.config import Settings
from app.main import create_app
from app.taxonomy.models import dictionary, tag
from app.taxonomy.schema import Scope


async def benchmark(args):
    settings = Settings.from_env().model_copy(update={"demo_mode": True})
    app = create_app(settings)
    scope = Scope(uuid4(), uuid4())
    actor = uuid4()
    ids = [uuid4() for _ in range(args.dictionaries)]
    scope_fields = dict(org_id=scope.org_id, site_id=scope.site_id, created_by=actor)
    headers = {"X-Org-ID": str(scope.org_id), "X-Site-ID": str(scope.site_id)}
    paths = [f"/taxonomy/dictionaries/{dictionary_id}/{part}" for dictionary_id in ids for part in ("tree", "aliases")]
    latencies = []
    first_tag_ids = []
    async with app.router.lifespan_context(app):
        service = app.state.taxonomy
        redis = service.cache.redis
        async with service.engine.begin() as conn:
            pg_version = await conn.scalar(text("SHOW server_version"))
            await conn.execute(insert(dictionary), [dict(id=item, **scope_fields) for item in ids])
            for item in ids:
                root = uuid4()
                first_tag_ids.append(root)
                await conn.execute(insert(tag), [
                    dict(id=root if n == 0 else uuid4(), dictionary_id=item, parent_id=None if n == 0 else root,
                         code=f"sample-{n:04d}", label=f"样例 {n}", aliases=[f"别名{n}"], status="active", **scope_fields)
                    for n in range(args.tags)
                ])
        try:
            redis_version = (await redis.info("server"))["redis_version"]
            start_stats = await redis.info("stats")
            start = perf_counter()
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://benchmark") as client:
                async def timed_read(path):
                    began = perf_counter()
                    response = await client.get(path, headers=headers)
                    response.raise_for_status()
                    latencies.append((perf_counter() - began) * 1000)

                for cycle in range(args.cycles):
                    if cycle:
                        for item, tag_id in zip(ids, first_tag_ids, strict=True):
                            await service.change(scope, item, tag_id, "modify", label=f"样例变更 {cycle}")
                    for _ in range(args.rounds):
                        await asyncio.gather(*(timed_read(path) for path in paths))
            elapsed = perf_counter() - start
            end_stats = await redis.info("stats")
        finally:
            async with service.engine.begin() as conn:
                await conn.execute(delete(tag).where(tag.c.org_id == scope.org_id))
                await conn.execute(delete(dictionary).where(dictionary.c.org_id == scope.org_id))
            keys = [key async for key in redis.scan_iter(f"taxonomy:{scope.org_id}:*")]
            if keys:
                await redis.delete(*keys)

    hits = end_stats["keyspace_hits"] - start_stats["keyspace_hits"]
    misses = end_stats["keyspace_misses"] - start_stats["keyspace_misses"]
    if hits + misses != len(latencies):
        raise RuntimeError("Redis counters differ from HTTP reads; check cache failures or shared Redis use.")
    latencies.sort()
    p50 = latencies[math.ceil(0.50 * len(latencies)) - 1]
    p95 = latencies[math.ceil(0.95 * len(latencies)) - 1]
    print(f"OS={platform.system()} {platform.release()} Python={platform.python_version()}")
    print(f"PostgreSQL={pg_version} Redis={redis_version}")
    print(f"dictionaries={args.dictionaries} tags_per_dictionary={args.tags} cycles={args.cycles} rounds_per_cycle={args.rounds}")
    print(f"concurrent_reads_per_round={len(paths)} writes={len(ids) * (args.cycles - 1)} http_2xx={len(latencies)}")
    print(f"redis_hits={hits} redis_misses={misses} hit_rate={100 * hits / (hits + misses):.2f}%")
    print(f"elapsed_seconds={elapsed:.3f} reads_per_second={len(latencies) / elapsed:.2f} p50_ms={p50:.2f} p95_ms={p95:.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionaries", type=int, default=12, choices=range(1, 33), metavar="1–32")
    parser.add_argument("--tags", type=int, default=48, choices=range(1, 501), metavar="1–500")
    parser.add_argument("--cycles", type=int, default=3, choices=range(1, 21), metavar="1–20")
    parser.add_argument("--rounds", type=int, default=20, choices=range(1, 101), metavar="1–100")
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(benchmark(parser.parse_args()))


if __name__ == "__main__":
    main()
