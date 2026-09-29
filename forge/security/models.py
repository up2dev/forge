"""
forge.security.models
======================
Modèles Auth (User/Role/Permission) + tokens d'accès (AccessToken) +
MFA, en SQLAlchemy async.

Pas de colonne "owner" scannée par convention : `BaseRepository.owner_column`
reste None par défaut, un Repository qui veut du scoping par
utilisateur le déclare explicitement.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from forge.models.base import Base, TimestampMixin

user_role = Table(
    "user_role",
    Base.metadata,
    Column("user_id", ForeignKey("users.id"), primary_key=True),
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
)

role_permission = Table(
    "role_permission",
    Base.metadata,
    Column("role_id", ForeignKey("roles.id"), primary_key=True),
    Column("permission_id", ForeignKey("permissions.id"), primary_key=True),
)


class Permission(Base, TimestampMixin):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))

    permissions: Mapped[list[Permission]] = relationship(secondary=role_permission)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    roles: Mapped[list[Role]] = relationship(secondary=user_role)


class AccessToken(Base, TimestampMixin):
    """
    Un token émis = une ligne. `token_hash` est ce qui est indexé et
    comparé (jamais le token en clair, cf. forge.security.tokens) —
    `name` reprend l'idée de Rivet (Hash::make(user-agent)) pour
    pouvoir nettoyer les tokens d'un appareil précis sans purger toute
    la session de l'utilisateur.
    """

    __tablename__ = "access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()


class MfaMethod(Base, TimestampMixin):
    """Une méthode activée = une ligne ('totp'/'email'/'webauthn').
    confirmed_at=None = inscription en cours, pas encore utilisable
    pour se connecter.

    `secret` sert au TOTP — chiffré au repos (voir forge/security/crypto.py),
    jamais en clair en base, d'où la largeur de colonne (le chiffré est
    plus long que le secret d'origine). `last_totp_counter` porte
    l'anti-rejeu : un code déjà accepté (même time-step ou antérieur)
    est refusé, même valide.

    `credential_id`/`public_key`/`sign_count` au WebAuthn (une seule
    clé de sécurité par utilisateur dans cette version — plusieurs clés
    demanderait une table à part) ; `webauthn_challenge` porte le
    challenge en attente le temps d'une cérémonie d'inscription, effacé
    une fois confirmé."""

    __tablename__ = "user_mfa_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    method: Mapped[str] = mapped_column(String(20))
    secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_totp_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credential_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    public_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    webauthn_challenge: Mapped[str | None] = mapped_column(Text, nullable=True)


class MfaPendingToken(Base, TimestampMixin):
    """Émis après vérification du mot de passe, avant la vérification
    MFA — prouve que l'étape 1 est passée, sans donner accès.
    `webauthn_challenge` porte le challenge de connexion WebAuthn en
    attente, le temps d'une cérémonie (options -> réponse signée).
    `failed_attempts` compte les codes faux sur CE pending_token —
    au-delà de `FORGE_MFA_MAX_ATTEMPTS`, il est détruit (retour à un
    login complet), indépendamment du rate-limit par IP."""

    __tablename__ = "mfa_pending_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    intent: Mapped[str] = mapped_column(String(20))  # "verify" (enroll: pas encore fait)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    webauthn_challenge: Mapped[str | None] = mapped_column(Text, nullable=True)


class MfaEmailCode(Base, TimestampMixin):
    """Un seul code actif par utilisateur — un nouveau écrase le
    précédent, usage unique (supprimé à la tentative, valide ou non)."""

    __tablename__ = "mfa_email_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(Base, TimestampMixin):
    """Un seul lien actif par utilisateur — une nouvelle demande
    invalide l'ancienne (voir forge/security/password_reset.py),
    plutôt que de laisser plusieurs liens valides en parallèle."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
