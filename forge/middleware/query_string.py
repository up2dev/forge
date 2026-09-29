"""
forge.middleware.query_string
==============================
Parse la query string en QueryContext (?filters=/?sort=/?with=).

Syntaxe de ?filters= : ET/OU à plat, pas d'imbrication multi-niveaux —
largement suffisant pour la plupart des listings, et plus simple à
lire/écrire côté client :

    ?filters=name:lk(john),age:gte(18)|or|status:eq(active)

  -> (name LIKE %john% AND age >= 18) OR status = 'active'

Chaque groupe séparé par `|or|` est un ET de conditions séparées par
des virgules — la virgule de séparation entre conditions n'est
reconnue que HORS parenthèses, pour ne pas casser `year:in(1,2,3)`
(voir _split_top_level). Si le besoin de groupes imbriqués apparaît,
ce sera un module à part plutôt que de complexifier ce parseur.

?with= est parsé mais PAS validé ici : c'est BaseRepository qui le
valide contre son allowlist `includes`, au moment de la requête ORM.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from forge.query_context import Condition, OrderBy, QueryContext
from forge.repositories.base import InvalidFilterError


def _split_top_level(raw: str, sep: str) -> list[str]:
    """Comme str.split(sep), mais ignore sep tant qu'on est entre une
    parenthèse ouvrante et sa fermante — year:in(1,2,3),status:eq(x)
    donne 2 parties, pas 3."""
    parts = []
    current = []
    depth = 0

    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1

        if ch == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)

    parts.append("".join(current))

    return parts


class QueryStringMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Un middleware (contrairement à une route) est hors de portée
        # des @app.exception_handler — une erreur levée ici finirait en
        # 500 brut si elle n'était pas rattrapée explicitement.
        try:
            request.state.query_context = self._parse(request)
        except InvalidFilterError as exc:
            return JSONResponse(status_code=400, content={"detail": str(exc)})

        return await call_next(request)

    def _parse(self, request: Request) -> QueryContext:
        params = request.query_params
        ctx = QueryContext()

        if page := params.get("page"):
            ctx.page = int(page)

        if limit := params.get("limit"):
            ctx.limit = int(limit)

        if params.get("distinct"):
            ctx.distinct = bool(int(params["distinct"]))

        if sort := params.get("sort"):
            ctx.order_by = self._parse_sort(sort)

        if filters := params.get("filters"):
            ctx.conditions = self._parse_filters(filters)

        if includes := params.get("with"):
            ctx.includes = [i for i in includes.split(",") if i]

        return ctx

    def _parse_sort(self, raw: str) -> list[OrderBy]:
        orders = []

        for part in raw.split(","):
            if not part:
                continue

            bits = part.split(".")
            direction = "asc"

            if bits[-1].lower() in ("asc", "desc"):
                direction = bits.pop().lower()

            orders.append(OrderBy(attribute=".".join(bits), direction=direction))

        return orders

    def _parse_filters(self, raw: str) -> list[list[Condition]]:
        groups = []

        for group in raw.split("|or|"):
            conditions = [self._parse_one(part) for part in _split_top_level(group, ",") if part]

            if conditions:
                groups.append(conditions)

        return groups

    def _parse_one(self, part: str) -> Condition:
        # field:op(value) — ex. "n" (IS NULL) s'écrit field:n(), jamais
        # field:n seul : la syntaxe exige toujours des parenthèses.
        try:
            target, rest = part.split(":", 1)
            operator, value = rest.rstrip(")").split("(", 1)
        except ValueError:
            raise InvalidFilterError(
                f"Filtre malformé : '{part}' — attendu champ:opérateur(valeur)."
            )

        return Condition(target=target, operator=operator, value=value)
