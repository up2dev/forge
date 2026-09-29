"""
forge.config
============
Config centrale, lue une fois depuis l'environnement/.env — jamais
d'os.environ.get() ailleurs dans le code (même principe que Rivet:
toujours config(), jamais env() en dehors de config/*.php).
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./forge.db"
    sql_echo: bool = Field(default=False, alias="FORGE_SQL_ECHO")

    # 0 = pas d'expiration (déconseillé).
    token_ttl_minutes: int = Field(default=10080, alias="FORGE_TOKEN_TTL_MINUTES")

    # Premier administrateur créé par scripts/seed.py. Les valeurs par défaut
    # ne sont bonnes qu'en dev local — en prod, les définir avant `seed`.
    admin_login: str = Field(default="admin", alias="FORGE_ADMIN_LOGIN")
    admin_email: str = Field(default="admin@example.test", alias="FORGE_ADMIN_EMAIL")
    admin_password: str = Field(default="changeme", alias="FORGE_ADMIN_PASSWORD")

    # Fuseau des expressions cron du planificateur (forge/scheduler.py) —
    # "0 3 * * *" veut dire 3h dans CE fuseau, pas en UTC.
    scheduler_timezone: str = Field(default="UTC", alias="FORGE_SCHEDULER_TIMEZONE")

    # Reset de mot de passe par email.
    pwd_reset_token_ttl_minutes: int = Field(default=60, alias="FORGE_PWD_RESET_TOKEN_TTL_MINUTES")
    # Révoque les sessions actives (AccessToken) à la réinitialisation —
    # un mot de passe compromis ne doit pas laisser une session déjà
    # ouverte ailleurs valide après coup.
    pwd_reset_revokes_sessions: bool = Field(default=True, alias="FORGE_PWD_RESET_REVOKES_SESSIONS")

    # Le lien de l'email pointe vers le FRONT, pas vers l'API — c'est
    # le front qui affiche le formulaire de saisie du nouveau mot de
    # passe, puis appelle POST /auth/pwd/reset avec le token.
    frontend_url: str = Field(default="http://localhost:5173", alias="FORGE_FRONTEND_URL")
    frontend_pwd_reset_path: str = Field(default="/reset-password", alias="FORGE_FRONTEND_PWD_RESET_PATH")

    login_rate_limit_times: int = Field(default=5, alias="FORGE_LOGIN_RATE_LIMIT_TIMES")
    login_rate_limit_seconds: int = Field(default=60, alias="FORGE_LOGIN_RATE_LIMIT_SECONDS")

    default_locale: str = Field(default="en", alias="FORGE_DEFAULT_LOCALE")
    supported_locales_raw: str = Field(default="en,fr", alias="FORGE_SUPPORTED_LOCALES")

    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=1025, alias="SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=False, alias="SMTP_USE_TLS")

    mail_from: str = Field(default="noreply@example.test", alias="MAIL_FROM")
    mail_from_name: str = Field(default="Forge", alias="MAIL_FROM_NAME")
    brand_color: str = Field(default="#4f46e5", alias="FORGE_BRAND_COLOR")

    mfa_enabled: bool = Field(default=True, alias="FORGE_MFA_ENABLED")
    mfa_issuer: str = Field(default="Forge", alias="FORGE_MFA_ISSUER")
    mfa_methods_raw: str = Field(default="totp,email,webauthn", alias="FORGE_MFA_METHODS")
    mfa_pending_ttl_minutes: int = Field(default=10, alias="FORGE_MFA_PENDING_TTL_MINUTES")
    mfa_email_code_ttl_minutes: int = Field(default=10, alias="FORGE_MFA_EMAIL_CODE_TTL_MINUTES")
    # Permission qui dispense du MFA (ex: "ADMIN_MFA_EXEMPT"). Vide = personne n'est exempté.
    mfa_bypass_permission: str = Field(default="", alias="FORGE_MFA_BYPASS_PERMISSION")

    # Permission qui autorise à désactiver sa dernière méthode MFA même
    # sous inscription forcée — sans elle, le garde-fou est absolu.
    mfa_force_disable_permission: str = Field(default="", alias="FORGE_MFA_FORCE_DISABLE_PERMISSION")
    # Force l'inscription MFA au prochain login si aucune méthode n'est
    # encore confirmée (équivalent force_enrollment côté Rivet).
    mfa_force_enrollment: bool = Field(default=False, alias="FORGE_MFA_FORCE_ENROLLMENT")

    # rp_id doit être le domaine exact vu par le navigateur (sans port
    # ni schéma) — "localhost" en dev, "app.exemple.fr" en prod. Un
    # mismatch fait échouer toute vérification WebAuthn, silencieusement
    # du point de vue de l'utilisateur (le navigateur refuse juste).
    webauthn_rp_id: str = Field(default="localhost", alias="FORGE_WEBAUTHN_RP_ID")
    webauthn_rp_name: str = Field(default="Forge", alias="FORGE_WEBAUTHN_RP_NAME")
    webauthn_origin: str = Field(default="http://localhost:8000", alias="FORGE_WEBAUTHN_ORIGIN")

    # Clé de chiffrement des secrets TOTP au repos (voir forge/security/crypto.py).
    # Vide en dev = clé de repli connue, insuffisant pour de vraies
    # données — à définir avant tout déploiement réel.
    app_key: str = Field(default="", alias="FORGE_APP_KEY")

    # Nombre de codes faux tolérés sur un même pending_token avant de le
    # détruire (retour à un login complet) — indépendant du rate-limit
    # par IP, qui ne protège pas contre une attaque distribuée sur UN
    # seul pending_token compromis.
    mfa_max_attempts: int = Field(default=5, alias="FORGE_MFA_MAX_ATTEMPTS")

    log_dir: str = Field(default="storage/logs", alias="FORGE_LOG_DIR")
    log_level: str = Field(default="INFO", alias="FORGE_LOG_LEVEL")
    log_max_bytes: int = Field(default=5_000_000, alias="FORGE_LOG_MAX_BYTES")
    log_backup_count: int = Field(default=5, alias="FORGE_LOG_BACKUP_COUNT")
    # "file" (défaut, storage/logs/forge.log) ou "mongo".
    log_backend: str = Field(default="file", alias="FORGE_LOG_BACKEND")
    log_mongo_url: str = Field(default="mongodb://localhost:27017", alias="FORGE_LOG_MONGO_URL")
    log_mongo_db: str = Field(default="forge_logs", alias="FORGE_LOG_MONGO_DB")
    log_mongo_collection: str = Field(default="logs", alias="FORGE_LOG_MONGO_COLLECTION")

    storage_dir: str = Field(default="storage/files", alias="FORGE_STORAGE_DIR")
    storage_max_bytes: int = Field(default=25_000_000, alias="FORGE_STORAGE_MAX_BYTES")
    # Taille max d'un morceau pour l'upload par chunks (PUT /files/{id}).
    # Un chunk plus gros est refusé (413) — sans ça, un client pourrait
    # envoyer tout le fichier en un seul "chunk" et défaire l'intérêt du
    # chunking (mémoire chargée d'un coup côté serveur).
    storage_chunk_size: int = Field(default=1_000_000, alias="FORGE_STORAGE_CHUNK_SIZE")
    storage_allowed_types_raw: str = Field(
        default=(
            "image/png,image/jpeg,image/gif,image/webp,"
            "application/pdf,"
            "application/msword,"
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
            "application/vnd.ms-excel,"
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
            "text/plain,text/csv"
        ),
        alias="FORGE_STORAGE_ALLOWED_TYPES",
    )

    @property
    def supported_locales(self) -> list[str]:
        return [l.strip() for l in self.supported_locales_raw.split(",") if l.strip()]

    @property
    def mfa_methods(self) -> list[str]:
        return [m.strip() for m in self.mfa_methods_raw.split(",") if m.strip()]

    @property
    def storage_allowed_types(self) -> list[str]:
        return [t.strip() for t in self.storage_allowed_types_raw.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
