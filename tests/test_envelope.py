import io

from tests.helpers import auth, create_user, login


def test_success_response_has_standard_envelope(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    r = client.post("/authors/", json={"name": "Frank Herbert"}, headers=auth(token))

    assert r.status_code == 200
    body = r.json()
    assert body["meta"]["status"] == "success"
    assert body["meta"]["code"] == 200
    assert body["data"]["name"] == "Frank Herbert"
    assert isinstance(body["meta"]["duration_ms"], (int, float))
    assert "errors" not in body


def test_list_response_moves_pagination_to_meta(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    client.post("/authors/", json={"name": "A"}, headers=auth(token))

    r = client.get("/authors/", headers=auth(token))
    body = r.json()

    assert isinstance(body["data"], list)
    assert set(body["meta"]) >= {"total", "page", "limit", "total_pages", "previous_page", "next_page"}
    # les clés de pagination ne trainent pas en double dans data
    assert "total" not in body["data"][0] if body["data"] else True


def test_error_response_has_standard_envelope(client):
    r = client.get("/authors/")  # sans token -> 401

    assert r.status_code == 401
    body = r.json()
    assert body["meta"]["status"] == "error"
    assert body["meta"]["code"] == 401
    assert "detail" in body["errors"]
    assert "data" not in body


def test_duration_ms_present_on_every_response(client):
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")

    ok = client.get("/authors/", headers=auth(token))
    err = client.get("/authors/")

    assert "duration_ms" in ok.json()["meta"]
    assert "duration_ms" in err.json()["meta"]


def test_data_never_mixed_with_metadata(client):
    """data/errors ne doit contenir QUE la réponse réelle — jamais
    status/code/duration_ms/pagination mélangés dedans."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    client.post("/authors/", json={"name": "A"}, headers=auth(token))

    r = client.get("/authors/", headers=auth(token))
    body = r.json()

    meta_only_keys = {"status", "code", "duration_ms", "total", "page", "limit"}
    assert meta_only_keys.isdisjoint(body.keys())  # rien de tout ça à la racine
    for item in body["data"]:
        assert meta_only_keys.isdisjoint(item.keys())  # ni mélangé dans chaque élément


def test_file_download_is_never_wrapped(client):
    """Le contenu binaire d'un fichier ne doit jamais passer par
    l'enveloppe JSON — sinon on casserait le téléchargement."""
    create_user("alice", "pass1234")
    token = login(client, "alice", "pass1234")
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49"
        "4441547801010000feff0000000200016a3a5cc50000000049454e44ae426082"
    )
    file_id = client.post(
        "/files/", files={"file": ("x.png", io.BytesIO(png), "image/png")}, headers=auth(token)
    ).json()["data"]["id"]

    r = client.get(f"/files/{file_id}", headers=auth(token))

    assert r.headers["content-type"] == "image/png"
    assert r.content == png  # jamais transformé en JSON {"status":..., "data": ...}


def test_rate_limit_headers_survive_envelope(client):
    """Régression : reconstruire la réponse dans le middleware
    supprimait Retry-After (et tout autre en-tête custom)."""
    create_user("carol", "pass1234")

    for _ in range(5):
        client.post("/auth/login", json={"login": "carol", "password": "wrong"})

    r = client.post("/auth/login", json={"login": "carol", "password": "wrong"})

    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_openapi_json_is_never_wrapped(client):
    """Régression : Swagger/Redoc s'attendent à openapi/info/paths à la
    racine du document — l'enveloppe cachait tout ça sous data,
    rendant le document illisible ("version field missing")."""
    r = client.get("/openapi.json")

    assert r.status_code == 200
    body = r.json()
    assert "openapi" in body
    assert "data" not in body
    assert "meta" not in body


def test_health_check_is_public(client):
    r = client.get("/health")

    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ok"


def test_webauthn_test_page_is_public_html(client):
    r = client.get("/webauthn-test")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "navigator.credentials" in r.text


def test_favicon_served_as_svg(client):
    r = client.get("/favicon.svg")

    assert r.status_code == 200
    assert r.headers["content-type"] == "image/svg+xml"
    assert b"<svg" in r.content


def test_docs_and_redoc_use_custom_favicon(client):
    for path in ("/docs", "/redoc"):
        r = client.get(path)

        assert r.status_code == 200
        assert "/favicon.svg" in r.text
