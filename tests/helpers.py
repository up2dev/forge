import asyncio

from sqlalchemy import select

from forge.db import get_session
from forge.security.models import Permission, Role, User
from forge.security.passwords import hash_password


def create_user(login: str, password: str, *, email=None, role_ids=None, is_active=True) -> int:
    async def _create():
        async with get_session() as session:
            user = User(
                login=login,
                email=email or f"{login}@example.test",
                password_hash=hash_password(password),
                is_active=is_active,
            )

            if role_ids:
                stmt = select(Role).where(Role.id.in_(role_ids))
                user.roles = list((await session.execute(stmt)).scalars().all())

            session.add(user)
            await session.commit()
            await session.refresh(user)

            return user.id

    return asyncio.run(_create())


def create_role(uid: str, permission_uids=()) -> int:
    async def _create():
        async with get_session() as session:
            perms = []

            for puid in permission_uids:
                p = Permission(uid=puid, name=puid)
                session.add(p)
                perms.append(p)

            await session.flush()

            role = Role(uid=uid, name=uid)
            role.permissions = perms
            session.add(role)
            await session.commit()
            await session.refresh(role)

            return role.id

    return asyncio.run(_create())


def login(client, login_name: str, password: str) -> str:
    r = client.post("/auth/login", json={"login": login_name, "password": password})
    assert r.status_code == 200, r.text

    return r.json()["data"]["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
