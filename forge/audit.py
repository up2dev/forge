"""
forge.audit
===========
Change tracking for models that opt in. Set `loggable = True` on a
Repository and create/update/delete get recorded — no base class to
inherit, just the flag.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from forge.db import get_session
from forge.models.base import Base, TimestampMixin

logger = logging.getLogger("forge.audit")


class ActivityLog(Base, TimestampMixin):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(80), index=True)
    record_id: Mapped[int] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(20))  # create | update | delete
    actor_id: Mapped[int | None] = mapped_column(nullable=True)
    changes: Mapped[str | None] = mapped_column(String(4000), nullable=True)  # JSON


async def log_activity(
    model: str, record_id: int, action: str, actor_id: int | None, changes: dict[str, Any] | None = None
) -> None:
    payload = json.dumps(changes, default=str) if changes else None

    async with get_session() as session:
        session.add(
            ActivityLog(model=model, record_id=record_id, action=action, actor_id=actor_id, changes=payload)
        )
        await session.commit()

    # Also to the log file — grep-able without a DB query.
    logger.info("%s %s#%s by actor=%s changes=%s", action, model, record_id, actor_id, payload)
