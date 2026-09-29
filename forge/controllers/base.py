"""
forge.controllers.base
=======================
Controller générique : résout son Repository par convention de nommage
(myapp.controllers.book.BookController -> myapp.repositories.book.BookRepository).
Échec de résolution levé au démarrage (ControllerRouter instancie le
Controller une fois, à l'import), jamais à la première requête.
"""
from __future__ import annotations

import importlib
from typing import Any, Generic, TypeVar

from fastapi import Body, Depends, HTTPException, Request

from forge.repositories.base import BaseRepository, ListResult
from forge.schemas import MassDeleteBody
from forge.security.dependencies import get_current_user_optional
from forge.security.models import User

R = TypeVar("R", bound=BaseRepository)


class RepositoryResolutionError(Exception):
    """Aucun repository_class posé et aucun Repository trouvé par convention."""


class BaseController(Generic[R]):
    #: À poser explicitement si la convention module/classe ne s'applique pas.
    repository_class: type[R] | None = None

    def __init__(self, repo: R | None = None) -> None:
        self.repo: R = repo or self._resolve_repository()()

    def _resolve_repository(self) -> type[R]:
        if self.repository_class is not None:
            return self.repository_class

        module_name = type(self).__module__
        class_name = type(self).__name__

        if not class_name.endswith("Controller"):
            raise RepositoryResolutionError(
                f"{class_name}: no repository_class set and the class name "
                "doesn't end in 'Controller'."
            )

        target_module = module_name.replace(".controllers.", ".repositories.")
        target_class = class_name[: -len("Controller")] + "Repository"

        if target_module == module_name:
            raise RepositoryResolutionError(
                f"{class_name}: module '{module_name}' has no '.controllers.' "
                "segment — can't derive the repository module."
            )

        try:
            mod = importlib.import_module(target_module)
        except ModuleNotFoundError as exc:
            raise RepositoryResolutionError(
                f"{class_name}: repository module '{target_module}' not found."
            ) from exc

        repo_cls = getattr(mod, target_class, None)

        if repo_cls is None:
            raise RepositoryResolutionError(
                f"{class_name}: class '{target_class}' not found in "
                f"'{target_module}'."
            )

        return repo_cls

    def _owner_id(self, user: User | None) -> int | None:
        return user.id if user else None

    # ------------------------------------------------------------------
    # Actions CRUD génériques — rien à écrire dans un Controller basique.
    # ------------------------------------------------------------------

    async def list(
        self, request: Request, user: User | None = Depends(get_current_user_optional)
    ) -> ListResult:
        return await self.repo.all(
            query_context=request.state.query_context, owner_id=self._owner_id(user)
        )

    async def list_all(self, request: Request) -> ListResult:
        """Comme list(), mais sans scoping propriétaire — équivalent
        AUTH_UNLIMITED de Rivet. À câbler sur sa propre route avec
        permission=, jamais public=/authenticated_only= seul."""
        return await self.repo.all(query_context=request.state.query_context, owner_id=None)

    async def show(
        self,
        uid: int,
        request: Request,
        user: User | None = Depends(get_current_user_optional),
    ):
        item = await self.repo.read(
            uid, query_context=request.state.query_context, owner_id=self._owner_id(user)
        )

        if item is None:
            raise HTTPException(404, "Not found")

        return item

    async def add(
        self,
        payload: dict[str, Any] = Body(default_factory=dict),
        user: User | None = Depends(get_current_user_optional),
    ):
        return await self.repo.create(
            payload, owner_id=self._owner_id(user), actor_id=self._owner_id(user)
        )

    async def mass_add(
        self,
        payload: list[dict[str, Any]] = Body(default_factory=list),
        user: User | None = Depends(get_current_user_optional),
    ):
        return await self.repo.mass_create(
            payload, owner_id=self._owner_id(user), actor_id=self._owner_id(user)
        )

    async def edit(
        self,
        uid: int,
        payload: dict[str, Any] = Body(default_factory=dict),
        user: User | None = Depends(get_current_user_optional),
    ):
        item = await self.repo.update(
            uid, payload, owner_id=self._owner_id(user), actor_id=self._owner_id(user)
        )

        if item is None:
            raise HTTPException(404, "Not found")

        return item

    async def mass_edit(
        self,
        payload: list[dict[str, Any]] = Body(default_factory=list),
        user: User | None = Depends(get_current_user_optional),
    ):
        return await self.repo.mass_update(
            payload, owner_id=self._owner_id(user), actor_id=self._owner_id(user)
        )

    async def remove(
        self, uid: int, user: User | None = Depends(get_current_user_optional)
    ) -> dict:
        ok = await self.repo.delete(
            uid, owner_id=self._owner_id(user), actor_id=self._owner_id(user)
        )

        if not ok:
            raise HTTPException(404, "Not found")

        return {"deleted": uid}

    async def mass_remove(
        self,
        body: MassDeleteBody,
        request: Request,
        user: User | None = Depends(get_current_user_optional),
    ) -> dict:
        """Refuse d'agir sans ids explicites ou confirm=True + un filtre
        actif — voir BaseRepository.mass_delete."""
        count = await self.repo.mass_delete(
            ids=body.ids,
            query_context=request.state.query_context,
            confirm=body.confirm,
            owner_id=self._owner_id(user),
        )

        return {"deleted_count": count}
