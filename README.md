# Tatparya API

FastAPI backend for the Tatparya autonomous multi-agent data analyst application. Stage 7 adds a provider-consistent Supervisor, Profile Interpreter, and Planner pipeline that produces a validated analysis plan without executing calculations.

## Requirements

- Python 3.11+
- PostgreSQL

## Setup

```bash
cd server
python -m venv .venv
```

On Windows:

```bash
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, then update `DATABASE_URL` for your PostgreSQL installation:

```bash
copy .env.example .env
```

Configure these required and optional authentication settings in `.env`:

```env
JWT_SECRET_KEY=<generate-a-long-random-secret>
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
```

Generate a development secret, for example, with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Never commit the generated secret or your `.env` file.

Configure Cloudinary and upload limits in `.env`:

```env
CLOUDINARY_CLOUD_NAME=<your-cloud-name>
CLOUDINARY_API_KEY=<your-api-key>
CLOUDINARY_API_SECRET=<your-api-secret>
MAX_UPLOAD_SIZE_MB=25
MAX_PROFILE_ROWS=500000
```

Cloudinary credentials are required. Dataset files are uploaded as raw assets; credentials are never returned by the API.

Configure the provider(s) you intend to use:

```env
GEMINI_API_KEY=
GEMINI_MODEL=
GROQ_API_KEY=
GROQ_MODEL=
LLM_REQUEST_TIMEOUT_SECONDS=60
```

Only the selected provider must be configured. The persisted `analysis_runs.llm_provider` controls the complete run; execution never falls back to the other provider.

Create the development database if it does not already exist:

```sql
CREATE DATABASE insightforge;
```

Apply database migrations:

```bash
alembic upgrade head
```

Run the development server:

```bash
uvicorn app.main:app --reload
```

Swagger documentation is available at `http://localhost:8000/docs`.

## Application logging

Console output is intentionally concise. SQL statement/parameter logging is disabled independently of `DEBUG`, so dataset values and tokens are not written to the terminal. Detailed application events are stored as searchable JSON Lines in:

- `logs/insightforge.jsonl` for normal execution and validation events
- `logs/errors.jsonl` for errors only
- `logs/*-<process-id>.jsonl` when Windows has the base file locked during reload

Each analysis failure includes `analysis_run_id`, `agent_run_id` when available, `task_code`, `error_code`, `error_type`, and the exact internal `validation_reason`. Request/response bodies and secrets are not copied into these log files.

Watch errors live in PowerShell:

```powershell
Get-Content .\logs\errors*.jsonl -Wait
```

Find every event for one failed analysis run:

```powershell
Select-String -Path .\logs\*.jsonl -Pattern '<analysis-run-id>'
```

