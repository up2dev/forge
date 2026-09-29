from tests.helpers import auth, create_role, create_user, login


def _setup(client):
    create_user("u", "pass1234")
    token = login(client, "u", "pass1234")
    h = auth(token)
    author_id = client.post("/authors/", json={"name": "Frank Herbert"}, headers=h).json()["data"]["id"]

    return h, author_id


def _setup_with_delete_permission(client):
    role_id = create_role("BOOKDEL", ["BOOKS_DELETE"])
    create_user("deleter", "pass1234", role_ids=[role_id])
    token = login(client, "deleter", "pass1234")
    h = auth(token)
    author_id = client.post("/authors/", json={"name": "Frank Herbert"}, headers=h).json()["data"]["id"]

    return h, author_id


def test_create_and_list(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)

    r = client.get("/books/", headers=h)

    assert r.status_code == 200
    assert r.json()["meta"]["total"] == 1


def test_filter_allowlisted_key(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=title:lk(dune)", headers=h)

    assert r.status_code == 200
    assert [b["title"] for b in r.json()["data"]] == ["Dune"]


def test_filter_and_within_group(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Dune", "year": 1966, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=title:eq(Dune),year:eq(1965)", headers=h)

    assert [b["year"] for b in r.json()["data"]] == [1965]


def test_filter_or_between_groups(client):
    """Régression : |or| était parsé mais jamais appliqué en OU réel
    dans la requête SQL — tout finissait en ET (0 résultat)."""
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Neuromancer", "year": 1984, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=title:eq(Dune)|or|year:eq(1951)", headers=h)

    assert sorted(b["title"] for b in r.json()["data"]) == ["Dune", "Foundation"]


def test_filter_in_operator_with_internal_commas(client):
    """Régression : la virgule de in(1,2,3) était confondue avec le
    séparateur entre conditions — plantait en 500."""
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=year:in(1965,1984)", headers=h)

    assert r.status_code == 200
    assert [b["title"] for b in r.json()["data"]] == ["Dune"]


def test_filter_malformed_syntax_returns_clean_400(client):
    """Régression : une erreur de parsing levée dans le middleware
    ne remontait jamais au handler global — 500 brut au lieu d'un 400."""
    h, _ = _setup(client)

    r = client.get("/books/?filters=year:n", headers=h)

    assert r.status_code == 400


def test_filter_unknown_key_rejected(client):
    """Une clé de filtre non déclarée est rejetée — même discipline
    que l'allowlist des includes."""
    h, _ = _setup(client)

    r = client.get("/books/?filters=not_a_field:eq(x)", headers=h)

    assert r.status_code == 400


def test_with_unknown_relation_is_ignored_not_rejected(client):
    """?with= non allowlisté: ignoré silencieusement, jamais une 500
    ni une 400 — différent des filtres, volontairement."""
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)

    r = client.get("/books/?with=not_a_relation", headers=h)

    assert r.status_code == 200


def test_with_allowlisted_relation_is_included(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)

    r = client.get("/books/?with=author", headers=h)

    assert r.json()["data"][0]["author"]["name"] == "Frank Herbert"


def test_with_absent_leaves_relation_null_no_lazy_load_crash(client):
    """Accéder à une relation non chargée plante en async SQLAlchemy
    (DetachedInstanceError) — regression test."""
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)

    r = client.get("/books/", headers=h)

    assert r.status_code == 200
    assert r.json()["data"][0]["author"] is None


