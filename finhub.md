# FinHub — Agentic AI for Safe Financial Document Replication

> Business and design narrative for this prototype. For setup, commands, and eval how-to, start with [`README.md`](README.md).

## Business Context

Large global organisations often run a complex ERP landscape that has grown through expansion, acquisitions, regional rollouts, and vendor diversity. Finance teams then introduce a central finance layer so controllers and CFO organisations can see accounting activity from multiple operational ERPs in one place.

In a SAP Central Finance-style process, source accounting documents are replicated into a central target system. The target system validates master data, mappings, posting periods, duplicate references, and finance controls before accepting the document. When replication fails, the document sits in an exception queue until the issue is diagnosed, remediated, approved where required, and reprocessed.

## Problem Observed

In real-world finance operations, failed replication is rarely a simple technical retry. A single failed document can involve integration support, source ERP teams, master-data teams, controllers, and sometimes business process owners.

The manual process is slow because each failure requires evidence gathering, root-cause classification, routing to the right team, remediation, approval, reprocessing, and audit tracking. The workflow is often fragmented across monitoring tools, spreadsheets, tickets, email, and manual status updates.

Real production landscapes see many failure types. **This prototype focuses on ten** that map to the MAS rules specification (see [Prototype scope](#prototype-scope) below).

## Prototype Goal

This prototype validates whether an Agentic AI workflow can execute failed-document remediation safely **without relying on SAP data or SAP APIs**.

The project uses synthetic finance documents and vendor-neutral mock systems to simulate a Central Finance-style failure queue. The goal is not to replicate SAP technically. The goal is to prove the operating model:

- Can agents diagnose finance replication failures?
- Can they propose the correct remediation?
- Can deterministic guardrails prevent unsafe execution?
- Can humans stay in the loop where master-data creation requires approval?
- Can the workflow be observed, evaluated, and deployed as a real application?

## Prototype scope

Based on the MAS rules specification, the POC implements **10 failure scenarios** across three policy shapes:

| Policy shape | What happens | Approval? | Example docs |
|--------------|--------------|-----------|--------------|
| **Missing source-to-target mapping** | Analyst **manually** maintains the mapping entry, then the document can reprocess | No | DOC-1002, DOC-1004, DOC-1007 |
| **Missing target master data** | Target master data must be created; reprocess only after approval | Yes | DOC-1001, DOC-1003, DOC-1005, DOC-1008, DOC-1009, DOC-1010 |
| **Closed posting period** | Document stays blocked; external controller action required | Blocked | DOC-1006 |

**In scope for this POC:**

- Missing GL account, cost center, or profit center **mapping** (source-to-target).
- Missing GL account, cost center, profit center, vendor, customer, or asset **master data** in the target system.
- Closed posting period in the target system.
- Human approval before creating target master data.
- Manual mapping maintenance by the analyst (not system auto-update of mapping tables).
- Full audit trail for diagnosis, governance, and reprocess decisions.

**Explicitly out of scope** (deferred or handled elsewhere in a real SAP landscape):

- **Ambiguous mappings** — the synthetic mapping table enforces uniqueness; ambiguity is not modeled.
- **Duplicate documents** — SAP enforces unique document numbers; not simulated here.
- **Document value thresholds** — high-value approvals happen at source; not part of this target-side remediation flow.

## Agentic Workflow Design

When `OPENAI_API_KEY` is configured, the default path uses the **OpenAI Agents SDK** to orchestrate specialist agents. **Deterministic Python services remain the source of truth** for policy, approval gates, and reprocessing — agents reason and call tools but cannot bypass guardrails.

The workflow is structured as:

- **Intake agent** — gathers the failed document, target validation issues, and available mappings.
- **Diagnosis agent** — classifies the root cause and captures evidence (via deterministic classifier).
- **Remediation planner** — proposes the next action, approval requirement, and reprocessing path.
- **Governance agent** — applies deterministic policy checks and invokes controlled reprocess only when allowed.
- **Analyst summary writer** — produces a short plain-English explanation for finance analysts (`agent_summary`). Uses `SUMMARY_MODEL` when `SUMMARY_USE_LLM=1`; otherwise stores eval-aligned deterministic text.

Agents do not directly mutate finance state. State-changing behavior lives in guarded tools backed by deterministic services.

## Guardrails

The prototype implements explicit **code-level** policy checks (not prompt-only instructions):

- **Master-data creation** without approval → `needs_approval`; no reprocess until approval is recorded.
- **Master-data creation** with approval → allowed; document can reprocess.
- **Mapping maintenance** → allowed; analyst maintains mapping manually, then reprocess (no approval gate for mapping-only cases).
- **Closed posting period** → always `blocked`; requires external controller action.
- **Structured outputs** — diagnosis, remediation plan, governance decision, audit events on every run.
- **Deterministic fallback** — workflow runs without LLM when no API key or `DISABLE_LLM=1` (used for exact evals and testing).

The agent is an orchestrator inside a controlled execution boundary, not an unchecked autonomous actor.

## Technology Stack

| Layer | Technology |
|-------|------------|
| Runtime | Python, `uv` |
| Agent orchestration | OpenAI Agents SDK (`gpt-4o-mini` default) |
| Policy & services | Deterministic Python (`services.py`, `workflow.py`) |
| Evals | Promptfoo — deterministic (12 cases) + summary LLM judge (10 golden docs) |
| Observability | Langfuse + OpenTelemetry (optional) — agent spans + `analyst-summary` generation |
| Demo UI | React exception workbench + FastAPI (`frontend/`, `src/cfin_agents/api.py`) |
| Persistence | SQLite tickets/staging + local or S3 attachments (`FINHUB_DATA_DIR`) |
| Deployment | Railway — multi-stage **`Dockerfile`** ([`DEPLOYMENT.md`](DEPLOYMENT.md)) |

## Exception Workbench (demo UI)

The workbench is the portfolio-facing demo surface. Operators triage agent-created tickets without SAP connectivity.

**Demo flow (UI only):**

1. Reset & seed the staging queue with synthetic failed documents.
2. Run agent processing — agents diagnose, apply policy, and create tickets with analyst summaries.
3. Review the agent diagnosis callout on each ticket.
4. Update operator status; add comments; upload proof when resolving.
5. Open **View trace in Langfuse** on ticket detail to inspect agent + summary model spans (when Langfuse is configured).

**Status model:**

- **Operator status** (`assigned` / `in_progress` / `blocked` / `resolved`) — what humans control in the queue.
- **Workflow status** (`needs_approval`, `blocked`, `reprocessed`, …) — agent policy outcome, shown as context in the diagnosis summary.
- **Activity log** — ingestion, diagnosis, assignment, and manual transitions.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for API endpoints, persistence, and deployment topology.

## Synthetic Scenarios (10 documents)

| Doc | Failure | Reason code | Expected outcome |
|-----|---------|-------------|------------------|
| DOC-1001 | GL account master data missing | `MD_GL_ACCOUNT_MASTER_DATA_MISSING` | Needs approval |
| DOC-1002 | Cost center mapping missing | `MP_COST_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING` | Reprocessed (manual mapping) |
| DOC-1003 | Vendor master data missing | `MD_VENDOR_MASTER_DATA_MISSING` | Needs approval |
| DOC-1004 | GL account mapping missing | `MP_GL_ACCOUNT_SOURCE_TO_TARGET_MAPPING_MISSING` | Reprocessed (manual mapping) |
| DOC-1005 | Cost center master data missing | `MD_COST_CENTER_MASTER_DATA_MISSING` | Needs approval |
| DOC-1006 | Posting period closed | `DC_POSTING_PERIOD_CLOSED` | Blocked |
| DOC-1007 | Profit center mapping missing | `MP_PROFIT_CENTER_SOURCE_TO_TARGET_MAPPING_MISSING` | Reprocessed (manual mapping) |
| DOC-1008 | Profit center master data missing | `MD_PROFIT_CENTER_MASTER_DATA_MISSING` | Needs approval |
| DOC-1009 | Customer master data missing | `MD_CUSTOMER_MASTER_DATA_MISSING` | Needs approval |
| DOC-1010 | Asset master data missing | `MD_ASSET_MASTER_DATA_MISSING` | Needs approval |

These ten cases demonstrate safe mapping remediation, human-in-the-loop master-data creation, and hard policy blocks.

## Evals and Quality Gates

Two automated eval layers protect regression quality:

1. **Deterministic evals** — 12 cases in `evals/deterministic_cases.yaml` verify exact workflow status, reason codes, actions, and policy outcomes (includes approved variants such as DOC-1001 with `--approve`).
2. **Summary evals** — 10 golden cases in `evals/summary_cases.yaml`; an LLM judge scores analyst-facing `agent_summary` text (accuracy ≥ 4 **and** actionability ≥ 4).

**Human methodology:** Three exemplar docs (DOC-1001, DOC-1002, DOC-1006) plus a rubric and six calibration examples live in `AI Evals_SM5_v0.6.xlsx` (local workbook). That defined what “good” looks like and calibrated the judge. YAML scales the same three policy shapes to all ten scenarios for automated regression. See [Why Excel was left at 3 docs](Evals-Journey.md#why-excel-was-left-at-3-docs) in [`Evals-Journey.md`](Evals-Journey.md).

Further reading: [`promptfoo.md`](promptfoo.md), [`Evals-Journey.md`](Evals-Journey.md) (session log + [eval concepts](Evals-Journey.md#evals-concepts-ground-up-guide)), [`CI.md`](CI.md).

## Outcome

The prototype shows how an Agentic AI solution can reduce manual triage and handoffs while preserving finance governance. The strongest framing is not “AI replaces the finance support process end to end.” It is:

> AI agents accelerate diagnosis, evidence gathering, remediation planning, workflow tracking, and controlled reprocessing while deterministic guardrails and human approvals protect finance-critical decisions.

The demo is realistic, portable, and suitable for portfolio sharing without exposing enterprise SAP data.

## Documentation map

| Doc | Use when… |
|-----|-----------|
| [`README.md`](README.md) | Running the app, evals, deployment |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Technical architecture, data model, API |
| [`finhub.md`](finhub.md) | Explaining the business case (this file) |
| [`Evals-Journey.md`](Evals-Journey.md) | Understanding the eval methodology and decisions |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Deploying to Railway |
| [`CI.md`](CI.md) | Understanding CI vs local test scripts |
