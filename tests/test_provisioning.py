import asyncio
import csv

import pytest

from scripts.create_role import create_role
from scripts.create_user import create_user, create_users_from_csv
from scripts.grant_permission import grant
from scripts.sync_permissions import sync_permissions
from tests.helpers import auth


def test_create_role(client):
    role = asyncio.run(create_role("EDITOR", "Éditeur"))

    assert role.uid == "EDITOR"
    assert role.permissions == []


def test_create_role_with_permissions(client):
    asyncio.run(sync_permissions())

    role = asyncio.run(create_role("MODERATOR", "Modérateur", ["BOOKS_DELETE"]))

    assert [p.uid for p in role.permissions] == ["BOOKS_DELETE"]


def test_create_role_duplicate_rejected(client):
    asyncio.run(create_role("EDITOR", "Éditeur"))

    with pytest.raises(ValueError):
        asyncio.run(create_role("EDITOR", "Autre nom"))


def test_create_role_unknown_permission_rejected(client):
    with pytest.raises(ValueError):
        asyncio.run(create_role("EDITOR", "Éditeur", ["NOPE"]))


def test_create_user_without_role(client):
    user = asyncio.run(create_user("carol", "carol@example.test", "pass1234"))

    assert user.login == "carol"
    assert user.roles == []


def test_create_user_with_role(client):
    asyncio.run(create_role("EDITOR", "Éditeur"))

    user = asyncio.run(create_user("carol", "carol@example.test", "pass1234", "EDITOR"))

    assert [r.uid for r in user.roles] == ["EDITOR"]


def test_create_user_duplicate_login_or_email_rejected(client):
    asyncio.run(create_user("carol", "carol@example.test", "pass1234"))

    with pytest.raises(ValueError):
        asyncio.run(create_user("carol", "autre@example.test", "pass1234"))

    with pytest.raises(ValueError):
        asyncio.run(create_user("autrelogin", "carol@example.test", "pass1234"))


def test_create_user_unknown_role_rejected(client):
    with pytest.raises(ValueError):
        asyncio.run(create_user("carol", "carol@example.test", "pass1234", "GHOST"))


def test_created_user_can_actually_login(client):
    asyncio.run(create_user("carol", "carol@example.test", "un-mot-de-passe"))

    r = client.post("/auth/login", json={"login": "carol", "password": "un-mot-de-passe"})

    assert r.status_code == 200


def test_role_permission_actually_opens_the_route_end_to_end(client):
    """Bout en bout : create_role, create_user, grant, une vraie route."""
    asyncio.run(sync_permissions())
    asyncio.run(create_role("EDITOR", "Éditeur"))
    asyncio.run(create_user("carol", "carol@example.test", "pass1234", "EDITOR"))

    token = client.post(
        "/auth/login", json={"login": "carol", "password": "pass1234"}
    ).json()["data"]["token"]
    h = auth(token)
    author_id = client.post("/authors/", json={"name": "A"}, headers=h).json()["data"]["id"]
    book_id = client.post(
        "/books/", json={"title": "T", "year": 2000, "author_id": author_id}, headers=h
    ).json()["data"]["id"]

    assert client.delete(f"/books/{book_id}", headers=h).status_code == 403

    asyncio.run(grant("EDITOR", "BOOKS_DELETE"))

    assert client.delete(f"/books/{book_id}", headers=h).status_code == 200


def test_create_users_from_csv(client, tmp_path):
    asyncio.run(create_role("EDITOR", "Éditeur"))
    csv_path = tmp_path / "users.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["login", "email", "password", "role"])
        writer.writerow(["frank", "frank@example.test", "motdepasse123", "EDITOR"])
        writer.writerow(["grace", "grace@example.test", "", ""])

    results = asyncio.run(create_users_from_csv(str(csv_path)))

    assert [login for login, _ in results] == ["frank", "grace"]
    assert results[0][1] == "motdepasse123"  # mot de passe fourni, repris tel quel
    assert len(results[1][1]) > 8  # mot de passe généré pour grace

    r = client.post("/auth/login", json={"login": "frank", "password": "motdepasse123"})
    assert r.status_code == 200


def test_create_users_from_csv_rejects_duplicate_inside_file(client, tmp_path):
    csv_path = tmp_path / "users.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["login", "email", "password", "role"])
        writer.writerow(["frank", "frank@example.test", "x", ""])
        writer.writerow(["frank", "autre@example.test", "y", ""])

    with pytest.raises(ValueError):
        asyncio.run(create_users_from_csv(str(csv_path)))
