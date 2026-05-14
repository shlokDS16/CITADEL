# Module Spec — 04 · Anomaly Monitoring

> Frontend: `AnomalyMonitoring` in `pages.jsx`. Tabs: Alerts · Sensor Fleet · City Map · Work Orders · Analytics.
> Backend: `backend/app/modules/anomaly/`. Prefix: `/api/v1/anomaly`.
> Audience: gov officers (`gov_officer` field crew, `gov_analyst` city ops, `gov_admin` infrastructure director).

## Outcome
City IoT sensor fleet (~847 sensors covering bridge vibration, sewage flow, water tank pressure, traffic signal counters, AQI particulate, power meters, structural strain) streams telemetry to the platform. Per-sensor IsolationForest detects point anomalies and SARIMA flags temporal trend deviations. New anomalies surface as Alerts (CRITICAL/HIGH/MEDIUM/LOW) with confidence + ack flag. Officers ack the alert, drill into root cause, and create a Work Order assigned to a department crew with SLA. The City Map shows live alert pins per zone; Analytics shows MTTR, prevented downtime days, FP rate, top categories, critical asset uptime.

## Personas & permissions
- `gov_officer` (field crew): view own assigned work orders, update progress, mark resolved
- `gov_officer` (control room): view all alerts, ack, create work orders
- `gov_analyst`: read-only across alerts/sensors/analytics
- `gov_admin`: register sensors, set anomaly thresholds, manage SLAs

## Endpoints

### Alerts
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/alerts` | `anomaly:read` | List alerts, filter `?severity=&cat=&status=open,acked,resolved&zone=&from=` |
| `GET` | `/alerts/{alert_id}` | `anomaly:read` | Detail + linked sensor data + root-cause hints |
| `POST` | `/alerts/{alert_id}/ack` | `anomaly:write` | Ack alert (records actor + ts) |
| `POST` | `/alerts/{alert_id}/dismiss` | `anomaly:write` | Mark as false positive with required reason |
| `POST` | `/alerts/{alert_id}/root-cause` | `anomaly:write` | Submit root-cause analysis text + linked sensors |
| `GET` | `/alerts/{alert_id}/sensor-data` | `anomaly:read` | 24h sensor stream around the anomaly window |
| `GET` | `/alerts/stats` | `anomaly:read` | Counts: total open, by severity, unacked |

### Sensors
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/sensors` | `anomaly:read` | List sensors, filter `?type=&zone=&health=&battery_lt=` |
| `GET` | `/sensors/{sensor_id}` | `anomaly:read` | Detail + last 1h readings + computed baseline |
| `POST` | `/sensors` | `anomaly:admin` | Register new sensor |
| `PATCH` | `/sensors/{sensor_id}` | `anomaly:admin` | Update name/zone/thresholds |
| `DELETE` | `/sensors/{sensor_id}` | `anomaly:admin` | Decommission (soft delete) |
| `POST` | `/sensors/{sensor_id}/ingest` | `anomaly:ingest` | Push reading (called by gateway, mTLS) |
| `POST` | `/sensors/bulk-ingest` | `anomaly:ingest` | Batch readings (CSV/JSON, ≤1000 rows) |
| `GET` | `/sensors/{sensor_id}/timeseries` | `anomaly:read` | Range query `?from=&to=&agg=raw,5min,1h` |

### Map
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/map/pins` | `anomaly:read` | All current alert pins with status color |
| `GET` | `/map/zones` | `anomaly:read` | Per-zone summary (alerts count, sensors, status) |

### Work Orders
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/work-orders` | `anomaly:read` | List, filter `?status=&priority=&assignee=&sla=overdue` |
| `GET` | `/work-orders/{wo_id}` | `anomaly:read` | Detail + linked alert + history timeline |
| `POST` | `/work-orders` | `anomaly:write` | Create from alert; body links `alert_id`, sets task/assignee/SLA |
| `PATCH` | `/work-orders/{wo_id}` | `anomaly:write` | Update status, add progress note, change assignee |
| `POST` | `/work-orders/{wo_id}/resolve` | `anomaly:write` | Mark resolved with resolution note + linked sensor recheck |
| `POST` | `/work-orders/{wo_id}/escalate` | `anomaly:write` | Escalate to next priority/dept |

