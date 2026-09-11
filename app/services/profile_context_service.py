from typing import Any

from app.core.analysis_constants import (
    MAX_PROFILE_COLUMNS_IN_CONTEXT,
    MAX_QUALITY_ISSUES_IN_CONTEXT,
)
from app.models.dataset_profile import DatasetProfile


class ProfileContextService:
    def build(self, profile: DatasetProfile, *, file_name: str) -> dict[str, Any]:
        columns = profile.schema_json.get("columns", [])[:MAX_PROFILE_COLUMNS_IN_CONTEXT]
        return {
            "file_name": file_name,
            "row_count": profile.row_count,
            "column_count": profile.column_count,
            "columns": [
                {
                    "name": column.get("name"),
                    "inferred_type": column.get("inferred_type", "unknown"),
                    "missing_percentage": column.get("null_percentage", 0),
                }
                for column in columns
                if column.get("name")
            ],
            "quality_issues": [
                {
                    "code": issue.get("code"),
                    "severity": issue.get("severity"),
                    "column": issue.get("column"),
                    "message": issue.get("message"),
                }
                for issue in profile.quality_issues_json[:MAX_QUALITY_ISSUES_IN_CONTEXT]
            ],
        }

    @staticmethod
    def column_names(context: dict[str, Any]) -> set[str]:
        return {column["name"] for column in context.get("columns", [])}
