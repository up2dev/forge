from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import inspect as sa_inspect

from forge.controllers.base import BaseController
from forge.security.dependencies import get_current_user_optional
from forge.security.models import User

from example_app.repositories.book import BookRepository
from example_app.schemas.book import AuthorRead, BookCreate, BookList, BookRead, BookUpdate


def _to_book_read(book) -> BookRead:
    """
    `author` n'est inclus que si la relation a été explicitement
    chargée (via ?with=author, cf. BookRepository.includes) — y
    accéder sinon déclencherait un lazy-load implicite, qui échoue en
    async SQLAlchemy dès que la session est fermée (DetachedInstanceError).

    Construit à la main (pas via `BookRead.model_validate(book)`
    directement) : `from_attributes=True` lirait `book.author` dans
    tous les cas, y compris quand ce n'est pas chargé — exactement le
    déclencheur du bug qu'on évite ici.
    """
    loaded = "author" not in sa_inspect(book).unloaded

    return BookRead(
        id=book.id,
        title=book.title,
        year=book.year,
        author_id=book.author_id,
        author=AuthorRead.model_validate(book.author) if loaded and book.author else None,
        created_at=book.created_at,
        updated_at=book.updated_at,
    )


class BookController(BaseController[BookRepository]):
    """
    Surcharge list/show/add/edit avec des schémas Pydantic explicites
    (BookCreate/BookUpdate en entrée, BookRead/BookList en sortie).
    C'est ce typage qui alimente /docs avec les vrais champs
    attendus/retournés pour cette ressource.

    remove/mass_add/mass_edit/mass_remove restent génériques.
    """

    async def list(self, request: Request) -> BookList:
        result = await self.repo.all(query_context=request.state.query_context)

        return BookList(
            items=[_to_book_read(b) for b in result.items],
            total=result.total,
            page=result.page,
            limit=result.limit,
            total_pages=result.total_pages,
            previous_page=result.previous_page,
            next_page=result.next_page,
        )

    async def show(self, uid: int, request: Request) -> BookRead:
        item = await self.repo.read(uid, query_context=request.state.query_context)

        if item is None:
            raise HTTPException(404, "Book not found")

        return _to_book_read(item)

    async def add(
        self, payload: BookCreate, user: User | None = Depends(get_current_user_optional)
    ) -> BookRead:
        actor_id = user.id if user else None
        item = await self.repo.create(payload.model_dump(), actor_id=actor_id)

        return _to_book_read(item)

    async def edit(
        self,
        uid: int,
        payload: BookUpdate,
        user: User | None = Depends(get_current_user_optional),
    ) -> BookRead:
        actor_id = user.id if user else None
        item = await self.repo.update(uid, payload.model_dump(exclude_unset=True), actor_id=actor_id)

        if item is None:
            raise HTTPException(404, "Book not found")

        return _to_book_read(item)
