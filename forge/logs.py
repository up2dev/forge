"""
forge.logs
==========
setup_logging() une fois au démarrage (voir example_app/main.py),
ensuite logging.getLogger("forge") partout ailleurs — pas d'API
maison à apprendre.

FORGE_LOG_BACKEND choisit la destination : "file" (défaut,
storage/logs/forge.log, rotatif) ou "mongo" (une collection). La
console reste toujours active en plus, quel que soit le backend.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from forge.config import get_settings

_configured = False


class MongoLogHandler(logging.Handler):
    """Un document par log ligne. Le client Mongo est synchrone
    (pymongo) — un logger l'est presque toujours, même dans une app
    async ; si Mongo est injoignable, le log est juste perdu
    (handleError), l'app ne plante jamais pour ça."""

    def __init__(self, url: str, db_name: str, collection_name: str) -> None:
        super().__init__()

        import pymongo

        self._collection = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000)[db_name][
            collection_name
        ]

    def emit(self, record: logging.LogRecord) -> None:
        try:
            doc = {
                "timestamp": datetime.now(timezone.utc),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }

            if record.exc_info:
                doc["traceback"] = self.format(record)

            self._collection.insert_one(doc)
        except Exception:
            self.handleError(record)


def _build_durable_handler(settings) -> logging.Handler:
    if settings.log_backend == "mongo":
        return MongoLogHandler(settings.log_mongo_url, settings.log_mongo_db, settings.log_mongo_collection)

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "forge.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    return handler


def setup_logging() -> None:
    global _configured

    if _configured:
        return

    settings = get_settings()

    root = logging.getLogger("forge")
    root.setLevel(settings.log_level)
    root.addHandler(_build_durable_handler(settings))
    root.addHandler(logging.StreamHandler())  # console, toujours en plus

    _configured = True
