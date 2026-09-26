# Tatparya API

Tatparya API is the FastAPI backend for **Tatparya**, an autonomous multi-agent data-analysis product. It manages authentication, datasets, deterministic profiling, conversations, queued analytical workflows, evidence, statistical validation, claims, charts, reports, monitoring, landing-page content, and blog publishing.

The analysis system uses LLMs for bounded planning and interpretation while Python, Pandas, DuckDB, SciPy, and Statsmodels perform the calculations. Raw dataset rows are not intentionally sent to LLM providers.

> Read [DOCUMENTATION.md](./DOCUMENTATION.md) for the full architecture, every endpoint, database model ownership, analysis pipeline, and feature-extension guide.

## Main capabilities

- Password and Google authentication with rotating refresh-token sessions
- Email verification, password reset, session revocation, and account deletion
- Owner/admin authorization through configured email addresses
- CSV, Excel, JSON, and Parquet upload through Cloudinary
- Deterministic dataset profiling and quality checks
- Conversation/message persistence
- Background in-process analysis queue with retry and cancellation
- Gemini and Groq provider adapters
- LangGraph orchestration with safe recovery paths
- Controlled analytical and statistical tool registries
- Evidence, claims, Critic reviews, chart specifications, and structured reports
- LangSmith metadata tracing and owner monitoring
- Landing-page CMS and structured blog CMS
- Security headers, bounded request bodies, rate limits, CORS, and production safeguards
- JSON Lines application/error logging

## Technology

- Python 3.12.x (the repository and Render are pinned to Python 3.12.8)
- FastAPI and Uvicorn
- PostgreSQL, SQLAlchemy 2, Psycopg, and Alembic
- Pydantic 2
- LangGraph and LangSmith
- Google Gen AI and Groq SDKs
- Pandas, NumPy, DuckDB, SciPy, and Statsmodels
- Cloudinary

## Local setup

```powershell
cd server
python --version # must report Python 3.12.x
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Do not reuse a `.venv` created by another Python version. Remove and recreate that environment after installing Python 3.12.8; newer Windows runtimes can exhibit test-runner shutdown problems even after every test has completed.

Create a PostgreSQL database and set at least the required values in `.env`:

```env
APP_ENV=development
DEBUG=true
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/insightforge
FRONTEND_URL=http://localhost:5173
ADMIN_EMAILS=owner@example.com

JWT_SECRET_KEY=<at-least-32-random-characters>

CLOUDINARY_CLOUD_NAME=<cloud-name>
CLOUDINARY_API_KEY=<api-key>
CLOUDINARY_API_SECRET=<api-secret>

GEMINI_API_KEY=<optional>
GEMINI_MODEL=<optional>
GROQ_API_KEY=<optional>
GROQ_MODEL=<optional>
```

Generate a JWT secret:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Apply all migrations:

```powershell
alembic upgrade head
```

Start the API from the `server` directory:

```powershell
python -m uvicorn app.main:app --reload
```

Do not run `uvicorn main:app`; the ASGI module is `app.main`.

Development URLs:

- API: [http://localhost:8000](http://localhost:8000)
- Swagger: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)
- Database health: [http://localhost:8000/api/v1/health/db](http://localhost:8000/api/v1/health/db)

## Configuration groups

The complete template is in [`.env.example`](./.env.example).

| Group | Important variables |
| --- | --- |
| Runtime | `APP_NAME`, `APP_ENV`, `DEBUG`, `API_V1_PREFIX` |
| Database | `DATABASE_URL` |
| Frontend/admin | `FRONTEND_URL`, `ADMIN_EMAILS` |
| Authentication | `JWT_SECRET_KEY`, `JWT_ALGORITHM`, expiry settings, `GOOGLE_CLIENT_ID` |
| Email | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME`, `SUPPORT_EMAIL`, `SMTP_USE_TLS` |
| Storage/profile | Cloudinary keys, `MAX_UPLOAD_SIZE_MB`, `MAX_PROFILE_ROWS`, `MAX_EXPANDED_FILE_MB`, `MAX_DATASET_COLUMNS` |
| LLM | Gemini/Groq keys and models, `LLM_REQUEST_TIMEOUT_SECONDS` |
| Observability | logging settings and `LANGSMITH_*` |

At least one LLM provider must be configured to execute an analysis. Both may be configured so the user can choose per run.

## Analysis lifecycle

```text
Question submitted
  → pending analysis run
  → in-process queue claims the run
  → load verified context
  → supervisor
  → profile interpreter
  → planner
  → deterministic analytical tools
  → statistical validation
  → claim generation
  → critic review
  → chart selection and deterministic chart data
  → structured report
  → persisted assistant response
```

