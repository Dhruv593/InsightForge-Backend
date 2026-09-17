import logging
import time
import cloudinary.utils
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.models.dataset import Dataset

logger = logging.getLogger(__name__)

ALLOWED_DATASET_ASSET_HOSTS = frozenset({"res.cloudinary.com"})
DOWNLOAD_TIMEOUT_SECONDS = 30.0
DOWNLOAD_CHUNK_SIZE = 1024 * 1024


class DatasetFileDownloadError(Exception):
    """Internal error raised when a stored dataset asset cannot be retrieved."""


class DatasetFileService:
    def __init__(self) -> None:
        settings = get_settings()
        self.max_download_size = settings.max_upload_size_mb * 1024 * 1024
        self.cloudinary_cloud_name = settings.cloudinary_cloud_name

    async def download(self, dataset: Dataset) -> bytes:
        parsed_url = urlparse(dataset.cloudinary_url)
        path_parts = [part for part in parsed_url.path.split("/") if part]
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname not in ALLOWED_DATASET_ASSET_HOSTS
            or parsed_url.username is not None
            or parsed_url.port not in {None, 443}
            or not path_parts
            or path_parts[0] != self.cloudinary_cloud_name
        ):
            logger.warning(
                "Dataset download rejected dataset_id=%s user_id=%s reason=invalid_host",
                dataset.id,
                dataset.user_id,
            )
            raise DatasetFileDownloadError

        download_url = dataset.cloudinary_url
        if "/raw/authenticated/" in parsed_url.path:
            expected_id = f"insightforge/datasets/{dataset.user_id}/{dataset.id}.{dataset.file_type}"
            if dataset.cloudinary_public_id != expected_id:
                raise DatasetFileDownloadError
            settings = get_settings()
            download_url = cloudinary.utils.private_download_url(
                expected_id, None, resource_type="raw", type="authenticated",
                expires_at=int(time.time()) + 60,
                cloud_name=settings.cloudinary_cloud_name,
                api_key=settings.cloudinary_api_key.get_secret_value(),
                api_secret=settings.cloudinary_api_secret.get_secret_value(),
                secure=True,
            )

        timeout = httpx.Timeout(DOWNLOAD_TIMEOUT_SECONDS, connect=10.0)
        downloaded = bytearray()
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    content_length = response.headers.get("content-length")
                    if (
                        content_length is not None
                        and int(content_length) > self.max_download_size
                    ):
                        raise DatasetFileDownloadError

                    async for chunk in response.aiter_bytes(DOWNLOAD_CHUNK_SIZE):
                        downloaded.extend(chunk)
                        if len(downloaded) > self.max_download_size:
                            raise DatasetFileDownloadError
        except DatasetFileDownloadError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "Dataset download failed dataset_id=%s user_id=%s error_type=%s",
                dataset.id,
                dataset.user_id,
                type(exc).__name__,
            )
            raise DatasetFileDownloadError from exc

        if not downloaded:
            raise DatasetFileDownloadError
        return bytes(downloaded)
