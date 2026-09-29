"""
forge.repositories.base
========================
Moteur CRUD générique.

- ?with= validé contre `Repository.includes` (allowlist), jamais
  transmis brut à l'ORM.
- mass_delete() refuse sans `ids` explicites ou `confirm=True` + un
  filtre actif.
- Scoping propriétaire (`owner_column`) opt-in par Repository, jamais
  implicite depuis un nom de colonne.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Generic, TypeVar

from sqlalchemy import delete as sa_delete
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import selectinload

from forge.audit import log_activity
from forge.db import get_session
from forge.models.base import Base
from forge.query_context import Condition, QueryContext

M = TypeVar("M", bound=Base)

_OPERATORS = {
    "eq": "__eq__",
    "neq": "__ne__",
    "gt": "__gt__",
    "gte": "__ge__",
    "lt": "__lt__",
    "lte": "__le__",
}


class RepositoryResolutionError(Exception):
    pass


class InvalidFilterError(Exception):
    """Clé de filtre inconnue. Jamais levée pour une relation ?with=
    inconnue — voir _apply_includes, qui l'ignore silencieusement."""


class OwnershipError(Exception):
    """Écriture tentée sur une ligne hors du scope propriétaire."""


@dataclass
class ListResult(Generic[M]):
    items: list[M]
    total: int
    page: int
    limit: int | None
    total_pages: int
    previous_page: int | None
    next_page: int | None


