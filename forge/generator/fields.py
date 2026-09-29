"""
forge.generator.fields
=======================
Les types de champs proposés quand une table n'existe pas encore.
"kind" -> (annotation Python, expression de colonne SQLAlchemy).
"""
from __future__ import annotations

from dataclasses import dataclass

KIND_TO_TYPES = {
    "str": ("str", "String(255)"),
    "text": ("str", "Text"),
    "int": ("int", "Integer"),
    "float": ("float", "Float"),
    "bool": ("bool", "Boolean"),
    "datetime": ("datetime", "DateTime(timezone=True)"),
}

#: Colonnes déjà fournies par BaseModel/TimestampMixin — jamais
#: demandées, jamais générées comme champ normal.
AUTO_COLUMNS = {"id", "created_at", "updated_at", "deleted_at"}


@dataclass
class GeneratedField:
    name: str  # "title", ou "author" pour une fk (jamais "author_id")
    kind: str  # une des clés de KIND_TO_TYPES, ou "fk"
    nullable: bool = False
    fk_table: str | None = None  # uniquement si kind == "fk"

    @property
    def column_name(self) -> str:
        return f"{self.name}_id" if self.kind == "fk" else self.name
