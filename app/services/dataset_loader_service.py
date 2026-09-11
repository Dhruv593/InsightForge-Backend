import csv
import io
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as parquet


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
        column_names = [str(name) for name in parquet_file.schema.names]
        buffer.seek(0)
        dataframe = pd.read_parquet(buffer, engine="pyarrow")
        return LoadedDataset(dataframe, column_names, [])

    def _enforce_row_limit(self, dataframe: pd.DataFrame) -> None:
        if len(dataframe.index) > self.max_rows:
            raise DatasetRowLimitError

    @staticmethod
    def _enforce_flat_structure(dataframe: pd.DataFrame) -> None:
        if dataframe.shape[1] == 0:
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
