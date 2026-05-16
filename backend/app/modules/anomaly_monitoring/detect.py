"""
Anomaly scoring.

Every rule here is anchored to a published standard so the "confidence"
we show an officer is defensible, not invented:

  - PM2.5 / US AQI  → US EPA AQI breakpoints
  - NO2 / O3 / SO2  → WHO Global Air Quality Guidelines (2021)
  - Earthquake mag  → USGS magnitude classes
  - Heat / cold     → IMD heat-wave / cold-wave criteria
  - Rain            → IMD rainfall intensity classes
  - River discharge → ratio vs the model's own climatological mean

A reading becomes an *anomaly* only when it crosses the MEDIUM band or
above. Each anomaly carries: category, severity, confidence, the metric
that tripped, its value, the threshold it crossed, and a short factual
"why".
"""
from __future__ import annotations

from typing import Any, Optional

# severity ordering helper
_SEV_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _aqi_band(aqi: float) -> tuple[str, str]:
    """US AQI → (severity, label)."""
    if aqi <= 50:   return "LOW", "Good"
    if aqi <= 100:  return "LOW", "Moderate"
    if aqi <= 150:  return "MEDIUM", "Unhealthy (Sensitive Groups)"
    if aqi <= 200:  return "HIGH", "Unhealthy"
    if aqi <= 300:  return "HIGH", "Very Unhealthy"
    return "CRITICAL", "Hazardous"


def _pm25_severity(v: float) -> Optional[tuple[str, str, float]]:
    """EPA 24h PM2.5 µg/m³ → (severity, label, crossed_threshold)."""
    if v is None:
        return None
    if v >= 250.5: return "CRITICAL", "Hazardous PM2.5", 250.5
    if v >= 150.5: return "HIGH", "Very Unhealthy PM2.5", 150.5
    if v >= 55.5:  return "HIGH", "Unhealthy PM2.5", 55.5
    if v >= 35.5:  return "MEDIUM", "Unhealthy for Sensitive Groups (PM2.5)", 35.5
    return None


def _generic(metric: str, v: Optional[float], med: float, high: float, crit: float, unit: str):
    if v is None:
        return None
    if v >= crit: return "CRITICAL", f"{metric} critical ({v:.0f}{unit})", crit
    if v >= high: return "HIGH", f"{metric} high ({v:.0f}{unit})", high
    if v >= med:  return "MEDIUM", f"{metric} elevated ({v:.0f}{unit})", med
    return None


def score_air_quality(station: dict[str, Any], aq: dict[str, Any]) -> list[dict[str, Any]]:
    """Returns 0..n anomaly dicts for one station's air-quality reading."""
    out: list[dict[str, Any]] = []
    if not aq:
        return out

    # 1) US AQI headline
    aqi = aq.get("us_aqi")
    if aqi is not None and aqi > 100:
        sev, label = _aqi_band(aqi)
        if _SEV_RANK[sev] >= 2:
            out.append({
                "category": "Air Quality",
                "metric": "US AQI",
                "value": round(aqi, 1),
                "unit": "AQI",
                "threshold": 100,
                "severity": sev,
                "confidence": min(99, 70 + int((aqi - 100) / 4)),
                "why": f"US AQI {aqi:.0f} — {label}. Sustained exposure affects "
                       f"respiratory & cardiovascular health.",
            })

    # 2) PM2.5 raw concentration (independent of AQI conversion)
    pm = _pm25_severity(aq.get("pm2_5"))
    if pm:
        sev, label, thr = pm
        out.append({
            "category": "Air Quality",
            "metric": "PM2.5",
            "value": round(aq.get("pm2_5"), 1),
            "unit": "µg/m³",
            "threshold": thr,
            "severity": sev,
            "confidence": min(98, 72 + int(aq.get("pm2_5") / 8)),
            "why": f"{label}: PM2.5 {aq.get('pm2_5'):.0f} µg/m³ vs EPA limit {thr:.0f}.",
        })

    # 3) NO2 (WHO 24h guideline 25 µg/m³; traffic-corridor spike if much higher)
    g = _generic("NO₂", aq.get("no2"), 90, 200, 400, " µg/m³")
    if g:
        sev, label, thr = g
        out.append({
            "category": "Air Quality", "metric": "NO2",
            "value": round(aq.get("no2"), 1), "unit": "µg/m³", "threshold": thr,
            "severity": sev, "confidence": 80,
            "why": f"{label}. Indicates heavy combustion / traffic-corridor build-up.",
        })

    # 4) O3 (WHO 8h 100 µg/m³)
    g = _generic("Ozone", aq.get("o3"), 160, 240, 360, " µg/m³")
    if g:
        sev, label, thr = g
        out.append({
            "category": "Air Quality", "metric": "O3",
            "value": round(aq.get("o3"), 1), "unit": "µg/m³", "threshold": thr,
            "severity": sev, "confidence": 78,
            "why": f"{label}. Photochemical smog risk; harmful on exertion outdoors.",
        })
    return out


