"""Pydantic schemas for the Resume Screening API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ---- Enums ----
Urgency = Literal["LOW", "NORMAL", "HIGH"]
JobStatus = Literal["draft", "open", "closed", "archived"]
CandidateStatus = Literal["PROCESSING", "SHORTLISTED", "REJECTED", "INTERVIEW", "OFFER", "RECRUITED"]
RejectReason = Literal["skills_gap", "experience_gap", "location", "compensation", "cultural_fit", "other"]


# ===========================================================
# Job
# ===========================================================
class ScoringWeights(BaseModel):
    skills: int = 40
    experience: int = 25
    education: int = 15
    location: int = 10
    culture_fit: int = 10


class BiasFlags(BaseModel):
    redact_gender: bool = True
    redact_age: bool = True
    redact_location: bool = False
    redact_name: bool = True


class JobCreateRequest(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    urgency: Urgency = "NORMAL"
    openings: int = 1
    raw_jd_text: Optional[str] = None
    parsed_jd: Optional[dict[str, Any]] = None      # if caller already parsed
    auto_shortlist_threshold: float = 70.0
    posted_by: Optional[str] = "RSD"


class JobUpdateRequest(BaseModel):
    title: Optional[str] = None
    department: Optional[str] = None
    urgency: Optional[Urgency] = None
    openings: Optional[int] = None
    status: Optional[JobStatus] = None
    raw_jd_text: Optional[str] = None
    parsed_jd: Optional[dict[str, Any]] = None
    scoring_weights: Optional[ScoringWeights] = None
    bias_flags: Optional[BiasFlags] = None
    auto_shortlist_threshold: Optional[float] = None


class JobOut(BaseModel):
    id: UUID
    code: str
    title: str
    department: Optional[str] = None
    urgency: Urgency
    status: JobStatus
    openings: int
    raw_jd_text: Optional[str] = None
    parsed_jd: dict[str, Any]
    scoring_weights: dict[str, int]
    bias_flags: dict[str, bool]
    auto_shortlist_threshold: float
    posted_by: Optional[str] = None
    posted_at: datetime
    days_open: int
    applicants: int = 0
    shortlisted: int = 0
    interviewing: int = 0
    offered: int = 0
    recruited: int = 0
    rejected: int = 0


class JDParseRequest(BaseModel):
    text: str = Field(..., min_length=10)


class JDParseResponse(BaseModel):
    parsed_jd: dict[str, Any]


# ===========================================================
# Candidate
# ===========================================================
class CandidateSummaryOut(BaseModel):
    id: UUID
    code: str
    job_id: UUID
    name: Optional[str] = None
    email: Optional[str] = None
    location: Optional[str] = None
    total_experience_years: Optional[float] = None
    final_score: Optional[float] = None
    status: CandidateStatus
    source: Optional[str] = "Direct"
    top_skills: list[str] = Field(default_factory=list)
    applied_at: datetime


class CandidateDetailOut(CandidateSummaryOut):
    parsed_resume: dict[str, Any]
    score_breakdown: Optional[dict[str, float]] = None
    scoring_config_snapshot: Optional[dict[str, Any]] = None
    ai_insights: list[dict[str, Any]] = Field(default_factory=list)
    bias_panel: Optional[dict[str, Any]] = None
    skill_profile: dict[str, float] = Field(default_factory=dict)
    notes: list[dict[str, Any]] = Field(default_factory=list)
    pipeline_history: list[dict[str, Any]] = Field(default_factory=list)
    cv_filename: Optional[str] = None
    cv_storage_url: Optional[str] = None
    rejection_reason: Optional[str] = None
    rejection_note: Optional[str] = None
    scheduled_interview_at: Optional[datetime] = None


class CandidateUploadResponse(BaseModel):
    batch_id: str
    job_id: UUID
    total: int
    candidates: list[dict[str, str]]      # [{code, filename}]


# ===========================================================
# Pipeline / actions
# ===========================================================
class MoveStageRequest(BaseModel):
    new_status: CandidateStatus
    note: Optional[str] = None


class RejectRequest(BaseModel):
    reason: RejectReason = "other"
    note: Optional[str] = None
    send_telegram: bool = True
    use_ai_cheerup: bool = False
    custom_hint: Optional[str] = None         # extra context for AI cheerup


class ScheduleInterviewRequest(BaseModel):
    when: datetime                          # interview datetime
    prep: Optional[str] = None              # what to prepare
    send_telegram: bool = True


class AddNoteRequest(BaseModel):
    text: str
    author: Optional[str] = "RSD"


class CompareRequest(BaseModel):
    candidate_ids: list[str] = Field(..., min_length=2, max_length=3)


# ===========================================================
# Settings (per job)
# ===========================================================
class SettingsUpdateRequest(BaseModel):
    scoring_weights: Optional[ScoringWeights] = None
    bias_flags: Optional[BiasFlags] = None
    auto_shortlist_threshold: Optional[float] = None


# ===========================================================
# Telegram
# ===========================================================
class TelegramStatusOut(BaseModel):
    bot_ok: bool
    bot_username: Optional[str] = None
    chats: list[dict[str, Any]]
    bot_error: Optional[str] = None
