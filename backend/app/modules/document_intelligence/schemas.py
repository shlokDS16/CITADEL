"""
Pydantic v2 request / response models for the Document Intelligence module.
Schemas are the contract — frontend mocks must match these shapes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ---- enums (string Literals — narrow, OpenAPI-friendly) ----

DocumentType = Literal[
    "invoice", "contract", "id_document", "government_permit", "tender_notice",
    "permit", "report", "receipt", "affidavit", "certificate", "auto_detect",
]

ResolvedDocumentType = Literal[
    "invoice", "contract", "id_document", "government_permit", "tender_notice",
    "permit", "report", "receipt", "affidavit", "certificate",
]

Language = Literal["en", "hi", "en+hi"]
Priority = Literal["low", "normal", "high", "urgent"]
DocumentStatus = Literal["PROCESSING", "PENDING_REVIEW", "APPROVED", "REJECTED", "ARCHIVED"]
SignatureStatus = Literal["detected", "not_found", "unclear"]
PIIStatus = Literal["REDACTED", "FLAGGED"]
DocAction = Literal["approve", "reject", "archive", "reassign", "delete"]


# ============================================================
# Upload
# ============================================================
class UploadResponseFile(BaseModel):
    doc_id: str
    filename: str
    storage_path: str


class UploadResponse(BaseModel):
    batch_id: UUID
    total: int
    documents: list[UploadResponseFile]
    message: str = "Upload accepted — processing in background."


# ============================================================
# PII (per-finding)
# ============================================================
class PIIFindingOut(BaseModel):
    label: str
    count: int
    status: PIIStatus
    confidence: float
    positions: list[tuple[int, int]] = Field(default_factory=list)
    note: Optional[str] = None


# ============================================================
# Document core
# ============================================================
class DocumentBase(BaseModel):
    doc_id: str
    filename: str
    document_type: str
    status: DocumentStatus
    priority: Priority
    confidence: Optional[float] = None
    language: Language = "en"
    tags: list[str] = Field(default_factory=list)
    department: Optional[str] = None
    title: Optional[str] = None
    uploaded_by: Optional[str] = None
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    created_at: datetime
    processed_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    sla_breached: bool = False


class DocumentSummaryOut(DocumentBase):
    """Compact view used in queue + library lists."""
    time_ago: Optional[str] = None
    pii_count: int = 0
    signature_status: Optional[SignatureStatus] = None


class DocumentDetailOut(DocumentBase):
    """Full document with extracted text + PII + signature + tags + storage url."""
    extracted_text_preview: Optional[str] = None
    extracted_text: Optional[str] = None
    redacted_text: Optional[str] = None
    extracted_fields: Optional[dict[str, Any]] = None
    pii_enabled: bool = False
    pii_results: Optional[dict[str, PIIFindingOut]] = None
    pii_count: int = 0
    signature_enabled: bool = False
    signature_status: Optional[SignatureStatus] = None
    template_id: Optional[UUID] = None
    storage_url: Optional[str] = None


# ============================================================
# Batch results
# ============================================================
class BatchResultDocument(BaseModel):
    doc_id: str
    filename: str
    document_type: str
    confidence: Optional[float] = None
    status: DocumentStatus
    pii_results: dict[str, dict] = Field(default_factory=dict)
    signature_status: Optional[SignatureStatus] = None
    tags: list[str] = Field(default_factory=list)
    extracted_text_preview: Optional[str] = None


class BatchResultsOut(BaseModel):
    batch_id: UUID
    total_processed: int
    successful: int
    failed: int
    avg_confidence: float
    pii_found_total: int
    documents: list[BatchResultDocument]
    export_options: list[str] = Field(default_factory=lambda: ["csv", "json"])


# ============================================================
# Audit log
# ============================================================
class AuditEntryOut(BaseModel):
    id: UUID
    document_id: Optional[UUID] = None
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    performed_by: Optional[str] = None
    created_at: datetime


class AuditLogOut(BaseModel):
    doc_id: str
    entries: list[AuditEntryOut]


# ============================================================
# Actions
# ============================================================
class BulkActionRequest(BaseModel):
    doc_ids: list[str] = Field(..., min_length=1, max_length=200)
    action: DocAction
    performed_by: Optional[str] = "system"
    reason: Optional[str] = None         # required for reject


class ActionResponse(BaseModel):
    doc_id: str
    action: DocAction
    new_status: DocumentStatus
    success: bool
    message: Optional[str] = None


class BulkActionResponse(BaseModel):
    requested: int
    successful: int
    failed: int
    results: list[ActionResponse]


# ============================================================
# Library
# ============================================================
class LibraryItemOut(BaseModel):
    doc_id: str
    document_type: str
    title: Optional[str] = None
    filename: str
    file_size: str
    file_size_bytes: int
    tags: list[str] = Field(default_factory=list)
    department: Optional[str] = None
    archived_at: Optional[datetime] = None
    storage_url: Optional[str] = None
    mime_type: Optional[str] = None


class LibraryListOut(BaseModel):
    items: list[LibraryItemOut]
    total: int


class LibraryExportRequest(BaseModel):
    doc_ids: Optional[list[str]] = None     # None → export all archived (capped)


# ============================================================
# Queue
# ============================================================
class QueueListOut(BaseModel):
    items: list[DocumentSummaryOut]
    total: int
    page: int
    per_page: int
    total_pages: int


# ============================================================
# Templates
# ============================================================
class TemplateField(BaseModel):
    name: str
    type: str
    required: bool = False


class TemplateOut(BaseModel):
    id: UUID
    name: str
    document_type: str
    fields: list[TemplateField]
    is_system: bool = False
    avg_accuracy: float = 0
    docs_processed: int = 0
    created_at: datetime
    updated_at: datetime


class TemplateCreateRequest(BaseModel):
    name: str
    document_type: str
    fields: list[TemplateField]


class TemplateUpdateRequest(BaseModel):
    name: Optional[str] = None
    fields: Optional[list[TemplateField]] = None
    passport_key: Optional[str] = None


class TemplateAccessRequest(BaseModel):
    passport_key: str = Field(..., min_length=4, max_length=64)


class TemplateAccessResponse(BaseModel):
    access_granted: bool
    reason: Optional[str] = None


# ============================================================
# Edit
# ============================================================
class EditViewOut(BaseModel):
    doc_id: str
    document_type: str
    template_id: Optional[UUID] = None
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    template_fields: list[TemplateField] = Field(default_factory=list)
    extracted_text: Optional[str] = None
    requires_passport_key: bool = False


class EditSaveRequest(BaseModel):
    fields: dict[str, Any] = Field(default_factory=dict)
    extracted_text: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    department: Optional[str] = None
    passport_key: Optional[str] = None


class EditSaveResponse(BaseModel):
    doc_id: str
    saved: bool
    reindexed: bool
    message: Optional[str] = None


# ============================================================
# Dashboard
# ============================================================
DashboardPeriod = Literal["7d", "14d", "30d", "90d"]


class StatBlock(BaseModel):
    value: float | int
    change_percent: float
    trend: Literal["up", "down", "flat"]


class DashboardStatsOut(BaseModel):
    docs_processed: StatBlock
    avg_confidence: StatBlock
    pii_redactions: StatBlock
    avg_time_to_approve: StatBlock          # value in hours


class VolumeBucket(BaseModel):
    date: str
    count: int


class VolumeOut(BaseModel):
    period: DashboardPeriod
    data: list[VolumeBucket]
    today_count: int


class TypeBreakdownEntry(BaseModel):
    type: str
    count: int
    percent: float


class TypeBreakdownOut(BaseModel):
    total: int
    breakdown: list[TypeBreakdownEntry]


class UploaderEntry(BaseModel):
    rank: int
    name: str
    initials: str
    count: int


class TopUploadersOut(BaseModel):
    uploaders: list[UploaderEntry]


class SLABucket(BaseModel):
    count: int
    percent: float


class SLADistributionOut(BaseModel):
    under_1h: SLABucket
    one_to_4h: SLABucket = Field(..., alias="1_to_4h")
    four_to_24h: SLABucket = Field(..., alias="4_to_24h")
    over_24h: SLABucket

    model_config = {"populate_by_name": True}
