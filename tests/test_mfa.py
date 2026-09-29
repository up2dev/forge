import re
import time

import pyotp

from tests.helpers import auth, create_role, create_user, login


def _extract_code(message) -> str:
    html_part = message.get_body(preferencelist=("html",))
    body = html_part.get_content() if html_part is not None else str(message)
    match = re.search(r"(\d{6})", body)
    return match.group(1)


def _setup_totp(client, token) -> str:
    r = client.post("/auth/mfa/setup", json={"method": "totp"}, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()["data"]["secret"]


def _confirm_totp(client, token, secret) -> None:
    code = pyotp.TOTP(secret).now()
    r = client.post("/auth/mfa/confirm", json={"method": "totp", "code": code}, headers=auth(token))
    assert r.status_code == 200, r.text


def _next_totp_code(secret: str) -> str:
    """Code du time-step SUIVANT, sans attendre 30s pour de vrai —
    nécessaire dès qu'un test génère un deuxième code après un premier
    déjà consommé (ex. après _confirm_totp) : l'anti-rejeu refuse à
    raison de régénérer .now() deux fois dans la même fenêtre."""
    totp = pyotp.TOTP(secret)

    return totp.at(time.time() + totp.interval)


# ---------------------------------------------------------- self-service


def test_totp_setup_and_confirm(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)


def test_totp_setup_with_imported_secret(client):
    """Le cas token matériel (C105, Yubikey OTP...) — le secret vient
    du fabricant, pas généré par nous."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    hardware_secret = pyotp.random_base32()

    r = client.post(
        "/auth/mfa/setup", json={"method": "totp", "secret": hardware_secret}, headers=auth(token)
    )

    assert r.status_code == 200
    assert r.json()["data"]["secret"] == hardware_secret

    _confirm_totp(client, token, hardware_secret)


def test_totp_confirm_wrong_code_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    _setup_totp(client, token)

    r = client.post("/auth/mfa/confirm", json={"method": "totp", "code": "000000"}, headers=auth(token))

    assert r.status_code == 400


def test_totp_secret_encrypted_at_rest(client):
    """Régression : le secret TOTP ne doit jamais être lisible en clair
    directement en base — chiffré (voir forge/security/crypto.py)."""
    import asyncio

    from sqlalchemy import select

    from forge.db import get_session
    from forge.security.models import MfaMethod

    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)

    async def _fetch_stored():
        async with get_session() as session:
            stmt = select(MfaMethod.secret).where(MfaMethod.method == "totp")
            return (await session.execute(stmt)).scalar_one()

    stored = asyncio.run(_fetch_stored())

    assert stored != secret


def test_totp_anti_replay_rejects_same_code_twice(client):
    """Régression critique : un code TOTP déjà accepté ne doit jamais
    fonctionner une deuxième fois, même valide dans sa fenêtre."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)  # consomme déjà le code de ce time-step

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    same_code = pyotp.TOTP(secret).now()  # même time-step que _confirm_totp
    r = client.post(
        "/auth/mfa/verify", json={"pending_token": pending_token, "method": "totp", "code": same_code}
    )

    assert r.status_code == 400


def test_totp_max_attempts_destroys_pending_token(client, monkeypatch):
    """Indépendant du rate-limit par IP : après FORGE_MFA_MAX_ATTEMPTS
    codes faux sur UN pending_token, il est détruit — retour à un
    login complet, même avant que le rate-limit IP ne s'active."""
    from forge import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("FORGE_MFA_MAX_ATTEMPTS", "3")
    config.get_settings.cache_clear()

    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    for _ in range(2):
        r = client.post(
            "/auth/mfa/verify", json={"pending_token": pending_token, "method": "totp", "code": "000000"}
        )
        assert r.status_code == 400  # pas encore détruit

    r = client.post(
        "/auth/mfa/verify", json={"pending_token": pending_token, "method": "totp", "code": "000000"}
    )
    assert r.status_code == 401  # 3e essai faux -> détruit

    r = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token, "method": "totp", "code": _next_totp_code(secret)},
    )
    assert r.status_code == 401  # le pending_token n'existe plus, même avec le bon code

    config.get_settings.cache_clear()


