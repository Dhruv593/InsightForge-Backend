# Tatparya API — Engineering Documentation

The interactive agent-orchestration diagram is available at [`docs/architecture/tatparya-agent-flow.html`](docs/architecture/tatparya-agent-flow.html); its editable source and validation artifact live in the same directory.

This is the technical reference for maintaining and extending the Tatparya backend. It describes request flow, endpoint ownership, persistence, the multi-agent pipeline, safeguards, and the exact areas normally changed for a new feature.

## 1. Architectural principles

Tatparya separates responsibilities into predictable layers:

```text
HTTP request
  → API router (`app/api`)
  → dependency/authentication check (`app/api/dependencies.py`)
  → service/business transaction (`app/services`)
  → repository/query (`app/repositories`)
  → SQLAlchemy model (`app/models`)
  → PostgreSQL
```

Request and response validation is handled by Pydantic schemas in `app/schemas`. Domain failures use structured `AppError` responses from `app/core/exceptions.py`.

The analysis path adds an orchestration layer:

```text
AnalysisRunService creates pending run
  → AnalysisJobQueue claims it
  → AnalysisExecutionService builds LangGraph workflow
  → agents choose/interpret bounded actions
  → deterministic registries calculate values
  → evidence/statistics/claims/reviews/charts/report persist
  → assistant message persists
```

Important boundaries:

- API routers translate HTTP; they should not contain substantial business logic.
- Services own validation, authorization-sensitive operations, and transaction boundaries.
- Repositories own database queries, not business decisions.
- LLMs do not execute arbitrary Python or SQL.
- Analytical values come from controlled backend tools.
- Chart values are built from persisted evidence rather than invented by the visualization agent.
- Raw rows are not intentionally included in LLM prompts or LangSmith metadata-only tracing.

## 2. Application startup

`app/main.py` creates the FastAPI application.

Startup behavior:

1. Settings are loaded from `app/core/config.py`.
2. JSON Lines logging is configured.
3. `SecurityMiddleware` is installed.
4. CORS allows the exact `FRONTEND_URL` origin.
5. exception handlers and request-ID logging are installed.
6. all API routers are mounted under `API_V1_PREFIX`.
7. the lifespan starts `AnalysisJobQueue`.
8. interrupted `running` analyses are returned to the database-backed pending queue.

The canonical ASGI target is:

```text
app.main:app
```

## 3. Directory map

| Path | Responsibility |
| --- | --- |
| `app/main.py` | FastAPI creation, middleware, router mounting, queue lifespan |
| `app/api/` | HTTP endpoints |
| `app/schemas/` | Request/response and agent/tool data contracts |
| `app/models/` | SQLAlchemy tables and relationships |
| `app/repositories/` | Database reads/writes |
| `app/services/` | Business logic, orchestration, integrations, transactions |
| `app/services/llm/` | Provider-neutral LLM interface plus Gemini/Groq adapters |
| `app/agents/` | Agent wrappers and response validation |
| `app/prompts/` | One prompt module per agent plus shared prompt rules |
| `app/graph/` | LangGraph state, nodes, topology, workflow, Studio entry |
| `app/tools/analytics/` | Controlled deterministic analysis operations |
| `app/tools/statistics/` | Controlled statistical tests |
| `app/core/` | Config, security, errors, tracing, constants, logging |
| `app/db/` | SQLAlchemy base and async session factory |
| `alembic/versions/` | Ordered database migrations |
| `tests/` | Unit and integration coverage |
| `render.yaml` | Render deployment blueprint |
| `langgraph.json` | Optional local LangGraph Studio configuration |

## 4. Configuration

`app/core/config.py` is the source of truth. `get_settings()` is cached, so tests that change environment variables must clear that cache.

### Required runtime configuration

| Variable | Meaning |
| --- | --- |
| `DATABASE_URL` | PostgreSQL URL; managed `postgres://` and `postgresql://` URLs are normalized to Psycopg |
| `JWT_SECRET_KEY` | Signing secret, minimum 32 characters |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary account |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |
| `FRONTEND_URL` | Exact allowed CORS and Google sign-in origin |

