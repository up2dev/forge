import asyncio

from sqlalchemy import select

from forge.db import get_session
from forge.security.models import Permission
from scripts.sync_permissions import sync_permissions


def test_sync_creates_missing_permissions(client):
    created, unused = asyncio.run(sync_permissions())

    assert set(created) == {"BOOKS_DELETE", "NOTES_ADMIN"}
    assert unused == []

    async def _fetch():
        async with get_session() as session:
            return set((await session.execute(select(Permission.uid))).scalars().all())

    assert asyncio.run(_fetch()) == {"BOOKS_DELETE", "NOTES_ADMIN"}


def test_sync_is_idempotent(client):
    asyncio.run(sync_permissions())
    created, unused = asyncio.run(sync_permissions())

    assert created == []
    assert unused == []


def test_sync_reports_unused_permission(client):
    async def _seed_orphan():
        async with get_session() as session:
            session.add(Permission(uid="ORPHAN", name="Orphan"))
            await session.commit()

    asyncio.run(_seed_orphan())

    created, unused = asyncio.run(sync_permissions())

    assert "ORPHAN" in unused
    assert set(created) == {"BOOKS_DELETE", "NOTES_ADMIN"}


# ------------------------------------------------------------------ grant


def test_grant_gives_permission_to_role(client):
    import pytest

    from scripts.grant_permission import grant
    from tests.helpers import create_role

    create_role("EDITOR", [])
    asyncio.run(sync_permissions())

    assert asyncio.run(grant("EDITOR", "BOOKS_DELETE")) == "granted"
    assert asyncio.run(grant("EDITOR", "BOOKS_DELETE")) == "already"  # idempotent

    with pytest.raises(ValueError):
        asyncio.run(grant("GHOST", "BOOKS_DELETE"))

    with pytest.raises(ValueError):
        asyncio.run(grant("EDITOR", "NOPE"))


def test_granted_permission_actually_opens_the_route(client):
    """Bout en bout : permission créée par sync, donnée par grant,
    utilisée par un utilisateur réel sur une vraie route."""
    from scripts.grant_permission import grant
    from tests.helpers import auth, create_role, create_user, login

    role_id = create_role("CLEANER", [])
    create_user("carol", "pass1234", role_ids=[role_id])
    token = login(client, "carol", "pass1234")
    h = auth(token)
    author_id = client.post("/authors/", json={"name": "A"}, headers=h).json()["data"]["id"]
    book_id = client.post(
        "/books/", json={"title": "T", "year": 2000, "author_id": author_id}, headers=h
    ).json()["data"]["id"]

    assert client.delete(f"/books/{book_id}", headers=h).status_code == 403  # pas encore

    asyncio.run(sync_permissions())
    asyncio.run(grant("CLEANER", "BOOKS_DELETE"))

    assert client.delete(f"/books/{book_id}", headers=h).status_code == 200
