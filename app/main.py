"""FastAPI application entry point."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin.routes import router as admin_router
from app.api.auth.routes import router as auth_router
from app.api.public.routes import router as public_router
from app.core.config import settings
from app.core.db import dispose_engine
from app.core.http_cache import no_store
from app.security.tokens import session_secret

logging.basicConfig(level=settings.LOG_LEVEL.upper())
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("starting api in %s mode", settings.APP_ENV)
    session_secret()  # fail fast in production when SESSION_SECRET is missing
    if not settings.admin_email:
        log.warning("ADMIN_EMAIL is not set — nobody can sign in to the admin panel")
    yield
    from app.core.cache import get_redis

    redis = get_redis()
    if redis is not None:
        await redis.aclose()
    await dispose_engine()


app = FastAPI(
    title="chamathdilshan.dev API",
    version="0.2.0",
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
    openapi_url=None if settings.is_production else "/openapi.json",
    lifespan=lifespan,
)

# Explicit origins only — never "*" for an API that carries a session cookie.
# (SECURITY.md §19)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "If-None-Match"],
    max_age=600,
)


@app.get("/api/health")
async def health(response: Response) -> dict[str, str]:
    no_store(response)
    return {"status": "ok"}


app.include_router(public_router, prefix="/api", tags=["public"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
