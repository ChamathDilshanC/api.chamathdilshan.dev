"""Audit trail for admin and authentication events (SECURITY.md — auditability)."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor: str = "",
    target: str = "",
    ip: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(AuditLog(action=action, actor=actor, target=target[:200], ip=ip, detail=detail or {}))
    await db.commit()


async def recent(db: AsyncSession, limit: int = 50) -> list[AuditLog]:
    rows = await db.scalars(select(AuditLog).order_by(AuditLog.at.desc(), AuditLog.id.desc())
                            .limit(limit))
    return list(rows)
