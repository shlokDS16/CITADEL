"""
Concept-drift monitor (Jensen-Shannon divergence).

Misinformation shifts over time (what was "true" about COVID in 2020 vs
2022). We watch whether the distribution of inputs/scores the model is
seeing *recently* diverges from a *reference* baseline window. A high JS
divergence flags that the world moved and the thresholds/feeds need a
refresh — surfaced, not silently ignored.

Pure scipy/numpy over the persisted `analyses` rows. Degrades to
``available=False`` if Supabase or data is missing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger("citadel.fake_news.drift")

_NUMERIC = ["risk_score", "confidence"]
_VERDICTS = ["REAL", "LIKELY_REAL", "UNCERTAIN", "LIKELY_FAKE", "FAKE"]
_BINS = 10
_DRIFT_THRESHOLD = 0.20          # JS distance above this on any feature → drift


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable for drift: %s", e)
        return None


def _js(p: list[float], q: list[float]) -> float:
    import numpy as np
    from scipy.spatial.distance import jensenshannon

    pa = np.asarray(p, dtype=float)
    qa = np.asarray(q, dtype=float)
    if pa.sum() <= 0 or qa.sum() <= 0:
        return 0.0
    pa = pa / pa.sum()
    qa = qa / qa.sum()
    d = jensenshannon(pa, qa, base=2)          # 0..1 (base-2 → bounded)
    return float(round(0.0 if d != d else d, 4))   # NaN-guard


def _hist(vals: list[float], lo: float = 0.0, hi: float = 1.0) -> list[float]:
    import numpy as np

    if not vals:
        return [0.0] * _BINS
    h, _ = np.histogram(np.clip(vals, lo, hi), bins=_BINS, range=(lo, hi))
    return h.tolist()


def _rows(sb, start: datetime, end: datetime) -> list[dict]:  # noqa: ANN001
    try:
        return (sb.table("analyses")
                .select("risk_score,confidence,verdict,submitted_at")
                .is_("deleted_at", "null")
                .gte("submitted_at", start.isoformat())
                .lt("submitted_at", end.isoformat())
                .limit(5000).execute().data or [])
    except Exception as e:  # noqa: BLE001
        log.debug("drift rows fetch failed: %s", e)
        return []


def compute_drift(window_hours: int = 24, ref_hours: int = 168) -> dict:
    """JS divergence of the recent window vs the preceding reference window."""
    sb = _sb()
    if sb is None:
        return {"available": False, "reason": "no supabase"}
    now = datetime.now(timezone.utc)
    cur_start = now - timedelta(hours=window_hours)
    ref_start = cur_start - timedelta(hours=ref_hours)
    cur = _rows(sb, cur_start, now)
    ref = _rows(sb, ref_start, cur_start)
    if len(cur) < 5 or len(ref) < 5:
        return {"available": False, "drifted": False,
                "reason": f"insufficient data (recent={len(cur)}, "
                          f"reference={len(ref)}; need >=5 each)",
                "n_recent": len(cur), "n_reference": len(ref)}

    per_feature: dict[str, float] = {}
    for f in _NUMERIC:
        per_feature[f] = _js(
            _hist([float(r.get(f) or 0.0) for r in cur]),
            _hist([float(r.get(f) or 0.0) for r in ref]))
    cur_v = [sum(1 for r in cur if r.get("verdict") == v) for v in _VERDICTS]
    ref_v = [sum(1 for r in ref if r.get("verdict") == v) for v in _VERDICTS]
    per_feature["verdict_mix"] = _js(cur_v, ref_v)

    worst = max(per_feature.values()) if per_feature else 0.0
    drifted = worst >= _DRIFT_THRESHOLD
    result = {
        "available": True, "drifted": drifted,
        "max_js_divergence": round(worst, 4),
        "threshold": _DRIFT_THRESHOLD,
        "per_feature": per_feature,
        "n_recent": len(cur), "n_reference": len(ref),
        "window_hours": window_hours, "reference_hours": ref_hours,
        "computed_at": now.isoformat(),
    }
    try:
        sb.table("fn_drift_snapshots").insert({
            "window_start": cur_start.isoformat(),
            "window_end": now.isoformat(),
            "js_divergence": per_feature, "drifted": drifted,
            "n_samples": len(cur), "created_at": now.isoformat(),
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.debug("drift snapshot persist skipped: %s", e)
    return result


def latest(limit: int = 20) -> dict:
    """Most recent computed snapshot + a short history."""
    sb = _sb()
    if sb is None:
        return {"available": False}
    try:
        rows = (sb.table("fn_drift_snapshots").select("*")
                .order("created_at", desc=True).limit(limit).execute().data
                or [])
        return {"available": True, "latest": rows[0] if rows else None,
                "history": rows}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}
