# Railway Deployment

Deploy the FinHub exception workbench (FastAPI + React) to [Railway](https://railway.com). Eval scripts run locally or in GitHub Actions — **not** on Railway.

For architecture context see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). User-facing overview: [`README.md`](README.md#deploy-to-railway-production).

## Prerequisites

- Railway account
- GitHub repo with this project pushed (do **not** commit `.env`)
- OpenAI API key for multi-agent workflow and analyst summaries

## 1. Create the service

1. In Railway: **New Project** → **Deploy from GitHub repo**
2. Select this repository (branch: `main`)
3. Railway reads `railway.json` and builds the **`Dockerfile`**:

   | Stage | Image | What it does |
   |-------|-------|----------------|
   | `frontend-builder` | `node:22-bookworm-slim` | `npm ci` + `vite build` → `frontend/dist` |
   | `runtime` | `ghcr.io/astral-sh/uv:python3.11-bookworm-slim` | `uv sync --frozen --no-dev`, copy `dist`, start API |

4. The container runs `uv run cfin-api`, binding `0.0.0.0:$PORT` when Railway sets `PORT`.

> **Note:** `nixpacks.toml` and `Procfile` are legacy/local references. Production deploys use the **Dockerfile** only (`railway.json` → `"builder": "DOCKERFILE"`).

If a deploy still shows Nixpacks `stage-0` logs, open **Deployments** → **Clear build cache & redeploy** after pulling latest `main`.

## 2. Public URL

1. Open your service → **Settings** → **Networking** → **Public Networking**
2. Click **Generate Domain**
3. Your workbench loads at the root URL; API at `/api/*` on the same host (no separate frontend server)

## 3. Environment variables

In the service **Variables** tab:

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | **Yes** | Multi-agent orchestration + analyst summaries |
| `SUMMARY_USE_LLM` | **Recommended** | Set `1` for LLM analyst summaries on tickets |
| `SUMMARY_MODEL` | No | Default `gpt-4o-mini`; often `gpt-4o` for demos |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini` for agent orchestration |
| `DISABLE_LLM` | No | Set `0` for multi-agent (default) |
| `FINHUB_DATA_DIR` | **Recommended** | e.g. `/data/finhub` — SQLite + attachment files |
| `RAILWAY_RUN_UID` | **Recommended** | Set `0` when using Docker + volumes (write permissions) |
| `LANGFUSE_PUBLIC_KEY` | No | Observability traces |
| `LANGFUSE_SECRET_KEY` | No | Observability traces |
| `LANGFUSE_HOST` or `LANGFUSE_BASE_URL` | No | e.g. `https://cloud.langfuse.com` |
| `STORAGE_BACKEND` | No | `local` (default) or `s3` for attachment blobs |
| `S3_*` | If `STORAGE_BACKEND=s3` | S3-compatible attachment storage |

Do **not** set `PORT` — Railway injects it automatically.

`SUMMARY_JUDGE_MODEL` and Promptfoo keys are for **local evals only** — not needed on Railway.

## 4. Durable storage (recommended)

Railway containers use an **ephemeral filesystem** by default. Without a volume, tickets and proof uploads are lost on redeploy.

### Create a Railway Volume

Volumes are **not** under Settings → Volumes in the current Railway UI. Use one of:

**Command palette (recommended)**

1. Open your **project canvas** (diagram view with the service box)
2. Press **`⌘K`** (Mac) or **`Ctrl+K`** (Windows/Linux)
3. Search **Create Volume** (or **Add Volume**)
4. Select your FinHub service
5. Set **mount path:** `/data`
6. Confirm — Railway redeploys the service

**Right-click**

- Right-click the project canvas → **Create Volume** → same steps as above

**CLI**

```bash
npx @railway/cli login
npx @railway/cli link
npx @railway/cli volume add --mount-path /data
```

### Configure the app

After attaching the volume:

1. Set variable: `FINHUB_DATA_DIR=/data/finhub`
2. Set variable: `RAILWAY_RUN_UID=0` (Docker runtime + volume writes)
3. Redeploy if not automatic

The app creates `/data/finhub/finhub.db` and attachment subdirs on first use. Bundled synthetic JSON (`documents.json`, mappings, etc.) stays in the Docker image under `/app/data/synthetic/`.

Railway also sets `RAILWAY_VOLUME_MOUNT_PATH` at runtime when a volume is attached — you do not need to define it manually.

### Option B — S3-compatible storage (attachments only)

Set `STORAGE_BACKEND=s3` and configure `S3_*` variables. Keep SQLite on a volume via `FINHUB_DATA_DIR`.

## 5. Health check

Configured in `railway.json`: `GET /api/health` (120s timeout).

Healthy response example:

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

If Langfuse variables are not set, `"langfuse": {"enabled": false}` is expected and does not block deployment.

## 6. Verify the deployment

1. Open your Railway domain — the React workbench should load (static files from `frontend/dist` served by FastAPI).
2. Confirm `https://<your-domain>/api/health` returns `"status": "ok"` and `"data_dir": "/data/finhub"` when the volume is configured.
3. In **Workbench Controls**:
   - **Reset & seed queue**
   - **Run agent processing**
   - Confirm tickets appear with agent diagnosis summaries
4. Open a ticket — add a comment, upload proof on **Resolved** (verifies volume + attachments).
5. Click **View trace in Langfuse** (when Langfuse is configured) on a newly processed ticket:
   - Root span `agentic-cfin-workflow`
   - Agent SDK spans (`OPENAI_MODEL`)
   - Generation `analyst-summary` (`SUMMARY_MODEL`) when `SUMMARY_USE_LLM=1`
6. **Persistence check:** redeploy once — tickets should still exist if the volume is mounted correctly.

## 7. Local development

```bash
uv sync
cp .env.example .env   # add OPENAI_API_KEY, optionally SUMMARY_USE_LLM=1
bash scripts/dev-workbench.sh   # backend :8000, frontend :5173 (Vite proxy)
```

Local dev uses two processes (API + Vite). Production uses one Docker container.

## 8. Production build (manual check)

**Without Docker** (API + pre-built frontend):

```bash
npm --prefix frontend ci
npm --prefix frontend run build
API_RELOAD=0 uv run cfin-api
# open http://127.0.0.1:8000
```

**With Docker** (matches Railway):

```bash
docker build -t finhub .
docker run --rm -p 8000:8000 \
  -e OPENAI_API_KEY=sk-... \
  -e SUMMARY_USE_LLM=1 \
  finhub
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Build shows Nixpacks `stage-0` / Node 20 | Clear build cache; ensure latest `main` with `Dockerfile` + `railway.json` |
| `uv: command not found` | Old Nixpacks deploy — switch to Dockerfile builder |
| Rolldown / native binding errors | Fixed by Dockerfile + Vite 6 pin; clear cache and redeploy |
| UI loads, API 404 | Check deploy logs; confirm `/api/health` |
| Sweep creates no tickets | Set `OPENAI_API_KEY`; check deploy **Logs** for errors |
| DB/upload permission denied | Set `RAILWAY_RUN_UID=0` and `FINHUB_DATA_DIR=/data/finhub` |
| Data lost after redeploy | Attach volume at `/data`; set `FINHUB_DATA_DIR` |
| No Langfuse trace link | Set Langfuse vars; re-sweep (old tickets have no trace ID) |

## Notes

- Bundled read-only synthetic data ships in the Docker image; runtime tickets and attachments use `FINHUB_DATA_DIR`
- Production frontend uses same-origin `/api` — do not set `VITE_API_BASE` unless splitting API and UI hosts
- CLI seed/sweep (`cfin-seed`, `cfin-sweep`) remain for automation; the UI workbench loop does not require them
- Legacy API endpoints (`/api/demo/*`, `/api/jobs/diagnose-new`) exist for scripting; the workbench uses `/api/workbench/*`
- Rotate any API key that was ever committed to git before making the repo public

## Related docs

| Doc | Topic |
|-----|--------|
| [`README.md`](README.md) | Setup, evals, Railway quick start |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Full system architecture |
| [`CI.md`](CI.md) | GitHub Actions vs local test scripts |
