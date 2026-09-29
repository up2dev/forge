#!/usr/bin/env python3
"""
scripts/make_crud.py
=====================
Génère model/repository/controller pour une ressource, à partir d'une
table existante en base OU en demandant les champs si elle n'existe
pas encore.

Usage :
    python scripts/make_crud.py tag
    python scripts/make_crud.py tag --fields "name:str,price:float?,category:fk:authors"
    python scripts/make_crud.py tag --fields "name:str,tags:m2m:tags"
    python scripts/make_crud.py tag --no-wire   # ne touche pas routes.py

Types de champ (name:type) :
    str/text/int/float/bool/datetime  — ajouter ? pour rendre nullable
    fk:table                          — relation N-1, ajouter ? pour 0-N (optionnelle)
    m2m:table                         — relation N-N (génère la table d'association)

id/created_at/updated_at/deleted_at ne sont jamais demandés — déjà
fournis par BaseModel/TimestampMixin.
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from forge.generator.fields import KIND_TO_TYPES, GeneratedField
from forge.generator.introspect import introspect_table
from forge.generator.render import render_controller, render_model, render_repository

APP_DIR = Path(__file__).parent.parent / "example_app"
ROUTES_FILE = APP_DIR / "routes.py"


def pluralize(name: str) -> str:
    """Pluriel anglais courant — pas parfait (irrégulier type
    "child"->"children" pas couvert), mais gère les cas fréquents que
    "+ s" seul rate. --table reste l'échappatoire pour le reste."""
    if re.search(r"[^aeiou]y$", name):
        return name[:-1] + "ies"

    if re.search(r"(s|x|z|ch|sh)$", name):
        return name + "es"

    return name + "s"


def parse_fields_arg(raw: str) -> list[GeneratedField]:
    """"name:str,price:float?,category:fk:authors?,tags:m2m:tags" -> [GeneratedField, ...]"""
    fields = []

    for part in raw.split(","):
        bits = part.strip().split(":")
        nullable = bits[-1].endswith("?")

        if nullable:
            bits[-1] = bits[-1][:-1]

        if len(bits) == 2 and bits[1] in KIND_TO_TYPES:
            fields.append(GeneratedField(name=bits[0], kind=bits[1], nullable=nullable))
        elif len(bits) == 3 and bits[1] == "fk":
            fields.append(GeneratedField(name=bits[0], kind="fk", fk_table=bits[2], nullable=nullable))
        elif len(bits) == 3 and bits[1] == "m2m":
            fields.append(GeneratedField(name=bits[0], kind="m2m", fk_table=bits[2]))
        else:
            sys.exit(
                f"Champ invalide: '{part}'. Attendu name:type[?], name:fk:table[?] "
                "ou name:m2m:table."
            )

    return fields


def prompt_fields() -> list[GeneratedField]:
    print("Table introuvable — décris les champs (id/dates déjà gérés).")
    print(f"Types: {', '.join(KIND_TO_TYPES)} (+ ? pour optionnel), fk:<table>[?], m2m:<table>")

    fields = []

    while True:
        name = input("Nom du champ (vide pour terminer): ").strip()

        if not name:
            break

        kind = input(f"Type de '{name}': ").strip()
        nullable = kind.endswith("?")

        if nullable:
            kind = kind[:-1]

        if kind.startswith("fk:"):
            fields.append(GeneratedField(name=name, kind="fk", fk_table=kind[3:], nullable=nullable))
        elif kind.startswith("m2m:"):
            fields.append(GeneratedField(name=name, kind="m2m", fk_table=kind[4:]))
        elif kind in KIND_TO_TYPES:
            fields.append(GeneratedField(name=name, kind=kind, nullable=nullable))
        else:
            print(f"Type inconnu '{kind}', champ ignoré.")

    return fields


def write_file(path: Path, content: str) -> None:
    if path.exists():
        sys.exit(f"{path} existe déjà — supprime-le ou choisis un autre nom.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  créé: {path}")


def wire_routes(entity: str, class_name: str, table_name: str) -> bool:
    """Insère aux marqueurs # forge:generated-*. Ne touche rien si un
    marqueur manque (routes.py édité à la main entre-temps, etc.) —
    imprime les lignes à coller à la place."""
    content = ROUTES_FILE.read_text(encoding="utf-8")
    router_var = f"{entity}s_router"

    import_line = f"from example_app.controllers.{entity} import {class_name}Controller"
    router_lines = (
        f'{router_var} = ControllerRouter({class_name}Controller, prefix="/{table_name}", '
        f'tags=["{table_name}"])\n'
        f"{router_var}.resource(authenticated_only=True)  "
        f"# généré — resserrer les permissions si besoin"
    )
    entry = f"{router_var},\n"

    markers = ["# forge:generated-imports", "# forge:generated-routers", "# forge:generated-entries"]
    if not all(m in content for m in markers):
        return False

    content = content.replace("# forge:generated-imports", f"{import_line}\n# forge:generated-imports")
    content = content.replace("# forge:generated-routers", f"{router_lines}\n# forge:generated-routers")
    content = content.replace("# forge:generated-entries", f"{entry}    # forge:generated-entries")

    ROUTES_FILE.write_text(content, encoding="utf-8")
    return True


async def main() -> None:
    parser = argparse.ArgumentParser(description="Génère un CRUD Forge (model/repository/controller).")
    parser.add_argument("name", help="Nom de la ressource, singulier (ex: tag)")
    parser.add_argument("--table", help="Nom de table si différent de <name>s")
    parser.add_argument("--fields", help='"name:str,price:float,category:fk:authors"')
    parser.add_argument("--no-wire", action="store_true", help="Ne pas modifier routes.py")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.name):
        sys.exit("Le nom doit être en minuscules, ex: tag, blog_post.")

    class_name = "".join(p.capitalize() for p in args.name.split("_"))
    table_name = args.table or pluralize(args.name)

    fields = await introspect_table(table_name)

    if fields is not None:
        print(f"Table '{table_name}' trouvée en base — {len(fields)} champ(s) repris.")
    else:
        print(f"Table '{table_name}' introuvable en base (utilise --table si le nom diffère).")

        if args.fields:
            fields = parse_fields_arg(args.fields)
        else:
            fields = prompt_fields()

    if not fields:
        sys.exit("Aucun champ — rien à générer.")

    write_file(APP_DIR / "models" / f"{args.name}.py", render_model(class_name, table_name, fields))
    write_file(
        APP_DIR / "repositories" / f"{args.name}.py",
        render_repository(class_name, args.name, fields),
    )
    write_file(APP_DIR / "controllers" / f"{args.name}.py", render_controller(class_name))

    if args.no_wire:
        print("\n--no-wire: ajoute toi-même à example_app/routes.py.")
        return

    if wire_routes(args.name, class_name, table_name):
        print(f"\nroutes.py mis à jour — /{table_name} est en ligne (redémarre le serveur).")
    else:
        print("\nMarqueurs absents de routes.py — ajoute à la main:")
        print(f"  from example_app.controllers.{args.name} import {class_name}Controller")
        print(
            f'  {args.name}s_router = ControllerRouter({class_name}Controller, '
            f'prefix="/{table_name}", tags=["{table_name}"])'
        )
        print(f"  {args.name}s_router.resource(authenticated_only=True)")
        print(f"  # + ajouter {args.name}s_router à ALL_ROUTERS")


if __name__ == "__main__":
    asyncio.run(main())