Logging can be adjusted in `.env` with `LOG_LEVEL`, `CONSOLE_LOG_LEVEL`, `SQL_LOG_LEVEL`, `LOG_DIR`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`, and `SQL_ECHO`. Keep `SQL_ECHO=false` unless short-lived SQL diagnostics are explicitly required.

## Endpoints

- `GET /api/v1/health` checks API availability without connecting to PostgreSQL.
- `GET /api/v1/health/db` executes `SELECT 1` to verify PostgreSQL connectivity.
- `POST /api/v1/auth/register` creates a user and authentication session.
- `POST /api/v1/auth/login` authenticates a user and creates a session.
- `POST /api/v1/auth/refresh` rotates a refresh token and issues new tokens.
- `POST /api/v1/auth/logout` revokes a refresh-token session.
- `GET /api/v1/auth/me` returns the authenticated user.
- `POST /api/v1/datasets` uploads a dataset file and stores its metadata.
- `GET /api/v1/datasets` lists the authenticated user's datasets, newest first.
- `GET /api/v1/datasets/{dataset_id}` returns an owned dataset.
- `DELETE /api/v1/datasets/{dataset_id}` deletes an owned dataset asset and metadata.
- `POST /api/v1/datasets/{dataset_id}/profile` creates or refreshes a deterministic dataset profile.
- `GET /api/v1/datasets/{dataset_id}/profile` returns the current stored profile.

### Stage 5 conversations

- `POST /api/v1/conversations` creates a conversation for an owned dataset.
- `GET /api/v1/conversations` lists the current user's conversations by recent activity. Use the optional `dataset_id` query parameter to filter them.
- `GET /api/v1/conversations/{conversation_id}` returns owned conversation metadata.
- `PATCH /api/v1/conversations/{conversation_id}` updates only the title.
- `DELETE /api/v1/conversations/{conversation_id}` deletes the conversation and cascades to its messages and analysis runs, without deleting its dataset.

### Stage 5 messages and analysis runs

- `POST /api/v1/conversations/{conversation_id}/query` atomically creates a user message and linked pending analysis run.
- `GET /api/v1/conversations/{conversation_id}/messages` returns messages oldest first.
- `GET /api/v1/conversations/{conversation_id}/analysis-runs` returns the conversation's runs.
- `GET /api/v1/analysis-runs/{analysis_run_id}` returns one owned run.
- `POST /api/v1/analysis-runs/{analysis_run_id}/execute` executes an owned pending run using its persisted provider.
- `GET /api/v1/analysis-runs/{analysis_run_id}/agent-runs` returns safe execution metadata for an owned run.
- `GET /api/v1/analysis-runs/{analysis_run_id}/plan` returns an owned validated plan and its pending tasks.
- `GET /api/v1/analysis-runs/{analysis_run_id}/claims` returns candidate claims, evidence links, and Critic review metadata.
- `GET /api/v1/analysis-runs/{analysis_run_id}/charts` returns whitelisted chart metadata and data derived from evidence.
- `GET /api/v1/analysis-runs/{analysis_run_id}/report` returns the persisted structured final report.

The query endpoint accepts only `gemini` or `groq` as `llm_provider` (case-insensitive) and requires a completed deterministic profile. It records a pending run; the separate execute endpoint then transitions it through `pending → running → completed/failed`.

Example:

```json
{
  "query": "Why did revenue decline in August?",
  "llm_provider": "gemini"
}
```

Execute the returned run ID without a body:

```http
POST /api/v1/analysis-runs/2bd98f73-c0e5-4fb0-8918-a803f81ed249/execute
Authorization: Bearer <access_token>
```

Successful response shape:

```json
{
  "analysis_run": {
    "id": "2bd98f73-c0e5-4fb0-8918-a803f81ed249",
    "llm_provider": "gemini",
    "status": "completed"
  },
  "message": {
    "role": "assistant",
    "message_type": "analysis_result",
    "content": "The dataset context is available and ready for analysis."
  }
}
```

## Stage 9 validated result pipeline

The supported analysis path is now:

```text
START → load_context → supervisor → profile_interpreter → planner
      → execute_analysis → statistical_validation → generate_claims
      → critic → visualization → report → prepare_response → END
```

Unsupported questions still branch from Supervisor directly to `prepare_response`. Claim Generator sees only the question, completed evidence, and statistical summaries. Candidate claims are limited to 12, linked many-to-many to persisted evidence, and rejected before persistence when codes are duplicated, evidence is missing or unknown, or a number is not traceable to evidence/statistics.

Critic reviews claims sequentially and stores exactly one controlled review per claim: `accepted`, `rejected`, or `needs_more_evidence`, with weak/moderate/strong evidence strength. Corrected wording is preserved in the review and used downstream without overwriting the original claim. Only accepted claims can reach charts, the report, or the assistant response; Stage 9 does not automatically replan a needs-more-evidence claim. Causal wording backed only by correlation and significance language without an available effect size are rejected by deterministic validation in addition to the Critic prompt.

Visualization selects at most four whitelisted chart specifications. It never supplies plotted values: the backend constructs labels, values, series, or heatmap matrices from linked deterministic evidence. If visualization generation fails, the backend derives safe chart specifications from chartable evidence. Claims and the final report are assembled deterministically from persisted evidence and accepted claim links, then formatted into the assistant message.

Migration `20260831_0008_add_claims_charts_reports.py` creates `claims`, `claim_evidence`, `claim_reviews`, `chart_specs`, and `reports`. Apply it manually when ready:

```bash
alembic upgrade head
```

Every Stage 9 model call uses the provider persisted on the analysis run and creates its own `agent_runs` record (`claim_generator`, `critic:C#`, `visualization`, and `report`). There is no fallback or provider mixing.

