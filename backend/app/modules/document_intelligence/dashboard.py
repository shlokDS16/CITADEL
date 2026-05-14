"""
Dashboard analytics — all queries computed from real `documents` rows.
No hardcoded values per the build prompt.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.database import get_supabase

PERIOD_DAYS = {"7d": 7, "14d": 14, "30d": 30, "90d": 90}
PROCESSED_STATUSES = ("APPROVED", "ARCHIVED", "REJECTED", "PENDING_REVIEW")


def _period_window(period: str) -> tuple[datetime, datetime, datetime]:
    """Return (current_start, current_end, previous_start) for trend deltas."""
    days = PERIOD_DAYS.get(period, 30)
    now = datetime.now(timezone.utc)
    cur_start = now - timedelta(days=days)
    prev_start = cur_start - timedelta(days=days)
    return cur_start, now, prev_start


def _trend(current: float, previous: float) -> tuple[float, Literal["up", "down", "flat"]]:
    if previous == 0:
        return (100.0 if current > 0 else 0.0), ("up" if current > 0 else "flat")
    pct = round((current - previous) / previous * 100, 2)
    if abs(pct) < 0.5:
        return pct, "flat"
    return pct, ("up" if pct > 0 else "down")


def _query_processed(start: datetime, end: datetime) -> list[dict]:
    return (
        get_supabase().table("documents")
        .select("id, document_type, confidence, pii_count, created_at, approved_at, archived_at, uploaded_by, department")
        .gte("created_at", start.isoformat())
        .lte("created_at", end.isoformat())
        .in_("status", list(PROCESSED_STATUSES))
        .execute().data or []
    )


# ============================================================
# 5.1 Stats
# ============================================================
def get_stats(period: str = "30d") -> dict[str, Any]:
    cur_start, cur_end, prev_start = _period_window(period)

    cur_rows = _query_processed(cur_start, cur_end)
    prev_rows = _query_processed(prev_start, cur_start)

    def _avg_conf(rows): vals = [r["confidence"] for r in rows if r.get("confidence") is not None]; return round(sum(vals) / len(vals), 2) if vals else 0.0
    def _pii_total(rows): return sum(int(r.get("pii_count") or 0) for r in rows)
    def _avg_ttl(rows):
        deltas = []
        for r in rows:
            t_end = r.get("approved_at") or r.get("archived_at")
            if not t_end: continue
            try:
                t_end_dt = datetime.fromisoformat(t_end.replace("Z", "+00:00"))
                t_start_dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
                deltas.append((t_end_dt - t_start_dt).total_seconds() / 3600.0)
            except Exception:
                continue
        return round(sum(deltas) / len(deltas), 2) if deltas else 0.0

    cur_count = len(cur_rows)
    prev_count = len(prev_rows)
    cur_conf = _avg_conf(cur_rows)
    prev_conf = _avg_conf(prev_rows)
    cur_pii = _pii_total(cur_rows)
    prev_pii = _pii_total(prev_rows)
    cur_ttl = _avg_ttl(cur_rows)
    prev_ttl = _avg_ttl(prev_rows)

    p1, t1 = _trend(cur_count, prev_count)
    p2, t2 = _trend(cur_conf, prev_conf)
    p3, t3 = _trend(cur_pii, prev_pii)
    p4, t4 = _trend(cur_ttl, prev_ttl)

    return {
        "docs_processed":      {"value": cur_count, "change_percent": p1, "trend": t1},
        "avg_confidence":      {"value": cur_conf,  "change_percent": p2, "trend": t2},
        "pii_redactions":      {"value": cur_pii,   "change_percent": p3, "trend": t3},
        # for time-to-approve, "down" trend (faster) is good — but we report raw direction
        "avg_time_to_approve": {"value": cur_ttl,   "change_percent": p4, "trend": t4},
    }


# ============================================================
# 5.2 Volume
# ============================================================
def get_volume(period: str = "14d") -> dict[str, Any]:
    cur_start, cur_end, _ = _period_window(period)
    rows = _query_processed(cur_start, cur_end)

    bucket: Counter = Counter()
    for r in rows:
        try:
            d = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00")).date().isoformat()
            bucket[d] += 1
        except Exception:
            continue

    days = PERIOD_DAYS.get(period, 14)
    today = datetime.now(timezone.utc).date()
    series = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        series.append({"date": d, "count": int(bucket.get(d, 0))})

    return {"period": period, "data": series, "today_count": int(bucket.get(today.isoformat(), 0))}


# ============================================================
# 5.3 By type
# ============================================================
def get_by_type(period: str = "30d") -> dict[str, Any]:
    cur_start, cur_end, _ = _period_window(period)
    rows = _query_processed(cur_start, cur_end)
    if not rows:
        return {"total": 0, "breakdown": []}

    counts = Counter(r["document_type"] for r in rows)
    total = sum(counts.values())

    top3 = counts.most_common(3)
    other = total - sum(c for _, c in top3)

    breakdown = [
        {"type": t, "count": c, "percent": round(c * 100 / total, 2)}
        for t, c in top3
    ]
    if other > 0:
        breakdown.append({"type": "other", "count": other, "percent": round(other * 100 / total, 2)})

    return {"total": total, "breakdown": breakdown}


# ============================================================
# 5.4 Top uploaders
# ============================================================
def get_top_uploaders(period: str = "30d", limit: int = 5) -> dict[str, Any]:
    cur_start, cur_end, _ = _period_window(period)
    rows = _query_processed(cur_start, cur_end)
    if not rows:
        return {"uploaders": []}

    counter: Counter = Counter()
    for r in rows:
        key = r.get("department") or r.get("uploaded_by") or "Unknown"
        counter[key] += 1

    out = []
    for rank, (name, count) in enumerate(counter.most_common(limit), start=1):
        initials = "".join(w[0].upper() for w in name.split() if w)[:3] or "?"
        out.append({"rank": rank, "name": name, "initials": initials, "count": count})
    return {"uploaders": out}


# ============================================================
# 5.5 SLA distribution
# ============================================================
def get_sla_distribution(period: str = "30d") -> dict[str, Any]:
    cur_start, cur_end, _ = _period_window(period)
    rows = _query_processed(cur_start, cur_end)

    buckets = {"under_1h": 0, "1_to_4h": 0, "4_to_24h": 0, "over_24h": 0}
    total = 0

    for r in rows:
        end = r.get("approved_at") or r.get("archived_at")
        if not end:
            continue
        try:
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
            start_dt = datetime.fromisoformat(r["created_at"].replace("Z", "+00:00"))
        except Exception:
            continue
        h = (end_dt - start_dt).total_seconds() / 3600.0
        if h < 1: buckets["under_1h"] += 1
        elif h < 4: buckets["1_to_4h"] += 1
        elif h < 24: buckets["4_to_24h"] += 1
        else: buckets["over_24h"] += 1
        total += 1

    out = {}
    for key, count in buckets.items():
        pct = round(count * 100 / total, 2) if total else 0.0
        out[key] = {"count": count, "percent": pct}
    return out
