import asyncio
import logging
from time import perf_counter
from uuid import UUID

from app.core.exceptions import AppError
from app.core.logging_config import bind_log_context, reset_log_context
from app.db.session import AsyncSessionFactory
from app.models.analysis_run import AnalysisRun
from app.models.user import User
from app.repositories.analysis_run_repository import AnalysisRunRepository
from app.services.analysis_execution_service import AnalysisExecutionService

logger = logging.getLogger(__name__)


class AnalysisJobQueue:
    """Small durable DB-backed queue suitable for the single Render web process."""

    def __init__(self, concurrency: int = 1, poll_seconds: float = 1.5) -> None:
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._poll_seconds = poll_seconds
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._poller: asyncio.Task | None = None
        self._wake = asyncio.Event()

    async def start(self) -> None:
        if self._poller is None:
            try:
                async with AsyncSessionFactory() as session:
                    recovered = await AnalysisRunRepository(session).requeue_interrupted()
                    await session.commit()
                if recovered:
                    logger.warning("Requeued interrupted analyses count=%s", recovered)
            except Exception:
                logger.exception("Interrupted analyses could not be requeued during startup; polling will continue")
            self._poller = asyncio.create_task(self._poll(), name="analysis-queue-poller")
            logger.info(
                "Analysis queue started concurrency=%s poll_seconds=%s",
                self._concurrency,
                self._poll_seconds,
                extra={"event": "analysis.queue.started", "concurrency": self._concurrency, "poll_seconds": self._poll_seconds},
            )

    async def stop(self) -> None:
        if self._poller:
            self._poller.cancel()
        for task in self._tasks.values():
            task.cancel()
        pending = [task for task in [self._poller, *self._tasks.values()] if task]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        self._poller = None
        logger.info("Analysis queue stopped", extra={"event": "analysis.queue.stopped"})

    def notify(self) -> None:
        self._wake.set()

    def cancel(self, analysis_run_id: UUID) -> None:
        task = self._tasks.get(analysis_run_id)
        if task:
            task.cancel()

    async def _poll(self) -> None:
        while True:
            try:
                async with AsyncSessionFactory() as session:
                    pending = await AnalysisRunRepository(session).list_pending()
                for run in pending:
                    if run.id not in self._tasks:
                        task = asyncio.create_task(self._run(run.id), name=f"analysis-{run.id}")
                        self._tasks[run.id] = task
                        task.add_done_callback(lambda _, run_id=run.id: self._tasks.pop(run_id, None))
                self._wake.clear()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=self._poll_seconds)
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Analysis queue poll failed")
                await asyncio.sleep(self._poll_seconds)

    async def _run(self, analysis_run_id: UUID) -> None:
        context_token = bind_log_context(analysis_run_id=analysis_run_id)
        started = perf_counter()
        try:
            logger.info("Background analysis started", extra={"event": "analysis.job.started"})
            async with self._semaphore:
                async with AsyncSessionFactory() as session:
                    run = await session.get(AnalysisRun, analysis_run_id)
                    if run is None or run.status != "pending":
                        logger.info("Background analysis skipped status=%s", getattr(run, "status", "missing"), extra={"event": "analysis.job.skipped", "status": getattr(run, "status", "missing")})
                        return
                    user = await session.get(User, run.user_id)
                    if user is None or not user.is_active:
                        await AnalysisRunRepository(session).update_status(run, "failed", error_code="USER_UNAVAILABLE", error_message="The account is not available.")
                        await session.commit()
                        return
                    await AnalysisExecutionService(session).execute(run.id, user)
        except asyncio.CancelledError:
            logger.warning("Background analysis cancelled", extra={"event": "analysis.job.cancelled", "duration_ms": round((perf_counter() - started) * 1000, 2)})
            raise
        except AppError as exc:
            logger.warning("Background analysis ended code=%s", exc.code, extra={"event": "analysis.job.failed", "error_code": exc.code, "duration_ms": round((perf_counter() - started) * 1000, 2)})
        except Exception:
            logger.exception("Background analysis failed", extra={"event": "analysis.job.failed", "error_code": "BACKGROUND_EXECUTION_FAILED", "duration_ms": round((perf_counter() - started) * 1000, 2)})
            await self._mark_failed(analysis_run_id)
        else:
            logger.info("Background analysis completed", extra={"event": "analysis.job.completed", "duration_ms": round((perf_counter() - started) * 1000, 2)})
        finally:
            reset_log_context(context_token)

    @staticmethod
    async def _mark_failed(analysis_run_id: UUID) -> None:
        async with AsyncSessionFactory() as session:
            run = await session.get(AnalysisRun, analysis_run_id)
            if run and run.status in {"pending", "running"}:
                await AnalysisRunRepository(session).update_status(run, "failed", error_code="BACKGROUND_EXECUTION_FAILED", error_message="The analysis could not be completed. You can retry it.")
                await session.commit()