### Analytics
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/analytics/kpis` | `anomaly:read` | MTTR, prevented days, FP rate, critical asset count |
| `GET` | `/analytics/timeline` | `anomaly:read` | 24h anomaly count per hour |
| `GET` | `/analytics/severity-distribution` | `anomaly:read` | Counts by severity over window |
| `GET` | `/analytics/categories` | `anomaly:read` | Donut: structure / traffic / water / AQI / power |
| `GET` | `/analytics/critical-assets` | `anomaly:read` | List of P0/P1 assets with uptime % |

### Operations
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `POST` | `/operations/full-scan` | `anomaly:admin` | Trigger fleet-wide scan job → 202 + task id |
| `POST` | `/operations/auto-scan/toggle` | `anomaly:admin` | Enable/disable scheduled scans |

### Health
| Method | Path | Scope | Purpose |
|---|---|---|---|
| `GET` | `/health` | public | Liveness + ingestion lag + per-zone health summary |

### Real-time channels
| Channel | Purpose | Message types |
|---|---|---|
| `/ws/anomaly/alerts` | New alert push to control-room dashboards | `alert_created`, `alert_acked`, `alert_resolved`, `severity_change` |
| `/ws/anomaly/sensor-stream` | Live sensor reading stream (filtered) | `reading`, `health_change` |

## Schemas (key shapes)

### Alert
```python
class AlertOut(BaseModel):
    id: str                                    # "ANM-244431"
    title: str
    category: Literal["Bridge","Traffic","Drainage","Structure","Water","AQI","Electric"]
    location: str                              # human label
    geo: GeoPoint                              # {lat, lng}
    sensor_ids: list[str]                      # contributing sensors
    severity: Literal["CRITICAL","HIGH","MEDIUM","LOW"]
    confidence: float                          # 0..1
    detected_at: datetime
    acked: bool
    acked_at: datetime | None
    acked_by: UUID | None
    resolved_at: datetime | None
    work_order_id: str | None
    root_cause_text: str | None
    detection_method: Literal["isolation_forest","sarima_residual","threshold","manual"]
```

### Sensor
```python
class SensorOut(BaseModel):
    id: str                                    # "SNS-0147"
    type: Literal["bridge_vibration","water_pressure","aqi_particulate","aqi_no2",
                  "traffic_signal","sewage_level","power_meter","structure_vibration"]
    zone: str
    geo: GeoPoint
    battery_pct: int                           # 0..100, 0 = offline
    uptime_pct: float
    health: Literal["healthy","warning","offline"]
    last_seen: datetime
    last_value: float | None
    unit: str                                  # "mm/s", "kPa", "µg/m³", ...
    threshold_low: float | None
    threshold_high: float | None
```

### Sensor reading (ingest)
```python
class SensorReadingIn(BaseModel):
    sensor_id: str
    value: float
    ts: datetime                               # device-side timestamp
    battery_pct: int | None = None
    quality_flag: Literal["ok","suspect","invalid"] = "ok"
```

### Work Order
```python
class WorkOrderOut(BaseModel):
    id: str                                    # "WO-3821"
    alert_id: str
    task: str
    assignee_id: UUID
    assignee_label: str                        # "PWD Team A"
    department: Literal["PWD","Traffic","Sanitation","Electric","Water","Environment","Structural"]
    priority: Literal["CRITICAL","HIGH","MEDIUM","LOW"]
    status: Literal["assigned","in_progress","blocked","resolved","cancelled"]
    sla_due_at: datetime
    sla_label: str                             # "6h left", "OVERDUE"
    created_at: datetime
    started_at: datetime | None
    resolved_at: datetime | None
    resolution_note: str | None
```

### WebSocket alert message
```python
class AlertCreatedMessage(BaseModel):
    type: Literal["alert_created"]
    alert: AlertOut
    ts: datetime
