from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse

from forge.errors import register_error_handlers
from forge.logs import setup_logging
from forge.middleware.envelope import ResponseEnvelopeMiddleware
from forge.middleware.locale import LocaleMiddleware
from forge.middleware.query_string import QueryStringMiddleware

from example_app.routes import ALL_ROUTERS

setup_logging()

_ASSETS_DIR = Path(__file__).parent.parent / "docs" / "assets"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Le schéma vient des migrations Alembic (`alembic upgrade head`,
    # ou `make migrate`) — plus de create_all ici. Un schéma qui existe
    # seulement parce que l'app vient de démarrer ne survit à aucune
    # évolution réelle (ajouter une colonne à un modèle ne fait rien
    # sur une base qui a déjà ses tables).
    yield


# docs_url/redoc_url désactivés ici, recréés juste en dessous — la
# seule façon de leur passer une favicon perso plutôt que celle de
# FastAPI par défaut.
app = FastAPI(title="Forge example app", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(QueryStringMiddleware)
app.add_middleware(LocaleMiddleware)
# Ajouté en dernier -> englobe tous les autres middlewares et leurs
# erreurs (voir forge/middleware/envelope.py).
app.add_middleware(ResponseEnvelopeMiddleware)
register_error_handlers(app)


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return FileResponse(_ASSETS_DIR / "logo.svg", media_type="image/svg+xml")


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url=app.openapi_url, title=f"{app.title} — Swagger", swagger_favicon_url="/favicon.svg"
    )


@app.get("/redoc", include_in_schema=False)
async def redoc():
    return get_redoc_html(
        openapi_url=app.openapi_url, title=f"{app.title} — Redoc", redoc_favicon_url="/favicon.svg"
    )


@app.get("/health")
async def health():
    """Sonde de santé pour un load balancer/orchestrateur — jamais
    authentifiée, ne touche pas la base. Ajoutée directement sur
    l'app (pas via ControllerRouter) : une sonde d'infra doit rester
    accessible même si l'auth ou la base a un problème."""
    return {"status": "ok"}


@app.get("/webauthn-test", response_class=HTMLResponse)
async def webauthn_test_page():
    """Page de test WebAuthn — pour tester avec une vraie clé de
    sécurité (Yubikey...) depuis un navigateur, plutôt qu'avec
    l'authentificateur logiciel utilisé par la suite pytest.
    Dev uniquement — à retirer avant un déploiement en prod (voir
    docs/DEPLOYMENT.md) ; elle n'expose rien de plus que ce que /docs
    permet déjà de faire à la main, mais autant ne pas la laisser
    traîner publiquement."""
    return (Path(__file__).parent / "webauthn_test.html").read_text()


for router in ALL_ROUTERS:
    app.include_router(router.router)
