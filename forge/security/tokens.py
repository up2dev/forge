"""
forge.security.tokens
======================
Token opaque à haute entropie, dont seul le hash SHA-256 est stocké
en base — jamais le token en clair.
"""
from __future__ import annotations

import hashlib
import secrets


def generate_token() -> str:
    # secrets.token_urlsafe: CSPRNG, ~256 bits d'entropie pour 40
    # octets source — largement au-dessus de ce qu'un brute-force
    # distribué peut raisonnablement viser.
    return secrets.token_urlsafe(40)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