At least one complete provider pair is needed for analyses:

- `GEMINI_API_KEY` and `GEMINI_MODEL`
- `GROQ_API_KEY` and `GROQ_MODEL`

### Optional integrations

- Google sign-in: `GOOGLE_CLIENT_ID`
- Email delivery: `SMTP_*`
- LangSmith: `LANGSMITH_*`
- Owner access: comma-separated `ADMIN_EMAILS`

An owner must be active, email-verified, and present in `ADMIN_EMAILS`.

### Production safety

When `APP_ENV=production`, startup rejects:

- `DEBUG=true`
- `SQL_ECHO=true`
- `LANGSMITH_DETAIL_MODE=true`
- non-HTTPS `FRONTEND_URL`
- an obviously unchanged example JWT secret

## 5. Authentication and authorization

### Tokens and sessions

- Access tokens are short-lived JWTs.
- Refresh tokens are associated with persisted `user_sessions` records.
- Refresh rotates the refresh token.
- Logout/revocation invalidates a session.
- `token_version` supports account-wide invalidation.
- Passwords are hashed with the configured `pwdlib[argon2]` implementation.

`app/core/security.py` owns token/password primitives. `app/services/auth_service.py` owns registration, authentication, refresh, and logout. `app/api/dependencies.py` exposes:

- `CurrentUser`: valid Bearer access token required.
- `AdminUser`: current user must satisfy `User.is_admin`.

Every user-owned lookup must include the current user's ID. Do not rely only on a client-supplied resource UUID.

### Google sign-in

`app/api/google_auth.py`:

1. checks the exact request origin;
2. creates a short-lived HttpOnly nonce cookie;
3. returns the public Google client ID and nonce;
4. verifies the Google ID token, audience, nonce, and verified email;
5. creates or loads the local account;
6. issues normal Tatparya access/refresh tokens.

See `GOOGLE_SIGN_IN.md` for console setup.

### Account recovery

`account_tokens` stores hashed, expiring verification/reset tokens. `app/services/account_service.py` creates/consumes tokens and `app/services/email_service.py` delivers links when SMTP is configured.

## 6. Data and analysis lifecycle

### Dataset upload

```text
POST /datasets
  → FileValidationService checks name, extension, size, content
  → CloudinaryService uploads the original file as a raw asset
  → DatasetService saves metadata
```

Supported formats: CSV, XLSX, XLS, JSON, and Parquet.

Limits are enforced before multipart parsing and again during validation/loading. Dataset files are never stored in Git.

### Profiling

```text
POST /datasets/:id/profile
  → verify ownership
  → download Cloudinary object
  → DatasetLoaderService parses a bounded flat table
  → DeterministicDatasetProfiler calculates profile
  → DatasetProfilingService saves profile/status
```

The profile includes rows, columns, inferred types, missing values, exact duplicates, numeric summaries, categorical values, date ranges, and conservative quality warnings. Profiling does not mutate source data, impute missing values, or remove outliers.

### Query and queue

`POST /conversations/:conversationId/query` atomically creates:

- a user message;
- a pending `analysis_runs` row with the chosen provider.

The in-process `AnalysisJobQueue` polls PostgreSQL every 1.5 seconds, executes one analysis at a time, and persists state so interrupted runs can be requeued on startup. It is designed for one Render web process. Multiple workers would require a shared distributed worker/locking design.

`POST /analysis-runs/:id/execute` currently wakes/returns the queued run rather than performing the long provider request in the HTTP handler.

### Multi-agent pipeline

Current supported path:

```text
START
  → load_context
  → supervisor
      ├─ unsupported → prepare_response → END
      └─ supported
          → profile_interpreter
          → planner
          → execute_analysis
          → statistical_validation
          → generate_claims
          → critic
          → visualization
          → report
          → prepare_response
          → END
```

The topology and state contracts are documented in `app/graph/topology.py`. The compiled graph is in `app/graph/workflow.py`; node adapters are in `app/graph/nodes.py`; typed state is in `app/graph/state.py`.

### Agent responsibilities

