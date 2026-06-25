from __future__ import annotations


def call_api(prompt: str, options: dict | None = None, context: dict | None = None) -> dict:
    """Return a pre-written summary from test vars (no workflow run)."""
    vars_ = (context or {}).get("vars", {})
    generated_summary = vars_.get("generated_summary") or prompt
    return {
        "output": generated_summary,
        "metadata": {
            "case_id": vars_.get("case_id"),
            "document_id": vars_.get("document_id"),
            "calibration_label": vars_.get("expected_pass"),
        },
    }
