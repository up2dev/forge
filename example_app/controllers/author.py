from forge.controllers.base import BaseController

from example_app.repositories.author import AuthorRepository


class AuthorController(BaseController[AuthorRepository]):
    """Contrôleur générique pur, comme BookController avant typage — la
    doc /docs pour cette ressource reste générique (schéma "objet
    libre") faute de schémas Pydantic dédiés. Ajouter des schémas
    (comme pour Book) est le seul geste nécessaire pour la retrouver."""
