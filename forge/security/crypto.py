"""
forge.security.crypto
=======================
Chiffrement symétrique (Fernet) pour les données sensibles stockées en
base — actuellement les secrets TOTP, en clair auparavant. Dérive la
clé de `FORGE_APP_KEY` (équivalent d'APP_KEY côté Laravel) — vide en
dev, un repli connu et documenté comme tel, jamais à utiliser pour de
vraies données.
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from forge.config import get_settings


class DecryptionError(Exception):
    pass


def _fernet() -> Fernet:
    key_material = get_settings().app_key or "forge-insecure-default-change-in-prod"
    # Fernet exige 32 octets urlsafe-base64 — dériver plutôt que
    # d'imposer un format de clé particulier à FORGE_APP_KEY.
    raw_key = hashlib.sha256(key_material.encode()).digest()

    return Fernet(base64.urlsafe_b64encode(raw_key))


def encrypt_secret(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError("FORGE_APP_KEY a changé, ou la valeur stockée est corrompue.") from exc
