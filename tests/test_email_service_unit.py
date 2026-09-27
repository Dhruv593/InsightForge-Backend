from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.services import email_service as email_service_module
from app.services.email_service import BREVO_EMAILS_URL, EmailDeliveryUnavailable, EmailService


class FakeResponse:
    def __init__(self, *, message_id: str = "email_test_123") -> None:
        self.status_code = 200
        self._message_id = message_id

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"messageId": self._message_id}


class FakeAsyncClient:
    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def post(self, url, *, headers, json):
        self.request = {"url": url, "headers": headers, "json": json}
        FakeAsyncClient.last_request = self.request
        return FakeResponse()


@pytest.mark.anyio
async def test_brevo_transport_sends_html_text_and_reply_to(monkeypatch):
    settings = SimpleNamespace(
        email_provider="brevo",
        brevo_api_key=SecretStr("xkeysib-test-secret"),
        brevo_from_email="tatparya.demo@gmail.com",
        brevo_from_name="Tatparya",
        support_email="help@tatparya.example",
    )
    monkeypatch.setattr(email_service_module, "get_settings", lambda: settings)
    monkeypatch.setattr(email_service_module.httpx, "AsyncClient", FakeAsyncClient)

    await EmailService().send(
        recipient="customer@example.com",
        subject="Your answer",
        text_body="Plain answer",
        html_body="<p>Answer</p>",
        reply_to="agent@tatparya.example",
    )

    request = FakeAsyncClient.last_request
    assert request["url"] == BREVO_EMAILS_URL
    assert request["headers"]["api-key"] == "xkeysib-test-secret"
    assert request["json"] == {
        "sender": {"email": "tatparya.demo@gmail.com", "name": "Tatparya"},
        "to": [{"email": "customer@example.com"}],
        "subject": "Your answer",
        "textContent": "Plain answer",
        "htmlContent": "<p>Answer</p>",
        "replyTo": {"email": "agent@tatparya.example"},
    }


@pytest.mark.anyio
async def test_brevo_transport_requires_api_key_and_sender(monkeypatch):
    settings = SimpleNamespace(
        email_provider="brevo",
        brevo_api_key=None,
        brevo_from_email="",
        brevo_from_name="Tatparya",
        support_email="",
    )
    monkeypatch.setattr(email_service_module, "get_settings", lambda: settings)

    with pytest.raises(EmailDeliveryUnavailable, match="Brevo"):
        await EmailService().send(recipient="customer@example.com", subject="Test", text_body="Test")