| Agent/module | Responsibility |
| --- | --- |
| `agents/supervisor.py` | Determine whether the question is supported by available data and route it |
| `agents/profile_interpreter.py` | Select relevant verified columns and profile constraints |
| `agents/planner.py` | Build a bounded dependency-safe analysis plan |
| `agents/analyst.py` | Interpret deterministic analytical outputs |
| `agents/statistical_validator.py` | Produce cautious grounded statistical interpretation |
| `agents/claim_generator.py` | Convert completed evidence into candidate claims |
| `agents/critic.py` | Accept, correct, reject, or request more evidence for claims |
| `agents/visualization.py` | Recommend chart specifications from accepted claims/evidence |
| `agents/report.py` | Produce report language within validated evidence boundaries |

Prompts live only under `app/prompts/`. Modify the corresponding `<agent>_prompt.py` rather than embedding long prompts in services.

### Deterministic analytical tools

`app/tools/analytics/registry.py` supports:

- `groupby_aggregate`
- `filter_dataset`
- `calculate_percentage_change`
- `calculate_contribution`
- `calculate_correlation`
- `distribution_summary`
- `time_series_aggregate`

Column existence, numeric compatibility, filters, date bounds, aggregation, frequency, sort order, and result limits are validated. DuckDB receives backend-built SQL only; model-written SQL is never executed.

### Statistical tools

`app/tools/statistics/registry.py` supports:

- Pearson and Spearman correlation
- chi-square
- independent t-test
- Welch t-test
- Mann–Whitney U
- one-way ANOVA

The result includes p-value, effect size when defined, assumptions, warnings, validity, significance using alpha `0.05`, and confidence intervals for t-tests. Correlation is never treated as proof of causation.

### Claims, visuals, and report

`app/services/analysis_output_service.py` coordinates downstream persistence and deterministic fallbacks.

- At most 12 claims per run.
- Claims link to evidence through `claim_evidence`.
- Critic status is persisted separately in `claim_reviews`.
- Only accepted/corrected supported claims reach customer output.
- At most 4 charts per run.
- Supported chart types are line, bar, horizontal/grouped/stacked bar, scatter, histogram, boxplot, pie, donut, heatmap, and waterfall.
- Chart data is constructed from evidence.
- The report stores summaries, findings, notes/limitations, and recommendations.
- Report generation calls `ReportAgent` using the selected provider, accepted claims, and their evidence. `_generate_report` in `analysis_execution_service.py` falls back to the deterministic report only if generation/validation fails or there are no accepted claims. Numeric values and finding-level evidence links are checked before persistence; database write failures go to global recovery.

### Recovery

`app/services/analysis_recovery.py` attempts to return a useful answer when an optional stage or provider response fails. It reads committed evidence/claims/report after rollback and creates a cautious fallback. Rejected claims are excluded. If no calculations succeeded, it returns verified dataset context and a practical next step rather than exposing an internal exception.

## 7. API reference

All paths below are relative to `/api/v1`.

### Health

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `HEAD` | `/health` | Public | Lightweight uptime probe; no DB query |
| `GET` | `/health` | Public | API process status |
| `GET` | `/health/db` | Public | Runs `SELECT 1` |

### Authentication

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/auth/register` | Public | Create account/session and attempt verification email |
| `POST` | `/auth/login` | Public | Password login |
| `POST` | `/auth/refresh` | Refresh token | Rotate session tokens |
| `POST` | `/auth/logout` | Refresh token | Revoke session |
| `GET` | `/auth/me` | User | Current user and admin state |
| `POST` | `/auth/google/challenge` | Public, valid origin | Set nonce cookie and return Google client ID |
| `POST` | `/auth/google` | Public, nonce cookie | Verify Google credential and issue Tatparya tokens |

### Account

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/account/forgot-password` | Public | Request reset email without account enumeration |
| `POST` | `/account/reset-password` | Reset token | Set new password |
| `POST` | `/account/verify-email` | Verification token | Verify email |
| `POST` | `/account/verification-email` | User | Resend verification |
| `PATCH` | `/account/profile` | User | Update display name |
| `POST` | `/account/password` | User | Add/change password and invalidate sessions as required |
| `GET` | `/account/sessions` | User | List active/recent sessions |
| `DELETE` | `/account/sessions/:sessionId` | User | Revoke one owned session |
| `DELETE` | `/account/sessions` | User | Revoke all sessions |
| `POST` | `/account/delete` | User | Permanently delete account after confirmation |