If a provider or optional stage fails, recovery attempts to produce the best safe answer supported by committed evidence. A completed run means that the user received a response; report limitations indicate whether every requested operation succeeded.

## API groups

All application endpoints use the configured prefix, normally `/api/v1`.

| Prefix | Purpose |
| --- | --- |
| `/health` | API and database health |
| `/auth` | Registration, login, refresh, logout, current user, Google sign-in |
| `/account` | Verification, password reset/change, profile, sessions, account deletion |
| `/datasets` | Upload, list, read, delete, and profile datasets |
| `/conversations` | Conversation CRUD, queries, messages, and conversation runs |
| `/analysis-runs` | Queue, retry, cancel, status, agents, plans, evidence, claims, charts, reports |
| `/monitoring` | Owner-only operational overview |
| `/site-content` and `/admin/site-content` | Public/admin landing content |
| `/blogs` and `/admin/blogs` | Public publishing and admin blog CRUD |

Protected requests require:

```http
Authorization: Bearer <access-token>
```

See [DOCUMENTATION.md](./DOCUMENTATION.md#7-api-reference) for the endpoint-by-endpoint reference.

## Database migrations

Create a migration whenever a persisted schema changes:

```powershell
alembic revision -m "describe change"
alembic upgrade head
```

Review generated/manual migrations before applying them. Never edit a migration that has already been deployed; add a new migration instead.

Current migrations cover authentication, datasets/profiles, conversations/runs, agents, plans/tasks, evidence/statistics, claims/charts/reports, Google sign-in, account management, CMS content, and starter blog posts.

## Tests and checks

Install development requirements:

```powershell
pip install -r requirements-dev.txt
```

Use a separate PostgreSQL test database whose name contains `test`:

```env
TEST_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/insightforge_test
```

Run tests:

```powershell
python -m pytest -q
```

Optional dependency audit:

```powershell
pip-audit -r requirements.txt
```

## Logs and tracing

Production emits structured JSON to stdout, so events remain visible in the hosting provider's log viewer even when its filesystem is ephemeral. The same events are also written to rotating JSON Lines files when the log directory is writable:

- `logs/insightforge.jsonl`: application events
- `logs/errors.jsonl`: errors
- process-suffixed files may be used when Windows reload mode locks a base log file

Each record includes an `event`, `service`, `environment`, and any available correlation identifiers: `request_id`, `analysis_run_id`, `user_id`, `conversation_id`, and `dataset_id`. The API returns `x-request-id` on every handled response. Use that value to find the entire request path. Request bodies, queries, dataset rows, access tokens, and provider responses are intentionally excluded.

Follow errors in PowerShell:

```powershell
Get-Content .\logs\errors*.jsonl -Wait
```

Search one analysis:

```powershell
Select-String -Path .\logs\*.jsonl -Pattern '<analysis-run-id>'
```

Inspect one request as parsed JSON:

```powershell
Get-Content .\logs\insightforge*.jsonl |
  ConvertFrom-Json |
  Where-Object request_id -eq '<x-request-id>'
```

Useful lifecycle events include `http.request.started`, `http.request.completed`, `http.request.failed`, `analysis.job.started`, `analysis.agent.completed`, `analysis.agent.failed`, `analysis.run.completed`, and `analysis.job.failed`.

LangSmith setup is documented in [LANGSMITH.md](./LANGSMITH.md). Google sign-in setup is documented in [GOOGLE_SIGN_IN.md](./GOOGLE_SIGN_IN.md).

## Deployment

[`render.yaml`](./render.yaml) configures a Render web service. Its start command applies migrations before starting Uvicorn:

```text
alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Recommended production architecture:

- frontend: Vercel
- backend: Render
- PostgreSQL: Neon
- uploaded files/content images: Cloudinary
- uptime probe: `HEAD /api/v1/health`

Production validation rejects unsafe settings such as enabled debug/SQL echo/detail tracing or a non-HTTPS frontend origin.

## Documentation

Continue with [DOCUMENTATION.md](./DOCUMENTATION.md) for:

- detailed request and analysis flows
- all API endpoints and access levels
- database model relationships
- module/file ownership
- adding endpoints, models, migrations, agents, prompts, tools, chart types, providers, and CMS fields
- security, logging, recovery, testing, and deployment guidance

Agent-specific references:

- [AGENT_PROCESS.md](./AGENT_PROCESS.md) explains the orchestration stages, contracts, fallbacks, and accuracy controls.
- [Interactive agent-flow diagram](./docs/architecture/tatparya-agent-flow.html) provides a presentation-ready visual companion.
