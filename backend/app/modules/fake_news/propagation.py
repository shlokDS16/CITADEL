"""
Coordinated Inauthentic Behaviour (CIB) / propagation analysis.

Production misinformation systems analyse *how* content spreads, not just
the content. We have no live social-graph firehose, so this subsystem is
**ingest-fed**: the operator uploads a share-graph (CSV or JSON) and we
compute real propagation signals on it. Nothing is invented — if the input
lacks the required fields it returns a clear error, not fabricated metrics.

Signals (all 0..1, transparent — this is GNN-*inspired* structural
analysis, not a trained GNN; a trained GNN needs labelled cascades we
don't have, and we don't pretend otherwise):
  - burst        : temporal concentration of shares (bot bursts vs organic)
  - coordination : distinct accounts posting the same content within a tight
                   window (the CIB signature)
  - bot_likeness : mass-created accounts / low followers / extreme post rate
  - structural   : disconnected broadcast pattern vs a connected cascade

Accepted input
  CSV  : header row; columns (case-insensitive, flexible names) —
         account_id (req), timestamp (req), content_id|content_hash,
         account_created_at, parent_account_id, followers
  JSON : [ {event}, ... ]  or  {"events":[...]}  or
         {"nodes":[...], "edges":[...]}
"""
from __future__ import annotations

import csv
import io
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone

log = logging.getLogger("citadel.fake_news.propagation")

_TS_KEYS = ("timestamp", "ts", "shared_at", "time", "created_at_share")
_ACC_KEYS = ("account_id", "user_id", "account", "user", "uid", "handle")
_CONTENT_KEYS = ("content_hash", "content_id", "post_id", "url", "message_id")
_PARENT_KEYS = ("parent_account_id", "parent", "source_account", "shared_from",
                "in_reply_to")
_CREATED_KEYS = ("account_created_at", "account_created", "user_created_at",
                 "join_date")
_FOLLOWERS_KEYS = ("followers", "follower_count", "followers_count")

_COORD_WINDOW_S = 90          # same content within this → coordinated
_BURST_WINDOW_S = 600         # tightest 10-min window for burst measure
_MASS_CREATE_DAYS = 2         # accounts created within N days → mass-created


def _first(d: dict, keys: tuple[str, ...]) -> str | None:
    for k in keys:
        if k in d and str(d[k]).strip():
            return str(d[k]).strip()
    return None


def _parse_dt(v: str | None) -> datetime | None:
    if not v:
        return None
    v = v.strip().replace("Z", "+00:00")
    def _utc(d):  # noqa: ANN001, ANN202 — normalize to tz-aware UTC so
        # naive and offset-aware inputs never get subtracted together.
        if d is None:
            return None
        return (d.replace(tzinfo=timezone.utc) if d.tzinfo is None
                else d.astimezone(timezone.utc))

    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M",
                "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return _utc(datetime.fromisoformat(v) if fmt is None
                        else datetime.strptime(v, fmt))
        except Exception:  # noqa: BLE001
            continue
    try:
        return _utc(datetime.fromtimestamp(float(v)))
    except Exception:  # noqa: BLE001
        return None


def parse_share_graph(raw: bytes, filename: str = "") -> dict:
    """Normalise CSV/JSON upload → list of share events. Never raises."""
    text = raw.decode("utf-8", "replace").strip()
    rows: list[dict] = []
    try:
        if filename.lower().endswith(".json") or text[:1] in ("[", "{"):
            data = json.loads(text)
            if isinstance(data, dict):
                rows = data.get("events") or data.get("nodes") or []
            elif isinstance(data, list):
                rows = data
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"could not parse input ({e})"}

    events: list[dict] = []
    for r in rows:
        r = {str(k).strip().lower(): v for k, v in dict(r).items()}
        acc = _first(r, _ACC_KEYS)
        ts = _parse_dt(_first(r, _TS_KEYS))
        if not acc or ts is None:
            continue
        events.append({
            "account": acc, "ts": ts,
            "content": _first(r, _CONTENT_KEYS) or "_single",
            "parent": _first(r, _PARENT_KEYS),
            "created": _parse_dt(_first(r, _CREATED_KEYS)),
            "followers": _to_int(_first(r, _FOLLOWERS_KEYS)),
        })
    if len(events) < 3:
        return {"ok": False,
                "error": "need >=3 share events with at least account_id + "
                         "timestamp columns (CSV header or JSON events)"}
    return {"ok": True, "events": events}


def _to_int(v: str | None) -> int | None:
    try:
        return int(float(v)) if v is not None else None
    except Exception:  # noqa: BLE001
        return None


def _burst(events: list[dict]) -> float:
    """Temporal burstiness, combining:
      - relative concentration vs a uniform-spread expectation, and
      - absolute peak share-rate (so a tight sub-window bot burst, where
        total span < the window, still scores high).
    """
    ts = sorted(e["ts"].timestamp() for e in events)
    n = len(ts)
    span = ts[-1] - ts[0]
    if span <= 0:                       # all shares at once → maximal burst
        return 1.0
    best, j, best_dur = 0, 0, 0.0
    for i in range(n):
        while ts[i] - ts[j] > _BURST_WINDOW_S:
            j += 1
        if i - j + 1 > best:
            best = i - j + 1
            best_dur = ts[i] - ts[j]
    peak_frac = best / n
    expected = min(1.0, _BURST_WINDOW_S / span)        # uniform expectation
    relative = max(0.0, (peak_frac - expected) / (1 - expected + 1e-9))
    # density only counts when there is an actual multi-event cluster — a
    # lone event in the window is not a burst (avoids a divide-by-floor
    # false positive on slow organic spread).
    if best >= 3:
        rate_per_min = best / max(best_dur / 60.0, 1 / 60.0)
        density = min(1.0, rate_per_min / 10.0)        # >=10 shares/min → max
    else:
        density = 0.0
    return round(min(1.0, max(relative, density)), 4)


