from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUNDLED_DATA_DIR = PROJECT_ROOT / "data" / "synthetic"


def runtime_data_dir() -> Path:
    """Mutable workbench state: SQLite DB and attachment files."""
    override = os.getenv("FINHUB_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return BUNDLED_DATA_DIR


def attachment_backend_name() -> str:
    return os.getenv("STORAGE_BACKEND", "local").strip().lower() or "local"
