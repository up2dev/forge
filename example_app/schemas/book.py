from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BookCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200, examples=["Dune"])
    year: int = Field(ge=0, le=2100, examples=[1965])
    author_id: int


class BookUpdate(BaseModel):
    """Tous les champs optionnels : édition partielle (PATCH-like sur
    un PUT), seuls les champs fournis sont modifiés."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=0, le=2100)
    author_id: int | None = None


class AuthorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class BookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    year: int
    author_id: int
    author: AuthorRead | None = None
    created_at: datetime
    updated_at: datetime


class BookList(BaseModel):
    items: list[BookRead]
    total: int
    page: int
    limit: int | None
    total_pages: int
    previous_page: int | None
    next_page: int | None
