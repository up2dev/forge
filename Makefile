.PHONY: up start down stop restart build logs ps sh sh-db test seed migrate migration migrate-down crud permissions grant create-role create-user prune schedule-list schedule-run clean tidy prod-up prod-down prod-restart prod-logs prod-migrate prod-seed prod-sh

PROD = docker compose -f docker-compose.prod.yml --env-file .env.prod

# Démarre en arrière-plan (build si besoin). Usage courant au quotidien.
up:
	docker compose up -d --build

# Alias explicite de `up`, sans rebuild forcé — plus rapide quand rien
# n'a changé dans requirements.txt/Dockerfile.
start:
	docker compose up -d

# Arrête les conteneurs SANS les supprimer (état/volumes conservés).
stop:
	docker compose stop

# Arrête ET supprime les conteneurs (les volumes nommés, donc les
# données Postgres, sont conservés — voir `clean` pour tout raser).
down:
	docker compose down

restart:
	docker compose restart

# Rebuild explicite de l'image (après un changement de
# requirements.txt ou du Dockerfile).
build:
	docker compose build

# Logs suivis en direct de tous les services, ou d'un seul :
# make logs SERVICE=api
logs:
	docker compose logs -f $(SERVICE)

ps:
	docker compose ps

# Shell dans le conteneur api (débogage, lancer une commande ponctuelle).
sh:
	docker compose exec api bash

# psql direct dans le conteneur Postgres.
sh-db:
	docker compose exec db psql -U forge -d forge

test:
	docker compose exec api pytest

# Crée l'utilisateur admin (par défaut admin / changeme, réglable avec
# FORGE_ADMIN_LOGIN / _EMAIL / _PASSWORD) avec le rôle ADMIN — idempotent,
# ne fait rien s'il existe déjà.
seed:
	docker compose exec api python scripts/seed.py

# Applique les migrations en attente (alembic upgrade head).
migrate:
	docker compose exec api alembic upgrade head

# Génère une migration par autogenerate : make migration name="add isbn to books"
migration:
	docker compose exec api alembic revision --autogenerate -m "$(name)"

# Annule la dernière migration appliquée.
migrate-down:
	docker compose exec api alembic downgrade -1

# Génère un CRUD sans passer par make sh :
#   make crud name=tag fields="name:str,price:float"
#   make crud name=category table=categories   (table déjà en base, introspection)
#   make crud name=tag                          (aucun champ -> saisie interactive)
crud:
	docker compose exec api python scripts/make_crud.py $(name) $(if $(fields),--fields "$(fields)") $(if $(table),--table $(table))

# Scanne les routes (permission=...) et crée les permissions
# manquantes en base — équivalent rightsmanagement de Rivet. `make
# seed` l'appelle déjà pour l'admin ; utile seul après avoir ajouté
# une permission à une route existante.
permissions:
	docker compose exec api python scripts/sync_permissions.py

# Crée un rôle, permissions optionnelles :
#   make create-role uid=EDITOR name="Éditeur" permissions=BOOKS_DELETE,NOTES_ADMIN
create-role:
	docker compose exec api python scripts/create_role.py "$(uid)" "$(name)" $(if $(permissions),--permissions "$(permissions)")

# Crée un utilisateur, rôle optionnel — sans password=, un mot de passe
# est généré et affiché une seule fois :
#   make create-user login=carol email=carol@exemple.fr role=EDITOR
create-user:
	docker compose exec api python scripts/create_user.py "$(login)" "$(email)" $(if $(password),--password "$(password)") $(if $(role),--role "$(role)")

# Donne une permission à un rôle (l'attribution n'est jamais automatique) :
#   make grant role=ADMIN permission=TAGS_DELETE
grant:
	docker compose exec api python scripts/grant_permission.py $(role) $(permission)

# Supprime les liens de reset de mot de passe expirés — à planifier
# en cron côté hébergement (voir scripts/prune_expired_tokens.py).
prune:
	docker compose exec api python scripts/prune_expired_tokens.py

# Tâches planifiées (example_app/schedule.py) : elles tournent toutes seules
# dans le conteneur `scheduler` (logs : make logs SERVICE=scheduler).
schedule-list:
	docker compose exec api python scripts/schedule.py list

# Exécute les tâches dues à cette minute, puis sort.
schedule-run:
	docker compose exec api python scripts/schedule.py run

# Supprime aussi les volumes nommés (les données Postgres) — destructif,
# à utiliser pour repartir d'une base totalement vierge.
clean:
	docker compose down -v

# Dégage les fichiers parasites qui n'ont rien à faire dans le repo :
# artefacts Windows/WSL (*:Zone.Identifier, Thumbs.db), macOS
# (.DS_Store), et le cache Python local si tu bosses hors Docker.
tidy:
	find . -name "*Zone.Identifier*" -delete
	find . -name ".DS_Store" -delete
	find . -name "Thumbs.db" -delete
	find . -name "__pycache__" -type d -exec rm -rf {} +
	find . -name "*.pyc" -delete
	rm -f forge.db test.db

# ------------------------------------------------------------------
# Déploiement (docker-compose.prod.yml — voir docs/DEPLOYMENT.md)
# ------------------------------------------------------------------

# Construit et démarre la stack de prod. Exige .env.prod (jamais
# commité, voir .env.example) — message clair plutôt qu'une erreur
# Docker cryptique s'il manque.
prod-up:
	@test -f .env.prod || (echo "Manquant : .env.prod (cp .env.example .env.prod, puis éditer les vrais secrets)" && exit 1)
	$(PROD) up -d --build

prod-down:
	$(PROD) down

prod-restart:
	$(PROD) restart

# Logs de la stack de prod, ou d'un seul service : make prod-logs SERVICE=api
prod-logs:
	$(PROD) logs -f $(SERVICE)

# Migrations en prod — jamais automatique au démarrage du conteneur,
# un seul appel explicite (voir docs/DEPLOYMENT.md).
prod-migrate:
	$(PROD) exec api alembic upgrade head

# Crée le premier admin en prod (identifiants : FORGE_ADMIN_* dans .env.prod).
prod-seed:
	$(PROD) exec api python scripts/seed.py

prod-sh:
	$(PROD) exec api bash
