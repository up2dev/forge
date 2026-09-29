from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from forge.config import get_settings

settings = get_settings()

# FORGE_DB_POOL=null (posé par tests/conftest.py) désactive le pool de
# connexions : chaque asyncio.run() y crée sa propre boucle
# d'événements, et une connexion asyncpg réutilisée d'une boucle à
# l'autre plante ("attached to a different loop") — jamais en
# production, où uvicorn tourne sur UNE seule boucle en continu.
_pool_kwargs = {"poolclass": NullPool} if os.environ.get("FORGE_DB_POOL") == "null" else {}
engine = create_async_engine(settings.database_url, echo=settings.sql_echo, **_pool_kwargs)
_SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession]:
    async with _SessionFactory() as session:
        yield session
