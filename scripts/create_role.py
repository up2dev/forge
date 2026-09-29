#!/usr/bin/env python3
"""
scripts/create_role.py
========================
Crée un rôle, avec des permissions optionnelles (déjà existantes —
`make permissions` d'abord si besoin). Équivalent de
`rightsmanagement --action=create-role` côté Rivet.

Usage :
    docker compose exec api python scripts/create_role.py EDITOR "Éditeur"
    docker compose exec api python scripts/create_role.py EDITOR "Éditeur" --permissions BOOKS_DELETE,NOTES_ADMIN
    # ou : make create-role uid=EDITOR name="Éditeur" permissions=BOOKS_DELETE,NOTES_ADMIN
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select

from forge.db import get_session
from forge.security.models import Permission, Role


async def create_role(uid: str, name: str, permission_uids: list[str] | None = None) -> Role:
    permission_uids = permission_uids or []

    async with get_session() as session:
        existing = (await session.execute(select(Role).where(Role.uid == uid))).scalar_one_or_none()

        if existing is not None:
            raise ValueError(f"Rôle déjà existant : '{uid}'")

        permissions = []

        for perm_uid in permission_uids:
            permission = (
                await session.execute(select(Permission).where(Permission.uid == perm_uid))
            ).scalar_one_or_none()

            if permission is None:
                raise ValueError(f"Permission inconnue : '{perm_uid}' (make permissions la crée)")

            permissions.append(permission)

        role = Role(uid=uid, name=name, permissions=permissions)
        session.add(role)
        await session.commit()

        return role


def main() -> None:
    parser = argparse.ArgumentParser(description="Crée un rôle")
    parser.add_argument("uid", help="identifiant unique, ex. EDITOR")
    parser.add_argument("name", help="nom affiché, ex. \"Éditeur\"")
    parser.add_argument("--permissions", default="", help="uids séparés par des virgules, ex. BOOKS_DELETE,NOTES_ADMIN")
    args = parser.parse_args()
    permission_uids = [p.strip() for p in args.permissions.split(",") if p.strip()]

    try:
        role = asyncio.run(create_role(args.uid, args.name, permission_uids))
    except ValueError as exc:
        sys.exit(str(exc))

    suffix = f" avec {', '.join(permission_uids)}" if permission_uids else ""
    print(f"Rôle {role.uid} ({role.name}) créé{suffix}.")


if __name__ == "__main__":
    main()
