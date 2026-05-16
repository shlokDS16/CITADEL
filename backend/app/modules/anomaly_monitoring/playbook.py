"""
Response playbook.

Turns a raw anomaly into an actionable brief an operations officer can
hand to a field team:

  - impact radius (km), scaled by severity & category physics
  - estimated population at risk (radius × representative urban density)
  - the civic systems / who is affected
  - IMMEDIATE actions (first 60 min)
  - RECOMMENDED solutions (root-cause / mitigation)
  - which department owns the response

Numbers are transparent estimates (assumptions stated in the payload),
not precise claims — the UI labels them "est.".
"""
from __future__ import annotations

import math
from typing import Any

# Representative built-up population density (people / km²) for Indian
# metro cores. Conservative single figure keeps the estimate explainable.
_URBAN_DENSITY = 11000

# severity → impact-radius multiplier (km baseline per category below)
_SEV_MULT = {"LOW": 0.5, "MEDIUM": 1.0, "HIGH": 1.8, "CRITICAL": 3.0}

# category → (baseline radius km, owning department, affected systems)
_CATEGORY = {
    "Air Quality": {
        "base_km": 6.0,
        "dept": "Pollution Control Board",
        "systems": ["Public health (respiratory)", "Schools & outdoor labour", "Hospitals (OPD load)"],
        "immediate": [
            "Issue a public health advisory for the affected zone (mask + limit outdoor activity).",
            "Trigger SAFAR/CPCB cross-check and notify district health officer.",
            "Halt open burning & dust-generating construction within the radius.",
            "Deploy water sprinkling / anti-smog measures on arterial roads.",
        ],
        "solutions": [
            "Activate Graded Response Action Plan (GRAP) stage matching the AQI band.",
            "Re-route heavy diesel traffic away from the corridor for 24–48 h.",
            "Inspect nearby industrial emitters for non-compliance.",
        ],
    },
    "Seismic / Structural": {
        "base_km": 12.0,
        "dept": "Disaster Management Authority (PWD structural cell)",
        "systems": ["Bridges & flyovers", "Old/heritage buildings", "Gas & water mains", "Metro tunnels"],
        "immediate": [
            "Dispatch structural inspection teams to bridges/flyovers in radius.",
            "Visually clear and, if needed, close the most vulnerable spans.",
            "Alert utilities to check gas & water mains for rupture.",
            "Open the emergency operations centre; ready NDRF liaison.",
        ],
        "solutions": [
            "Prioritise instrumented bridges for accelerometer data review.",
            "Schedule rapid visual screening (RVS) of pre-1990 structures.",
            "Issue aftershock public-safety guidance.",
        ],
    },
    "Drainage / Flood": {
        "base_km": 8.0,
        "dept": "Municipal Storm-Water & Sanitation",
        "systems": ["Low-lying colonies", "Underpasses", "Sewage network", "Power substations at grade"],
        "immediate": [
            "Pre-position de-watering pumps at known water-logging points.",
            "Barricade and man flooded underpasses; stop traffic entry.",
            "Clear storm-drain inlets of debris on the affected stretch.",
            "Warn residents of low-lying colonies; ready relief shelters.",
        ],
        "solutions": [
            "Open flood gates / divert excess to retention ponds.",
            "Coordinate upstream reservoir release schedule.",
            "Inspect substations for grade-level water ingress; isolate if at risk.",
        ],
    },
    "Weather Extreme": {
        "base_km": 15.0,
        "dept": "State Disaster Management + Health",
        "systems": ["Outdoor workers", "Elderly & homeless", "Power grid (peak load)", "Hoardings & trees"],
        "immediate": [
            "Broadcast heat/cold/storm advisory across the affected districts.",
            "Open cooling/relief centres; extend hospital heat-stroke readiness.",
            "Inspect & secure large hoardings; pre-clear tree-fall hotspots.",
            "Warn the discom of likely peak-load surge.",
        ],
        "solutions": [
            "Shift outdoor labour hours away from peak heat window.",
            "Activate the state heat-action / cold-wave plan.",
            "Stage mobile medical units near high-footfall areas.",
        ],
    },
}

_DEFAULT = {
    "base_km": 6.0,
    "dept": "City Operations Centre",
    "systems": ["General civic services"],
    "immediate": ["Dispatch a field team to verify the sensor reading."],
    "solutions": ["Escalate to the relevant department for root-cause analysis."],
}


def build_impact(category: str, severity: str) -> dict[str, Any]:
    spec = _CATEGORY.get(category, _DEFAULT)
    radius_km = round(spec["base_km"] * _SEV_MULT.get(severity, 1.0), 1)
    area = math.pi * radius_km * radius_km
    pop = int(area * _URBAN_DENSITY)
    return {
        "impact_radius_km": radius_km,
        "impact_area_km2": round(area, 1),
        "population_at_risk_est": pop,
        "density_assumption": _URBAN_DENSITY,
        "owning_department": spec["dept"],
        "affected_systems": spec["systems"],
        "immediate_actions": spec["immediate"],
        "recommended_solutions": spec["solutions"],
    }


def affected_zones(station: dict[str, Any], radius_km: float) -> list[str]:
    """Human-readable affected-area phrasing for the alert body."""
    city = station.get("city", "the city")
    zone = station.get("zone", "")
    return [
        f"{city} core ({radius_km:.0f} km radius)",
        f"{zone} administrative zone",
        f"Wards within {radius_km:.0f} km of station {station.get('id','')}",
    ]
