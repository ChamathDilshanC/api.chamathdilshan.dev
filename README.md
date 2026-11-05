# api.chamathdilshan.dev — Backend

FastAPI service providing the content API behind every editable part of the
site, owner-only sign-in (Google + emailed code via Resend), the contact form
(emailed to the owner via Resend), Cloudinary media,
caching and audit logging for the chamathdilshan.dev platform.

Setup and usage of the admin panel: `docs/ADMIN_CMS.md` in the main repo.

This repository is a **submodule** of
[ChamathDilshanC/chamathdilshan](https://github.com/ChamathDilshanC/chamathdilshan).
It deploys on its own, with the repo root as the app root.

---

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

cp .env.example .env               # fill in ADMIN_EMAIL, GOOGLE_*, CLOUDINARY_*
alembic upgrade head               # create the tables (SQLite by default)
python -m app.seed --sections      # optional: load the current site content
uvicorn app.main:app --reload      # http://localhost:8000
```

OpenAPI docs: `http://localhost:8000/docs` (disabled in production).

---

## Structure

```text
app/
├── main.py            application entry point, CORS, health, routers
├── api/
│   ├── content/       /api/content, /api/projects, /api/posts, /api/skills, /api/experience
│   ├── contact/       POST /api/contact — contact form emailed to the owner
│   ├── admin/         owner-only CRUD — sections, projects, posts, skills, experience, media
│   └── auth/          Google sign-in, emailed code, session
├── core/
│   ├── config.py      settings from environment
│   ├── db.py          async SQLAlchemy engine and base
│   ├── cache.py       Redis cache-aside, tag invalidation, frontend revalidate
│   └── http_cache.py  Cache-Control / ETag policies
├── models/            SQLAlchemy models
├── schemas/           Pydantic models — also the admin form definitions
├── services/          business logic (owns cache invalidation on mutation)
├── integrations/      Google, Resend, Cloudinary
├── security/          sessions, origin check, rate limiting, signed cookies
└── seed/              default content + `python -m app.seed`
migrations/            Alembic

tests/
├── unit/
└── integration/
```

---

## Authorization

Admin sign-in is Google OpenID Connect restricted to `ADMIN_EMAIL` (and the
immutable Google `sub` when `ADMIN_GOOGLE_SUB` is set), followed by a 6-digit
code emailed through Resend. Every `/api/admin/*` endpoint verifies the session
and, for writes, the request Origin server-side — route obscurity is not a
security control.

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
