import hashlib
import hmac
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.email_templates import payment_confirmation_email
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.repositories.payment_order_repository import PaymentOrderRepository
from app.repositories.user_repository import UserRepository
from app.schemas.payment import PaymentOrderResponse, PaymentResultResponse
from app.schemas.site_content import PlansContent
from app.services.site_content_service import DEFAULT_PLANS_CONTENT, SiteContentService
from app.services.email_service import EmailService

logger = logging.getLogger(__name__)
RAZORPAY_API = "https://api.razorpay.com/v1"


class PaymentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.orders = PaymentOrderRepository(session)
        self.users = UserRepository(session)
        self.content = SiteContentService(session)
        self.settings = get_settings()
        self.email = EmailService()

    def _credentials(self) -> tuple[str, str]:
        secret = self.settings.razorpay_key_secret.get_secret_value() if self.settings.razorpay_key_secret else ""
        if not self.settings.razorpay_key_id or not secret:
            raise AppError("PAYMENTS_NOT_CONFIGURED", "Online payments are not available yet.", 503)
        return self.settings.razorpay_key_id, secret

    async def create_order(self, plan_index: int, user: User) -> PaymentOrderResponse:
        key_id, key_secret = self._credentials()
        entry = await self.content.get_plans(published_only=True)
        plans = PlansContent.model_validate(entry.content) if entry is not None else DEFAULT_PLANS_CONTENT
        if not plans.enabled:
            raise AppError("PLANS_NOT_AVAILABLE", "Credit plans are not currently available.", 409)
        if plan_index >= len(plans.plans):
            raise AppError("PLAN_NOT_FOUND", "The selected credit plan is no longer available.", 404)
        plan = plans.plans[plan_index]
        if plan.amount_paise < 100:
            raise AppError("PLAN_PRICE_INVALID", "The selected plan does not have a valid payment amount.", 422)

        local_id = uuid4()
        receipt = f"tp_{local_id.hex[:32]}"
        payload = {
            "amount": plan.amount_paise,
            "currency": "INR",
            "receipt": receipt,
            "notes": {"local_order_id": str(local_id), "plan": plan.name},
        }
        try:
            async with httpx.AsyncClient(auth=(key_id, key_secret), timeout=self.settings.razorpay_request_timeout_seconds) as client:
                response = await client.post(f"{RAZORPAY_API}/orders", json=payload)
                response.raise_for_status()
                remote = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Razorpay order creation failed user_id=%s error_type=%s", user.id, type(exc).__name__)
            raise AppError("PAYMENT_PROVIDER_UNAVAILABLE", "The payment service is temporarily unavailable. Please try again.", 502) from exc

        remote_order_id = str(remote.get("id", ""))
        if not remote_order_id.startswith("order_") or remote.get("amount") != plan.amount_paise or remote.get("currency") != "INR":
            raise AppError("PAYMENT_PROVIDER_INVALID_RESPONSE", "The payment service returned an invalid order.", 502)
        order = PaymentOrder(
            id=local_id, user_id=user.id, plan_name=plan.name, credits=plan.credits,
            amount_paise=plan.amount_paise, currency="INR", receipt=receipt,
            razorpay_order_id=remote_order_id, status="pending",
        )
        try:
            await self.orders.create(order)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.exception("Unable to persist Razorpay order user_id=%s", user.id)
            raise AppError("PAYMENT_ORDER_SAVE_FAILED", "The payment order could not be saved. Please try again.", 500) from exc
        return PaymentOrderResponse(
            local_order_id=order.id, razorpay_order_id=order.razorpay_order_id, key_id=key_id,
            amount=order.amount_paise, currency=order.currency, plan_name=order.plan_name,
            credits=order.credits, customer_name=user.name, customer_email=user.email,
        )

    async def verify_checkout(self, *, order_id: str, payment_id: str, signature: str, user: User) -> PaymentResultResponse:
        _, key_secret = self._credentials()
        order = await self.orders.get_by_razorpay_order_id(order_id)
        if order is None or order.user_id != user.id:
            raise AppError("PAYMENT_ORDER_NOT_FOUND", "Payment order not found.", 404)
        expected = hmac.new(key_secret.encode(), f"{order.razorpay_order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise AppError("PAYMENT_SIGNATURE_INVALID", "Payment verification failed.", 400)
        payment = await self._fetch_payment(payment_id)
        return await self._fulfill(order_id=order.razorpay_order_id, payment=payment, expected_user_id=user.id)

    async def process_webhook(self, raw_body: bytes, signature: str | None) -> None:
        webhook_secret = self.settings.razorpay_webhook_secret.get_secret_value() if self.settings.razorpay_webhook_secret else ""
        if not webhook_secret:
            raise AppError("PAYMENT_WEBHOOK_NOT_CONFIGURED", "Payment webhook is not configured.", 503)
        expected = hmac.new(webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(expected, signature):
            raise AppError("PAYMENT_WEBHOOK_SIGNATURE_INVALID", "Webhook signature is invalid.", 400)
        try:
            import json
            event = json.loads(raw_body)
            if event.get("event") != "payment.captured":
                return
            payment = event["payload"]["payment"]["entity"]
            order_id = payment["order_id"]
        except (KeyError, TypeError, ValueError) as exc:
            raise AppError("PAYMENT_WEBHOOK_INVALID", "Webhook payload is invalid.", 400) from exc
        if not await self.orders.get_by_razorpay_order_id(str(order_id)):
            logger.warning("Ignoring Razorpay webhook for unknown order_id=%s", order_id)
            return
        await self._fulfill(order_id=str(order_id), payment=payment)

    async def _fetch_payment(self, payment_id: str) -> dict:
        key_id, key_secret = self._credentials()
        try:
            async with httpx.AsyncClient(auth=(key_id, key_secret), timeout=self.settings.razorpay_request_timeout_seconds) as client:
                response = await client.get(f"{RAZORPAY_API}/payments/{payment_id}")
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AppError("PAYMENT_STATUS_UNAVAILABLE", "Payment status could not be confirmed. Your credits will be added after confirmation.", 502) from exc

    async def _fulfill(self, *, order_id: str, payment: dict, expected_user_id: UUID | None = None) -> PaymentResultResponse:
        order = await self.orders.get_for_update(order_id)
        if order is None or (expected_user_id is not None and order.user_id != expected_user_id):
            raise AppError("PAYMENT_ORDER_NOT_FOUND", "Payment order not found.", 404)
        payment_id = str(payment.get("id", ""))
        if order.status == "paid":
            if order.razorpay_payment_id != payment_id:
                raise AppError("PAYMENT_ALREADY_FULFILLED", "This order has already been fulfilled.", 409)
            user = await self.users.get_by_id(order.user_id)
            return PaymentResultResponse(status="paid", credits_added=0, credit_balance=user.credits if user else 0)
        if (
            payment.get("status") != "captured"
            or str(payment.get("order_id", "")) != order.razorpay_order_id
            or payment.get("amount") != order.amount_paise
            or payment.get("currency") != order.currency
            or not payment_id.startswith("pay_")
        ):
            raise AppError("PAYMENT_NOT_CAPTURED", "Payment has not been captured. Credits will be added after confirmation.", 409)
        try:
            balance = await self.users.adjust_credits(order.user_id, order.credits)
            if balance is None:
                raise AppError("PAYMENT_USER_NOT_FOUND", "The account for this payment could not be found.", 404)
            order.razorpay_payment_id = payment_id
            order.status = "paid"
            order.paid_at = datetime.now(timezone.utc)
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise AppError("PAYMENT_ALREADY_FULFILLED", "This payment has already been processed.", 409) from exc
        except Exception:
            await self.session.rollback()
            raise
        logger.info("Payment fulfilled order_id=%s user_id=%s credits=%s", order.razorpay_order_id, order.user_id, order.credits)
        user = await self.users.get_by_id(order.user_id)
        if user is not None:
            templates = await self.content.resolve_email_templates()
            frontend_url = getattr(self.settings, "frontend_url", "http://localhost:5173")
            support_email = (
                getattr(self.settings, "support_email", "")
                or getattr(self.settings, "smtp_from_email", "")
            )
            email = payment_confirmation_email(
                user_name=user.name,
                plan_name=order.plan_name,
                credits_added=order.credits,
                credit_balance=balance,
                amount_minor=order.amount_paise,
                currency=order.currency,
                payment_id=payment_id,
                paid_at=order.paid_at or datetime.now(timezone.utc),
                frontend_url=frontend_url,
                support_email=support_email,
                template=templates.payment_confirmation,
            )
            try:
                await self.email.send_rendered(recipient=user.email, email=email)
            except Exception:
                logger.exception(
                    "Payment confirmation email could not be delivered order_id=%s user_id=%s",
                    order.razorpay_order_id,
                    order.user_id,
                )
        return PaymentResultResponse(status="paid", credits_added=order.credits, credit_balance=balance)
