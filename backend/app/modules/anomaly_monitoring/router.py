"""
Anomaly Monitoring — HTTP endpoints. URL prefix: /api (mounted in main.py)

  GET  /api/v1/anomaly/health
  GET  /api/anomaly/alerts              ?severity=&category=&status=
  GET  /api/anomaly/alerts/{id}
  POST /api/anomaly/alerts/{id}/ack
  POST /api/anomaly/alerts/{id}/work-order
  POST /api/anomaly/alerts/{id}/notify
  GET  /api/anomaly/sensors
  GET  /api/anomaly/map
  GET  /api/anomaly/work-orders
  GET  /api/anomaly/analytics           ?window_hours=
  POST /api/anomaly/refresh
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.modules.anomaly_monitoring import schemas, service

log = logging.getLogger("citadel.anomaly_monitoring.router")
router = APIRouter()


@router.get("/v1/anomaly/health", tags=["anomaly-monitoring"])
async def health() -> dict:
    return {"status": "ok", "module": "anomaly_monitoring"}


@router.get("/anomaly/alerts", response_model=schemas.AlertList, tags=["anomaly-monitoring"])
async def list_alerts(
    severity: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
):
    try:
        return service.list_alerts(severity=severity, category=category, status=status)
    except Exception as e:
        log.exception("list_alerts failed")
        raise HTTPException(status_code=500, detail=f"Alerts failed: {e}")


@router.get("/anomaly/alerts/{alert_id}", response_model=schemas.AlertRow, tags=["anomaly-monitoring"])
async def get_alert(alert_id: str):
    a = service.get_alert(alert_id)
    if not a:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return a


@router.post("/anomaly/alerts/{alert_id}/ack", tags=["anomaly-monitoring"])
async def ack_alert(alert_id: str, body: Optional[schemas.ActionRequest] = None):
    try:
        return service.ack_alert(alert_id, actor=(body.actor if body else "rsd") or "rsd")
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        log.exception("ack failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomaly/alerts/{alert_id}/work-order", response_model=schemas.WorkOrder, tags=["anomaly-monitoring"])
async def create_work_order(alert_id: str, body: Optional[schemas.ActionRequest] = None):
    try:
        return service.create_work_order(alert_id, actor=(body.actor if body else "rsd") or "rsd")
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        log.exception("work-order failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomaly/alerts/{alert_id}/notify", response_model=schemas.NotifyResult, tags=["anomaly-monitoring"])
async def notify_alert(alert_id: str, body: Optional[schemas.ActionRequest] = None):
    try:
        return service.notify_alert(alert_id, actor=(body.actor if body else "rsd") or "rsd")
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        log.exception("notify failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomaly/sensors", response_model=schemas.SensorList, tags=["anomaly-monitoring"])
async def list_sensors():
    try:
        return service.list_sensors()
    except Exception as e:
        log.exception("sensors failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomaly/map", response_model=schemas.MapData, tags=["anomaly-monitoring"])
async def map_data():
    try:
        return service.map_data()
    except Exception as e:
        log.exception("map failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomaly/work-orders", response_model=schemas.WorkOrderList, tags=["anomaly-monitoring"])
async def list_work_orders():
    try:
        return service.list_work_orders()
    except Exception as e:
        log.exception("work-orders failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/anomaly/analytics", response_model=schemas.AnalyticsSummary, tags=["anomaly-monitoring"])
async def analytics(window_hours: int = Query(24, ge=1, le=168)):
    try:
        return service.analytics_summary(window_hours=window_hours)
    except Exception as e:
        log.exception("analytics failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/anomaly/refresh", tags=["anomaly-monitoring"])
async def refresh():
    try:
        return service.force_refresh()
    except Exception as e:
        log.exception("refresh failed")
        raise HTTPException(status_code=500, detail=str(e))
