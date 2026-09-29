"""
scripts/seed.py
================
Crée l'utilisateur admin avec toutes les permissions déclarées dans
les routes (scan via sync_permissions, voir scripts/sync_permissions.py),
si nécessaire — idempotent, rejouable sans risque.

Usage :
    docker compose exec api python scripts/seed.py
    # ou : make seed
"""
import asyncio
from pathlib import Path

from sqlalchemy import select

from forge.config import get_settings
from forge.db import get_session
from forge.i18n import trans
from forge.mail.base import BaseMail
from forge.security.models import Permission, Role, User
from forge.security.passwords import hash_password

from scripts.sync_permissions import sync_permissions

# FORGE_ADMIN_LOGIN / FORGE_ADMIN_EMAIL / FORGE_ADMIN_PASSWORD (voir
# forge/config.py) — les défauts (admin / changeme) ne valent qu'en dev.
_settings = get_settings()
ADMIN_LOGIN = _settings.admin_login
ADMIN_EMAIL = _settings.admin_email
ADMIN_PASSWORD = _settings.admin_password


def run_migrations() -> None:
    """alembic upgrade head, en synchrone, AVANT d'entrer dans la boucle
    asyncio de main() — command.upgrade() lance son propre asyncio.run()
    en interne (voir alembic/env.py), l'appeler depuis une coroutine
    déjà en cours lèverait "cannot be called from a running event loop"."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).parent.parent / "alembic.ini"))
    command.upgrade(cfg, "head")


async def main() -> None:
    async with get_session() as session:
        existing = (
            await session.execute(select(User).where(User.login == ADMIN_LOGIN))
        ).scalar_one_or_none()

        if existing is not None:
            print(f"L'utilisateur '{ADMIN_LOGIN}' existe déjà (id={existing.id}) — rien à faire.")
            return

    created, _ = await sync_permissions()

    if created:
        print(f"Permissions créées : {', '.join(created)}")

    async with get_session() as session:
        all_permissions = (await session.execute(select(Permission))).scalars().all()

        admin_role = Role(uid="ADMIN", name="Administrator")
        admin_role.permissions = list(all_permissions)
        session.add(admin_role)
        await session.flush()

        admin = User(
            login=ADMIN_LOGIN,
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            is_active=True,
        )
        admin.roles = [admin_role]
        session.add(admin)

        await session.commit()

    if ADMIN_PASSWORD == "changeme":
        print(f"Utilisateur '{ADMIN_LOGIN}' créé / mot de passe 'changeme', rôle ADMIN.")
        print("Mot de passe par défaut : à changer avant quoi que ce soit ressemblant à de la prod.")
    else:
        # Jamais un vrai mot de passe dans les logs.
        print(f"Utilisateur '{ADMIN_LOGIN}' créé (mot de passe : FORGE_ADMIN_PASSWORD), rôle ADMIN.")

    await _send_welcome_email(admin)


async def _send_welcome_email(user: User) -> None:
    mail = BaseMail(
        template="welcome.html",
        context={
            "greeting": trans("mail.welcome.greeting", "fr", name=user.login),
            "body": trans("mail.welcome.body", "fr"),
        },
        to=[user.email],
        subject=trans("mail.welcome.subject", "fr", app_name="Forge"),
    )

    try:
        await mail.send()
        print(f"Email de bienvenue envoyé à {user.email}.")
    except Exception as exc:
        # L'admin est déjà créé — un SMTP injoignable ne doit pas faire
        # échouer tout le seed. Voir http://localhost:8025 (Mailpit) en Docker.
        print(f"Email de bienvenue non envoyé ({exc}) — SMTP injoignable ?")


if __name__ == "__main__":
    run_migrations()
    asyncio.run(main())
