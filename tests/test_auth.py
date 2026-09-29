from tests.helpers import auth, create_user, login


def test_login_success(client):
    create_user("alice", "pass1234")

    r = client.post("/auth/login", json={"login": "alice", "password": "pass1234"})

    assert r.status_code == 200
    assert "token" in r.json()["data"]


def test_login_wrong_password(client):
    create_user("alice", "pass1234")

    r = client.post("/auth/login", json={"login": "alice", "password": "wrong"})

    assert r.status_code == 401


def test_login_unknown_and_wrong_password_give_same_message(client):
    """Pas d'énumération de comptes via la réponse."""
    create_user("alice", "pass1234")

    r_unknown = client.post("/auth/login", json={"login": "ghost", "password": "x"})
    r_wrong = client.post("/auth/login", json={"login": "alice", "password": "wrong"})

    assert r_unknown.status_code == r_wrong.status_code == 401
    # pas .json() entier : "meta.duration_ms" diffère forcément d'un appel à l'autre
    assert r_unknown.json()["errors"] == r_wrong.json()["errors"]


def test_login_inactive_user(client):
    create_user("bob", "pass1234", is_active=False)

    r = client.post("/auth/login", json={"login": "bob", "password": "pass1234"})

    assert r.status_code == 403


def test_login_rate_limited_after_five_attempts(client):
    create_user("carol", "pass1234")

    for _ in range(5):
        client.post("/auth/login", json={"login": "carol", "password": "wrong"})

    r = client.post("/auth/login", json={"login": "carol", "password": "wrong"})

    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_protected_route_requires_token(client):
    r = client.get("/authors/")

    assert r.status_code == 401


def test_me_returns_current_user(client):
    create_user("dave", "pass1234")
    token = login(client, "dave", "pass1234")

    r = client.get("/auth/me", headers=auth(token))

    assert r.status_code == 200
    assert r.json()["data"]["login"] == "dave"


def test_logout_revokes_token(client):
    create_user("erin", "pass1234")
    token = login(client, "erin", "pass1234")

    assert client.post("/auth/logout", headers=auth(token)).status_code == 200
    assert client.get("/auth/me", headers=auth(token)).status_code == 401


def test_login_localized_via_accept_language(client):
    create_user("alice", "pass1234")

    r_fr = client.post(
        "/auth/login",
        json={"login": "alice", "password": "wrong"},
        headers={"Accept-Language": "fr-FR"},
    )
    r_en = client.post(
        "/auth/login",
        json={"login": "alice", "password": "wrong"},
        headers={"Accept-Language": "en-US"},
    )

    assert r_fr.json()["errors"]["detail"] == "Identifiants invalides"
    assert r_en.json()["errors"]["detail"] == "Invalid credentials"
