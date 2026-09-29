"""
forge.errors
============
Transforme les exceptions internes en réponses HTTP propres plutôt
que de les laisser remonter en 500 avec la stack trace brute — géré
une fois pour toutes ici, pas au cas par cas dans chaque Controller.
"""
from __future__ import annotations

import logging
import re

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from forge.repositories.base import InvalidFilterError

logger = logging.getLogger("forge.errors")

# Nom de la colonne NULL refusée, selon le moteur :
#   SQLite   : "NOT NULL constraint failed: categories.label"
#   Postgres : 'null value in column "label" of relation "categories" violates not-null constraint'
_NOT_NULL = re.compile(r'NOT NULL constraint failed: \w+\.(\w+)|null value in column "(\w+)"')


def describe_integrity_error(exc: IntegrityError) -> tuple[int, str]:
    """(code HTTP, message) pour une contrainte de base violée — sans
    jamais exposer le SQL ni les valeurs. Un champ obligatoire manquant
    est une erreur du client (422, avec le nom du champ) ; le reste
    (valeur déjà utilisée, référence inexistante) est un conflit (409)."""
    match = _NOT_NULL.search(str(exc.orig))

    if match:
        return 422, f"Champ obligatoire manquant : {match.group(1) or match.group(2)}"

    return 409, "Conflit avec une contrainte de la base (valeur déjà utilisée ou référence inexistante)"


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(InvalidFilterError)
    async def _invalid_filter(request: Request, exc: InvalidFilterError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _value_error(request: Request, exc: ValueError):
        # mass_delete() refuse ici — tout ValueError levé depuis un
        # Repository est, par convention, une erreur de requête
        # client (400), pas un bug serveur.
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(IntegrityError)
    async def _integrity_error(request: Request, exc: IntegrityError):
        # Un contrôleur générique (sans schéma Pydantic) laisse passer un
        # champ manquant jusqu'à la base : plutôt qu'un 500 opaque, une
        # réponse que le client peut corriger.
        status, message = describe_integrity_error(exc)
        logger.warning("Contrainte violée sur %s %s : %s", request.method, request.url.path, exc.orig)

        return JSONResponse(status_code=status, content={"detail": message})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Stack trace complète dans le fichier de log (storage/logs/forge.log)
        # pour déboguer — jamais dans la réponse HTTP.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)

        return JSONResponse(status_code=500, content={"detail": "Internal server error"})
