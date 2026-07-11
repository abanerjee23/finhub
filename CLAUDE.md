# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Agentic proof-of-concept for safe Central Finance failed document replication remediation. Uses synthetic data (no real SAP/ERP backend). The default app/CLI path is OpenAI Agents SDK orchestration when `OPENAI_API_KEY` is present and `DISABLE_LLM=0`; deterministic mode remains available for exact testing/validation and no-key fallback. Deterministic services are always the source of truth.

**Scope (based on MAS Rules):** 10 failure types across mapping failures, missing master data, and closed posting periods. Out of scope: ambiguous mappings (mapping table enforces uniqueness), duplicate documents (SAP enforces unique document numbers), document value thresholds (approvals happen at source).

**Architecture reference:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Commands

```bash
# Setup
uv sync
cp .env.example .env          # add OPENAI_API_KEY; SUMMARY_USE_LLM=1 for LLM summaries

# Run CLI (multi-agent by default when OPENAI_API_KEY is set and DISABLE_LLM=0)
uv run cfin-demo DOC-1002                # missing mapping → analyst maintains mapping, then reprocesses
uv run cfin-demo DOC-1001                # missing_gl_account_master → needs_approval
uv run cfin-demo DOC-1001 --approve      # approved → reprocessed
uv run cfin-demo DOC-1006                # closed_posting_period → blocked

# Dev workbench (FastAPI backend + React frontend)
bash scripts/dev-workbench.sh          # backend on :8000, frontend on :5173

# Workbench queue (CLI alternative to UI controls)
uv run cfin-seed --count 50 --reset      # clear + seed staging queue
SUMMARY_USE_LLM=1 uv run cfin-sweep --batch-size 5

# Legacy / maintenance CLI
uv run cfin-batch-demo --count 50        # deterministic bootstrap (not agentic)
uv run cfin-refresh-summaries            # regenerate ticket agent_summary fields

# All deterministic tests + evals
bash scripts/run_deterministic_evals.sh

# Summary eval smoke tests (requires OPENAI_API_KEY)
bash scripts/run_summary_calibration.sh
bash scripts/run_summary_evals.sh              # Promptfoo 10-doc judge + JSONL log
bash scripts/run_summary_eval_batch.sh         # programmatic batch + log only

# Pytest only (workbench + core)
uv run pytest tests/test_services.py tests/test_deterministic_cases.py tests/test_summary_cases.py tests/test_eval_results.py tests/test_ticketing.py tests/test_workbench_api.py tests/test_observability.py -q

# Pytest matching CI deterministic script only
uv run pytest tests/test_deterministic_cases.py tests/test_services.py -q

# Lint
uv run ruff check src/ tests/ evals/ --line-length=100

# Production UI bundle check
npm --prefix frontend run build && API_RELOAD=0 uv run cfin-api
```

## Architecture

### Execution Paths

`AgenticWorkflow` (workflow.py) has two paths based on `OPENAI_API_KEY` / `DISABLE_LLM`:
1. **Multi-agent default**: Creates OpenAI Agents SDK agents with `FinanceToolset` tools, then runs `DeterministicWorkflow` as the authoritative outcome. Used when `OPENAI_API_KEY` is present and `DISABLE_LLM=0`.
2. **Deterministic fallback/test mode**: Runs `DeterministicWorkflow` directly. Used when no API key is configured, `DISABLE_LLM=1`, or tests pass `force_deterministic=True`.

All state mutation is controlled by deterministic services — agents reason and invoke tools, but cannot bypass policy.

On LLM-path runs, the manager agent's final narrative is captured as shadow-mode telemetry: `WorkflowRun.agent_final_output` + keyword-cue `shadow_agreement`, appended to `{FINHUB_DATA_DIR}/agent_shadow_log.jsonl` (workflow.py). Deterministic outcome stays authoritative.

Datetimes are timezone-aware UTC throughout — use `timeutil.utc_now()` (never `datetime.utcnow()`); model fields use `timeutil.UTCDateTime`, which coerces legacy naive payloads on read.

### Exception Workbench (React + FastAPI)

Self-contained demo loop in the UI (`frontend/src/App.tsx` orchestrates; components in `frontend/src/components/`, shared helpers in `frontend/src/lib/format.ts`):

