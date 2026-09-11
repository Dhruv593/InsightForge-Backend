from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import DatabaseConnectionError
from app.db.session import get_db_session

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, str]:
    """Report API availability without requiring a database connection."""
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name}


@router.get("/db")
async def database_health_check(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Verify database connectivity with a lightweight query."""
    try:
        await session.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        raise DatabaseConnectionError() from exc

    return {"status": "ok", "database": "connected"}
