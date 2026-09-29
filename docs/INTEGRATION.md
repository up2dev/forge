# Guide de démarrage — pour quelqu'un qui découvre

Ce guide part du principe que tu ne connais pas Forge. On explique
tout, y compris le vocabulaire. Si un mot te semble déjà connu,
tant mieux — tu peux sauter la définition.

Il suit le chemin d'un vrai projet : démarrer, faire un premier appel,
créer ta première ressource, puis protéger l'accès, sécuriser les
comptes, envoyer des fichiers, planifier des tâches, et enfin passer en
production. Chaque étape a été suivie pour de vrai avant d'être écrite
ici — les réponses affichées sont de vraies réponses.

---

## 1. C'est quoi, Forge ?

Forge est un outil (on dit un "framework") qui sert à construire le
serveur d'une application — la partie qui reçoit des demandes (venant
d'un site web, d'une appli mobile...) et qui répond avec des données,
en allant les chercher (ou en les modifiant) dans une base de données.

Concrètement : si tu as une appli de gestion de livres, Forge te
permet de créer des adresses comme `/books` (pour lister les livres),
`/books/12` (pour voir le livre n°12), et de gérer tout ce qu'il faut
autour sans réécrire la même mécanique à chaque fois.

**Ce que Forge fait déjà pour toi**, sans que tu aies rien à écrire :

- **Connexion** : se connecter, se déconnecter, savoir qui est connecté.
- **Droits d'accès** : chaque adresse dit qui a le droit de l'utiliser
  (tout le monde, tout utilisateur connecté, ou seulement ceux qui ont
  une permission précise). Oublier de le dire empêche l'appli de
  démarrer, pour ne jamais laisser une porte ouverte par erreur.
- **Double authentification** : par application (Google Authenticator...),
  par code envoyé par email, ou avec une clé de sécurité (Yubikey...).
- **Mot de passe oublié** : par email, avec un lien à usage unique.
- **Fichiers** : envoyer, afficher, télécharger — images, PDF, Word,
  Excel ; les gros fichiers peuvent être envoyés par morceaux.
- **Listes** : filtrer, trier, découper en pages, avec le total et les
  pages précédente/suivante.
- **Réponses toujours de la même forme**, en cas de succès comme d'erreur.
- **Tâches planifiées** : "tous les jours à 3h, nettoie ceci".
- **Journal** des erreurs et **historique** de qui a modifié quoi.
- **Migrations** : l'historique des changements de la base de données.
- **Documentation interactive** de toutes tes adresses, générée toute seule.

Tu restes libre de modifier n'importe quelle partie.

## 2. Ce qu'il te faut avant de commencer

