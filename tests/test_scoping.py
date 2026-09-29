from tests.helpers import auth, create_role, create_user, login


def test_user_only_sees_own_notes(client):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")

    alice_h = auth(login(client, "alice", "pass1234"))
    bob_h = auth(login(client, "bob", "pass1234"))

    client.post("/notes/", json={"content": "secret alice"}, headers=alice_h)
    client.post("/notes/", json={"content": "secret bob"}, headers=bob_h)

    r = client.get("/notes/", headers=alice_h)

    assert [n["content"] for n in r.json()["data"]] == ["secret alice"]


def test_cannot_read_others_note(client):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")

    alice_h = auth(login(client, "alice", "pass1234"))
    bob_h = auth(login(client, "bob", "pass1234"))

    bob_note_id = client.post("/notes/", json={"content": "x"}, headers=bob_h).json()["data"]["id"]

    r = client.get(f"/notes/{bob_note_id}", headers=alice_h)

    assert r.status_code == 404  # jamais 403 — pas de fuite d'existence


def test_cannot_edit_or_delete_others_note(client):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")

    alice_h = auth(login(client, "alice", "pass1234"))
    bob_h = auth(login(client, "bob", "pass1234"))

    bob_note_id = client.post("/notes/", json={"content": "x"}, headers=bob_h).json()["data"]["id"]

    assert client.put(f"/notes/{bob_note_id}", json={"content": "hack"}, headers=alice_h).status_code == 404
    assert client.delete(f"/notes/{bob_note_id}", headers=alice_h).status_code == 404


def test_notes_all_bypasses_scoping_for_admin(client):
    create_user("alice", "pass1234")
    role_id = create_role("NOTEADMIN", ["NOTES_ADMIN"])
    create_user("admin", "pass1234", role_ids=[role_id])

    alice_h = auth(login(client, "alice", "pass1234"))
    admin_h = auth(login(client, "admin", "pass1234"))

    client.post("/notes/", json={"content": "secret alice"}, headers=alice_h)

    r = client.get("/notes/all", headers=admin_h)

    assert [n["content"] for n in r.json()["data"]] == ["secret alice"]


def test_admin_own_notes_list_stays_scoped(client):
    """Même avec la permission NOTES_ADMIN, GET /notes/ normal reste
    scopé — seul /notes/all bypass."""
    role_id = create_role("NOTEADMIN", ["NOTES_ADMIN"])
    create_user("admin", "pass1234", role_ids=[role_id])
    create_user("alice", "pass1234")

    admin_h = auth(login(client, "admin", "pass1234"))
    alice_h = auth(login(client, "alice", "pass1234"))

    client.post("/notes/", json={"content": "secret alice"}, headers=alice_h)

    r = client.get("/notes/", headers=admin_h)

    assert r.json()["data"] == []
