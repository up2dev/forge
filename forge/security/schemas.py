from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    login: str
    password: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    email: str
    is_active: bool


class TokenResponse(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_at: datetime | None
    user: UserRead


class MfaPendingResponse(BaseModel):
    """Renvoyé par /auth/login à la place de TokenResponse quand le
    compte a du MFA confirmé (intent="verify") ou doit en activer un
    faute d'en avoir (intent="enroll", FORGE_MFA_FORCE_ENROLLMENT)."""

    pending_token: str
    intent: str  # "verify" | "enroll"
    methods: list[str]


class MfaSetupRequest(BaseModel):
    method: str
    # Fournir un secret existant (token matériel type C105/Yubikey OTP)
    # plutôt que d'en générer un — sinon laissé vide pour une app TOTP.
    secret: str | None = None
    # Présent uniquement en inscription forcée (pas encore de Bearer token).
    pending_token: str | None = None


class MfaConfirmRequest(BaseModel):
    method: str
    code: str | None = None  # absent pour webauthn (webauthn_response à la place)
    webauthn_response: dict | None = None
    pending_token: str | None = None


class MfaResendRequest(BaseModel):
    """Corps de /auth/mfa/request-code — pending_token pour renvoyer un
    code pendant un login/enrollment en cours (pas encore de Bearer),
    absent pour un renvoi self-service (déjà connecté)."""

    pending_token: str | None = None


class MfaSetupResponse(BaseModel):
    secret: str | None = None  # absent pour "email"/"webauthn"
    qr_uri: str | None = None
    detail: str | None = None  # présent pour "email" ("code envoyé")
    webauthn_options: dict | None = None  # présent pour "webauthn" — à passer à navigator.credentials.create()


class MfaConfirmResponse(BaseModel):
    """Soit une simple confirmation (self-service), soit un vrai token
    d'accès si la confirmation complète une inscription forcée."""

    confirmed: bool = True
    token: TokenResponse | None = None


class MfaVerifyRequest(BaseModel):
    pending_token: str
    method: str
    code: str | None = None  # absent pour webauthn (webauthn_response à la place)
    webauthn_response: dict | None = None


class MfaMethodsResponse(BaseModel):
    available: list[str]
    enabled: list[str]


class WebauthnLoginOptionsRequest(BaseModel):
    pending_token: str


class WebauthnLoginOptionsResponse(BaseModel):
    options: dict


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str = Field(min_length=8)
