from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_order import PaymentOrder


class PaymentOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, order: PaymentOrder) -> PaymentOrder:
        self.session.add(order)
        await self.session.flush()
        return order

    async def get_by_razorpay_order_id(self, order_id: str) -> PaymentOrder | None:
        result = await self.session.execute(select(PaymentOrder).where(PaymentOrder.razorpay_order_id == order_id))
        return result.scalar_one_or_none()

    async def get_for_update(self, order_id: str) -> PaymentOrder | None:
        result = await self.session.execute(
            select(PaymentOrder).where(PaymentOrder.razorpay_order_id == order_id).with_for_update()
        )
        return result.scalar_one_or_none()
