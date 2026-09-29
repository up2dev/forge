#!/usr/bin/env python3
"""
scripts/prune_expired_tokens.py
=================================
Supprime les tokens expirés (liens de reset de mot de passe), à la
demande. Le planificateur le fait déjà chaque nuit à 3h (voir
example_app/schedule.py) — ce script sert à le forcer.

Usage :
    docker compose exec api python scripts/prune_expired_tokens.py
    # ou : make prune
"""
from __future__ import annotations

import asyncio

from forge.security import password_reset


async def main() -> None:
    count = await password_reset.purge_expired()
    print(f"{count} lien(s) de reset expiré(s) supprimé(s).")


if __name__ == "__main__":
    asyncio.run(main())
