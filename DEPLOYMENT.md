# Railway Deployment

Deploy the FinHub exception workbench (FastAPI + React) to [Railway](https://railway.com). Eval scripts run locally or in GitHub Actions — **not** on Railway.

For architecture context see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Prerequisites

- Railway account
- GitHub repo with this project pushed (do **not** commit `.env`)
- OpenAI API key for multi-agent workflow and analyst summaries

## 1. Create the service

1. In Railway: **New Project** → **Deploy from GitHub repo**
2. Select this repository
3. Railway uses the **`Dockerfile`** (see `railway.json`):
   - Stage 1: Node 22 → `npm ci` + `vite build` in `frontend/`
   - Stage 2: Python 3.11 + `uv sync` → copies built `frontend/dist`
   - Starts `uv run cfin-api` on `$PORT`

> **Note:** `nixpacks.toml` is kept for reference only; production deploys use the Dockerfile for reproducible Linux builds.

## 2. Configure environment variables

In the Railway service **Variables** tab, set:

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Yes | Multi-agent orchestration + analyst summaries |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini` |
| `SUMMARY_MODEL` | No | Default `gpt-4o-mini` |
| `SUMMARY_USE_LLM` | No | Set `1` to persist LLM-generated analyst summaries on tickets |
| `SUMMARY_JUDGE_MODEL` | No | Default `gpt-4o` (evals only — not needed on Railway) |
| `DISABLE_LLM` | No | Set `0` for multi-agent (default) |
| `LANGFUSE_PUBLIC_KEY` | No | Observability traces |
| `LANGFUSE_SECRET_KEY` | No | Observability traces |
| `LANGFUSE_HOST` or `LANGFUSE_BASE_URL` | No | e.g. `https://cloud.langfuse.com` (either name works) |
| `FINHUB_DATA_DIR` | **Recommended** | Directory for SQLite DB + local attachments |
| `STORAGE_BACKEND` | No | `local` (default) or `s3` for attachment blobs |
| `S3_BUCKET` | If `STORAGE_BACKEND=s3` | Object storage bucket |
| `S3_ENDPOINT_URL` | No | S3-compatible endpoint (Railway Buckets, R2, MinIO) |
| `S3_ACCESS_KEY_ID` | If using S3 | Access key |
| `S3_SECRET_ACCESS_KEY` | If using S3 | Secret key |
| `S3_REGION` | No | Default `auto` |
| `S3_PREFIX` | No | Key prefix, default `attachments/` |

Railway sets `PORT` automatically. The API binds `0.0.0.0:$PORT` when `PORT` is present.

## 3. Durable storage (recommended for demos)

Railway containers use an **ephemeral filesystem** by default. Without persistence, tickets and proof uploads are lost on redeploy.

### Option A — Railway Volume (recommended)

1. In the service: **Settings → Volumes → Add Volume**
2. Mount path: `/data`
3. Set variable: `FINHUB_DATA_DIR=/data/finhub`
4. Redeploy

SQLite (`finhub.db`) and attachment files live on the volume. Bundled synthetic documents/mappings stay in the Docker image.

### Option B — S3-compatible object storage (attachments only)

Set `STORAGE_BACKEND=s3` and configure `S3_*` variables. Keep SQLite on a volume via `FINHUB_DATA_DIR`.

## 4. Health check

Railway uses `/api/health` (configured in `railway.json`). A healthy response includes:

```json
{
  "status": "ok",
  "storage_backend": "local",
  "data_dir": "/data/finhub",
  "langfuse": {
    "enabled": true,
    "connected": true,
    "host": "https://cloud.langfuse.com"
  }
}
```

If Langfuse variables are not set, `langfuse.enabled` is `false` — that is expected and does not block deployment.

## 5. Verify the deployment

1. Open the generated Railway URL — the React workbench should load (built `frontend/dist` served by FastAPI).
2. Confirm `/api/health` returns `"status": "ok"`. If Langfuse is configured, confirm `"langfuse": {"connected": true}`.
3. In the UI **Workbench Controls** panel:
   - Click **Reset & seed queue**
   - Click **Run agent processing**
   - Confirm tickets appear with agent diagnosis summaries
4. Open a ticket, add a comment, upload proof on resolve to verify attachment storage.
5. On ticket detail, click **View trace in Langfuse** (when Langfuse is configured) and confirm:
   - Root span `agentic-cfin-workflow`
   - Agent SDK spans (`OPENAI_MODEL`)
   - Generation `analyst-summary` (`SUMMARY_MODEL`) when `SUMMARY_USE_LLM=1`

## 6. Local dev

```bash
uv sync
cp .env.example .env   # add OPENAI_API_KEY, optionally SUMMARY_USE_LLM=1
bash scripts/dev-workbench.sh   # backend :8000, frontend :5173 (Vite proxy)
```

Local dev uses two processes (API + Vite). Production uses a single process serving API + static build.

## 7. Production build (manual check)

To verify the production bundle locally:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
API_RELOAD=0 uv run cfin-api
# open http://127.0.0.1:8000
```

## Notes

- Bundled read-only synthetic data ships in `data/synthetic/`; runtime tickets and attachments use `FINHUB_DATA_DIR`
- Production frontend uses same-origin `/api` (no separate Vite server); do not set `VITE_API_BASE` unless splitting API and UI
- **Build troubleshooting:** production builds use the **`Dockerfile`** (Node 22 + Python 3.11), not Nixpacks. If an old Nixpacks deploy shows Node 20 or Rolldown/`tsc` errors, trigger a fresh deploy after pulling latest `main`. In Railway → service → **Deployments** → **Clear build cache** if needed.
- Do not put Promptfoo or eval-only keys in Railway unless you intentionally run evals there
- Rotate any API key that was ever committed to git before making the repo public
- CLI seed/sweep (`cfin-seed`, `cfin-sweep`) remain available for automation; the UI workbench loop does not require them
- **Legacy API** endpoints (`/api/demo/*`, `/api/jobs/diagnose-new`) exist for scripting; the workbench uses `/api/workbench/*`

## Related docs

| Doc | Topic |
|-----|--------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full system architecture |
| [`README.md`](README.md) | Setup, evals, environment variables |
| [`CI.md`](CI.md) | GitHub Actions vs local test scripts |