### Datasets

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/datasets` | User | Validate/upload dataset and save metadata |
| `GET` | `/datasets` | User | List owned datasets |
| `GET` | `/datasets/:datasetId` | Owner | Get dataset metadata |
| `DELETE` | `/datasets/:datasetId` | Owner | Delete metadata and Cloudinary asset |
| `POST` | `/datasets/:datasetId/profile` | Owner | Create or refresh deterministic profile |
| `GET` | `/datasets/:datasetId/profile` | Owner | Read saved profile |

### Conversations

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `POST` | `/conversations` | User | Create conversation for owned dataset |
| `GET` | `/conversations` | User | List conversations; optional `dataset_id` filter |
| `GET` | `/conversations/:conversationId` | Owner | Get conversation |
| `PATCH` | `/conversations/:conversationId` | Owner | Rename conversation |
| `DELETE` | `/conversations/:conversationId` | Owner | Delete conversation and dependent analysis history |
| `POST` | `/conversations/:conversationId/query` | Owner | Add user message and pending run; accepts provider and optional force flag |
| `GET` | `/conversations/:conversationId/messages` | Owner | Chronological messages |
| `GET` | `/conversations/:conversationId/analysis-runs` | Owner | Conversation runs |

### Analysis runs

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `GET` | `/analysis-runs/queue/active` | User | Current user's pending/running runs |
| `POST` | `/analysis-runs/:runId/execute` | Owner | Wake queue and return queue position |
| `POST` | `/analysis-runs/:runId/retry` | Owner | Create a fresh pending run from a failed/cancelled run |
| `POST` | `/analysis-runs/:runId/cancel` | Owner | Mark/cancel pending or running work |
| `GET` | `/analysis-runs/:runId/queue` | Owner | Status and queue position |
| `GET` | `/analysis-runs/:runId/agent-runs` | Owner | Safe agent stage metadata |
| `GET` | `/analysis-runs/:runId/plan` | Owner | Validated plan/tasks |
| `GET` | `/analysis-runs/:runId/evidence` | Owner | Deterministic results |
| `GET` | `/analysis-runs/:runId/statistical-validations` | Owner | Statistical results |
| `GET` | `/analysis-runs/:runId/claims` | Owner | Claims, evidence codes, and review result |
| `GET` | `/analysis-runs/:runId/charts` | Owner | Saved chart specifications/data |
| `GET` | `/analysis-runs/:runId/report` | Owner | Structured report |
| `GET` | `/analysis-runs/:runId` | Owner | Run status and safe errors |

### Monitoring and content

| Method | Path | Access | Behavior |
| --- | --- | --- | --- |
| `GET` | `/monitoring/overview` | Admin | Users, sessions, run/provider/agent metrics and recent failures |
| `GET` | `/site-content/landing` | Public | Published landing content |
| `GET` | `/admin/site-content/landing` | Admin | Editable landing content |
| `PUT` | `/admin/site-content/landing` | Admin | Validate and publish landing content |
| `POST` | `/admin/site-content/images` | Admin | Upload CMS image to Cloudinary |
| `GET` | `/blogs` | Public if enabled | Published post summaries |
| `GET` | `/blogs/:slug` | Public if enabled | Published full post |
| `GET` | `/admin/blogs` | Admin | Draft and published summaries |
| `GET` | `/admin/blogs/:slug` | Admin | Full editable post |
| `POST` | `/admin/blogs` | Admin | Create post |
| `PUT` | `/admin/blogs/:slug` | Admin | Update post/slug/status |
| `DELETE` | `/admin/blogs/:slug` | Admin | Delete post |
| `POST` | `/site-content/contact` | Public | Store a landing-page contact inquiry and attempt the admin notification email |
| `GET` | `/admin/contact-inquiries` | Admin | List/filter inquiries with total and status counts |
| `GET` | `/admin/contact-inquiries/:id` | Admin | Read one inquiry |
| `PATCH` | `/admin/contact-inquiries/:id` | Admin | Mark an inquiry new, read, replied, or closed |
| `POST` | `/admin/contact-inquiries/:id/reply` | Admin | Send the editable contact-reply email and record the reply |

Schemas in `app/schemas` are the authoritative payload/response definition. In development, use `/docs` for live examples.

## 8. Database model map

| Table/model | Purpose and key relationships |
| --- | --- |
| `users` / `User` | Account identity; owns sessions, datasets, conversations, runs, account tokens |
| `user_sessions` / `UserSession` | Refresh-token session lifecycle |
| `account_tokens` / `AccountToken` | Verification and password-reset tokens |
| `datasets` / `Dataset` | Uploaded file metadata and Cloudinary identity |
| `dataset_profiles` / `DatasetProfile` | One deterministic profile per dataset |
| `conversations` / `Conversation` | Dataset-scoped user analysis thread |
| `messages` / `Message` | User/assistant history, optionally linked to a run |
| `analysis_runs` / `AnalysisRun` | Provider, lifecycle, safe error, and root relationship for analysis artifacts |
| `agent_runs` / `AgentRun` | Per-stage provider/model/status/usage/latency metadata |
| `analysis_plans` / `AnalysisPlan` | One validated plan per run |
| `analysis_tasks` / `AnalysisTask` | Ordered/dependent controlled operations |
| `evidence` / `Evidence` | Persisted deterministic tool outputs |
| `statistical_validations` / `StatisticalValidation` | Statistical method/result/assumption records |
| `claims` / `Claim` | Candidate findings |
| `claim_evidence` | Many-to-many claim/evidence traceability |
| `claim_reviews` / `ClaimReview` | Critic decision and corrected wording |
| `chart_specs` / `ChartSpec` | Whitelisted chart metadata plus derived data |
| `reports` / `Report` | One final structured report per run |
| `content_entries` / `ContentEntry` | Versioned landing/blog JSON content keyed by type + slug |

Most user-content relationships cascade on account/dataset/conversation deletion. Review every foreign key and cleanup of external Cloudinary assets when adding a new relationship.

## 9. Module ownership

### API routers

- `api/auth.py`: password auth.
- `api/google_auth.py`: Google nonce/credential flow.
- `api/account.py`: recovery/profile/session/account lifecycle.
- `api/datasets.py`: dataset and profile endpoints.
- `api/conversations.py`: conversations, query creation, messages, runs.
- `api/analysis_runs.py`: queue and analysis artifacts.
- `api/monitoring.py`: owner metrics.
- `api/site_content.py`: landing/blog CMS.
- `api/health.py`: uptime and DB health.

### Important services

- `auth_service.py`, `account_service.py`, `email_service.py`: identity lifecycle.
- `dataset_service.py`: Cloudinary upload/metadata/delete.
- `file_validation_service.py`: safe upload checks.
- `dataset_loader_service.py`: bounded parsing.
- `dataset_profiler.py`, `dataset_profiling_service.py`: deterministic profiling and persistence.
- `conversation_service.py`, `message_service.py`: chat domain.
- `analysis_run_service.py`: pending/retry/cancel/status/ownership.
- `analysis_job_queue.py`: background queue.
- `analysis_execution_service.py`: full run transaction/orchestration.
- `analysis_plan_service.py`, `analysis_task_execution_service.py`: validated tasks and tools.
- `analysis_output_service.py`: claims, reviews, visuals, reports, fallbacks.
- `deterministic_recommendations.py`: domain-neutral evidence-based fallback actions, with a compatibility wrapper for revenue-focused callers.
- `analysis_recovery.py`: safe degraded answer.
- `site_content_service.py`: landing/blog persistence.
- `cloudinary_service.py`: dataset and content-image integration.

### Repositories

There is normally one repository per aggregate/table. Use repository methods for queries so ownership ordering/eager-loading behavior is not duplicated across routers and services.

## 10. Adding a feature

### Add a standard API resource

For a new persisted feature such as saved dashboards:

1. Create `app/models/saved_dashboard.py`.
2. Export it from `app/models/__init__.py` so Alembic metadata can discover it.
3. Add `app/schemas/saved_dashboard.py` for create/update/response validation.
4. Add `app/repositories/saved_dashboard_repository.py` for database operations.
5. Add `app/services/saved_dashboard_service.py` for ownership and transactions.
6. Add `app/api/saved_dashboards.py` with `CurrentUser` or `AdminUser` dependencies.
7. Mount the router in `app/main.py`.
8. Create a new Alembic migration.
9. Add ownership, validation, rollback, and not-found tests.
10. Add the frontend service/page separately.

Do not commit a model change without its migration.

### Add an endpoint to an existing feature

1. Add/extend its request and response schemas.
2. Add repository behavior only if a new query is needed.
3. Implement the business operation in the service.
4. Keep the API function thin.
5. Use a stable structured error code for expected failures.
6. Add tests for authentication, ownership, validation, success, and rollback.

### Add a database field

1. Update the SQLAlchemy model.
2. Update relevant Pydantic schemas.
3. Update service/repository writes and reads.
4. Add an Alembic revision after the current head.
5. Backfill or provide a safe database default for existing rows.
6. Update tests and both documentation files.

Never modify an already-deployed migration to represent a new change.

### Add a new agent

1. Define the output schema in `app/schemas` if structured control output is necessary.
2. Create `app/prompts/<agent_name>_prompt.py`.
3. Create `app/agents/<agent_name>.py`.
4. Add state inputs/outputs to `app/graph/state.py` and `app/graph/topology.py`.
5. Add a node adapter to `app/graph/nodes.py`.
6. Register the node/edges in `app/graph/workflow.py`.
7. Execute it through the common `run_agent` path so `agent_runs` captures status/usage/latency.
8. Add fallback behavior if the stage is optional.
9. Update tracing tests and prompt catalog tests.

Avoid direct agent-to-agent calls. Agents exchange validated state contracts through the graph.

### Change an agent prompt

1. Edit only the matching module under `app/prompts/`.
2. Keep role, input facts, task instructions, constraints, and output expectations clearly separated.
3. Do not request hidden chain-of-thought.
4. Do not place secrets or unrestricted raw rows in the prompt.
5. If structured output changed, update the Pydantic schema and both provider adapters/tests.
6. Run `tests/test_prompt_catalog_unit.py`.

### Add an analytical operation

1. Add its name to `SUPPORTED_ANALYTICS_TOOLS` in `app/core/analysis_constants.py`.
2. Add a private handler in `app/tools/analytics/registry.py`.
3. Validate every column, type, filter, operation, and limit before calculating.
4. Return `ToolExecutionResult` with JSON-safe values, columns, filters, and warnings.
5. Update planning schemas/prompts so the tool can be selected.
6. Update `analysis_task_execution_service.py` if parameter translation is needed.
7. Add unit tests for valid and adversarial parameters.
8. Add fallback/report/chart coverage where applicable.

Never accept model-written Python or SQL.

### Add a statistical test

1. Extend the statistical request schema/allowed test type.
2. Add execution logic to `app/tools/statistics/registry.py`.
3. Define minimum sample requirements and assumptions.
4. Calculate an effect size and confidence interval where meaningful.
5. Return non-finite results as invalid rather than serializing NaN/Infinity.
6. Update prompts, interpretations, tests, and customer-language conversion.

### Add a chart type

1. Add it to `SUPPORTED_CHART_TYPES`.
2. Extend chart schemas/validation.
3. Update `AnalysisOutputService._chart_data` and deterministic fallback selection.
4. Ensure values can only be derived from evidence.
5. Update the frontend `chartFigure.js` and PDF path.
6. Test duplicate suppression, empty data, screen rendering, and PDF consistency.

### Add an LLM provider

1. Implement `BaseLLMProvider` in `app/services/llm/`.
2. Support `generate_text` and validated `generate_structured`.
3. Normalize provider failures into `LLMProviderError` with safe codes/messages.
4. Add settings/API key/model fields.
5. Register the provider in `LLMService` and provider enums/schemas.
6. Add retry/invalid-output/authentication tests.
7. Update the frontend provider selector.

Provider fallback/mixing should not occur silently; a run is tied to its persisted provider.

### Add a landing CMS section

1. Add a Pydantic content class/field in `app/schemas/site_content.py`.
2. Prefer defaults for newly added fields so older stored JSON remains readable.
3. Update the frontend default content, public renderer, admin navigation, and section editor.
4. If persistence shape needs backfill, add a migration.
5. Test links/images through `_safe_location` and require alt text for meaningful images.

### Add another content type

Reuse `content_entries` when the data naturally fits versioned JSON content:

1. define a new `content_type` constant;
2. create strict Pydantic content/write/response schemas;
3. add repository/service methods;
4. expose public and admin routes with proper status filtering;
5. add indexes/migrations if query patterns differ.

Use dedicated normalized tables instead if relational querying, large volume, or transactional relationships are central to the feature.

## 11. Error handling and transactions

Expected domain failures should raise `AppError(code, safe_message, status, details?)`. Do not return stack traces or provider error text to clients.

General service transaction pattern:

```python
try:
    # mutate through repository/session
    await session.commit()
