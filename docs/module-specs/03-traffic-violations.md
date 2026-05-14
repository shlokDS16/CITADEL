# Module Spec — 03 · Traffic Violations

> Frontend: `TrafficViolations` in `pages.jsx`. Tabs: Live Feed · Incidents · Challans · Repeat Offenders · Analytics.
> Backend: `backend/app/modules/traffic/`. Prefix: `/api/v1/traffic`.
> Audience: gov officers (`gov_officer` traffic police, `gov_analyst` city ops, `gov_admin` traffic commissioner).

## Outcome
A bank of city CCTV cameras streams to the system; YOLOv8n detects vehicles, riders, helmets, lane positions, signal state; DeepSort tracks across frames; EasyOCR extracts the Indian-format number plate. The Live Feed tab shows up to 16 cameras with overlay boxes and a real-time alert ticker. Each detection is filed as an Incident; an officer reviews/approves/rejects, and approved incidents auto-generate a Challan with SMS notification to the registered owner (RTO lookup). Repeat Offenders aggregates by plate. Analytics shows hour×day heatmap, violation breakdown, hotspot zones, FP rate.

## Personas & permissions
- `gov_officer` (traffic): view live feed, review incidents, approve/reject, view challans
- `gov_officer` (challan_issuer): issue challans, mark paid/disputed, send SMS
- `gov_analyst`: read-only analytics + offender lookup
- `gov_admin`: manage cameras, change auto-issue thresholds, manage RTO API config

## Endpoints

### Live Feed & Cameras
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/cameras` | `traffic:read` | List cameras (id, name, location, status, fps, last_frame_at) |
| `GET` | `/cameras/{cam_id}` | `traffic:read` | Camera detail + recent detection counts |
| `POST` | `/cameras` | `traffic:admin` | Register a new camera (RTSP URL, location, zone) |
| `PATCH` | `/cameras/{cam_id}` | `traffic:admin` | Update name/location/zone/active flag |
| `POST` | `/cameras/{cam_id}/restart` | `traffic:admin` | Force re-connect upstream worker |
| `GET` | `/cameras/{cam_id}/snapshot` | `traffic:read` | Latest still frame (jpeg) for thumbnail |

### Incidents (Detections)
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/incidents` | `traffic:read` | List incidents, filter `?type=&severity=&status=&cam=&plate=&from=&to=` |
| `GET` | `/incidents/{inc_id}` | `traffic:read` | Detail + 3-second video clip URL + overlay metadata |
| `POST` | `/incidents/{inc_id}/approve` | `traffic:approve` | Approve → triggers challan generation |
| `POST` | `/incidents/{inc_id}/reject` | `traffic:approve` | Reject with reason (false_positive, plate_unreadable, lawful_exception, other) |
| `POST` | `/incidents/bulk-approve` | `traffic:approve` | Approve a list of incident ids |
| `POST` | `/incidents/upload` | `traffic:upload` | Manual upload of dashcam/CCTV video for offline detection |

### Challans
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/challans` | `traffic:read` | List, filter `?status=PAID,UNPAID,DISPUTED&plate=&from=&to=` |
| `GET` | `/challans/{ch_id}` | `traffic:read` | Detail + linked incident + RTO owner snapshot |
| `POST` | `/challans` | `traffic:issue-challan` | Manually issue (rare — most are auto from incidents) |
| `POST` | `/challans/{ch_id}/send-sms` | `traffic:issue-challan` | Re-send SMS notice to registered owner |
| `POST` | `/challans/{ch_id}/mark-paid` | `traffic:issue-challan` | Mark paid (manual reconciliation) |
| `POST` | `/challans/{ch_id}/dispute` | `traffic:issue-challan` | Open dispute case with reason |
| `GET` | `/challans/{ch_id}/pdf` | `traffic:read` | Pre-signed challan PDF download (5min TTL) |

### Repeat Offenders
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/offenders` | `traffic:read` | Top N by offense count, filter `?window=30d,90d,1y&min_offenses=` |
| `GET` | `/offenders/{plate}` | `traffic:read` | Plate-level history: all incidents, challans, total dues, risk score |
| `POST` | `/offenders/{plate}/notify` | `traffic:issue-challan` | Send escalation SMS / email to owner |

