import pytest

from tests.helpers import auth, create_role, create_user, login


def test_route_without_authorization_decision_refuses_to_register():
    """Impossible de déclarer une route sans permission=/public=/
    authenticated_only= — l'app plante au démarrage plutôt que de
    laisser une route ouverte en silence."""
    from forge.routing import ControllerRouter, RouteAuthorizationError

    class DummyController:
        async def list(self):
            return []

    router = ControllerRouter(DummyController, prefix="/dummy")

    with pytest.raises(RouteAuthorizationError):
        router.get("/", "list")


def test_route_with_both_permission_and_public_refuses():
    from forge.routing import ControllerRouter, RouteAuthorizationError

    class DummyController:
        async def list(self):
            return []

    router = ControllerRouter(DummyController, prefix="/dummy")

    with pytest.raises(RouteAuthorizationError):
        router.get("/", "list", permission="X", public=True)


def test_permission_denied_without_role(client):
    create_user("noperm", "pass1234")
    token = login(client, "noperm", "pass1234")

    author_id = client.post("/authors/", json={"name": "X"}, headers=auth(token)).json()["data"]["id"]
    book_id = client.post(
        "/books/", json={"title": "Y", "year": 2000, "author_id": author_id}, headers=auth(token)
    ).json()["data"]["id"]

    r = client.delete(f"/books/{book_id}", headers=auth(token))

    assert r.status_code == 403


def test_permission_granted_with_role(client):
    role_id = create_role("BOOKDEL", ["BOOKS_DELETE"])
    create_user("hasperm", "pass1234", role_ids=[role_id])
    token = login(client, "hasperm", "pass1234")

    author_id = client.post("/authors/", json={"name": "X"}, headers=auth(token)).json()["data"]["id"]
    book_id = client.post(
        "/books/", json={"title": "Y", "year": 2000, "author_id": author_id}, headers=auth(token)
    ).json()["data"]["id"]

    r = client.delete(f"/books/{book_id}", headers=auth(token))

    assert r.status_code == 200


def test_notes_all_requires_admin_permission(client):
    create_user("plain", "pass1234")
    token = login(client, "plain", "pass1234")

    r = client.get("/notes/all", headers=auth(token))

    assert r.status_code == 403


def test_notes_all_works_with_admin_permission(client):
    role_id = create_role("NOTEADMIN", ["NOTES_ADMIN"])
    create_user("admin2", "pass1234", role_ids=[role_id])
    token = login(client, "admin2", "pass1234")

    r = client.get("/notes/all", headers=auth(token))

    assert r.status_code == 200
