from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from ..config import Settings

logger = logging.getLogger(__name__)


class EmailService:
    """Small SMTP wrapper with a log-only mode for local development."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        if self.settings.email_mode != "smtp" or not self.settings.smtp_host:
            logger.info(
                "Email (log mode) to=%s subject=%s\n%s",
                to,
                subject,
                body,
            )
            return

        await asyncio.to_thread(self._send_smtp, message)

    def _send_smtp(self, message: EmailMessage) -> None:
        settings = self.settings
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as client:
            if settings.smtp_starttls:
                client.starttls()
            if settings.smtp_username:
                client.login(settings.smtp_username, settings.smtp_password)
            client.send_message(message)
        logger.info("Email sent to %s", message["To"])

    async def send_verification(self, *, to: str, link: str) -> None:
        await self.send(
            to=to,
            subject="Verify your ABM email",
            body=(
                "Open this link to verify your ABM email address:\n\n"
                f"{link}\n\n"
                "If you did not create this account, ignore this message."
            ),
        )

    async def send_password_reset(self, *, to: str, link: str) -> None:
        await self.send(
            to=to,
            subject="Reset your ABM password",
            body=(
                "Open this link to choose a new ABM password:\n\n"
                f"{link}\n\n"
                "If you did not request this, ignore this message."
            ),
        )

    async def send_usage_alert(
        self,
        *,
        to: str,
        threshold: int,
        plan: str,
        totals: dict[str, int],
        console_url: str,
    ) -> None:
        await self.send(
            to=to,
            subject=f"ABM usage alert: {threshold}% of plan quota",
            body=(
                f"Your ABM {plan} plan has reached {threshold}% of a monthly quota.\n\n"
                f"Tool calls: {totals.get('toolCalls', 0)}\n"
                f"Video jobs: {totals.get('videoJobs', 0)}\n"
                f"Video relay bytes: {totals.get('videoBytes', 0)}\n\n"
                f"Review usage and plan options: {console_url}\n"
            ),
        )