except SQLAlchemyError:
    await session.rollback()
    raise
```

Long LLM/network calls should not hold unnecessary database transactions open. Persist status, release the transaction, call the provider, then start the next persistence boundary.

## 12. Security model

`app/core/http_security.py` provides per-process safeguards:

- security headers and production HSTS;
- general write limiting;
- stricter auth/account creation limits;
- per-user/IP expensive-operation limits;
- bounded bodies before multipart/JSON parsing;
- separate limits for datasets, CMS images, blog bodies, and ordinary requests.

Additional controls:

- exact-origin CORS;
- JWT validation and session persistence;
- ownership-qualified repository queries;
- admin-only monitoring/CMS writes;
- safe file extensions, size limits, expanded-file limits, column/row limits;
- structured schemas with bounded strings/lists;
- no SQL echo by default;
- CSP/security headers at the frontend edge;
- production settings validation.

The in-memory rate limiter is per process. For multiple API instances or stricter public abuse protection, add an edge/shared limiter such as Cloudflare, Redis, or provider-native rate limiting.

## 13. Logging, monitoring, and LangSmith

`app/core/logging_config.py` configures a shared structured logging pipeline. In production, console output is JSON so the deployment platform is the durable source of truth even when local disk is ephemeral. When `LOG_DIR` is writable, the same records are copied into rotating `insightforge.jsonl` and error-only `errors.jsonl` files. Development console output remains compact and human-readable.

Every record has a stable `event`, service name, environment, UTC timestamp, severity, logger, and message. Context variables automatically propagate the available `request_id`, `analysis_run_id`, `user_id`, `conversation_id`, and `dataset_id` through async request and background-job execution. HTTP middleware returns `x-request-id` and emits start/completion/failure events with method, path, status, response size, and duration. Uvicorn/Gunicorn errors use the same handlers; noisy access, SQL, and HTTP-client logs stay restricted.

The main analysis lifecycle is observable through these events:

- `analysis.job.started`, `analysis.job.completed`, `analysis.job.failed`, `analysis.job.cancelled`, `analysis.job.skipped`
- `analysis.agent.completed`, `analysis.agent.failed`
- `analysis.run.completed`

Exception records retain exception type and safe stack-frame locations, while exception messages are withheld because provider and database errors can contain credentials or business data. URLs, bearer tokens, passwords, API keys, and secrets are redacted as a second line of defense. Do not log request bodies, user queries, dataset rows, prompts, provider responses, or authentication credentials.

Use the returned `x-request-id` to investigate an HTTP failure and `analysis_run_id` to follow work after it moves to the queue. On Render, filter the service logs by these fields or by the event name. Locally, use `Get-Content logs\insightforge*.jsonl | ConvertFrom-Json` and filter the resulting objects.

`app/core/tracing.py` implements optional LangSmith traces. Metadata-only mode is the production-safe default. `LANGSMITH_DETAIL_MODE` is forbidden in production.

`GET /monitoring/overview` queries operational aggregates from PostgreSQL and returns the optional LangSmith project URL for the owner UI.

## 14. Migrations

Migrations are ordered in `alembic/versions`:

1. authentication tables
2. datasets
3. profiles
4. conversations/messages/runs
5. agent runs
6. plans/tasks
7. evidence/statistics
8. claims/charts/reports
9. Google sign-in fields
10. account-management fields/tokens
11. generic CMS content entries
12. starter blog posts

Useful commands:

```powershell
alembic current
alembic heads
alembic upgrade head
alembic downgrade -1
```

Only downgrade when the migration explicitly supports safe data loss/reversal and you understand its effect.

## 15. Testing strategy

Install `requirements-dev.txt`, set a separate `TEST_DATABASE_URL`, then run:

```powershell
python -m pytest -q
```

Test areas:

- `test_auth.py`: authentication/session behavior.
- `test_health.py`: health endpoints.
- `test_deployment_config_unit.py`: production configuration constraints.
- `test_prompt_catalog_unit.py`: prompt organization.
- `test_tracing_unit.py`: safe tracing behavior.
- `test_recovery.py`: degraded analysis responses.
- `test_revenue_recommendations_unit.py`: deterministic recommendation rules.
- `test_stage5.py` through `test_stage9.py`: domain/pipeline milestones and regressions.

For any new resource, test:

- unauthenticated access;
- cross-user access;
- invalid input boundaries;
- success and not-found behavior;
- transaction rollback;
- deletion/cascade behavior;
- safe error responses;
- migration on an empty and representative existing database.

Avoid pointing tests at development or production databases. The test configuration deliberately requires a database name containing `test`.

## 16. Deployment and operations

### Render

`render.yaml` installs production requirements, applies migrations, and starts one Uvicorn process. Keep one process while using the in-process queue and limiter.

Required hosted values include:

- Neon `DATABASE_URL`
- Vercel `FRONTEND_URL`
- Cloudinary credentials
- JWT secret
- selected LLM provider credentials/models
- `ADMIN_EMAILS`
- optional Google, SMTP, and LangSmith configuration

### Health monitoring

Use:

```http
HEAD /api/v1/health
```

for lightweight uptime checks. Use `/health/db` for deployment health checks that must verify PostgreSQL.

### Before release

1. Run migrations on a staging/preview database.
2. Run the automated suite.
3. Run `pip-audit` and review results.
4. Confirm `APP_ENV=production`, `DEBUG=false`, `SQL_ECHO=false`.
5. Confirm frontend/backend origins match exactly.
6. Confirm Cloudinary deletion/upload, Google login, and SMTP if enabled.
7. Submit analyses with both configured providers.
8. Inspect normal, failed, cancelled, recovered, and restarted queued runs.
9. Verify owner-only routes with both admin and ordinary accounts.

## 17. Troubleshooting

### `Could not import module "main"`

Run from `server` using:

```powershell
python -m uvicorn app.main:app --reload
```

### Missing package

Activate the correct virtual environment and reinstall:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Database table missing

```powershell
alembic current
alembic upgrade head
```

### Google returns 401 or origin errors

- Use the same hostname consistently (`localhost` versus `127.0.0.1`).
- Set exact `FRONTEND_URL`.
- Add that origin to the Google Web client.
- Confirm frontend and backend use the same `GOOGLE_CLIENT_ID` public client configuration.

### Analysis remains pending

- Check that the application lifespan started the queue.
- Inspect logs for `analysis-queue-poller` errors.
- Query the run status and queue endpoint.
- Verify one active web process and PostgreSQL connectivity.

### Analysis completes with a limited answer

- Inspect agent runs, plan, evidence, statistics, claims, and report endpoints.
- Search JSONL logs by `analysis_run_id`.
- Check provider credentials/model support and validation reasons.
- A recovery answer may intentionally omit unsupported or failed calculations.

### Blog or landing changes missing

- Apply migration head.
- Confirm the content entry exists and is published.
- Check the global blog visibility flag.
- Confirm the caller is in `ADMIN_EMAILS` and email-verified for writes.
