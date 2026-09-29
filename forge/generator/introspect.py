"""
forge.generator.introspect
============================
Lit le vrai schéma d'une table existante — colonnes, types, clés
étrangères — par réflexion SQLAlchemy async. Renvoie None si la table
n'existe pas, pour que l'appelant retombe sur une saisie manuelle.
"""
from __future__ import annotations

import sqlalchemy as sa

from forge.db import engine
from forge.generator.fields import AUTO_COLUMNS, GeneratedField


async def introspect_table(table_name: str) -> list[GeneratedField] | None:
    async with engine.connect() as conn:
        exists = await conn.run_sync(lambda c: sa.inspect(c).has_table(table_name))

        if not exists:
            return None

        columns = await conn.run_sync(lambda c: sa.inspect(c).get_columns(table_name))
        foreign_keys = await conn.run_sync(lambda c: sa.inspect(c).get_foreign_keys(table_name))

    fk_target_by_column = {
        col: fk["referred_table"] for fk in foreign_keys for col in fk["constrained_columns"]
    }

    fields: list[GeneratedField] = []

    for col in columns:
        name = col["name"]

        if name in AUTO_COLUMNS:
            continue

        if name in fk_target_by_column:
            base_name = name[:-3] if name.endswith("_id") else name
            fields.append(
                GeneratedField(
                    name=base_name,
                    kind="fk",
                    nullable=col["nullable"],
                    fk_table=fk_target_by_column[name],
                )
            )
            continue

        fields.append(GeneratedField(name=name, kind=_kind_of(col["type"]), nullable=col["nullable"]))

    return fields


def _kind_of(sa_type) -> str:
    py_type = getattr(sa_type, "python_type", str)
    type_name = type(sa_type).__name__.upper()

    if py_type is bool:
        return "bool"
    if py_type is int:
        return "int"
    if py_type is float:
        return "float"
    if py_type.__name__ == "datetime":
        return "datetime"
    if "TEXT" in type_name or "CLOB" in type_name:
        return "text"

    return "str"