def test_cannot_disable_last_method_when_enrollment_forced(client, monkeypatch):
    from forge import config

    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")  # login normal, avant l'activation
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    config.get_settings.cache_clear()
    monkeypatch.setenv("FORGE_MFA_FORCE_ENROLLMENT", "1")
    config.get_settings.cache_clear()

    r = client.request("DELETE", "/auth/mfa/totp", headers=auth(token))

    assert r.status_code == 400
    assert client.get("/auth/mfa/methods", headers=auth(token)).json()["data"]["enabled"] == ["totp"]

    config.get_settings.cache_clear()


def test_force_disable_permission_bypasses_last_method_guard(client, monkeypatch):
    """La permission dédiée lève le garde-fou — sans elle, absolu."""
    from forge import config

    role_id = create_role("MFA_OVERRIDE", ["MFA_FORCE_DISABLE"])
    create_user("alice", "pass1234", role_ids=[role_id])
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    config.get_settings.cache_clear()
    monkeypatch.setenv("FORGE_MFA_FORCE_ENROLLMENT", "1")
    monkeypatch.setenv("FORGE_MFA_FORCE_DISABLE_PERMISSION", "MFA_FORCE_DISABLE")
    config.get_settings.cache_clear()

    r = client.request("DELETE", "/auth/mfa/totp", headers=auth(token))

    assert r.status_code == 200
    assert client.get("/auth/mfa/methods", headers=auth(token)).json()["data"]["enabled"] == []

    config.get_settings.cache_clear()


