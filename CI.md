# CI — Continuous Integration

> Plain-language guide to automated testing in this repo: what CI is, what it runs, and what you can run on your laptop instead.

**Config file:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml)

---

## What is CI?

**CI** stands for **Continuous Integration**. It means: *when you push code to GitHub, a robot runs your test checklist automatically* and reports pass or fail on the repo.

Think of it like this:

```text
You change code on your Mac
        ↓
You push to GitHub
        ↓
GitHub Actions runs the same tests you could run locally
        ↓
You see ✅ or ❌ on the repository
```

CI does **not** add new tests. It **automates** tests that already exist as shell scripts and pytest/Promptfoo configs.

---

## What CI does in this project

The workflow has **two jobs**:

### 1. `deterministic` — runs automatically

**When:** Every push to `main` or `master`, and every pull request.

**Steps:**

| Step | Command (equivalent) | Purpose |
|------|----------------------|---------|
| Lint | `uv run ruff check src/ tests/ evals/` | Catch style and simple code errors |
| Deterministic evals | `bash scripts/run_deterministic_evals.sh` | Verify workflow logic still matches golden expectations |

**No OpenAI API key required.**

### 2. `summary-eval` — manual only

**When:** You click **Run workflow** in the GitHub Actions tab (`workflow_dispatch`).

**Steps:**

| Step | Purpose |
|------|---------|
| Summary judge unit tests | Verify golden cases and judge code load correctly |
| `bash scripts/run_summary_evals.sh` | Calibrate judge + run 10-doc live summary evals |
| Log to JSONL | Append results to `evals/model_outputs.jsonl` |
| Upload artifact | Download eval log from the Actions run |

**Requires:** `OPENAI_API_KEY` as a GitHub repository secret. Costs API usage and takes several minutes — so it is **not** run on every push.

---

## CI vs running tests locally

Same idea, different place:

```text
YOU (local)                          GITHUB CI (cloud)
─────────────────                    ─────────────────
Edit code                            Push to GitHub
     ↓                                    ↓
Run script in Terminal               GitHub runs the script
     ↓                                    ↓
See pass/fail in terminal            See pass/fail on GitHub
```

Until the project is pushed to GitHub with Actions enabled, **you are the CI** — run the scripts yourself in Terminal.

---

## The two main scripts (run on your Mac)

These live in `scripts/`. They are **saved recipes** — a sequence of commands so you do not run each step by hand.

### `bash scripts/run_deterministic_evals.sh`

**What it checks:** Did the **governed workflow logic** break? (status, reason code, action, policy — not the English summary.)

**Runs in order:**

1. **pytest** — `tests/test_deterministic_cases.py`, `tests/test_services.py` (matches CI `deterministic` job)
2. **Smoke check** — `scripts/smoke_check.py` (quick end-to-end sanity on a few documents)
3. **Promptfoo** — 12 cases from `evals/deterministic_cases.yaml`

For broader local coverage before a release, also run workbench tests:

```bash
uv run pytest tests/test_ticketing.py tests/test_workbench_api.py tests/test_observability.py -q
```

**API key:** Not needed (deterministic mode, no LLM agents).

**Success looks like:**

```text
Deterministic eval suite completed successfully.
```

**Run from project root:**

```bash
cd /path/to/finhub
bash scripts/run_deterministic_evals.sh
```

### `bash scripts/run_summary_evals.sh`

**What it checks:** Does the **analyst-facing English summary** (`agent_summary`) still explain failures correctly?

**Runs in order:**

1. **pytest** — summary cases and judge unit tests
2. **Judge calibration** — 6 fixed good/bad summaries; judge must agree with human pass/fail labels
3. **Live summary evals** — 10 golden docs: run workflow → generate summary → LLM judge scores vs YAML
4. **Log results** — append to `evals/model_outputs.jsonl`

**API key:** Required (`OPENAI_API_KEY` in `.env` or exported).

**Run from project root:**

```bash
cd /path/to/finhub
set -a && source .env && set +a
bash scripts/run_summary_evals.sh
```

**Note:** This takes several minutes and uses OpenAI (agents, summary writer, and judge).

---

## When to run which script

| You changed… | Run this |
|--------------|----------|
| Policy, diagnosis, reprocess logic (`services.py`, `workflow.py`, etc.) | `bash scripts/run_deterministic_evals.sh` |
| Synthetic data or deterministic golden cases (`evals/deterministic_cases.yaml`) | `bash scripts/run_deterministic_evals.sh` |
| Workbench API, tickets, persistence (`api.py`, `ticketing.py`, `document_store.py`) | `uv run pytest tests/test_ticketing.py tests/test_workbench_api.py tests/test_ticket_migration.py tests/test_observability.py -q` |
| Summary prompts, agent instructions, judge, golden YAML (`summary_cases.yaml`) | `bash scripts/run_summary_evals.sh` |
| Models (`OPENAI_MODEL`, `SUMMARY_MODEL`, `SUMMARY_JUDGE_MODEL`) | `bash scripts/run_summary_evals.sh` |
| Docs only (README, markdown) | Nothing required |

**Rule of thumb:** Run the deterministic script when you touch **structure/policy**; run the summary script when you touch **wording/prompts/models**.

---

## What “run locally before you share” means

Not before every keystroke — **before you consider a change done** or before pushing to GitHub:

1. Make your code or prompt changes
2. Run the appropriate script
3. Confirm it passes
4. Then commit / push / deploy

If deterministic evals fail, something in the workflow no longer matches the golden expectations (e.g. wrong status for DOC-1006). If summary evals fail, the analyst summary may be misleading even if the JSON outcome is correct.

---

## Is CI required for this project?

**No.** For a solo personal project, running the scripts locally is enough for regression confidence.

| Benefit | Solo project |
|---------|----------------|
| Reminds you to run tests | Mildly useful |
| Green checkmark on GitHub | Visible proof the main test path passed |
| Blocks bad merges | Not relevant (no collaborators) |
| Runs summary evals on every push | No — still manual by design |

CI was added as **scale + ops polish**: it shows evals can gate changes the way production teams do. You can:

- **Keep it** if you want automated regression checks on every push
- **Ignore it** until you push to GitHub
- **Remove or simplify** `.github/workflows/ci.yml` if you prefer less maintenance (e.g. lint + pytest only, skip Promptfoo in CI)

The **scripts** are the source of truth either way.

---

## Setting up CI on GitHub (optional)

1. Initialize git and push the repo to GitHub
2. GitHub Actions picks up `.github/workflows/ci.yml` automatically
3. On every push/PR, the `deterministic` job runs
4. For manual summary evals: **Settings → Secrets → Actions** → add `OPENAI_API_KEY`, then **Actions → CI → Run workflow**

---

## Related docs

| Doc | Topic |
|-----|--------|
| [`README.md`](README.md) | Project overview and eval commands |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture |
| [`promptfoo.md`](promptfoo.md) | How manual grading became Promptfoo automation |
| [`Evals-Journey.md`](Evals-Journey.md) | Session log + [eval concepts](Evals-Journey.md#evals-concepts-ground-up-guide) |

---

## One-sentence summary

**CI** auto-runs your deterministic test recipe on GitHub when you push; **`run_deterministic_evals.sh`** and **`run_summary_evals.sh`** are the same recipes (or a larger one) you run yourself in Terminal — for a personal project, the scripts matter; CI is optional automation.
