"""
Anomaly Detection Service (Sensors)
- Real-time anomaly detection from sensor readings
- Sensor correlation across zones
- Automatic alert/ticket generation
"""
from typing import Dict, List, Optional, Any, Tuple
from uuid import UUID, uuid4
from datetime import datetime, timedelta
from collections import defaultdict

from supabase import create_client

from config import SUPABASE_URL, SUPABASE_KEY
from services.audit_service import log_ai_decision
from services.ticket_service import create_ticket

# Initialize Supabase
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Sensor thresholds
SENSOR_THRESHOLDS = {
    "aqi": {"warning": 100, "critical": 200, "unit": "AQI"},
    "fire": {"warning": 65, "critical": 85, "unit": "°C"},
    "smoke": {"warning": 50, "critical": 100, "unit": "ppm"},
    "noise": {"warning": 70, "critical": 90, "unit": "dB"},
    "traffic": {"warning": 0.7, "critical": 0.9, "unit": "congestion"}
}


async def ingest_sensor_reading(
    sensor_id: str,
    sensor_type: str,
    value: float,
    location: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    Ingest sensor reading and detect anomalies.
    """
    reading_id = uuid4()
    
    # Check threshold breach
    threshold_breach, breach_level = check_threshold(sensor_type, value)
    
    # Detect statistical anomaly
    anomaly_score, is_anomaly = await detect_anomaly(sensor_id, sensor_type, value)
    
    # Get unit
    unit = SENSOR_THRESHOLDS.get(sensor_type, {}).get("unit", "units")
    
    # Create reading record
    reading_record = {
        "id": str(reading_id),
        "sensor_id": sensor_id,
        "sensor_type": sensor_type,
        "location": location,
        "value": value,
        "unit": unit,
        "threshold_breach": threshold_breach,
        "anomaly_score": anomaly_score,
        "anomaly_detected": is_anomaly,
        "created_at": datetime.utcnow().isoformat()
    }
    
    supabase.table("sensor_readings").insert(reading_record).execute()
    
    # If anomaly or critical breach, raise alert
    if is_anomaly or breach_level == "critical":
        await raise_alert(reading_record, breach_level)
    
    return reading_record


def check_threshold(sensor_type: str, value: float) -> Tuple[bool, Optional[str]]:
    """Check if value breaches defined thresholds"""
    thresholds = SENSOR_THRESHOLDS.get(sensor_type, {})
    
    if not thresholds:
        return False, None
    
    if value >= thresholds.get("critical", float("inf")):
        return True, "critical"
    elif value >= thresholds.get("warning", float("inf")):
        return True, "warning"
    
    return False, None


from sklearn.ensemble import IsolationForest
import numpy as np

# Global detector cache
_detectors = {}

class IsolationForestDetector:
    def __init__(self, sensor_id: str):
        self.sensor_id = sensor_id
        self.model = IsolationForest(contamination=0.05, random_state=42)
        self.history = []
        self.is_fitted = False
        
    def train(self, values: List[float]):
        if len(values) < 10: return
        data = np.array(values).reshape(-1, 1)
        self.model.fit(data)
        self.is_fitted = True
        
    def score(self, value: float) -> Tuple[float, bool]:
        if not self.is_fitted:
            # Fallback to simple outlier logic if not fitted
            if self.history:
                mean = sum(self.history)/len(self.history)
                return (1.0 if abs(value - mean) > mean*0.5 else 0.0), abs(value - mean) > mean*0.5
            return 0.0, False
            
        pred = self.model.predict([[value]])[0] # -1 for anomaly
        decision = self.model.decision_function([[value]])[0]
        # Normalize decision to 0-1
        # decision is usually negative for anomalies
        anomaly_score = 0.5 - (decision / 2.0)
        anomaly_score = max(0.0, min(1.0, anomaly_score))
        return anomaly_score, pred == -1

def get_detector(sensor_id: str) -> IsolationForestDetector:
    if sensor_id not in _detectors:
        _detectors[sensor_id] = IsolationForestDetector(sensor_id)
    return _detectors[sensor_id]

async def detect_anomaly(
    sensor_id: str,
    sensor_type: str,
    value: float
) -> Tuple[float, bool]:
    """
    Detect anomaly using online Isolation Forest + history buffer.
    """
    detector = get_detector(sensor_id)
    
    # Add to history
    detector.history.append(value)
    if len(detector.history) > 200:
        detector.history.pop(0)
        
    # Auto-train periodically
    if len(detector.history) >= 20 and (not detector.is_fitted or len(detector.history) % 50 == 0):
        detector.train(detector.history)
    
    # Predict
    anomaly_score, is_anomaly = detector.score(value)
    
    # Check simple thresholds as safety net
    threshold_breach, level = check_threshold(sensor_type, value)
    if threshold_breach and level == "critical":
        is_anomaly = True
        anomaly_score = max(anomaly_score, 0.9)
        
    return anomaly_score, is_anomaly


async def correlate_sensors(zone_id: str) -> Dict[str, Any]:
    """
    Correlate sensor readings within a zone to detect multi-sensor anomalies.
    """
    # Get recent readings for zone
    one_hour_ago = (datetime.utcnow() - timedelta(hours=1)).isoformat()
    
    readings = supabase.table("sensor_readings").select("*").contains(
        "location", {"zone": zone_id}
    ).gte("created_at", one_hour_ago).execute()
    
    if not readings.data:
        return {
            "zone_id": zone_id,
            "status": "no_data",
            "correlated_anomalies": []
        }
    
    # Group by sensor type
    by_type = defaultdict(list)
    anomalies_by_type = defaultdict(list)
    
    for reading in readings.data:
        sensor_type = reading.get("sensor_type")
        by_type[sensor_type].append(reading)
        if reading.get("anomaly_detected"):
            anomalies_by_type[sensor_type].append(reading)
    
    # Check for correlated anomalies (multiple types showing anomalies)
    correlated = []
    if len(anomalies_by_type) >= 2:
        # Multiple sensor types showing anomalies - likely real event
        correlated = [
            {
                "sensor_type": stype,
                "count": len(readings),
                "latest_value": readings[-1]["value"] if readings else None
            }
            for stype, readings in anomalies_by_type.items()
        ]
    
    return {
        "zone_id": zone_id,
        "status": "correlated_anomaly" if correlated else "normal",
        "sensor_types_active": list(by_type.keys()),
        "correlated_anomalies": correlated
    }


async def raise_alert(reading: Dict, breach_level: str) -> Dict:
    """Create alert ticket for anomalous reading"""
    sensor_type = reading.get("sensor_type", "unknown")
    sensor_id = reading.get("sensor_id", "unknown")
    value = reading.get("value", 0)
    unit = reading.get("unit", "units")
    
    # Log AI decision
    decision_id = await log_ai_decision(
        model_name="anomaly-forest-v1",
        model_version="1.0.0",
        module="anomaly",
        input_data={"sensor_id": sensor_id, "value": value, "sensor_type": sensor_type},
        output={"anomaly_score": reading.get("anomaly_score"), "breach_level": breach_level},
        confidence=0.85,
        explanation=f"Detected {breach_level} anomaly: {value} {unit}"
    )
    
    # Determine priority based on breach level
    priority = "critical" if breach_level == "critical" else "high"
    
    # Create ticket
    ticket = await create_ticket(
        title=f"Sensor Alert: {sensor_type.upper()} anomaly detected",
        description=f"""
Automated alert from sensor monitoring system.

Sensor ID: {sensor_id}
Type: {sensor_type}
Reading: {value} {unit}
Anomaly Score: {reading.get('anomaly_score', 0):.2f}
Breach Level: {breach_level}
Location: {reading.get('location', 'Unknown')}
Time: {reading.get('created_at')}

Please investigate and take appropriate action.
        """,
        submitter_id=UUID('00000000-0000-0000-0000-000000000000'),  # System user
        source="anomaly_system",
        source_ref_id=UUID(reading.get("id"))
    )
    
    return {
        "alert_created": True,
        "ticket_id": ticket.get("id"),
        "decision_id": str(decision_id)
    }


async def get_sensor_baseline(sensor_id: str, hours: int = 24) -> Dict[str, Any]:
    """Get historical baseline for a sensor"""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    
    readings = supabase.table("sensor_readings").select("value, created_at").eq(
        "sensor_id", sensor_id
    ).gte("created_at", cutoff).order("created_at", desc=False).execute()
    
    if not readings.data:
        return {"sensor_id": sensor_id, "status": "no_data"}
    
    values = [r["value"] for r in readings.data]
    
    return {
        "sensor_id": sensor_id,
        "period_hours": hours,
        "reading_count": len(values),
        "mean": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "latest": values[-1] if values else None
    }


async def list_recent_anomalies(
    sensor_type: Optional[str] = None,
    hours: int = 24,
    limit: int = 50
) -> List[Dict]:
    """List recent anomalous readings"""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    
    query = supabase.table("sensor_readings").select("*").eq(
        "anomaly_detected", True
    ).gte("created_at", cutoff)
    
    if sensor_type:
        query = query.eq("sensor_type", sensor_type)
    
    results = query.order("created_at", desc=True).limit(limit).execute()
    return results.data if results.data else []
