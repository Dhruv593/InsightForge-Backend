from enum import Enum


DEFAULT_CONVERSATION_TITLE = "New Analysis"
MAX_CONVERSATION_TITLE_LENGTH = 200
MAX_QUERY_LENGTH = 5_000


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class MessageType(str, Enum):
    TEXT = "text"
    ANALYSIS_RESULT = "analysis_result"
    SYSTEM_EVENT = "system_event"


class LLMProvider(str, Enum):
    GEMINI = "gemini"
    GROQ = "groq"


class AnalysisRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


PIPELINE_TEST_AGENT_NAME = "pipeline_test"
MAX_CONVERSATION_CONTEXT_MESSAGES = 10

SUPERVISOR_AGENT_NAME = "supervisor"
PROFILE_INTERPRETER_AGENT_NAME = "profile_interpreter"
PLANNER_AGENT_NAME = "planner"
MAX_ANALYSIS_TASKS = 10
MAX_PROFILE_COLUMNS_IN_CONTEXT = 200
MAX_QUALITY_ISSUES_IN_CONTEXT = 20


class AnalysisPlanStatus(str, Enum):
    CREATED = "created"
    VALIDATED = "validated"
    FAILED = "failed"


class AnalysisTaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class AnalysisTaskType(str, Enum):
    AGGREGATION = "aggregation"
    COMPARISON = "comparison"
    SEGMENTATION = "segmentation"
    CORRELATION = "correlation"
    STATISTICAL_TEST = "statistical_test"
    REGRESSION = "regression"
    TIME_SERIES = "time_series"
    DISTRIBUTION = "distribution"
    DATA_QUALITY = "data_quality"


STATISTICAL_ALPHA = 0.05
SUPPORTED_ANALYTICS_TOOLS = frozenset({
    "groupby_aggregate", "filter_dataset", "calculate_percentage_change",
    "calculate_contribution", "calculate_correlation", "distribution_summary",
    "time_series_aggregate",
})

MAX_CLAIMS_PER_RUN = 12
MAX_CHARTS_PER_RUN = 4
SUPPORTED_CHART_TYPES = frozenset({
    "line", "bar", "horizontal_bar", "grouped_bar", "stacked_bar",
    "scatter", "histogram", "boxplot", "pie", "donut", "heatmap",
    "waterfall",
})
