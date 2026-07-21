"""
System Overview — the landing-dashboard KPI aggregator (Phase 4).

Composes real cross-module counts for the government and citizen landing
dashboards, replacing the hardcoded StatCard values (847 sensors, 12
alerts, 92% accuracy, etc.). Every number here has a genuine source or is
honestly a fixed structural fact (module count); nothing is invented.
"""
from app.modules.overview.router import router  # noqa: F401
