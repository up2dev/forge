from __future__ import annotations

from forge.repositories.base import BaseRepository

from example_app.models.book import Book


class BookRepository(BaseRepository[Book]):
    model = Book

    # ?filters=title:lk(dune) ou ?sort=year.desc
    filters = {
        "title": "title",
        "year": "year",
        "author_id": "author_id",
    }

    # ?with=author — toute autre relation demandée est ignorée
    includes = {"author"}

    # Journalise create/update/delete dans ActivityLog — voir forge/audit.py
    loggable = True