### Stage 9 manual checks

After applying the migration and starting the applications yourself, try:

1. `Which region generated the highest revenue?` Expect a grounded regional claim, likely a bar chart, and a concise report.
2. `Why did revenue decrease in March?` Expect period and contributor evidence, Critic-reviewed findings, useful charts only, and causal limitations.
3. `Is revenue related to units sold?` Expect a deterministic coefficient, cautious relationship wording, and possibly a scatter plot—never causation.
4. `Is revenue significantly different between regions?` Confirm the report separates significance, effect size, business interpretation, and assumptions.
5. With mocked correlation evidence of `0.72`, submit the candidate wording `Higher marketing spend caused higher revenue.` The Critic must reject it or correct it to non-causal association wording.

Inspect Stage 9 persistence:

```sql
SELECT id, analysis_run_id, claim_code, claim_text, claim_type, status, created_at
FROM claims ORDER BY created_at;

SELECT cr.claim_id, c.claim_code, cr.status, cr.evidence_strength,
       cr.issues_json, cr.missing_analysis_json, cr.corrected_wording
FROM claim_reviews cr
JOIN claims c ON c.id = cr.claim_id
ORDER BY cr.created_at;

SELECT id, analysis_run_id, chart_code, chart_type, title, x_column,
       y_column, group_column, evidence_codes_json, purpose
FROM chart_specs ORDER BY created_at;

SELECT id, analysis_run_id, executive_summary, key_findings_json,
       statistical_findings_json, data_notes_json, limitations_json,
       recommendations_json, created_at
FROM reports ORDER BY created_at DESC;
```

End-to-end traceability:

```sql
SELECT ar.id AS analysis_run_id, at.task_code, e.evidence_code,
       sv.method_used, sv.p_value, c.claim_code, c.status AS claim_status,
       cr.status AS review_status, cr.evidence_strength,
       r.id AS report_id, r.executive_summary
FROM analysis_runs ar
LEFT JOIN analysis_plans ap ON ap.analysis_run_id = ar.id
LEFT JOIN analysis_tasks at ON at.analysis_plan_id = ap.id
LEFT JOIN evidence e ON e.analysis_task_id = at.id
LEFT JOIN statistical_validations sv ON sv.evidence_id = e.id
LEFT JOIN claim_evidence ce ON ce.evidence_id = e.id
LEFT JOIN claims c ON c.id = ce.claim_id
LEFT JOIN claim_reviews cr ON cr.claim_id = c.id
LEFT JOIN reports r ON r.analysis_run_id = ar.id
ORDER BY ar.created_at, at.priority, e.evidence_code, c.claim_code;
```

Stage 9 adds no RAG, vector storage, long-term memory, unrestricted Python/SQL, background queues, automatic Critic retry loop, or report export.

Stage 6 introduced the provider-neutral execution foundation through an acknowledgement graph. Stage 7 replaces that active acknowledgement pipeline with the planning graph below while retaining its provider adapters, transaction boundaries, and durable agent-run logging.

## Stage 7 planning pipeline

The active graph is now:

```text
START → load_context → supervisor
                         ├─ unsupported → prepare_response → END
                         └─ supported → profile_interpreter → planner
                                           → prepare_response → END
```

All LLM invocations use the single provider persisted on the analysis run. Structured LLM responses are limited to machine-readable control decisions: supervisor routing, planning, claim critique, and visualization recommendations. Profile interpretation, analytical/statistical tool selection, claims, and report assembly are deterministic. Analytical and statistical narratives use plain-text generation with numeric grounding and deterministic fallback. Each invocation receives bounded verified context and creates a separate `agent_runs` row with usage, latency, and status. There is no cross-provider fallback.

### Interrupted analysis recovery

