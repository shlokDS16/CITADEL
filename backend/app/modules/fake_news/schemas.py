"""
Fake News Detector — Pydantic v2 schemas.

Contract: docs/module-specs/06-fake-news-detector.md. Request and response
models are kept separate (no shared base). Spec shapes are honored exactly;
production-layer fields (risk_score / layers / reasoning / needs_review /
quota_exhausted / nli_label / drift) are additive so spec consumers don't
break.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Mode = Literal["TEXT", "URL", "IMAGE", "VIDEO"]
Verdict = Literal["REAL", "LIKELY_REAL", "UNCERTAIN", "LIKELY_FAKE", "FAKE"]
ClaimVerdict = Literal["TRUE", "FALSE", "UNVERIFIED", "SUSPICIOUS", "MISLEADING"]
RequesterRole = Literal["citizen", "gov_analyst", "gov_admin"]
TrustRating = Literal["LOW", "MEDIUM", "HIGH"]

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MAX_TEXT = 20000


# --------------------------------------------------------------------------
# Health (Phase 0)
# --------------------------------------------------------------------------
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


# --------------------------------------------------------------------------
# Request
# --------------------------------------------------------------------------
class AnalyzeOptions(BaseModel):
    source_credibility: bool = True
    claim_by_claim: bool = True
    bias_detection: bool = True
    deepfake_detection: bool = False        # only meaningful for IMAGE/VIDEO
    cross_reference: bool = True            # search fact-check feeds / web


class AnalyzeIn(BaseModel):
    mode: Mode = "TEXT"
    text: Optional[str] = Field(None, max_length=_MAX_TEXT,
                                description="Article / message text (TEXT mode)")
    url: Optional[str] = Field(None, max_length=2048,
                               description="Article URL (URL mode)")
    media_blob_id: Optional[str] = Field(None, description="Uploaded image/video id")
    options: AnalyzeOptions = AnalyzeOptions()

    @field_validator("text")
    @classmethod
    def _clean_text(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = _CTRL.sub("", v).strip()
        return v[:_MAX_TEXT]

    @field_validator("url")
    @classmethod
    def _clean_url(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if v and not re.match(r"^https?://", v, re.I):
            v = "https://" + v
        return v or None

    @model_validator(mode="after")
    def _need_input(self) -> "AnalyzeIn":
        if self.mode in ("TEXT",) and not (self.text and self.text.strip()):
            raise ValueError("text is required for TEXT mode")
        if self.mode == "URL" and not self.url:
            raise ValueError("url is required for URL mode")
        if self.mode in ("IMAGE", "VIDEO") and not self.media_blob_id and not self.url:
            raise ValueError("media_blob_id or url is required for IMAGE/VIDEO mode")
        return self


class BulkIn(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=50)
    options: AnalyzeOptions = AnalyzeOptions()


class ReviewDecision(BaseModel):
    """HITL reviewer's resolution of a queued analysis."""
    human_verdict: Verdict
    notes: str = Field("", max_length=2000)


class FeedbackIn(BaseModel):
    analysis_id: str
    human_verdict: Verdict
    notes: str = Field("", max_length=2000)


class SourceUpdate(BaseModel):
    """Officer edit of a source-credibility row (runtime-editable)."""
    publisher_name: str | None = None
    trust_rating: Optional[Literal["LOW", "MEDIUM", "HIGH"]] = None
    score: int | None = Field(None, ge=0, le=100)
    in_allowlist: bool | None = None
    in_blocklist: bool | None = None
    bias_lean: Optional[Literal["left", "center", "right"]] = None
    notes: str | None = None


# --------------------------------------------------------------------------
# Response sub-shapes (spec-06)
# --------------------------------------------------------------------------
class Source(BaseModel):
    title: str | None = None
    url: str | None = None
    publisher: str | None = None
    snippet: str | None = None
    stance: Optional[Literal["support", "contradict", "neutral"]] = None


class ClaimAnalysis(BaseModel):
    id: str
    text: str
    verdict: ClaimVerdict
    confidence: float = Field(..., ge=0.0, le=1.0)
    notes: str = ""
    nli_label: Optional[Literal["entailment", "contradiction", "neutral"]] = None
    supporting_evidence: list[Source] = []
    contradicting_evidence: list[Source] = []


class SourceCredibility(BaseModel):
    publisher: str
    publisher_known: bool = False
    domain_age_days: int | None = None
    age_label: str = ""
    score: int = Field(0, ge=0, le=100)
    trust_rating: TrustRating = "MEDIUM"
    in_allowlist: bool = False
    in_blocklist: bool = False


class BiasProfile(BaseModel):
    left: int = 0
    center: int = 100
    right: int = 0
    confidence: float = 0.0


class SentimentBreakdown(BaseModel):
    positive: int = 0
    negative: int = 0
    neutral: int = 100


class ManipulationProfile(BaseModel):
    clickbait: int = 0
    urgency: int = 0
    authority_claim: int = 0
    emotional: int = 0


class RelatedFactCheck(BaseModel):
    title: str
    publisher: str
    url: str
    published_at: str | None = None
    matched_claim_ids: list[str] = []


# --------------------------------------------------------------------------
# Response (spec-06 + additive production fields)
# --------------------------------------------------------------------------
class AnalysisOut(BaseModel):
    id: str
    requester_id: str | None = None
    requester_role: RequesterRole = "citizen"
    submitted_at: datetime
    completed_at: datetime | None = None
    mode: Mode
    input_excerpt: str = ""
    verdict: Verdict
    confidence: float = Field(..., ge=0.0, le=1.0)
    # --- additive production fields ---
    risk_score: float = Field(0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    quota_exhausted: bool = False
    # --- spec analysis payload ---
    claims: list[ClaimAnalysis] = []
    source_credibility: SourceCredibility | None = None
    bias_profile: BiasProfile | None = None
    sentiment: SentimentBreakdown | None = None
    red_flags: list[str] = []
    manipulation: ManipulationProfile | None = None
    related_fact_checks: list[RelatedFactCheck] = []
    reasoning: list[str] = []
    layers: dict[str, Any] = {}
    model_versions: dict[str, str] = {}
    response_time_ms: int = 0


class BulkItem(BaseModel):
    url: str
    verdict: Literal["REAL", "LIKELY_FAKE", "FAKE", "UNCERTAIN", "ERROR"] = "UNCERTAIN"
    confidence: float = 0.0
    analysis_id: str | None = None
    error: str | None = None


class BulkBatchOut(BaseModel):
    id: str
    submitted_at: datetime
    total: int
    completed: int
    items: list[BulkItem] = []
