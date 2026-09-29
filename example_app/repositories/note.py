from __future__ import annotations

from forge.repositories.base import BaseRepository

from example_app.models.note import Note


class NoteRepository(BaseRepository[Note]):
    model = Note
    filters = {"content": "content"}
    owner_column = "user_id"  # chaque utilisateur ne voit/modifie que ses notes
