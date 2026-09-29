"""
forge.security.webauthn
=========================
Enveloppe autour de python-fido2 (`fido2.server.Fido2Server`) pour
l'inscription et la vérification de clés de sécurité (Yubikey en mode
FIDO2/WebAuthn — pas le mode OTP, déjà couvert par TOTP).

Une seule clé par utilisateur dans cette version (même limite que
TOTP/email — un seul MfaMethod par méthode). `state` (renvoyé par
register_begin/authenticate_begin) est du JSON, stocké tel quel le
temps de la cérémonie (MfaMethod.webauthn_challenge pour l'inscription,
MfaPendingToken.webauthn_challenge pour la connexion) — jamais après.
"""
from __future__ import annotations

import json

from fido2 import cbor
from fido2.cose import CoseKey
from fido2.server import Fido2Server
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (
    AttestedCredentialData,
    AuthenticatorData,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialRpEntity,
    PublicKeyCredentialType,
    PublicKeyCredentialUserEntity,
)

from forge.config import get_settings


class WebauthnError(Exception):
    """Cérémonie invalide — challenge expiré/absent, signature ne
    correspondant pas, origin incorrecte..."""


def _server() -> Fido2Server:
    settings = get_settings()

    return Fido2Server(
        PublicKeyCredentialRpEntity(id=settings.webauthn_rp_id, name=settings.webauthn_rp_name),
        verify_origin=lambda origin: origin == settings.webauthn_origin,
    )


def registration_options(user_id: int, login: str) -> tuple[dict, str]:
    """(options à renvoyer telles quelles au client, state à conserver
    jusqu'à verify_registration)."""
    options, state = _server().register_begin(
        PublicKeyCredentialUserEntity(id=str(user_id).encode(), name=login, display_name=login)
    )

    return dict(options.public_key), json.dumps(state)


def verify_registration(state_json: str, response: dict) -> tuple[str, str]:
    """Vérifie la réponse du navigateur contre le challenge attendu.
    Renvoie (credential_id, public_key) en base64url — des chaînes,
    prêtes à stocker telles quelles."""
    try:
        auth_data = _server().register_complete(json.loads(state_json), response)
    except Exception as exc:
        raise WebauthnError(str(exc)) from exc

    cred = auth_data.credential_data

    return websafe_encode(cred.credential_id), websafe_encode(cbor.encode(cred.public_key))


def login_options(credential_id_b64: str) -> tuple[dict, str]:
    """N'a besoin que de l'id de la clé pour la liste allowCredentials
    — la clé publique ne sert qu'à verify_login, une fois la réponse
    signée reçue."""
    descriptor = PublicKeyCredentialDescriptor(
        type=PublicKeyCredentialType.PUBLIC_KEY, id=websafe_decode(credential_id_b64)
    )
    options, state = _server().authenticate_begin([descriptor])

    return dict(options.public_key), json.dumps(state)


def verify_login(state_json: str, credential_id_b64: str, public_key_b64: str, response: dict) -> int:
    """Vérifie la réponse signée contre le challenge attendu et la clé
    publique stockée à l'inscription. Renvoie le nouveau compteur à
    sauvegarder (voir mfa_controller.py pour la détection de clonage :
    un compteur qui ne progresse pas d'une connexion à l'autre)."""
    cose_key = CoseKey.parse(cbor.decode(websafe_decode(public_key_b64)))
    credential = AttestedCredentialData.create(b"\x00" * 16, websafe_decode(credential_id_b64), cose_key)

    try:
        _server().authenticate_complete(json.loads(state_json), [credential], response)
    except Exception as exc:
        raise WebauthnError(str(exc)) from exc

    raw_auth_data = websafe_decode(response["response"]["authenticatorData"])

    return AuthenticatorData(raw_auth_data).counter
