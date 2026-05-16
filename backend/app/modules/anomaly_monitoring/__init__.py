"""
Anomaly Monitoring — CITADEL Government Module 4.

Live infrastructure / environmental anomaly detection over REAL, free,
no-API-key open data feeds:

  - Open-Meteo Air Quality   (Copernicus CAMS) — PM2.5/PM10/NO2/O3/SO2/CO/US-AQI
  - Open-Meteo Weather       — temperature / wind / precipitation extremes
  - Open-Meteo Flood         — river discharge (drainage / flood risk)
  - USGS Earthquake GeoJSON  — live seismic events (structural / vibration)

No vendor keys, no billing. Coordinates are real Indian-metro stations so
the map and the alerts are grounded in actual sensor geography.
"""
from app.modules.anomaly_monitoring.router import router  # noqa: F401
