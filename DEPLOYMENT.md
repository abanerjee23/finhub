# Railway Deployment

Deploy the Streamlit dashboard to [Railway](https://railway.com). Eval scripts run locally or in GitHub Actions — not on Railway.

## Prerequisites

- Railway account
- GitHub repo with this project pushed (do **not** commit `.env`)
- OpenAI API key for multi-agent workflow and analyst summaries

## 1. Create the service

1. In Railway: **New Project** → **Deploy from GitHub repo**
2. Select this repository
3. Railway detects `railway.json` and uses Nixpacks to build

## 2. Configure environment variables

In the Railway service **Variables** tab, set:

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPENAI_API_KEY` | Yes | Multi-agent orchestration + analyst summaries |
| `OPENAI_MODEL` | No | Default `gpt-4o-mini` |
| `SUMMARY_MODEL` | No | Default `gpt-4o-mini` |
| `DISABLE_LLM` | No | Set `0` for multi-agent (default) |
| `LANGFUSE_PUBLIC_KEY` | No | Observability traces |
| `LANGFUSE_SECRET_KEY` | No | Observability traces |
| `LANGFUSE_HOST` | No | e.g. `https://cloud.langfuse.com` |

Railway sets `PORT` automatically. The start command in `railway.json` binds Streamlit to `0.0.0.0:${PORT}`.

## 3. Health check

Railway uses `/_stcore/health` (configured in `railway.json`). The app should report healthy once Streamlit is listening.

## 4. Verify the deployment

1. Open the generated Railway URL
2. Select a failed document (e.g. `DOC-1002`)
3. Click **Run guarded workflow**
4. Confirm `execution_mode` shows `openai_agents_sdk_guarded` when `OPENAI_API_KEY` is set
5. Open the **Eval Results** page in the sidebar to view logged summary eval runs (after running evals locally or in CI)

Summary eval golden labels: 10 docs in `evals/summary_cases.yaml`. Human Excel workbook (`AI Evals_SM5_v0.6.xlsx`) covers 3 starter docs + rubric — optional to sync the remaining 7 rows.

## 5. Local parity check

```bash
uv sync
cp .env.example .env   # add OPENAI_API_KEY
uv run streamlit run app/streamlit_app.py
```

## Notes

- Synthetic data is bundled in `data/synthetic/` — no external database required
- Do not put Promptfoo or eval API keys in Railway unless you intentionally run evals in CI only
- Rotate any API key that was ever committed to git before making the repo public
