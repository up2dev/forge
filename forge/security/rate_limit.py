"""
forge.security.rate_limit
==========================
Throttling en mémoire, à poser explicitement sur les routes sensibles
(login, vérification MFA, mot de passe oublié...) via `dependencies=`
de ControllerRouter.

Fenêtre fixe, par (clé, IP cliente) — volontairement simple pour cette
v1. À savoir avant prod :

  - Ne fonctionne pas correctement avec plusieurs workers/instances
    (chaque process a son propre compteur en mémoire) — un déploiement
    multi-worker doit basculer sur un backend partagé (Redis, INCR +
    EXPIRE) derrière la même interface `rate_limit(key, times, seconds)`.
  - Pas de nettoyage périodique du dict : sur un processus long-lived
    avec beaucoup d'IPs distinctes, la mémoire grossit. Acceptable en
    dev, à surveiller en prod avant un vrai backend externe.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request

_hits: dict[str, list[float]] = defaultdict(list)


def rate_limit(key: str, times: int, seconds: int):
    async def _check(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        bucket_key = f"{key}:{client_ip}"
        now = time.monotonic()

        window = [t for t in _hits[bucket_key] if now - t < seconds]

        if len(window) >= times:
            retry_after = int(seconds - (now - window[0])) + 1

            raise HTTPException(
                429,
                f"Too many requests — retry in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

        window.append(now)
        _hits[bucket_key] = window

    return _check
