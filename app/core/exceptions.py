from typing import Any

from fastapi import Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base exception for errors safe to expose to API clients."""

    def __init__(self, code: str, message: str, status_code: int, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class DatabaseConnectionError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATABASE_CONNECTION_ERROR",
            message="Unable to connect to the database.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class DuplicateEmailError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="EMAIL_ALREADY_REGISTERED",
            message="An account with this email already exists.",
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidCredentialsError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_CREDENTIALS",
            message="Invalid email or password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class InvalidAccessTokenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_ACCESS_TOKEN",
            message="A valid access token is required.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class InvalidRefreshTokenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_REFRESH_TOKEN",
            message="The refresh token is invalid, expired, or revoked.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class InactiveUserError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INACTIVE_USER",
            message="This user account is inactive.",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class MissingFileNameError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="MISSING_FILE_NAME",
            message="The uploaded file must have a filename.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class UnsupportedFileTypeError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="UNSUPPORTED_FILE_TYPE",
            message="Supported file types are CSV, XLSX, XLS, JSON, and Parquet.",
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )


class FileTooLargeError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="FILE_TOO_LARGE",
            message="Uploaded file exceeds the maximum allowed size.",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )


class EmptyFileError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="EMPTY_FILE",
            message="The uploaded file must not be empty.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class DatasetNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_NOT_FOUND",
            message="Dataset not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class DatasetUploadFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_UPLOAD_FAILED",
            message="Unable to save the uploaded dataset.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class DatasetDeleteFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_DELETE_FAILED",
            message="Unable to delete the dataset.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class CloudinaryUploadFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="CLOUDINARY_UPLOAD_FAILED",
            message="Unable to upload the dataset file.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


class CloudinaryDeleteFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="CLOUDINARY_DELETE_FAILED",
            message="Unable to delete the stored dataset file.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


class DatasetProfileNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_PROFILE_NOT_FOUND",
            message="Dataset profile not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class DatasetDownloadFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_DOWNLOAD_FAILED",
            message="The dataset file could not be retrieved.",
            status_code=status.HTTP_502_BAD_GATEWAY,
        )


class DatasetParseFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_PARSE_FAILED",
            message="The uploaded dataset could not be parsed.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class DatasetProfileFailedError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_PROFILE_FAILED",
            message="The dataset could not be profiled.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class ProfileRowLimitExceededError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="PROFILE_ROW_LIMIT_EXCEEDED",
            message="The dataset exceeds the maximum supported profiling row count.",
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )


class UnsupportedDataStructureError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="UNSUPPORTED_DATA_STRUCTURE",
            message="The dataset structure is not supported for tabular profiling.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class ConversationNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class InvalidConversationTitleError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_CONVERSATION_TITLE",
            message="Conversation title must contain 1 to 200 characters.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class MessageEmptyError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="MESSAGE_EMPTY",
            message="The query must not be empty.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class QueryTooLongError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="QUERY_TOO_LONG",
            message="The query must not exceed 5000 characters.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class InvalidLLMProviderError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="INVALID_LLM_PROVIDER",
            message="The selected LLM provider is not supported.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )


class AnalysisRunNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="ANALYSIS_RUN_NOT_FOUND",
            message="Analysis run not found.",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class DatasetNotProfiledError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="DATASET_NOT_PROFILED",
            message="The dataset must be profiled before analysis can begin.",
            status_code=status.HTTP_409_CONFLICT,
        )


class AnalysisRunNotExecutableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            code="ANALYSIS_RUN_NOT_EXECUTABLE",
            message="Only a pending analysis run can be executed.",
            status_code=status.HTTP_409_CONFLICT,
        )


class DuplicateAnalysisRunError(AppError):
    def __init__(self, analysis_run_id: Any, run_status: str) -> None:
        super().__init__(
            code="DUPLICATE_ANALYSIS_RUN",
            message="A similar analysis already exists for this dataset.",
            status_code=status.HTTP_409_CONFLICT,
            details={"analysis_run_id": str(analysis_run_id), "status": run_status},
        )


class LLMRequestError(AppError):
    _STATUS_CODES = {
        "LLM_PROVIDER_UNAVAILABLE": status.HTTP_503_SERVICE_UNAVAILABLE,
        "LLM_AUTHENTICATION_FAILED": status.HTTP_502_BAD_GATEWAY,
        "LLM_RATE_LIMITED": status.HTTP_429_TOO_MANY_REQUESTS,
        "LLM_TIMEOUT": status.HTTP_504_GATEWAY_TIMEOUT,
        "LLM_INVALID_RESPONSE": status.HTTP_502_BAD_GATEWAY,
        "LLM_EXECUTION_FAILED": status.HTTP_502_BAD_GATEWAY,
    }

    def __init__(self, code: str, message: str) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=self._STATUS_CODES.get(
                code,
                status.HTTP_502_BAD_GATEWAY,
            ),
        )


class AnalysisPlanInvalidError(AppError):
    def __init__(self, message: str = "The generated analysis plan is invalid.") -> None:
        super().__init__("ANALYSIS_PLAN_INVALID", message, status.HTTP_502_BAD_GATEWAY)


class AnalysisPlanNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "ANALYSIS_PLAN_NOT_FOUND",
            "Analysis plan not found.",
            status.HTTP_404_NOT_FOUND,
        )


class AnalysisPlanPersistenceError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "ANALYSIS_PLAN_PERSISTENCE_FAILED",
            "The analysis plan could not be saved.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class AgentExecutionError(AppError):
    _MESSAGES = {
        "AGENT_SUPERVISOR_FAILED": "The supervisor could not evaluate the request.",
        "AGENT_PROFILE_INTERPRETER_FAILED": "The dataset profile could not be interpreted.",
        "AGENT_PLANNER_FAILED": "The analysis plan could not be generated.",
    }

    def __init__(self, code: str) -> None:
        super().__init__(
            code,
            self._MESSAGES.get(code, "The analysis agent could not complete its work."),
            status.HTTP_502_BAD_GATEWAY,
        )


class AnalysisToolError(AppError):
    _MESSAGES = {
        "ANALYSIS_TOOL_VALIDATION_FAILED": "The planned analytical operation is invalid for this dataset.",
        "ANALYSIS_TOOL_EXECUTION_FAILED": "The analytical operation could not be completed.",
        "ANALYSIS_METHOD_NOT_SUPPORTED": "The planned analytical method is not supported yet.",
        "EVIDENCE_PERSISTENCE_FAILED": "The analytical evidence could not be saved.",
        "STATISTICAL_TEST_FAILED": "The statistical test could not be completed.",
        "STATISTICAL_VALIDATION_FAILED": "The statistical result could not be validated.",
        "CLAIM_GENERATION_FAILED": "Evidence-backed claims could not be generated.",
        "CLAIM_VALIDATION_FAILED": "A generated claim could not be validated.",
        "CLAIM_PERSISTENCE_FAILED": "The generated claims could not be saved.",
        "CRITIC_VALIDATION_FAILED": "A claim review could not be validated.",
        "CRITIC_EXECUTION_FAILED": "The claim review could not be completed.",
        "VISUALIZATION_FAILED": "Supporting visualizations could not be prepared.",
        "CHART_SPEC_INVALID": "A chart specification was invalid.",
        "REPORT_GENERATION_FAILED": "The final report could not be generated.",
        "REPORT_VALIDATION_FAILED": "The final report could not be validated.",
        "REPORT_PERSISTENCE_FAILED": "The final report could not be saved.",
    }

    def __init__(self, code: str) -> None:
        super().__init__(code, self._MESSAGES[code], status.HTTP_422_UNPROCESSABLE_CONTENT if code in {"ANALYSIS_TOOL_VALIDATION_FAILED", "ANALYSIS_METHOD_NOT_SUPPORTED"} else status.HTTP_500_INTERNAL_SERVER_ERROR)


class ReportNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("REPORT_NOT_FOUND", "Analysis report not found.", status.HTTP_404_NOT_FOUND)


def _error_payload(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        payload["error"]["details"] = details
    return payload


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_payload(exc.code, exc.message, exc.details),
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    del request
    messages = [error["msg"] for error in exc.errors()]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=_error_payload("VALIDATION_ERROR", "; ".join(messages)),
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    del request, exc
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=_error_payload(
            "INTERNAL_SERVER_ERROR",
            "An unexpected error occurred.",
        ),
    )
