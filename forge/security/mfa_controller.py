"""
forge.security.mfa_controller
================================
setup/confirm sont génériques (method="totp"|"email"|... en
paramètre, pas un endpoint par méthode). Résolvent leur cible de deux
façons : Bearer token (self-service, déjà connecté) ou pending_token
d'intent "enroll" (inscription forcée, mi-connexion, pas de Bearer).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Body, Depends, HTTPException, Request
from sqlalchemy import select

from forge.config import get_settings
from forge.db import get_session
from forge.i18n import trans
from forge.security import crypto, mfa, webauthn
from forge.security.auth_controller import issue_access_token
from forge.security.dependencies import get_current_user_optional
from forge.security.models import MfaMethod, MfaPendingToken, User
from forge.security.schemas import (
    MfaConfirmRequest,
    MfaConfirmResponse,
    MfaMethodsResponse,
    MfaResendRequest,
    MfaSetupRequest,
    MfaSetupResponse,
    MfaVerifyRequest,
    TokenResponse,
    WebauthnLoginOptionsRequest,
    WebauthnLoginOptionsResponse,
)


class MfaController:
    async def setup(
        self,
        payload: MfaSetupRequest,
        request: Request,
        user: User | None = Depends(get_current_user_optional),
    ) -> MfaSetupResponse:
        locale = getattr(request.state, "locale", None)
        target, _ = await self._resolve_target(payload.pending_token, user, locale, {"enroll"})
        self._check_available(payload.method, locale)

        if await mfa.has_confirmed(target.id, payload.method):
            raise HTTPException(400, trans("auth.mfa.already_confirmed", locale))

        if payload.method == "totp":
            # secret fourni (token matériel type C105/Yubikey OTP) ou
            # généré (app TOTP) — le reste de la vérification est
            # identique dans les deux cas.
            secret = payload.secret or mfa.generate_secret()
            await self._upsert_method(target.id, "totp", secret=secret)

            return MfaSetupResponse(secret=secret, qr_uri=mfa.qr_uri(target.email, secret))

        if payload.method == "email":
            await self._upsert_method(target.id, "email")
            await mfa.send_email_code(target, locale)

            return MfaSetupResponse(detail=trans("auth.mfa.code_sent", locale))

        if payload.method == "webauthn":
            options, state = webauthn.registration_options(target.id, target.login)
            await self._upsert_method(target.id, "webauthn", webauthn_challenge=state)

            return MfaSetupResponse(webauthn_options=options)

        raise HTTPException(404, trans("auth.mfa.unknown_method", locale))

    async def confirm(
        self,
        payload: MfaConfirmRequest,
        request: Request,
        user: User | None = Depends(get_current_user_optional),
    ) -> MfaConfirmResponse:
        locale = getattr(request.state, "locale", None)
        target, enroll_token = await self._resolve_target(
            payload.pending_token, user, locale, {"enroll"}
        )

        method_row = await self._pending_method(target.id, payload.method)

        if payload.method == "webauthn":
            valid = method_row is not None and await self._confirm_webauthn(method_row, payload)
        else:
            valid = method_row is not None and await self._verify_code(target, payload.method, payload.code)

        if not valid:
            raise HTTPException(400, trans("auth.mfa.invalid_code", locale))

        await self._confirm(method_row.id)

        if enroll_token is not None:
            # Inscription forcée: confirmer LA méthode termine la
            # connexion — un vrai token est émis ici, pas besoin d'un
            # /verify séparé juste après.
            await mfa.invalidate_pending_token(enroll_token)

            return MfaConfirmResponse(confirmed=True, token=await issue_access_token(target))

        return MfaConfirmResponse(confirmed=True)

    async def request_email_code(
        self,
        request: Request,
        payload: MfaResendRequest = Body(default_factory=MfaResendRequest),
        user: User | None = Depends(get_current_user_optional),
    ) -> dict:
        """Renvoie un code — self-service (Bearer) ou mi-connexion avec
        le pending_token en cours (login "verify" expiré, ou enroll
        dont le premier code n'est jamais arrivé)."""
        locale = getattr(request.state, "locale", None)
        target, _ = await self._resolve_target(
            payload.pending_token, user, locale, {"enroll", "verify"}
        )
        await mfa.send_email_code(target, locale)

        return {"detail": trans("auth.mfa.code_sent", locale)}

    async def methods(
        self,
        request: Request,
        pending_token: str | None = None,
        user: User | None = Depends(get_current_user_optional),
    ) -> MfaMethodsResponse:
        """Fonctionne connecté (Bearer — liste ce que CE compte a
        activé) ou en inscription forcée (?pending_token=... — liste
        forcément vide, rien n'est encore confirmé, mais confirme que
        le token est valide et quelles méthodes sont proposées)."""
        locale = getattr(request.state, "locale", None)
        target, _ = await self._resolve_target(pending_token, user, locale, {"enroll"})

        return MfaMethodsResponse(
            available=get_settings().mfa_methods, enabled=await mfa.confirmed_methods(target.id)
        )

    async def disable(self, method: str, user: User | None = Depends(get_current_user_optional)) -> dict:
        if get_settings().mfa_force_enrollment and not mfa.can_force_disable(user):
            enabled = await mfa.confirmed_methods(user.id)

            if enabled == [method]:
                # L'inscription est obligatoire — se retrouver à zéro
                # méthode confirmée reviendrait à désactiver le MFA
                # soi-même malgré l'obligation, en silence. Sauf
                # permission dédiée (FORGE_MFA_FORCE_DISABLE_PERMISSION),
                # ce garde-fou est absolu.
                raise HTTPException(400, trans("auth.mfa.cannot_disable_last_method", None))

        async with get_session() as session:
            stmt = select(MfaMethod).where(MfaMethod.user_id == user.id, MfaMethod.method == method)
            row = (await session.execute(stmt)).scalar_one_or_none()

            if row is not None:
                await session.delete(row)
                await session.commit()

        return {"detail": trans("auth.mfa.disabled", None)}

    async def webauthn_login_options(
        self, payload: WebauthnLoginOptionsRequest, request: Request
    ) -> WebauthnLoginOptionsResponse:
        """Étape 1/2 d'une connexion WebAuthn — étape 2 = /auth/mfa/verify
        avec webauthn_response. Séparé de verify() car webauthn est la
        seule méthode en deux allers-retours (les autres n'ont qu'un
        code à saisir, pas de challenge à récupérer d'abord)."""
        locale = getattr(request.state, "locale", None)
        entry = await mfa.resolve_pending_token(payload.pending_token)

        if entry is None or entry.intent != "verify":
            raise HTTPException(401, trans("auth.invalid_credentials", locale))

        async with get_session() as session:
            stmt = select(MfaMethod).where(
                MfaMethod.user_id == entry.user_id,
                MfaMethod.method == "webauthn",
                MfaMethod.confirmed_at.is_not(None),
            )
            method_row = (await session.execute(stmt)).scalar_one_or_none()

        if method_row is None:
            raise HTTPException(400, trans("auth.mfa.unknown_method", locale))

        options, state = webauthn.login_options(method_row.credential_id)

        async with get_session() as session:
            pending = await session.get(MfaPendingToken, entry.id)
            pending.webauthn_challenge = state
            await session.commit()

        return WebauthnLoginOptionsResponse(options=options)

    async def verify(self, payload: MfaVerifyRequest, request: Request) -> TokenResponse:
        locale = getattr(request.state, "locale", None)
        entry = await mfa.resolve_pending_token(payload.pending_token)

        if entry is None or entry.intent != "verify":
            raise HTTPException(401, trans("auth.mfa.invalid_code", locale))

        async with get_session() as session:
            user = await session.get(User, entry.user_id)

        if user is None or not await mfa.has_confirmed(user.id, payload.method):
            raise HTTPException(400, trans("auth.mfa.invalid_code", locale))

        if payload.method == "webauthn":
            valid = await self._verify_webauthn_login(entry, user, payload)
        else:
            valid = await self._verify_code(user, payload.method, payload.code)

        if not valid:
            # Indépendant du rate-limit par IP (qui ne protège pas
            # d'une attaque distribuée sur CE pending_token précis) —
            # au-delà de FORGE_MFA_MAX_ATTEMPTS codes faux, le
            # pending_token est détruit, retour à un login complet.
            attempts = await mfa.record_failed_attempt(payload.pending_token)

            if attempts >= get_settings().mfa_max_attempts:
                await mfa.invalidate_pending_token(payload.pending_token)
                raise HTTPException(401, trans("auth.mfa.too_many_attempts", locale))

            raise HTTPException(400, trans("auth.mfa.invalid_code", locale))

        await mfa.invalidate_pending_token(payload.pending_token)

        return await issue_access_token(user)

    # ------------------------------------------------------------------

    async def _resolve_target(
        self,
        pending_token: str | None,
        user: User | None,
        locale: str | None,
        allowed_intents: set[str],
    ) -> tuple[User, str | None]:
        """pending_token a priorité sur le Bearer token — c'est le cas
        mi-connexion qui justifie que ces routes tournent sans
        authenticated_only. allowed_intents restreint quels
        pending_token sont acceptés : setup/confirm/methods
        n'acceptent que "enroll" (jamais "verify", sinon on pourrait
        activer une méthode avec un token censé juste en vérifier
        une déjà confirmée) ; request_email_code accepte les deux."""
        if pending_token:
            entry = await mfa.resolve_pending_token(pending_token)

            if entry is None or entry.intent not in allowed_intents:
                raise HTTPException(401, trans("auth.invalid_credentials", locale))

            async with get_session() as session:
                target = await session.get(User, entry.user_id)

            if target is None:
                raise HTTPException(401, trans("auth.invalid_credentials", locale))

            # Seul un token "enroll" doit déclencher la complétion de
            # connexion dans confirm() — un "verify" reste seulement
            # un renvoi de code, rien d'autre à faire dessus ici.
            return target, (pending_token if entry.intent == "enroll" else None)

        if user is not None:
            return user, None

        raise HTTPException(401, "Missing bearer token or pending_token")

    def _check_available(self, method: str, locale: str | None) -> None:
        if method not in get_settings().mfa_methods:
            raise HTTPException(404, trans("auth.mfa.unknown_method", locale))

    async def _upsert_method(
        self, user_id: int, method: str, secret: str | None = None, webauthn_challenge: str | None = None
    ) -> None:
        # Chiffré au repos — jamais le secret TOTP en clair en base
        # (voir forge/security/crypto.py). Les appelants passent
        # toujours le secret en clair, c'est cette méthode qui gère le
        # chiffrement une fois pour toutes.
        stored_secret = crypto.encrypt_secret(secret) if secret is not None else None

        async with get_session() as session:
            stmt = select(MfaMethod).where(MfaMethod.user_id == user_id, MfaMethod.method == method)
            row = (await session.execute(stmt)).scalar_one_or_none()

            if row is not None:
                row.secret = stored_secret
                row.last_totp_counter = None  # une méthode ré-inscrite repart de zéro
                row.webauthn_challenge = webauthn_challenge
                row.confirmed_at = None
            else:
                session.add(
                    MfaMethod(
                        user_id=user_id,
                        method=method,
                        secret=stored_secret,
                        webauthn_challenge=webauthn_challenge,
                    )
                )

            await session.commit()

    async def _confirm_webauthn(self, method_row: MfaMethod, payload: MfaConfirmRequest) -> bool:
        if method_row.webauthn_challenge is None or payload.webauthn_response is None:
            return False

        try:
            credential_id, public_key = webauthn.verify_registration(
                method_row.webauthn_challenge, payload.webauthn_response
            )
        except webauthn.WebauthnError:
            return False

        async with get_session() as session:
            row = await session.get(MfaMethod, method_row.id)
            row.credential_id = credential_id
            row.public_key = public_key
            row.webauthn_challenge = None
            await session.commit()

        return True

    async def _verify_webauthn_login(self, entry: MfaPendingToken, user: User, payload: MfaVerifyRequest) -> bool:
        if entry.webauthn_challenge is None or payload.webauthn_response is None:
            return False

        async with get_session() as session:
            stmt = select(MfaMethod).where(MfaMethod.user_id == user.id, MfaMethod.method == "webauthn")
            method_row = (await session.execute(stmt)).scalar_one_or_none()

        if method_row is None:
            return False

        try:
            new_count = webauthn.verify_login(
                entry.webauthn_challenge, method_row.credential_id, method_row.public_key, payload.webauthn_response
            )
        except webauthn.WebauthnError:
            return False

        # Un compteur qui n'avance pas (hors authentificateurs qui ne le
        # supportent pas, toujours à 0) est le signe classique d'une clé
        # clonée — voir forge/security/webauthn.py.
        if new_count != 0 and new_count <= method_row.sign_count:
            return False

        async with get_session() as session:
            row = await session.get(MfaMethod, method_row.id)
            row.sign_count = new_count
            await session.commit()

        return True

    async def _pending_method(self, user_id: int, method: str) -> MfaMethod | None:
        async with get_session() as session:
            stmt = select(MfaMethod).where(
                MfaMethod.user_id == user_id,
                MfaMethod.method == method,
                MfaMethod.confirmed_at.is_(None),
            )
            return (await session.execute(stmt)).scalar_one_or_none()

    async def _confirm(self, method_id: int) -> None:
        async with get_session() as session:
            row = await session.get(MfaMethod, method_id)
            row.confirmed_at = datetime.now(timezone.utc)
            await session.commit()

    async def _verify_code(self, user: User, method: str, code: str) -> bool:
        if method == "totp":
            async with get_session() as session:
                stmt = select(MfaMethod).where(
                    MfaMethod.user_id == user.id, MfaMethod.method == "totp"
                )
                row = (await session.execute(stmt)).scalar_one_or_none()

            if row is None:
                return False

            secret = crypto.decrypt_secret(row.secret)

            return await mfa.verify_totp_and_record(row.id, secret, code)

        if method == "email":
            return await mfa.verify_email_code(user.id, code)

        return False
