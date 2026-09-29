"""
forge.i18n
==========
Clé plate -> chaîne par locale (forge/i18n/locales/*.json). Clé
manquante : repli sur la locale par défaut, puis sur la clé elle-même
— jamais d'erreur.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from forge.config import get_settings

_LOCALES_DIR = Path(__file__).parent / "locales"


@lru_cache
def _load(locale: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{locale}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def trans(key: str, locale: str | None = None, **kwargs: str) -> str:
    locale = locale or get_settings().default_locale
    default = get_settings().default_locale

    text = _load(locale).get(key) or _load(default).get(key) or key

    return text.format(**kwargs) if kwargs else text
