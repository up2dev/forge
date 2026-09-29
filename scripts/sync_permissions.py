#!/usr/bin/env python3
"""
scripts/sync_permissions.py
=============================
Scanne les routes déclarées (ALL_ROUTERS) et crée en base les
permissions référencées par permission="..." qui n'existent pas
encore. Idempotent — ne touche jamais une permission déjà là, ne
l'attache à aucun rôle (ça reste à faire à la main).

Usage :
    docker compose exec api python scripts/sync_permissions.py
    # ou : make permissions
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from forge.db import get_session
from forge.security.models import Permission

from example_app.routes import ALL_ROUTERS


async def sync_permissions() -> tuple[list[str], list[str]]:
    """Crée les permissions manquantes, renvoie (créées, orphelines).
    Réutilisé par seed.py — une seule logique de scan des routes."""
    declared: set[str] = set()

    for router in ALL_ROUTERS:
        declared |= getattr(router, "declared_permissions", set())

    async with get_session() as session:
        existing = set((await session.execute(select(Permission.uid))).scalars().all())
        missing = sorted(declared - existing)

        for uid in missing:
            session.add(Permission(uid=uid, name=uid.replace("_", " ").title()))

        if missing:
            await session.commit()

    return missing, sorted(existing - declared)


async def main() -> None:
    created, unused = await sync_permissions()

    if created:
        print(f"Permissions créées : {', '.join(created)}")
    else:
        print("Rien à créer — toutes les permissions déclarées existent déjà en base.")

    if unused:
        print(f"En base mais plus référencées par aucune route : {', '.join(unused)}")


if __name__ == "__main__":
    asyncio.run(main())
