from uuid import UUID

from pydantic import BaseModel, Field


class PaymentOrderCreate(BaseModel):
    plan_index: int = Field(ge=0, le=5)


class PaymentOrderResponse(BaseModel):
    local_order_id: UUID
    razorpay_order_id: str
    key_id: str
    amount: int
    currency: str
    plan_name: str
    credits: int
    customer_name: str
    customer_email: str


class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=5, max_length=100)
    razorpay_payment_id: str = Field(min_length=5, max_length=100)
    razorpay_signature: str = Field(min_length=20, max_length=200)


class PaymentResultResponse(BaseModel):
    status: str
    credits_added: int
    credit_balance: int
