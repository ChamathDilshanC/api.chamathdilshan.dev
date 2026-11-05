"""Fill an empty database with the default content.

    python -m app.seed            # only fills tables that are empty
    python -m app.seed --sections # also writes sections that were never saved

Sections never need seeding to render (the API serves the defaults for any
section that has not been saved), but writing them makes the database the
single source of truth. The seed file is generated from the frontend's
content/*.ts with `npm run export:seed`.
"""

import argparse
import asyncio
import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import dispose_engine, get_sessionmaker
from app.models import Post, Project, Section, Skill
from app.schemas.entities import PostIn, ProjectIn, SkillIn
from app.schemas.sections import SECTIONS
from app.services.common import dump
from app.services.sections import seed

log = logging.getLogger("seed")


async def _empty(db: AsyncSession, model: type[Project] | type[Post] | type[Skill]) -> bool:
    return int(await db.scalar(select(func.count()).select_from(model)) or 0) == 0


async def run(with_sections: bool) -> None:
    data = seed()
    async with get_sessionmaker()() as db:
        if await _empty(db, Project):
            for position, raw in enumerate(data.get("projects", []), start=1):
                item = ProjectIn.model_validate({**raw, "published": True})
                db.add(
                    Project(
                        slug=raw["slug"], title=item.title, category=item.category,
                        year=item.year, summary=item.summary, thumbnail=dump(item.thumbnail),
                        hero=dump(item.hero), intro=item.intro, discover=item.discover,
                        explore=item.explore, results=[dump(r) for r in item.results],
                        gallery=[dump(g) for g in item.gallery], tech=item.tech,
                        live_url=item.live_url, repo_url=item.repo_url, featured=item.featured,
                        published=True, sort_order=position,
                    )
                )
            log.info("seeded %d projects", len(data.get("projects", [])))

        if await _empty(db, Post):
            for raw in data.get("posts", []):
                post = PostIn.model_validate({**raw, "published": True})
                db.add(
                    Post(
                        slug=raw["slug"], title=post.title, category=post.category,
                        date=date.fromisoformat(str(post.date)), excerpt=post.excerpt,
                        cover=dump(post.cover), sections=[dump(s) for s in post.sections],
                        published=True,
                    )
                )
            log.info("seeded %d posts", len(data.get("posts", [])))

        if await _empty(db, Skill):
            for position, raw in enumerate(data.get("skills", []), start=1):
                skill = SkillIn.model_validate(raw)
                db.add(Skill(name=skill.name, category=skill.category, icon=skill.icon,
                             featured=skill.featured, visible=skill.visible, sort_order=position))
            log.info("seeded %d skills", len(data.get("skills", [])))

        if with_sections:
            stored = set(await db.scalars(select(Section.key)))
            for key_, spec in SECTIONS.items():
                if key_ not in stored and key_ in data.get("sections", {}):
                    clean = dump(spec.model.model_validate(data["sections"][key_]))
                    db.add(Section(key=key_, data=clean))
                    log.info("seeded section %s", key_)

        await db.commit()
    # aiosqlite runs on a worker thread that keeps the process alive until disposed.
    await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", action="store_true", help="also write unsaved sections")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(run(args.sections))


if __name__ == "__main__":
    main()
