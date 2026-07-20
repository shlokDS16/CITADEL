"""
Pydantic request/response models for the tickets module.

Shapes follow docs/module-specs/07-support-tickets.md. Where the spec and
the frontend mock disagree, the mock wins on field *names* the UI already
renders (pages.jsx:7792-7950) — the backend adapts, not the UI.

Category values are underscored on the wire (`Public_Safety`) to match the
DB CHECK constraint; `display_category` carries the spaced form the UI
shows. Request models accept either.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------
# Domains — single source of truth, mirrored by the DB CHECK constraints in
# migration 20260720000005. Changing one without the other will 23514.
# --------------------------------------------------------------------------
Category = Literal[
    "Roads", "Water", "Electric", "Sanitation", "Public_Safety", "Parks",
    "Health", "Drainage", "Traffic", "Planning", "Other",
]
Priority = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]
Department = Literal[
    "PWD", "Water_Board", "Electricity_Board", "Sanitation", "Police",
    "Parks", "Health", "Drainage", "Traffic", "Planning",
]
TicketStatus = Literal[
    "open", "assigned", "in_progress", "verification", "resolved",
    "closed", "reopened",
]
SlaStatus = Literal["on_track", "at_risk", "breached"]
Sentiment = Literal["positive", "neutral", "negative"]
AttachmentType = Literal["photo", "video", "voice", "location", "file"]
ActorRole = Literal["citizen", "gov_officer", "gov_admin", "system"]
Visibility = Literal["public", "internal"]

CATEGORIES: tuple[str, ...] = (
    "Roads", "Water", "Electric", "Sanitation", "Public_Safety", "Parks",
    "Health", "Drainage", "Traffic", "Planning", "Other",
)

#: UI spells some categories with a space; the DB uses underscores.
DISPLAY_CATEGORY = {c: c.replace("_", " ") for c in CATEGORIES}


def normalize_category(value: str | None) -> str | None:
    """Accept 'Public Safety', 'public_safety', 'PUBLIC SAFETY' → 'Public_Safety'.

    Returns None for None / blank / the UI's 'Auto-detect' sentinel, which
    all mean "let the classifier decide".
    """
    if value is None:
        return None
    raw = value.strip()
    if not raw or raw.lower() in {"auto-detect", "auto", "autodetect"}:
        return None
    key = raw.replace(" ", "_").replace("-", "_").lower()
    for c in CATEGORIES:
        if c.lower() == key:
            return c
    return None


# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------
class TableStatus(BaseModel):
    name: str
    present: bool
    rows: Optional[int] = Field(default=None, description="null when the table is absent")


class ClassifierStatus(BaseModel):
    mode: Literal["groq", "rules", "unavailable"] = Field(
        ..., description="Which path the next classification will actually take."
    )
    groq_configured: bool
    groq_model: Optional[str] = None
    rules_loaded: int = Field(..., description="Active routing_rules rows.")
    vader_available: bool


class StorageStatus(BaseModel):
    bucket: str
    ready: bool
    private: bool = Field(
        ..., description="Attachments are citizen PII — a public bucket is a failure."
    )


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    module: Literal["tickets"]
    version: str
    tables: list[TableStatus]
    classifier: ClassifierStatus
    storage: StorageStatus
    queue_depth: dict[str, int] = Field(
        default_factory=dict,
        description="Unresolved ticket count per department.",
    )
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Templates
# --------------------------------------------------------------------------
class TicketTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    body: str
    category: Category
    display_category: str


# --------------------------------------------------------------------------
# Classification / preview
# --------------------------------------------------------------------------
class TicketPreviewIn(BaseModel):
    subject: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=4000)
    category: Optional[str] = Field(
        default=None,
        description="Citizen override. 'Auto-detect' / null → classifier decides.",
    )
    priority: str = Field(
        default="AUTO",
        description="Citizen override. 'AUTO' → classifier decides.",
    )

    @field_validator("priority")
    @classmethod
    def _upper(cls, v: str) -> str:
        return (v or "AUTO").strip().upper()


class TicketPreviewOut(BaseModel):
    predicted_category: Category
    display_category: str
    predicted_priority: Priority
    predicted_department: Department
    predicted_sla_label: str = Field(..., examples=["4 hours", "48 hours"])
    predicted_sla_due_at: datetime
    sentiment: Sentiment
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning_summary: str = Field(
        ..., description="One line, e.g. 'Public safety + urgency cues → Police HIGH'."
    )
    source: Literal["groq", "rules"] = Field(
        ..., description="Which classifier actually produced this. Never fabricated."
    )
    quota_exhausted: bool = Field(
        default=False,
        description="True when Groq was rate-limited and the rule router answered instead.",
    )


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------
class TicketCreateIn(BaseModel):
    subject: str = Field(..., min_length=3, max_length=200)
    description: str = Field(default="", max_length=4000)
    category: Optional[str] = None
    priority: str = "AUTO"
    is_anonymous: bool = False
    geo_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    geo_lng: Optional[float] = Field(default=None, ge=-180, le=180)
    location_label: Optional[str] = Field(default=None, max_length=255)

    @field_validator("priority")
    @classmethod
    def _upper(cls, v: str) -> str:
        return (v or "AUTO").strip().upper()


# --------------------------------------------------------------------------
# Read
# --------------------------------------------------------------------------
class AttachmentOut(BaseModel):
    id: str
    type: AttachmentType
    name: str
    size_bytes: int
    mime_type: Optional[str] = None
    download_url: Optional[str] = Field(default=None, description="Pre-signed, 5 min TTL.")
    transcript: Optional[str] = None


class TicketUpdateOut(BaseModel):
    id: str
    ticket_id: str
    actor_id: Optional[str] = None
    actor_label: str
    actor_role: ActorRole
    text: str
    visibility: Visibility
    created_at: datetime


class TicketOut(BaseModel):
    id: str
    subject: str
    description: str
    category: Category
    display_category: str
    priority: Priority
    priority_was_auto: bool
    status: TicketStatus
    department: Department
    submitted_by: Optional[str] = None
    is_anonymous: bool
    geo_lat: Optional[float] = None
    geo_lng: Optional[float] = None
    location_label: Optional[str] = None
    upvotes: int
    age: str = Field(..., description="Human-readable, e.g. '2d', '3h'.")
    step: int = Field(
        ...,
        ge=0,
        le=4,
        description="Timeline index the UI renders (pages.jsx StatusTimeline).",
    )
    created_at: datetime
    assigned_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    sla_due_at: datetime
    sla_status: SlaStatus
    rating: Optional[int] = None
    sentiment: Optional[Sentiment] = None
    ai_classification: dict[str, Any] = Field(default_factory=dict)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    updates: list[TicketUpdateOut] = Field(default_factory=list)


class TicketListMeta(BaseModel):
    total: int
    limit: int
    offset: int


class TicketListOut(BaseModel):
    data: list[TicketOut]
    meta: TicketListMeta


class TicketStatsOut(BaseModel):
    open: int
    in_progress: int
    resolved: int
    avg_resolution: str = Field(
        ..., description="Mean over resolved tickets, or '—' when there are none."
    )
    by_status: dict[str, int] = Field(default_factory=dict)


class TicketUpdateIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


class TicketRateIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=2000)


class TicketReopenIn(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class TicketCreateOut(BaseModel):
    ticket: TicketOut
    preview: TicketPreviewOut = Field(
        ..., description="The classification actually applied to this ticket."
    )
