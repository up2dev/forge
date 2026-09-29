#!/usr/bin/env python3
"""
scripts/create_user.py
========================
Crée un utilisateur, avec un rôle optionnel (déjà existant — voir
scripts/create_role.py). Équivalent de `rightsmanagement
--action=create-user`/`create-users` côté Rivet.

Usage :
    docker compose exec api python scripts/create_user.py carol carol@exemple.fr --role EDITOR
    docker compose exec api python scripts/create_user.py carol carol@exemple.fr --password xxx
    docker compose exec api python scripts/create_user.py --file users.csv
    # ou : make create-user login=carol email=carol@exemple.fr role=EDITOR

Sans --password, un mot de passe aléatoire est généré et affiché une
seule fois — à transmettre à l'intéressé, jamais stocké en clair.

Le CSV (--file) attend les colonnes login,email,password,role (role
vide accepté) — une ligne par utilisateur, la première ligne étant
l'en-tête.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import secrets
import sys

from sqlalchemy import select

from forge.db import get_session
from forge.security.models import Role, User
from forge.security.passwords import hash_password


async def create_user(login: str, email: str, password: str, role_uid: str | None = None) -> User:
    async with get_session() as session:
        stmt = select(User).where((User.login == login) | (User.email == email))

        if (await session.execute(stmt)).scalar_one_or_none() is not None:
            raise ValueError(f"Login ou email déjà utilisé : '{login}' / '{email}'")

        roles = []

        if role_uid:
            role = (await session.execute(select(Role).where(Role.uid == role_uid))).scalar_one_or_none()

            if role is None:
                raise ValueError(f"Rôle inconnu : '{role_uid}' (scripts/create_role.py le crée)")

            roles.append(role)

        user = User(login=login, email=email, password_hash=hash_password(password), roles=roles)
        session.add(user)
        await session.commit()

        return user


async def create_users_from_csv(path: str) -> list[tuple[str, str]]:
    """[(login, mot de passe utilisé), ...] — pour affichage, jamais stocké."""
    results = []

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            password = row.get("password") or secrets.token_urlsafe(12)
            await create_user(row["login"], row["email"], password, row.get("role") or None)
            results.append((row["login"], password))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Crée un ou plusieurs utilisateurs")
    parser.add_argument("login", nargs="?")
    parser.add_argument("email", nargs="?")
    parser.add_argument("--password")
    parser.add_argument("--role")
    parser.add_argument("--file", help="CSV : login,email,password,role")
    args = parser.parse_args()

    if args.file:
        try:
            results = asyncio.run(create_users_from_csv(args.file))
        except (ValueError, FileNotFoundError, KeyError) as exc:
            sys.exit(f"{exc}")

        for login, password in results:
            print(f"{login} créé — mot de passe : {password}")

        print(f"\n{len(results)} utilisateur(s) créé(s).")

        return

    if not args.login or not args.email:
        sys.exit("login et email sont requis (ou --file pour un import CSV)")

    password = args.password or secrets.token_urlsafe(12)

    try:
        user = asyncio.run(create_user(args.login, args.email, password, args.role))
    except ValueError as exc:
        sys.exit(str(exc))

    print(f"Utilisateur {user.login} ({user.email}) créé.")

    if not args.password:
        print(f"Mot de passe généré : {password}  (à transmettre, jamais réaffiché)")

    if args.role:
        print(f"Rôle : {args.role}")


if __name__ == "__main__":
    main()
