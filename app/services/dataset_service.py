import logging
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    CloudinaryDeleteFailedError,
    CloudinaryUploadFailedError,
    DatasetDeleteFailedError,
    DatasetNotFoundError,
    DatasetUploadFailedError,
)
from app.models.dataset import Dataset, DatasetUploadStatus
from app.models.user import User
from app.repositories.dataset_repository import DatasetRepository
from app.services.cloudinary_service import (
    CloudinaryDeleteError,
    CloudinaryService,
    CloudinaryUploadError,
)
from app.services.file_validation_service import FileValidationService

logger = logging.getLogger(__name__)


class DatasetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.datasets = DatasetRepository(session)
        self.file_validator = FileValidationService()
        self.cloudinary = CloudinaryService()

    async def upload_dataset(self, upload: UploadFile, user: User) -> Dataset:
        dataset_id = uuid4()
        user_id = user.id

        try:
            validated_file = await self.file_validator.validate(upload)
            stored_file_name = f"{dataset_id}.{validated_file.file_type}"

            try:
                cloudinary_result = await self.cloudinary.upload_dataset_file(
                    file_object=upload.file,
                    user_id=user_id,
                    dataset_id=dataset_id,
                    file_type=validated_file.file_type,
                )
            except CloudinaryUploadError as exc:
                raise CloudinaryUploadFailedError from exc

            dataset = Dataset(
                id=dataset_id,
                user_id=user_id,
                original_file_name=validated_file.original_file_name,
                stored_file_name=stored_file_name,
                file_type=validated_file.file_type,
                mime_type=validated_file.mime_type,
                file_size=cloudinary_result.file_size,
                cloudinary_url=cloudinary_result.secure_url,
                cloudinary_public_id=cloudinary_result.public_id,
                cloudinary_resource_type=cloudinary_result.resource_type,
                upload_status=DatasetUploadStatus.UPLOADED.value,
            )

            try:
                await self.datasets.create(dataset)
                await self.session.commit()
            except SQLAlchemyError as exc:
                await self.session.rollback()
                await self._cleanup_failed_upload(
                    public_id=cloudinary_result.public_id,
                    resource_type=cloudinary_result.resource_type,
                    user_id=user_id,
                    dataset_id=dataset_id,
                )
                logger.error(
                    "Dataset metadata save failed dataset_id=%s user_id=%s error_type=%s",
                    dataset_id,
                    user_id,
                    type(exc).__name__,
                )
                raise DatasetUploadFailedError from exc

            logger.info(
                "Dataset upload completed dataset_id=%s user_id=%s",
                dataset_id,
                user_id,
            )
            return dataset
        finally:
            await upload.close()

    async def get_user_datasets(self, user: User) -> list[Dataset]:
        return await self.datasets.list_for_user(user.id)

    async def get_dataset(self, dataset_id: UUID, user: User) -> Dataset:
        dataset = await self.datasets.get_for_user(
            dataset_id=dataset_id,
            user_id=user.id,
        )
        if dataset is None:
            raise DatasetNotFoundError
        return dataset

    async def delete_dataset(self, dataset_id: UUID, user: User) -> None:
        dataset = await self.get_dataset(dataset_id, user)
        user_id = user.id
        owned_dataset_id = dataset.id

        try:
            await self.cloudinary.delete_dataset_file(
                public_id=dataset.cloudinary_public_id,
                resource_type=dataset.cloudinary_resource_type,
                user_id=user_id,
                dataset_id=owned_dataset_id,
            )
        except CloudinaryDeleteError as exc:
            raise CloudinaryDeleteFailedError from exc

        try:
            await self.datasets.delete(dataset)
            await self.session.commit()
        except SQLAlchemyError as exc:
            await self.session.rollback()
            logger.error(
                "Dataset metadata delete failed dataset_id=%s user_id=%s error_type=%s",
                owned_dataset_id,
                user_id,
                type(exc).__name__,
            )
            raise DatasetDeleteFailedError from exc

        logger.info(
            "Dataset delete completed dataset_id=%s user_id=%s",
            owned_dataset_id,
            user_id,
        )

    async def _cleanup_failed_upload(
        self,
        *,
        public_id: str,
        resource_type: str,
        user_id: UUID,
        dataset_id: UUID,
    ) -> None:
        try:
            await self.cloudinary.delete_dataset_file(
                public_id=public_id,
                resource_type=resource_type,
                user_id=user_id,
                dataset_id=dataset_id,
            )
        except CloudinaryDeleteError as exc:
            logger.error(
                "Cloudinary cleanup failed dataset_id=%s user_id=%s error_type=%s",
                dataset_id,
                user_id,
                type(exc).__name__,
            )