Provider calls retry once for transient errors or invalid output; malformed structured responses receive a correction instruction. Authentication errors are not retried. These retries do not replay persistence or analytical operations.

When planning fails after a validated supervisor decision, verified numeric target metrics can receive a limited whole-dataset summary. The report explicitly states that requested filters, comparisons, and periods were not applied. Missing or ambiguous target metrics do not trigger guessed calculations.

Failed optional statistical checks and individual analytical tasks are disclosed in the report. If the workflow stops, recovery reads committed results after rollback, preserves an existing report or builds one from accepted descriptive claims, and saves an assistant answer. Unreviewed calculations may appear as clearly identified data notes; rejected claims are excluded. With no results, the saved response explains that calculations failed and lists the available dataset context and a next step. A completed run means a response was delivered, not that every requested calculation succeeded; consult its limitations. The same report endpoints and PDF export remain available.

Ownership, authentication, profiling requirements, run locking, and persistence errors remain enforced. A database outage can prevent both normal execution and recovery from being saved. Live provider and browser checks are separate from the mocked recovery regression suite in `tests/test_recovery.py`.

The Supervisor classifies the request and determines dataset support. The Profile Interpreter selects relevant verified columns and quality constraints without recalculating the deterministic profile. The Planner creates at most ten pending tasks from a controlled analysis-type set. Python validation rejects invented columns, duplicate task codes, missing/self dependencies, cycles, non-positive priorities, and unsupported types before persistence.

Migration `20260831_0006_add_analysis_plans_and_tasks.py` adds:

- `analysis_plans`: one validated plan per analysis run, objective/strategy, target metric, statistics/visualization flags, completion criteria, limitations, and status.
- `analysis_tasks`: task code, objective, controlled type, method, JSONB required columns/dependencies, priority, and pending status.

The plan and all tasks are staged in the same transaction as the assistant plan message and completed analysis-run state. Any insertion failure rolls the transaction back, so a partial plan is not committed.

Stage 7 creates a plan only. It does not read raw dataset rows, calculate results, execute statistics, generate evidence, create charts, or produce reports.

## Stage 8 deterministic analytical execution

Stage 8 extends the supported path to:

```text
START → load_context → supervisor → profile_interpreter → planner
      → execute_analysis → statistical_validation → prepare_response → END
```

Unsupported questions still branch from Supervisor directly to `prepare_response`. Supported plans are persisted, their tasks run sequentially in deterministic topological order, and a failed dependency causes its dependents to be marked `skipped`. Regression remains intentionally unsupported and fails safely with `ANALYSIS_METHOD_NOT_SUPPORTED`.

The architectural boundary is explicit: LLMs select a controlled tool and interpret its returned result; Python, DuckDB, Pandas, and SciPy perform every calculation. Raw dataset rows are never sent to the provider. The analysis layer downloads the existing Cloudinary object through the established file service, loads a working DataFrame copy, and never changes the source object. It does not impute nulls or remove outliers automatically.

Controlled analytical tools are `groupby_aggregate`, `filter_dataset`, `calculate_percentage_change`, `calculate_contribution`, `calculate_correlation`, `distribution_summary`, and `time_series_aggregate`. Column names, numeric compatibility, filters, aggregation names, date bounds, frequencies, sort direction, and result limits are validated before execution. DuckDB handles the internally constructed group-by query; it never accepts model-written SQL. Pandas handles bounded filtering, changes, contribution, correlation, distribution, and time-series operations.

Statistical validation supports Pearson and Spearman correlation, chi-square, independent and Welch t-tests, Mann–Whitney U, and one-way ANOVA. Normality and equal-variance diagnostics are stored with the result. The centralized alpha is `0.05`; actual p-values, effect sizes where defined, t-test confidence intervals, warnings, validity, and a cautious grounded interpretation are persisted. Statistical significance is not presented as business significance, and correlation is not presented as causation.

Migration `20260831_0007_add_evidence_and_statistical_validations.py` expands the task lifecycle to `pending`, `running`, `completed`, `failed`, and `skipped`, and adds the `evidence` and `statistical_validations` tables. Apply it manually when ready:

