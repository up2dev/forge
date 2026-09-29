"""
forge.security.password_reset
================================
Lien de reset envoyé par email — un token opaque haute-entropie
(même principe qu'AccessToken/MfaPendingToken), jamais en clair en
base. Le lien pointe vers le FRONT (FORGE_FRONTEND_URL), pas vers
l'API elle-même : c'est le front qui affiche le formulaire et appelle
ensuite POST /auth/pwd/reset avec le token.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from forge.config import get_settings
from forge.db import get_session
from forge.i18n import trans
from forge.mail.base import BaseMail
from forge.security.models import PasswordResetToken, User
from forge.security.tokens import generate_token, hash_token


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def issue_reset_token(user_id: int) -> str:
    """Une seule demande active à la fois — une nouvelle invalide
    l'ancienne plutôt que de laisser plusieurs liens valides en
    parallèle (repli sur cette version, plus simple que d'exposer une
    liste de liens à révoquer un par un)."""
    settings = get_settings()
    token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.pwd_reset_token_ttl_minutes)

    async with get_session() as session:
        await session.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
        session.add(
            PasswordResetToken(token_hash=hash_token(token), user_id=user_id, expires_at=expires_at)
        )
        await session.commit()

    return token


async def resolve_reset_token(token: str) -> User | None:
    """Comparaison de date complète (jour+heure+minute+seconde) — pas
    seulement les minutes de l'intervalle restant, qui laisserait
    passer un token expiré depuis N heures pile (+ quelques secondes)."""
    async with get_session() as session:
        stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token))
        entry = (await session.execute(stmt)).scalar_one_or_none()

        if entry is None or _aware(entry.expires_at) < datetime.now(timezone.utc):
            return None

        return await session.get(User, entry.user_id)


async def revoke_reset_tokens(user_id: int) -> None:
    """Tous les liens en attente pour cet utilisateur, pas seulement
    celui utilisé — un reset réussi doit invalider toute demande
    antérieure encore active, pas juste celle qui a servi."""
    async with get_session() as session:
        await session.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
        await session.commit()


async def send_reset_email(user: User, token: str, locale: str | None = None) -> None:
    settings = get_settings()
    link = f"{settings.frontend_url}{settings.frontend_pwd_reset_path}?token={token}"

    mail = BaseMail(
        template="pwd_reset.html",
        context={
            "greeting": trans("mail.pwd_reset.greeting", locale, name=user.login),
            "intro": trans("mail.pwd_reset.intro", locale),
            "link": link,
            "expiry_notice": trans(
                "mail.pwd_reset.expiry", locale, minutes=settings.pwd_reset_token_ttl_minutes
            ),
        },
        to=[user.email],
        subject=trans("mail.pwd_reset.subject", locale),
    )
    await mail.send()


async def purge_expired() -> int:
    """Suppression des liens expirés — planifiée chaque nuit dans
    example_app/schedule.py (forge/scheduler.py), et à la demande via
    scripts/prune_expired_tokens.py."""
    async with get_session() as session:
        result = await session.execute(
            delete(PasswordResetToken).where(PasswordResetToken.expires_at < datetime.now(timezone.utc))
        )
        await session.commit()

        return result.rowcount