```

## Data model
```sql
sensors (
  id VARCHAR(16) PK,                          -- "SNS-0147"
  type VARCHAR(32),
  zone VARCHAR(64),
  location GEOGRAPHY(POINT, 4326),
  unit VARCHAR(16),
  threshold_low FLOAT NULL,
  threshold_high FLOAT NULL,
  battery_pct INT DEFAULT 100,
  uptime_pct FLOAT DEFAULT 100,
  health VARCHAR(8) DEFAULT 'healthy',
  last_seen TIMESTAMPTZ NULL,
  last_value FLOAT NULL,
  active BOOLEAN DEFAULT TRUE,
  registered_at TIMESTAMPTZ DEFAULT NOW(),
  decommissioned_at TIMESTAMPTZ NULL
);
CREATE INDEX ix_sensors_zone ON sensors(zone);
CREATE INDEX ix_sensors_health ON sensors(health);
CREATE INDEX ix_sensors_type ON sensors(type);

sensor_readings (
  -- TimescaleDB hypertable on (ts, sensor_id), or partitioned monthly in vanilla PG
  ts TIMESTAMPTZ NOT NULL,
  sensor_id VARCHAR(16) NOT NULL,
  value FLOAT,
  battery_pct INT NULL,
  quality_flag VARCHAR(8) DEFAULT 'ok',
  PRIMARY KEY (sensor_id, ts)
);
SELECT create_hypertable('sensor_readings', 'ts');
CREATE INDEX ix_readings_sensor_ts ON sensor_readings(sensor_id, ts DESC);

alerts (
  id VARCHAR(16) PK,                          -- "ANM-244431"
  title VARCHAR(255),
  category VARCHAR(16),
  location_label VARCHAR(255),
  geo GEOGRAPHY(POINT, 4326),
  severity VARCHAR(8),
  confidence FLOAT,
  detected_at TIMESTAMPTZ NOT NULL,
  detection_method VARCHAR(24),
  raw_signal JSONB,                           -- IF/SARIMA scores, residuals
  acked BOOLEAN DEFAULT FALSE,
  acked_at TIMESTAMPTZ NULL,
  acked_by UUID NULL,
  resolved_at TIMESTAMPTZ NULL,
  resolved_by UUID NULL,
  work_order_id VARCHAR(16) NULL,
  root_cause_text TEXT NULL,
  dismissed BOOLEAN DEFAULT FALSE,
  dismissed_reason VARCHAR(64) NULL
);
CREATE INDEX ix_alerts_severity ON alerts(severity, acked);
CREATE INDEX ix_alerts_detected ON alerts(detected_at DESC);
CREATE INDEX ix_alerts_category ON alerts(category);

alert_sensors (
  alert_id VARCHAR(16) FK -> alerts.id ON DELETE CASCADE,
  sensor_id VARCHAR(16) FK -> sensors.id,
  contribution_score FLOAT,
  PRIMARY KEY (alert_id, sensor_id)
);

work_orders (
  id VARCHAR(16) PK,                          -- "WO-3821"
  alert_id VARCHAR(16) FK -> alerts.id,
  task TEXT,
  assignee_id UUID,
  assignee_label VARCHAR(128),
  department VARCHAR(32),
  priority VARCHAR(8),
  status VARCHAR(16) DEFAULT 'assigned',
  sla_due_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  started_at TIMESTAMPTZ NULL,
  resolved_at TIMESTAMPTZ NULL,
  resolution_note TEXT NULL
);
CREATE INDEX ix_wo_status ON work_orders(status);
CREATE INDEX ix_wo_assignee ON work_orders(assignee_id, status);
CREATE INDEX ix_wo_sla ON work_orders(sla_due_at) WHERE status NOT IN ('resolved','cancelled');

work_order_history (
  id UUID PK,
  work_order_id VARCHAR(16) FK -> work_orders.id ON DELETE CASCADE,
  actor_id UUID,
  field_changed VARCHAR(32),
  before JSONB,
  after JSONB,
  note TEXT,
  ts TIMESTAMPTZ DEFAULT NOW()
);

