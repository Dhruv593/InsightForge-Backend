import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as pandas_types

from app.services.dataset_loader_service import LoadedDataset
from app.utils.json_utils import to_json_safe

MISSING_LOW_MAX_PERCENTAGE = 5.0
MISSING_MEDIUM_MAX_PERCENTAGE = 20.0
HIGH_CARDINALITY_RATIO = 0.90
HIGH_CARDINALITY_MIN_VALUES = 20
CATEGORICAL_MAX_UNIQUE_VALUES = 50
CATEGORICAL_MAX_UNIQUE_RATIO = 0.20
CATEGORICAL_LOW_UNIQUE_VALUES = 20
CATEGORICAL_SMALL_DATASET_MAX_RATIO = 0.50
DATETIME_PARSE_RATIO = 0.90
DATETIME_SAMPLE_SIZE = 1000
TOP_VALUES_LIMIT = 10
IQR_OUTLIER_MULTIPLIER = 1.5

DATE_COLUMN_NAME_PATTERN = re.compile(
    r"(^|[\s_-])(date|time|datetime|timestamp|created|updated)([\s_-]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProfileResult:
    row_count: int
    column_count: int
    schema: dict[str, Any]
    missing_values: dict[str, Any]
    duplicate_summary: dict[str, Any]
    numeric_summary: dict[str, Any]
    categorical_summary: dict[str, Any]
    date_summary: dict[str, Any]
    outlier_summary: dict[str, Any]
    quality_issues: list[dict[str, Any]]


class DeterministicDatasetProfiler:
    def profile(self, loaded: LoadedDataset) -> ProfileResult:
        dataframe = loaded.dataframe
        row_count, column_count = dataframe.shape
        column_names = self._normalize_column_names(loaded)
        dataframe.columns = column_names
        name_counts = Counter(column_names)

        schema_columns: list[dict[str, Any]] = []
        missing_columns: list[dict[str, Any]] = []
        numeric_summary: dict[str, Any] = {}
        categorical_summary: dict[str, Any] = {}
        date_summary: dict[str, Any] = {}
        outlier_summary: dict[str, Any] = {}
        quality_issues: list[dict[str, Any]] = [
            {
                "code": warning.code,
                "severity": "low",
                "message": warning.message,
            }
            for warning in loaded.warnings
        ]

        duplicate_names = sorted(
            name for name, count in name_counts.items() if count > 1
        )
        if duplicate_names:
            quality_issues.append(
                {
                    "code": "DUPLICATE_COLUMN_NAMES",
                    "severity": "high",
                    "columns": duplicate_names,
                    "message": "The dataset contains duplicate column names.",
                },
            )

        total_missing_cells = 0
        for column_index in range(column_count):
            column_name = column_names[column_index]
            summary_key = self._summary_key(
                column_name,
                column_index,
                name_counts[column_name],
            )
            series = dataframe.iloc[:, column_index]
            null_count = int(series.isna().sum())
            non_null_count = int(row_count - null_count)
            unique_count = int(series.nunique(dropna=True))
            null_percentage = self._percentage(null_count, row_count)
            total_missing_cells += null_count

            inferred_type, parsed_dates = self._infer_type(series, column_name)
            schema_columns.append(
                {
                    "name": column_name,
                    "column_index": column_index,
                    "pandas_dtype": str(series.dtype),
                    "inferred_type": inferred_type,
                    "non_null_count": non_null_count,
                    "null_count": null_count,
                    "null_percentage": null_percentage,
                    "unique_count": unique_count,
                },
            )
            missing_columns.append(
                {
                    "column": column_name,
                    "column_index": column_index,
                    "missing_count": null_count,
                    "missing_percentage": null_percentage,
                },
            )

            self._append_missing_issues(
                quality_issues,
                summary_key,
                null_count,
                null_percentage,
                non_null_count,
            )
            if non_null_count > 0 and unique_count <= 1:
                quality_issues.append(
                    {
                        "code": "CONSTANT_COLUMN",
                        "column": summary_key,
                        "severity": "medium",
                        "message": f"Column '{summary_key}' has one distinct non-null value.",
                    },
                )

            unique_ratio = unique_count / non_null_count if non_null_count else 0.0
            if (
                inferred_type in {"categorical", "text"}
                and non_null_count >= HIGH_CARDINALITY_MIN_VALUES
                and unique_ratio >= HIGH_CARDINALITY_RATIO
            ):
                quality_issues.append(
                    {
                        "code": "HIGH_CARDINALITY",
                        "column": summary_key,
                        "severity": "low",
                        "unique_ratio": round(unique_ratio, 6),
                        "message": (
                            f"Column '{summary_key}' has a high ratio of unique values "
                            "and may represent identifiers or free text."
                        ),
                    },
                )

            if inferred_type == "numeric":
                numeric_values, numeric_stats, non_finite_count = self._numeric_stats(
                    series,
                )
                numeric_summary[summary_key] = numeric_stats
                outlier_stats = self._outlier_stats(numeric_values)
                outlier_summary[summary_key] = outlier_stats

                if non_finite_count:
                    quality_issues.append(
                        {
                            "code": "NON_FINITE_NUMERIC_VALUES",
                            "column": summary_key,
                            "severity": "medium",
                            "count": non_finite_count,
                            "message": (
                                f"Column '{summary_key}' contains non-finite numeric values."
                            ),
                        },
                    )
                if outlier_stats["potential_outlier_count"]:
                    quality_issues.append(
                        {
                            "code": "POTENTIAL_OUTLIERS",
                            "column": summary_key,
                            "severity": "low",
                            "count": outlier_stats["potential_outlier_count"],
                            "percentage": outlier_stats[
                                "potential_outlier_percentage"
                            ],
                            "message": (
                                f"Column '{summary_key}' contains values outside the "
                                "1.5×IQR bounds."
                            ),
                        },
                    )
            elif inferred_type in {"categorical", "text", "boolean"}:
                categorical_summary[summary_key] = self._categorical_stats(series)

            if inferred_type == "datetime" and parsed_dates is not None:
                date_summary[summary_key] = self._date_stats(series, parsed_dates)

        duplicate_rows = int(dataframe.duplicated().sum())
        duplicate_percentage = self._percentage(duplicate_rows, row_count)
        if duplicate_rows:
            quality_issues.append(
                {
                    "code": "EXACT_DUPLICATE_ROWS",
                    "severity": "medium",
                    "count": duplicate_rows,
                    "percentage": duplicate_percentage,
                    "message": f"The dataset contains {duplicate_rows} exact duplicate rows.",
                },
            )

        total_cells = row_count * column_count
        result = ProfileResult(
            row_count=int(row_count),
            column_count=int(column_count),
            schema={"columns": schema_columns},
            missing_values={
                "columns": missing_columns,
                "total_missing_cells": total_missing_cells,
                "overall_missing_percentage": self._percentage(
                    total_missing_cells,
                    total_cells,
                ),
            },
            duplicate_summary={
                "duplicate_rows": duplicate_rows,
                "duplicate_percentage": duplicate_percentage,
            },
            numeric_summary=numeric_summary,
            categorical_summary=categorical_summary,
            date_summary=date_summary,
            outlier_summary=outlier_summary,
            quality_issues=quality_issues,
        )
        safe_result = to_json_safe(asdict(result))
        return ProfileResult(**safe_result)

    @staticmethod
    def _normalize_column_names(loaded: LoadedDataset) -> list[str]:
        dataframe = loaded.dataframe
        source_names = loaded.original_column_names
        if len(source_names) != dataframe.shape[1]:
            source_names = [str(name) for name in dataframe.columns]
        return [str(name).strip() for name in source_names]

    @staticmethod
    def _summary_key(column_name: str, column_index: int, name_count: int) -> str:
        display_name = column_name or "[unnamed]"
        if name_count > 1:
            return f"{display_name} [column {column_index + 1}]"
        return display_name

    def _infer_type(
        self,
        series: pd.Series,
        column_name: str,
    ) -> tuple[str, pd.Series | None]:
        if pandas_types.is_bool_dtype(series.dtype):
            return "boolean", None
        if pandas_types.is_datetime64_any_dtype(series.dtype):
            return "datetime", pd.to_datetime(series, errors="coerce", utc=True)
        if pandas_types.is_numeric_dtype(series.dtype):
            return "numeric", None
        if isinstance(series.dtype, pd.CategoricalDtype):
            return "categorical", None

        non_null = series.dropna()
        if non_null.empty:
            return "unknown", None

        string_sample = non_null.astype(str).str.strip().head(DATETIME_SAMPLE_SIZE)
        normalized_values = {value.lower() for value in string_sample.unique()}
        if normalized_values and normalized_values <= {"true", "false", "yes", "no"}:
            return "boolean", None

        if self._is_datetime_like(string_sample, column_name):
            parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
            parsed_ratio = float(parsed.notna().sum()) / len(non_null)
            if parsed_ratio >= DATETIME_PARSE_RATIO:
                return "datetime", parsed

        unique_count = int(non_null.nunique())
        unique_ratio = unique_count / len(non_null)
        if (
            (
                unique_count <= CATEGORICAL_LOW_UNIQUE_VALUES
                and unique_ratio <= CATEGORICAL_SMALL_DATASET_MAX_RATIO
            )
            or (
                unique_count <= CATEGORICAL_MAX_UNIQUE_VALUES
                and unique_ratio <= CATEGORICAL_MAX_UNIQUE_RATIO
            )
        ):
            return "categorical", None
        return "text", None

    @staticmethod
    def _is_datetime_like(sample: pd.Series, column_name: str) -> bool:
        if not DATE_COLUMN_NAME_PATTERN.search(column_name):
            return False
        if sample.str.fullmatch(r"\d+").all():
            return False
        return bool(sample.str.contains(r"[-/:T ]", regex=True).mean() >= 0.80)

    @staticmethod
    def _numeric_stats(
        series: pd.Series,
    ) -> tuple[pd.Series, dict[str, Any], int]:
        numeric = pd.to_numeric(series, errors="coerce")
        numeric_array = numeric.to_numpy(dtype=float, na_value=np.nan)
        non_finite_mask = np.isinf(numeric_array)
        non_finite_count = int(non_finite_mask.sum())
        finite_array = np.where(non_finite_mask, np.nan, numeric_array)
        finite = pd.Series(finite_array).dropna()

        stats = {
            "count": int(finite.count()),
            "mean": finite.mean() if not finite.empty else None,
            "std": finite.std() if len(finite) > 1 else None,
            "min": finite.min() if not finite.empty else None,
            "25%": finite.quantile(0.25) if not finite.empty else None,
            "median": finite.median() if not finite.empty else None,
            "75%": finite.quantile(0.75) if not finite.empty else None,
            "max": finite.max() if not finite.empty else None,
            "zero_count": int((finite == 0).sum()),
            "negative_count": int((finite < 0).sum()),
            "non_finite_count": non_finite_count,
        }
        return finite, to_json_safe(stats), non_finite_count

    def _outlier_stats(self, finite: pd.Series) -> dict[str, Any]:
        if finite.empty:
            return {
                "q1": None,
                "q3": None,
                "iqr": None,
                "lower_bound": None,
                "upper_bound": None,
                "potential_outlier_count": 0,
                "potential_outlier_percentage": 0.0,
            }

        q1 = float(finite.quantile(0.25))
        q3 = float(finite.quantile(0.75))
        iqr = q3 - q1
        lower_bound = q1 - IQR_OUTLIER_MULTIPLIER * iqr
        upper_bound = q3 + IQR_OUTLIER_MULTIPLIER * iqr
        outlier_count = int(
            ((finite < lower_bound) | (finite > upper_bound)).sum(),
        )
        return {
            "q1": q1,
            "q3": q3,
            "iqr": iqr,
            "lower_bound": lower_bound,
            "upper_bound": upper_bound,
            "potential_outlier_count": outlier_count,
            "potential_outlier_percentage": self._percentage(
                outlier_count,
                len(finite),
            ),
        }

    @staticmethod
    def _categorical_stats(series: pd.Series) -> dict[str, Any]:
        non_null = series.dropna()
        counts = non_null.value_counts().head(TOP_VALUES_LIMIT)
        top_values = [
            {"value": to_json_safe(value), "count": int(count)}
            for value, count in counts.items()
        ]
        return {
            "unique_count": int(non_null.nunique()),
            "most_frequent_value": top_values[0]["value"] if top_values else None,
            "most_frequent_count": top_values[0]["count"] if top_values else 0,
            "top_values": top_values,
        }

    @staticmethod
    def _date_stats(series: pd.Series, parsed: pd.Series) -> dict[str, Any]:
        valid_dates = parsed.dropna()
        return {
            "min_date": to_json_safe(valid_dates.min()) if not valid_dates.empty else None,
            "max_date": to_json_safe(valid_dates.max()) if not valid_dates.empty else None,
            "null_count": int(series.isna().sum()),
            "unique_count": int(valid_dates.nunique()),
        }

    @staticmethod
    def _append_missing_issues(
        issues: list[dict[str, Any]],
        column_name: str,
        null_count: int,
        null_percentage: float,
        non_null_count: int,
    ) -> None:
        if null_count == 0:
            return
        if non_null_count == 0:
            issues.append(
                {
                    "code": "EMPTY_COLUMN",
                    "column": column_name,
                    "severity": "high",
                    "message": f"Column '{column_name}' contains no non-null values.",
                },
            )

        if null_percentage <= MISSING_LOW_MAX_PERCENTAGE:
            code, severity = "MISSING_VALUES", "low"
        elif null_percentage <= MISSING_MEDIUM_MAX_PERCENTAGE:
            code, severity = "HIGH_MISSING_VALUES", "medium"
        else:
            code, severity = "HIGH_MISSING_VALUES", "high"
        issues.append(
            {
                "code": code,
                "column": column_name,
                "severity": severity,
                "count": null_count,
                "percentage": null_percentage,
                "message": (
                    f"Column '{column_name}' contains {null_percentage}% missing values."
                ),
            },
        )

    @staticmethod
    def _percentage(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round((numerator / denominator) * 100.0, 6)
