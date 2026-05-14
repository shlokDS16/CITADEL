"""
Pydantic response shapes for the Traffic Violations module.

These mirror exactly the keys that pages.jsx (TrafficLive / TrafficIncidents /
TrafficChallans / TrafficOffenders / TrafficAnalytics) consumes, so the frontend
renders unchanged.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------- Live Feed ----------
class Camera(BaseModel):
    id: str
    name: str
    gateway: str
    status: str                     # active | offline | degraded
    rtsp_url: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    fps: Optional[float] = None
    last_seen: Optional[str] = None


class CameraList(BaseModel):
    total: int
    cameras: list[Camera]


class HeaderStats(BaseModel):
    camera_count: int
    detections_today: int
    pipeline: str = "YOLOv8 + DEEPSORT + CRNN OCR"


# ---------- Incidents ----------
class IncidentRow(BaseModel):
    """Shape pages.jsx TrafficIncidents card expects."""
    id: str = Field(..., description="Human-readable INC-XXXX id")
    type: str
    plate: str
    cam: str
    time: str                       # HH:MM:SS
    conf: int                       # 0-100
    severity: str                   # CRITICAL | HIGH | MEDIUM | LOW
    status: str                     # pending | approved | rejected


class IncidentList(BaseModel):
    total: int
    incidents: list[IncidentRow]


# ---------- Challans ----------
class ChallanRow(BaseModel):
    """Shape pages.jsx TrafficChallans DataTable expects."""
    id: str
    plate: str
    driver: str
    type: str
    amt: int
    issued: str                     # YYYY-MM-DD
    due: str
    status: str                     # PAID | UNPAID | DISPUTED


class ChallanList(BaseModel):
    total: int
    challans: list[ChallanRow]


class ChallanKPIs(BaseModel):
    issued_30d: int
    total_collected: int
    collection_rate: float
    disputed_pct: float


# ---------- Offenders ----------
class OffenderRow(BaseModel):
    rank: int
    plate: str
    driver: str
    offenses: int
    total: int
    last: str
    risk: str                       # HIGH | MEDIUM | LOW


class OffenderList(BaseModel):
    total: int
    offenders: list[OffenderRow]


# ---------- Analytics ----------
class AnalyticsSummary(BaseModel):
    detections_24h: int
    avg_confidence: float
    false_positive_pct: float
    cam_uptime_pct: float


# ---------- Fines (lookup table) ----------
class FineRow(BaseModel):
    violation_type: str
    fine_amount: int
    description: Optional[str] = None
    legal_section: Optional[str] = None


# ---------- Phase 1+: Camera Health Strip ----------
class LastDetection(BaseModel):
    detected_at: Optional[str] = None
    plate: Optional[str] = None
    cam_id: Optional[str] = None
    violation_type: Optional[str] = None


class CameraHealth(BaseModel):
    total: int
    online: int
    offline: int
    degraded: int
    online_pct: float
    avg_fps: float
    last_detection: Optional[LastDetection] = None


# ---------- Phase 1+: System Status Bar ----------
class StatusItem(BaseModel):
    ok: bool


class GroqStatus(BaseModel):
    ok: bool
    model: Optional[str] = None


class TelegramStatus(BaseModel):
    ok: bool


class SystemStatus(BaseModel):
    supabase: StatusItem
    groq: GroqStatus
    ocr: StatusItem
    telegram: TelegramStatus
    env: str


# ---------- Phase 2+: Live snapshot map (Singapore data.gov.sg) ----------
class LoopAssignment(BaseModel):
    loop_id: str
    video_url: str
    tracks_url: str
    start_offset: float
    duration: float


class SnapshotEntry(BaseModel):
    image_url: Optional[str] = None
    captured_at: Optional[str] = None
    source: Optional[str] = None
    source_cam_id: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    loop: Optional[LoopAssignment] = None


class SnapshotMap(BaseModel):
    source: str
    total: int
    snapshots: dict[str, SnapshotEntry]
    cached_for_seconds: int


# ---------- Phase 3+: YOLO detections on the snapshots ----------
class DetectionBox(BaseModel):
    cls: str            # 'car' | 'motorcycle' | 'bus' | 'truck' | 'person' | 'bicycle'
    conf: float
    x: float            # normalized 0..1 (x of bbox top-left)
    y: float
    w: float            # normalized 0..1 (width)
    h: float
    track_id: Optional[int] = None     # OTVision-equivalent stable track id across snapshots
    lifetime: Optional[int] = None     # consecutive snapshots this track has been seen


class DetectionSummary(BaseModel):
    cars: int = 0
    motorcycles: int = 0
    buses: int = 0
    trucks: int = 0
    persons: int = 0
    bicycles: int = 0
    total: int = 0


class DetectionMap(BaseModel):
    computed_at: str
    cached_for_seconds: int
    summary: DetectionSummary
    detections: dict[str, list[DetectionBox]]


# ---------- Phase 1+: Plate history ----------
class PlateHistory(BaseModel):
    plate: str
    found: bool
    driver_name: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    incidents: list[IncidentRow] = []
    challans: list[ChallanRow] = []
    total_incidents: int = 0
    total_challans: int = 0
    total_pending: int = 0
    risk: Optional[str] = None


# ---------- Phase 1+: Bulk action request/response ----------
class BulkActionRequest(BaseModel):
    ids: list[str]
    action: str                     # 'approve' | 'reject'
    reason: Optional[str] = None
    actor: Optional[str] = "rsd"


class BulkActionResponse(BaseModel):
    action: str
    updated: int
    ids: list[str]
    challan_ids: list[str] = []
    telegram_failures: list[dict] = []


# ---------- Phase 3: Single-incident approve / reject ----------
class ApproveResult(BaseModel):
    incident: Optional[IncidentRow] = None
    challan: Optional[ChallanRow] = None
    telegram_message_id: Optional[str] = None
    telegram_error: Optional[str] = None
    status: str                          # approved | already_approved | rejected | already_rejected


class RejectRequest(BaseModel):
    reason: Optional[str] = None
    actor: Optional[str] = "rsd"


class ApproveRequest(BaseModel):
    actor: Optional[str] = "rsd"


# ---------- Phase 1+: SLA queue (challans approaching due_by) ----------
class SLAChallanRow(ChallanRow):
    due_by_iso: Optional[str] = None
    days_overdue: Optional[int] = None
    days_until_due: Optional[int] = None


class SLAReport(BaseModel):
    window_days: int
    overdue_count: int
    approaching_count: int
    total_at_risk: int
    overdue: list[SLAChallanRow] = []
    approaching: list[SLAChallanRow] = []


# ---------- Phase 1+: Revenue forecast ----------
class RevenueForecast(BaseModel):
    days: int
    last_30d_issued_amount: int
    last_30d_paid_amount: int
    collection_rate: float
    pending_amount: int
    projected_new_amount: int
    projected_collection_new: int
    projected_collection_pending: int
    projected_total_collection: int


# ---------- Phase 1+: Court evidence pack manifest ----------
class AuditEntry(BaseModel):
    ts: Optional[str] = None
    action: Optional[str] = None
    actor: Optional[str] = None
    payload: Optional[dict] = None


class CourtPackManifest(BaseModel):
    found: bool
    inc_id: str
    issued_at: Optional[str] = None
    incident: Optional[IncidentRow] = None
    evidence: Optional[dict] = None
    challans: list[ChallanRow] = []
    audit_trail: list[AuditEntry] = []
    trail_length: int = 0
    ready_for_export: bool = False


# ---------- Phase 2: Upload pipeline ----------
class UploadJobAck(BaseModel):
    job_id: str
    status: str
    filename: Optional[str] = None
    size_bytes: int = 0


class UploadJobStatus(BaseModel):
    job_id: str
    filename: Optional[str] = None
    size_bytes: int = 0
    cam_id: Optional[str] = None
    types_filter: list[str] = []
    status: str                          # queued | processing | complete | error
    frames_processed: int = 0
    total_frames: int = 0
    detection_count: int = 0
    incident_ids: list[str] = []
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


# ---------- Phase 5: Repeat Offenders ----------
class OffenderTimelineEvent(BaseModel):
    kind: str                            # 'incident' | 'challan' | 'audit'
    at: str                              # ISO timestamp
    label: str                           # human-readable summary
    badge: Optional[str] = None          # severity / status pill text
    badge_color: Optional[str] = None    # green | red | gold | cyan
    detail: Optional[str] = None         # secondary line (amount, actor, etc.)
    ref_id: Optional[str] = None         # inc_id or challan_id


class OffenderTimeline(BaseModel):
    plate: str
    driver: Optional[str] = None
    chat_id: Optional[str] = None
    incident_count: int
    challan_count: int
    total_outstanding: int
    total_paid: int
    events: list[OffenderTimelineEvent]


class NotifyRequest(BaseModel):
    actor: Optional[str] = "rsd"


class NotifyResult(BaseModel):
    plate: str
    notified: bool
    telegram_message_id: Optional[str] = None
    error: Optional[str] = None
    offense_count: int = 0
    total_outstanding: int = 0
