"""
forge.security.passwords
=========================
bcrypt directement (pas passlib — son wrapper bcrypt n'est plus
maintenu et déclenche des warnings avec les versions récentes de la
lib bcrypt).
"""
from __future__ import annotations

import bcrypt


def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    """bcrypt.checkpw est à temps constant par construction (comparaison
    du hash recalculé, pas de la valeur en clair) — pas besoin d'un
    hmac.compare_digest en plus."""
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # hash malformé/vide — jamais une authentification valide.
        return False
