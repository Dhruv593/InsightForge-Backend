import asyncio
import logging
import ssl
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

import httpx

from app.core.config import get_settings
from app.email_templates import RenderedEmail

logger = logging.getLogger(__name__)
BREVO_EMAILS_URL = "https://api.brevo.com/v3/smtp/email"


class EmailDeliveryUnavailable(Exception):
    pass


class EmailDeliveryFailed(Exception):
    pass


class EmailService:
    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        settings = get_settings()
        if settings.email_provider == "brevo":
            await self._send_with_brevo(
                recipient=recipient,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                reply_to=reply_to,
            )
            return
        if not settings.smtp_host or not settings.smtp_from_email:
            raise EmailDeliveryUnavailable("SMTP is not configured")

        def deliver() -> None:
            message = EmailMessage()
            _, from_address = parseaddr(settings.smtp_from_email)
            message["From"] = formataddr((settings.smtp_from_name, from_address))
            message["To"] = recipient
            message["Subject"] = subject
            if reply_to or settings.support_email:
                message["Reply-To"] = reply_to or settings.support_email
            message.set_content(text_body)
            if html_body:
                message.add_alternative(html_body, subtype="html")
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value() if settings.smtp_password else "")
                smtp.send_message(message)

        await asyncio.to_thread(deliver)

    async def _send_with_brevo(
        self,
        *,
        recipient: str,
        subject: str,
        text_body: str,
        html_body: str | None,
        reply_to: str | None,
    ) -> None:
        settings = get_settings()
        api_key = settings.brevo_api_key.get_secret_value() if settings.brevo_api_key else ""
        sender_email = settings.brevo_from_email.strip()
        sender_name = settings.brevo_from_name.strip() or "Tatparya"
        if not api_key or not sender_email:
            raise EmailDeliveryUnavailable("Brevo email delivery is not configured")

        payload: dict[str, object] = {
            "sender": {"email": sender_email, "name": sender_name},
            "to": [{"email": recipient}],
            "subject": subject,
            "textContent": text_body,
        }
        if html_body:
            payload["htmlContent"] = html_body
        response_address = reply_to or settings.support_email.strip()
        if response_address:
            payload["replyTo"] = {"email": response_address}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    BREVO_EMAILS_URL,
                    headers={"api-key": api_key, "accept": "application/json", "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Brevo rejected email request status_code=%s",
                exc.response.status_code,
                extra={"event": "email.brevo.rejected", "status_code": exc.response.status_code},
            )
            raise EmailDeliveryFailed("Brevo rejected the email request") from exc
        except httpx.HTTPError as exc:
            logger.exception("Brevo email request failed", extra={"event": "email.brevo.failed"})
            raise EmailDeliveryFailed("Brevo could not be reached") from exc

        try:
            message_id = response.json().get("messageId")
        except ValueError:
            message_id = None
        logger.info(
            "Email accepted by Brevo message_id=%s",
            message_id,
            extra={"event": "email.brevo.accepted", "provider_message_id": message_id},
        )

    async def send_rendered(self, *, recipient: str, email: RenderedEmail) -> None:
        await self.send(
            recipient=recipient,
            subject=email.subject,
            text_body=email.text,
            html_body=email.html,
        )
