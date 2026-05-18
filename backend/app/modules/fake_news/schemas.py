"""
Fake News Detector — Pydantic schemas.

Phase 0: health only. Request/response analysis schemas (spec-06 shapes:
AnalyzeIn / AnalysisOut / ClaimAnalysis / SourceCredibility / BiasProfile /
ManipulationProfile / RelatedFactCheck / BulkBatchOut …) land in Phase 1.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MLRuntime(BaseModel):
    torch: str | None = None
    transformers: str | None = None
    onnxruntime: str | None = None
    huggingface_hub: str | None = None
    scikit_learn: str | None = None


class HealthResponse(BaseModel):
    status: str = Field(..., examples=["ok"])
    module: str = "fake_news"
    version: str
    python: str
    ml: MLRuntime
    models_dir: str
    models_dir_ok: bool
    models_configured: dict[str, str]
    tables_ok: bool
    tables_missing: list[str] = []
    groq_configured: bool
    google_factcheck_configured: bool
    notes: list[str] = []
