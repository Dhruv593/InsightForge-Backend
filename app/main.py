import logging
from contextlib import asynccontextmanager
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
from app.api.account import router as account_router
from app.api.monitoring import router as monitoring_router
from app.api.site_content import router as site_content_router
from app.api.llm_settings import router as llm_settings_router
from app.api.admin_users import router as admin_users_router
from app.api.payments import router as payments_router
from app.api.contact_inquiries import router as contact_inquiries_router
from app.core.config import get_settings
from app.core.http_security import SecurityMiddleware
from app.core.logging_config import bind_log_context, flush_logging, reset_log_context, setup_logging
from app.core.exceptions import (
    AppError,
    app_error_handler,
    unexpected_error_handler,
    validation_error_handler,
)
from app.services.analysis_job_queue import AnalysisJobQueue

logger = logging.getLogger(__name__)


@asynccontextmanager
async def application_lifespan(application: FastAPI):
    queue = AnalysisJobQueue()
    application.state.analysis_queue = queue
    await queue.start()
    try:
        yield
    finally:
        await queue.stop()
        logger.info("Application shutdown completed", extra={"event": "application.stopped"})
        flush_logging()


def create_application() -> FastAPI:
    settings = get_settings()
    logging_setup = setup_logging(settings)
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug if settings.app_env.lower() == "development" else False,
        docs_url="/docs" if settings.app_env.lower() == "development" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.app_env.lower() == "development" else None,
        lifespan=application_lifespan,
    )

    application.add_middleware(SecurityMiddleware, settings=settings)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_url],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def log_request(request, call_next):
        request_id = str(uuid4())
        context_token = bind_log_context(request_id=request_id)
        started = perf_counter()
        request_path = request.url.path
        logger.info(
            "HTTP request started method=%s path=%s",
            request.method,
            request_path,
            extra={"event": "http.request.started", "method": request.method, "path": request_path},
        )
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.exception(
                "HTTP request failed method=%s path=%s error_type=%s",
                request.method,
                request_path,
                type(exc).__name__,
                extra={"event": "http.request.failed", "method": request.method, "path": request_path, "error_type": type(exc).__name__, "duration_ms": round((perf_counter() - started) * 1000, 2)},
            )
            raise
        else:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            response.headers["x-request-id"] = request_id
            level = logging.ERROR if response.status_code >= 500 else logging.WARNING if response.status_code >= 400 else logging.INFO
            logger.log(
                level,
                "HTTP request completed method=%s path=%s status_code=%s duration_ms=%s",
                request.method,
                request_path,
                response.status_code,
                duration_ms,
                extra={
                    "event": "http.request.completed",
                    "method": request.method,
                    "path": request_path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "response_bytes": response.headers.get("content-length"),
                },
            )
            return response
        finally:
            reset_log_context(context_token)

    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_exception_handler(Exception, unexpected_error_handler)
    application.include_router(health_router, prefix=settings.api_v1_prefix)
    application.include_router(auth_router, prefix=settings.api_v1_prefix)
    application.include_router(google_auth_router, prefix=settings.api_v1_prefix)
    application.include_router(datasets_router, prefix=settings.api_v1_prefix)
    application.include_router(conversations_router, prefix=settings.api_v1_prefix)
    application.include_router(analysis_runs_router, prefix=settings.api_v1_prefix)
    application.include_router(account_router, prefix=settings.api_v1_prefix)
    application.include_router(monitoring_router, prefix=settings.api_v1_prefix)
    application.include_router(site_content_router, prefix=settings.api_v1_prefix)
    application.include_router(llm_settings_router, prefix=settings.api_v1_prefix)
    application.include_router(admin_users_router, prefix=settings.api_v1_prefix)
    application.include_router(payments_router, prefix=settings.api_v1_prefix)
    application.include_router(contact_inquiries_router, prefix=settings.api_v1_prefix)

    application.state.logging_setup = logging_setup
    logger.info(
        "Application logging configured log_dir=%s application_log=%s error_log=%s",
        logging_setup.log_dir,
        logging_setup.application_log,
        logging_setup.error_log,
        extra={
            "event": "application.logging.configured",
            "log_dir": str(logging_setup.log_dir),
            "application_log": str(logging_setup.application_log) if logging_setup.application_log else None,
            "error_log": str(logging_setup.error_log) if logging_setup.error_log else None,
        },
    )

    return application


app = create_application()