Une seule chose : **Docker Desktop** installé sur ta machine (Windows,
Mac ou Linux). Tout le reste (le langage Python, la base de données,
le serveur d'emails de test...) tourne à l'intérieur de conteneurs
Docker — tu n'as rien d'autre à installer toi-même.

Un conteneur, c'est une sorte de petite boîte isolée qui contient un
programme et tout ce dont il a besoin pour fonctionner, sans rien
mélanger avec le reste de ta machine. Le projet en utilise plusieurs :
un pour le serveur (l'API), un pour la base de données, un pour les
emails de test, un pour les tâches planifiées, un pour regarder dans la
base.

## 3. Démarrer le projet, la toute première fois

Ouvre un terminal à la racine du projet (le dossier qui contient le
fichier `Makefile`), et tape ces commandes une par une :

```bash
make up
```

Ça construit et démarre tous les conteneurs. La première fois, ça prend
une minute ou deux (téléchargement des briques nécessaires) — les fois
suivantes, c'est quasi instantané.

```bash
make seed
```

Ça prépare la base de données (crée les tables) et crée un premier
utilisateur pour tester : login `admin`, mot de passe `changeme`.

Vérifie que tout tourne :

```bash
make ps
```

Tu dois voir cinq services à l'état "Up" : `api`, `scheduler`, `db`,
`mailpit`, `adminer`.

### Les adresses utiles

Une fois démarré, ces adresses marchent dans ton navigateur :

| Adresse | À quoi ça sert |
|---|---|
| http://localhost:8000/docs | **La doc interactive** : toutes tes adresses, avec un bouton pour les tester directement. C'est là que tu vas passer du temps. |
| http://localhost:8000/redoc | La même doc, présentée pour la lecture. |
| http://localhost:8000/health | Répond `ok` si l'API tourne. |
| http://localhost:8025 | **Mailpit**, une boîte mail de test : tous les emails envoyés par l'appli arrivent ici, **aucun ne part vraiment**. |
| http://localhost:8081 | **Adminer**, pour regarder dans la base de données. Connexion : système `PostgreSQL`, serveur `db`, utilisateur `forge`, mot de passe `forge`, base `forge`. |
| http://localhost:8000/webauthn-test | Une page pour tester une clé de sécurité (voir la section 12). |

Si `http://localhost:8000/docs` s'affiche, le projet tourne
correctement.

## 4. Ton premier appel à l'API

### Se connecter

Dans `http://localhost:8000/docs`, trouve `POST /auth/login`, clique
"Try it out", mets ceci dans le corps de la requête, puis "Execute" :

```json
{"login": "admin", "password": "changeme"}
```

La réponse contient ton **jeton** (`token`) — une longue suite de
caractères qui prouve que tu es connecté :

```json
{
  "data": {
    "token": "P6e4orT5kj-Y…",
    "token_type": "bearer",
    "expires_at": "2026-10-05T06:17:06Z",
    "user": {"id": 1, "login": "admin", "email": "admin@example.test", "is_active": true}
  },
  "meta": {"status": "success", "code": 200, "duration_ms": 346.35}
}
```

Copie la valeur de `data.token`. Puis, en haut à droite de la page,
clique **Authorize** (le cadenas), colle le jeton (juste le jeton, sans
le mot "Bearer"), valide. À partir de là, toutes tes requêtes dans
`/docs` sont faites "en tant qu'admin". Essaie `GET /auth/me` : tu dois
voir ton utilisateur.

Le jeton est valable 7 jours (`FORGE_TOKEN_TTL_MINUTES` pour changer).

### La même chose en ligne de commande

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"login": "admin", "password": "changeme"}'

curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer LE_JETON_COPIÉ_CI-DESSUS"
```

Trop d'essais de connexion ratés (5 par minute) et Forge répond `429`
pendant une minute : c'est voulu, contre les mots de passe devinés.

### La forme des réponses

Toutes les réponses JSON ont la même forme. **`data` ne contient que la
vraie réponse** ; tout le reste (statut, durée, pagination) est dans
`meta`.

Un objet :

```json
{"data": {"id": 1, "name": "Frank Herbert", "created_at": "2026-09-28T06:17:06"},
 "meta": {"status": "success", "code": 200, "duration_ms": 14.7}}
```

Une liste (`data` est un tableau, `meta` dit où tu en es) :

```json
{"data": [{"id": 2, "title": "Dune Messiah", "year": 1969}],
 "meta": {"status": "success", "code": 200, "duration_ms": 9.75,
          "total": 2, "page": 1, "limit": 1, "total_pages": 2,
          "previous_page": null, "next_page": 2}}
```

Une erreur (`errors` remplace `data`) :

```json
{"errors": {"detail": "Book not found"},
 "meta": {"status": "error", "code": 404, "duration_ms": 5.52}}
```

Les messages sortent en anglais par défaut ; envoie l'en-tête
`Accept-Language: fr` pour les avoir en français. Seul le contenu d'un
fichier (image, PDF...) n'est jamais enveloppé : tu reçois le fichier
tel quel.

### Les codes que tu vas croiser

| Code | Ça veut dire | Que faire |
|---|---|---|
| 200 | Ça a marché | — |
| 400 | La demande est mal formée (filtre inconnu, syntaxe...) | Lis `errors.detail` |
| 401 | Tu n'es pas connecté, ou ton jeton a expiré | Reconnecte-toi (`/auth/login`) |
| 403 | Tu es connecté mais tu n'as pas le droit | Il manque une permission (section 11) |
| 404 | Ça n'existe pas (ou ce n'est pas à toi) | Vérifie le numéro |
| 413 / 415 | Fichier trop gros / type de fichier refusé | Section 13 |
| 422 | Il manque un champ obligatoire ou une valeur est invalide | `errors.detail` dit lequel |
| 429 | Trop de tentatives | Attends une minute |
| 500 | Une erreur dans le code du serveur | `make logs` (section 15) |

## 5. Les commandes disponibles

Toutes ces commandes se tapent dans le terminal, à la racine du
projet. Elles sont définies dans le fichier `Makefile` — un fichier
qui liste des raccourcis pour des commandes plus longues et plus
compliquées à retenir.

**Démarrer, arrêter, regarder**

| Commande | Ce qu'elle fait |
|---|---|
| `make up` | Démarre tout (et reconstruit si nécessaire) |
| `make start` | Redémarre sans reconstruire (plus rapide) |
| `make stop` | Met en pause, sans rien supprimer |
| `make down` | Arrête et supprime les conteneurs (**garde tes données**) |
| `make restart` | Redémarre les conteneurs |
| `make logs` | Affiche ce qui se passe en direct — le premier réflexe si quelque chose ne marche pas. `make logs SERVICE=api` pour un seul service |
| `make ps` | Liste les conteneurs et leur état |
| `make sh` | Ouvre un terminal *à l'intérieur* du conteneur du serveur |
| `make sh-db` | Ouvre la console de la base de données |
| `make clean` | Supprime tout, **y compris les données** — repart de zéro |

**La base de données**

| Commande | Ce qu'elle fait |
|---|---|
| `make seed` | Prépare la base (applique les migrations) et crée l'utilisateur de test |
| `make migration name="..."` | Écrit un nouveau changement de structure, à partir de ce que tu as modifié dans tes modèles |
| `make migrate` | Applique les changements de structure en attente |
| `make migrate-down` | Annule le dernier changement appliqué |

**Écrire moins de code**

| Commande | Ce qu'elle fait |
|---|---|
| `make crud name=... fields="..."` | Génère tout le nécessaire pour une nouvelle "ressource" (section 9) |
| `make permissions` | Crée en base les droits d'accès que tu as écrits dans le code (section 11) |
| `make grant role=... permission=...` | Donne un droit à un rôle (section 11) |
| `make create-role uid=... name="..."` | Crée un rôle, permissions optionnelles (section 11) |
| `make create-user login=... email=...` | Crée un utilisateur, rôle optionnel (section 11) |

**Tâches planifiées et entretien**

| Commande | Ce qu'elle fait |
|---|---|
| `make schedule-list` | Montre les tâches planifiées et leur prochaine exécution (section 14) |
| `make schedule-run` | Exécute maintenant les tâches dues à cette minute |
| `make prune` | Supprime tout de suite les liens de mot de passe oublié expirés |
| `make test` | Lance tous les tests automatiques du projet |
| `make tidy` | Supprime les fichiers parasites (`.DS_Store`, caches...) |

**Production** (section 16)

| Commande | Ce qu'elle fait |
|---|---|
| `make prod-up` | Construit et démarre la version de production |
| `make prod-migrate` | Applique les migrations en production |
| `make prod-seed` | Crée le premier administrateur en production |
| `make prod-logs` | Les logs de la production (`SERVICE=scheduler` pour un seul service) |
| `make prod-restart` / `prod-down` / `prod-sh` | Redémarrer, arrêter, ouvrir un terminal |

Si tu ne devais retenir que quatre commandes : `make up`, `make logs`,
`make seed`, `make migrate`.

### Quand faut-il relancer quoi ?

| J'ai modifié… | Je fais |
|---|---|
| du code Python (modèle, contrôleur, route...) | **Rien** : l'API se recharge toute seule |
| une tâche planifiée | `docker compose restart scheduler` (le conteneur des tâches ne se recharge pas tout seul) |
| un modèle (une colonne, une table) | `make migration name="..."` puis `make migrate` |
| `requirements.txt` ou un Dockerfile | `make up` (reconstruit) |
| le fichier `.env` | `make down` puis `make up` |
| — je veux tout effacer et repartir de zéro | `make clean`, puis `make up`, puis `make seed` |

## 6. Comment le projet est rangé

Voici les dossiers et fichiers principaux, et à quoi chacun sert :

```
forge/            <- le framework lui-même. Tu n'as normalement jamais
                     besoin d'y toucher — c'est le moteur.
example_app/      <- TON application. C'est ici que tu vas travailler
                     la plupart du temps.
alembic/          <- l'historique des changements de la base de données
scripts/          <- des petits programmes utilitaires (créer l'admin,
                     générer une ressource, donner un droit, lancer
                     les tâches planifiées...)
tests/            <- les tests automatiques, qui vérifient que tout
                     marche encore après une modification
bruno/            <- une collection de requêtes toutes prêtes, pour
                     tester l'API sans passer par du code
docs/             <- la documentation (dont ce fichier)
storage/          <- créé tout seul : les fichiers envoyés (storage/files)
                     et le journal des erreurs (storage/logs)
.env              <- les réglages de ton environnement de développement
.env.example      <- le modèle à copier pour la production
Makefile          <- les commandes `make ...`
Dockerfile, docker-compose.yml            <- le développement
Dockerfile.prod, docker-compose.prod.yml  <- la production
```

Le dossier qui t'intéresse presque toujours, c'est `example_app/`.
Regardons ce qu'il y a dedans :

```
example_app/
  models/          <- la structure de tes données
  repositories/     <- l'accès à la base de données
  controllers/       <- ce qui se passe quand une requête arrive
  schemas/           <- la forme exacte des données envoyées/reçues
  routes.py           <- la liste des adresses de ton application
  schedule.py          <- tes tâches planifiées
  main.py              <- le point de démarrage de l'application
```

Ces cinq mots (modèle, repository, contrôleur, schéma, route) sont le
vocabulaire de base. On les explique un par un juste en dessous, avant
de les utiliser pour de vrai.

## 7. Le vocabulaire de base

### Un modèle (dans `models/`)

Un modèle décrit **une table de la base de données**, sous forme de
code. Si tu as une table "livres" avec les colonnes titre, année, et
auteur, le modèle ressemble à ça :

```python
class Book(Base, TimestampMixin):
    __tablename__ = "books"          # le nom de la table en base

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    year: Mapped[int] = mapped_column(Integer)
```

Chaque ligne correspond à une colonne. `id` est toujours présent (un
numéro unique attribué automatiquement à chaque livre). `TimestampMixin`
ajoute automatiquement deux colonnes utiles (date de création, date de
dernière modification) — pas besoin de les écrire toi-même.

### Un repository (dans `repositories/`)

Un repository, c'est l'intermédiaire entre ton code et la base de
données : c'est lui qui sait comment aller chercher, créer, modifier
ou supprimer des lignes dans une table. Il porte quasiment toujours le
même nom que le modèle, avec "Repository" à la fin :

```python
class BookRepository(BaseRepository[Book]):
    model = Book
```

Dans la majorité des cas, c'est tout ce qu'il y a à écrire — `BaseRepository`
(fourni par Forge) sait déjà faire "lister", "créer", "modifier",
"supprimer" tout seul, du moment qu'on lui dit quel modèle utiliser.

### Un contrôleur (dans `controllers/`)

Un contrôleur, c'est ce qui **reçoit une demande** (par exemple "donne-moi
la liste des livres") et **prépare la réponse**. La plupart du temps,
il ne fait quasiment rien lui-même — il passe la main au repository :

```python
class BookController(BaseController[BookRepository]):
    pass
```

Encore une fois, vide — `BaseController` sait déjà répondre à "liste
tout", "montre-moi celui-ci", "crée-en un", "modifie celui-ci",
"supprime celui-ci". Tu ne remplis un contrôleur toi-même que si tu
veux un comportement particulier (voir plus loin).

### Une route (dans `routes.py`)

Une route, c'est **l'adresse** qu'on tape (ou qu'un site/une appli
appelle) pour déclencher une action. `GET /books/` (lister),
`POST /books/` (créer), `GET /books/12` (voir le livre 12)... Une
route relie une adresse à une méthode du contrôleur :

```python
books_router = ControllerRouter(BookController, prefix="/books")
books_router.resource(authenticated_only=True)
```

`resource()` crée d'un coup les 8 routes habituelles (lister, voir,
créer, modifier, supprimer, et leurs équivalents "en masse"). Le
`authenticated_only=True` dit : "il faut être connecté pour utiliser
ces routes" — Forge t'oblige toujours à préciser qui a le droit
(connecté, tout le monde, ou une permission précise), jamais de route
ouverte par oubli.

### Un schéma (dans `schemas/`)

Un schéma décrit **la forme exacte** des données qu'on envoie ou
qu'on reçoit — un peu comme un formulaire qui dit "il faut un champ
titre (texte), un champ année (nombre)". Il sert à deux choses :
vérifier que ce qui arrive est correct, et documenter clairement ce
que l'API attend/renvoie.

```python
class BookCreate(BaseModel):
    title: str
    year: int
    author_id: int
```

Un schéma est **optionnel** — sans lui, Forge accepte n'importe quel
champ envoyé. Avec, seuls les champs prévus sont acceptés, et la page
`/docs` affiche exactement à quoi ressemble une requête correcte.

### Une migration (dans `alembic/`)

Une migration, c'est **la trace écrite d'un changement dans la
structure de la base de données** ("ajoute une colonne", "crée une
table"...). Sans ça, si tu ajoutes une colonne dans un modèle, rien
ne se passe automatiquement en base — il faut générer et appliquer
une migration pour que le changement soit réellement fait sur les
vraies données.

---

## 8. Construire une ressource, vraiment de zéro

On va créer une petite fonctionnalité complète : gérer des
**catégories** (juste un nom, pour rester simple). On fait tout à la
main, sans le générateur automatique — pour bien comprendre chaque
étape. La commande automatique est montrée à la toute fin.

### Étape 1 — le modèle

Crée le fichier `example_app/models/category.py` avec ce contenu :

```python
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from forge.models.base import Base, TimestampMixin


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(120))
```

Ligne par ligne :
- `__tablename__ = "categories"` : le nom de la table qui sera créée
  en base de données.
- `id` : le numéro unique de chaque catégorie, généré automatiquement.
- `label` : le nom de la catégorie, un texte de 120 caractères max.
- `Base, TimestampMixin` : deux briques fournies par Forge —
  `TimestampMixin` ajoute les colonnes de dates automatiquement.

### Étape 2 — le repository

Crée `example_app/repositories/category.py` :

```python
from __future__ import annotations

