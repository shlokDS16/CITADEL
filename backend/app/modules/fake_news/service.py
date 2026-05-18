"""
Fake News Detector — service layer.

Phase 0: real liveness/readiness report (no mock values). The waterfall
orchestrator, HITL, history and drift glue arrive in later phases.
"""
from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import httpx

from app import __version__
from app.config import settings
from app.modules.fake_news import adversarial, heuristics, pipeline as ml, schemas

log = logging.getLogger("citadel.fake_news.service")

# Spec-06 + extension tables this module relies on.
_EXPECTED_TABLES = [
    "analyses",
    "claim_analyses",
    "source_credibility_db",
    "fact_check_feed",
    "learn_content",
    "fn_debunked",
    "fn_review_queue",
    "fn_feedback",
    "fn_drift_snapshots",
    "fn_meta_weights",
    "fn_propagation_runs",
]


def _pkg(name: str) -> str | None:
    """Package version via metadata — does NOT import the module (fast)."""
    try:
        return metadata.version(name)
    except Exception:
        return None


def _probe_tables() -> tuple[bool, list[str]]:
    """Best-effort: which expected tables are reachable via service-role.

    A missing table is normal until the user runs backend/sql/fake_news_schema.sql
    — the module degrades gracefully, so this is informational, not fatal.
    """
    try:
        from app.database import get_supabase

        sb = get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase client unavailable: %s", e)
        return False, list(_EXPECTED_TABLES)

    missing: list[str] = []
    for t in _EXPECTED_TABLES:
        try:
            sb.table(t).select("*").limit(1).execute()
        except Exception:  # noqa: BLE001 — table absent / not yet created
            missing.append(t)
    return (len(missing) == 0), missing


def health() -> schemas.HealthResponse:
    """Readiness probe — real signals only."""
    models_dir = settings.fn_models_path
    try:
        models_dir.mkdir(parents=True, exist_ok=True)
        models_dir_ok = models_dir.is_dir()
    except Exception as e:  # noqa: BLE001
        log.warning("models dir not creatable: %s", e)
        models_dir_ok = False

    tables_ok, missing = _probe_tables()

    notes: list[str] = []
    if missing:
        notes.append(
            f"{len(missing)} table(s) not found — run backend/sql/fake_news_schema.sql "
            "in the Supabase SQL editor."
        )
    if not settings.GOOGLE_FACTCHECK_API_KEY:
        notes.append("GOOGLE_FACTCHECK_API_KEY not set — keyless fact-check fallbacks will be used.")
    if not settings.FN_ENABLE_HEAVY_MODELS:
        notes.append("FN_ENABLE_HEAVY_MODELS=false — propaganda/NLI/deepfake disabled (lean profile).")

    return schemas.HealthResponse(
        status="ok",
        module="fake_news",
        version=__version__,
        python=sys.version.split()[0],
        ml=schemas.MLRuntime(
            torch=_pkg("torch"),
            transformers=_pkg("transformers"),
            onnxruntime=_pkg("onnxruntime"),
            huggingface_hub=_pkg("huggingface_hub"),
            scikit_learn=_pkg("scikit-learn"),
        ),
        models_dir=str(models_dir),
        models_dir_ok=models_dir_ok,
        models_configured={
            "fake_news": settings.FN_MODEL_FAKE,
            "clickbait": settings.FN_MODEL_CLICKBAIT,
            "propaganda": settings.FN_MODEL_PROPAGANDA,
            "nli": settings.FN_MODEL_NLI,
            "bias": settings.FN_MODEL_BIAS,
            "deepfake": settings.FN_MODEL_DEEPFAKE,
            "deepfake_fallback": settings.FN_MODEL_DEEPFAKE_FALLBACK,
        },
        tables_ok=tables_ok,
        tables_missing=missing,
        groq_configured=bool(settings.GROQ_API_KEY),
        google_factcheck_configured=bool(settings.GOOGLE_FACTCHECK_API_KEY),
        notes=notes,
    )


# ==========================================================================
# Analysis waterfall.  Phase 1 = Layer 1 only (heuristics + adversarial +
# hash/near-dup). Layers 2-4 (transformer classifier, RAG/NLI, LLM rationale)
# are wired in later phases — the verdict is honestly marked preliminary
# until then. Nothing here returns mock values; every field is computed.
# ==========================================================================
_UA = "Mozilla/5.0 (compatible; CitadelFakeNews/1.0; +https://citadel.local)"
_FETCH_TIMEOUT = 12.0
_FETCH_MAX_BYTES = 2_000_000
_EXCERPT = 240
_L1_VERSION = "l1-heuristics-1.0"


