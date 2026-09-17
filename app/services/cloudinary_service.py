import asyncio
import logging
from dataclasses import dataclass
from typing import Any, BinaryIO
from uuid import UUID

import cloudinary
import cloudinary.uploader

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class CloudinaryUploadError(Exception):
    """Internal provider error raised when a Cloudinary upload fails."""


class CloudinaryDeleteError(Exception):
    """Internal provider error raised when a Cloudinary deletion fails."""


@dataclass(frozen=True, slots=True)
class CloudinaryUploadResult:
    secure_url: str
    public_id: str
    resource_type: str
    file_size: int
    file_format: str | None


class CloudinaryService:
    def __init__(self) -> None:
        settings = get_settings()
        cloudinary.config(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key.get_secret_value(),
            api_secret=settings.cloudinary_api_secret.get_secret_value(),
            secure=True,
        )

    async def upload_dataset_file(
        self,
        *,
        file_object: BinaryIO,
        user_id: UUID,
        dataset_id: UUID,
        file_type: str,
    ) -> CloudinaryUploadResult:
        public_id = f"insightforge/datasets/{user_id}/{dataset_id}.{file_type}"
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                cloudinary.uploader.upload,
                file_object,
                public_id=public_id,
                resource_type="raw",
                type="authenticated",
                overwrite=False,
                unique_filename=False,
                use_filename=False,
            )
            result = self._parse_upload_response(response)
        except Exception as exc:
            logger.warning(
                "Cloudinary upload failed dataset_id=%s user_id=%s error_type=%s",
                dataset_id,
                user_id,
                type(exc).__name__,
            )
            raise CloudinaryUploadError from exc

        logger.info(
            "Cloudinary upload succeeded dataset_id=%s user_id=%s",
            dataset_id,
            user_id,
        )
        return result

    async def delete_dataset_file(
        self,
        *,
        public_id: str,
        resource_type: str,
        user_id: UUID,
        dataset_id: UUID,
        delivery_type: str = "authenticated",
    ) -> None:
        try:
            response: dict[str, Any] = await asyncio.to_thread(
                cloudinary.uploader.destroy,
                public_id,
                resource_type=resource_type,
                type=delivery_type,
                invalidate=True,
            )
            if response.get("result") not in {"ok", "not found"}:
                raise CloudinaryDeleteError
        except CloudinaryDeleteError:
            logger.warning(
                "Cloudinary delete failed dataset_id=%s user_id=%s error_type=%s",
                dataset_id,
                user_id,
                "unexpected_provider_result",
            )
            raise
        except Exception as exc:
            logger.warning(
                "Cloudinary delete failed dataset_id=%s user_id=%s error_type=%s",
                dataset_id,
                user_id,
                type(exc).__name__,
            )
            raise CloudinaryDeleteError from exc

        logger.info(
            "Cloudinary delete succeeded dataset_id=%s user_id=%s",
            dataset_id,
            user_id,
        )

    @staticmethod
    def _parse_upload_response(response: dict[str, Any]) -> CloudinaryUploadResult:
        secure_url = response.get("secure_url")
        public_id = response.get("public_id")
        resource_type = response.get("resource_type")
        file_size = response.get("bytes")

        if (
            not isinstance(secure_url, str)
            or not isinstance(public_id, str)
            or not isinstance(resource_type, str)
            or not isinstance(file_size, int)
        ):
            raise CloudinaryUploadError

        file_format = response.get("format")
        return CloudinaryUploadResult(
            secure_url=secure_url,
            public_id=public_id,
            resource_type=resource_type,
            file_size=file_size,
            file_format=file_format if isinstance(file_format, str) else None,
        )