from forge.repositories.base import BaseRepository

from example_app.models.category import Category


class CategoryRepository(BaseRepository[Category]):
    model = Category
    filters = {"label": "label"}
```

`filters` dit : "on autorise à filtrer/trier sur le champ `label`".
Sans cette ligne, personne ne pourrait faire une recherche par nom de
catégorie via l'API — c'est volontaire, pour éviter qu'un champ
sensible soit filtrable sans qu'on l'ait décidé explicitement.

### Étape 3 — le contrôleur

Crée `example_app/controllers/category.py` :

```python
from forge.controllers.base import BaseController

from example_app.repositories.category import CategoryRepository


class CategoryController(BaseController[CategoryRepository]):
    pass
```

Rien de plus à écrire pour l'instant — lister/créer/modifier/supprimer
fonctionnent déjà grâce à `BaseController`.

### Étape 4 — brancher les routes

Ouvre `example_app/routes.py`. Ajoute l'import en haut du fichier :

```python
from example_app.controllers.category import CategoryController
```

Puis, à côté des routeurs déjà présents (`books_router`,
`authors_router`...), ajoute :

```python
categories_router = ControllerRouter(CategoryController, prefix="/categories", tags=["categories"])
categories_router.resource(authenticated_only=True)
```

Et enfin, ajoute `categories_router` dans la liste `ALL_ROUTERS` un
peu plus bas dans le même fichier — c'est cette liste que
`example_app/main.py` parcourt pour activer toutes les routes. Sans
cet ajout, tes routes existeraient dans le code mais ne répondraient
à rien.

Si tu oublies le `authenticated_only=True` (ou l'équivalent
`public=True` ou `permission="..."`), l'application refusera de
démarrer, avec une erreur claire — c'est volontaire : Forge préfère te
bloquer tout de suite plutôt que de laisser passer une route sans
protection sans que tu t'en rendes compte.

### Étape 5 — créer la table en base

Le modèle existe dans le code, mais la table n'existe pas encore
réellement dans la base de données. Il faut générer et appliquer une
migration :

```bash
make migration name="add categories"
make migrate
```

La première commande regarde ce qui a changé dans les modèles et
écrit automatiquement le nécessaire dans un nouveau fichier, dans
`alembic/versions/`. La deuxième commande applique ce fichier sur la
vraie base de données.

### Étape 6 — tester

Va sur `http://localhost:8000/docs`, clique sur "Authorize" en haut à
droite, connecte-toi avec `admin` / `changeme`, puis cherche
"categories" dans la liste — tu peux créer, lister, modifier,
supprimer des catégories directement depuis cette page.

