#!/usr/bin/env python3
"""
scripts/grant_permission.py
=============================
Donne une permission à un rôle (les deux doivent exister). `make
permissions` crée les permissions déclarées dans les routes mais ne les
attribue jamais — c'est volontaire, l'attribution est une décision
humaine. Cette commande la rend simple, sans éditer la base à la main.

Usage :
    docker compose exec api python scripts/grant_permission.py ADMIN TAGS_DELETE
    # ou : make grant role=ADMIN permission=TAGS_DELETE
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from forge.db import get_session
from forge.security.models import Permission, Role


async def grant(role_uid: str, permission_uid: str) -> str:
    """Renvoie "granted", "already" ou lève ValueError (rôle/permission inconnus)."""
    async with get_session() as session:
        role = (
            await session.execute(select(Role).where(Role.uid == role_uid).options(selectinload(Role.permissions)))
        ).scalar_one_or_none()

        if role is None:
            raise ValueError(f"Rôle inconnu : '{role_uid}'")

        permission = (
            await session.execute(select(Permission).where(Permission.uid == permission_uid))
        ).scalar_one_or_none()

        if permission is None:
            raise ValueError(f"Permission inconnue : '{permission_uid}' (make permissions la crée)")

        if permission in role.permissions:
            return "already"

        role.permissions.append(permission)
        await session.commit()

        return "granted"


def main() -> None:
    parser = argparse.ArgumentParser(description="Donne une permission à un rôle")
    parser.add_argument("role", help="uid du rôle, ex. ADMIN")
    parser.add_argument("permission", help="uid de la permission, ex. TAGS_DELETE")
    args = parser.parse_args()

    try:
        result = asyncio.run(grant(args.role, args.permission))
    except ValueError as exc:
        sys.exit(str(exc))

    if result == "already":
        print(f"Le rôle {args.role} a déjà la permission {args.permission}.")
    else:
        print(f"Permission {args.permission} donnée au rôle {args.role}.")


if __name__ == "__main__":
    main()
