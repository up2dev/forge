# DSL de filtres, tri, includes et pagination

S'applique à toute ressource générique (`BaseRepository`) — `?filters=`,
`?sort=`, `?with=`, `?page=`, `?limit=`, `?distinct=`. Rien de tout ça
ne fonctionne sur un champ non déclaré : chaque Repository choisit
explicitement ce qui est filtrable/triable (`filters`) et ce qui est
chargeable (`includes`).

## `?filters=`

Syntaxe : `champ:opérateur(valeur)`, plusieurs conditions séparées par
une virgule (ET), plusieurs groupes séparés par `|or|` (OU) :

```
?filters=title:lk(dune)
?filters=year:gte(1960),year:lte(1970)
?filters=title:eq(Dune)|or|year:eq(1951)
?filters=author_id:eq(2),year:gte(1980)|or|title:eq(Dune)
```

Le dernier exemple : `(author_id=2 ET year>=1980) OU title='Dune'` —
chaque groupe (séparé par `|or|`) est un ET de ses propres conditions,
les groupes entre eux sont des OU. Pas d'imbrication plus profonde
(pas de OU à l'intérieur d'un ET à l'intérieur d'un OU) — si ce besoin
apparaît, ce sera un DSL à part plutôt que de complexifier celui-ci.

### Opérateurs

| Opérateur | SQL équivalent | Exemple |
|---|---|---|
| `eq` | `=` | `status:eq(active)` |
| `neq` | `!=` | `status:neq(deleted)` |
| `gt` | `>` | `year:gt(1960)` |
| `gte` | `>=` | `year:gte(1960)` |
| `lt` | `<` | `year:lt(2000)` |
| `lte` | `<=` | `year:lte(2000)` |
| `lk` | `ILIKE %valeur%` | `title:lk(dune)` — insensible à la casse |
| `nlk` | `NOT ILIKE %valeur%` | `title:nlk(dune)` |
| `in` | `IN (...)` | `year:in(1965,1984,2001)` — valeurs séparées par une virgule, **à l'intérieur** de la parenthèse (la virgule y est reconnue différemment de celle qui sépare deux conditions — testé, pas un hasard) |
| `n` | `IS NULL` | `deleted_at:n()` — **toujours avec les parenthèses vides**, `champ:n` seul renvoie un 400 (syntaxe invalide) |

Clé de filtre non déclarée dans `Repository.filters` → **400**
(`InvalidFilterError`). Syntaxe malformée (ex. `champ:n` sans
parenthèses) → **400** aussi, jamais un 500.

### Déclarer les filtres autorisés

```python
class BookRepository(BaseRepository[Book]):
    filters = {
        "title": "title",        # clé côté client -> nom de colonne réel
        "year": "year",
        "author_id": "author_id",
    }
```

La clé et le nom de colonne peuvent différer (utile pour exposer un
nom plus parlant sans renommer la colonne SQL) — `filters =
{"auteur": "author_id"}` accepterait `?filters=auteur:eq(3)`.

## `?sort=`

`champ.direction`, plusieurs champs séparés par une virgule,
`direction` optionnelle (défaut `asc`) :

```
?sort=year.desc
?sort=year.desc,title.asc
?sort=title              (équivaut à title.asc)
```

Même allowlist que les filtres (`Repository.filters`) — un champ non
déclaré est **silencieusement ignoré** (pas d'erreur), contrairement
à `?filters=` qui rejette en 400. Volontaire : un tri sur un mauvais
champ ne doit pas faire échouer tout le listing, juste ne rien
changer à l'ordre.

## `?with=`

Relations à charger en une seule requête (`selectinload`), séparées
par une virgule :

```
?with=author
?with=author,category
```

Allowlist séparée : `Repository.includes`, jamais `filters`. Une
relation non déclarée est **silencieusement ignorée** (même logique
que le tri) — jamais d'erreur, jamais de relation chargée à
l'improviste.

```python
class BookRepository(BaseRepository[Book]):
    includes = {"author"}
```

**Piège à connaître (async SQLAlchemy)** : une relation non chargée
(absente de `?with=`) ne doit jamais être accédée directement dans le
code de réponse — ça lève `DetachedInstanceError` une fois la session
fermée. Voir `example_app/controllers/book.py::_to_book_read` pour le
pattern correct (vérifier l'état chargé via `sqlalchemy.inspect()`
avant d'y toucher).

## Pagination et tri

```
?page=2
?limit=50          (défaut : 20 ; limit=0 désactive la pagination)
?distinct=1
```

Une réponse de listing complète (voir `docs/RESPONSES.md` pour
l'enveloppe globale) :

```json
{
  "data": [ ... ],
  "meta": {
    "status": "success",
    "code": 200,
    "duration_ms": 4.2,
    "total": 25,
    "page": 1,
    "limit": 10,
    "total_pages": 3,
    "previous_page": null,
    "next_page": 2
  }
}
```

`previous_page`/`next_page` sont `null` en bout de liste (première ou
dernière page) — jamais un numéro de page invalide à appeler. Avec
`limit=0` (pagination désactivée), `total_pages` vaut `1` et les deux
valent toujours `null` (tout est déjà sur une seule "page").

## Résumé d'une requête complète

```
GET /books/?filters=title:lk(dune),year:gte(1960)|or|author_id:eq(3)&sort=year.desc&with=author&page=1&limit=20
```

`(title LIKE %dune% AND year >= 1960) OR author_id = 3`, trié par
année décroissante, avec l'auteur chargé, page 1, 20 résultats max.

## Utiliser le DSL sur `mass_delete` (`DELETE`)

`?filters=` s'applique aussi à `mass_remove`/`mass_delete` — voir la
doc `make:crud` et la section RBAC du README : sans `ids` explicites
dans le corps, il faut `confirm: true` ET un filtre actif, sinon
refusé (400).