En ligne de commande, ça donnerait :

```bash
curl -X POST http://localhost:8000/categories/ \
  -H "Authorization: Bearer TON_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label": "Science-fiction"}'
```

(`TON_TOKEN` est la valeur de `data.token` obtenue à la section 4.)

Voilà : une ressource complète, de zéro, sans avoir touché à `forge/`.

## 9. Le raccourci : générer tout ça automatiquement

Une fois que tu as compris ce que fait chaque fichier, tu n'as plus
besoin de les écrire à la main à chaque fois. Cette seule commande
fait exactement les étapes 1 à 4 ci-dessus d'un coup :

```bash
make crud name=category fields="label:str"
```

Il ne reste plus que les étapes 5 et 6 (migration, puis tester) à
faire toi-même — le générateur écrit le code, jamais le schéma de la
base.

D'autres types de champs sont possibles :

```bash
# un champ optionnel (peut être vide) : ajoute un ?
make crud name=product fields="name:str,price:float?"

# une relation vers une autre table (un livre appartient à un auteur)
make crud name=book fields="title:str,author:fk:authors"

# une relation optionnelle
make crud name=book fields="title:str,category:fk:categories?"

# une relation "plusieurs à plusieurs" (un livre peut avoir plusieurs
# étiquettes, une étiquette peut concerner plusieurs livres)
make crud name=tag fields="name:str,books:m2m:books"
```

## 10. Chercher, trier, découper les listes

Toute liste (`GET /books/`, `GET /categories/`...) sait déjà filtrer,
trier et se découper en pages, grâce à des paramètres dans l'adresse :

```
GET /books/?filters=title:lk(dune)&sort=year.desc&with=author&limit=1&page=1
```

Ça veut dire : les livres dont le titre contient "dune", du plus récent
au plus ancien, avec leur auteur, à raison d'un par page, page 1.

| Paramètre | Rôle | Exemple |
|---|---|---|
| `filters` | Ne garder que certaines lignes | `title:lk(dune)` (contient "dune") |
| `sort` | Trier (`.asc` ou `.desc`) | `year.desc` |
| `with` | Ajouter une relation à chaque ligne | `author` |
| `limit` | Combien de lignes par page (20 par défaut) | `limit=50` |
| `page` | Quelle page | `page=2` |

Les comparaisons les plus utiles : `eq` (égal), `neq` (différent), `gt` /
`gte` (plus grand que / ou égal), `lt` / `lte` (plus petit), `lk`
(contient), `in` (dans une liste : `year:in(1965,1984)`). On combine avec
une virgule (**et**) ou `|or|` (**ou**) :
`filters=year:gte(1960),year:lte(1970)`.

La réponse dit où tu en es, dans `meta` (voir la section 4) : `total`,
`total_pages`, `previous_page`, `next_page` — `null` quand il n'y a plus
de page à visiter.

