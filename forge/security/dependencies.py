"""
forge.security.dependencies
============================
Auth en dépendances FastAPI, résolue par route plutôt que par un
middleware global — permet à ControllerRouter d'imposer une décision
sur chaque route (voir forge.routing).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from forge.db import get_session
from forge.security.models import AccessToken, Role, User
from forge.security.tokens import hash_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None:
        raise HTTPException(401, "Missing bearer token")

    return await _resolve_user(credentials.credentials)


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    """Même résolution que get_current_user, mais renvoie None au lieu
    d'un 401 sans token — pour les Repositories scopés utilisés sur
    des routes publiques."""
    if credentials is None:
        return None

    return await _resolve_user(credentials.credentials)


async def _resolve_user(token: str) -> User:
    token_hash = hash_token(token)

    async with get_session() as session:
        stmt = (
            select(AccessToken)
            .where(AccessToken.token_hash == token_hash)
            .options(
                selectinload(AccessToken.user)
                .selectinload(User.roles)
                .selectinload(Role.permissions)
            )
        )
        access_token = (await session.execute(stmt)).scalar_one_or_none()

    if access_token is None:
        raise HTTPException(401, "Invalid or expired token")

    if access_token.expires_at is not None:
        expires_at = access_token.expires_at

        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < datetime.now(timezone.utc):
            raise HTTPException(401, "Invalid or expired token")

    if not access_token.user.is_active:
        raise HTTPException(403, "Inactive user")

    return access_token.user


def require_permission(permission_uid: str):
    """Depends(require_permission("BOOKS_LIST")) — la permission est
    déclarée explicitement à l'enregistrement de la route, jamais
    déduite du chemin."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        held = {p.uid for role in user.roles for p in role.permissions}

        if permission_uid not in held:
            raise HTTPException(403, f"Missing permission: {permission_uid}")

        return user

    return _check
