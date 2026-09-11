import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.google_auth import router as google_auth_router
from app.api.analysis_runs import router as analysis_runs_router
from app.api.conversations import router as conversations_router
from app.api.datasets import router as datasets_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.core.exceptions import (
    AppError,
    app_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    settings = get_settings()
    log_dir = setup_logging(settings)
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def log_request(request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid4())
        started = perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "HTTP request failed method=%s path=%s request_id=%s",
                request.method,
                request.url.path,
                request_id,
                extra={"request_id": request_id, "method": request.method, "path": request.url.path},
            )
            raise
        response.headers["x-request-id"] = request_id
        logger.info(
            "HTTP request completed method=%s path=%s status_code=%s duration_ms=%s request_id=%s",
            request.method,
            request.url.path,
            response.status_code,
            round((perf_counter() - started) * 1000, 2),
            request_id,
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            },
        )
        return response

    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)
    application.include_router(health_router, prefix=settings.api_v1_prefix)
    application.include_router(auth_router, prefix=settings.api_v1_prefix)
    application.include_router(google_auth_router, prefix=settings.api_v1_prefix)
    application.include_router(datasets_router, prefix=settings.api_v1_prefix)
    application.include_router(conversations_router, prefix=settings.api_v1_prefix)
    application.include_router(analysis_runs_router, prefix=settings.api_v1_prefix)

    logger.info("Application logging configured log_dir=%s", log_dir)

    return application


app = create_application()
