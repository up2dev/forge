"""
forge.query_context
====================
Porté PAR LA REQUÊTE (`request.state.query_context`), jamais par un
état global partagé entre requêtes.

`conditions` est une liste de groupes (`list[list[Condition]]`) : les
conditions d'un même groupe sont combinées en ET, les groupes entre
eux en OU — reflète directement la syntaxe `a:eq(1),b:eq(2)|or|c:eq(3)`
(voir forge/middleware/query_string.py).

`includes` n'est PAS transmis tel quel à l'ORM : BaseRepository le
valide contre `Repository.includes` (l'allowlist déclarée par le
Repository, symétrique à `Repository.filters`) avant de le laisser
toucher la requête SQL — voir BaseRepository._apply_includes().
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Condition:
    target: str
    operator: str
    value: str


@dataclass
class OrderBy:
    attribute: str
    direction: str = "asc"


@dataclass
class QueryContext:
    conditions: list[list[Condition]] = field(default_factory=list)
    order_by: list[OrderBy] = field(default_factory=list)
    includes: list[str] = field(default_factory=list)
    page: int = 1
    limit: int | None = None
    distinct: bool = False
