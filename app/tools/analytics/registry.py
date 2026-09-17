from typing import Any

import duckdb
import numpy as np
import pandas as pd

from app.schemas.analysis_execution import ToolExecutionResult
from app.utils.json_utils import to_json_safe
from app.core.analysis_constants import SUPPORTED_ANALYTICS_TOOLS

ALLOWED_AGGREGATIONS = {"sum", "mean", "median", "count", "min", "max"}
ALLOWED_FILTERS = {"equals", "not_equals", "greater_than", "less_than", "greater_equal", "less_equal", "between", "in", "date_range"}
FREQUENCIES = {"daily": "D", "weekly": "W", "monthly": "ME", "quarterly": "QE", "yearly": "YE"}


class ToolValidationError(Exception):
    pass


class AnalyticsToolRegistry:
    def execute(self, dataframe: pd.DataFrame, tool: str, parameters: dict[str, Any]) -> ToolExecutionResult:
        if not isinstance(parameters, dict):
            raise ToolValidationError("Tool parameters must be an object.")
        if tool not in SUPPORTED_ANALYTICS_TOOLS:
            raise ToolValidationError("Unsupported analytical tool.")
        frame = dataframe.copy(deep=False)
        handler = getattr(self, f"_{tool}", None)
        if handler is None or tool.startswith("_"):
            raise ToolValidationError("Unsupported analytical tool.")
        result, columns, filters, warnings = handler(frame, parameters)
        return ToolExecutionResult(tool=tool, columns_used=columns, filters=filters, result=to_json_safe(result), warnings=warnings)

    @staticmethod
    def _columns(frame: pd.DataFrame, names: list[str]) -> None:
        unknown = [name for name in names if name not in frame.columns]
        if unknown:
            available = ", ".join(str(name) for name in frame.columns)
            missing = ", ".join(repr(name) for name in unknown)
            raise ToolValidationError(f"Unknown column(s): {missing}. Available columns: {available}.")

    def _apply_filters(self, frame: pd.DataFrame, filters: list[dict[str, Any]]) -> pd.DataFrame:
        if not isinstance(filters, list):
            raise ToolValidationError("Filters must be a list.")
        result = frame.copy()
        for condition in filters:
            if not isinstance(condition, dict):
                raise ToolValidationError("Each filter must be an object.")
            column, operator = condition.get("column"), condition.get("operator")
            if column not in result.columns or operator not in ALLOWED_FILTERS:
                raise ToolValidationError("Invalid filter condition.")
            value = condition.get("value")
            series = result[column]
            try:
                if operator == "equals": mask = series == value
                elif operator == "not_equals": mask = series != value
                elif operator == "greater_than": mask = series > value
                elif operator == "less_than": mask = series < value
                elif operator == "greater_equal": mask = series >= value
                elif operator == "less_equal": mask = series <= value
                elif operator in {"between", "date_range"}:
                    values = condition.get("values")
                    if not isinstance(values, list) or len(values) != 2:
                        raise ToolValidationError("Range filters require exactly two values.")
                    if operator == "date_range":
                        parsed = pd.to_datetime(series, errors="coerce")
                        bounds = pd.to_datetime(values, errors="coerce")
                        if bounds.isna().any():
                            raise ToolValidationError("Date-range bounds must be valid dates.")
                        mask = parsed.between(bounds[0], bounds[1])
                    else: mask = series.between(values[0], values[1])
                else:
                    values = condition.get("values")
                    if not isinstance(values, list): raise ToolValidationError("In filters require a value list.")
                    mask = series.isin(values)
            except ToolValidationError:
                raise
            except (TypeError, ValueError) as exc:
                raise ToolValidationError("Filter value is incompatible with the selected column.") from exc
            result = result.loc[mask.fillna(False)]
        return result

    def _groupby_aggregate(self, frame, p):
        group_by, metric, aggregation = p.get("group_by"), p.get("metric"), p.get("aggregation")
        if not isinstance(group_by, list) or not group_by:
            raise ToolValidationError("groupby_aggregate requires a non-empty group_by list.")
        if not isinstance(metric, str) or not metric:
            raise ToolValidationError("groupby_aggregate requires a metric column.")
        if aggregation not in ALLOWED_AGGREGATIONS:
            raise ToolValidationError(f"groupby_aggregate requires one of these aggregations: {', '.join(sorted(ALLOWED_AGGREGATIONS))}.")
        self._columns(frame, [*group_by, metric])
        if aggregation in {"sum", "mean", "median"}:
            self._numeric(frame, metric)
        filters = p.get("filters", [])
        filtered = self._apply_filters(frame, filters)
        quote = lambda name: '"' + str(name).replace('"', '""') + '"'
        aggregation_sql = {"mean": "avg", "median": "median"}.get(aggregation, aggregation)
        select_groups = ", ".join(quote(name) for name in group_by)
        query = f"SELECT {select_groups}, {aggregation_sql}({quote(metric)}) AS value FROM dataset GROUP BY {select_groups}"
        connection = duckdb.connect(database=":memory:")
        try:
            connection.register("dataset", filtered)
            output = connection.execute(query).fetchdf()
        finally: connection.close()
        ascending = p.get("sort", "desc") == "asc"
        output = output.sort_values("value", ascending=ascending).head(self._limit(p))
        return output.to_dict("records"), [*group_by, metric], filters, self._data_warnings(filtered, metric)

    def _filter_dataset(self, frame, p):
        filters = p.get("filters", [])
        columns = p.get("columns") or list(frame.columns)
        self._columns(frame, columns)
        output = self._apply_filters(frame, filters)[columns].head(self._limit(p))
        return output.to_dict("records"), columns, filters, ["Result rows are limited for safe evidence storage."]

    def _calculate_percentage_change(self, frame, p):
        metric, aggregation = p.get("metric"), p.get("aggregation", "sum")
        self._columns(frame, [metric])
        self._numeric(frame, metric)
        if aggregation not in ALLOWED_AGGREGATIONS: raise ToolValidationError("Unsupported aggregation.")
        previous_filters, current_filters = p.get("previous_filters"), p.get("current_filters")
        if not previous_filters or not current_filters or previous_filters == current_filters:
            raise ToolValidationError("Percentage change requires distinct previous and current filters.")
        previous = self._aggregate(self._apply_filters(frame, previous_filters)[metric], aggregation)
        current = self._aggregate(self._apply_filters(frame, current_filters)[metric], aggregation)
        absolute = current - previous
        percentage = None if previous == 0 else absolute / abs(previous) * 100
        warnings = self._data_warnings(frame, metric)
        if previous == 0: warnings.append("Percentage change is undefined because the previous value is zero.")
        return {"previous_value": previous, "current_value": current, "absolute_change": absolute, "percentage_change": percentage}, [metric], [*p.get("previous_filters", []), *p.get("current_filters", [])], warnings

    def _calculate_contribution(self, frame, p):
        dimension, metric = p.get("dimension"), p.get("metric")
        self._columns(frame, [dimension, metric])
        self._numeric(frame, metric)
        baseline_filters, current_filters = p.get("baseline_filters"), p.get("current_filters")
        if not baseline_filters or not current_filters or baseline_filters == current_filters:
            raise ToolValidationError("Contribution analysis requires distinct baseline and current filters.")
        previous = self._apply_filters(frame, baseline_filters).groupby(dimension, dropna=False)[metric].sum()
        current = self._apply_filters(frame, current_filters).groupby(dimension, dropna=False)[metric].sum()
        joined = pd.concat([previous.rename("previous"), current.rename("current")], axis=1).fillna(0)
        joined["change"] = joined["current"] - joined["previous"]
        total_change = float(joined["change"].sum())
        joined["contribution_percentage"] = None if total_change == 0 else joined["change"] / total_change * 100
        output = joined.reset_index().sort_values("change").head(self._limit(p)).to_dict("records")
        return {"total_change": total_change, "contributions": output}, [dimension, metric], [*baseline_filters, *current_filters], self._data_warnings(frame, metric)

    def _calculate_correlation(self, frame, p):
        x, y, method = p.get("x"), p.get("y"), p.get("method", "pearson")
        self._columns(frame, [x, y])
        if x == y: raise ToolValidationError("Correlation requires two different columns.")
        self._numeric(frame, x); self._numeric(frame, y)
        if method not in {"pearson", "spearman"}: raise ToolValidationError("Unsupported correlation method.")
        values = frame[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
        if len(values) < 3: raise ToolValidationError("Correlation requires at least three complete observations.")
        coefficient = float(values[x].corr(values[y], method=method))
        warnings = ["Correlation does not establish causation.", *self._data_warnings(frame, x), *self._data_warnings(frame, y)]
        return {"coefficient": coefficient, "sample_size": len(values), "method": method}, [x, y], [], list(dict.fromkeys(warnings))

    def _distribution_summary(self, frame, p):
        column = p.get("column"); self._columns(frame, [column])
        self._numeric(frame, column)
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if values.empty: raise ToolValidationError("Distribution requires numeric observations.")
        return {"count": int(values.count()), "mean": float(values.mean()), "median": float(values.median()), "std": float(values.std()), "min": float(values.min()), "q1": float(values.quantile(.25)), "q3": float(values.quantile(.75)), "max": float(values.max())}, [column], [], self._data_warnings(frame, column)

    def _time_series_aggregate(self, frame, p):
        date_column, metric, frequency, aggregation = p.get("date_column"), p.get("metric"), p.get("frequency"), p.get("aggregation", "sum")
        if not isinstance(date_column, str) or not date_column:
            raise ToolValidationError("time_series_aggregate requires a date_column.")
        if not isinstance(metric, str) or not metric:
            raise ToolValidationError("time_series_aggregate requires a metric column.")
        if not isinstance(frequency, str) or not frequency:
            raise ToolValidationError("time_series_aggregate requires a frequency.")
        self._columns(frame, [date_column, metric])
        self._numeric(frame, metric)
        if frequency not in FREQUENCIES or aggregation not in ALLOWED_AGGREGATIONS: raise ToolValidationError("Invalid time-series parameters.")
        filters = p.get("filters", []); filtered = self._apply_filters(frame, filters).copy()
        parsed = pd.to_datetime(filtered[date_column], errors="coerce"); invalid = int(parsed.isna().sum())
        if filtered[date_column].notna().any() and parsed.notna().sum() == 0:
            raise ToolValidationError("The selected date column contains no valid dates.")
        filtered[date_column] = parsed; filtered = filtered.dropna(subset=[date_column])
        output = filtered.set_index(date_column)[metric].resample(FREQUENCIES[frequency]).agg(aggregation).dropna().reset_index()
        warnings = self._data_warnings(filtered, metric)
        if invalid: warnings.append(f"{invalid} rows had invalid dates and were excluded.")
        return output.head(self._limit(p)).to_dict("records"), [date_column, metric], filters, warnings

    @staticmethod
    def _aggregate(series, operation):
        numeric = pd.to_numeric(series, errors="coerce")
        value = getattr(numeric, operation)()
        if pd.isna(value): raise ToolValidationError("Aggregation produced no numeric value.")
        return float(value)

    @staticmethod
    def _numeric(frame, column):
        source = frame[column]
        converted = pd.to_numeric(source, errors="coerce")
        if converted.notna().sum() < source.notna().sum():
            raise ToolValidationError("The selected operation requires a numeric column.")

    @staticmethod
    def _limit(p):
        limit = p.get("limit", 100)
        if not isinstance(limit, int) or not 1 <= limit <= 500: raise ToolValidationError("Limit must be between 1 and 500.")
        return limit

    @staticmethod
    def _data_warnings(frame, column):
        count = int(frame[column].isna().sum())
        warnings = [f"{count} missing {column} values were ignored; no imputation was applied."] if count else []
        numeric = pd.to_numeric(frame[column], errors="coerce").dropna()
        if len(numeric) >= 4:
            q1, q3 = numeric.quantile(.25), numeric.quantile(.75)
            iqr = q3 - q1
            outliers = int(((numeric < q1 - 1.5 * iqr) | (numeric > q3 + 1.5 * iqr)).sum())
            if outliers:
                warnings.append(f"{outliers} potential {column} outliers were retained; no automatic removal was applied.")
        return warnings
