import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.email_templates import DEFAULT_EMAIL_TEMPLATES
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.schemas.payment import PaymentResultResponse
from app.services.payment_service import PaymentService

pytestmark = pytest.mark.asyncio


def payment_service() -> PaymentService:
    service = PaymentService(AsyncMock(spec=AsyncSession))
    service.settings = SimpleNamespace(
        razorpay_key_id="rzp_test_key",
        razorpay_key_secret=SecretStr("checkout-secret"),
        razorpay_webhook_secret=SecretStr("webhook-secret"),
        razorpay_request_timeout_seconds=15,
    )
    service.content.resolve_email_templates = AsyncMock(return_value=DEFAULT_EMAIL_TEMPLATES)
    return service


async def test_checkout_signature_uses_server_order_and_fulfills_captured_payment():
    service = payment_service()
    user = User(id=uuid4(), name="Test User", email="test@example.com")
    order = PaymentOrder(user_id=user.id, razorpay_order_id="order_test123", plan_name="Starter", credits=25, amount_paise=49900, currency="INR", receipt="tp_test")
    service.orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    payment = {"id": "pay_test123", "order_id": order.razorpay_order_id, "status": "captured", "amount": 49900, "currency": "INR"}
    service._fetch_payment = AsyncMock(return_value=payment)
    expected_result = PaymentResultResponse(status="paid", credits_added=25, credit_balance=30)
    service._fulfill = AsyncMock(return_value=expected_result)
    signature = hmac.new(b"checkout-secret", b"order_test123|pay_test123", hashlib.sha256).hexdigest()

    result = await service.verify_checkout(order_id=order.razorpay_order_id, payment_id="pay_test123", signature=signature, user=user)

    assert result == expected_result
    service._fetch_payment.assert_awaited_once_with("pay_test123")
    service._fulfill.assert_awaited_once_with(order_id="order_test123", payment=payment, expected_user_id=user.id)


async def test_invalid_checkout_signature_never_fetches_or_fulfills_payment():
    service = payment_service()
    user = User(id=uuid4(), name="Test User", email="test@example.com")
    order = PaymentOrder(user_id=user.id, razorpay_order_id="order_test123", plan_name="Starter", credits=25, amount_paise=49900, currency="INR", receipt="tp_test")
    service.orders.get_by_razorpay_order_id = AsyncMock(return_value=order)
    service._fetch_payment = AsyncMock()

    with pytest.raises(AppError) as caught:
        await service.verify_checkout(order_id=order.razorpay_order_id, payment_id="pay_test123", signature="invalid-signature-value", user=user)

    assert caught.value.code == "PAYMENT_SIGNATURE_INVALID"
    service._fetch_payment.assert_not_awaited()


async def test_paid_order_is_idempotent_and_does_not_add_credits_twice():
    service = payment_service()
    user = User(id=uuid4(), name="Test User", email="test@example.com", credits=30)
    order = PaymentOrder(user_id=user.id, razorpay_order_id="order_test123", razorpay_payment_id="pay_test123", plan_name="Starter", credits=25, amount_paise=49900, currency="INR", receipt="tp_test", status="paid")
    service.orders.get_for_update = AsyncMock(return_value=order)
    service.users.get_by_id = AsyncMock(return_value=user)
    service.users.adjust_credits = AsyncMock()

    result = await service._fulfill(order_id=order.razorpay_order_id, payment={"id": "pay_test123"})

    assert result.credits_added == 0
    assert result.credit_balance == 30
    service.users.adjust_credits.assert_not_awaited()


async def test_captured_payment_sends_confirmation_after_credits_are_committed():
    service = payment_service()
    service.settings.frontend_url = "https://tatparya.example"
    service.settings.support_email = "support@tatparya.example"
    service.settings.smtp_from_email = "no-reply@tatparya.example"
    user = User(id=uuid4(), name="Test User", email="test@example.com", credits=30)
    order = PaymentOrder(user_id=user.id, razorpay_order_id="order_test123", plan_name="Starter", credits=25, amount_paise=49900, currency="INR", receipt="tp_test")
    payment = {"id": "pay_test123", "order_id": order.razorpay_order_id, "status": "captured", "amount": 49900, "currency": "INR"}
    service.orders.get_for_update = AsyncMock(return_value=order)
    service.users.adjust_credits = AsyncMock(return_value=30)
    service.users.get_by_id = AsyncMock(return_value=user)
    service.email.send_rendered = AsyncMock()

    result = await service._fulfill(order_id=order.razorpay_order_id, payment=payment)

    assert result == PaymentResultResponse(status="paid", credits_added=25, credit_balance=30)
    service.session.commit.assert_awaited_once()
    service.email.send_rendered.assert_awaited_once()
    sent = service.email.send_rendered.await_args.kwargs["email"]
    assert sent.subject == "Your Tatparya credits are ready"
    assert "pay_test123" in sent.text
