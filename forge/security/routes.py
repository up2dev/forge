"""
forge.security.routes
======================
Routers auth/MFA prêts à l'emploi. Une app Forge n'a qu'à faire :

    from forge.security.routes import auth_router, mfa_router
    app.include_router(auth_router.router)
    app.include_router(mfa_router.router)

pour obtenir /auth/login, /auth/logout, /auth/me, /auth/mfa/*.
"""
from __future__ import annotations

from typing import Union

from fastapi import Depends

from forge.config import get_settings
from forge.routing import ControllerRouter
from forge.security.auth_controller import AuthController
from forge.security.mfa_controller import MfaController
from forge.security.rate_limit import rate_limit
from forge.security.schemas import MfaPendingResponse, TokenResponse

_settings = get_settings()


def _rate_limited(key: str):
    return Depends(
        rate_limit(key, times=_settings.login_rate_limit_times, seconds=_settings.login_rate_limit_seconds)
    )


auth_router = ControllerRouter(AuthController, prefix="/auth", tags=["auth"])

auth_router.post(
    "/login",
    "login",
    public=True,
    # response_model explicite: TokenResponse | MfaPendingResponse n'est
    # pas un `type` (c'est une union), la détection automatique dans
    # ControllerRouter._response_model ne s'applique qu'aux classes.
    response_model=Union[TokenResponse, MfaPendingResponse],
    dependencies=[_rate_limited("login")],
)
auth_router.post("/logout", "logout", authenticated_only=True)
auth_router.get("/me", "me", authenticated_only=True)

# Reset de mot de passe — publics (l'utilisateur n'est justement pas
# connecté), rate-limités : forgot évite le spam d'emails vers un
# compte, reset limite la devinette de token.
auth_router.post("/pwd/forgot", "forgot_password", public=True, dependencies=[_rate_limited("pwd_forgot")])
auth_router.post("/pwd/reset", "reset_password", public=True, dependencies=[_rate_limited("pwd_reset")])

mfa_router = ControllerRouter(MfaController, prefix="/auth/mfa", tags=["mfa"])

# setup/confirm/methods tournent en public=True au niveau routeur,
# mais ne sont pas ouvertes pour autant : MfaController résout la
# cible via Bearer token (self-service) OU pending_token d'intent
# "enroll" (inscription forcée, pas encore de Bearer) — sans l'un des
# deux, la résolution lève 401 elle-même.
mfa_router.post("/setup", "setup", public=True)
mfa_router.post("/confirm", "confirm", public=True)
mfa_router.get("/methods", "methods", public=True)

mfa_router.post(
    "/request-code",
    "request_email_code",
    public=True,
    dependencies=[_rate_limited("mfa_resend")],
)
mfa_router.post(
    "/webauthn/login-options",
    "webauthn_login_options",
    public=True,
    dependencies=[_rate_limited("mfa_webauthn_login_options")],
)
mfa_router.post("/verify", "verify", public=True, dependencies=[_rate_limited("mfa_verify")])
mfa_router.delete("/{method}", "disable", authenticated_only=True)
