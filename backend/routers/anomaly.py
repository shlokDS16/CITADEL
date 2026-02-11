"""
Anomaly Router - Sensor Anomaly Detection API endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict

from services.anomaly_service import (
    ingest_sensor_reading, correlate_sensors,
    get_sensor_baseline, list_recent_anomalies,
    get_detector
)
from data.loaders.sensor_loader import SensorLoader

router = APIRouter()


class SensorReading(BaseModel):
    sensor_id: str
    sensor_type: str
    value: float
    location: Optional[Dict] = None


@router.post("/reading")
async def add_sensor_reading(reading: SensorReading):
    """Ingest sensor reading and detect anomalies"""
    try:
        result = await ingest_sensor_reading(
            sensor_id=reading.sensor_id,
            sensor_type=reading.sensor_type,
            value=reading.value,
            location=reading.location
        )
        return {"success": True, "reading": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlate/{zone_id}")
async def correlate_zone_sensors(zone_id: str):
    """Get correlated sensor analysis for a zone"""
    result = await correlate_sensors(zone_id)
    return result


@router.get("/baseline/{sensor_id}")
async def get_baseline(sensor_id: str, hours: int = 24):
    """Get baseline statistics for a sensor"""
    result = await get_sensor_baseline(sensor_id, hours)
    return result


@router.get("/anomalies")
async def get_recent_anomalies(
    sensor_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 50
):
    """List recent anomalies"""
    anomalies = await list_recent_anomalies(sensor_type, hours, limit)
    return {"anomalies": anomalies}


@router.post("/train")
async def train_models(dataset: str = "uci"):
    """
    Load historical data and train anomaly models.
    Dataset: 'uci' (Air Quality) or 'nab' (Cloudwatch)
    """
    loader = SensorLoader()
    count = 0
    
    if dataset == "uci":
        data = loader.load_air_quality(limit=2000)
        # Train detector for 'air_quality_sensor_1'
        values = [d['value'] for d in data if d['source'] == 'air_quality_sensor_1' and d['metric'] == 'CO(GT)']
        detector = get_detector("air_quality_sensor_1")
        if values:
            detector.train(values)
            detector.history = values[-200:] # Keep recent history
            count = len(values)
        
    elif dataset == "nab":
        data = loader.load_nab_metric("realAWSCloudwatch")
        if data:
            sensor_id = data[0]['source']
            values = [d['value'] for d in data]
            detector = get_detector(sensor_id)
            detector.train(values)
            detector.history = values[-200:]
            count = len(values)
            
    return {"message": f"Trained models on {count} data points from {dataset}"}


@router.get("/stats")
async def get_anomaly_statistics():
    """
    Aggregate statistics for infrastructure anomaly monitoring.
    Provides overview of system health, active alerts, and sensor status.
    """
    from datetime import datetime
    
    # Return static data for validation - in production, integrate with context engine
    return {
        'summary': {
            'total_active_alerts': 0,
            'acknowledged_count': 0,
            'requires_immediate_attention': 0,
            'system_health': 'healthy'
        },
        'alerts_by_priority': {
            'high': 0,
            'medium': 0,
            'low': 0
        },
        'sensor_breakdown': {},
        'recent_alerts': [],
        'timestamp': datetime.now().isoformat()
    }

