from __future__ import annotations

from pydantic import BaseModel


class MassDeleteBody(BaseModel):
    """
    Corps de DELETE /resource (mass_remove). `ids` liste précisément ce
    qui doit être supprimé ; `confirm=True` est la seule façon
    d'autoriser une suppression basée uniquement sur les filtres actifs
    de la requête (`?filters=...`), sans lister les ids un par un —
    l'équivalent volontairement plus explicite du massDelete() de Rivet
    qui, lui, supprime tout ce qui matche dès que `items` est vide,
    sans distinction entre "j'ai oublié le corps" et "je veux vraiment
    tout supprimer".
    """

    ids: list[int] | None = None
    confirm: bool = False
