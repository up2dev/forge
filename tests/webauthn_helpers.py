"""
tests/webauthn_helpers.py
===========================
Un vrai authentificateur WebAuthn logiciel (clé EC réelle, signatures
réelles) — permet de tester le cycle inscription/connexion de bout en
bout, sans navigateur ni Yubikey physique. Utilise python-fido2 côté
vérification (le même que forge/security/webauthn.py) et `cryptography`
côté génération/signature.
"""
from __future__ import annotations

import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.hashes import SHA256
from fido2 import cbor
from fido2.cose import ES256
from fido2.utils import websafe_encode
from fido2.webauthn import AttestedCredentialData, AuthenticatorData


class VirtualAuthenticator:
    def __init__(self):
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self._counter = 0

    def register(self, options: dict, origin: str) -> dict:
        rp_id = options["rp"]["id"]
        challenge_b64 = options["challenge"]

        cose_key = ES256.from_cryptography_key(self.private_key.public_key())
        cred_data = AttestedCredentialData.create(b"\x00" * 16, self.credential_id, cose_key)
        auth_data = bytes(
            AuthenticatorData.create(
                hashlib.sha256(rp_id.encode()).digest(),
                AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV | AuthenticatorData.FLAG.AT,
                self._counter,
                cred_data,
            )
        )
        client_data = json.dumps(
            {"type": "webauthn.create", "challenge": challenge_b64, "origin": origin}
        ).encode()
        attestation_object = cbor.encode({"fmt": "none", "attStmt": {}, "authData": auth_data})

        return {
            "id": websafe_encode(self.credential_id),
            "rawId": websafe_encode(self.credential_id),
            "response": {
                "clientDataJSON": websafe_encode(client_data),
                "attestationObject": websafe_encode(attestation_object),
            },
            "type": "public-key",
        }

    def authenticate(self, options: dict, origin: str, *, bump_counter: bool = True) -> dict:
        rp_id = options["rpId"]
        challenge_b64 = options["challenge"]

        if bump_counter:
            self._counter += 1

        auth_data = bytes(
            AuthenticatorData.create(
                hashlib.sha256(rp_id.encode()).digest(), AuthenticatorData.FLAG.UP, self._counter
            )
        )
        client_data = json.dumps(
            {"type": "webauthn.get", "challenge": challenge_b64, "origin": origin}
        ).encode()
        signature = self.private_key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(SHA256())
        )

        return {
            "id": websafe_encode(self.credential_id),
            "rawId": websafe_encode(self.credential_id),
            "response": {
                "clientDataJSON": websafe_encode(client_data),
                "authenticatorData": websafe_encode(auth_data),
                "signature": websafe_encode(signature),
            },
            "type": "public-key",
        }