**Seuls les champs que tu as déclarés sont filtrables.** C'est la ligne
`filters = {"label": "label"}` que tu as écrite à l'étape 2 de la
section 8. Un autre champ est refusé, exprès :

```json
{"errors": {"detail": "Clé de filtre inconnue 'secret' pour BookRepository — à déclarer dans `filters`."},
 "meta": {"status": "error", "code": 400}}
```

Pour la liste complète des comparaisons et des cas particuliers :
[`docs/FILTERS.md`](FILTERS.md).

## 11. Qui a le droit ? Les accès et les permissions

À l'étape 4 de la section 8, tu as écrit
`categories_router.resource(authenticated_only=True)`. Ce petit
morceau décide **qui a le droit** d'utiliser les adresses. Il y a trois
réponses possibles, et Forge t'oblige à en choisir une :

| Tu écris | Qui peut utiliser l'adresse |
|---|---|
| `public=True` | Tout le monde, même sans être connecté |
| `authenticated_only=True` | Tout utilisateur connecté |
| `permission="CATEGORIES_DELETE"` | Seulement ceux qui ont cette permission |

Trois mots à connaître :

- une **permission** est un droit précis ("supprimer une catégorie") ;
- un **rôle** est un groupe de permissions (l'`ADMIN` en a beaucoup) ;
- un **utilisateur** a un ou plusieurs rôles.

### Exemple pas à pas : protéger la suppression

On veut que **seuls certains utilisateurs** puissent supprimer une
catégorie, mais que tout utilisateur connecté puisse lire et créer.

**1. Dans `example_app/routes.py`**, change la ligne de tes catégories :

```python
categories_router.resource(permissions={"remove": "CATEGORIES_DELETE"})
```

Toutes les actions non citées (lister, créer, modifier...) restent
ouvertes à tout utilisateur connecté ; seule `remove` (supprimer)
exige la permission.

**2. Crée la permission en base :**

```bash
make permissions
```

```
Permissions créées : CATEGORIES_DELETE
```

Le nom écrit dans le code ne crée rien tout seul : cette commande
parcourt toutes tes adresses et crée en base les permissions qui
manquent.

**3. Essaie de supprimer une catégorie** dans `/docs` (`DELETE
/categories/1`, connecté en admin) :

```json
{"errors": {"detail": "Missing permission: CATEGORIES_DELETE"},
 "meta": {"status": "error", "code": 403}}
```

Tu as un `403`, alors que tu es l'admin. C'est normal : la permission
existe maintenant, mais **Forge ne la donne jamais automatiquement** à
qui que ce soit. Donner un droit est une décision, pas un effet de
bord. (`make seed` donne à l'admin les permissions qui existent *au
moment où il le crée* ; celles créées après doivent lui être données.)

**4. Donne la permission à un rôle :**

```bash
make grant role=ADMIN permission=CATEGORIES_DELETE
```

```
Permission CATEGORIES_DELETE donnée au rôle ADMIN.
```

**5. Réessaie la suppression** : `200`. Tu n'as pas besoin de te
reconnecter — les droits sont relus à chaque requête.

```json
{"data": {"deleted": 1}, "meta": {"status": "success", "code": 200}}
```

### Créer d'autres rôles et d'autres utilisateurs

```bash
make create-role uid=EDITOR name="Éditeur"
make create-user login=carol email=carol@exemple.fr role=EDITOR
```

```
Rôle EDITOR (Éditeur) créé.
Utilisateur carol (carol@exemple.fr) créé.
Mot de passe généré : Qua_xhDiXT4FDsTl  (à transmettre, jamais réaffiché)
Rôle : EDITOR
```

Sans `password=`, un mot de passe est généré et affiché **une seule
fois** — jamais stocké en clair, à transmettre à l'intéressé. `make
create-role uid=... name=... permissions=BOOKS_DELETE,NOTES_ADMIN`
donne des permissions dès la création (elles doivent déjà exister,
`make permissions` les crée).

**Plusieurs utilisateurs d'un coup**, depuis un fichier CSV
(colonnes `login,email,password,role` — `password`/`role` vides
acceptés) :

```bash
docker compose exec api python scripts/create_user.py --file users.csv
```

Il n'y a en revanche pas d'adresse dans l'API pour qu'un visiteur
s'inscrive lui-même : qui peut s'inscrire, et comment, est propre à
chaque application (ouvert à tous ? sur invitation ? validé par un
administrateur ?). `scripts/create_user.py` est justement l'outil
d'administration pour créer des comptes sans en écrire — construire
une inscription publique reste au cas par cas.

## 12. Sécuriser les comptes

### 12.1 Mot de passe oublié

Tout se passe sans être connecté, et **sans qu'aucun email ne parte
vraiment** en développement : ils arrivent dans Mailpit
(http://localhost:8025).

**1.** Dans `/docs`, `POST /auth/pwd/forgot` :

```json
{"email": "admin@example.test"}
```

La réponse est **la même que le compte existe ou non** — exprès, pour
qu'on ne puisse pas deviner quels comptes existent :

```json
{"data": {"detail": "If this account exists, an email has just been sent"}, "meta": {"status": "success", "code": 200}}
```

**2.** Ouvre **Mailpit** (http://localhost:8025) : l'email est là, avec
un lien du genre :

```
http://localhost:5173/reset-password?token=FmWrJ8O4dsKim9PzD51u…
```

Le lien pointe vers **le front** (le site ou l'appli que tu construis
devant Forge), pas vers l'API : c'est lui qui affichera le formulaire
"nouveau mot de passe". Ici il n'existe pas encore (`localhost:5173`
ne répond pas) : **copie simplement la longue valeur après `token=`**.
L'adresse du front se règle avec `FORGE_FRONTEND_URL` et
`FORGE_FRONTEND_PWD_RESET_PATH`.

**3.** Dans `/docs`, `POST /auth/pwd/reset` (8 caractères minimum) :

```json
{"token": "LA_VALEUR_COPIÉE", "password": "nouveau-mot-de-passe"}
```

```json
{"data": {"detail": "Password updated"}, "meta": {"status": "success", "code": 200}}
```

**4.** Reconnecte-toi avec le nouveau mot de passe.

Ce qu'il faut savoir : le lien est valable **60 minutes** et ne sert
**qu'une fois** ; redemander un lien **annule le précédent** ; tes
sessions déjà ouvertes ailleurs sont **fermées** (un mot de passe
compromis ne doit pas laisser de session ouverte) ; et ça ne te
connecte pas — si tu as la double authentification, elle reste exigée.

### 12.2 Double authentification

La double authentification ajoute une deuxième preuve après le mot de
passe. Forge en propose trois. Tu peux en activer une ou plusieurs.

**Par email** (la plus simple à essayer) :

**1.** Connecté (bouton Authorize), `POST /auth/mfa/setup` :

```json
{"method": "email"}
```

**2.** Un code à 6 chiffres arrive dans Mailpit. `POST /auth/mfa/confirm` :

```json
{"method": "email", "code": "123456"}
```

```json
{"data": {"confirmed": true, "token": null}, "meta": {"status": "success", "code": 200}}
```

**3.** Maintenant, `POST /auth/login` ne te donne plus un jeton tout de
suite. Il répond :

```json
{"data": {"pending_token": "WDotD_Bi7R…", "intent": "verify", "methods": ["email"]},
 "meta": {"status": "success", "code": 200}}
```

Un nouveau code vient d'être envoyé à Mailpit. `POST /auth/mfa/verify`
avec ce `pending_token` et le code te donne enfin le vrai jeton :

```json
{"pending_token": "WDotD_Bi7R…", "method": "email", "code": "654321"}
```

**Par application** (Google Authenticator, Microsoft Authenticator,
Aegis...) : `POST /auth/mfa/setup` avec `{"method": "totp"}` renvoie un
`secret`. Dans ton application, ajoute un compte en choisissant
**"saisir une clé"** et colle ce secret. Elle affiche alors un code à 6
chiffres qui change toutes les 30 secondes : envoie-le à `POST
/auth/mfa/confirm` (`{"method": "totp", "code": "..."}`). Ensuite le
login se passe comme ci-dessus, avec `"method": "totp"`. Un même code
ne marche **qu'une fois** : si Forge dit "Invalid code" juste après
avoir confirmé, attends le code suivant.

**Avec une clé de sécurité** (Yubikey...) : branche ta clé, ouvre
http://localhost:8000/webauthn-test, connecte-toi, puis "Enregistrer ma
clé" (ton navigateur te demande de toucher la clé). "Se connecter avec
la clé" fait ensuite la connexion complète. Il faut utiliser
exactement l'adresse `localhost:8000` — pas `127.0.0.1:8000` — sinon le
navigateur refuse (voir la section 17).

Pour aller plus loin :

- `FORGE_MFA_FORCE_ENROLLMENT=1` oblige **tout le monde** à activer une
  méthode dès la première connexion ;
- 5 codes faux de suite sur une même connexion (`FORGE_MFA_MAX_ATTEMPTS`)
  détruisent la connexion en cours : il faut recommencer au mot de passe ;
- `DELETE /auth/mfa/totp` (ou `email`, `webauthn`) désactive une
  méthode — sauf la dernière quand l'inscription est obligatoire ;
- le détail de tout ça est dans le [`README.md`](../README.md), section MFA.

## 13. Envoyer et récupérer des fichiers

Forge sait déjà recevoir, ranger et rendre des fichiers. Chaque
utilisateur ne voit **que ses propres fichiers**.

**Envoyer un fichier** — dans `/docs`, `POST /files/`, "Try it out",
choisis un fichier, "Execute" (ou, en ligne de commande) :

```bash
curl -X POST http://localhost:8000/files/ \
  -H "Authorization: Bearer LE_JETON" \
  -F "file=@mon-document.pdf;type=application/pdf"
```

```json
{"data": {"id": 1, "filename": "note.pdf", "content_type": "application/pdf",
          "total_bytes": 13, "received_bytes": 13,
          "completed_at": "2026-09-28T06:17:06", "max_chunk_size": 1000000},
 "meta": {"status": "success", "code": 200}}
```

Note le `id` : c'est lui qui désigne ton fichier.

| Adresse | Ce que ça fait |
|---|---|
| `GET /files/` | Liste **tes** fichiers |
| `GET /files/1` | **Affiche** le fichier : une image ou un PDF s'ouvre directement |
| `GET /files/1/download` | **Télécharge** le fichier (fonctionne pour tout type de fichier) |
| `DELETE /files/1` | Supprime le fichier |

En ligne de commande : `curl -o copie.pdf -H "Authorization: Bearer LE_JETON" http://localhost:8000/files/1/download`.

À savoir :

- **Types acceptés** : images (png, jpeg, gif, webp), PDF, Word (doc,
  docx), Excel (xls, xlsx), texte et CSV. Un autre type est refusé avec
  un `415` (`FORGE_STORAGE_ALLOWED_TYPES` pour changer la liste).
- **Taille maximale** : 25 Mo (`FORGE_STORAGE_MAX_BYTES`), sinon `413`.
- Les fichiers sont rangés dans `storage/files/` sur ta machine, sous
  des noms aléatoires — jamais sous le nom que le client a envoyé.
- **Gros fichiers, connexion fragile** : on peut les envoyer par morceaux
  (`POST /files/start`, puis `PUT /files/{id}` autant de fois que
  nécessaire, puis `POST /files/{id}/complete`), et reprendre après une
  coupure sans tout renvoyer. Le détail est dans le
  [`README.md`](../README.md), section "Stockage de fichiers".

## 14. Les tâches planifiées

Une tâche planifiée, c'est un bout de code que Forge lance **tout seul à
heure fixe** : nettoyer des données, envoyer un rapport... Un conteneur
dédié (`scheduler`) s'en occupe, en permanence, dès `make up`.

Les tâches sont toutes déclarées **au même endroit** :
`example_app/schedule.py`. Regarde ce qui est déjà planifié :

```bash
make schedule-list
```

```
TÂCHE                             CRON          PROCHAINE EXÉCUTION (UTC)               DESCRIPTION
prune-password-reset-tokens       0 3 * * *     2026-09-29 03:00                        Supprime les liens de reset de mot de passe expirés
```

Cette tâche supprime chaque nuit, à 3h, les liens de mot de passe
oublié expirés.

### Ajouter ta propre tâche, pas à pas

Le plus simple pour comprendre : une tâche de test qui dit bonjour
**chaque minute**.

**1.** À la fin de `example_app/schedule.py`, ajoute :

```python
import logging

logger = logging.getLogger("forge.app")


async def dire_bonjour():
    logger.info("Bonjour depuis une tâche planifiée !")


schedule.task("bonjour", "* * * * *", dire_bonjour, "Test du guide")
```

Une tâche, c'est : un **nom** (unique), une **heure** (l'expression
`* * * * *`, expliquée juste après), la **fonction** à lancer, et une
courte description.