```bash
alembic upgrade head
```

Development inspection endpoints are ownership-protected:

```http
GET /api/v1/analysis-runs/{analysis_run_id}/evidence
GET /api/v1/analysis-runs/{analysis_run_id}/statistical-validations
Authorization: Bearer <access_token>
```

### Stage 8 manual checks

After manually applying the migration and starting both applications, upload/profile the business dataset and try:

1. `Which region generated the highest revenue?` Compare the evidence with `df.groupby("Region")["Revenue"].sum().sort_values(ascending=False)`.
2. `Why did revenue decrease in March?` Compare period totals with `df.assign(Date=pd.to_datetime(df["Date"])).groupby(pd.Grouper(key="Date", freq="ME"))["Revenue"].sum()` and independently group the February/March change by region or product.
3. `Is revenue related to units sold?` Compare with `df["Revenue"].corr(df["Units_Sold"])` and confirm the response avoids causal language.
4. `Is revenue significantly different between regions?` Inspect the selected deterministic test, assumptions, p-value, effect size, confidence information where applicable, and warnings.

Evidence inspection:

```sql
SELECT id, analysis_run_id, analysis_task_id, evidence_code, method,
       columns_used_json, filters_json, operation_json, result_json,
       interpretation, limitations_json, created_at
FROM evidence
ORDER BY created_at;
```

Statistical validation inspection:

```sql
SELECT id, analysis_run_id, analysis_task_id, evidence_id,
       method_requested, method_used, p_value, effect_size,
       confidence_interval_json, is_significant, is_valid,
       warnings_json, interpretation
FROM statistical_validations
ORDER BY created_at;
```

End-to-end traceability:

```sql
SELECT ar.id AS analysis_run_id, ar.status AS run_status,
       ap.id AS analysis_plan_id, at.id AS analysis_task_id,
       at.task_code, at.status AS task_status,
       e.id AS evidence_id, e.evidence_code, e.method AS evidence_method,
       sv.id AS statistical_validation_id, sv.method_used,
       sv.p_value, sv.effect_size, sv.is_valid
FROM analysis_runs ar
LEFT JOIN analysis_plans ap ON ap.analysis_run_id = ar.id
LEFT JOIN analysis_tasks at ON at.analysis_plan_id = ap.id
LEFT JOIN evidence e ON e.analysis_task_id = at.id
LEFT JOIN statistical_validations sv ON sv.analysis_task_id = at.id
ORDER BY ar.created_at, at.priority, at.task_code, e.created_at;
```

Stage 8 deliberately does not add a Critic Agent, claims, claim reviews, charts, reports, PDF export, RAG, long-term memory, or unrestricted code/SQL execution.

### Stage 7 manual checks

After `alembic upgrade head`, use the existing frontend flow with either provider:

1. Ask `Why did revenue decrease in March?` against a profiled business dataset.
2. Confirm the run completes with three successful agent runs: `supervisor`, `profile_interpreter`, and `planner`.
3. Confirm all three agent runs use the provider selected when the query was created.
4. Confirm the assistant message lists planned steps and explicitly says calculations have not run.
5. Read `GET /api/v1/analysis-runs/{run_id}/plan` and confirm its tasks use only real dataset columns.
6. Ask `How did competitor pricing affect our revenue?` when competitor data is absent. Confirm only Supervisor runs, no plan is created, the run completes, and the assistant explains the missing data.

Inspect Stage 7 persistence:

```sql
SELECT id, analysis_run_id, question_type, objective, target_metric,
       analysis_strategy, requires_statistics, requires_visualization, status
FROM analysis_plans
ORDER BY created_at DESC;

SELECT id, analysis_plan_id, task_code, objective, analysis_type, method,
       required_columns_json, depends_on_json, priority, status
FROM analysis_tasks
ORDER BY priority, task_code;

SELECT analysis_run_id, agent_name, provider, model, status,
       prompt_tokens, completion_tokens, total_tokens, latency_ms
FROM agent_runs
ORDER BY created_at;
```

## Stage 6 database and execution boundaries