### Analytics
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/analytics/kpis` | `traffic:read` | Detections 24h, avg confidence, FP rate, cam uptime |
| `GET` | `/analytics/heatmap` | `traffic:read` | 7×24 violations matrix |
| `GET` | `/analytics/breakdown` | `traffic:read` | Donut: by violation type |
| `GET` | `/analytics/trend` | `traffic:read` | 7-day rolling counts |
| `GET` | `/analytics/hotspots` | `traffic:read` | Top zones with counts + intensity |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + per-camera worker health summary |

### Real-time channels
| Channel | Purpose | Message types |
|---|---|---|
| `/ws/traffic/live-feed` | Per-camera detection stream | `detection`, `frame_snapshot`, `cam_status`, `alert` |
| `/ws/traffic/alerts` | Global ticker of high-severity events | `incident_created`, `challan_issued` |

## Schemas (key shapes)

### Camera
```python
class CameraOut(BaseModel):
    id: str                                     # "CAM-04"
    name: str                                   # "Sector 12 · R4 Junction"
    rtsp_url: str | None                        # internal — never returned
    location: GeoPoint                          # {lat, lng}
    zone: str                                   # "Sector 12"
    status: Literal["live","detecting","offline","reconnecting"]
    fps: int
    last_frame_at: datetime | None
    active_detections: int                      # rolling 60s
```

### Incident
```python
class IncidentOut(BaseModel):
    id: str                                     # "INC-8847"
    camera_id: str
    violation_type: Literal["NO_HELMET","SPEEDING","WRONG_LANE","RED_LIGHT",
                            "NO_SEATBELT","ILLEGAL_PARK","WRONG_WAY","TRIPLE_RIDING"]
    plate: str                                  # "MH-01-AB-9087" — sensitive PII
    plate_confidence: float
    detection_confidence: float                 # YOLO conf
    severity: Literal["LOW","MEDIUM","HIGH","CRITICAL"]
    status: Literal["pending","approved","rejected","auto_issued"]
    detected_at: datetime
    video_clip_url: str | None                  # 3s clip, pre-signed
    snapshot_url: str | None                    # frame at peak conf, pre-signed
    bbox_at_peak: tuple[float, float, float, float]
    speed_kmh: float | None                     # only for SPEEDING
    rejection_reason: str | None
    challan_id: str | None
```

### Challan
```python
class ChallanOut(BaseModel):
    id: str                                     # "CH-7823"
    incident_id: str
    plate: str
    driver_name: str | None                     # from RTO lookup
    owner_aadhaar_masked: str | None            # "XXXX-XXXX-1234"
    violation_type: str
    amount_inr: int
    issued_at: datetime
    due_by: date
    status: Literal["UNPAID","PAID","DISPUTED","CANCELLED"]
    paid_at: datetime | None
    sms_sent_at: datetime | None
    sms_attempts: int
    pdf_url: str | None                         # pre-signed
```

### Offender (aggregate)
```python
class OffenderOut(BaseModel):
    rank: int
    plate: str
    driver_name: str | None
    offenses: int
    total_dues_inr: int
    last_violation_at: datetime
    risk_level: Literal["LOW","MEDIUM","HIGH"]
    by_type: dict[str, int]                     # {"NO_HELMET": 6, "SPEEDING": 4, ...}
```

### WebSocket detection message
```python
class DetectionMessage(BaseModel):
    type: Literal["detection"]
    camera_id: str
    bbox: tuple[float, float, float, float]     # normalized 0..1
    label: str                                  # "VEHICLE" | "NO_HELMET" | ...
    confidence: float
    track_id: int                               # DeepSort
    plate_text: str | None
    plate_confidence: float | None
    ts: datetime
