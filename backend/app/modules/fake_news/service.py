"""
Fake News Detector — service layer.

Phase 0: real liveness/readiness report (no mock values). The waterfall
orchestrator, HITL, history and drift glue arrive in later phases.
"""
from __future__ import annotations

import logging
import sys
from importlib import metadata
from pathlib import Path

from app import __version__
from app.config import settings
from app.modules.fake_news import schemas

log = logging.getLogger("citadel.fake_news.service")

# Spec-06 + extension tables this module relies on.
_EXPECTED_TABLES = [
    "analyses",
    "claim_analyses",
    "source_credibility_db",
    "fact_check_feed",
    "learn_content",
    "fn_debunked",
    "fn_review_queue",
    "fn_feedback",
    "fn_drift_snapshots",
    "fn_meta_weights",
    "fn_propagation_runs",
]


def _pkg(name: str) -> str | None:
    """Package version via metadata — does NOT import the module (fast)."""
    try:
        return metadata.version(name)
    except Exception:
        return None


def _probe_tables() -> tuple[bool, list[str]]:
    """Best-effort: which expected tables are reachable via service-role.

    A missing table is normal until the user runs backend/sql/fake_news_schema.sql
    — the module degrades gracefully, so this is informational, not fatal.
    """
    try:
        from app.database import get_supabase

        sb = get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase client unavailable: %s", e)
        return False, list(_EXPECTED_TABLES)

    missing: list[str] = []
    for t in _EXPECTED_TABLES:
        try:
            sb.table(t).select("*").limit(1).execute()
        except Exception:  # noqa: BLE001 — table absent / not yet created
            missing.append(t)
    return (len(missing) == 0), missing


def health() -> schemas.HealthResponse:
    """Readiness probe — real signals only."""
    models_dir = settings.fn_models_path
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        models_dir_ok = models_dir.is_dir()
    except Exception as e:  # noqa: BLE001
        log.warning("models dir not creatable: %s", e)
        models_dir_ok = False

    tables_ok, missing = _probe_tables()

    notes: list[str] = []
    if missing:
        notes.append(
            f"{len(missing)} table(s) not found — run backend/sql/fake_news_schema.sql "
            "in the Supabase SQL editor."
        )
    if not settings.GOOGLE_FACTCHECK_API_KEY:
        notes.append("GOOGLE_FACTCHECK_API_KEY not set — keyless fact-check fallbacks will be used.")
    if not settings.FN_ENABLE_HEAVY_MODELS:
        notes.append("FN_ENABLE_HEAVY_MODELS=false — propaganda/NLI/deepfake disabled (lean profile).")

    return schemas.HealthResponse(
        status="ok",
        module="fake_news",
        version=__version__,
        python=sys.version.split()[0],
        ml=schemas.MLRuntime(
            torch=_pkg("torch"),
            transformers=_pkg("transformers"),
            onnxruntime=_pkg("onnxruntime"),
            huggingface_hub=_pkg("huggingface_hub"),
            scikit_learn=_pkg("scikit-learn"),
        ),
        models_dir=str(models_dir),
        models_dir_ok=models_dir_ok,
        models_configured={
            "fake_news": settings.FN_MODEL_FAKE,
            "clickbait": settings.FN_MODEL_CLICKBAIT,
            "propaganda": settings.FN_MODEL_PROPAGANDA,
            "nli": settings.FN_MODEL_NLI,
            "bias": settings.FN_MODEL_BIAS,
            "deepfake": settings.FN_MODEL_DEEPFAKE,
            "deepfake_fallback": settings.FN_MODEL_DEEPFAKE_FALLBACK,
        },
        tables_ok=tables_ok,
        tables_missing=missing,
        groq_configured=bool(settings.GROQ_API_KEY),
        google_factcheck_configured=bool(settings.GOOGLE_FACTCHECK_API_KEY),
        notes=notes,
    )
