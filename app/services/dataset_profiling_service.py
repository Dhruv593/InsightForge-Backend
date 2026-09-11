import asyncio
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import (
    DatasetDownloadFailedError,
    DatasetNotFoundError,
    DatasetParseFailedError,
    DatasetProfileFailedError,
    DatasetProfileNotFoundError,
    ProfileRowLimitExceededError,
    UnsupportedDataStructureError,
)
from app.models.dataset_profile import DatasetProfile, DatasetProfileStatus
from app.models.user import User
from app.repositories.dataset_profile_repository import DatasetProfileRepository
from app.repositories.dataset_repository import DatasetRepository
from app.services.dataset_file_service import (
    DatasetFileDownloadError,
    DatasetFileService,
)
from app.services.dataset_loader_service import (
    DatasetLoaderService,
    DatasetParseError,
    DatasetRowLimitError,
    UnsupportedDatasetStructureError,
)
from app.services.dataset_profiler import DeterministicDatasetProfiler, ProfileResult

logger = logging.getLogger(__name__)


class DatasetProfilingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.datasets = DatasetRepository(session)
        self.profiles = DatasetProfileRepository(session)
        self.files = DatasetFileService()
        self.loader = DatasetLoaderService(get_settings().max_profile_rows)
        self.profiler = DeterministicDatasetProfiler()

    async def profile_dataset(self, dataset_id: UUID, user: User) -> DatasetProfile:
        user_id = user.id
        dataset = await self.datasets.get_for_user(
            dataset_id=dataset_id,
            user_id=user_id,
        )
        if dataset is None:
            raise DatasetNotFoundError

        profile = await self._set_processing(dataset_id)
        stage = "download"
        try:
            file_bytes = await self.files.download(dataset)
            stage = "load"
            loaded = await asyncio.to_thread(
                self.loader.load,
                file_bytes,
                dataset.file_type,
            )
            stage = "profile"
            result = await asyncio.to_thread(self.profiler.profile, loaded)
            stage = "persist"
            await self.profiles.update(
                profile,
                **self._completed_values(result),
            )
            await self.session.commit()
            await self.session.refresh(profile)
        except DatasetFileDownloadError as exc:
            await self._mark_failed(dataset_id, user_id, stage, exc)
            raise DatasetDownloadFailedError from exc
        except DatasetRowLimitError as exc:
            await self._mark_failed(dataset_id, user_id, stage, exc)
            raise ProfileRowLimitExceededError from exc
        except UnsupportedDatasetStructureError as exc:
            await self._mark_failed(dataset_id, user_id, stage, exc)
            raise UnsupportedDataStructureError from exc
        except DatasetParseError as exc:
            await self._mark_failed(dataset_id, user_id, stage, exc)
            raise DatasetParseFailedError from exc
        except SQLAlchemyError as exc:
            await self._mark_failed(dataset_id, user_id, stage, exc)
            raise DatasetProfileFailedError from exc
        except Exception as exc:
            await self._mark_failed(dataset_id, user_id, stage, exc)
            raise DatasetProfileFailedError from exc

        logger.info(
            "Dataset profiling completed dataset_id=%s user_id=%s rows=%s columns=%s",
            dataset_id,
            user_id,
            profile.row_count,
            profile.column_count,
        )
        return profile

    async def get_profile(self, dataset_id: UUID, user: User) -> DatasetProfile:
        dataset = await self.datasets.get_for_user(
            dataset_id=dataset_id,
            user_id=user.id,
        )
        if dataset is None:
            raise DatasetNotFoundError

        profile = await self.profiles.get_by_dataset_id(dataset_id)
        if profile is None:
            raise DatasetProfileNotFoundError
        return profile

    async def _set_processing(self, dataset_id: UUID) -> DatasetProfile:
        try:
            profile = await self.profiles.get_by_dataset_id(dataset_id)
            reset_values = {
                "row_count": None,
                "column_count": None,
                "schema_json": {},
                "missing_values_json": {},
                "duplicate_summary_json": {},
                "numeric_summary_json": {},
                "categorical_summary_json": {},
                "date_summary_json": {},
                "outlier_summary_json": {},
                "quality_issues_json": [],
                "profile_status": DatasetProfileStatus.PROCESSING.value,
                "profiled_at": None,
            }
            if profile is None:
                profile = await self.profiles.create(
                    dataset_id,
                    DatasetProfileStatus.PROCESSING.value,
                )
                await self.profiles.update(profile, **reset_values)
            else:
                await self.profiles.update(profile, **reset_values)
            await self.session.commit()
            return profile
        except SQLAlchemyError as exc:
            await self.session.rollback()
            raise DatasetProfileFailedError from exc

    async def _mark_failed(
        self,
        dataset_id: UUID,
        user_id: UUID,
        stage: str,
        cause: Exception,
    ) -> None:
        try:
            await self.session.rollback()
            await self.profiles.mark_failed(dataset_id)
            await self.session.commit()
        except SQLAlchemyError as status_error:
            await self.session.rollback()
            logger.error(
                "Profile failure status update failed dataset_id=%s user_id=%s error_type=%s",
                dataset_id,
                user_id,
                type(status_error).__name__,
            )
        logger.warning(
            "Dataset profiling failed dataset_id=%s user_id=%s stage=%s error_type=%s",
            dataset_id,
            user_id,
            stage,
            type(cause).__name__,
        )

    @staticmethod
    def _completed_values(result: ProfileResult) -> dict[str, object]:
        return {
            "row_count": result.row_count,
            "column_count": result.column_count,
            "schema_json": result.schema,
            "missing_values_json": result.missing_values,
            "duplicate_summary_json": result.duplicate_summary,
            "numeric_summary_json": result.numeric_summary,
            "categorical_summary_json": result.categorical_summary,
            "date_summary_json": result.date_summary,
            "outlier_summary_json": result.outlier_summary,
            "quality_issues_json": result.quality_issues,
            "profile_status": DatasetProfileStatus.COMPLETED.value,
            "profile_version": 1,
            "profiled_at": datetime.now(timezone.utc),
        }
