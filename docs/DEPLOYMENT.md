# Guide de déploiement

Ce que le mode dev (`docker-compose.yml`, `Dockerfile`) fait exprès de
simplifier, et qu'il faut reprendre en main pour un vrai déploiement.

## Ce qui change

| | Dev | Prod |
|---|---|---|
| Image | `Dockerfile` | `Dockerfile.prod` — deux étapes, sans `build-essential` dans l'image finale, utilisateur non-root |
| Dépendances | `requirements-dev.txt` (+ pytest/httpx/mongomock) | `requirements.txt` seul |
| Code | monté en volume, `--reload` | figé dans l'image au build, pas de `--reload` |
| Secrets | `.env` commité (valeurs de dev, sans conséquence) | jamais commités — voir plus bas |
| Outils annexes | Mailpit, Adminer | aucun des deux — un vrai SMTP, un accès base par un outil tiers dédié |

`docker-compose.prod.yml` assemble tout ça pour un déploiement à un
seul serveur. Pour un orchestrateur (Kubernetes, ECS...), les mêmes
principes s'appliquent — seule la mécanique de déploiement change.

## Secrets

`.env` (dev) reste dans le dépôt : ses valeurs (`forge`/`forge`,
`changeme`...) n'ont aucune conséquence en local. Pour la prod, un
fichier séparé, **jamais commité** :

```bash
cp .env.example .env.prod
# éditer .env.prod : vrais mots de passe, vraie clé SMTP, etc.
```

Au minimum à changer : `POSTGRES_PASSWORD` (généré, pas `forge`),
`FORGE_APP_KEY` (`openssl rand -base64 32` — chiffre les secrets TOTP,
à garder : la changer les rend illisibles), `SMTP_*` (un vrai
fournisseur — Mailpit n'existe qu'en dev), `FORGE_FRONTEND_URL`, et le
premier administrateur : `FORGE_ADMIN_LOGIN`, `FORGE_ADMIN_EMAIL` (une
**vraie adresse** : c'est là que part le lien "mot de passe oublié") et
`FORGE_ADMIN_PASSWORD`. `.env.example` liste tout ça dans sa section
"Production uniquement".

## Lancer

```bash
cp .env.example .env.prod   # une fois, puis éditer les vrais secrets
make prod-up                # construit et démarre
make prod-migrate           # applique les migrations
make prod-seed              # crée le premier admin (FORGE_ADMIN_* de .env.prod)
```

Équivalent sans passer par les raccourcis `make` :

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api alembic upgrade head
```

Autres raccourcis : `make prod-logs` (`SERVICE=api` pour un seul
service), `make prod-restart`, `make prod-down`, `make prod-sh` (shell
dans le conteneur). `make prod-up` refuse proprement si `.env.prod`
n'existe pas encore, plutôt qu'une erreur Docker.

Les migrations sont **volontairement** une étape séparée, jamais
automatique au démarrage du conteneur — avec plusieurs instances qui
démarrent en même temps, un `alembic upgrade head` lancé par chacune
en même temps risquerait de se marcher dessus. Un seul appel, avant de
(re)démarrer les instances.

## HTTPS

Le conteneur `api` sert du HTTP brut sur le port 8000 — jamais de TLS
directement dans uvicorn. Un reverse proxy devant (nginx, Caddy,
Traefik, ou le load balancer du fournisseur cloud) termine le HTTPS et
transmet en HTTP à `api`. Hors de portée de ce guide — la config varie
trop d'un fournisseur à l'autre.

## Un seul worker par défaut — pourquoi

`Dockerfile.prod` lance `uvicorn --workers 1`. Deux choses dans le
code sont en mémoire/disque local, pas dans la base :

- **Le rate-limiter** (`forge/security/rate_limit.py`) — un dict en
  mémoire par process. Plusieurs workers (ou plusieurs instances) =
  plusieurs compteurs indépendants, la limite réelle devient floue
  (5 tentatives par worker, pas 5 au total).
- **Les fichiers en cours d'upload par chunks** — écrits sur le disque
  local du conteneur (`storage/files/tmp/`). Un chunk envoyé à
  l'instance A puis un autre reçu par l'instance B (derrière un load
  balancer sans session affinity) ne se retrouveraient jamais sur le
  même disque.

Passer à plusieurs workers ou plusieurs instances demande de résoudre
ces deux points d'abord : un rate-limiter partagé (Redis, `INCR` +
`EXPIRE`, même interface que `rate_limit()` actuelle) et un stockage
de fichiers partagé (disque réseau, ou bascule vers un stockage objet
type S3). Aucun des deux n'est fait dans cette version — un seul
worker reste le choix sûr en attendant.

## Sonde de santé

`GET /health` — jamais authentifiée, ne touche pas la base. Câblée
dans `Dockerfile.prod` (`HEALTHCHECK`) et réutilisable telle quelle
par un load balancer ou Kubernetes (`livenessProbe`/`readinessProbe`).

## Page de test WebAuthn

`GET /webauthn-test` (`example_app/main.py`) sert une page HTML de
test pour enregistrer/utiliser une vraie clé de sécurité depuis un
navigateur — utile en dev, aucune raison de la garder accessible en
prod. À retirer (ou à protéger derrière une permission) avant de
déployer.

## Tâches planifiées

Le service `scheduler` de `docker-compose.prod.yml` exécute les
tâches déclarées dans `example_app/schedule.py` (nettoyage des liens
de reset expirés chaque nuit, par exemple) — même image que `api`,
autre commande (`python scripts/schedule.py work`).

- **Une seule instance, jamais plusieurs** : chaque instance
  exécuterait chaque tâche. Sur Kubernetes, un `Deployment` à
  `replicas: 1` (avec `strategy: Recreate`, pour ne jamais avoir deux
  pods qui se chevauchent pendant une mise à jour) — ou, sans
  processus permanent, un `CronJob` toutes les minutes qui lance
  `python scripts/schedule.py run`.
- **Fuseau** : `FORGE_SCHEDULER_TIMEZONE` (`UTC` par défaut). `0 3 * * *`
  veut dire 3h dans ce fuseau — à régler (`Europe/Paris`...) si "3h du
  matin" doit être l'heure locale.
- **Logs** : `make prod-logs SERVICE=scheduler`. Le conteneur n'a pas le
  volume `storage` exprès (le fichier de log rotatif est celui de
  `api`) : ses logs passent par la console Docker.
- Un déploiement qui modifie `example_app/schedule.py` redémarre le
  service (`make prod-up` reconstruit l'image) : la minute en cours est
  sautée au redémarrage, aucune tâche n'est relancée en double.

## Logs

`FORGE_LOG_BACKEND=file` écrit dans `storage/logs/` **à l'intérieur du
conteneur** — perdu à la destruction du conteneur si ce dossier n'est
pas monté sur un volume persistant (ou mieux, redirigé vers un service
centralisé). `FORGE_LOG_BACKEND=mongo` est l'alternative déjà prête si
une collection MongoDB centralisée existe (voir README, section Logs).