def _get_sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable (degrading): %s", e)
        return None


def _fetch_article(url: str) -> tuple[str, str, str]:
    """Fetch a URL and extract clean article text. Never raises.

    Returns (text, title, final_url). On failure text/title are "".
    """
    try:
        with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": _UA}) as c:
            r = c.get(url)
        final_url = str(r.url)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "html" not in ctype.lower():
            return "", "", final_url
        html = r.text[: _FETCH_MAX_BYTES * 2]
        try:
            from readability import Document  # readability-lxml
            from lxml import html as lxml_html

            doc = Document(html)
            title = (doc.short_title() or "").strip()
            summary_html = doc.summary(html_partial=True)
            text = lxml_html.fromstring(summary_html).text_content()
        except Exception:  # noqa: BLE001 — fall back to crude strip
            import re as _re

            title = ""
            text = _re.sub(r"<[^>]+>", " ", html)
        text = " ".join(text.split())
        return text[:20000], title, final_url
    except Exception as e:  # noqa: BLE001
        log.info("article fetch failed for %s: %s", url, e)
        return "", "", url


def _credibility_from_domain(dom: dict | None) -> schemas.SourceCredibility | None:
    """Phase-1 credibility approximation from domain signals only.

    Phase 3 replaces this with the maintained source_credibility_db lookup
    (allowlist/blocklist). Kept honest: no invented publisher reputations.
    """
    if not dom:
        return None
    risk = float(dom.get("risk", 0.0))
    if dom.get("official_gov"):
        score, rating = 92, "HIGH"
    else:
        score = int(round(100 * (1.0 - risk)))
        score = max(5, min(95, score))
        rating = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
    return schemas.SourceCredibility(
        publisher=dom.get("publisher", "unknown"),
        publisher_known=bool(dom.get("official_gov")),
        domain_age_days=dom.get("domain_age_days"),
        age_label=dom.get("age_label", ""),
        score=score,
        trust_rating=rating,
        in_allowlist=bool(dom.get("official_gov")),
        in_blocklist=False,
    )


def _l2_run(text: str) -> dict:
    """Run the Layer-2 transformer + lexicon classifiers (each degrades)."""
    return {
        "fake": ml.classify_fake_news(text),
        "clickbait": ml.classify_clickbait(text),
        "bias": ml.classify_bias(text),
        "propaganda": ml.detect_propaganda(text),
        "sentiment": ml.sentiment(text),
    }


def _combine_verdict(
    l1_risk: float, l2: dict, debunked: dict | None
) -> tuple[float, str, float, bool]:
    """Fuse L1 risk with the L2 style classifiers into a verdict.

    Still pre-fact-check: these are *style/pattern* signals, so confidence is
    bounded below "verified" until Layer 3 (RAG/NLI) lands in Phase 3.
    """
    fake = l2["fake"].get("score") if l2["fake"].get("available") else None
    prop = l2["propaganda"].get("score", 0.0) if l2["propaganda"].get("available") else 0.0

    parts: list[tuple[float, float]] = [(0.45, l1_risk)]
    if fake is not None:
        parts.append((0.40, float(fake)))
    parts.append((0.15, float(prop)))
    wsum = sum(w for w, _ in parts)
    combined = sum(w * v for w, v in parts) / wsum
    if l1_risk >= 0.6 and (fake or 0.0) >= 0.6:        # L1 & L2 agree → reinforce
        combined = min(1.0, combined + 0.12)
    if debunked:
        combined = max(combined, 0.97 if debunked.get("kind") == "exact" else 0.90)
    combined = round(min(1.0, combined), 4)

    if debunked and debunked.get("kind") == "exact":
        verdict, conf = "FAKE", 0.97
    elif combined >= 0.82:
        verdict, conf = "LIKELY_FAKE", 0.80
    elif combined >= 0.60:
        verdict, conf = "LIKELY_FAKE", 0.70
    elif combined >= 0.42:
        verdict, conf = "UNCERTAIN", 0.50
    elif combined >= 0.22:
        verdict, conf = "LIKELY_REAL", 0.60
    else:
        verdict, conf = "LIKELY_REAL", 0.66
    needs_review = verdict == "UNCERTAIN" or conf < settings.FN_AUTO_VERDICT_CONFIDENCE
    return combined, verdict, round(conf, 4), needs_review


