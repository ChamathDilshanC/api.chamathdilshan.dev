"""Redis cache-aside layer with stampede protection and tag invalidation.

Implements CACHING.md §9 and §10. A Redis outage degrades performance only —
every helper falls back to loading straight from the database.
"""

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings

log = logging.getLogger(__name__)

_redis: Redis | None = None


def get_redis() -> Redis | None:
    global _redis
    if not settings.CACHE_ENABLED:
        return None
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


def key(*parts: str) -> str:
    """Namespaced cache key. Bump CACHE_NAMESPACE to invalidate everything."""
    return ":".join([settings.CACHE_NAMESPACE, *parts])


def _jitter(ttl: int) -> int:
    """Spread expiry so many keys never die at the same instant."""
    return ttl + random.randint(0, max(1, ttl // 10))  # noqa: S311


async def get_or_set(
    cache_key: str,
    ttl: int,
    tags: list[str],
    loader: Callable[[], Awaitable[Any]],
) -> Any:
    """Return the cached value, or load it once and cache it under `tags`."""
    redis = get_redis()
    if redis is None:
        return await loader()

    try:
        hit = await redis.get(cache_key)
        if hit is not None:
            return json.loads(hit)
    except RedisError:
        log.warning("cache read failed for %s — falling back to origin", cache_key)
        return await loader()

    lock = key("lock", cache_key)
    try:
        got_lock = await redis.set(lock, "1", nx=True, ex=10)
        if not got_lock:
            # Another worker is loading it; wait briefly for its result.
            for _ in range(50):
                await asyncio.sleep(0.1)
                hit = await redis.get(cache_key)
                if hit is not None:
                    return json.loads(hit)

        value = await loader()
        payload = json.dumps(value, default=str)
        expiry = _jitter(ttl)

        pipe = redis.pipeline()
        pipe.set(cache_key, payload, ex=expiry)
        for tag in tags:
            pipe.sadd(key("tag", tag), cache_key)
            pipe.expire(key("tag", tag), expiry + 3600)
        await pipe.execute()
        return value
    except RedisError:
        log.warning("cache write failed for %s — serving uncached", cache_key)
        return await loader()
    finally:
        try:
            await redis.delete(lock)
        except RedisError:
            pass


async def invalidate_tags(*tags: str) -> None:
    """Delete every cached key registered under the given tags."""
    redis = get_redis()
    if redis is None:
        return
    try:
        keys: set[str] = set()
        for tag in tags:
            # decode_responses=True gives str, but the stubs still widen to
            # bytes | str — normalise so this holds either way.
            members = await redis.smembers(key("tag", tag))
            keys.update(m.decode() if isinstance(m, bytes) else str(m) for m in members)

        pipe = redis.pipeline()
        for tag in tags:
            pipe.delete(key("tag", tag))
        for k in keys:
            pipe.delete(k)
        await pipe.execute()
        log.info("invalidated %d keys across tags %s", len(keys), list(tags))
    except RedisError:
        log.exception("tag invalidation failed for %s", tags)


async def revalidate_frontend(tags: list[str], paths: list[str]) -> None:
    """Tell Next.js to drop its Data Cache and Full Route Cache entries.

    Never raises — a failed revalidation must not fail the admin request.
    (CACHING.md §10.2)
    """
    if not settings.CACHE_REVALIDATE_SECRET:
        return
    try:
        # The public host may redirect to its canonical www host before the
        # route runs. Follow that redirect so cache invalidation is not
        # silently skipped after an admin mutation.
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.post(
                f"{settings.frontend_revalidation_url}/api/revalidate",
                headers={"x-revalidate-secret": settings.CACHE_REVALIDATE_SECRET},
                json={"tags": tags, "paths": paths},
            )
            if response.is_error:
                log.error(
                    "frontend revalidation rejected with HTTP %s: tags=%s paths=%s",
                    response.status_code,
                    tags,
                    paths,
                )
            response.raise_for_status()
    except httpx.HTTPError:
        log.exception("frontend revalidation failed: tags=%s paths=%s", tags, paths)


async def flush_content(tags: list[str], paths: list[str]) -> None:
    """The standard post-commit invalidation for an admin mutation."""
    await invalidate_tags(*tags)
    await revalidate_frontend(tags, paths)