**2.** Le conteneur des tâches ne se recharge pas tout seul :

```bash
docker compose restart scheduler
```

**3.** Vérifie qu'elle est connue : `make schedule-list` doit montrer
deux lignes.

**4.** Regarde les logs du planificateur, et attends la minute suivante :

```bash
make logs SERVICE=scheduler
```

```
Planificateur démarré : 2 tâche(s)
Bonjour depuis une tâche planifiée !
Tâche 'bonjour' terminée en 0 ms
```

**5.** Quand c'est compris, **retire la tâche de test** (sinon elle
tourne toute la journée), puis `docker compose restart scheduler`.

### Écrire l'heure : le format "cron"

L'heure s'écrit avec cinq nombres, dans cet ordre :

```
minute  heure  jour-du-mois  mois  jour-de-la-semaine
```

`*` veut dire "tous". Quelques exemples :

| Tu écris | Ça se lance |
|---|---|
| `* * * * *` | Chaque minute |
| `*/15 * * * *` | Toutes les 15 minutes |
| `0 3 * * *` | Tous les jours à 3h00 |
| `30 8 * * 1` | Tous les lundis à 8h30 (0 ou 7 = dimanche) |
| `0 9-17 * * 1-5` | Toutes les heures pile de 9h à 17h, du lundi au vendredi |
| `0 0 1 * *` | Le 1er de chaque mois à minuit |
| `@daily` | Tous les jours à minuit (aussi `@hourly`, `@weekly`, `@monthly`, `@yearly`) |