critical_assets (
  id UUID PK,
  name VARCHAR(255),
  asset_class VARCHAR(8),                     -- P0, P1, P2
  zone VARCHAR(64),
  linked_sensors JSONB,                       -- list of sensor ids
  uptime_pct FLOAT,
  registered_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Retention**: raw `sensor_readings` 1 year then downsampled to 1h aggregates (kept 7y); alerts 7 years (gov audit); work orders indefinite; raw IoT payloads 30 days.

## ML Pipeline
- **Per-sensor baseline**: rolling 14-day window mean+std stored as Redis cache; recomputed nightly.
- **Point anomaly**: `sklearn.ensemble.IsolationForest` per sensor (contamination=0.02, n_estimators=100, refit weekly with sliding 30-day window).
- **Temporal anomaly**: `statsmodels` SARIMA(p,d,q)(P,D,Q,s) per sensor type; flags residuals > 3σ.
- **Multi-sensor correlation**: when multiple co-located sensors flag in same 5-min window → upgrade severity (e.g., bridge vibration + structure strain together → CRITICAL).
- **Severity rules**: combination of confidence + asset class + linked-asset criticality (lookup `critical_assets`).
- **Root-cause hints**: simple rule engine over recent alerts in same zone + sensor type ("similar to ANM-XXXX 3 days ago").

**Latency budget**: <100ms per check (single sensor reading) per `ml-conventions.md`.
**Confidence threshold for auto-create work-order**: ≥0.95 + asset_class=P0 → auto-WO; else operator review.

## Background jobs
- `ingest_sensor_reading(reading)` — write + run point anomaly check (sync, <100ms).
- `run_sarima_check(sensor_id)` — every 5 min per sensor.
- `correlate_alerts()` — every minute, look for co-located co-occurring alerts → upgrade.
- `recompute_baselines()` — nightly, refits IsolationForest per sensor.
- `recompute_uptime()` — hourly, updates `critical_assets.uptime_pct`.
- `sla_breach_scan()` — every 5 min, mark overdue WOs + push alert.
- `purge_old_readings()` — daily, downsample raw → 1h aggregates past 1 year.
- `full_scan(scope)` — on-demand, fleet-wide retrigger (returns 202 task id).

## Real-time
- `/ws/anomaly/alerts` — control room subscription. Auth: JWT after connect. Filters: `?severity=` and `?zone=`.
- `/ws/anomaly/sensor-stream` — live readings filtered by `?sensor_id=` (whitelist; gov-only). Sampled at 1 reading/sec for UI.

## Frontend mock cross-reference
- Search `pages.jsx` for `AnomalyMonitoring` component (line 1115).
- Sub-components: `AnomalyAlerts`, `AnomalySensors`, `AnomalyMap`, `AnomalyWorkOrders`, `AnomalyAnalytics`.
- Inline mocks to extract: `MOCK_ALERTS` (in `AnomalyAlerts`), `MOCK_SENSORS` (in `AnomalySensors`), `MOCK_MAP_PINS` and `MOCK_ZONES` (in `AnomalyMap`), `MOCK_WORK_ORDERS` (in `AnomalyWorkOrders`), `MOCK_ANOMALY_TIMELINE`, `MOCK_SEVERITY_DIST`, `MOCK_CATEGORIES`, `MOCK_CRITICAL_ASSETS` (in `AnomalyAnalytics`).

## Non-functional
- p50 ingestion-to-stored: <50ms
- p95 ingestion-to-anomaly-decision: <100ms
- WebSocket alert push: <1s detection-to-UI
- Throughput: 5,000 readings/sec across fleet (sustained); 50,000/sec burst (incident scenarios)
- Storage growth: ~30 GB/month raw + 3 GB/month aggregates
- Availability: 99.9% (critical infrastructure SLA)
- SLA breach detection: ≤5 min after due time

## Open questions for user
- [ ] What is the IoT gateway protocol — MQTT, HTTP push, LoRaWAN, NB-IoT? Affects ingestion endpoint design and auth (mTLS vs HMAC vs token).
- [ ] Asset criticality (P0/P1/P2) — is there an existing asset register we should sync with, or do we author from scratch?
- [ ] Do we need to integrate with an existing CMMS (e.g., IBM Maximo, SAP PM) for work order sync, or is the in-app workflow standalone?
- [ ] What is the SLA matrix per (department, priority, asset_class)? E.g., is bridge-CRITICAL always 4h, or zone-dependent?
