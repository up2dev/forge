import asyncio
import re
from datetime import datetime, timedelta, timezone

import pyotp
from sqlalchemy import select

from forge.db import get_session
from forge.security import password_reset
from forge.security.models import PasswordResetToken
from tests.helpers import auth, create_user, login


def _token_from_email(message) -> str:
    body = message.get_body(preferencelist=("html",)).get_content()

    return re.search(r"token=([A-Za-z0-9_\-]+)", body).group(1)


def _forgot(client, email="alice@example.test"):
    return client.post("/auth/pwd/forgot", json={"email": email})


def _reset(client, token, password="nouveaumdp1"):
    return client.post("/auth/pwd/reset", json={"token": token, "password": password})


def test_forgot_sends_email_with_frontend_link(client, sent_emails):
    create_user("alice", "pass1234")

    r = _forgot(client)

    assert r.status_code == 200
    assert len(sent_emails) == 1
    body = sent_emails[0].get_body(preferencelist=("html",)).get_content()
    assert "http://localhost:5173/reset-password?token=" in body  # le FRONT, pas l'API


def test_forgot_unknown_email_same_response_no_email(client, sent_emails):
    """Pas d'énumération de comptes via la réponse."""
    create_user("alice", "pass1234")

    known = _forgot(client, "alice@example.test")
    unknown = _forgot(client, "ghost@example.test")

    assert known.status_code == unknown.status_code == 200
    assert known.json()["data"] == unknown.json()["data"]
    assert len(sent_emails) == 1  # seulement pour le compte réel


def test_forgot_inactive_account_sends_nothing(client, sent_emails):
    create_user("bob", "pass1234", is_active=False)

    r = _forgot(client, "bob@example.test")

    assert r.status_code == 200
    assert sent_emails == []


def test_forgot_smtp_failure_does_not_leak_account_existence(client, monkeypatch):
    """Une erreur SMTP seulement quand le compte existe révélerait
    justement son existence — même réponse dans tous les cas."""
    import forge.mail.base as mail_base

    async def broken_send(message, **kwargs):
        raise ConnectionError("SMTP down")

    monkeypatch.setattr(mail_base.aiosmtplib, "send", broken_send)
    create_user("alice", "pass1234")

    known = _forgot(client, "alice@example.test")
    unknown = _forgot(client, "ghost@example.test")

    assert known.status_code == unknown.status_code == 200
    assert known.json()["data"] == unknown.json()["data"]


def test_reset_changes_password(client, sent_emails):
    create_user("alice", "pass1234")
    _forgot(client)

    r = _reset(client, _token_from_email(sent_emails[0]))

    assert r.status_code == 200
    assert client.post("/auth/login", json={"login": "alice", "password": "pass1234"}).status_code == 401
    assert client.post("/auth/login", json={"login": "alice", "password": "nouveaumdp1"}).status_code == 200


def test_reset_token_is_single_use(client, sent_emails):
    create_user("alice", "pass1234")
    _forgot(client)
    token = _token_from_email(sent_emails[0])

    assert _reset(client, token).status_code == 200
    assert _reset(client, token, "autremdp123").status_code == 400


def test_new_request_invalidates_previous_link(client, sent_emails):
    create_user("alice", "pass1234")
    _forgot(client)
    _forgot(client)

    old_token = _token_from_email(sent_emails[0])
    new_token = _token_from_email(sent_emails[1])

    assert _reset(client, old_token).status_code == 400
    assert _reset(client, new_token).status_code == 200


def test_reset_rejects_expired_token(client, sent_emails):
    """Comparaison de date complète — un token expiré est refusé même
    de peu."""
    create_user("alice", "pass1234")
    _forgot(client)
    token = _token_from_email(sent_emails[0])

    async def _expire():
        async with get_session() as session:
            row = (await session.execute(select(PasswordResetToken))).scalar_one()
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await session.commit()

    asyncio.run(_expire())

    assert _reset(client, token).status_code == 400


def test_reset_rejects_garbage_token(client):
    assert _reset(client, "n-importe-quoi").status_code == 400


def test_reset_rejects_short_password(client, sent_emails):
    create_user("alice", "pass1234")
    _forgot(client)

    r = _reset(client, _token_from_email(sent_emails[0]), "court")

    assert r.status_code == 422


def test_reset_revokes_existing_sessions_by_default(client, sent_emails):
    """Un mot de passe compromis ne doit pas laisser une session déjà
    ouverte ailleurs valide après le reset."""
    create_user("alice", "pass1234")
    old_session = login(client, "alice", "pass1234")
    _forgot(client)

    _reset(client, _token_from_email(sent_emails[0]))

    assert client.get("/auth/me", headers=auth(old_session)).status_code == 401


def test_reset_keeps_sessions_when_revocation_disabled(client, sent_emails, monkeypatch):
    from forge import config

    monkeypatch.setenv("FORGE_PWD_RESET_REVOKES_SESSIONS", "0")
    config.get_settings.cache_clear()

    create_user("alice", "pass1234")
    old_session = login(client, "alice", "pass1234")
    _forgot(client)

    _reset(client, _token_from_email(sent_emails[0]))

    assert client.get("/auth/me", headers=auth(old_session)).status_code == 200


def test_reset_leaves_no_pending_link_behind(client, sent_emails):
    create_user("alice", "pass1234")
    _forgot(client)
    _reset(client, _token_from_email(sent_emails[0]))

    async def _count():
        async with get_session() as session:
            return len((await session.execute(select(PasswordResetToken))).scalars().all())

    assert asyncio.run(_count()) == 0


def test_reset_does_not_bypass_mfa(client, sent_emails):
    """Le reset ne connecte pas — le login qui suit passe toujours par
    le MFA confirmé."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = client.post("/auth/mfa/setup", json={"method": "totp"}, headers=auth(token)).json()["data"]["secret"]
    client.post(
        "/auth/mfa/confirm", json={"method": "totp", "code": pyotp.TOTP(secret).now()}, headers=auth(token)
    )

    _forgot(client)
    assert _reset(client, _token_from_email(sent_emails[0])).status_code == 200

    r = client.post("/auth/login", json={"login": "alice", "password": "nouveaumdp1"})

    assert r.status_code == 200
    assert "pending_token" in r.json()["data"]
    assert "token" not in r.json()["data"]


def test_purge_expired_removes_only_expired(client, sent_emails):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")
    _forgot(client, "alice@example.test")
    _forgot(client, "bob@example.test")

    async def _expire_first():
        async with get_session() as session:
            rows = (await session.execute(select(PasswordResetToken))).scalars().all()
            rows[0].expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            await session.commit()

    asyncio.run(_expire_first())

    assert asyncio.run(password_reset.purge_expired()) == 1

    async def _count():
        async with get_session() as session:
            return len((await session.execute(select(PasswordResetToken))).scalars().all())

    assert asyncio.run(_count()) == 1


def test_forgot_is_rate_limited(client, sent_emails):
    create_user("alice", "pass1234")

    for _ in range(5):
        _forgot(client)

    assert _forgot(client).status_code == 429
