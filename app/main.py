"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.http_cache import no_store

logging.basicConfig(level=settings.LOG_LEVEL.upper())
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting api in %s mode", settings.APP_ENV)
    yield
    from app.core.cache import get_redis

    redis = get_redis()
    if redis is not None:
        await redis.aclose()


app = FastAPI(
    title="chamathdilshan.dev API",
    version="0.1.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# Explicit origins only — never "*" for an API that carries a session cookie.
# (SECURITY.md §19)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/api/health")
async def health(response: Response) -> dict[str, str]:
    no_store(response)
    return {"status": "ok"}


# Routers are registered here as they are implemented:
#
# from app.api.public import profile, projects, blog, research, contact, search
# from app.api.admin  import dashboard, projects as admin_projects, media, settings
# from app.api.auth   import github
#
# app.include_router(github.router,  prefix="/api/auth",  tags=["auth"])
# app.include_router(profile.router, prefix="/api",       tags=["public"])
# app.include_router(dashboard.router, prefix="/api/admin", tags=["admin"])
