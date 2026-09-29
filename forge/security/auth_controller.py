"""
forge.security.auth_controller
===============================
login/logout/me, sans passer par BaseController/CRUD — ce ne sont pas
des actions CRUD sur une ressource.

Fourni par le framework (contrairement à BookController, écrit par
l'app) : n'importe quelle app Forge obtient login/logout/me d'entrée,
il suffit de brancher le router — voir forge.security.routes.auth_router.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import delete, select

from forge.config import get_settings
from forge.db import get_session
from forge.i18n import trans
from forge.security import mfa, password_reset
from forge.security.dependencies import bearer_scheme, get_current_user
from forge.security.models import AccessToken, User
from forge.security.passwords import hash_password, verify_password
from forge.security.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MfaPendingResponse,
    ResetPasswordRequest,
    TokenResponse,
    UserRead,
)
from forge.security.tokens import generate_token, hash_token


async def issue_access_token(user: User) -> TokenResponse:
    """Émet un vrai token d'accès — appelé par login() directement
    (pas de MFA confirmé) ou par MfaController.verify() (MFA validé)."""
    ttl_minutes = get_settings().token_ttl_minutes
    token = generate_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes) if ttl_minutes > 0 else None
    )

    async with get_session() as session:
        session.add(AccessToken(user_id=user.id, token_hash=hash_token(token), expires_at=expires_at))
        await session.commit()

    return TokenResponse(token=token, expires_at=expires_at, user=UserRead.model_validate(user))


class AuthController:
    async def login(
        self, payload: LoginRequest, request: Request
    ) -> TokenResponse | MfaPendingResponse:
        locale = getattr(request.state, "locale", None)

        async with get_session() as session:
            stmt = select(User).where(User.login == payload.login)
            user = (await session.execute(stmt)).scalar_one_or_none()

            # Même message d'erreur, login inexistant ou mot de passe
            # faux — pas d'énumération de comptes via la réponse.
            if user is None or not verify_password(payload.password, user.password_hash):
                raise HTTPException(401, trans("auth.invalid_credentials", locale))

            if not user.is_active:
                raise HTTPException(403, trans("auth.inactive", locale))

        if get_settings().mfa_enabled and not mfa.is_exempt(user):
            methods = await mfa.confirmed_methods(user.id)

            if methods:
                pending_token = await mfa.issue_pending_token(user.id, "verify")

                if "email" in methods:
                    await mfa.send_email_code(user, locale)

                return MfaPendingResponse(pending_token=pending_token, intent="verify", methods=methods)

            if get_settings().mfa_force_enrollment:
                pending_token = await mfa.issue_pending_token(user.id, "enroll")

                return MfaPendingResponse(
                    pending_token=pending_token,
                    intent="enroll",
                    methods=get_settings().mfa_methods,
                )

        return await issue_access_token(user)

    async def logout(
        self, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
    ) -> dict:
        if credentials is None:
            raise HTTPException(401, "Missing bearer token")

        async with get_session() as session:
            await session.execute(
                delete(AccessToken).where(AccessToken.token_hash == hash_token(credentials.credentials))
            )
            await session.commit()

        return {"logged_out": True}

    async def me(self, user: User = Depends(get_current_user)) -> UserRead:
        return UserRead.model_validate(user)

    async def forgot_password(self, payload: ForgotPasswordRequest, request: Request) -> dict:
        """Toujours la même réponse, que le compte existe ou non — pas
        d'énumération de comptes. Une nouvelle demande invalide le lien
        précédent (voir password_reset.issue_reset_token)."""
        locale = getattr(request.state, "locale", None)

        async with get_session() as session:
            stmt = select(User).where(User.email == payload.email)
            user = (await session.execute(stmt)).scalar_one_or_none()

        if user is not None and user.is_active:
            token = await password_reset.issue_reset_token(user.id)

            try:
                await password_reset.send_reset_email(user, token, locale)
            except Exception:
                # Déjà loggué par BaseMail.send() — jamais remonté au
                # client : une erreur SMTP seulement quand le compte
                # existe révélerait justement son existence.
                pass

        return {"detail": trans("auth.pwd.forgot_sent", locale)}

    async def reset_password(self, payload: ResetPasswordRequest, request: Request) -> dict:
        locale = getattr(request.state, "locale", None)
        user = await password_reset.resolve_reset_token(payload.token)

        if user is None or not user.is_active:
            raise HTTPException(400, trans("auth.pwd.invalid_token", locale))

        async with get_session() as session:
            db_user = await session.get(User, user.id)
            db_user.password_hash = hash_password(payload.password)

            if get_settings().pwd_reset_revokes_sessions:
                await session.execute(delete(AccessToken).where(AccessToken.user_id == user.id))

            await session.commit()

        # Tous les liens en attente, pas seulement celui utilisé.
        await password_reset.revoke_reset_tokens(user.id)

        return {"detail": trans("auth.pwd.reset_done", locale)}