def _persist(out: schemas.AnalysisOut, hashes: dict[str, str], url: str | None) -> None:
    sb = _get_sb()
    if sb is None:
        return
    try:
        sb.table("analyses").insert({
            "id": out.id,
            "requester_id": out.requester_id,
            "requester_role": out.requester_role,
            "mode": out.mode,
            "input_text_hash": hashes.get("sha256"),
            "input_simhash": int(hashes["simhash"]) if hashes.get("simhash") else None,
            "input_url": url,
            "input_excerpt": out.input_excerpt,
            "verdict": out.verdict,
            "confidence": out.confidence,
            "risk_score": out.risk_score,
            "layers": out.layers,
            "claims": [c.model_dump() for c in out.claims],
            "source_credibility": out.source_credibility.model_dump()
            if out.source_credibility else None,
            "bias_profile": out.bias_profile.model_dump() if out.bias_profile else None,
            "sentiment": out.sentiment.model_dump() if out.sentiment else None,
            "manipulation": out.manipulation.model_dump() if out.manipulation else None,
            "red_flags": out.red_flags,
            "reasoning": out.reasoning,
            "model_versions": out.model_versions,
            "response_time_ms": out.response_time_ms,
            "needs_review": out.needs_review,
            "submitted_at": out.submitted_at.isoformat(),
            "completed_at": out.completed_at.isoformat() if out.completed_at else None,
        }).execute()
    except Exception as e:  # noqa: BLE001 — table may not exist yet (pre-DDL)
        log.debug("analyses persist skipped: %s", e)


