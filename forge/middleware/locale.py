from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from forge.config import get_settings


class LocaleMiddleware(BaseHTTPMiddleware):
    """Fixe request.state.locale depuis Accept-Language, repli sur
    Settings.default_locale si absent/non supporté."""

    async def dispatch(self, request: Request, call_next):
        request.state.locale = self._resolve(request)

        return await call_next(request)

    def _resolve(self, request: Request) -> str:
        settings = get_settings()
        header = request.headers.get("accept-language", "")

        for part in header.split(","):
            code = part.split(";")[0].strip().split("-")[0].lower()

            if code in settings.supported_locales:
                return code

        return settings.default_locale