def _pagination_meta(total: int, page: int, limit: int | None) -> tuple[int, int | None, int | None]:
    total_pages = -(-total // limit) if limit else 1  # division entière arrondie au-dessus
    total_pages = max(total_pages, 1)

    previous_page = page - 1 if page > 1 else None
    next_page = page + 1 if limit and page < total_pages else None

    return total_pages, previous_page, next_page


class BaseRepository(Generic[M]):
    model: type[M]

    #: clé client -> nom de colonne. Sert aussi d'allowlist pour le tri.
    filters: dict[str, str] = {}

    #: allowlist pour ?with=, ex. {"author", "author.publisher"}.
    includes: set[str] = set()

    #: colonne propriétaire d'une ligne, pour le scoping par
    #: utilisateur. None = pas de scoping (défaut). À poser
    #: explicitement, jamais déduit d'un nom de colonne existant.
    owner_column: str | None = None

    #: journalise create/update/delete dans ActivityLog (table +
    #: fichier de log) quand activé — voir forge/audit.py.
    loggable: bool = False

    def __init__(self) -> None:
        if not hasattr(self, "model") or self.model is None:
            self.model = self._resolve_model()

    def _resolve_model(self) -> type[M]:
        module_name = type(self).__module__
        class_name = type(self).__name__

        if not class_name.endswith("Repository"):
            raise RepositoryResolutionError(
                f"{class_name}: no `model` set and the class name doesn't "
                "end in 'Repository' — set `model` explicitly."
            )

        target_module = module_name.replace(".repositories.", ".models.")
        target_class = class_name[: -len("Repository")]

        try:
            mod = importlib.import_module(target_module)
            return getattr(mod, target_class)
        except (ModuleNotFoundError, AttributeError) as exc:
            raise RepositoryResolutionError(
                f"{class_name}: couldn't resolve model '{target_class}' in "
                f"'{target_module}'. Set `model` explicitly."
            ) from exc

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------

    async def all(
        self, query_context: QueryContext | None = None, owner_id: int | None = None
    ) -> ListResult[M]:
        ctx = query_context or QueryContext()

        async with get_session() as session:
            stmt = self._owner_filter(self._apply_context(select(self.model), ctx), owner_id)
            count_stmt = self._owner_filter(
                self._apply_conditions(select(func.count()).select_from(self.model), ctx.conditions),
                owner_id,
            )

            total = (await session.execute(count_stmt)).scalar_one()

            limit = ctx.limit if ctx.limit is not None else 20
            if limit:
                stmt = stmt.offset((ctx.page - 1) * limit).limit(limit)

            items = list((await session.execute(stmt)).scalars().unique().all())
            total_pages, previous_page, next_page = _pagination_meta(total, ctx.page, limit or None)

            return ListResult(
                items=items,
                total=total,
                page=ctx.page,
                limit=limit or None,
                total_pages=total_pages,
                previous_page=previous_page,
                next_page=next_page,
            )

    async def read(
        self,
        uid: int,
        query_context: QueryContext | None = None,
        owner_id: int | None = None,
    ) -> M | None:
        ctx = query_context or QueryContext()

        async with get_session() as session:
            stmt = self._apply_includes(select(self.model), ctx.includes)
            stmt = self._owner_filter(stmt.where(self.model.id == uid), owner_id)

            return (await session.execute(stmt)).scalars().unique().first()

    # ------------------------------------------------------------------
    # Écriture
    # ------------------------------------------------------------------

    async def create(
        self, fields: dict[str, Any], owner_id: int | None = None, actor_id: int | None = None
    ) -> M:
        clean = self._sanitize(fields)

        # L'appartenance est assignée côté serveur, jamais reprise du payload client.
        if self.owner_column and owner_id is not None:
            clean[self.owner_column] = owner_id

        async with get_session() as session:
            instance = self.model(**clean)
            session.add(instance)
            await session.commit()
            await session.refresh(instance)

        if self.loggable:
            await log_activity(self.model.__name__, instance.id, "create", actor_id, clean)

        return instance

    async def mass_create(
        self, items: list[dict[str, Any]], owner_id: int | None = None, actor_id: int | None = None
    ) -> list[M]:
        return [await self.create(item, owner_id=owner_id, actor_id=actor_id) for item in items]

    async def update(
        self,
        uid: int,
        fields: dict[str, Any],
        owner_id: int | None = None,
        actor_id: int | None = None,
    ) -> M | None:
        async with get_session() as session:
            stmt = self._owner_filter(
                select(self.model).where(self.model.id == uid), owner_id
            )
            instance = (await session.execute(stmt)).scalar_one_or_none()

            if instance is None:
                return None

            clean = self._sanitize(fields)
            clean.pop(self.owner_column, None)  # l'appartenance ne se réassigne pas via update

            for key, value in clean.items():
                setattr(instance, key, value)

            await session.commit()
            await session.refresh(instance)

        if self.loggable and clean:
            await log_activity(self.model.__name__, uid, "update", actor_id, clean)

        return instance

    async def mass_update(
        self, items: list[dict[str, Any]], owner_id: int | None = None, actor_id: int | None = None
    ) -> list[M]:
        results = []

        for item in items:
            uid = item.pop("id")
            updated = await self.update(uid, item, owner_id=owner_id, actor_id=actor_id)

            if updated is not None:
                results.append(updated)

        return results

    async def delete(self, uid: int, owner_id: int | None = None, actor_id: int | None = None) -> bool:
        async with get_session() as session:
            stmt = self._owner_filter(
                select(self.model).where(self.model.id == uid), owner_id
            )
            instance = (await session.execute(stmt)).scalar_one_or_none()

            if instance is None:
                return False

            await session.delete(instance)
            await session.commit()

        if self.loggable:
            await log_activity(self.model.__name__, uid, "delete", actor_id)

        return True

    async def mass_delete(
        self,
        ids: list[int] | None,
        query_context: QueryContext | None,
        confirm: bool,
        owner_id: int | None = None,
    ) -> int:
        if ids:
            async with get_session() as session:
                stmt = self._owner_filter(
                    sa_delete(self.model).where(self.model.id.in_(ids)), owner_id
                )
                result = await session.execute(stmt)
                await session.commit()

                return result.rowcount or 0

        ctx = query_context or QueryContext()

        if not confirm or not ctx.conditions:
            raise ValueError(
                "mass_delete requires either an explicit `ids` list, or "
                "`confirm=True` together with at least one active filter."
            )

        async with get_session() as session:
            stmt = self._owner_filter(
                self._apply_conditions(sa_delete(self.model), ctx.conditions), owner_id
            )
            result = await session.execute(stmt)
            await session.commit()

            return result.rowcount or 0

    # ------------------------------------------------------------------
    # Construction de requête
    # ------------------------------------------------------------------

    def _sanitize(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Ne garde que les vraies colonnes du modèle."""
        columns = {c.name for c in self.model.__table__.columns}

        return {k: v for k, v in fields.items() if k in columns}

    def _owner_filter(self, stmt, owner_id: int | None):
        if self.owner_column is None or owner_id is None:
            return stmt

        return stmt.where(getattr(self.model, self.owner_column) == owner_id)

    def _apply_context(self, stmt, ctx: QueryContext):
        stmt = self._apply_conditions(stmt, ctx.conditions)
        stmt = self._apply_sort(stmt, ctx)
        stmt = self._apply_includes(stmt, ctx.includes)

        if ctx.distinct:
            stmt = stmt.distinct()

        return stmt

    def _apply_conditions(self, stmt, groups: list[list[Condition]]):
        """groups = [[a, b], [c]] -> WHERE (a AND b) OR (c) — un groupe
        par segment séparé par |or|, conditions d'un groupe en ET."""
        if not groups:
            return stmt

        or_clauses = []

        for group in groups:
            and_clauses = [self._condition_clause(g) for g in group]
            or_clauses.append(and_clauses[0] if len(and_clauses) == 1 else and_(*and_clauses))

        return stmt.where(or_clauses[0] if len(or_clauses) == 1 else or_(*or_clauses))

    def _condition_clause(self, cond: Condition):
        if cond.target not in self.filters:
            raise InvalidFilterError(
                f"Clé de filtre inconnue '{cond.target}' pour "
                f"{type(self).__name__} — à déclarer dans `filters`."
            )

        column = getattr(self.model, self.filters[cond.target])

        if cond.operator in _OPERATORS:
            return getattr(column, _OPERATORS[cond.operator])(self._coerce(column, cond.value))

        if cond.operator == "lk":
            return column.ilike(f"%{cond.value}%")

        if cond.operator == "nlk":
            return ~column.ilike(f"%{cond.value}%")

        if cond.operator == "in":
            return column.in_([self._coerce(column, v) for v in cond.value.split(",")])

        if cond.operator == "n":
            return column.is_(None)

        raise InvalidFilterError(f"Opérateur inconnu '{cond.operator}'")

    def _coerce(self, column, raw: str):
        """La query string ne fournit que des chaînes — SQLite les
        compare sans broncher à une colonne entière/booléenne, mais
        Postgres (le vrai moteur de prod) refuse net. Convertit vers le
        type Python réel de la colonne avant de construire la
        comparaison ; une valeur invalide devient un 400 propre, pas
        un 500 selon le moteur utilisé."""
        try:
            python_type = column.type.python_type
        except NotImplementedError:
            return raw  # type sans équivalent Python direct (JSON...) — inchangé

        if python_type is bool:
            if raw.lower() in ("1", "true", "t", "yes"):
                return True

            if raw.lower() in ("0", "false", "f", "no"):
                return False

            raise InvalidFilterError(f"Valeur booléenne invalide : '{raw}'")

        if python_type in (int, float, Decimal):
            try:
                return python_type(raw)
            except ValueError:
                raise InvalidFilterError(f"Valeur numérique invalide : '{raw}'") from None

        if python_type in (datetime, date):
            try:
                return python_type.fromisoformat(raw)
            except ValueError:
                raise InvalidFilterError(f"Date invalide (attendu ISO 8601) : '{raw}'") from None

        return raw

    def _apply_sort(self, stmt, ctx: QueryContext):
        for order in ctx.order_by:
            if order.attribute not in self.filters:
                continue  # même allowlist que les filtres, silencieux comme includes

            column = getattr(self.model, self.filters[order.attribute])
            stmt = stmt.order_by(column.desc() if order.direction == "desc" else column.asc())

        return stmt

    def _apply_includes(self, stmt, includes: list[str]):
        for path in includes:
            if path not in self.includes:
                continue  # allowlist

            attr = getattr(self.model, path.split(".")[0])
            stmt = stmt.options(selectinload(attr))

        return stmt
