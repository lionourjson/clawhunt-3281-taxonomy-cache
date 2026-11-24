from typing import Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.taxonomy.cache import TaxonomyCache, cache_key
from app.taxonomy.models import dictionary, tag
from app.taxonomy.schema import AliasMap, Kind, Scope, TagNode, TagTree

Action = Literal["activate", "modify", "deactivate", "merge"]


class DictionaryNotFound(LookupError):
    pass


class InvalidChange(ValueError):
    pass


def dictionary_filter(scope: Scope, dictionary_id: UUID):
    return (
        dictionary.c.id == dictionary_id,
        dictionary.c.org_id == scope.org_id,
        dictionary.c.site_id == scope.site_id,
        dictionary.c.deleted_at.is_(None),
    )


def tag_filter(scope: Scope, dictionary_id: UUID):
    return (
        tag.c.dictionary_id == dictionary_id,
        tag.c.org_id == scope.org_id,
        tag.c.site_id == scope.site_id,
        tag.c.deleted_at.is_(None),
    )


async def dictionary_version(conn: AsyncConnection, scope: Scope, dictionary_id: UUID, *, lock=False) -> int:
    query = select(dictionary.c.version).where(*dictionary_filter(scope, dictionary_id))
    version = await conn.scalar(query.with_for_update() if lock else query)
    if version is None:
        raise DictionaryNotFound(dictionary_id)
    return version


async def lock_dictionary(conn: AsyncConnection, scope: Scope, dictionary_id: UUID) -> None:
    """Acquire the per-dictionary lock before the caller changes any tag rows."""
    await dictionary_version(conn, scope, dictionary_id, lock=True)


async def bump_version(conn: AsyncConnection, scope: Scope, dictionary_id: UUID) -> int:
    """Call after tag writes, on the transaction that acquired lock_dictionary."""
    query = (
        update(dictionary).where(*dictionary_filter(scope, dictionary_id))
        .values(version=dictionary.c.version + 1, updated_at=func.now())
        .returning(dictionary.c.version)
    )
    version = await conn.scalar(query)
    if version is None:
        raise DictionaryNotFound(dictionary_id)
    return version


def tree_snapshot(rows) -> TagTree:
    nodes = {
        row.id: TagNode(code=row.code, label=row.label, status=row.status, children=[])
        for row in rows if row.status in ("active", "inactive")
    }
    roots = []
    for row in rows:
        if row.id in nodes:
            if row.parent_id in nodes:
                nodes[row.parent_id].children.append(row.id)
            else:
                roots.append(row.id)
    return TagTree(roots=roots, nodes=nodes)


def alias_snapshot(rows) -> AliasMap:
    by_id = {row.id: row for row in rows}
    resolved = {}
    aliases = {}
    for row in rows:
        cursor = row.id
        visited = set()
        while cursor in by_id and cursor not in resolved and cursor not in visited:
            visited.add(cursor)
            entry = by_id[cursor]
            if entry.status != "merged":
                resolved[cursor] = cursor if entry.status == "active" else None
                break
            cursor = entry.merged_into
        target = resolved.get(cursor)
        for source in visited:
            resolved[source] = target
        if target is not None:
            for alias in row.aliases:
                aliases.setdefault(alias, target)
    return AliasMap(aliases=aliases)


class TaxonomyService:
    def __init__(self, engine: AsyncEngine, cache: TaxonomyCache):
        self.engine = engine
        self.snapshot_engine = engine.execution_options(isolation_level="REPEATABLE READ")
        self.cache = cache

    async def read(self, scope: Scope, dictionary_id: UUID, kind: Kind) -> TagTree | AliasMap:
        model, project = (TagTree, tree_snapshot) if kind == "tree" else (AliasMap, alias_snapshot)
        # Cache identity and payload must come from the same PostgreSQL snapshot.
        async with self.snapshot_engine.begin() as conn:
            identity = (await conn.execute(
                select(dictionary.c.cache_generation, dictionary.c.version)
                .where(*dictionary_filter(scope, dictionary_id)),
            )).one_or_none()
            if identity is None:
                raise DictionaryNotFound(dictionary_id)
            generation, version = identity
            key = cache_key(scope.org_id, dictionary_id, generation, version, kind)
            lookup = await self.cache.get(key, model, dictionary_id, version)
            if lookup.data is not None:
                return lookup.data
            rows = (await conn.execute(
                select(tag).where(*tag_filter(scope, dictionary_id)).order_by(tag.c.code, tag.c.id),
            )).all()
        data = project(rows)
        if lookup.can_fill:
            await self.cache.put(key, dictionary_id, version, data)
        return data

    async def change(
        self, scope: Scope, dictionary_id: UUID, tag_id: UUID, action: Action,
        *, label: str | None = None, target_id: UUID | None = None,
    ) -> int:
        """Local integration example. Production callers can use the transaction hooks directly."""
        async with self.engine.begin() as conn:
            await lock_dictionary(conn, scope, dictionary_id)
            filters = tag_filter(scope, dictionary_id)
            rows = (await conn.execute(select(tag).where(*filters))).all()
            tags = {row.id: row for row in rows}
            source = tags.get(tag_id)
            if source is None or source.status == "merged":
                raise InvalidChange("source tag is missing or merged")
            if action == "modify":
                if not isinstance(label, str) or not label.strip() or len(label) > 128 or "\x00" in label:
                    raise InvalidChange("label must contain 1–128 characters")
                values = {"label": label}
            elif action == "activate":
                values = {"status": "active"}
            elif action == "deactivate":
                values = {"status": "inactive"}
            elif action == "merge":
                target = tags.get(target_id)
                if target is None or target.status != "active":
                    raise InvalidChange("target must be an active tag in the same dictionary")
                validate_merge_target(tags, tag_id, target.id)
                await conn.execute(
                    update(tag).where(*filters, tag.c.parent_id == tag_id)
                    .values(parent_id=target.id, updated_at=func.now()),
                )
                values = {"status": "merged", "merged_into": target.id}
            else:
                raise InvalidChange("unknown action")
            await conn.execute(
                update(tag).where(*filters, tag.c.id == tag_id).values(**values, updated_at=func.now()),
            )
            return await bump_version(conn, scope, dictionary_id)


def validate_merge_target(tags, source_id: UUID, target_id: UUID) -> None:
    visited = {source_id}
    cursor = target_id
    while cursor in tags:
        if cursor in visited:
            raise InvalidChange("merge would create or reuse a parent cycle")
        visited.add(cursor)
        cursor = tags[cursor].parent_id