Migration `20260831_0005_add_agent_runs_table.py` adds `agent_runs` with UUID identity, cascading `analysis_run_id`, agent/provider/model/status, bounded JSONB input and output, provider token usage, request latency, safe errors, and timezone-aware lifecycle timestamps.

Execution uses two transactions. The first conditionally changes only a pending run to running and creates a running `pipeline_test` agent record. No database transaction remains open while the provider request is in flight. A second transaction atomically persists either the validated output, assistant message, and completed states, or safe failed states. The conditional update prevents ordinary concurrent requests from executing one run twice.

## Manual Stage 6 verification

1. Add credentials and model names for Gemini, Groq, or both to `.env`.
2. From `server/`, activate `.venv`, install requirements, and run `alembic upgrade head`.
3. Start the backend with `python -m uvicorn app.main:app --reload`.
4. Start the frontend separately, log in, upload and profile a dataset, and create a conversation.
5. Select Gemini, submit a query, and confirm the UI shows `Analyzing…` followed by the persisted assistant acknowledgement and a completed run.
6. Inspect `GET /api/v1/analysis-runs/{run_id}/agent-runs`; confirm both run records use `gemini` and the configured Gemini model.
7. Repeat with Groq and confirm both records use `groq` and the configured Groq model.
8. For failure handling, create a new run with a temporarily invalid credential and execute it. Expect both records to be failed, a safe error, and no assistant message.
9. Execute a completed or failed run again. Expect `409 ANALYSIS_RUN_NOT_EXECUTABLE` and no second provider call.

Direct API testing follows the same sequence: call `/conversations/{conversation_id}/query`, copy `analysis_run.id`, then call `/analysis-runs/{run_id}/execute`. The frontend performs these two calls automatically.

PostgreSQL inspection:

```sql
SELECT id, conversation_id, llm_provider, status, started_at, completed_at,
       error_code, error_message
FROM analysis_runs
ORDER BY created_at DESC;

SELECT id, analysis_run_id, agent_name, provider, model, status,
       prompt_tokens, completion_tokens, total_tokens, latency_ms,
       error_code, created_at
FROM agent_runs
ORDER BY created_at DESC;

SELECT m.content AS user_question, ar.id AS analysis_run_id,
       agr.id AS agent_run_id, agr.provider, agr.model, agr.status,
       reply.id AS assistant_message_id, reply.content AS assistant_response
FROM analysis_runs ar
JOIN messages m ON m.analysis_run_id = ar.id AND m.role = 'user'
LEFT JOIN agent_runs agr ON agr.analysis_run_id = ar.id
LEFT JOIN messages reply ON reply.analysis_run_id = ar.id AND reply.role = 'assistant'
ORDER BY ar.created_at DESC;
```

Protected routes require an access token:

```text
Authorization: Bearer <access_token>
```

All dataset endpoints require this access-token header. Supported dataset formats are CSV, XLSX, XLS, JSON, and Parquet. Uploads must be non-empty and may not exceed `MAX_UPLOAD_SIZE_MB`.

## Deterministic dataset profiling

Profiling uses Pandas, NumPy, OpenPyXL, xlrd, and PyArrow. It calculates:

- row and column counts
- column schema and conservative inferred types
- missing-value counts and percentages
- exact duplicate rows
- numeric summaries
- categorical top values
- date ranges
- potential outliers using the 1.5×IQR method
- deterministic data-quality issues

Profiling is limited to `MAX_PROFILE_ROWS`. Excel workbooks use only the first worksheet and report a warning when more sheets exist. Profiling does not modify the uploaded dataset.

Test them with:

```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:8000/api/v1/health/db
```

Run automated tests:

```bash
pytest
```

Stage 5 coverage is in `tests/test_stage5.py`. It includes ownership, validation, chronological history, cascade deletion, message/run linking, and transaction rollback checks.

Authentication integration tests require a separate PostgreSQL database and a `TEST_DATABASE_URL` ending in a database name that contains `test`:

```env
TEST_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/insightforge_test
```

Create it once with:

```sql
CREATE DATABASE insightforge_test;
```
