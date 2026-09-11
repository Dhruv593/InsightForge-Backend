# LangSmith observability

## Rich stage traces and graph visualization

Restart the API after updating. New traces contain `stage.*` entries. Select one and open Input → handoffs to see the source stage, target stage, state field, availability, and a safe summary. These describe shared-state contracts, not peer-to-peer messaging or a claim that every available field was used on every branch. Outputs show known result fields and collection counts. Provider attempt events contain attempt numbers and safe error codes.

The root Output now has `analysis_outcome`: completed, unsupported, partial, completed_with_fallback, or recovered_partial. A green trace means the request returned; check this outcome before interpreting it as analytical success. Failed child spans still show exception types. Old traces cannot be upgraded retroactively.

### Open the connection diagram in Studio

The Studio graph is a **read-only topology viewer**, sharing the same execution edges as production. It does not replay a selected LangSmith trace and does not run real analyses, call providers, or access your database. Actual execution paths and data summaries remain in LangSmith Tracing. This separation prevents the local development server from bypassing application authentication.

From `server`, in an activated development environment:

```powershell
python -m pip install -r requirements-studio.txt
Copy-Item .env.studio.example .env.studio
langgraph dev --host 127.0.0.1 --port 2024 --no-browser
```

Copy the example only if `.env.studio` does not already exist. Open the Studio URL printed by the command, connect to `http://127.0.0.1:2024`, choose `insightforge_topology`, and use Graph mode. It shows all configured stages and the supervisor's two branches. Submitting a run intentionally returns a read-only error; do not submit real business data. Keep this server loopback-only; do not tunnel, publicly deploy, or expose it. There is no new admin route on your website.

The CLI may have different Python compatibility requirements from the API. Use a separate Python 3.12/3.13 virtual environment if installation fails on your current Python. Studio was not launched during implementation.

### Optional detailed previews (synthetic development data only)

```env
APP_ENV=development
LANGSMITH_DETAIL_MODE=true
```

This includes bounded redacted stage/agent payload previews and response previews. It is ignored unless APP_ENV is exactly development. Sensitive key names, emails, URLs and long token-like strings are redacted; lists, strings and nesting are capped. Redaction cannot recognize every business secret, personal name, phone number, or confidential value. Use synthetic data only and do not enable for real customer datasets. Raw provider message lists and ORM objects remain excluded. Set false and restart after debugging. Metadata-only summaries remain the default.

1. Create a private workspace at https://smith.langchain.com and create an API key in its settings. Do not share trace links publicly.
2. Install dependencies from the activated server environment: `python -m pip install -r requirements.txt`.
3. Add these settings to your server `.env` (never to the frontend):

```env
LANGSMITH_ENABLED=true
LANGSMITH_API_KEY=your-key
LANGSMITH_PROJECT=insightforge
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

Use the endpoint for your workspace region if different. Restart the backend and submit a normal analysis. In LangSmith, open the `insightforge` project and find `analysis.request`; its metadata includes `analysis_run_id` for correlation with existing server logs. Only new analyses are traced. No database migration or frontend change is required.

The nested trace includes workflow execution, named agent invocations, individual Gemini/Groq attempts (including retries), analytical/statistical execution stages, and deterministic claim/review/chart/report fallbacks. Failed spans show exception types, not raw exception messages. Provider/model metadata and token usage are included when returned by the provider. Failed provider attempts may not return usage, so cost totals are not guaranteed complete.

Inputs and outputs expose only argument types and collection counts. This shows execution flow but deliberately does not show raw prompts, business values, dataset rows, full state snapshots, emails, passwords, keys, or model responses. Exact payload inspection remains in the existing local application records; full-content external tracing is not enabled. This is execution tracing, not hidden model reasoning, and does not audit authentication or every database operation.

Use `LANGSMITH_ENABLED`, not global `LANGSMITH_TRACING` or `LANGCHAIN_TRACING_V2`. Leave those global automatic tracing switches unset/false so third-party integrations do not independently export raw graph state. Metadata still leaves your server: choose appropriate access controls, regional endpoint, retention and billing limits in LangSmith before production use.

SDK export errors are isolated from application execution and never cause the analysis operation to be repeated. Export is best-effort/background batched; abrupt shutdown or an outage can lose traces. A local warning indicates tracing could not be enqueued. Set `LANGSMITH_ENABLED=false` and restart to disable. Real credentials and live export were not tested during implementation.

Reference: https://docs.langchain.com/langsmith/annotate-code
