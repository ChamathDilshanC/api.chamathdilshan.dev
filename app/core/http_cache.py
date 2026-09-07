"""HTTP cache-control policies for API responses.

Implements CACHING.md §6. Every public GET must apply one of the PUBLIC_*
policies; anything session-dependent must apply PRIVATE.
"""

import hashlib

from fastapi import Response

# public, shared-cacheable
PUBLIC_STABLE = "public, s-maxage=3600, stale-while-revalidate=86400, stale-if-error=604800"
PUBLIC_CONTENT = "public, s-maxage=300, stale-while-revalidate=86400, stale-if-error=604800"
PUBLIC_DYNAMIC = "public, s-maxage=30, stale-while-revalidate=300, stale-if-error=86400"

# never stored anywhere
PRIVATE = "private, no-store, max-age=0"

# long-lived, content-hashed assets only
IMMUTABLE = "public, max-age=31536000, immutable"


def apply_cache(response: Response, policy: str, body: bytes | None = None) -> None:
    """Attach the cache policy, Vary, and an ETag for conditional requests."""
    response.headers["Cache-Control"] = policy

    if policy == PRIVATE:
        response.headers["Vary"] = "Cookie, Authorization"
        return

    response.headers["Vary"] = "Accept-Encoding"
    if body is not None:
        digest = hashlib.sha256(body).hexdigest()[:32]
        response.headers["ETag"] = f'W/"sha256-{digest}"'


def no_store(response: Response) -> None:
    """Shorthand for admin / auth / contact / health responses."""
    apply_cache(response, PRIVATE)
