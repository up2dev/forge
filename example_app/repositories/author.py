from __future__ import annotations

from forge.repositories.base import BaseRepository

from example_app.models.book import Author


class AuthorRepository(BaseRepository[Author]):
    model = Author

    filters = {"name": "name"}
    includes = {"books"}