def test_can_disable_method_when_enrollment_not_forced(client):
    """Le garde-fou ne s'applique QUE si l'inscription est obligatoire
    — sinon désactiver sa dernière méthode reste permis, comme avant."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    r = client.request("DELETE", "/auth/mfa/totp", headers=auth(token))

    assert r.status_code == 200


def test_setup_unknown_method_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = client.post("/auth/mfa/setup", json={"method": "sms"}, headers=auth(token))

    assert r.status_code == 404


def test_email_mfa_full_flow(client, sent_emails):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = client.post("/auth/mfa/setup", json={"method": "email"}, headers=auth(token))
    assert r.status_code == 200
    assert len(sent_emails) == 1

    setup_code = _extract_code(sent_emails[0])
    r = client.post("/auth/mfa/confirm", json={"method": "email", "code": setup_code}, headers=auth(token))
    assert r.status_code == 200

    login_resp = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})
    assert "pending_token" in login_resp.json()["data"]
    assert len(sent_emails) == 2

    verify_code = _extract_code(sent_emails[1])
    r = client.post(
        "/auth/mfa/verify",
        json={
            "pending_token": login_resp.json()["data"]["pending_token"],
            "method": "email",
            "code": verify_code,
        },
    )

    assert r.status_code == 200
    assert "token" in r.json()["data"]


def test_methods_lists_available_and_enabled(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    r = client.get("/auth/mfa/methods", headers=auth(token))

    assert r.status_code == 200
    assert r.json()["data"]["enabled"] == ["totp"]
    assert set(r.json()["data"]["available"]) == {"totp", "email", "webauthn"}


def test_disable_removes_method(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    client.request("DELETE", "/auth/mfa/totp", headers=auth(token))

    assert client.get("/auth/mfa/methods", headers=auth(token)).json()["data"]["enabled"] == []
    assert "token" in client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]


# ---------------------------------------------------------------- verify


def test_login_returns_pending_verify_once_mfa_confirmed(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    r = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})

    assert r.status_code == 200
    assert r.json()["data"]["intent"] == "verify"
    assert r.json()["data"]["methods"] == ["totp"]


def test_verify_with_totp_issues_real_token(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    r = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token, "method": "totp", "code": _next_totp_code(secret)},
    )

    assert r.status_code == 200
    assert "token" in r.json()["data"]


def test_verify_with_wrong_code_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    r = client.post(
        "/auth/mfa/verify", json={"pending_token": pending_token, "method": "totp", "code": "000000"}
    )

    assert r.status_code == 400


def test_mfa_verify_is_rate_limited(client):
    create_user("alice", "pass1234")

    for _ in range(5):
        client.post("/auth/mfa/verify", json={"pending_token": "x", "method": "totp", "code": "000000"})

    r = client.post("/auth/mfa/verify", json={"pending_token": "x", "method": "totp", "code": "000000"})

    assert r.status_code == 429


# ------------------------------------------------------- forced enrollment


def test_login_without_mfa_still_works_when_not_forced(client):
    """FORGE_MFA_FORCE_ENROLLMENT=0 par défaut: pas de méthode -> login normal."""
    create_user("alice", "pass1234")

    r = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})

    assert r.status_code == 200
    assert "token" in r.json()["data"]


def test_forced_enrollment_blocks_login_until_method_confirmed(client, monkeypatch):
    from forge import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("FORGE_MFA_FORCE_ENROLLMENT", "1")
    config.get_settings.cache_clear()

    create_user("alice", "pass1234")

    r = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["intent"] == "enroll"
    pending_token = body["pending_token"]

    # setup + confirm SANS Bearer, avec le pending_token d'enrôlement
    r = client.post("/auth/mfa/setup", json={"method": "totp", "pending_token": pending_token})
    assert r.status_code == 200, r.text
    secret = r.json()["data"]["secret"]

    r = client.post(
        "/auth/mfa/confirm",
        json={"method": "totp", "code": pyotp.TOTP(secret).now(), "pending_token": pending_token},
    )

    assert r.status_code == 200
    assert r.json()["data"]["token"] is not None  # la confirmation complète la connexion

    config.get_settings.cache_clear()


def test_forced_enrollment_methods_endpoint_works_without_bearer(client, monkeypatch):
    from forge import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("FORGE_MFA_FORCE_ENROLLMENT", "1")
    config.get_settings.cache_clear()

    create_user("alice", "pass1234")
    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    r = client.get(f"/auth/mfa/methods?pending_token={pending_token}")

    assert r.status_code == 200
    assert r.json()["data"]["enabled"] == []
    assert set(r.json()["data"]["available"]) == {"totp", "email", "webauthn"}

    config.get_settings.cache_clear()


def test_setup_without_bearer_or_pending_token_rejected(client):
    r = client.post("/auth/mfa/setup", json={"method": "totp"})

    assert r.status_code == 401


# ------------------------------------------------------- resend without bearer


def test_resend_code_works_during_verify_without_bearer(client, sent_emails):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    client.post("/auth/mfa/setup", json={"method": "email"}, headers=auth(token))
    setup_code = _extract_code(sent_emails[-1])
    client.post("/auth/mfa/confirm", json={"method": "email", "code": setup_code}, headers=auth(token))

    login_resp = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})
    pending_token = login_resp.json()["data"]["pending_token"]
    emails_before = len(sent_emails)

    r = client.post("/auth/mfa/request-code", json={"pending_token": pending_token})

    assert r.status_code == 200
    assert len(sent_emails) == emails_before + 1

    new_code = _extract_code(sent_emails[-1])
    r = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token, "method": "email", "code": new_code},
    )
    assert r.status_code == 200
    assert "token" in r.json()["data"]


def test_resend_code_without_bearer_or_pending_token_rejected(client):
    r = client.post("/auth/mfa/request-code", json={})

    assert r.status_code == 401


def test_resend_code_with_verify_token_cannot_be_used_to_setup(client):
    """Un pending_token "verify" (une méthode déjà confirmée) ne doit
    jamais permettre d'appeler setup/confirm — seul un token "enroll"
    le peut."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    r = client.post("/auth/mfa/setup", json={"method": "email", "pending_token": pending_token})

    assert r.status_code == 401


# --------------------------------------------------------------- webauthn


def _setup_webauthn(client, token):
    from tests.webauthn_helpers import VirtualAuthenticator

    r = client.post("/auth/mfa/setup", json={"method": "webauthn"}, headers=auth(token))
    assert r.status_code == 200, r.text
    options = r.json()["data"]["webauthn_options"]

    device = VirtualAuthenticator()
    response = device.register(options, WEBAUTHN_ORIGIN)

    r = client.post(
        "/auth/mfa/confirm", json={"method": "webauthn", "webauthn_response": response}, headers=auth(token)
    )
    assert r.status_code == 200, r.text

    return device