```

## Data model
```sql
cameras (
  id VARCHAR(16) PK,                          -- "CAM-04"
  name VARCHAR(255),
  rtsp_url_encrypted TEXT,                    -- fernet
  location GEOGRAPHY(POINT, 4326),
  zone VARCHAR(64),
  status VARCHAR(16) DEFAULT 'offline',
  fps INT DEFAULT 30,
  last_frame_at TIMESTAMPTZ NULL,
  active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_cameras_status ON cameras(status);
CREATE INDEX ix_cameras_zone ON cameras(zone);

incidents (
  id VARCHAR(16) PK,                          -- "INC-8847"
  camera_id VARCHAR(16) FK -> cameras.id,
  violation_type VARCHAR(24),
  plate_encrypted TEXT,                       -- fernet (sensitive)
  plate_hash CHAR(64),                        -- HMAC for offender lookup
  plate_confidence FLOAT,
  detection_confidence FLOAT,
  severity VARCHAR(8),
  status VARCHAR(16) DEFAULT 'pending',
  detected_at TIMESTAMPTZ NOT NULL,
  video_clip_path TEXT,                       -- internal storage path
  snapshot_path TEXT,
  bbox JSONB,
  speed_kmh FLOAT NULL,
  reviewed_by UUID NULL,
  reviewed_at TIMESTAMPTZ NULL,
  rejection_reason VARCHAR(32) NULL,
  challan_id VARCHAR(16) NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX ix_incidents_status ON incidents(status);
CREATE INDEX ix_incidents_camera ON incidents(camera_id, detected_at DESC);
CREATE INDEX ix_incidents_plate_hash ON incidents(plate_hash);
CREATE INDEX ix_incidents_detected ON incidents(detected_at DESC);

challans (
  id VARCHAR(16) PK,                          -- "CH-7823"
  incident_id VARCHAR(16) FK -> incidents.id,
  plate_encrypted TEXT,
  plate_hash CHAR(64),
  driver_name VARCHAR(128) NULL,
  owner_aadhaar_encrypted TEXT NULL,
  violation_type VARCHAR(24),
  amount_inr INT,
  issued_at TIMESTAMPTZ DEFAULT NOW(),
  due_by DATE,
  status VARCHAR(16) DEFAULT 'UNPAID',
  paid_at TIMESTAMPTZ NULL,
  sms_sent_at TIMESTAMPTZ NULL,
  sms_attempts INT DEFAULT 0,
  pdf_path TEXT NULL,
  issued_by UUID NULL,                        -- null if auto-issued
  dispute_opened_at TIMESTAMPTZ NULL,
  dispute_reason TEXT NULL
);
CREATE INDEX ix_challans_status ON challans(status);
CREATE INDEX ix_challans_plate_hash ON challans(plate_hash);
CREATE INDEX ix_challans_due ON challans(due_by);

offender_aggregates (
  plate_hash CHAR(64) PK,
  plate_masked VARCHAR(20),                   -- "MH-01-XX-9087" for display
  offenses INT,
  total_dues_inr INT,
  last_violation_at TIMESTAMPTZ,
  risk_level VARCHAR(8),
  by_type JSONB,                              -- {"NO_HELMET": 6, ...}
  recomputed_at TIMESTAMPTZ
);
CREATE INDEX ix_offenders_offenses ON offender_aggregates(offenses DESC);
CREATE INDEX ix_offenders_risk ON offender_aggregates(risk_level);

rto_owner_cache (
  plate_hash CHAR(64) PK,
  driver_name_encrypted TEXT,
  owner_aadhaar_encrypted TEXT,
  registered_state VARCHAR(8),
  registered_address_encrypted TEXT,
  fetched_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ                      -- 30-day TTL
);
```

**Retention**: video clips 90 days (storage cost), incidents 7 years (gov audit), challans indefinite, RTO cache 30 days, raw frames not persisted.

## ML Pipeline
- **Vehicle/person detection**: `YOLOv8n` (Ultralytics, AGPL — confirm acceptable or use `YOLOv8n-cc` variant). Classes: `vehicle`, `motorcycle`, `person`, `helmet`, `seatbelt`.
- **Tracking**: `DeepSort` with appearance descriptor → stable `track_id` across frames; needed for "did the rider have a helmet at any point in this clip" logic.
- **Plate detection**: same YOLO with custom-trained plate class (~5k Indian plates), then crop.
- **Plate OCR**: `EasyOCR` with custom Indian-plate post-processor (regex `^[A-Z]{2}[-\s]?\d{1,2}[-\s]?[A-Z]{1,2}[-\s]?\d{4}$`); rejects readings outside this format unless confidence > 0.95.
- **Speed estimation**: pixel→meters via per-camera homography matrix (calibration step) × Δt across DeepSort track.
- **Red-light state**: detect signal head + classify color (small CNN, 3 classes), cross-reference with vehicle crossing stop-line.

**Latency budget**: <80ms per frame (single GPU). Worker per camera, batch frames per N=4 to amortize.
**Confidence threshold for auto-issue challan**: ≥0.92 detection + ≥0.95 plate OCR (per `ml-conventions.md`); else routes to officer review queue.

## Background jobs
- `process_camera_frame(cam_id, frame)` — runs continuously per camera in dedicated worker.
- `generate_challan(incident_id)` — RTO lookup → PDF render → SMS dispatch.
- `send_challan_sms(challan_id)` — SMS via gov SMS gateway (with retry, max 3).
- `recompute_offenders()` — hourly aggregate over `incidents` + `challans` by `plate_hash`.
- `purge_old_clips()` — daily, removes video clips > 90 days.
- `refresh_rto_cache()` — refetches stale rows < 30d expiry.

## Real-time
- `/ws/traffic/live-feed` — server pushes per-frame detection messages, batched at 5 fps to UI (downsample from 30 fps native). Auth: JWT first message after connect (per `api-conventions.md`). Filter by `?cam_id=` query.
- `/ws/traffic/alerts` — global ticker, push on `incident.severity ∈ {HIGH, CRITICAL}` or `challan_issued`.

## Frontend mock cross-reference
- Search `pages.jsx` for `TrafficViolations` component (line 819).
- Sub-components: `TrafficLive`, `TrafficIncidents`, `TrafficChallans`, `TrafficOffenders`, `TrafficAnalytics`.
- Inline mocks to extract: `MOCK_CAMERAS` (in `TrafficLive`), `MOCK_DETECTION_TYPES` (toggle chips), `MOCK_INCIDENTS` (in `TrafficIncidents`), `MOCK_CHALLANS` (in `TrafficChallans`), `MOCK_OFFENDERS` (in `TrafficOffenders`), `MOCK_HEATMAP`, `MOCK_BREAKDOWN`, `MOCK_HOTSPOTS` (in `TrafficAnalytics`).

## Non-functional
- p50 frame inference: <80ms
- p95 detection-to-incident-row: <2s end-to-end
- WebSocket: <500ms detection-to-UI
- Throughput: 24 concurrent camera streams @ 30 fps → downsampled to 5 fps for ML
- Camera uptime SLO: 99.5%
- False positive rate target: <5% (currently 4.2% in mock)
- Availability: 99.9% (public safety SLA)

## Open questions for user
- [ ] RTO API access — is this via VAHAN/Parivahan central API or per-state portal? Affects auth + rate limit + caching strategy.
- [ ] SMS gateway — should we integrate with the central gov SMS provider (e.g., NIC / mGov) or commercial (MSG91, Gupshup)?
- [ ] Which violations are auto-issuable vs always require officer approval? Indian Motor Vehicles Act has nuance (e.g., "no helmet" usually fine, but "wrong-way" sometimes needs sworn officer).
- [ ] Are we allowed to store raw video clips at all, or only the 3-second peak excerpt? Affects storage cost massively (24 cams × 30 fps × 24h vs 100 incidents/day × 3s).
