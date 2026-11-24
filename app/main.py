from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.taxonomy.cache import TaxonomyCache, redis_client
from app.taxonomy.schema import AliasMap, Kind, Scope, TagTree
from app.taxonomy.service import DictionaryNotFound, TaxonomyService


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = create_async_engine(config.database_url, pool_pre_ping=True)
        redis = redis_client(config)
        app.state.taxonomy = TaxonomyService(engine, TaxonomyCache(redis, config))
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(title="Taxonomy cache", lifespan=lifespan)

    def caller_scope(request: Request) -> Scope:
        authenticated = getattr(request.state, "taxonomy_scope", None)
        if isinstance(authenticated, Scope):
            return authenticated
        if config.demo_mode:
            try:
                return Scope(UUID(request.headers["X-Org-ID"]), UUID(request.headers["X-Site-ID"]))
            except (KeyError, ValueError):
                pass
        raise HTTPException(403, "Tenant scope is required")

    async def read(request: Request, scope: Scope, dictionary_id: UUID, kind: Kind):
        try:
            return await request.app.state.taxonomy.read(scope, dictionary_id, kind)
        except DictionaryNotFound as exc:
            raise HTTPException(404, "Dictionary not found") from exc

    router_path = "/taxonomy/dictionaries/{dictionary_id}"

    @app.get(router_path + "/tree", response_model=TagTree)
    async def read_tree(request: Request, dictionary_id: UUID, scope: Scope = Depends(caller_scope)):
        return await read(request, scope, dictionary_id, "tree")

    @app.get(router_path + "/aliases", response_model=AliasMap)
    async def read_aliases(request: Request, dictionary_id: UUID, scope: Scope = Depends(caller_scope)):
        return await read(request, scope, dictionary_id, "alias")

    return app
