import asyncio
import ssl
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from app.core.config import get_settings
from app.email_templates import RenderedEmail


class EmailDeliveryUnavailable(Exception):
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

    async def send_rendered(self, *, recipient: str, email: RenderedEmail) -> None:
        await self.send(
            recipient=recipient,
            subject=email.subject,
            text_body=email.text,
            html_body=email.html,
        )