def _coordination(events: list[dict]) -> tuple[float, list[dict]]:
    by_content: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_content[e["content"]].append(e)
    coordinated = 0
    clusters: list[dict] = []
    for content, evs in by_content.items():
        evs.sort(key=lambda x: x["ts"])
        i = 0
        while i < len(evs):
            j = i
            accts = {evs[i]["account"]}
            while (j + 1 < len(evs) and
                   (evs[j + 1]["ts"] - evs[i]["ts"]).total_seconds()
                   <= _COORD_WINDOW_S):
                j += 1
                accts.add(evs[j]["account"])
            if len(accts) >= 3:                         # >=3 accts in window
                coordinated += (j - i + 1)
                clusters.append({
                    "content": content[:80], "accounts": len(accts),
                    "events": j - i + 1,
                    "window_seconds": int(
                        (evs[j]["ts"] - evs[i]["ts"]).total_seconds()),
                })
            i = j + 1
    score = round(coordinated / len(events), 4) if events else 0.0
    clusters.sort(key=lambda c: -c["accounts"])
    return score, clusters[:10]


def _bot_likeness(events: list[dict]) -> float:
    accts: dict[str, dict] = {}
    for e in events:
        a = accts.setdefault(e["account"], {"n": 0, "created": e["created"],
                                            "followers": e["followers"]})
        a["n"] += 1
    n = len(accts)
    if n == 0:
        return 0.0
    created = [a["created"] for a in accts.values() if a["created"]]
    mass = 0.0
    if len(created) >= 3:
        days = sorted(c.timestamp() / 86400 for c in created)
        clustered = sum(
            1 for i in range(len(days))
            if days[i] - days[max(0, i - 1)] <= _MASS_CREATE_DAYS)
        mass = clustered / len(days)
    low_followers = [a for a in accts.values() if a["followers"] is not None]
    lf = (sum(1 for a in low_followers if a["followers"] < 15)
          / len(low_followers)) if low_followers else 0.0
    hyper = sum(1 for a in accts.values() if a["n"] >= 5) / n
    return round(min(1.0, 0.5 * mass + 0.3 * lf + 0.2 * hyper), 4)


def _structural(events: list[dict]) -> tuple[float, int, int]:
    """Disconnected broadcast (CIB) vs a connected organic cascade."""
    parent = {}            # union-find
    nodes: set[str] = set()
    edges = 0

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    for e in events:
        nodes.add(e["account"])
        if e["parent"]:
            nodes.add(e["parent"])
            union(e["account"], e["parent"])
            edges += 1
    comps = len({find(n) for n in nodes}) if nodes else 1
    n = len(nodes) or 1
    # many components relative to nodes + few edges → broadcast/seeded pattern
    frag = comps / n
    sparsity = 1.0 - min(1.0, edges / n)
    return round(min(1.0, 0.6 * frag + 0.4 * sparsity), 4), len(nodes), edges


def analyze(events: list[dict]) -> dict:
    burst = _burst(events)
    coordination, clusters = _coordination(events)
    bot = _bot_likeness(events)
    structural, n_nodes, n_edges = _structural(events)
    cib = round(0.30 * coordination + 0.25 * burst + 0.25 * bot
                + 0.20 * structural, 4)
    if cib >= 0.66:
        verdict = "COORDINATED"
    elif cib >= 0.40:
        verdict = "SUSPICIOUS"
    else:
        verdict = "ORGANIC"
    ts = sorted(e["ts"] for e in events)
    explain = [
        f"Burst {burst:.2f}: peak share concentration in a "
        f"{_BURST_WINDOW_S // 60}-min window.",
        f"Coordination {coordination:.2f}: {len(clusters)} cluster(s) of >=3 "
        f"accounts posting the same content within {_COORD_WINDOW_S}s.",
        f"Bot-likeness {bot:.2f}: mass-created / low-follower / hyperactive "
        f"account share.",
        f"Structural {structural:.2f}: {n_nodes} accounts / {n_edges} "
        f"reshare edges (fragmentation vs connected cascade).",
    ]
    return {
        "cib_verdict": verdict, "cib_score": cib,
        "burst_score": burst, "coordination_score": coordination,
        "bot_likeness_score": bot, "structural_score": structural,
        "n_nodes": n_nodes, "n_edges": n_edges, "n_events": len(events),
        "n_accounts": len({e["account"] for e in events}),
        "time_span_seconds": int((ts[-1] - ts[0]).total_seconds()),
        "clusters": clusters, "explanation": explain,
    }


def run(raw: bytes, filename: str = "") -> dict:
    parsed = parse_share_graph(raw, filename)
    if not parsed["ok"]:
        return {"ok": False, "error": parsed["error"]}
    try:
        result = analyze(parsed["events"])
        result["ok"] = True
        return result
    except Exception as e:  # noqa: BLE001
        log.exception("propagation analyze failed")
        return {"ok": False, "error": f"analysis failed: {e}"}
