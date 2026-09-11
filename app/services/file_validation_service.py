import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import (
    EmptyFileError,
    FileTooLargeError,
    MissingFileNameError,
    UnsupportedFileTypeError,
)

SUPPORTED_DATASET_EXTENSIONS = frozenset({"csv", "xlsx", "xls", "json", "parquet"})

ALLOWED_MIME_TYPES: dict[str, frozenset[str]] = {
    "csv": frozenset(
        {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"},
    ),
    "xlsx": frozenset(
        {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ),
    "xls": frozenset(
        {"application/vnd.ms-excel", "application/x-msexcel"},
    ),
    "json": frozenset({"application/json", "text/json", "text/plain"}),
    "parquet": frozenset(
        {"application/vnd.apache.parquet", "application/x-parquet"},
    ),
}

GENERIC_BINARY_MIME_TYPE = "application/octet-stream"
READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ValidatedDatasetFile:
    original_file_name: str
    file_type: str
    mime_type: str
    file_size: int


class FileValidationService:
    def __init__(self) -> None:
        self.max_upload_size = get_settings().max_upload_size_mb * 1024 * 1024

    async def validate(self, upload: UploadFile) -> ValidatedDatasetFile:
        original_file_name = self._sanitize_filename(upload.filename)
        file_type = Path(original_file_name).suffix.removeprefix(".").lower()

        if file_type not in SUPPORTED_DATASET_EXTENSIONS:
            raise UnsupportedFileTypeError

        mime_type = (upload.content_type or GENERIC_BINARY_MIME_TYPE).lower()
        allowed_types = ALLOWED_MIME_TYPES[file_type]
        if mime_type != GENERIC_BINARY_MIME_TYPE and mime_type not in allowed_types:
            raise UnsupportedFileTypeError

        file_size = await self._measure_file(upload)
        if file_size == 0:
            raise EmptyFileError

        return ValidatedDatasetFile(
            original_file_name=original_file_name,
            file_type=file_type,
            mime_type=mime_type,
            file_size=file_size,
        )

    async def _measure_file(self, upload: UploadFile) -> int:
        file_size = 0
        try:
            while chunk := await upload.read(READ_CHUNK_SIZE):
                file_size += len(chunk)
                if file_size > self.max_upload_size:
                    raise FileTooLargeError
        finally:
            await upload.seek(0)
        return file_size

    @staticmethod
    def _sanitize_filename(filename: str | None) -> str:
        if filename is None:
            raise MissingFileNameError

        base_name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
        if not base_name or base_name in {".", ".."}:
            raise MissingFileNameError

        sanitized = re.sub(r"[^A-Za-z0-9._ -]", "_", base_name).strip(" .")
        if not sanitized:
            raise MissingFileNameError

        suffix = Path(sanitized).suffix
        if suffix and len(suffix) < 32:
            stem = sanitized[: -len(suffix)]
            return f"{stem[: 255 - len(suffix)]}{suffix}"
        return sanitized[:255]
