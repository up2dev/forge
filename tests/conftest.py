import asyncio
import os
import shutil
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
# Les tests enchaînent des asyncio.run() indépendants (une boucle
# d'événements par appel) — sans pool, chaque connexion reste dans sa
# boucle, jamais réutilisée dans une autre (voir forge/db.py).
os.environ.setdefault("FORGE_DB_POOL", "null")
_TEST_STORAGE_DIR = tempfile.mkdtemp(prefix="forge-test-storage-")
os.environ.setdefault("FORGE_STORAGE_DIR", _TEST_STORAGE_DIR)

import pytest
from fastapi.testclient import TestClient

from forge.db import engine
from forge.models.base import Base

# Import déclenche l'enregistrement de tous les modèles (Book, Author,
# Note, User, MfaMethod...) sur Base.metadata avant le premier test.
from example_app.main import app as _app


def _cleanup_storage():
    shutil.rmtree(_TEST_STORAGE_DIR, ignore_errors=True)
    os.makedirs(_TEST_STORAGE_DIR, exist_ok=True)


@pytest.fixture(autouse=True)
def _fresh_db():
    async def _reset():
        # create_all, pas les migrations Alembic : les tests veulent un
        # schéma déterministe à chaque run, pas rejouer l'historique de
        # migrations. Les deux mécanismes sont volontairement séparés —
        # Alembic gère l'évolution de la vraie base (voir alembic/),
        # create_all reste légitime pour une base de test jetable.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_reset())
    _cleanup_storage()  # dossier dédié (FORGE_STORAGE_DIR ci-dessus), jamais storage/ du projet

    # Le rate-limiter est un dict en mémoire au niveau module — sans
    # ce reset, les tests se pollueraient les uns les autres (même
    # IP "testclient" pour toutes les requêtes TestClient).
    import forge.security.rate_limit as rate_limit_module

    rate_limit_module._hits.clear()

    # Un test qui monkeypatch une variable d'env (FORGE_MFA_FORCE_ENROLLMENT,
    # FORGE_STORAGE_CHUNK_SIZE...) et échoue avant son propre cache_clear()
    # final laissait la config polluée pour tous les tests suivants — un
    # cache_clear() systématique avant ET après élimine cette classe de
    # bugs entièrement, plutôt que de compter sur chaque test pour le faire
    # correctement (même en cas d'échec).
    from forge.config import get_settings

    get_settings.cache_clear()

    yield

    get_settings.cache_clear()


@pytest.fixture
def client():
    with TestClient(_app) as c:
        yield c


@pytest.fixture
def sent_emails(monkeypatch):
    """Intercepte l'envoi SMTP — les tests ne dépendent pas d'un
    serveur mail (Mailpit) en marche."""
    captured = []

    async def fake_send(message, **kwargs):
        captured.append(message)

    import forge.mail.base as mail_base

    monkeypatch.setattr(mail_base.aiosmtplib, "send", fake_send)

    return captured
