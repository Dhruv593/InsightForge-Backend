import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings


class EmailDeliveryUnavailable(Exception):
    pass


class EmailService:
    async def send(self, *, recipient: str, subject: str, body: str) -> None:
        settings = get_settings()
        if not settings.smtp_host or not settings.smtp_from_email:
            raise EmailDeliveryUnavailable("SMTP is not configured")

        def deliver() -> None:
            message = EmailMessage()
            message["From"] = settings.smtp_from_email
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(body)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password.get_secret_value() if settings.smtp_password else "")
                smtp.send_message(message)

        await asyncio.to_thread(deliver)
