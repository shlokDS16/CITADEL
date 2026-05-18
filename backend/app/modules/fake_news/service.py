"""
Fake News Detector — service layer.

Phase 0: real liveness/readiness report (no mock values). The waterfall
orchestrator, HITL, history and drift glue arrive in later phases.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

import httpx

from app import __version__
from app.config import settings
from app.modules.fake_news import (
    adversarial,
    credibility,
    fact_check,
    heuristics,
    pipeline as ml,
    schemas,
)

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

    # L1 (verified strong) weighted above the L2 fake-news head, which is a
    # known-noisy public model (flags some true short facts as fabrication).
    # Real verification comes from Layer 3, applied in _final_verdict.
    parts: list[tuple[float, float]] = [(0.50, l1_risk)]
    if fake is not None:
        parts.append((0.30, float(fake)))
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


def _final_verdict(
    combined_risk: float, l2_verdict: str, l2_conf: float,
    claims: list[dict], debunked: dict | None,
) -> tuple[float, str, float, bool, str]:
    """Fuse the style risk with Layer-3 fact verification.

    This is the only path (besides an exact debunk hash) that may emit a
    high-confidence REAL or FAKE — because here the claims were actually
    checked against external evidence, not just scored for style.
    """
    fc_false = any(c["verdict"] == "FALSE" and c["confidence"] >= 0.85
                   for c in claims)
    weak_false = any(c["verdict"] in ("FALSE", "SUSPICIOUS") for c in claims)
    disputed = any(c["verdict"] == "MISLEADING" for c in claims)
    corroborated = (
        any(c["verdict"] == "TRUE" and c["confidence"] >= 0.80 for c in claims)
        and not any(c["verdict"] in ("FALSE", "SUSPICIOUS", "MISLEADING")
                    for c in claims)
    )

    if debunked and debunked.get("kind") == "exact":
        return 0.97, "FAKE", 0.97, False, "Exact match to known debunked content."
    if fc_false:
        return (max(combined_risk, 0.95), "FAKE", 0.93, False,
                "A credible fact-checker rated a central claim false.")
    if weak_false and combined_risk >= 0.4:
        return (max(combined_risk, 0.7), "LIKELY_FAKE", 0.82, False,
                "Independent evidence contradicts a central claim.")
    if disputed:
        return (combined_risk, "UNCERTAIN", 0.55, True,
                "Claims are disputed — supporting and contradicting evidence.")
    if corroborated and combined_risk < 0.4:
        return (min(combined_risk, 0.15), "REAL", 0.86, False,
                "Central claims corroborated by credible sources.")
    if corroborated:
        return (min(combined_risk, 0.3), "LIKELY_REAL", 0.74, False,
                "Claims corroborated, though style signals are mixed.")
    # no decisive verification → fall back to the style verdict, but a
    # genuine verification *attempt* slightly de-risks pure-style calls.
    conf = round(min(0.78, l2_conf + (0.05 if claims else 0.0)), 4)
    nr = l2_verdict == "UNCERTAIN" or conf < settings.FN_AUTO_VERDICT_CONFIDENCE
    note = ("Claims checked but evidence was inconclusive."
            if claims else "No check-worthy claims extracted.")
    return combined_risk, l2_verdict, conf, nr, note


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
    # ---- Layer 3: RAG fact verification (claims + NLI + Google FC) ----
    fc: dict = {"claims": [], "related_fact_checks": []}
    if req.options.cross_reference and req.options.claim_by_claim:
        try:
            fc = fact_check.analyze_claims(text, max_claims=4)
        except Exception as e:  # noqa: BLE001
            log.warning("fact-check layer failed: %s", e)

    claim_objs = [
        schemas.ClaimAnalysis(
            id=c["id"], text=c["text"], verdict=c["verdict"],
            confidence=c["confidence"], notes=c["notes"],
            nli_label=c.get("nli_label"),
            supporting_evidence=[schemas.Source(**s) for s in c["supporting_evidence"]],
            contradicting_evidence=[schemas.Source(**s)
                                    for s in c["contradicting_evidence"]],
        )
        for c in fc.get("claims", [])
    ]
    related_objs = [schemas.RelatedFactCheck(**r)
                    for r in fc.get("related_fact_checks", [])]

    final_risk, verdict, confidence, needs_review, fc_note = _final_verdict(
        combined_risk, verdict, confidence, fc.get("claims", []), h.debunked_match)

    if fc.get("claims"):
        vc: dict[str, int] = {}
        for c in fc["claims"]:
            vc[c["verdict"]] = vc.get(c["verdict"], 0) + 1
        reasoning.append(
            f"Layer 3: extracted {len(fc['claims'])} claim(s); verdicts "
            + ", ".join(f"{k}x{n}" for k, n in vc.items()) + f". {fc_note}")
    else:
        reasoning.append("Layer 3: " + fc_note)
    reasoning.append("Layer 4 (LLM rationale, high-risk only) wires in Phase 4.")

    cred_obj = None
    if req.options.source_credibility:
        dom = h.domain or {}
        cinfo = credibility.score_for(
            (dom.get("publisher") if dom else None) or url,
            dom.get("domain_age_days") if dom else None)
        cred_obj = schemas.SourceCredibility(
            publisher=cinfo["publisher"], publisher_known=cinfo["publisher_known"],
            domain_age_days=cinfo["domain_age_days"], age_label=cinfo["age_label"],
            score=cinfo["score"], trust_rating=cinfo["trust_rating"],
            in_allowlist=cinfo["in_allowlist"], in_blocklist=cinfo["in_blocklist"])
        if cinfo.get("in_blocklist"):
            red_flags.insert(0, f"Publisher on blocklist: {cinfo['publisher']}")
        elif cinfo.get("in_allowlist"):
            reasoning.append(f"Publisher {cinfo['publisher']} is a known credible "
                             f"source (credibility {cinfo['score']}/100).")

    out = schemas.AnalysisOut(
        id=aid, requester_id=requester_id,
        requester_role=requester_role,  # type: ignore[arg-type]
        submitted_at=now, completed_at=datetime.now(timezone.utc),
        mode=req.mode, input_excerpt=(norm.normalized or text)[:_EXCERPT],
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence, risk_score=round(final_risk, 4),
        needs_review=needs_review, quota_exhausted=False,
        claims=claim_objs,
        source_credibility=cred_obj,
        bias_profile=None,
        sentiment=sentiment_obj,
        red_flags=list(dict.fromkeys(red_flags)),
        manipulation=schemas.ManipulationProfile(**manip),
        related_fact_checks=related_objs,
        reasoning=reasoning,
        layers={
            "adversarial": {"signals": norm.signals,
                            "obfuscation_score": norm.obfuscation_score},
            "heuristics": {"l1_risk": h.l1_risk, "metrics": h.metrics,
                           "signals": h.signals, "domain": h.domain,
                           "debunked_match": h.debunked_match},
            "classifier": l2["fake"], "clickbait": l2["clickbait"],
            "bias": l2["bias"], "propaganda": l2["propaganda"],
            "sentiment": l2["sentiment"],
            "fact_check": {
                "n_claims": len(fc.get("claims", [])),
                "related": len(related_objs),
                "google_fc": bool(settings.GOOGLE_FACTCHECK_API_KEY),
            },
        },
        model_versions={
            "adversarial": "1.0", "heuristics": _L1_VERSION,
            "fake_news": settings.FN_MODEL_FAKE,
            "clickbait": settings.FN_MODEL_CLICKBAIT,
            "bias": settings.FN_MODEL_BIAS,
            "propaganda": settings.FN_MODEL_PROPAGANDA,
            "nli": settings.FN_MODEL_NLI, "claims": "spacy-en_core_web_sm",
            "sentiment": "vader-3",
        },
        response_time_ms=int((time.perf_counter() - t0) * 1000),
    )
    _persist(out, h.hashes, url)
    return out


# ==========================================================================
# Background: curated-credibility seed + fact-check feed refresh (<=6h).
# Mirrors the anomaly module's daemon pattern; degrades if tables absent.
# ==========================================================================
_FEED_STOP = threading.Event()
_FEED_THREAD: threading.Thread | None = None
_FEED_INTERVAL = 6 * 3600


def _parse_feed(xml_text: str) -> list[dict]:
    import html as _html
    import re as _re
    import xml.etree.ElementTree as ET

    items: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:  # noqa: BLE001
        return items
    for el in root.iter():
        if el.tag.split("}")[-1].lower() not in ("item", "entry"):
            continue
        d: dict = {}
        for ch in el:
            ctag = ch.tag.split("}")[-1].lower()
            if ctag == "title":
                d["title"] = (ch.text or "").strip()
            elif ctag == "link":
                d["url"] = (ch.get("href") or ch.text or "").strip()
            elif ctag in ("description", "summary", "content"):
                txt = _re.sub(r"<[^>]+>", "", ch.text or "")
                d["body"] = _html.unescape(txt).strip()[:500]
        if d.get("title") and d.get("url"):
            items.append(d)
    return items


def refresh_fact_check_feed() -> dict:
    """Pull recent debunks from configured fact-check RSS into fact_check_feed."""
    sb = _get_sb()
    if sb is None:
        return {"ok": False, "reason": "no supabase"}
    total = 0
    for feed_url in settings.fn_factcheck_feed_list:
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True,
                              headers={"User-Agent": _UA}) as c:
                r = c.get(feed_url)
            if r.status_code != 200:
                continue
            pub = feed_url.split("/")[2] if "//" in feed_url else feed_url
            rows = [{
                "publisher": pub, "url": it["url"],
                "title": it.get("title", "")[:500],
                "body_excerpt": it.get("body", "")[:500],
                "claim_norm": (it.get("title", "") or "").lower()[:300],
                "published_at": None,
            } for it in _parse_feed(r.text)[:30]]
            if rows:
                sb.table("fact_check_feed").upsert(rows, on_conflict="url").execute()
                total += len(rows)
        except Exception as e:  # noqa: BLE001
            log.debug("feed refresh failed for %s: %s", feed_url, e)
    return {"ok": True, "ingested": total}


def _feed_loop() -> None:
    try:
        credibility.seed()
    except Exception as e:  # noqa: BLE001
        log.warning("credibility seed failed: %s", e)
    while not _FEED_STOP.is_set():
        try:
            log.info("fact-check feed refresh: %s", refresh_fact_check_feed())
        except Exception as e:  # noqa: BLE001
            log.warning("feed loop error: %s", e)
        _FEED_STOP.wait(timeout=_FEED_INTERVAL)


def start_background_feed_refresh() -> None:
    global _FEED_THREAD
    if _FEED_THREAD is not None and _FEED_THREAD.is_alive():
        return
    _FEED_STOP.clear()
    _FEED_THREAD = threading.Thread(target=_feed_loop, name="fn-feed-refresh",
                                    daemon=True)
    _FEED_THREAD.start()


def stop_background_feed_refresh() -> None:
    _FEED_STOP.set()