- **Workbench Controls** — reset/seed queue, run agent processing (async sweep job with progress bar), refresh
- **Business Impact** — open value at risk / total value failed (USD-equivalent via fixed demo FX in `ticketing.FX_RATES_TO_USD`), open value by company code / source system (click-to-filter the ticket list), SLA breach count+value, aging buckets, automation rate
- **Analytics** — KPIs, operator status breakdown, owner chart, stage times
- **Ticket detail** — agent diagnosis hero (execution-mode badge, 👍/👎 summary feedback, shadow-mode agent note), **Approve & Reprocess** for `needs_approval` tickets, **Maintain Mapping** for `MP_*` tickets, assignee reassignment, metadata, comments, proof attachments, activity log
- **Search Tickets** — filter, inline `operator_status` dropdown, bulk status moves (assigned/in-progress only)

API: `src/cfin_agents/api.py`. Workbench endpoints under `/api/workbench/*`; sweep runs as a background job (`POST /api/workbench/sweep` → job id, poll `GET /api/workbench/sweep/jobs/{id}`; pass `"wait": true` for synchronous test use). Ticket transitions use `operator_status` (not legacy `status` + policy flags). Ticket mutations use per-ticket `get_ticket`/`upsert_ticket` writes — never rewrite the whole table in endpoints.

Human-in-the-loop ticket actions:
- `POST /api/tickets/{id}/approve` — records approval, re-runs the governed workflow (deterministic, authoritative), resolves the ticket with `approval_recorded` + `reprocess_completed` timeline events
- `POST /api/tickets/{id}/maintain-mapping` — `MP_*` tickets only; records the mapping entry (source value auto-derived from the staging record), reprocesses, resolves
- `PATCH /api/tickets/{id}/assignee`, `POST /api/tickets/{id}/summary-feedback` (rating logged to `{FINHUB_DATA_DIR}/summary_feedback.jsonl`)

### Persistence

| Layer | Location |
|-------|----------|
| Bundled synthetic ERP data | `data/synthetic/*.json` (read-only, in image) |
| Tickets + staging queue | `{FINHUB_DATA_DIR}/finhub.db` (SQLite JSON payloads) |
| Attachment blobs | Local `{FINHUB_DATA_DIR}/attachments/` or S3 via `STORAGE_BACKEND=s3` |

Env: `FINHUB_DATA_DIR`, `STORAGE_BACKEND`, `S3_*`. Legacy ticket payloads migrate on read (`ticket_migration.py`).

### Ticket status model

- **`operator_status`** — human queue status: `assigned`, `in_progress`, `blocked`, `resolved`
- **`workflow_run.status`** — agent policy outcome (`needs_approval`, `blocked`, `reprocessed`, …); exposed as `workflow_status` in list API
- **`timeline`** — internal journey + manual transitions (Activity Log in UI)
- **`agent_summary`** — persisted at ticket creation (`generate_analyst_summary()`); LLM when `SUMMARY_USE_LLM=1`, else eval-aligned deterministic template. `resolve_agent_summary()` polishes stored text on read and returns `None` for missing/legacy summaries (no on-read regeneration).

### Service Pipeline (services.py)

```
SyntheticRepository → Validator → DiagnosisService → RemediationPlanner → PolicyEngine → ReprocessingService
```

**PolicyEngine** logic (simplified — no value thresholds):
- `CREATE_TARGET_MASTER_DATA` without approval → `NEEDS_APPROVAL`, blocked
- `CREATE_TARGET_MASTER_DATA` with approval → allowed, reprocess
- `CLOSED_POSTING_PERIOD` → always `BLOCKED` (requires external controller action)
- `MAINTAIN_SOURCE_MAPPING` → allowed; analyst manually maintains the mapping, then the document can be reprocessed
- Diagnosis confidence below `CONFIDENCE_REVIEW_THRESHOLD` (env, default 0.5) → `NEEDS_APPROVAL` (human review); the default never trips on the deterministic classifier (0.8–0.95), keeping evals unchanged

**DeterministicWorkflow** orchestrates all services and records an `AuditLog` at each step. After the run, `generate_analyst_summary()` populates `agent_summary` (LLM when `SUMMARY_USE_LLM=1` + key; deterministic template otherwise).

### Observability (observability.py)

Langfuse v4 + OpenInference when credentials are configured:

- `configure_openai_agents_tracing()` — OpenAI Agents SDK spans → OTLP → Langfuse
- `workflow_observation()` — root span per run; `langfuse_trace_id` on `WorkflowRun`
- `summary_generation_observation()` — `analyst-summary` generation for `SUMMARY_MODEL`
- `langfuse_trace_url()` — linked from ticket detail UI

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#observability-langfuse) for trace hierarchy diagram.

### Agent Tools (toolkit.py)