def analyze(
    req: schemas.AnalyzeIn,
    requester_id: str | None = None,
    requester_role: str = "citizen",
) -> schemas.AnalysisOut:
    """Run the analysis waterfall (Phase 1: Layer 1) and return the result."""
    t0 = time.perf_counter()
    now = datetime.now(timezone.utc)
    aid = str(uuid.uuid4())
    reasoning: list[str] = []

    # ---- media: forensics arrive in Phase 5 (don't error the endpoint) ----
    if req.mode in ("IMAGE", "VIDEO"):
        return schemas.AnalysisOut(
            id=aid, requester_id=requester_id, requester_role=requester_role,
            submitted_at=now, completed_at=datetime.now(timezone.utc),
            mode=req.mode, input_excerpt="(media)", verdict="UNCERTAIN",
            confidence=0.0, risk_score=0.0, needs_review=True,
            reasoning=["Deepfake / AI-image forensics is delivered in Phase 5. "
                       "Text and URL analysis is fully live now."],
            model_versions={"pipeline": "phase-1"},
            response_time_ms=int((time.perf_counter() - t0) * 1000),
        )

    # ---- resolve input text ----
    url = req.url
    title = ""
    if req.mode == "URL":
        text, title, url = _fetch_article(req.url or "")
        if not text:
            return schemas.AnalysisOut(
                id=aid, requester_id=requester_id, requester_role=requester_role,
                submitted_at=now, completed_at=datetime.now(timezone.utc),
                mode=req.mode, input_excerpt=(req.url or "")[:_EXCERPT],
                verdict="UNCERTAIN", confidence=0.0, risk_score=0.0,
                needs_review=True,
                reasoning=[f"Could not fetch or extract readable article text "
                           f"from {req.url}. The page may be paywalled, JS-only, "
                           f"or unreachable."],
                model_versions={"pipeline": "phase-1"},
                response_time_ms=int((time.perf_counter() - t0) * 1000),
            )
        reasoning.append(f"Fetched article from {url}"
                         + (f" — \"{title}\"" if title else ""))
    else:
        text = req.text or ""

    # ---- Layer 1: adversarial normalize + heuristics ----
    norm = adversarial.normalize(text)
    if norm.signals:
        reasoning.append("Adversarial evasion detected: " + ", ".join(norm.signals))
    h = heuristics.analyze(
        original=text,
        normalized=norm.normalized,
        match_variant=norm.match_variant,
        obfuscation_score=norm.obfuscation_score,
        obfuscation_signals=norm.signals,
        url=url,
        supabase=_get_sb(),
    )
    if h.debunked_match:
        reasoning.append(
            f"Matched previously debunked content "
            f"({h.debunked_match['kind']}, distance {h.debunked_match['distance']})."
        )
    reasoning.append(
        f"Layer 1 heuristics risk = {h.l1_risk:.2f} "
        f"(manipulation peak {max(h.manipulation.values())}/100, "
        f"{len(h.red_flags)} red flag(s))."
    )
    reasoning.append("Layers 2-4 (transformer classifier, RAG/NLI fact-check, "
                     "LLM rationale) are not yet active — this is a preliminary "
                     "Layer-1 screening result.")

    # ---- Layer 2: transformer style classifiers + VADER sentiment ----
    l2 = _l2_run(text)
    red_flags = list(h.red_flags)
    manip = dict(h.manipulation)

    cb = l2["clickbait"]
    if cb.get("available") and "score" in cb:
        manip["clickbait"] = max(manip.get("clickbait", 0),
                                 int(round(cb["score"] * 100)))
    fk = l2["fake"]
    if fk.get("available") and fk.get("score", 0.0) >= 0.65:
        red_flags.append(
            f"Fabrication-style language flagged by classifier "
            f"({int(round(fk['score'] * 100))}% — a style signal, not proof)"
        )
    pr = l2["propaganda"]
    if pr.get("available") and pr.get("techniques"):
        red_flags.append("Propaganda techniques: " + ", ".join(pr["techniques"][:4]))
    bi = l2["bias"]
    if bi.get("available") and bi.get("score", 0.0) >= 0.60:
        red_flags.append(
            f"Loaded / biased language ({int(round(bi['score'] * 100))}% "
            f"intensity — not a political-lean score)"
        )
    red_flags = list(dict.fromkeys(red_flags))

    se = l2["sentiment"]
    sentiment_obj = (
        schemas.SentimentBreakdown(
            positive=se.get("positive", 0), negative=se.get("negative", 0),
            neutral=se.get("neutral", 100))
        if se.get("available") else None
    )

    combined_risk, verdict, confidence, needs_review = _combine_verdict(
        h.l1_risk, l2, h.debunked_match)

    l2_bits: list[str] = []
    if fk.get("available"):
        l2_bits.append(f"fabrication-style {int(round(fk.get('score', 0) * 100))}%")
    elif fk.get("discriminative") is False:
        l2_bits.append("fabrication classifier excluded (not discriminative on "
                       "general text — RAG/NLI in Layer 3 does verification)")
    if cb.get("available"):
        l2_bits.append(f"clickbait {manip['clickbait']}%")
    if bi.get("available"):
        l2_bits.append(f"bias {int(round((bi.get('score') or 0) * 100))}%")
    if pr.get("available"):
        l2_bits.append(f"propaganda {int(round(pr.get('score', 0) * 100))}%")
    reasoning.append(
        "Layer 2: "
        + (", ".join(l2_bits) if l2_bits else "no classifier signals available")
        + f". Combined risk {combined_risk:.2f}."
    )
    if se.get("available"):
        reasoning.append(
            f"Sentiment (VADER): pos {se['positive']}% / neg {se['negative']}% / "
            f"neu {se['neutral']}% (compound {se.get('compound', 0)}).")
    reasoning.append("Layer 3 (RAG fact-check + NLI claim verification) is not yet "
                     "active — this verdict is style/pattern based, not fact-checked.")

    out = schemas.AnalysisOut(
        id=aid,
        requester_id=requester_id,
        requester_role=requester_role,  # type: ignore[arg-type]
        submitted_at=now,
        completed_at=datetime.now(timezone.utc),
        mode=req.mode,
        input_excerpt=(norm.normalized or text)[:_EXCERPT],
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        risk_score=combined_risk,
        needs_review=needs_review,
        quota_exhausted=False,
        claims=[],                                  # Phase 3-4
        source_credibility=_credibility_from_domain(h.domain)
        if req.options.source_credibility else None,
        bias_profile=None,                          # political-lean model: later phase
        sentiment=sentiment_obj,
        red_flags=red_flags,
        manipulation=schemas.ManipulationProfile(**manip),
        related_fact_checks=[],                     # Phase 3
        reasoning=reasoning,
        layers={
            "adversarial": {"signals": norm.signals,
                            "obfuscation_score": norm.obfuscation_score},
            "heuristics": {"l1_risk": h.l1_risk, "metrics": h.metrics,
                           "signals": h.signals, "domain": h.domain,
                           "debunked_match": h.debunked_match},
            "classifier": l2["fake"],
            "clickbait": l2["clickbait"],
            "bias": l2["bias"],
            "propaganda": l2["propaganda"],
            "sentiment": l2["sentiment"],
        },
        model_versions={
            "adversarial": "1.0", "heuristics": _L1_VERSION,
            "fake_news": settings.FN_MODEL_FAKE,
            "clickbait": settings.FN_MODEL_CLICKBAIT,
            "bias": settings.FN_MODEL_BIAS,
            "propaganda": settings.FN_MODEL_PROPAGANDA,
            "sentiment": "vader-3",
        },
        response_time_ms=int((time.perf_counter() - t0) * 1000),
    )
    _persist(out, h.hashes, url)
    return out

