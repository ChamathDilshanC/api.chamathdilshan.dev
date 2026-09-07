# api.chamathdilshan.dev — Backend

FastAPI service providing the REST API, GitHub OAuth authentication,
owner-only authorization, content management, media handling, caching and
audit logging for the chamathdilshan.dev platform.

This repository is a **submodule** of
[ChamathDilshanC/chamathdilshan](https://github.com/ChamathDilshanC/chamathdilshan).
It deploys on its own, with the repo root as the app root.

---

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env               # fill in DB, OAuth, Redis
uvicorn app.main:app --reload      # http://localhost:8000
```

OpenAPI docs: `http://localhost:8000/docs` (disabled in production).

---

## Structure

```text
app/
├── main.py            application entry point, CORS, health, routers
├── api/
│   ├── public/        unauthenticated read endpoints
│   ├── admin/         owner-only endpoints — all behind authorization
│   └── auth/          GitHub OAuth start + callback + session
├── core/
│   ├── config.py      settings from environment
│   ├── cache.py       Redis cache-aside, tag invalidation, frontend revalidate
│   ├── http_cache.py  Cache-Control / ETag policies
│   ├── security.py    session handling, owner verification
│   └── logging.py
├── models/            SQLAlchemy models
├── schemas/           Pydantic request/response models
├── services/          business logic (owns cache invalidation on mutation)
├── repositories/      database access
├── integrations/      Supabase, GitHub, storage clients
└── security/          middleware, rate limiting, validation helpers

tests/
├── unit/
└── integration/
```

---

## Authorization

Admin access is GitHub OAuth plus an allowlist on the **immutable numeric
GitHub user ID** (`GITHUB_OWNER_ID`). Every `/api/admin/*` endpoint verifies
the session server-side — route obscurity is not a security control.

See `docs/SECURITY.md` in the main repo.

---

## Caching

Two tiers: a small in-process TTL cache for hot settings, and Redis cache-aside
for public payloads and aggregates. Every mutation runs the post-commit flush:

```python
await flush_content(
    tags=["blog", f"post:{slug}", "content"],
    paths=["/blog", f"/blog/{slug}", "/"],
)
```

Redis being unavailable degrades performance only — never correctness.

See `docs/CACHING.md` in the main repo.

---

## Commands

| Command | Does |
|---|---|
| `uvicorn app.main:app --reload` | Development server |
| `ruff check .` | Lint |
| `mypy app` | Type check |
| `pytest` | Tests |
| `alembic upgrade head` | Apply migrations |
| `docker build -t api .` | Build container |

---

## Commit policy

Author and committer must be `ChamathDilshanC`. No AI attribution trailers.
See `GITPUSH.md` in the main repo.