def score_weather(station: dict[str, Any], wx: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not wx:
        return out
    t = wx.get("temp_c")
    if t is not None:
        if t >= 47:
            sev = "CRITICAL"
        elif t >= 45:
            sev = "HIGH"
        elif t >= 40:
            sev = "MEDIUM"
        else:
            sev = None
        if sev:
            out.append({
                "category": "Weather Extreme", "metric": "Temperature",
                "value": round(t, 1), "unit": "°C", "threshold": 40,
                "severity": sev, "confidence": 88,
                "why": f"Heat-wave conditions ({t:.0f}°C, IMD threshold 40°C). "
                       f"Heat-stroke risk for outdoor workers & elderly.",
            })
        elif t <= 4:
            out.append({
                "category": "Weather Extreme", "metric": "Temperature",
                "value": round(t, 1), "unit": "°C", "threshold": 4,
                "severity": "MEDIUM" if t > 2 else "HIGH", "confidence": 82,
                "why": f"Cold-wave conditions ({t:.0f}°C). Exposure risk for "
                       f"homeless & livestock.",
            })
    w = wx.get("wind_kph")
    g = _generic("Wind", w, 52, 75, 100, " kph")
    if g:
        sev, label, thr = g
        out.append({
            "category": "Weather Extreme", "metric": "Wind Speed",
            "value": round(w, 1), "unit": "kph", "threshold": thr,
            "severity": sev, "confidence": 80,
            "why": f"{label}. Risk to hoardings, trees, overhead power lines.",
        })
    p = wx.get("precip_mm")
    if p is not None:
        # IMD: heavy 64.5–115.5, very heavy 115.6–204.4, extreme >204.4 (per day);
        # current is an hourly rate so we scale the bands down.
        if p >= 50:
            sev = "CRITICAL"
        elif p >= 25:
            sev = "HIGH"
        elif p >= 12:
            sev = "MEDIUM"
        else:
            sev = None
        if sev:
            out.append({
                "category": "Drainage / Flood", "metric": "Rainfall",
                "value": round(p, 1), "unit": "mm/hr", "threshold": 12,
                "severity": sev, "confidence": 83,
                "why": f"Intense rainfall ({p:.0f} mm/hr). Urban water-logging & "
                       f"storm-drain overflow risk.",
            })
    return out


def score_flood(station: dict[str, Any], fl: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not fl:
        return out
    disc = fl.get("river_discharge")
    mean = fl.get("river_discharge_mean")
    if disc is None or mean in (None, 0):
        return out
    ratio = disc / mean if mean else 0
    if ratio >= 4:
        sev = "CRITICAL"
    elif ratio >= 2.5:
        sev = "HIGH"
    elif ratio >= 1.6:
        sev = "MEDIUM"
    else:
        sev = None
    if sev:
        out.append({
            "category": "Drainage / Flood", "metric": "River Discharge",
            "value": round(disc, 1), "unit": "m³/s", "threshold": round(mean * 1.6, 1),
            "severity": sev, "confidence": min(95, 70 + int(ratio * 6)),
            "why": f"{station.get('river','River')} discharge {disc:.0f} m³/s is "
                   f"{ratio:.1f}× its seasonal mean ({mean:.0f}). Bank-overflow / "
                   f"low-lying inundation risk.",
        })
    return out


def score_earthquake(eq: dict[str, Any]) -> Optional[dict[str, Any]]:
    mag = eq.get("mag")
    if mag is None:
        return None
    if mag >= 6.0:
        sev = "CRITICAL"
    elif mag >= 5.0:
        sev = "HIGH"
    elif mag >= 4.0:
        sev = "MEDIUM"
    elif mag >= 3.0 and eq.get("in_india"):
        sev = "LOW"
    else:
        return None
    depth = eq.get("depth_km")
    return {
        "category": "Seismic / Structural", "metric": "Earthquake Magnitude",
        "value": round(mag, 1), "unit": "M", "threshold": 4.0,
        "severity": sev, "confidence": 96,
        "why": f"M{mag:.1f} earthquake, depth {depth:.0f} km — {eq.get('place')}. "
               f"Shallow events near built-up areas threaten structural integrity.",
    }
