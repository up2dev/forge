<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-wordmark-dark.svg">
  <img src="docs/assets/logo-wordmark.svg" alt="Forge" width="280">
</picture>

Framework CRUD/RBAC par convention pour FastAPI, dans l'esprit de
[Rivet](https://github.com/up2dev/rivet) — Router/Controller/Repository
plutôt que des endpoints libres. Auth, RBAC, MFA (TOTP/email/WebAuthn),
reset de mot de passe, stockage de fichiers, planificateur de tâches,
générateur de CRUD, et une suite de 179 tests qui tourne aussi bien sur
SQLite que sur un vrai Postgres.

## Lancer avec Docker

```bash
make up
make seed   # crée l'utilisateur admin/changeme (rôle ADMIN)
```

- API : http://localhost:8000
- **Doc interactive (Swagger)** : http://localhost:8000/docs — bouton "Authorize" en haut à droite pour coller un token Bearer et tester les routes protégées directement depuis la doc
- **Doc alternative (Redoc)** : http://localhost:8000/redoc
- Schéma OpenAPI brut : http://localhost:8000/openapi.json
- Postgres exposé sur `localhost:5432` (user/pass/db : `forge`/`forge`/`forge`)
- **Voir les données en base (dev)** : http://localhost:8081 (Adminer)
  — système "PostgreSQL", serveur `db`, user/pass/base `forge`. Jamais
  exposé en prod (retire le service `adminer` du `docker-compose.yml`
  avant de déployer — pour la prod, passe par un outil tiers dédié,
  pas d'accès web direct à la base).
- **Emails (Mailpit)** : http://localhost:8025 — tous les emails envoyés par l'app atterrissent là, rien ne part jamais vers un vrai serveur mail

Le service `api` monte `./forge` et `./example_app` en volume avec
`--reload` : les modifications de code sont prises en compte à chaud,
sans rebuild d'image.

Pour un déploiement (pas du dev local), retire le `command:` avec
`--reload` et les `volumes:` du service `api` dans
`docker-compose.yml` — l'image buildée contient déjà tout le code.

## Format des réponses

Toute réponse JSON (succès ou erreur) est enveloppée dans une forme
standard — `data` (ou `errors`) ne contient que la réponse réelle,
`meta` regroupe `status`/`code`/`duration_ms` et, pour un listing, la
pagination :

```json
{"data": {"id": 1, "title": "Dune"}, "meta": {"status": "success", "code": 200, "duration_ms": 3.1}}
{"errors": {"detail": "Not found"}, "meta": {"status": "error", "code": 404, "duration_ms": 0.4}}
```

Détail complet (listing/pagination compris) : `docs/RESPONSES.md`.
Seul le contenu binaire d'un fichier (`/files/{id}`, `/download`)
n'est jamais enveloppé.

## MFA (TOTP, email, WebAuthn/FIDO2)

Endpoints génériques — `method` en paramètre, pas un endpoint par
méthode :

- `POST /auth/mfa/setup` `{method: "totp"|"email"|"webauthn", secret?}`
  → pour `totp` : `{secret, qr_uri}`, à scanner dans une app TOTP.
  `secret` optionnel : à fournir toi-même pour importer un token
  matériel (C105, Yubikey en mode OTP...) plutôt que d'en générer un —
  le secret est encodé dans le QR code du fabricant (format
  `otpauth://...&secret=XXXX`), le chiffre imprimé sur le boîtier est
  en général le numéro de série, pas la clé.
  Pour `email` : envoie un code, renvoie `{detail}`.
  Pour `webauthn` : renvoie `{webauthn_options}` — à passer tel quel
  à `navigator.credentials.create()` côté client.
- `POST /auth/mfa/confirm` `{method, code}` (totp/email) ou
  `{method: "webauthn", webauthn_response}` (le retour de
  `navigator.credentials.create()`, sérialisé en JSON) — confirme la
  méthode.
- `GET /auth/mfa/methods` → `{available, enabled}`.
- `POST /auth/mfa/request-code` `{pending_token?}` — renvoie un code
  email si le premier a expiré ou n'est jamais arrivé. Marche connecté
  (Bearer, self-service) **ou** en pleine connexion (`pending_token`
  d'intent `"verify"` ou `"enroll"`, sans Bearer) — sinon un code perdu
  bloquerait la connexion sans recours.
- `DELETE /auth/mfa/{method}`.

Toutes ces routes marchent connecté (Bearer token, self-service) — et
`setup`/`confirm`/`methods` marchent AUSSI sans Bearer, avec un
`pending_token` d'intent `"enroll"` à la place, pour l'inscription
forcée (voir plus bas).

**Vérification au login** — une fois une méthode confirmée,
`POST /auth/login` ne renvoie plus un token directement : un
`{pending_token, intent: "verify", methods}` à la place (`email`
déclenche l'envoi automatique du code à cet instant). `POST
/auth/mfa/verify` `{pending_token, method, code}` renvoie enfin le
vrai token. Rate-limité comme `/auth/login`.

**WebAuthn — deux allers-retours, pas un code** — contrairement à
TOTP/email, une clé de sécurité ne "saisit" rien : le navigateur
signe un challenge. Un endpoint dédié récupère ce challenge avant de
vérifier la réponse :

1. `POST /auth/mfa/webauthn/login-options` `{pending_token}` →
   `{options}` — à passer à `navigator.credentials.get()`.
2. `POST /auth/mfa/verify` `{pending_token, method: "webauthn",
   webauthn_response}` — le retour de `navigator.credentials.get()`,
   sérialisé en JSON. Renvoie le vrai token.

Une seule clé de sécurité par utilisateur dans cette version (même
limite que TOTP/email — un `MfaMethod` par méthode). `FORGE_WEBAUTHN_RP_ID`
doit être le domaine exact vu par le navigateur (sans port ni schéma —
`localhost` en dev), `FORGE_WEBAUTHN_ORIGIN` l'URL complète servie —
un décalage entre les deux fait échouer toute vérification, côté
navigateur, avant même d'atteindre le serveur.

Protection contre une clé clonée : chaque connexion doit faire
progresser le compteur de signatures de la clé — une signature déjà
utilisée (compteur qui n'avance pas) est refusée.

**Durcissement de sécurité** (porté depuis Rivet v1.3.0) :

- Secret TOTP **chiffré au repos** (`FORGE_APP_KEY`, voir
  `forge/security/crypto.py`) — jamais en clair en base. Une migration
  rechiffre automatiquement un secret créé par une version antérieure.
  Change `FORGE_APP_KEY` = tous les secrets TOTP existants deviennent
  indéchiffrables, à garder stable.
- **Anti-rejeu TOTP** : un code déjà accepté est refusé, même encore
  valide dans sa fenêtre de tolérance — sans ça, un code intercepté
  reste utilisable une deuxième fois pendant ~60-90s.
- `FORGE_MFA_MAX_ATTEMPTS` (défaut 5) : au-delà de ce nombre de codes
  faux sur **un même** `pending_token`, il est détruit (retour à un
  login complet) — indépendant du rate-limit par IP, qui ne protège
  pas d'une attaque distribuée sur un seul `pending_token` compromis.
- Impossible de désactiver sa dernière méthode confirmée
  (`DELETE /auth/mfa/{method}`) tant que `FORGE_MFA_FORCE_ENROLLMENT=1`
  — sinon on pourrait se soustraire soi-même à une obligation MFA.
  `FORGE_MFA_FORCE_DISABLE_PERMISSION` lève ce garde-fou pour qui la
  détient (ex. un rôle support) — vide par défaut, garde-fou absolu.

**Tester avec une vraie clé (Yubikey...)** : http://localhost:8000/webauthn-test
— page servie par l'app elle-même (nécessaire : l'origine doit
correspondre exactement à `FORGE_WEBAUTHN_ORIGIN`, ouvrir le fichier
en local ne marcherait pas). Connexion, puis un bouton pour enregistrer
la clé, un bouton pour se reconnecter avec. Dev uniquement — à retirer
avant un déploiement en prod. Pour tester sans navigateur ni clé
physique (CI, etc.) : `tests/webauthn_helpers.py`, un authentificateur
logiciel avec de vraies signatures EC, utilisé par la suite pytest.

**Inscription forcée** (`FORGE_MFA_FORCE_ENROLLMENT=1`) — si le compte
n'a AUCUNE méthode confirmée, le login renvoie
`{pending_token, intent: "enroll", methods: <disponibles>}` au lieu
d'un token. Le client appelle alors `setup`/`confirm` en passant ce
`pending_token` dans le body (pas de Bearer, l'utilisateur n'est pas
encore connecté) — confirmer la méthode **complète la connexion** et
renvoie directement `{confirmed: true, token: {...}}`, pas besoin d'un
`/verify` séparé après. Voir `bruno/MFA/*(forced enrollment).bru`.

`FORGE_MFA_METHODS` (par défaut `totp,email,webauthn`) limite les
méthodes proposées.

## Reset de mot de passe

Deux routes publiques, rate-limitées comme `/auth/login` :

1. `POST /auth/pwd/forgot` `{email}` → **toujours** la même réponse
   200, que le compte existe ou non (pas d'énumération de comptes —
   même une erreur SMTP n'est jamais remontée, elle révélerait
   l'existence du compte). Pour un compte actif, envoie un email avec
   un lien vers le **front** (`FORGE_FRONTEND_URL` +
   `FORGE_FRONTEND_PWD_RESET_PATH`, ex.
   `http://localhost:5173/reset-password?token=XXX`) — le front affiche
   le formulaire, l'API n'a pas de page HTML pour ça.
2. `POST /auth/pwd/reset` `{token, password}` (8 caractères min.) →
   change le mot de passe.

Règles :

- **Un seul lien actif par compte** : une nouvelle demande invalide
  l'ancienne (`forgot` deux fois de suite, seul le dernier email
  fonctionne).
- **Usage unique** : un reset réussi supprime le lien — et tout autre
  lien encore en attente pour ce compte.
- **Expiration** `FORGE_PWD_RESET_TOKEN_TTL_MINUTES` (60 par défaut),
  vérifiée en comparant la date complète, pas seulement les minutes
  restantes (un lien expiré depuis quelques secondes est refusé).
- **Sessions révoquées** (`FORGE_PWD_RESET_REVOKES_SESSIONS=1`, défaut)
  : toutes les sessions ouvertes du compte (tokens d'accès) sont
  invalidées au reset — un mot de passe compromis ne doit pas laisser
  une session déjà ouverte ailleurs valide après coup.
- **Le reset ne connecte pas et ne contourne jamais le MFA** : le
  login qui suit passe par la vérification MFA confirmée, comme
  d'habitude.
- Token stocké **haché** (SHA-256), jamais en clair en base — comme
  les tokens d'accès.

Nettoyage : les liens expirés sont supprimés chaque nuit à 3h par le
planificateur (voir "Tâches planifiées"). `make prune` le fait à la
demande.

## Tâches planifiées

Un planificateur déclaratif, à la `schedule:run` de Laravel : les
tâches sont déclarées **à un seul endroit** (`example_app/schedule.py`),
un runner dédié les exécute à la bonne minute.

```python
schedule = Schedule(get_settings().scheduler_timezone)

schedule.task(
    "prune-password-reset-tokens",   # nom (unique)
    "0 3 * * *",                     # cron : tous les jours à 3h
    password_reset.purge_expired,    # fonction async ou sync
    "Supprime les liens de reset expirés",
)
```

Cron 5 champs (`minute heure jour-du-mois mois jour-de-semaine`) :
`*`, listes (`1,15`), intervalles (`9-17`), pas (`*/5`, `0-30/10`),
alias `@hourly` `@daily` `@weekly` `@monthly` `@yearly`. Jour-du-mois
**et** jour-de-semaine renseignés : l'un OU l'autre suffit (comme le
cron classique). Une expression invalide plante **au démarrage**, pas
à 3h du matin. Le fuseau est `FORGE_SCHEDULER_TIMEZONE` (`UTC` par
défaut) : `0 3 * * *` veut dire 3h dans ce fuseau, heure d'été comprise.

```bash
make schedule-list   # les tâches et leur prochaine exécution
make schedule-run    # exécute les tâches dues à cette minute, puis sort
```

**En continu** : le conteneur `scheduler` (dans les deux compose)
lance `python scripts/schedule.py work` — il se réveille à chaque
minute. **Une seule instance, jamais plusieurs** : chaque instance
exécuterait chaque tâche. Il est séparé de l'API exprès : avec
plusieurs workers uvicorn, un planificateur intégré à l'API
s'exécuterait une fois par worker. Logs : `make logs SERVICE=scheduler`.
En dev, `docker compose restart scheduler` après avoir modifié une
tâche (pas de rechargement à chaud).

**Sans processus permanent** : `python scripts/schedule.py run`
toutes les minutes par un cron système ou un CronJob Kubernetes fait
la même chose.

Comportements à connaître :

- Une tâche qui plante est loguée et n'empêche **ni les autres ni le
  runner**.
- Une tâche encore en cours à sa prochaine échéance est **ignorée**
  (pas de chevauchement de la même tâche) — dans un même runner ; deux
  processus `run` simultanés ne se protègent pas entre eux.
- Au démarrage, la minute en cours est **sautée** : redémarrer le
  runner à 03:00:30 ne relance pas les tâches de 03:00.
- `SIGTERM` (arrêt Docker) : le runner attend la fin des tâches en
  cours avant de sortir.
- Pas d'historique en base : seuls les logs gardent la trace des
  exécutions.

## Auth / RBAC

`POST /auth/login` (`{"login": "...", "password": "..."}`) renvoie un
token Bearer à passer en `Authorization: Bearer <token>` sur les
routes protégées. `GET /auth/me` et `POST /auth/logout` s'en servent.

**Chaque route doit déclarer explicitement sa politique d'accès** —
`permission="XXX"`, `public=True` ou `authenticated_only=True` — sinon
l'app refuse de démarrer (`RouteAuthorizationError`). C'est la
correction directe d'un point relevé sur Rivet : là-bas, une route
sans permission enregistrée est ouverte à tout utilisateur
authentifié, en silence. Ici, oublier la décision fait planter l'app
au démarrage plutôt que de laisser une route ouverte sans le savoir.

`/auth/login` est limité à 5 tentatives/minute par IP (429 au-delà) —
en mémoire pour cette v1, donc pas fiable en multi-worker/multi-
instance sans passer sur un backend partagé (Redis). Voir
`forge/security/rate_limit.py`.

**Créer les permissions en base** — `permission="BOOKS_DELETE"` dans
le code ne crée rien tout seul, il faut une ligne `Permission` en
base pour qu'un rôle puisse l'obtenir. `make permissions` scanne
toutes les routes (`ControllerRouter.declared_permissions`) et crée
les permissions manquantes — équivalent de `rightsmanagement
--action=create-permissions` côté Rivet. Jamais d'assignation à un
rôle automatique (ça reste volontairement manuel) : `make grant
role=ADMIN permission=BOOKS_DELETE` la donne à un rôle. `make seed`
l'appelle déjà et donne toutes les permissions **existant à ce
moment-là** au rôle ADMIN créé — celles créées après doivent lui être
données avec `make grant`.

**Créer d'autres rôles et utilisateurs** — `make create-role
uid=EDITOR name="Éditeur" permissions=BOOKS_DELETE` et `make
create-user login=carol email=carol@exemple.fr role=EDITOR` (sans
`password=`, un mot de passe est généré et affiché une seule fois).
`scripts/create_user.py --file users.csv` pour en créer plusieurs
d'un coup (colonnes `login,email,password,role`). Équivalent de
`rightsmanagement --action=create-role|create-user|create-users` côté
Rivet — en trois commandes distinctes plutôt qu'un seul flag
`--action=`.

`make seed` crée un admin de test (`admin` / `changeme`). Les
identifiants se règlent avec `FORGE_ADMIN_LOGIN`, `FORGE_ADMIN_EMAIL`,
`FORGE_ADMIN_PASSWORD` — indispensable en production (`make
prod-seed`), où le mot de passe n'est jamais affiché dans les logs.

## Migrations (Alembic)

`create_all` a disparu de `main.py` — le schéma vient d'Alembic. `make
seed` applique les migrations automatiquement avant de créer l'admin
(via `scripts/seed.py`), donc le quickstart plus haut n'a rien à
changer.

```bash
make migrate                        # applique les migrations en attente
make migration name="add isbn"      # autogenerate depuis les modèles modifiés
make migrate-down                   # annule la dernière migration
```

`alembic/env.py` prend `DATABASE_URL` sur `forge.config` (donc `.env`
ou l'override Docker), jamais sur `alembic.ini` — une seule source de
vérité. Testé avec de vraies données : ajouter une colonne à `Book`,
générer, appliquer — la ligne existante survit avec la colonne à
`NULL` ; `downgrade` la retire proprement, sans perte de données.
`create_all` ne fait ça sur aucune base qui a déjà ses tables.

## Config

Toute la config passe par `forge/config.py` (`pydantic-settings`),
jamais d'`os.environ.get()` ailleurs dans le code — même principe que
les `config/*.php` de Rivet. Variables lues depuis `.env` (copie de
`.env.example`), avec les vraies variables d'environnement qui
l'emportent toujours sur le fichier (utile pour les overrides Docker,
voir `docker-compose.yml`).

## Créer un CRUD sans écrire de code (make:crud)

```bash
make crud name=tag fields="name:str,price:float?,author:fk:authors"
```

Génère `models/tag.py`, `repositories/tag.py`, `controllers/tag.py`
et câble `/tags` dans `routes.py` automatiquement (accès :
connexion requise, pas de permission fine par défaut — à resserrer
si besoin, comme pour `Book`).

- **Table déjà en base** : `make crud name=category table=categories`
  — les champs sont repris de la vraie table (types, nullable, clés
  étrangères), rien à ressaisir.
- **Table inexistante** : `fields="name:type,..."`, types
  `str`/`text`/`int`/`float`/`bool`/`datetime` (ajouter `?` pour
  nullable, ex. `price:float?`), `champ:fk:table[?]` pour une
  relation N-1 (`?` = 0-N, optionnelle), `champ:m2m:table` pour une
  relation N-N (génère la table d'association). Sans `fields=`,
  saisie interactive champ par champ (`make crud name=tag`).
- `id`/`created_at`/`updated_at`/`deleted_at` ne sont jamais demandés
  — déjà fournis par `TimestampMixin`.
- Le nom de table est déduit du nom de ressource au pluriel anglais
  courant (`tag` → `tags`, `category` → `categories`, `box` →
  `boxes`) — `table=` pour un pluriel vraiment irrégulier
  (`child`/`children`...).
- **Une migration reste à générer après coup** (`make migration
  name="add tags"` puis `make migrate`) — le générateur écrit le
  code, pas le schéma en base.
- N-N : attacher/détacher une relation many-to-many n'a pas
  d'endpoint généré (au-delà du CRUD de base) — manipuler la table
  d'association directement, ou ajouter une action dédiée au
  Controller.

Les fichiers générés sont du code Forge normal, comme `Author`/`Note`
— à ouvrir et modifier ensuite si un besoin dépasse le CRUD de base
(surcharger une méthode, resserrer une permission…), exactement comme
`BookController` l'a fait.

Envie de voir ce qu'il y a derrière (sans le générateur) ?
[`docs/INTEGRATION.md`](docs/INTEGRATION.md) construit la même chose
à la main, étape par étape. Pour le détail complet de `?filters=`,
`?sort=`, `?with=` : [`docs/FILTERS.md`](docs/FILTERS.md).

## Scoping utilisateur

`Repository.owner_column = "user_id"` restreint list/show/edit/delete
aux lignes de l'utilisateur connecté — jamais implicite (contrairement
à Rivet, qui scope dès qu'une colonne du bon nom existe). Voir
`example_app/repositories/note.py` : une ligne suffit, tout le reste
(create assigne l'owner, update/delete refusent sur une ligne d'un
autre owner) est dans `BaseRepository`.

Pour outrepasser (équivalent du `AUTH_UNLIMITED` de Rivet) : l'action
`list_all` de `BaseController` ignore le scoping, à câbler sur sa
propre route avec une permission dédiée — jamais avec
`public=`/`authenticated_only=` seuls. Voir `GET /notes/all` dans
`example_app/routes.py` (permission `NOTES_ADMIN`). Volontairement
une route séparée plutôt qu'un comportement caché de `GET /notes/` :
même endpoint, deux résultats différents selon le rôle, c'est le genre
de piège qu'on veut éviter.

## Logs & audit (`Loggable`)

Deux choses distinctes, à ne pas confondre :

- **Logs applicatifs** (`logging.getLogger("forge.<module>")`, rien de
  spécial à apprendre) — erreurs, stack traces, événements. Pas de
  table pour ça par défaut : `FORGE_LOG_BACKEND=file` (défaut) écrit
  dans `storage/logs/forge.log`, rotatif (5 Mo x 5,
  `FORGE_LOG_DIR`/`FORGE_LOG_MAX_BYTES`/`FORGE_LOG_BACKUP_COUNT`).
  Toute exception non gérée y part avec sa stack trace complète — le
  client ne voit jamais qu'un 500 générique (`forge/errors.py`).
  `FORGE_LOG_BACKEND=mongo` bascule vers une collection MongoDB à la
  place (`FORGE_LOG_MONGO_URL`/`_DB`/`_COLLECTION`) — un document par
  ligne de log (`timestamp`, `level`, `logger`, `message`, `traceback`
  si présent). Le client Mongo (pymongo) est synchrone — s'il est
  injoignable, le log est perdu plutôt que de faire planter l'app.
  Voir `forge/logs.py`.

- **Audit des modèles** (`Repository.loggable = True`, voir
  `BookRepository`) — journalise create/update/delete dans la table
  `activity_log` **et** le fichier de log : modèle, id, action,
  `actor_id` (l'utilisateur qui a fait l'action — pas forcément le
  propriétaire de la ligne), et les champs changés en JSON. Rien à
  hériter en plus — juste l'attribut sur le Repository. Voir
  `forge/audit.py` et `docs/SCHEMA.md` pour la structure de la table.

## i18n

`forge/i18n/locales/*.json` (clé plate -> chaîne), résolu via
`trans(key, locale)`. La locale de la requête vient de
`Accept-Language` (`LocaleMiddleware`, `request.state.locale`) —
repli sur `FORGE_DEFAULT_LOCALE` si absent/non supporté. Clé manquante
= repli sur la locale par défaut, puis sur la clé elle-même — jamais
d'erreur. Voir `AuthController.login` pour l'usage sur une réponse
HTTP, `scripts/seed.py` pour un usage direct (hors requête).

## Mailing

`forge/mail/base.py` (`BaseMail`) : un layout global
(`templates/layout.html`, couleur de marque via `FORGE_BRAND_COLOR`)
et un micro-template par email (`templates/welcome.html` en exemple),
Jinja2, envoyé en SMTP async (`aiosmtplib`) — même découpage que
`Mail\BaseMail` + `layout.blade.php` côté Rivet.

En Docker, [Mailpit](https://github.com/axllent/mailpit) capture tout
— rien ne part jamais vers un vrai serveur mail en dev. Interface web :
http://localhost:8025. `make seed` envoie un email de bienvenue à
l'admin créé, visible immédiatement là-dedans.

## Stockage de fichiers

`POST /files/` (multipart, champ `file`) → upload direct. Chaque
fichier appartient à celui qui l'a envoyé (même principe que le
scoping `owner_column` des Notes, appliqué à la main ici) — un
utilisateur ne voit/télécharge/supprime que ses propres fichiers.

- `GET /files/{id}` — **un seul endpoint, deux réponses selon
  l'état** : upload en cours -> statut JSON (`received_bytes`/
  `total_bytes`) ; upload terminé -> le fichier en ligne
  (`Content-Disposition: inline`, une image ou un PDF s'affiche
  directement dans le navigateur).
- `GET /files/{id}/download` — **téléchargement forcé**
  (`Content-Disposition: attachment`) : pour tout le reste (Excel,
  Word...), que le navigateur ne peut de toute façon pas afficher.
  Refusé tant que l'upload n'est pas terminé.
- `GET /files/` — liste ; `DELETE /files/{id}`.

Types acceptés par défaut : images (png/jpeg/gif/webp), PDF, Word
(doc/docx), Excel (xls/xlsx), texte/CSV — `FORGE_STORAGE_ALLOWED_TYPES`
pour ajuster. `FORGE_STORAGE_MAX_BYTES` (25 Mo par défaut) pour la
taille max.

Le nom réel sur disque est un UUID opaque (`storage_key`), jamais le
nom du fichier envoyé par le client — élimine toute la classe de bugs
"path traversal via le nom de fichier" sans avoir à assainir quoi que
ce soit.

En Docker, `storage/` est monté en volume (`./storage:/app/storage`)
— sans ça, un `make down` supprimerait les fichiers uploadés avec le
conteneur.

### Upload par chunks (fichiers volumineux, reprise après coupure)

Pour un envoi direct (`POST /files/`), `UploadFile` de Starlette
bascule déjà sur disque au-delà d'une petite taille en mémoire — pas
besoin de chunker pour l'efficacité. L'upload par chunks sert un
besoin différent : la **résilience** sur un gros fichier (reprendre
après une coupure sans tout renvoyer) et une éventuelle barre de
progression côté client.

Même `StorageFile` du début à la fin — pas de table à part, pas de
bascule d'id entre le démarrage et la fin de l'upload :

1. `POST /files/start` `{filename, content_type, total_bytes}` →
   `{id, received_bytes: 0, completed_at: null, ...}`
2. `PUT /files/{id}` avec le morceau en corps brut (pas de multipart)
   — autant de fois que nécessaire, dans l'ordre. Renvoie
   `received_bytes` à jour à chaque appel.
3. `GET /files/{id}` à tout moment pour savoir où reprendre après une
   coupure (`received_bytes`) — le client ne renvoie que ce qui
   manque.
4. `POST /files/{id}/complete` une fois `received_bytes ==
   total_bytes` → `completed_at` posé, même id, utilisable ensuite
   comme n'importe quel fichier. Refusé (400) si incomplet.

Taille max d'un chunk : `FORGE_STORAGE_CHUNK_SIZE` (1 Mo par défaut,
413 au-delà) — renvoyée dans `max_chunk_size` à chaque réponse, pour
que le client sache comment découper. Sans cette limite, un client
pourrait envoyer tout le fichier en un seul "chunk" et défaire
l'intérêt du chunking (le serveur le chargerait entièrement en
mémoire d'un coup).

Chunks toujours ajoutés en fin de fichier, jamais à un offset
arbitraire — plus simple qu'un vrai upload parallèle multi-chunks,
suffisant pour la reprise séquentielle.

## Déploiement

Le `Dockerfile`/`docker-compose.yml` par défaut sont pour le dev
(`--reload`, code monté en volume, Mailpit, Adminer). Pour un vrai
déploiement : `Dockerfile.prod` (image deux étapes, utilisateur
non-root, sans les dépendances de test) et `docker-compose.prod.yml`
(pas de bind-mount sur le code, pas d'outils de dev). Détail complet,
secrets, HTTPS, limite du worker unique : `docs/DEPLOYMENT.md`.

## Lancer sans Docker

```bash
pip install -r requirements-dev.txt   # requirements.txt seul si tests non nécessaires
uvicorn example_app.main:app --reload
python scripts/seed.py
```

Utilise SQLite (`./forge.db`) par défaut hors Docker. Force Postgres ou
toute autre base via la variable d'environnement `DATABASE_URL`.

## Tests automatisés

```bash
make test
# ou hors Docker : pytest
```

185 tests, base SQLite dédiée (`test.db`, recréée avant chaque test —
jamais la même que `forge.db`), emails interceptés (pas besoin de
Mailpit qui tourne). Couvre auth (login, rate-limit, i18n des
messages), RBAC (refus de démarrage sans décision d'autorisation,
permissions), CRUD générique (filtres, tri, `?with=`, mass-delete
sécurisé, pagination), scoping utilisateur (isolation, bypass admin),
MFA (TOTP avec de vrais codes `pyotp` et anti-rejeu, email avec code
intercepté et relu, **WebAuthn avec une vraie clé de sécurité
logicielle** — signatures EC réelles, vérifiées par `python-fido2`, y
compris le rejet d'une signature rejouée), stockage de fichiers
(upload direct et par chunks), logs (fichier et Mongo),
synchronisation des permissions, reset de mot de passe (anti-énumération,
lien à usage unique, expiration, révocation des sessions) et l'enveloppe
de réponse standard, et le planificateur (expressions cron, fuseaux, tâche
en échec, chevauchement, arrêt propre), et les emails (encodage UTF-8,
logo intégré, couleur de marque personnalisable).

## Intégration continue

`.github/workflows/ci.yml` — quatre jobs, à chaque push et pull request :

- **lint** — `pyflakes`.
- **test-sqlite** — les 174 tests, sur la base SQLite par défaut.
- **test-postgres** — les mêmes tests, contre un vrai Postgres (service
  GitHub Actions), puis un aller-retour complet des migrations
  (`upgrade head` / `downgrade base`). **Utile pour de vrai, pas
  symbolique** : c'est en construisant ce job qu'un filtre sur une
  colonne entière (`?filters=year:eq(1965)`) s'est révélé planter sur
  Postgres tout en étant silencieux sur SQLite (Postgres est typé
  strictement, SQLite ne l'est pas) — corrigé avant que la CI existe,
  mais ça ne se serait jamais vu sans elle. `forge/db.py` désactive le
  pool de connexions en test (`FORGE_DB_POOL=null`, posé par
  `tests/conftest.py`) : `asyncpg` refuse qu'une connexion change de
  boucle d'événements d'un `asyncio.run()` à l'autre — un souci de test
  uniquement, jamais en production (une seule boucle, en continu, chez
  uvicorn).
- **docker-build** — que `Dockerfile` et `Dockerfile.prod` construisent
  toujours, sans plus.

Deux bugs trouvés par la suite en l'écrivant : quatre tests
`mass_delete` échouaient à cause de mon propre setup de test (pas de
la permission `BOOKS_DELETE`), et l'extraction du code depuis l'email
capturé échouait sur un message multipart (`get_content()` direct ne
marche pas dessus, il faut `get_body(preferencelist=("html",))`).

## Tester avec Bruno

Le dossier `bruno/` est une collection [Bruno](https://www.usebruno.com/)
prête à l'emploi :

1. Ouvrir Bruno → "Open Collection" → sélectionner le dossier `bruno/`
2. Choisir l'environnement **local** (en haut à droite) — pointe sur
   `http://localhost:8000`
3. Lancer `Auth/Login` — stocke automatiquement le token dans une
   variable de collection, réutilisée par toutes les autres requêtes
   (auth Bearer déjà configurée dessus)
4. `Authors/Create author` (récupère l'`id` retourné), puis
   `Books/Create book` en renseignant cet `id` comme `author_id`
5. Les autres requêtes du dossier `Books/` couvrent le CRUD complet,
   ainsi que des cas volontairement en échec qui démontrent les
   corrections apportées par rapport à Rivet : `?filters=` sur une clé
   non déclarée → 400, `mass_delete` sans `ids`/`confirm` → 400, et
   `Books/Delete book` échoue en 403 si le compte connecté n'a pas la
   permission `BOOKS_DELETE` (seul `admin`, via le seed, l'a).

## Structure

```
forge/                  # le framework
  routing.py             # ControllerRouter (Route::controller()->group())
                          # + politique d'accès obligatoire par route
  controllers/base.py     # BaseController (résolution Repository par convention)
  repositories/base.py    # CRUD générique + DSL de filtres/tri/includes
  query_context.py        # QueryContext porté par la requête
  middleware/query_string.py  # parse ?filters=/?sort=/?with=
  errors.py                # exceptions internes -> réponses JSON propres
  db.py, models/base.py    # SQLAlchemy async
  security/                 # auth, RBAC, rate-limiting, MFA
    models.py                 # User, Role, Permission, AccessToken, MfaMethod, MfaPendingToken
    mfa.py, mfa_controller.py  # TOTP/email, tokens pending
    passwords.py, tokens.py    # bcrypt, tokens opaques hashés
    dependencies.py             # get_current_user, require_permission
    rate_limit.py                # throttling en mémoire (dev)
    auth_controller.py, routes.py # /auth/login, /logout, /me
  i18n/                      # trans(), locales/*.json
  mail/                      # BaseMail, templates/layout.html + micro-templates
  storage/                   # upload, vue en ligne/téléchargement, StorageFile
  generator/                 # introspection de table + génération de code (make:crud)
  audit.py                  # ActivityLog — trait Loggable (create/update/delete)
  logs.py                   # setup_logging() — storage/logs/forge.log
  config.py                 # Settings centrale (pydantic-settings, .env)

alembic/                  # migrations (env.py importe example_app.routes -> tous les modèles)

example_app/             # une app d'exemple, quatre ressources
  models/book.py           # Author, Book (SQLAlchemy)
  models/note.py            # Note — user_id, exemple de scoping par utilisateur
  repositories/            # BookRepository (loggable), AuthorRepository, NoteRepository
  controllers/              # BookController (typé Pydantic), Author/Note (génériques)
  schemas/book.py            # BookCreate/BookUpdate/BookRead/BookList
  routes.py, main.py

scripts/seed.py           # migre + sync les permissions + crée l'admin + envoie l'email de bienvenue
scripts/sync_permissions.py # crée les permissions manquantes depuis les routes
scripts/grant_permission.py # donne une permission à un rôle (make grant)
scripts/create_role.py     # crée un rôle (make create-role)
scripts/create_user.py      # crée un utilisateur, ou plusieurs depuis un CSV (make create-user)
scripts/prune_expired_tokens.py # supprime les liens de reset expirés (aussi planifié chaque nuit)
scripts/schedule.py         # runner des tâches planifiées (list / run / work)
scripts/make_crud.py       # génère un CRUD (existant ou nouveau) — voir plus haut
tests/                    # suite pytest (auth, RBAC, CRUD, scoping, MFA, storage, i18n)
bruno/                   # collection de test HTTP
docs/SCHEMA.md            # schéma de la base (Mermaid, rendu par GitHub)
docs/FILTERS.md            # référence complète du DSL filtres/tri/includes
docs/RESPONSES.md           # forme standard des réponses (succès/erreur/pagination)
Dockerfile / Dockerfile.prod    # image dev (--reload) / image de prod (deux étapes, non-root)
docker-compose.yml / .prod.yml   # stack dev (Mailpit/Adminer) / stack de référence pour déployer
.github/workflows/ci.yml    # lint, tests (SQLite + Postgres), build Docker
requirements.txt / requirements-dev.txt   # dépendances runtime / + pytest/httpx/mongomock
docs/INTEGRATION.md         # créer une ressource à la main, from-scratch
```
