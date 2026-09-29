"""
forge.middleware.envelope
============================
Enveloppe toutes les réponses JSON dans un format standard, façon
Rivet :

    succès : {"data": ..., "meta": {"status": "success", "code": 200, ...}}
    erreur : {"errors": ..., "meta": {"status": "error", "code": 400, ...}}

`data`/`errors` ne contient QUE la réponse réelle — rien d'autre.
Toute métadonnée (statut, code HTTP, temps de traitement, et pour un
listing : total/page/limit/total_pages/previous_page/next_page) va
dans `meta`, jamais mélangée à la réponse elle-même.

Ne touche jamais un contenu non-JSON (fichiers en streaming/téléchargement,
via FileResponse) — repéré par le Content-Type de la réponse, testé
avant de lire quoi que ce soit du corps. Ne touche pas non plus
`/openapi.json` — Swagger/Redoc s'attendent à trouver `openapi`/`info`/
`paths` à la racine du document, pas sous `data` (sinon "version field
missing", le lecteur ne reconnaît plus le document du tout).
"""
from __future__ import annotations

import json
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# Ces clés, si présentes dans le corps d'origine, partent dans `meta`
# plutôt que dans `data` — c'est la forme que renvoie ListResult (voir
# forge/repositories/base.py).
_PAGINATION_KEYS = ("total", "page", "limit", "total_pages", "previous_page", "next_page")

# Chemins jamais enveloppés, même en JSON — des documents dans un
# format imposé par un standard externe, pas une réponse API. Mettre à
# jour si openapi_url= est personnalisé dans FastAPI(...).
_EXCLUDED_PATHS = {"/openapi.json"}


class ResponseEnvelopeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)

        if request.url.path in _EXCLUDED_PATHS:
            return response

        content_type = response.headers.get("content-type", "")

        if not content_type.startswith("application/json"):
            # Fichier en streaming (stream/download) — jamais enveloppé,
            # jamais lu en mémoire ici.
            return response

        body = b""

        async for chunk in response.body_iterator:
            body += chunk

        try:
            original = json.loads(body) if body else None
        except json.JSONDecodeError:
            original = None

        is_error = response.status_code >= 400
        meta: dict = {
            "status": "error" if is_error else "success",
            "code": response.status_code,
            "duration_ms": duration_ms,
        }
        payload = original

        if isinstance(original, dict):
            payload = dict(original)

            for key in _PAGINATION_KEYS:
                if key in payload:
                    meta[key] = payload.pop(key)

            if list(payload.keys()) == ["items"]:
                payload = payload["items"]

        envelope = {"errors" if is_error else "data": payload, "meta": meta}

        # Le corps change de taille -> content-length doit être recalculé,
        # pas recopié. Le reste (Retry-After, en-têtes custom...) doit
        # survivre à la reconstruction de la réponse.
        headers = {
            k: v for k, v in response.headers.items() if k.lower() not in ("content-length", "content-type")
        }

        return JSONResponse(status_code=response.status_code, content=envelope, headers=headers)
