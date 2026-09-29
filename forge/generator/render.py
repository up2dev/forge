"""
forge.generator.render
========================
Génère le code source (model.py/repository.py/controller.py) en
chaînes brutes — pas de Jinja2, l'indentation reste exacte et facile
à relire.
"""
from __future__ import annotations

from forge.generator.fields import KIND_TO_TYPES, GeneratedField


def singularize(table_name: str) -> str:
    """Inverse de pluralize() côté make_crud.py — gère les mêmes cas
    fréquents (categories -> category, boxes -> box), pas les
    pluriels irréguliers ; renommer la relation générée à la main si
    ça ne colle pas."""
    if table_name.endswith("ies"):
        return table_name[:-3] + "y"

    if table_name.endswith(("ses", "xes", "zes", "ches", "shes")):
        return table_name[:-2]

    return table_name[:-1] if table_name.endswith("s") else table_name


def render_model(class_name: str, table_name: str, fields: list[GeneratedField]) -> str:
    plain = [f for f in fields if f.kind not in ("fk", "m2m")]
    fks = [f for f in fields if f.kind == "fk"]
    m2ms = [f for f in fields if f.kind == "m2m"]

    sa_types = sorted({KIND_TO_TYPES[f.kind][1].split("(")[0] for f in plain})
    if fks or m2ms:
        sa_types = sorted({*sa_types, "ForeignKey"})
    if m2ms:
        sa_types = sorted({*sa_types, "Table", "Column"})

    lines = [
        "from __future__ import annotations",
        "",
        f"from sqlalchemy import {', '.join(sa_types)}",
        "from sqlalchemy.orm import Mapped, mapped_column" + (", relationship" if fks or m2ms else ""),
        "",
        "from forge.models.base import Base, TimestampMixin",
    ]

    # Tables d'association — au niveau module, avant la classe qui les
    # référence dans relationship(secondary=...). Si l'autre côté de
    # la relation est généré séparément, retire l'un des deux
    # doublons : une seule définition par table d'association.
    for f in m2ms:
        assoc_name = f"{table_name}_{f.fk_table}"
        left_col = f"{singularize(table_name)}_id"
        right_col = f"{singularize(f.fk_table)}_id"
        lines += [
            "",
            f'{assoc_name} = Table(',
            f'    "{assoc_name}",',
            "    Base.metadata,",
            f'    Column("{left_col}", ForeignKey("{table_name}.id"), primary_key=True),',
            f'    Column("{right_col}", ForeignKey("{f.fk_table}.id"), primary_key=True),',
            ")",
        ]

    lines += [
        "",
        "",
        f"class {class_name}(Base, TimestampMixin):",
        f'    __tablename__ = "{table_name}"',
        "",
        "    id: Mapped[int] = mapped_column(primary_key=True)",
    ]

    for f in plain:
        py_type, sa_expr = KIND_TO_TYPES[f.kind]
        annotation = f"{py_type} | None" if f.nullable else py_type
        kwargs = ", nullable=True" if f.nullable else ""
        lines.append(f"    {f.name}: Mapped[{annotation}] = mapped_column({sa_expr}{kwargs})")

    for f in fks:
        annotation = "int | None" if f.nullable else "int"
        kwargs = ", nullable=True" if f.nullable else ""
        lines.append(
            f'    {f.column_name}: Mapped[{annotation}] = mapped_column('
            f'ForeignKey("{f.fk_table}.id"){kwargs})'
        )

    for f in fks:
        related_class = singularize(f.fk_table).capitalize()
        lines.append(f'    {f.name}: Mapped["{related_class}"] = relationship()')

    for f in m2ms:
        assoc_name = f"{table_name}_{f.fk_table}"
        related_class = singularize(f.fk_table).capitalize()
        lines.append(
            f'    {f.name}: Mapped[list["{related_class}"]] = relationship(secondary={assoc_name})'
        )

    return "\n".join(lines) + "\n"


def render_repository(class_name: str, entity_module: str, fields: list[GeneratedField]) -> str:
    plain = [f for f in fields if f.kind not in ("fk", "m2m")]
    fks = [f for f in fields if f.kind == "fk"]
    m2ms = [f for f in fields if f.kind == "m2m"]

    filter_entries = [f'"{f.name}": "{f.name}"' for f in plain]
    filter_entries += [f'"{f.column_name}": "{f.column_name}"' for f in fks]
    # Pas de filtre sur une relation m2m — le DSL ne compare que des
    # scalaires, pas une liste. ?with= fonctionne (includes ci-dessous).
    includes_entries = [f'"{f.name}"' for f in fks] + [f'"{f.name}"' for f in m2ms]

    lines = [
        "from __future__ import annotations",
        "",
        "from forge.repositories.base import BaseRepository",
        "",
        f"from example_app.models.{entity_module} import {class_name}",
        "",
        "",
        f"class {class_name}Repository(BaseRepository[{class_name}]):",
        f"    model = {class_name}",
        f"    filters = {{{', '.join(filter_entries)}}}",
    ]

    if includes_entries:
        lines.append(f"    includes = {{{', '.join(includes_entries)}}}")

    return "\n".join(lines) + "\n"


def render_controller(class_name: str) -> str:
    return (
        "from forge.controllers.base import BaseController\n\n"
        f"from example_app.repositories.{class_name.lower()} import {class_name}Repository\n\n\n"
        f"class {class_name}Controller(BaseController[{class_name}Repository]):\n"
        '    """Généré par forge make:crud — vide, tout hérité de '
        'BaseController. Surcharge une méthode ici pour personnaliser."""\n'
    )
