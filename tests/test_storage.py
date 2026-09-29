import io

from tests.helpers import auth, create_user, login

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a4944415478"
    "9c6360000002000155bce9130000000049454e44ae426082"
)


def _upload(client, token, filename="test.png", content=PNG_1PX, content_type="image/png"):
    return client.post(
        "/files/",
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=auth(token),
    )


def _start(client, token, total_bytes, content_type="application/pdf", filename="big.bin"):
    return client.post(
        "/files/start",
        json={"filename": filename, "content_type": content_type, "total_bytes": total_bytes},
        headers=auth(token),
    )


def test_upload_and_view_inline(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = _upload(client, token)
    assert r.status_code == 200
    file_id = r.json()["data"]["id"]
    assert r.json()["data"]["completed_at"] is not None  # upload direct = complet immédiatement

    r = client.get(f"/files/{file_id}", headers=auth(token))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "inline" in r.headers["content-disposition"]
    assert r.content == PNG_1PX


def test_download_forces_attachment(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _upload(client, token).json()["data"]["id"]

    r = client.get(f"/files/{file_id}/download", headers=auth(token))

    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]


def test_list_only_shows_own_files(client):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")
    alice_token = login(client, "alice", "pass1234")
    bob_token = login(client, "bob", "pass1234")

    _upload(client, alice_token)

    assert len(client.get("/files/", headers=auth(alice_token)).json()["data"]) == 1
    assert client.get("/files/", headers=auth(bob_token)).json()["data"] == []


def test_cannot_access_others_file(client):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")
    alice_token = login(client, "alice", "pass1234")
    bob_token = login(client, "bob", "pass1234")

    file_id = _upload(client, alice_token).json()["data"]["id"]

    assert client.get(f"/files/{file_id}", headers=auth(bob_token)).status_code == 404
    assert client.get(f"/files/{file_id}/download", headers=auth(bob_token)).status_code == 404
    assert client.delete(f"/files/{file_id}", headers=auth(bob_token)).status_code == 404


def test_unsupported_type_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = _upload(client, token, "virus.exe", b"MZ...", "application/x-msdownload")

    assert r.status_code == 415


def test_pdf_upload_accepted(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    pdf = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>"

    r = _upload(client, token, "doc.pdf", pdf, "application/pdf")

    assert r.status_code == 200
    assert r.json()["data"]["content_type"] == "application/pdf"


def test_delete_removes_file(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _upload(client, token).json()["data"]["id"]

    assert client.delete(f"/files/{file_id}", headers=auth(token)).status_code == 200
    assert client.get(f"/files/{file_id}", headers=auth(token)).status_code == 404


def test_upload_requires_auth(client):
    r = client.post("/files/", files={"file": ("x.png", io.BytesIO(PNG_1PX), "image/png")})

    assert r.status_code == 401


# ------------------------------------------------------------------
# Upload par chunks — même StorageFile, même id, du début à la fin
# ------------------------------------------------------------------


def test_chunked_upload_reconstructs_exact_bytes_same_id(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    original = bytes(range(256)) * 200  # 51200 octets, motif vérifiable

    file_id = _start(client, token, len(original)).json()["data"]["id"]

    chunk_size = 7000  # volontairement pas un diviseur rond de la taille totale
    for i in range(0, len(original), chunk_size):
        r = client.put(f"/files/{file_id}", content=original[i : i + chunk_size], headers=auth(token))
        assert r.status_code == 200, r.text

    r = client.post(f"/files/{file_id}/complete", headers=auth(token))
    assert r.status_code == 200
    assert r.json()["data"]["id"] == file_id  # même id qu'au start — pas de bascule

    downloaded = client.get(f"/files/{file_id}/download", headers=auth(token)).content
    assert downloaded == original


def test_get_while_uploading_returns_json_status(client):
    """Un seul endpoint pour statut et contenu : GET /files/{id} rend
    du JSON tant que c'est en cours, le fichier une fois complet."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _start(client, token, 100).json()["data"]["id"]

    client.put(f"/files/{file_id}", content=b"x" * 40, headers=auth(token))

    r = client.get(f"/files/{file_id}", headers=auth(token))

    assert r.headers["content-type"].startswith("application/json")
    assert r.json()["data"]["received_bytes"] == 40
    assert r.json()["data"]["completed_at"] is None


def test_download_before_complete_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _start(client, token, 100).json()["data"]["id"]
    client.put(f"/files/{file_id}", content=b"x" * 40, headers=auth(token))

    r = client.get(f"/files/{file_id}/download", headers=auth(token))

    assert r.status_code == 404


def test_complete_before_full_upload_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _start(client, token, 100).json()["data"]["id"]

    client.put(f"/files/{file_id}", content=b"x" * 40, headers=auth(token))
    r = client.post(f"/files/{file_id}/complete", headers=auth(token))

    assert r.status_code == 400


def test_append_after_complete_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _start(client, token, 10).json()["data"]["id"]

    client.put(f"/files/{file_id}", content=b"x" * 10, headers=auth(token))
    client.post(f"/files/{file_id}/complete", headers=auth(token))

    r = client.put(f"/files/{file_id}", content=b"y", headers=auth(token))

    assert r.status_code == 404


def test_chunk_exceeding_declared_total_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    file_id = _start(client, token, 10).json()["data"]["id"]

    r = client.put(f"/files/{file_id}", content=b"x" * 50, headers=auth(token))

    assert r.status_code == 413


def test_chunk_size_is_configurable_and_enforced(client, monkeypatch):
    from forge import config

    config.get_settings.cache_clear()
    monkeypatch.setenv("FORGE_STORAGE_CHUNK_SIZE", "1000")
    config.get_settings.cache_clear()

    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = _start(client, token, 5000)
    assert r.json()["data"]["max_chunk_size"] == 1000
    file_id = r.json()["data"]["id"]

    assert client.put(f"/files/{file_id}", content=b"x" * 500, headers=auth(token)).status_code == 200
    assert client.put(f"/files/{file_id}", content=b"x" * 2000, headers=auth(token)).status_code == 413

    config.get_settings.cache_clear()


def test_start_unsupported_type_rejected(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = _start(client, token, 10, content_type="application/x-msdownload")

    assert r.status_code == 415


def test_chunked_upload_isolated_by_owner(client):
    create_user("alice", "pass1234")
    create_user("bob", "pass1234")
    alice_token = login(client, "alice", "pass1234")
    bob_token = login(client, "bob", "pass1234")

    file_id = _start(client, alice_token, 10).json()["data"]["id"]

    assert client.put(f"/files/{file_id}", content=b"x" * 10, headers=auth(bob_token)).status_code == 404
    assert client.get(f"/files/{file_id}", headers=auth(bob_token)).status_code == 404
