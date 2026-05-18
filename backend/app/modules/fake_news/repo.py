"""
Persistence + HITL + feedback loop (Supabase service-role).

Tables (spec-06 + fn_*): analyses, claim_analyses, fn_review_queue,
fn_feedback, fn_meta_weights. Every call degrades gracefully if Supabase
or a table is unavailable — analysis still works, only persistence/HITL
no-op (matching the anomaly module's resilience contract).

The meta-classifier is a logistic model over the layer scores, refit from
human feedback. It is deliberately NOT applied to the live verdict until
it has enough labelled samples and acceptable accuracy — an under-trained
model must not override the verified Layer-3 result.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.modules.fake_news import heuristics

log = logging.getLogger("citadel.fake_news.repo")

_META_MIN_SAMPLES = 30          # below this, feedback is collected but not applied
_FAKEISH = {"FAKE", "LIKELY_FAKE"}
_REALISH = {"REAL", "LIKELY_REAL"}


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable: %s", e)
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# Persist
# --------------------------------------------------------------------------
def _feature_vector(out) -> dict:  # noqa: ANN001
    """Stable numeric features for the meta-classifier / drift."""
    layers = out.layers or {}
    h = layers.get("heuristics", {})
    cl = layers.get("classifier", {})
    pr = layers.get("propaganda", {})
    m = out.manipulation
    return {
        "l1_risk": float(h.get("l1_risk", 0.0)),
        "fake_score": float(cl.get("score", 0.0)) if cl.get("available") else 0.0,
        "prop_score": float(pr.get("score", 0.0)) if pr.get("available") else 0.0,
        "obfuscation": float(layers.get("adversarial", {}).get("obfuscation_score", 0.0)),
        "manip_peak": (max(m.clickbait, m.urgency, m.authority_claim, m.emotional)
                       / 100.0) if m else 0.0,
        "risk_score": float(out.risk_score),
        "n_false_claims": float(sum(1 for c in out.claims if c.verdict == "FALSE")),
        "n_true_claims": float(sum(1 for c in out.claims if c.verdict == "TRUE")),
    }


def persist_analysis(out, hashes: dict[str, str], url: str | None) -> None:  # noqa: ANN001
    """Insert the analysis + its claims; enqueue HITL review if flagged."""
    sb = _sb()
    if sb is None:
        return
    try:
        sb.table("analyses").insert({
            "id": out.id, "requester_id": out.requester_id,
            "requester_role": out.requester_role, "mode": out.mode,
            "input_text_hash": hashes.get("sha256"),
            "input_simhash": heuristics.to_signed64(int(hashes["simhash"]))
            if hashes.get("simhash") else None,
            "input_url": url, "input_excerpt": out.input_excerpt,
            "verdict": out.verdict, "confidence": out.confidence,
            "risk_score": out.risk_score, "layers": out.layers,
            "source_credibility": out.source_credibility.model_dump()
            if out.source_credibility else None,
            "bias_profile": out.bias_profile.model_dump() if out.bias_profile else None,
            "sentiment": out.sentiment.model_dump() if out.sentiment else None,
            "manipulation": out.manipulation.model_dump() if out.manipulation else None,
            "red_flags": out.red_flags, "reasoning": out.reasoning,
            "model_versions": out.model_versions,
            "response_time_ms": out.response_time_ms,
            "needs_review": out.needs_review,
            "submitted_at": out.submitted_at.isoformat(),
            "completed_at": out.completed_at.isoformat() if out.completed_at else None,
        }).execute()
    except Exception as e:  # noqa: BLE001
        log.debug("analyses insert skipped: %s", e)
        return
    if out.claims:
        try:
            sb.table("claim_analyses").insert([{
                "id": c.id, "analysis_id": out.id, "claim_text": c.text,
                "verdict": c.verdict, "confidence": c.confidence,
                "notes": c.notes, "nli_label": c.nli_label,
                "supporting_evidence": [s.model_dump() for s in c.supporting_evidence],
                "contradicting_evidence": [s.model_dump()
                                           for s in c.contradicting_evidence],
            } for c in out.claims]).execute()
        except Exception as e:  # noqa: BLE001
            log.debug("claim_analyses insert skipped: %s", e)
    if out.needs_review:
        try:
            sb.table("fn_review_queue").insert({
                "analysis_id": out.id,
                "reason": f"confidence {out.confidence} / verdict {out.verdict}",
                "status": "pending", "model_verdict": out.verdict,
                "created_at": _now(),
            }).execute()
        except Exception as e:  # noqa: BLE001
            log.debug("review enqueue skipped: %s", e)


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------
def get_analysis(analysis_id: str, requester_id: str | None = None,
                 allow_any: bool = False) -> dict | None:
    """Fetch an analysis. Tenant-scoped by `requester_id` unless `allow_any`
    (only the signed share-link path passes allow_any — the token is the
    grant). No requester and not allow_any → no access."""
    sb = _sb()
    if sb is None:
        return None
    if not allow_any and not requester_id:
        return None
    try:
        qy = (sb.table("analyses").select("*").eq("id", analysis_id)
              .is_("deleted_at", "null"))
        if not allow_any:
            qy = qy.eq("requester_id", requester_id)
        a = qy.limit(1).execute()
        if not a.data:
            return None
        row = a.data[0]
        cl = (sb.table("claim_analyses").select("*")
              .eq("analysis_id", analysis_id).execute())
        row["claims"] = cl.data or []
        return row
    except Exception as e:  # noqa: BLE001
        log.debug("get_analysis failed: %s", e)
        return None


def history(requester_id: str | None, page: int = 1, page_size: int = 25,
            q: str | None = None, verdict: str | None = None) -> dict:
    sb = _sb()
    if sb is None:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}
    try:
        page = max(1, page)
        page_size = max(1, min(100, page_size))
        query = (sb.table("analyses")
                 .select("id,mode,verdict,confidence,risk_score,input_excerpt,"
                         "needs_review,reported_to_pib,submitted_at",
                         count="exact")
                 .is_("deleted_at", "null"))
        if requester_id:
            query = query.eq("requester_id", requester_id)
        if verdict:
            query = query.eq("verdict", verdict)
        if q:
            # escape PostgREST/LIKE metacharacters so a user query of
            # "%" / "_" / "," can't widen or alter the filter
            safe = (q[:200].replace("\\", "\\\\").replace("%", "\\%")
                    .replace("_", "\\_").replace(",", " "))
            query = query.ilike("input_excerpt", f"%{safe}%")
        lo = (page - 1) * page_size
        res = (query.order("submitted_at", desc=True)
               .range(lo, lo + page_size - 1).execute())
        return {"items": res.data or [], "total": res.count or 0,
                "page": page, "page_size": page_size}
    except Exception as e:  # noqa: BLE001
        log.debug("history failed: %s", e)
        return {"items": [], "total": 0, "page": page, "page_size": page_size}


def history_stats(requester_id: str | None) -> dict:
    sb = _sb()
    base = {"checks_run": 0, "fake_detected": 0, "real_verified": 0,
            "reported_to_pib": 0}
    if sb is None:
        return base

    def _count(**filters: Any) -> int:
        try:
            qy = sb.table("analyses").select("id", count="exact").is_(
                "deleted_at", "null")
            if requester_id:
                qy = qy.eq("requester_id", requester_id)
            for k, v in filters.items():
                qy = qy.eq(k, v) if k != "_in" else qy
            if "_in" in filters:
                qy = qy.in_("verdict", filters["_in"])
            return qy.execute().count or 0
        except Exception:  # noqa: BLE001
            return 0

    base["checks_run"] = _count()
    base["fake_detected"] = _count(_in=["FAKE", "LIKELY_FAKE"])
    base["real_verified"] = _count(_in=["REAL", "LIKELY_REAL"])
    base["reported_to_pib"] = _count(reported_to_pib=True)
    return base


def soft_delete(analysis_id: str, requester_id: str | None) -> bool:
    sb = _sb()
    if sb is None or not requester_id:        # never delete cross-tenant
        return False
    try:
        (sb.table("analyses").update({"deleted_at": _now()})
         .eq("id", analysis_id).eq("requester_id", requester_id).execute())
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("soft_delete failed: %s", e)
        return False


def mark_reported(analysis_id: str) -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        sb.table("analyses").update(
            {"reported_to_pib": True, "reported_at": _now()}
        ).eq("id", analysis_id).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("mark_reported failed: %s", e)
        return False


# --------------------------------------------------------------------------
# HITL review queue + feedback
# --------------------------------------------------------------------------
def list_review_queue(status: str = "pending", limit: int = 100) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        q = sb.table("fn_review_queue").select("*")
        if status:
            q = q.eq("status", status)
        return (q.order("created_at", desc=True).limit(limit).execute().data
                or [])
    except Exception as e:  # noqa: BLE001
        log.debug("list_review_queue failed: %s", e)
        return []


def decide_review(queue_id: str, human_verdict: str, notes: str,
                  reviewer: str | None) -> dict | None:
    """Resolve a review item → update queue, correct the analysis, record
    ground-truth feedback (with the layer feature vector for retraining)."""
    sb = _sb()
    if sb is None:
        return None
    try:
        item = (sb.table("fn_review_queue").select("*")
                .eq("id", queue_id).limit(1).execute())
        if not item.data:
            return None
        row = item.data[0]
        aid = row.get("analysis_id")
        sb.table("fn_review_queue").update({
            "status": "resolved", "human_verdict": human_verdict,
            "notes": notes, "assigned_to": reviewer, "decided_at": _now(),
        }).eq("id", queue_id).execute()

        layer_scores = {}
        an = sb.table("analyses").select("layers,risk_score,manipulation,verdict") \
            .eq("id", aid).limit(1).execute()
        model_verdict = row.get("model_verdict")
        if an.data:
            a0 = an.data[0]
            model_verdict = model_verdict or a0.get("verdict")
            lay = a0.get("layers") or {}
            layer_scores = {
                "l1_risk": (lay.get("heuristics") or {}).get("l1_risk", 0.0),
                "fake_score": (lay.get("classifier") or {}).get("score", 0.0),
                "prop_score": (lay.get("propaganda") or {}).get("score", 0.0),
                "risk_score": a0.get("risk_score", 0.0),
            }
            sb.table("analyses").update(
                {"verdict": human_verdict, "needs_review": False}
            ).eq("id", aid).execute()

        sb.table("fn_feedback").insert({
            "analysis_id": aid, "human_verdict": human_verdict,
            "model_verdict": model_verdict,
            "correct": (human_verdict == model_verdict),
            "layer_scores": layer_scores, "notes": notes,
            "reviewer": reviewer, "created_at": _now(),
        }).execute()
        return {"queue_id": queue_id, "analysis_id": aid,
                "human_verdict": human_verdict, "resolved": True}
    except Exception as e:  # noqa: BLE001
        log.warning("decide_review failed: %s", e)
        return None


def add_feedback(analysis_id: str, human_verdict: str,
                 reviewer: str | None, notes: str = "") -> bool:
    sb = _sb()
    if sb is None:
        return False
    try:
        an = sb.table("analyses").select("layers,risk_score,verdict").eq(
            "id", analysis_id).limit(1).execute()
        mv, ls = None, {}
        if an.data:
            a0 = an.data[0]
            mv = a0.get("verdict")
            lay = a0.get("layers") or {}
            ls = {"l1_risk": (lay.get("heuristics") or {}).get("l1_risk", 0.0),
                  "fake_score": (lay.get("classifier") or {}).get("score", 0.0),
                  "prop_score": (lay.get("propaganda") or {}).get("score", 0.0),
                  "risk_score": a0.get("risk_score", 0.0)}
        sb.table("fn_feedback").insert({
            "analysis_id": analysis_id, "human_verdict": human_verdict,
            "model_verdict": mv, "correct": (human_verdict == mv),
            "layer_scores": ls, "notes": notes, "reviewer": reviewer,
            "created_at": _now(),
        }).execute()
        return True
    except Exception as e:  # noqa: BLE001
        log.debug("add_feedback failed: %s", e)
        return False


# --------------------------------------------------------------------------
# Refittable meta-classifier (logistic over layer scores)
# --------------------------------------------------------------------------
_FEATS = ["l1_risk", "fake_score", "prop_score", "risk_score"]


def refit_meta() -> dict:
    """Train a logistic model feedback → fake/real. No-op below the sample
    floor (an under-trained model must not influence live verdicts)."""
    sb = _sb()
    if sb is None:
        return {"trained": False, "reason": "no supabase"}
    try:
        rows = (sb.table("fn_feedback")
                .select("human_verdict,layer_scores").execute().data or [])
        xs, ys = [], []
        for r in rows:
            hv = (r.get("human_verdict") or "").upper()
            ls = r.get("layer_scores") or {}
            if hv in _FAKEISH:
                ys.append(1)
            elif hv in _REALISH:
                ys.append(0)
            else:
                continue
            xs.append([float(ls.get(f, 0.0)) for f in _FEATS])
        n = len(ys)
        if n < _META_MIN_SAMPLES or len(set(ys)) < 2:
            return {"trained": False, "n_samples": n,
                    "reason": f"need >= {_META_MIN_SAMPLES} balanced samples"}
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression(max_iter=300).fit(xs, ys)
        acc = round(float(clf.score(xs, ys)), 4)
        weights = {"coef": clf.coef_[0].tolist(),
                   "intercept": float(clf.intercept_[0]), "features": _FEATS}
        sb.table("fn_meta_weights").insert({
            "weights": weights, "n_samples": n,
            "metrics": {"train_accuracy": acc}, "trained_at": _now(),
        }).execute()
        # Honest: weights are persisted for audit/export and future
        # gated rollout — they are NOT yet fed into the live verdict
        # (an under-trained meta-model must not override verified L3).
        return {"trained": True, "n_samples": n, "train_accuracy": acc,
                "applied_to_live": False,
                "note": "weights stored; live application gated pending eval"}
    except Exception as e:  # noqa: BLE001
        log.warning("refit_meta failed: %s", e)
        return {"trained": False, "reason": str(e)}


def save_propagation_run(requester_id: str | None, source_name: str,
                         result: dict) -> str | None:
    sb = _sb()
    if sb is None:
        return None
    try:
        import uuid as _uuid

        rid = str(_uuid.uuid4())
        sb.table("fn_propagation_runs").insert({
            "id": rid, "requester_id": requester_id,
            "source_name": source_name,
            "n_nodes": result.get("n_nodes"), "n_edges": result.get("n_edges"),
            "burst_score": result.get("burst_score"),
            "coordination_score": result.get("coordination_score"),
            "bot_likeness_score": result.get("bot_likeness_score"),
            "cib_verdict": result.get("cib_verdict"),
            "clusters": result.get("clusters"),
            "metrics": {k: result.get(k) for k in
                        ("cib_score", "structural_score", "n_events",
                         "n_accounts", "time_span_seconds", "explanation")},
            "created_at": _now(),
        }).execute()
        return rid
    except Exception as e:  # noqa: BLE001
        log.debug("propagation persist skipped: %s", e)
        return None


def list_propagation_runs(limit: int = 50) -> list[dict]:
    sb = _sb()
    if sb is None:
        return []
    try:
        return (sb.table("fn_propagation_runs").select("*")
                .order("created_at", desc=True).limit(limit).execute().data
                or [])
    except Exception as e:  # noqa: BLE001
        log.debug("list_propagation_runs failed: %s", e)
        return []


def meta_status() -> dict:
    sb = _sb()
    if sb is None:
        return {"available": False}
    try:
        r = (sb.table("fn_meta_weights").select("*")
             .order("trained_at", desc=True).limit(1).execute())
        if not r.data:
            return {"available": False, "trained": False}
        m = r.data[0]
        return {"available": True, "trained": True,
                "n_samples": m.get("n_samples"),
                "metrics": m.get("metrics"), "trained_at": m.get("trained_at")}
    except Exception as e:  # noqa: BLE001
        return {"available": False, "error": str(e)}
