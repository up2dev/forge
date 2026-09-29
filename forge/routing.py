"""
forge.routing
=============
Reproduit `Route::controller('XController')->group(...)` de Laravel :
les routes pointent vers une méthode de Controller, pas une fonction.

    router = ControllerRouter(BookController, prefix="/books", tags=["books"])
    router.get("/", "list")
    router.post("/", "add")
    app.include_router(router.router)
"""
from __future__ import annotations

import typing
from typing import Any, Sequence

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from forge.security.dependencies import get_current_user, require_permission


class RouteAuthorizationError(Exception):
    """Levée au démarrage quand une route n'a aucune décision
    d'autorisation explicite — jamais de route ouverte par oubli."""


class ControllerRouter:
    """Enveloppe un APIRouter, route chaque verbe HTTP vers une méthode
    nommée du Controller. Le Controller est instancié une seule fois
    (pas par requête), donc la résolution du Repository se fait au
    démarrage."""

    def __init__(
        self,
        controller_cls: type,
        prefix: str = "",
        tags: Sequence[str] | None = None,
        dependencies: Sequence[Any] | None = None,
    ) -> None:
        self.controller = controller_cls()
        self.router = APIRouter(
            prefix=prefix,
            tags=list(tags or []),
            dependencies=list(dependencies or []),
        )
        #: chaque uid passé à permission= à travers ce routeur — sert à
        #: générer les permissions manquantes en base, voir
        #: scripts/sync_permissions.py.
        self.declared_permissions: set[str] = set()

    def _bind(self, action: str):
        # La méthode liée est passée telle quelle (pas enveloppée) pour
        # garder sa vraie signature — c'est elle que FastAPI inspecte
        # pour les type hints, Depends() et le corps de requête.
        if not hasattr(self.controller, action):
            raise AttributeError(
                f"{type(self.controller).__name__} has no action '{action}'"
            )

        return getattr(self.controller, action)

    def _add(
        self,
        path: str,
        action: str,
        methods: list[str],
        *,
        permission: str | None = None,
        public: bool = False,
        authenticated_only: bool = False,
        **kwargs,
    ) -> None:
        decisions_taken = sum([permission is not None, public, authenticated_only])

        if decisions_taken == 0:
            raise RouteAuthorizationError(
                f"{methods} {path} ('{action}'): no authorization decision. "
                "Pass permission=\"...\" , public=True, or "
                "authenticated_only=True."
            )

        if decisions_taken > 1:
            raise RouteAuthorizationError(
                f"{methods} {path} ('{action}'): pass exactly ONE of "
                "permission=/public=/authenticated_only=."
            )

        auth_dependencies: list[Any] = []

        if permission is not None:
            auth_dependencies.append(Depends(require_permission(permission)))
            self.declared_permissions.add(permission)
        elif authenticated_only:
            auth_dependencies.append(Depends(get_current_user))
        # public=True: aucune dépendance ajoutée.

        kwargs["dependencies"] = [*auth_dependencies, *kwargs.get("dependencies", [])]

        # add_api_route (contrairement au décorateur @app.get) n'infère
        # pas response_model depuis l'annotation de retour — on le fait ici.
        if "response_model" not in kwargs:
            kwargs["response_model"] = self._response_model(action)

        self.router.add_api_route(path, self._bind(action), methods=methods, **kwargs)

    def _response_model(self, action: str) -> type[BaseModel] | None:
        # get_type_hints() résout les annotations en chaîne (via
        # `from __future__ import annotations`) — return_annotation brut
        # renverrait 'BookList' en texte, pas la classe.
        method = getattr(self.controller, action)
        hints = typing.get_type_hints(method)
        annotation = hints.get("return")

        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            return annotation

        return None

    def get(self, path: str, action: str, **kwargs) -> None:
        self._add(path, action, ["GET"], **kwargs)

    def post(self, path: str, action: str, **kwargs) -> None:
        self._add(path, action, ["POST"], **kwargs)

    def put(self, path: str, action: str, **kwargs) -> None:
        self._add(path, action, ["PUT"], **kwargs)

    def patch(self, path: str, action: str, **kwargs) -> None:
        self._add(path, action, ["PATCH"], **kwargs)

    def delete(self, path: str, action: str, **kwargs) -> None:
        self._add(path, action, ["DELETE"], **kwargs)

    def resource(
        self,
        prefix: str = "",
        *,
        permissions: dict[str, str] | None = None,
        public: bool = False,
        authenticated_only: bool = False,
    ) -> None:
        """
        Enregistre les 8 actions CRUD (list/show/add/edit/remove +
        variantes mass), chacune avec sa décision d'autorisation :

          - permissions={"remove": "BOOKS_DELETE"} : cette action exige
            la permission ; toute action absente retombe sur
            authenticated_only.
          - public=True : toute la ressource ouverte, sans auth.
          - authenticated_only=True : connexion requise, pas de permission.
          - rien de tout ça : RouteAuthorizationError au démarrage.

        Les routes "/mass" sont déclarées avant "/{uid}" — Starlette
        matche par ordre de déclaration, PUT /mass après PUT /{uid}
        serait capturé comme uid="mass".
        """

        def decision(action: str) -> dict[str, Any]:
            if permissions and action in permissions:
                return {"permission": permissions[action]}

            if public:
                return {"public": True}

            if authenticated_only or permissions:
                return {"authenticated_only": True}

            return {}  # -> RouteAuthorizationError (deny-by-default)

        self.get(f"{prefix}/", "list", **decision("list"))
        self.post(f"{prefix}/", "add", **decision("add"))
        self.post(f"{prefix}/mass", "mass_add", **decision("mass_add"))
        self.put(f"{prefix}/mass", "mass_edit", **decision("mass_edit"))
        self.delete(f"{prefix}/", "mass_remove", **decision("mass_remove"))
        self.get(f"{prefix}/{{uid}}", "show", **decision("show"))
        self.put(f"{prefix}/{{uid}}", "edit", **decision("edit"))
        self.delete(f"{prefix}/{{uid}}", "remove", **decision("remove"))