def test_sort(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.get("/books/?sort=year.desc", headers=h)

    assert [b["title"] for b in r.json()["data"]] == ["Dune", "Foundation"]


def test_update_partial(client):
    h, author_id = _setup(client)
    book_id = client.post(
        "/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h
    ).json()["data"]["id"]

    r = client.put(f"/books/{book_id}", json={"year": 1966}, headers=h)

    assert r.status_code == 200
    assert r.json()["data"]["year"] == 1966
    assert r.json()["data"]["title"] == "Dune"  # inchangé


def test_add_validates_typed_schema(client):
    """BookController est typé (BookCreate) — titre vide rejeté en 422."""
    h, author_id = _setup(client)

    r = client.post("/books/", json={"title": "", "year": 1965, "author_id": author_id}, headers=h)

    assert r.status_code == 422


def test_mass_delete_refuses_without_ids_or_confirm(client):
    """mass_delete sans items ne supprime plus toute la table."""
    h, author_id = _setup_with_delete_permission(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)

    r = client.request("DELETE", "/books/", json={}, headers=h)

    assert r.status_code == 400

    still_there = client.get("/books/", headers=h)
    assert still_there.json()["meta"]["total"] == 1


def test_mass_delete_refuses_confirm_without_filter(client):
    h, author_id = _setup_with_delete_permission(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)

    r = client.request("DELETE", "/books/", json={"confirm": True}, headers=h)

    assert r.status_code == 400


def test_mass_delete_with_confirm_and_filter_works(client):
    h, author_id = _setup_with_delete_permission(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.request(
        "DELETE", "/books/?filters=title:lk(dune)", json={"confirm": True}, headers=h
    )

    assert r.status_code == 200
    assert r.json()["data"]["deleted_count"] == 1

    remaining = client.get("/books/", headers=h)
    assert remaining.json()["meta"]["total"] == 1


def test_mass_delete_with_explicit_ids_works(client):
    h, author_id = _setup_with_delete_permission(client)
    book_id = client.post(
        "/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h
    ).json()["data"]["id"]

    r = client.request("DELETE", "/books/", json={"ids": [book_id]}, headers=h)

    assert r.status_code == 200
    assert r.json()["data"]["deleted_count"] == 1


# ------------------------------------------------------- pagination metadata


def test_pagination_metadata_first_page(client):
    h, author_id = _setup(client)

    for i in range(25):
        client.post(
            "/books/", json={"title": f"Book {i}", "year": 2000 + i, "author_id": author_id}, headers=h
        )

    r = client.get("/books/?limit=10&page=1", headers=h)
    d = r.json()

    assert d["meta"]["total"] == 25
    assert d["meta"]["page"] == 1
    assert d["meta"]["limit"] == 10
    assert d["meta"]["total_pages"] == 3
    assert d["meta"]["previous_page"] is None
    assert d["meta"]["next_page"] == 2
    assert len(d["data"]) == 10


def test_pagination_metadata_last_page(client):
    h, author_id = _setup(client)

    for i in range(25):
        client.post(
            "/books/", json={"title": f"Book {i}", "year": 2000 + i, "author_id": author_id}, headers=h
        )

    r = client.get("/books/?limit=10&page=3", headers=h)
    d = r.json()

    assert d["meta"]["total_pages"] == 3
    assert d["meta"]["previous_page"] == 2
    assert d["meta"]["next_page"] is None
    assert len(d["data"]) == 5


def test_pagination_metadata_generic_controller(client):
    """Même métadonnées sur un contrôleur générique (ListResult brut),
    pas seulement sur BookList (typé)."""
    h, _ = _setup(client)

    r = client.get("/authors/?limit=5", headers=h)
    d = r.json()

    assert "data" in d
    assert set(d["meta"]) >= {"total", "page", "limit", "total_pages", "previous_page", "next_page"}
    assert d["meta"]["total_pages"] == 1
    assert d["meta"]["previous_page"] is None
    assert d["meta"]["next_page"] is None


def test_pagination_default_limit_is_20(client):
    h, author_id = _setup(client)

    for i in range(25):
        client.post(
            "/books/", json={"title": f"Book {i}", "year": 2000 + i, "author_id": author_id}, headers=h
        )

    r = client.get("/books/", headers=h)
    d = r.json()

    assert d["meta"]["limit"] == 20
    assert d["meta"]["total_pages"] == 2
    assert d["meta"]["next_page"] == 2
    assert len(d["data"]) == 20


# ------------------------------------------------- contraintes de la base


def test_missing_required_field_is_422_not_500(client):
    """Régression : un champ obligatoire absent d'un contrôleur sans
    schéma Pydantic finissait en 500 (IntegrityError NOT NULL)."""
    h, _ = _setup(client)

    r = client.post("/authors/", json={}, headers=h)

    assert r.status_code == 422
    assert r.json()["errors"]["detail"] == "Champ obligatoire manquant : name"


def test_integrity_error_messages_for_both_engines():
    """Classement des messages SQLite ET Postgres (celui-ci ne tourne pas
    en test) : champ manquant -> 422 avec son nom, le reste -> 409."""
    from forge.errors import describe_integrity_error

    class Fake:
        def __init__(self, message):
            self.orig = message

    assert describe_integrity_error(Fake("NOT NULL constraint failed: authors.name")) == (
        422, "Champ obligatoire manquant : name",
    )
    assert describe_integrity_error(Fake('null value in column "name" of relation "authors"'))[0] == 422
    assert describe_integrity_error(Fake("UNIQUE constraint failed: users.login"))[0] == 409
    assert describe_integrity_error(Fake('duplicate key value violates unique constraint "x"'))[0] == 409


# ------------------------------------------------- typage des filtres


def test_filter_eq_on_integer_column_coerces_value(client):
    """Régression Postgres : year (Integer) comparé à "1965" (string
    brute de la query string) plante sur Postgres, silencieux sur
    SQLite. Trouvé en testant pour de vrai contre un vrai Postgres."""
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=year:eq(1965)", headers=h)

    assert r.status_code == 200
    assert [b["title"] for b in r.json()["data"]] == ["Dune"]


def test_filter_in_on_integer_column_coerces_each_value(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=year:in(1965,1984)", headers=h)

    assert [b["title"] for b in r.json()["data"]] == ["Dune"]


def test_filter_invalid_integer_value_is_400_not_500(client):
    h, _ = _setup(client)

    r = client.get("/books/?filters=year:eq(pas-un-nombre)", headers=h)

    assert r.status_code == 400


def test_filter_gte_on_integer_column(client):
    h, author_id = _setup(client)
    client.post("/books/", json={"title": "Dune", "year": 1965, "author_id": author_id}, headers=h)
    client.post("/books/", json={"title": "Foundation", "year": 1951, "author_id": author_id}, headers=h)

    r = client.get("/books/?filters=year:gte(1960)", headers=h)

    assert [b["title"] for b in r.json()["data"]] == ["Dune"]


def test_filter_unknown_operator_returns_400(client):
    """Régression : le fallback "opérateur inconnu" s'était retrouvé
    égaré dans une autre méthode (code mort, faisait tomber sur un
    None silencieux au lieu d'un 400)."""
    h, _ = _setup(client)

    r = client.get("/books/?filters=year:zzz(1965)", headers=h)

    assert r.status_code == 400