`FinanceToolset` wraps deterministic services as tool functions for OpenAI Agents SDK:
- `document_context()` → validation issues + mappings
- `classify_failure()` → Diagnosis
- `propose_remediation()` → RemediationPlan
- `evaluate_governance()` → GovernanceDecision
- `controlled_reprocess()` → ReprocessResult (only executes if policy allows)

Summary prompt rules distinguish root cause from remediation (`MD_*` = missing master data; `MP_*` = missing mapping). LLM judge uses `SUMMARY_JUDGE_MODEL` (default `gpt-4o`).

### Eval Test Cases

**Deterministic evals:** `evals/deterministic_cases.yaml` is the single source of truth for expected workflow behavior — used by pytest, Promptfoo (`evals/promptfooconfig.yaml`), and `evals/provider.py`. All deterministic tests force `DISABLE_LLM=1`.

**Summary evals:** Human golden labels for 3 starter docs live in `AI Evals_SM5_v0.6.xlsx` (local workbook). Automation golden copy: `evals/summary_cases.yaml` (**10 docs**). Promptfoo configs: `evals/promptfoo_summary_config.yaml` (live workflow + judge) and `evals/promptfoo_summary_calibration_config.yaml` (6 human pass/fail examples). Judge logic: `src/cfin_agents/summary_judge.py` + `evals/summary_assertions.py`. Result logging: `src/cfin_agents/eval_results.py` → `evals/model_outputs.jsonl`. CI: see `CI.md`. Session log: `Evals-Journey.md`.

When eval work progresses, append a session entry to `Evals-Journey.md` and update its status board + changelog.

### Synthetic Data (10 scenarios)

**Source-to-target mapping missing — manual mapping maintenance, no approval:**

| ID | Failure Scenario | Reason Code | Expected |
|---|---|---|---|
| DOC-1002 | Cost center source to target mapping missing | `MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING` | analyst maintains mapping, then reprocesses |
| DOC-1004 | GL account source to target mapping missing | `MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING` | analyst maintains mapping, then reprocesses |
| DOC-1007 | Profit center source to target mapping missing | `MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING` | analyst maintains mapping, then reprocesses |

**Master data missing — requires approval:**

| ID | Failure Scenario | Reason Code | Expected |
|---|---|---|---|
| DOC-1001 | GL account master data missing | `MD_GL_ACCOUNT_MASTER_DATA_MISSING` | needs_approval (reprocessed if approved) |
| DOC-1005 | Cost center master data missing | `MD_COST_CENTER_MASTER_DATA_MISSING` | needs_approval (reprocessed if approved) |
| DOC-1008 | Profit center master data missing | `MD_PROFIT_CENTER_MASTER_DATA_MISSING` | needs_approval (reprocessed if approved) |
| DOC-1003 | Vendor master data is missing | `MD_VENDOR_MASTER_DATA_MISSING` | needs_approval (reprocessed if approved) |
| DOC-1009 | Customer master data is missing | `MD_CUSTOMER_MASTER_DATA_MISSING` | needs_approval (reprocessed if approved) |
| DOC-1010 | Asset master data is missing | `MD_ASSET_MASTER_DATA_MISSING` | needs_approval (reprocessed if approved) |

**Period closed — always blocked:**

| ID | Failure Scenario | Reason Code | Expected |
|---|---|---|---|
| DOC-1006 | Posting period closed | `DC_POSTING_PERIOD_CLOSED` | blocked |

### Key Models (models.py)

`WorkflowRun` is the top-level workflow output: contains `Diagnosis` (with `reason_code`), `RemediationPlan`, `GovernanceDecision`, `ReprocessResult`, `AuditEvents`, `agent_summary`, and optional Langfuse trace ID.

`Ticket` (ticket_models.py) is the workbench entity: `operator_status`, `workflow_run`, `agent_summary`, `timeline`, `comments`, `attachments`.

### Deployment

FastAPI (`src/cfin_agents/api.py`) serves REST API and production React build (`frontend/dist`). Dev: `bash scripts/dev-workbench.sh` (Vite + API). **Railway:** multi-stage `Dockerfile` (Node 22 frontend build → Python 3.11/uv runtime); config in `railway.json`. See [`DEPLOYMENT.md`](DEPLOYMENT.md). Attach Railway Volume at `/data` → `FINHUB_DATA_DIR=/data/finhub`; set `RAILWAY_RUN_UID=0` for Docker. Health: `/api/health`. Evals run locally or in GitHub Actions — not on Railway.
