"""
forge.security.mfa
====================
TOTP (pyotp), codes email, et le token "pending" entre le mot de
passe et la vérification MFA. "method" n'est pas limité à deux
valeurs — ajouter "webauthn" pour une clé Yubikey ne change ni les
modèles ni ce module.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone
from secrets import SystemRandom

import pyotp
from sqlalchemy import delete, select

from forge.config import get_settings
from forge.db import get_session
from forge.i18n import trans
from forge.mail.base import BaseMail
from forge.security.models import MfaEmailCode, MfaMethod, MfaPendingToken, User
from forge.security.tokens import generate_token, hash_token

_rand = SystemRandom()


def generate_secret() -> str:
    return pyotp.random_base32()


def qr_uri(email: str, secret: str) -> str:
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=email, issuer_name=get_settings().mfa_issuer
    )


def _totp_counter_for(secret: str, code: str, valid_window: int = 1) -> int | None:
    """Cherche, dans la fenêtre de tolérance, quel time-step correspond
    au code fourni — None si aucun ne correspond. pyotp.verify() dit
    seulement oui/non ; il faut ce détail pour l'anti-rejeu (comparer
    CE time-step à celui déjà accepté, pas juste répondre "valide")."""
    totp = pyotp.TOTP(secret)
    now = int(time.time())

    for offset in range(-valid_window, valid_window + 1):
        for_time = now + offset * totp.interval

        if totp.at(for_time) == code:
            return int(for_time / totp.interval)

    return None


async def verify_totp_and_record(method_row_id: int, secret: str, code: str) -> bool:
    """Vérifie le code ET l'anti-rejeu : un code déjà accepté (même
    time-step ou plus ancien) est refusé même s'il reste valide dans
    la fenêtre de tolérance — sans ça, un code intercepté reste
    utilisable une deuxième fois tant que sa fenêtre de 30-90s dure."""
    counter = _totp_counter_for(secret, code)

    if counter is None:
        return False

    async with get_session() as session:
        row = await session.get(MfaMethod, method_row_id)

        if row.last_totp_counter is not None and counter <= row.last_totp_counter:
            return False

        row.last_totp_counter = counter
        await session.commit()

    return True


def generate_email_code() -> str:
    return f"{_rand.randint(0, 999999):06d}"


async def store_email_code(user_id: int, code: str) -> None:
    settings = get_settings()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.mfa_email_code_ttl_minutes)

    async with get_session() as session:
        await session.execute(delete(MfaEmailCode).where(MfaEmailCode.user_id == user_id))
        session.add(MfaEmailCode(user_id=user_id, code_hash=_hash_code(code), expires_at=expires_at))
        await session.commit()


async def send_email_code(user: User, locale: str | None = None) -> None:
    """Génère, stocke et envoie un code — point d'entrée unique,
    utilisé par login() (email confirmé) et par le self-service
    enable/resend."""
    settings = get_settings()
    code = generate_email_code()
    await store_email_code(user.id, code)

    await BaseMail(
        template="mfa_code.html",
        context={
            "intro": trans("mail.mfa.intro", locale),
            "code": code,
            "expiry_notice": trans(
                "mail.mfa.expiry", locale, minutes=str(settings.mfa_email_code_ttl_minutes)
            ),
        },
        to=[user.email],
        subject=trans("mail.mfa.subject", locale),
    ).send()


async def verify_email_code(user_id: int, code: str) -> bool:
    async with get_session() as session:
        stmt = select(MfaEmailCode).where(MfaEmailCode.user_id == user_id)
        entry = (await session.execute(stmt)).scalar_one_or_none()

        if entry is None:
            return False

        expires_at = _aware(entry.expires_at)
        matches = hmac.compare_digest(entry.code_hash, _hash_code(code))

        await session.delete(entry)  # usage unique, valide ou non
        await session.commit()

    return matches and expires_at > datetime.now(timezone.utc)


async def confirmed_methods(user_id: int) -> list[str]:
    async with get_session() as session:
        stmt = select(MfaMethod.method).where(
            MfaMethod.user_id == user_id, MfaMethod.confirmed_at.is_not(None)
        )
        return list((await session.execute(stmt)).scalars().all())


async def has_confirmed(user_id: int, method: str) -> bool:
    return method in await confirmed_methods(user_id)


async def issue_pending_token(user_id: int, intent: str) -> str:
    settings = get_settings()
    token = generate_token()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.mfa_pending_ttl_minutes)

    async with get_session() as session:
        session.add(
            MfaPendingToken(
                token_hash=hash_token(token), user_id=user_id, intent=intent, expires_at=expires_at
            )
        )
        await session.commit()

    return token


async def resolve_pending_token(token: str) -> MfaPendingToken | None:
    async with get_session() as session:
        stmt = select(MfaPendingToken).where(MfaPendingToken.token_hash == hash_token(token))
        entry = (await session.execute(stmt)).scalar_one_or_none()

    if entry is None or _aware(entry.expires_at) < datetime.now(timezone.utc):
        return None

    return entry


async def invalidate_pending_token(token: str) -> None:
    async with get_session() as session:
        await session.execute(
            delete(MfaPendingToken).where(MfaPendingToken.token_hash == hash_token(token))
        )
        await session.commit()


async def record_failed_attempt(token: str) -> int:
    """Incrémente failed_attempts sur ce pending_token, renvoie le
    nouveau total — à comparer par l'appelant contre
    FORGE_MFA_MAX_ATTEMPTS pour décider de détruire le token."""
    async with get_session() as session:
        stmt = select(MfaPendingToken).where(MfaPendingToken.token_hash == hash_token(token))
        entry = (await session.execute(stmt)).scalar_one_or_none()

        if entry is None:
            return 0

        entry.failed_attempts += 1
        await session.commit()

        return entry.failed_attempts


def _has_permission(user: User, permission: str) -> bool:
    if not permission:
        return False

    held = {p.uid for role in user.roles for p in role.permissions}

    return permission in held


def is_exempt(user: User) -> bool:
    return _has_permission(user, get_settings().mfa_bypass_permission)


def can_force_disable(user: User) -> bool:
    """Autorise à désactiver sa dernière méthode MFA même sous
    inscription forcée — voir MfaController.disable()."""
    return _has_permission(user, get_settings().mfa_force_disable_permission)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
