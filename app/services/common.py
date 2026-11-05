"""Helpers shared by the content services."""

import re
import unicodedata
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute


def slugify(text: str, max_length: int = 80) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug[:max_length].strip("-") or "untitled"


async def unique_slug(
    db: AsyncSession,
    column: InstrumentedAttribute[str],
    wanted: str,
    *,
    exclude_id: int | None = None,
    id_column: InstrumentedAttribute[int] | None = None,
) -> str:
    """`wanted`, or `wanted-2`, `wanted-3`… — whichever is free."""
    candidate, n = wanted, 1
    while True:
        query = select(column).where(column == candidate)
        if exclude_id is not None and id_column is not None:
            query = query.where(id_column != exclude_id)
        if await db.scalar(query) is None:
            return candidate
        n += 1
        candidate = f"{wanted[: 80 - len(str(n)) - 1]}-{n}"


def not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found.")


def conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=message)


def dump(model: Any) -> Any:
    """Pydantic model → JSON-ready camelCase dict (what is stored and what is served)."""
    if model is None:
        return None
    return model.model_dump(by_alias=True, mode="json")