Une expression invalide empêche le planificateur de démarrer, avec un
message clair — pas de surprise à 3h du matin.

**À quelle heure ?** Par défaut en UTC. Pour que "3h" soit ton heure à
toi, règle `FORGE_SCHEDULER_TIMEZONE=Europe/Paris` dans `.env` (heure
d'été comprise), puis `make down` et `make up`.

### Ce qu'il faut savoir

- Si une tâche **plante**, l'erreur est écrite dans les logs et les
  autres tâches continuent normalement.
- Si une tâche est **encore en cours** quand revient son heure, cette
  exécution est sautée (pas de doublon).
- Redémarrer le planificateur en pleine minute **ne relance pas** les
  tâches de cette minute.
- Il ne doit y avoir **qu'un seul** conteneur `scheduler` : deux
  exécuteraient chaque tâche en double.
- Il n'y a pas d'historique des exécutions en base : ce sont les logs
  qui gardent la trace.

## 15. Voir ce qui se passe

**Les logs en direct** — le premier réflexe quand quelque chose ne
marche pas :

```bash
make logs                    # tout
make logs SERVICE=api        # seulement l'API
make logs SERVICE=scheduler  # seulement les tâches planifiées
```

**Le journal des erreurs** — une erreur du serveur (`500`) affiche
seulement "Internal server error" à celui qui a fait la demande, pour ne
rien révéler. La vraie erreur, avec tous les détails, est écrite dans
`storage/logs/forge.log` sur ta machine.

**Voir les données** — ouvre **Adminer** (http://localhost:8081 ;
système `PostgreSQL`, serveur `db`, utilisateur `forge`, mot de passe
`forge`, base `forge`) : tu vois toutes les tables et leur contenu.

**Les emails** — en développement, ils arrivent tous dans **Mailpit**
(http://localhost:8025) et ne sortent jamais de ta machine.

**L'historique des modifications** — pour savoir *qui a changé quoi*,
ajoute une seule ligne dans le repository concerné :

```python
class CategoryRepository(BaseRepository[Category]):
    model = Category
    filters = {"label": "label"}
    loggable = True
```

Dès lors, chaque création, modification ou suppression de catégorie est
enregistrée. Crée une catégorie dans `/docs`, puis regarde dans Adminer
la table **`activity_log`** : tu y trouves le modèle touché, le numéro de
la ligne, l'action (`create`, `update`, `delete`), le numéro de
l'utilisateur qui l'a faite, et ce qui a changé.

## 16. Passer en production, pas à pas

La production n'utilise **pas** les mêmes fichiers que le
développement : une image plus légère et plus sûre (`Dockerfile.prod`),
sans rechargement automatique, sans Mailpit ni Adminer, avec des
secrets qui ne sont écrits nulle part dans le code. Tu as besoin d'un
serveur avec Docker et d'un nom de domaine.

**1. Prépare tes réglages secrets.** Copie le modèle :

```bash
cp .env.example .env.prod
```

Ce fichier ne doit **jamais** être publié (ni dans git). Ouvre-le et
change au minimum :

| Réglage | Pourquoi |
|---|---|
| `POSTGRES_PASSWORD` | Le mot de passe de la base. Un vrai, long, pas `forge`. |
| `FORGE_APP_KEY` | La clé qui chiffre les secrets de double authentification. Génère-en une : `openssl rand -base64 32`. **Garde-la précieusement** : la perdre ou la changer rend illisibles les secrets déjà enregistrés. |
| `FORGE_ADMIN_LOGIN`, `FORGE_ADMIN_EMAIL`, `FORGE_ADMIN_PASSWORD` | Ton premier administrateur. Mets une **vraie adresse email** : c'est là que partira le lien "mot de passe oublié". |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `MAIL_FROM` | Ton vrai serveur d'email (Mailpit n'existe pas en production). |
| `FORGE_FRONTEND_URL` | L'adresse de ton vrai site, pour les liens des emails. |
| `FORGE_WEBAUTHN_RP_ID`, `FORGE_WEBAUTHN_ORIGIN` | Ton domaine (`app.exemple.fr`) et son adresse complète (`https://app.exemple.fr`), si tu utilises les clés de sécurité. |
| `FORGE_SCHEDULER_TIMEZONE` | Ton fuseau (`Europe/Paris`), pour que "3h" soit ton 3h. |

**2. Démarre :**

```bash
make prod-up
```

Si `.env.prod` manque, la commande s'arrête avec un message clair.

**3. Crée les tables, puis le premier administrateur :**

```bash
make prod-migrate
make prod-seed
```

Les migrations ne sont **jamais** lancées automatiquement au démarrage :
c'est un geste volontaire, une seule fois par mise à jour.

**4. Vérifie :** `https://ton-domaine/health` doit répondre `ok`,
`make prod-logs` ne doit montrer aucune erreur, et
`make prod-logs SERVICE=scheduler` doit dire "Planificateur démarré".

**5. Le HTTPS** : Forge parle en HTTP simple sur le port 8000. Un
*reverse proxy* devant (nginx, Caddy, Traefik, ou le répartiteur de ton
hébergeur) fournit le HTTPS. Sans lui, mots de passe et jetons
circuleraient en clair.

**6. Ce qu'il faut retirer ou verrouiller :**

- la page de test `/webauthn-test` (la route est dans
  `example_app/main.py`) — utile en développement, inutile en production ;
- pense à qui doit voir `/docs` : c'est pratique, mais c'est aussi la
  carte de toutes tes adresses.

**7. Les sauvegardes.** Il y a deux choses à sauvegarder : la base, et
les fichiers envoyés (le volume `forge_storage`). Une sauvegarde de la
base :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T db \
  sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > sauvegarde.sql
```

Fais un essai de restauration **avant** d'en avoir besoin.

**8. Mettre à jour.** Récupère la nouvelle version du code, puis :

```bash
make prod-up
make prod-migrate
```

**À savoir :** la production tourne avec **un seul** worker et **un
seul** conteneur `scheduler`. Le compteur d'essais de connexion et les
envois de fichiers par morceaux vivent en mémoire / sur le disque du
conteneur : plusieurs instances derrière un répartiteur donneraient des
résultats incohérents. Les explications complètes (et comment passer à
plusieurs instances un jour) sont dans
[`docs/DEPLOYMENT.md`](DEPLOYMENT.md).

## 17. Si ça ne marche pas

Presque toujours, la réponse est dans `make logs` : regarde les
dernières lignes.

| Ce que tu vois | La cause probable | Que faire |
|---|---|---|
| `localhost:8000` ne répond pas (`ERR_EMPTY_RESPONSE`, page blanche) | L'API a planté au démarrage | `make logs SERVICE=api`, lis la dernière erreur |
| `ModuleNotFoundError: No module named 'forge.…'` après avoir décompressé une nouvelle version | La décompression était incomplète, ou d'anciens fichiers traînent | Supprime **entièrement** l'ancien dossier, décompresse la nouvelle archive complète à la place, puis `make down` et `make up` |
| `Multiple head revisions are present` | D'anciens fichiers de migration d'une version précédente traînent dans `alembic/versions/` | Ne garde dans ce dossier que les fichiers de la dernière archive, supprime les autres, puis `make migrate` |
| `relation "…" does not exist`, `no such table` | La base n'a pas les dernières tables | `make migrate` (ou `make seed`) |
| Un `401` partout | Pas de jeton, ou jeton expiré | Reconnecte-toi, puis Authorize dans `/docs` |
| Un `403` | Il te manque une permission | Section 11 (`make permissions`, puis `make grant`) |
| Un `422` | Un champ manque ou est invalide | Lis `errors.detail` : il nomme le champ |
| Un `429` | Trop de tentatives | Attends une minute |
| `port is already allocated` au `make up` | Un autre programme utilise déjà 8000, 5432, 8025 ou 8081 | Arrête-le, ou change le numéro de gauche dans `docker-compose.yml` |
| Le mot de passe oublié n'envoie rien | En développement, l'email est dans Mailpit | http://localhost:8025 |
| En production, aucun email ne part | Réglages `SMTP_*` incorrects | `make prod-logs`, cherche "Failed to send email" |
| La clé de sécurité est refusée par le navigateur | L'adresse utilisée n'est pas celle configurée | Utilise `http://localhost:8000` (pas `127.0.0.1`), ou règle `FORGE_WEBAUTHN_RP_ID` / `FORGE_WEBAUTHN_ORIGIN` sur ton vrai domaine |
| Ma tâche planifiée ne se lance pas | Le conteneur n'a pas été redémarré | `docker compose restart scheduler`, puis `make logs SERVICE=scheduler` |
| Un `500` sans explication | Une vraie erreur dans le code | `storage/logs/forge.log` contient tout le détail |

## 18. Pour la suite

Une fois cette base comprise, quelques sujets pour aller plus loin,
chacun avec sa propre doc :

- **Filtrer, trier, et charger des relations depuis l'API**
  (`?filters=`, `?sort=`, `?with=`) : [`docs/FILTERS.md`](FILTERS.md).
- **La forme de chaque réponse** (succès, erreur, pagination) :
  [`docs/RESPONSES.md`](RESPONSES.md).
- **Déployer en prod** (image, secrets, HTTPS, tâches planifiées) :
  [`docs/DEPLOYMENT.md`](DEPLOYMENT.md).
- **La structure complète de la base de données** (toutes les tables,
  leurs liens) : [`docs/SCHEMA.md`](SCHEMA.md).
- **Limiter l'accès à ses propres données** (un utilisateur ne voit
  que ses notes, par exemple), **les logs vers MongoDB**, **l'upload de
  fichiers par morceaux**, **tous les réglages** : tout est détaillé
  dans le [`README.md`](../README.md) à la racine du projet, section par
  section.
