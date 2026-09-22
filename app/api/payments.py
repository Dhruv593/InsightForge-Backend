from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import CurrentUser
from app.db.session import get_db_session
from app.schemas.payment import PaymentOrderCreate, PaymentOrderResponse, PaymentResultResponse, PaymentVerificationRequest
from app.services.payment_service import PaymentService

router = APIRouter(prefix="/payments", tags=["payments"])


def service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> PaymentService:
    return PaymentService(session)


@router.post("/orders", response_model=PaymentOrderResponse)
async def create_payment_order(payload: PaymentOrderCreate, user: CurrentUser, payments: Annotated[PaymentService, Depends(service)]) -> PaymentOrderResponse:
    return await payments.create_order(payload.plan_index, user)


@router.post("/verify", response_model=PaymentResultResponse)
async def verify_payment(payload: PaymentVerificationRequest, user: CurrentUser, payments: Annotated[PaymentService, Depends(service)]) -> PaymentResultResponse:
    return await payments.verify_checkout(
        order_id=payload.razorpay_order_id,
        payment_id=payload.razorpay_payment_id,
        signature=payload.razorpay_signature,
        user=user,
    )


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, payments: Annotated[PaymentService, Depends(service)]) -> dict[str, bool]:
    await payments.process_webhook(await request.body(), request.headers.get("x-razorpay-signature"))
    return {"received": True}
