"""
Équivalent de routes/api.php: on déclare, on ne devine rien.
"""
from forge.routing import ControllerRouter
from forge.security.routes import auth_router, mfa_router
from forge.storage.routes import files_router

from example_app.controllers.author import AuthorController
from example_app.controllers.book import BookController
from example_app.controllers.note import NoteController
# forge:generated-imports

books_router = ControllerRouter(BookController, prefix="/books", tags=["books"])
books_router.resource(
    # BOOKS_DELETE est requis pour supprimer (seul ou en masse) ; tout
    # le reste (list/show/add/edit/mass_add/mass_edit) ne demande
    # qu'une connexion valide, sans contrôle de rôle précis — repli
    # documenté dans ControllerRouter.resource().
    permissions={"remove": "BOOKS_DELETE", "mass_remove": "BOOKS_DELETE"},
)

authors_router = ControllerRouter(AuthorController, prefix="/authors", tags=["authors"])
authors_router.resource(authenticated_only=True)  # pas de granularité par rôle ici

notes_router = ControllerRouter(NoteController, prefix="/notes", tags=["notes"])
# "/all" doit être déclaré AVANT resource() (donc avant "/{uid}") —
# même règle d'ordre que "/mass".
notes_router.get("/all", "list_all", permission="NOTES_ADMIN")
notes_router.resource(authenticated_only=True)  # scoping par utilisateur via owner_column
# forge:generated-routers

# main.py boucle sur cette liste — un seul endroit à toucher pour
# ajouter une ressource (c'est aussi ce que forge make:crud complète
# automatiquement).
ALL_ROUTERS = [
    books_router, authors_router, notes_router, auth_router, mfa_router, files_router,
    # forge:generated-entries
]

# Ou verbe par verbe, si tu ne veux pas toutes les actions :
#   books_router.get("/", "list", authenticated_only=True)
#   books_router.get("/{uid}", "show", public=True)
