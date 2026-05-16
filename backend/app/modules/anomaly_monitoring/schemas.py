"""Pydantic response models for Anomaly Monitoring."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class ImpactBrief(BaseModel):
    impact_radius_km: float
    impact_area_km2: float
    population_at_risk_est: int
    density_assumption: int
    owning_department: str
    affected_systems: list[str]
    immediate_actions: list[str]
    recommended_solutions: list[str]
    affected_zones: list[str] = []


class AlertRow(BaseModel):
    id: str
    title: str
    category: str
    severity: str                      # CRITICAL | HIGH | MEDIUM | LOW
    confidence: int
    metric: str
    value: float
    unit: str
    threshold: float
    city: str
    zone: str
    station_id: str
    lat: float
    lng: float
    detected_at: str
    why: str
    acked: bool = False
    status: str = "open"               # open | acked | work_order | resolved
    source: str                        # open-meteo | usgs
    impact: Optional[ImpactBrief] = None


class AlertList(BaseModel):
    total: int
    counts: dict[str, int]
    generated_at: str
    alerts: list[AlertRow]


class SensorRow(BaseModel):
    id: str
    city: str
    zone: str
    type: str
    lat: float
    lng: float
    metric: str
    value: Optional[float] = None
    unit: str
    health: str                        # healthy | warning | offline
    last_seen: str


class SensorList(BaseModel):
    total: int
    online: int
    warning: int
    offline: int
    sensors: list[SensorRow]


class MapZone(BaseModel):
    station_id: str
    city: str
    zone: str
    lat: float
    lng: float
    level: str                         # critical | high | medium | nominal
    worst_metric: Optional[str] = None
    worst_value: Optional[float] = None
    alert_count: int
    summary: str


class MapData(BaseModel):
    generated_at: str
    center: dict[str, float]
    zones: list[MapZone]


class WorkOrder(BaseModel):
    id: str
    alert_id: str
    title: str
    category: str
    severity: str
    city: str
    department: str
    status: str                        # open | in_progress | resolved
    created_at: str
    sla_due: str


class WorkOrderList(BaseModel):
    total: int
    orders: list[WorkOrder]


class AnalyticsSummary(BaseModel):
    generated_at: str
    window_hours: int
    kpis: dict[str, Any]
    by_category: list[dict[str, Any]]
    by_severity: list[dict[str, Any]]
    by_city: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    top_zones: list[dict[str, Any]]


class ActionRequest(BaseModel):
    actor: Optional[str] = "rsd"
    note: Optional[str] = None


class NotifyResult(BaseModel):
    alert_id: str
    notified: bool
    telegram_message_id: Optional[str] = None
    error: Optional[str] = None
