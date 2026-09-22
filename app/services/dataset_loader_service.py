import csv
import io
import json
import zipfile
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet
from app.core.config import get_settings


class DatasetParseError(Exception):
    """Internal error raised when a supported file cannot be parsed."""


class UnsupportedDatasetStructureError(Exception):
    """Internal error raised when parsed data is not a flat table."""


class DatasetRowLimitError(Exception):
    """Internal error raised when a dataset exceeds the configured row limit."""


@dataclass(frozen=True, slots=True)
class LoaderWarning:
    code: str
    message: str


@dataclass(slots=True)
class LoadedDataset:
    dataframe: pd.DataFrame
    original_column_names: list[str]
    warnings: list[LoaderWarning]


class DatasetLoaderService:
    def __init__(self, max_rows: int) -> None:
        self.max_rows = max_rows

    def load(self, file_bytes: bytes, file_type: str) -> LoadedDataset:
        try:
            if file_type == "xlsx":
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                    entries = archive.infolist()
                    if len(entries) > 10000 or sum(item.file_size for item in entries) > get_settings().max_expanded_file_mb * 1024 * 1024:
                        raise UnsupportedDatasetStructureError
            if file_type == "csv":
                loaded = self._load_csv(file_bytes)
            elif file_type == "xlsx":
                loaded = self._load_excel(file_bytes, engine="openpyxl")
            elif file_type == "xls":
                loaded = self._load_excel(file_bytes, engine="xlrd")
            elif file_type == "json":
                loaded = self._load_json(file_bytes)
            elif file_type == "parquet":
                loaded = self._load_parquet(file_bytes)
            else:
                raise DatasetParseError

            self._enforce_flat_structure(loaded.dataframe)
            self._enforce_row_limit(loaded.dataframe)
            return loaded
        except (DatasetRowLimitError, UnsupportedDatasetStructureError):
            raise
        except Exception as exc:
            raise DatasetParseError from exc

    def preview(self, file_bytes: bytes, file_type: str, limit: int, offset: int = 0) -> LoadedDataset:
        """Load one page of rows for the read-only UI preview."""
        preview_rows = limit + 1
        try:
            if file_type == "csv":
                text = self._decode_csv(file_bytes)
                header = next(csv.reader(io.StringIO(text)), [])
                dataframe = pd.read_csv(
                    io.StringIO(text),
                    nrows=preview_rows,
                    skiprows=(lambda row: 0 < row <= offset) if offset else None,
                )
                names = [str(name) for name in header] if len(header) == dataframe.shape[1] else [str(name) for name in dataframe.columns]
                loaded = LoadedDataset(dataframe, names, [])
            elif file_type in {"xlsx", "xls"}:
                if file_type == "xlsx":
                    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
                        entries = archive.infolist()
                        if len(entries) > 10000 or sum(item.file_size for item in entries) > get_settings().max_expanded_file_mb * 1024 * 1024:
                            raise UnsupportedDatasetStructureError
                engine = "openpyxl" if file_type == "xlsx" else "xlrd"
                workbook = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
                if not workbook.sheet_names:
                    raise UnsupportedDatasetStructureError
                first_sheet = workbook.sheet_names[0]
                header_frame = workbook.parse(first_sheet, header=None, nrows=1)
                dataframe = workbook.parse(
                    first_sheet,
                    nrows=preview_rows,
                    skiprows=(lambda row: 0 < row <= offset) if offset else None,
                )
                names = [str(name) for name in dataframe.columns] if header_frame.empty else ["" if pd.isna(value) else str(value) for value in header_frame.iloc[0].tolist()]
                if len(names) != dataframe.shape[1]:
                    names = [str(name) for name in dataframe.columns]
                warnings = [LoaderWarning("MULTIPLE_SHEETS_DETECTED", "Workbook contains multiple sheets. Only the first sheet is shown.")] if len(workbook.sheet_names) > 1 else []
                loaded = LoadedDataset(dataframe, names, warnings)
            elif file_type == "json":
                loaded = self._load_json(file_bytes)
                loaded.dataframe = loaded.dataframe.iloc[offset : offset + preview_rows]
            elif file_type == "parquet":
                parquet_file = parquet.ParquetFile(io.BytesIO(file_bytes))
                if sum(parquet_file.metadata.row_group(i).total_byte_size for i in range(parquet_file.metadata.num_row_groups)) > get_settings().max_expanded_file_mb * 1024 * 1024:
                    raise UnsupportedDatasetStructureError
                frames: list[pd.DataFrame] = []
                remaining_offset = offset
                remaining_rows = preview_rows
                for batch in parquet_file.iter_batches(batch_size=max(preview_rows, 1024)):
                    if remaining_offset >= batch.num_rows:
                        remaining_offset -= batch.num_rows
                        continue
                    frame = batch.to_pandas().iloc[
                        remaining_offset : remaining_offset + remaining_rows
                    ]
                    frames.append(frame)
                    remaining_rows -= len(frame.index)
                    remaining_offset = 0
                    if remaining_rows <= 0:
                        break
                dataframe = (
                    pd.concat(frames, ignore_index=True)
                    if frames
                    else pd.DataFrame(columns=parquet_file.schema.names)
                )
                loaded = LoadedDataset(dataframe, [str(name) for name in parquet_file.schema.names], [])
            else:
                raise DatasetParseError
            self._enforce_flat_structure(loaded.dataframe)
            return loaded
        except UnsupportedDatasetStructureError:
            raise
        except Exception as exc:
            raise DatasetParseError from exc

    def _load_csv(self, file_bytes: bytes) -> LoadedDataset:
        text = self._decode_csv(file_bytes)
        header = next(csv.reader(io.StringIO(text)), [])
        dataframe = pd.read_csv(io.StringIO(text), nrows=self.max_rows + 1)
        column_names = (
            [str(name) for name in header]
            if len(header) == dataframe.shape[1]
            else [str(name) for name in dataframe.columns]
        )
        return LoadedDataset(dataframe, column_names, [])

    def _load_excel(self, file_bytes: bytes, *, engine: str) -> LoadedDataset:
        workbook = pd.ExcelFile(io.BytesIO(file_bytes), engine=engine)
        if not workbook.sheet_names:
            raise UnsupportedDatasetStructureError

        first_sheet = workbook.sheet_names[0]
        header_frame = workbook.parse(first_sheet, header=None, nrows=1)
        dataframe = workbook.parse(first_sheet, nrows=self.max_rows + 1)
        if header_frame.empty:
            column_names = [str(name) for name in dataframe.columns]
        else:
            column_names = [
                "" if pd.isna(value) else str(value)
                for value in header_frame.iloc[0].tolist()
            ]
            if len(column_names) != dataframe.shape[1]:
                column_names = [str(name) for name in dataframe.columns]

        warnings: list[LoaderWarning] = []
        if len(workbook.sheet_names) > 1:
            warnings.append(
                LoaderWarning(
                    code="MULTIPLE_SHEETS_DETECTED",
                    message=(
                        "Workbook contains multiple sheets. Only the first sheet "
                        "was profiled."
                    ),
                ),
            )
        return LoadedDataset(dataframe, column_names, warnings)

    def _load_json(self, file_bytes: bytes) -> LoadedDataset:
        payload = json.loads(file_bytes.decode("utf-8-sig"))
        if isinstance(payload, list):
            if not all(isinstance(row, dict) for row in payload):
                raise UnsupportedDatasetStructureError
            dataframe = pd.DataFrame(payload)
        elif isinstance(payload, dict):
            if all(isinstance(value, list) for value in payload.values()):
                dataframe = pd.DataFrame(payload)
            elif all(not isinstance(value, (dict, list)) for value in payload.values()):
                dataframe = pd.DataFrame([payload])
            else:
                raise UnsupportedDatasetStructureError
        else:
            raise UnsupportedDatasetStructureError

        return LoadedDataset(
            dataframe,
            [str(name) for name in dataframe.columns],
            [],
        )

    def _load_parquet(self, file_bytes: bytes) -> LoadedDataset:
        buffer = io.BytesIO(file_bytes)
        parquet_file = parquet.ParquetFile(buffer)
        if parquet_file.metadata.num_rows > self.max_rows:
            raise DatasetRowLimitError
        if sum(parquet_file.metadata.row_group(i).total_byte_size for i in range(parquet_file.metadata.num_row_groups)) > get_settings().max_expanded_file_mb * 1024 * 1024:
            raise UnsupportedDatasetStructureError
        column_names = [str(name) for name in parquet_file.schema.names]
        buffer.seek(0)
        dataframe = pd.read_parquet(buffer, engine="pyarrow")
        return LoadedDataset(dataframe, column_names, [])

    def _enforce_row_limit(self, dataframe: pd.DataFrame) -> None:
        if len(dataframe.index) > self.max_rows:
            raise DatasetRowLimitError

    @staticmethod
    def _enforce_flat_structure(dataframe: pd.DataFrame) -> None:
        if dataframe.shape[1] == 0 or dataframe.shape[1] > get_settings().max_dataset_columns:
            raise UnsupportedDatasetStructureError
        nested_types = (dict, list, tuple, set, np.ndarray)
        for column_index in range(dataframe.shape[1]):
            series = dataframe.iloc[:, column_index].dropna()
            if any(isinstance(value, nested_types) for value in series):
                raise UnsupportedDatasetStructureError

    @staticmethod
    def _decode_csv(file_bytes: bytes) -> str:
        encodings = (
            ("utf-8-sig", "utf-8", "latin-1")
            if file_bytes.startswith(b"\xef\xbb\xbf")
            else ("utf-8", "utf-8-sig", "latin-1")
        )
        for encoding in encodings:
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise DatasetParseError
