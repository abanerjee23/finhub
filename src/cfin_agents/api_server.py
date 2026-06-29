from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


def main() -> None:
    import uvicorn

    from dotenv import load_dotenv

    load_dotenv()

    on_railway = bool(os.getenv("PORT"))
    host = os.getenv("API_HOST", "0.0.0.0" if on_railway else "127.0.0.1")
    port = int(os.getenv("PORT", os.getenv("API_PORT", "8000")))
    default_reload = "0" if on_railway else "1"
    reload = os.getenv("API_RELOAD", default_reload).lower() in {"1", "true", "yes"}
    uvicorn.run(
        "cfin_agents.api:app",
        host=host,
        port=port,
        reload=reload,
        # Avoid restarting mid-request when demo JSON files are written.
        reload_dirs=[str(PACKAGE_DIR)],
        reload_excludes=["*.json", "*.jsonl"],
    )
