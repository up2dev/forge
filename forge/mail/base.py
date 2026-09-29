"""
forge.mail.base
================
BaseMail : un layout global (templates/layout.html), un micro-template
par type d'email qui l'étend.
"""
from __future__ import annotations

import logging
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from forge.config import get_settings

logger = logging.getLogger("forge.mail")

_env = Environment(
    loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
    autoescape=select_autoescape(["html"]),
)


class BaseMail:
    def __init__(self, template: str, context: dict, to: list[str], subject: str) -> None:
        self.template = template
        self.context = context
        self.to = to
        self.subject = subject

    def render(self) -> str:
        settings = get_settings()
        tpl = _env.get_template(self.template)

        return tpl.render(
            brand_color=settings.brand_color,
            app_name=settings.mail_from_name,
            **self.context,
        )

    async def send(self) -> None:
        settings = get_settings()

        message = EmailMessage()
        message["From"] = f"{settings.mail_from_name} <{settings.mail_from}>"
        message["To"] = ", ".join(self.to)
        message["Subject"] = self.subject
        message.set_content("This email requires an HTML-capable client.")
        message.add_alternative(self.render(), subtype="html", charset="utf-8")

        try:
            await aiosmtplib.send(
                message,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user or None,
                password=settings.smtp_password or None,
                use_tls=settings.smtp_use_tls,
            )
        except Exception:
            logger.exception("Failed to send email to %s", self.to)
            raise
