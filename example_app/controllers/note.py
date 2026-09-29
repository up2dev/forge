from forge.controllers.base import BaseController

from example_app.repositories.note import NoteRepository


class NoteController(BaseController[NoteRepository]):
    """Contrôleur générique — le scoping est entièrement géré par
    NoteRepository.owner_column."""
