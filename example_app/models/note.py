from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from forge.models.base import Base, TimestampMixin


class Note(Base, TimestampMixin):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(String(2000))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