WEBAUTHN_ORIGIN = "http://localhost:8000"


def test_webauthn_setup_and_confirm(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    _setup_webauthn(client, token)

    assert client.get("/auth/mfa/methods", headers=auth(token)).json()["data"]["enabled"] == ["webauthn"]


def test_webauthn_full_login_cycle(client):
    """Le cas critique : cycle complet avec une vraie clé EC logicielle
    et de vraies signatures, vérifiées par la même lib que le serveur."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    device = _setup_webauthn(client, token)

    login_resp = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})
    assert login_resp.json()["data"]["methods"] == ["webauthn"]
    pending_token = login_resp.json()["data"]["pending_token"]

    r = client.post("/auth/mfa/webauthn/login-options", json={"pending_token": pending_token})
    assert r.status_code == 200, r.text
    options = r.json()["data"]["options"]

    response = device.authenticate(options, WEBAUTHN_ORIGIN)
    r = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token, "method": "webauthn", "webauthn_response": response},
    )

    assert r.status_code == 200, r.text
    assert "token" in r.json()["data"]


def test_webauthn_replayed_signature_rejected(client):
    """Régression critique : une signature déjà utilisée ne doit
    jamais réussir une deuxième fois (détection de clé clonée via le
    compteur)."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    device = _setup_webauthn(client, token)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]
    options = client.post(
        "/auth/mfa/webauthn/login-options", json={"pending_token": pending_token}
    ).json()["data"]["options"]
    response = device.authenticate(options, WEBAUTHN_ORIGIN)

    ok = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token, "method": "webauthn", "webauthn_response": response},
    )
    assert ok.status_code == 200

    pending_token2 = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]
    client.post("/auth/mfa/webauthn/login-options", json={"pending_token": pending_token2})

    replay = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token2, "method": "webauthn", "webauthn_response": response},
    )

    assert replay.status_code == 400


def test_webauthn_second_real_login_works(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    device = _setup_webauthn(client, token)

    for _ in range(2):
        pending_token = client.post(
            "/auth/login", json={"login": "alice", "password": "pass1234"}
        ).json()["data"]["pending_token"]
        options = client.post(
            "/auth/mfa/webauthn/login-options", json={"pending_token": pending_token}
        ).json()["data"]["options"]
        response = device.authenticate(options, WEBAUTHN_ORIGIN)

        r = client.post(
            "/auth/mfa/verify",
            json={"pending_token": pending_token, "method": "webauthn", "webauthn_response": response},
        )

        assert r.status_code == 200, r.text


def test_webauthn_wrong_signature_rejected(client):
    import base64

    from tests.webauthn_helpers import VirtualAuthenticator

    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    _setup_webauthn(client, token)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]
    options = client.post(
        "/auth/mfa/webauthn/login-options", json={"pending_token": pending_token}
    ).json()["data"]["options"]

    wrong_device = VirtualAuthenticator()  # une autre clé, jamais enregistrée
    wrong_device.credential_id = base64.urlsafe_b64decode(options["allowCredentials"][0]["id"] + "==")
    response = wrong_device.authenticate(options, WEBAUTHN_ORIGIN)

    r = client.post(
        "/auth/mfa/verify",
        json={"pending_token": pending_token, "method": "webauthn", "webauthn_response": response},
    )

    assert r.status_code == 400


def test_webauthn_login_options_requires_confirmed_method(client):
    """Un pending_token "verify" existe (via TOTP), mais aucune clé
    WebAuthn confirmée pour ce compte -> refusé, pas de 500."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    secret = _setup_totp(client, token)
    _confirm_totp(client, token, secret)

    pending_token = client.post(
        "/auth/login", json={"login": "alice", "password": "pass1234"}
    ).json()["data"]["pending_token"]

    r = client.post("/auth/mfa/webauthn/login-options", json={"pending_token": pending_token})

    assert r.status_code == 400
