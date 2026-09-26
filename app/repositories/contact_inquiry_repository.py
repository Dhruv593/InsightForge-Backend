from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact_inquiry import ContactInquiry


class ContactInquiryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, inquiry: ContactInquiry) -> ContactInquiry:
        self.session.add(inquiry)
        await self.session.flush()
        return inquiry

    async def get(self, inquiry_id: UUID) -> ContactInquiry | None:
        return await self.session.get(ContactInquiry, inquiry_id)

    async def list(self, *, status: str | None = None) -> list[ContactInquiry]:
        query = select(ContactInquiry)
        if status:
            query = query.where(ContactInquiry.status == status)
        result = await self.session.execute(query.order_by(ContactInquiry.created_at.desc()))
        return list(result.scalars().all())

    async def counts(self) -> dict[str, int]:
        result = await self.session.execute(
            select(ContactInquiry.status, func.count(ContactInquiry.id)).group_by(ContactInquiry.status)
        )
        counts = {"new": 0, "read": 0, "replied": 0, "closed": 0}
        for status, count in result.all():
            counts[status] = count
        counts["total"] = sum(counts.values())
        return counts
