"""
Fake News Detector — service layer.

Phase 0: real liveness/readiness report (no mock values). The waterfall
orchestrator, HITL, history and drift glue arrive in later phases.
"""
from __future__ import annotations

import hashlib
import json
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
    drift,
    fact_check,
    heuristics,
    llm_rationale,
    media_forensics,
    pipeline as ml,
    repo,
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
        groq_backup_configured=bool(getattr(settings, "GROQ_API_KEY_2", "")),
        gemini_configured=bool(getattr(settings, "GEMINI_API_KEY", "")),
        google_factcheck_configured=bool(settings.GOOGLE_FACTCHECK_API_KEY),
        notes=notes,
    )


# ==========================================================================
# Analysis waterfall: L1 heuristics+adversarial+hash → L2 transformer
# classifiers + VADER → L3 RAG fact-check + NLI → L4 LLM rationale
# (high-risk only). Nothing returns mock values; every field is computed.
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


_MAX_REDIRECTS = 4


def _host_is_safe(host: str) -> bool:
    """True only if every IP `host` resolves to is a public address.

    Blocks SSRF to loopback / private / link-local (incl. cloud metadata
    169.254.169.254) / reserved / multicast ranges.
    """
    import ipaddress
    import socket

    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001
        return False
    for fam, _t, _p, _c, sockaddr in infos:
        ip_s = sockaddr[0].split("%")[0]
        try:
            ip = ipaddress.ip_address(ip_s)
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return False
    return True


def ssrf_safe_get(url: str, max_bytes: int = _FETCH_MAX_BYTES):  # noqa: ANN201
    """SSRF-hardened GET. Validates the host (and every redirect hop) is a
    public address, forbids non-http(s) schemes, and streams with a byte cap.
    Returns the final httpx.Response, or None if blocked/failed. Never raises.
    """
    from urllib.parse import urlparse

    cur = url
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            p = urlparse(cur)
            if p.scheme not in ("http", "https") or not p.hostname:
                log.warning("ssrf: rejected non-http/url %r", cur[:120])
                return None
            if not _host_is_safe(p.hostname):
                log.warning("ssrf: blocked private/internal host %r", p.hostname)
                return None
            with httpx.Client(timeout=_FETCH_TIMEOUT, follow_redirects=False,
                              headers={"User-Agent": _UA}) as c:
                with c.stream("GET", cur) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            return None
                        cur = str(httpx.URL(cur).join(loc))
                        continue
                    buf = bytearray()
                    for chunk in r.iter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            break
                    r._content = bytes(buf)  # noqa: SLF001 — finalize body
                    return r
        log.warning("ssrf: too many redirects for %r", url[:120])
        return None
    except Exception as e:  # noqa: BLE001
        log.info("ssrf_safe_get failed: %s", e)
        return None


def _fetch_article(url: str) -> tuple[str, str, str]:
    """Fetch a URL and extract clean article text. Never raises.

    Returns (text, title, final_url). On failure text/title are "".
    """
    try:
        r = ssrf_safe_get(url, max_bytes=_FETCH_MAX_BYTES * 2)
        if r is None:
            return "", "", url
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
    # An NLI / fact-check contradiction at >=0.70 is decisive verification.
    # L3 is the authority here (the public L2 classifier is noisy by
    # design), so an L3-contradicted claim must NOT be gated behind the L2
    # *style* risk the way weak_false was — a fact-checked-false claim with
    # clean prose was wrongly surfacing as UNCERTAIN.
    strong_false = any(c["verdict"] == "FALSE" and c["confidence"] >= 0.70
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
    if strong_false:
        return (max(combined_risk, 0.80), "LIKELY_FAKE", 0.82, False,
                "Layer-3 evidence (fact-check / NLI) contradicts a "
                "central claim.")
    if weak_false:
        return (max(combined_risk, 0.60), "LIKELY_FAKE", 0.72, True,
                "Independent evidence contradicts a central claim — "
                "routed for human review.")
    if disputed:
        return (combined_risk, "UNCERTAIN", 0.55, True,
                "Claims are disputed — supporting and contradicting evidence.")
    if corroborated and combined_risk < 0.4:
        return (min(combined_risk, 0.15), "REAL", 0.86, False,
                "Central claims corroborated by credible sources.")
    if corroborated:
        return (min(combined_risk, 0.3), "LIKELY_REAL", 0.74, False,
                "Claims corroborated, though style signals are mixed.")
    # No decisive verification. A misinformation tool must NOT assert a
    # REAL-family verdict from absence-of-red-flags alone — that's "not
    # verified", not "true". Downgrade unverified REAL-ish to UNCERTAIN;
    # only keep FAKE-ish style verdicts (those are risk warnings, not
    # truth claims).
    if l2_verdict in ("REAL", "LIKELY_REAL"):
        note = ("Style looks clean but no claim could be verified — "
                "treat as unverified, not confirmed true."
                if claims else
                "No check-worthy claims to verify — unverified, not confirmed.")
        return combined_risk, "UNCERTAIN", 0.5, True, note
    conf = round(min(0.78, l2_conf + (0.05 if claims else 0.0)), 4)
    nr = l2_verdict == "UNCERTAIN" or conf < settings.FN_AUTO_VERDICT_CONFIDENCE
    note = ("Claims checked but evidence was inconclusive."
            if claims else "No check-worthy claims extracted.")
    return combined_risk, l2_verdict, conf, nr, note


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

    # ---- media: fetch-from-URL forensics, else point at the upload route ----
    if req.mode in ("IMAGE", "VIDEO"):
        if req.url:
            try:
                rr = ssrf_safe_get(req.url, max_bytes=settings.max_upload_bytes)
                if rr is not None and rr.status_code == 200 and rr.content:
                    return analyze_media_content(
                        rr.content, req.url.split("/")[-1] or "media",
                        query="", requester_id=requester_id,
                        requester_role=requester_role)
            except Exception as e:  # noqa: BLE001
                log.info("media url fetch failed: %s", e)
        return schemas.AnalysisOut(
            id=aid, requester_id=requester_id,
            requester_role=requester_role,  # type: ignore[arg-type]
            submitted_at=now, completed_at=datetime.now(timezone.utc),
            mode=req.mode, input_excerpt="(media)", verdict="UNCERTAIN",
            confidence=0.0, risk_score=0.0, needs_review=True,
            reasoning=["For image/video, upload the file to POST "
                       "/api/v1/fake-news/analyze/media (multipart), or pass a "
                       "direct media URL."],
            model_versions={"pipeline": "fake-news"},
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

    # ---- Layer 4: LLM rationale — high-risk / ambiguous only (token-frugal) ----
    llm_layer: dict = {"invoked": False}
    llm_quota = False
    # Token-frugal gate: LLM only on genuinely risky/ambiguous content.
    # NOT gated on needs_review — confidence is < auto-threshold for almost
    # everything pre-fact-check, which would burn Groq's daily quota.
    if text and (final_risk >= settings.FN_HIGH_RISK_THRESHOLD
                 or verdict == "UNCERTAIN"):
        lr = llm_rationale.rationale(
            excerpt=norm.normalized or text, verdict=verdict,
            confidence=confidence, risk=final_risk,
            red_flags=red_flags, claims=fc.get("claims", []))
        llm_layer = {"invoked": True, **lr}
        if lr.get("quota_exhausted"):
            llm_quota = True
            reasoning.append(
                "Layer 4: LLM rationale unavailable — provider quota reached"
                + (f" (retry in ~{lr['retry_hint']})" if lr.get("retry_hint") else "")
                + ". Verdict stands from Layers 1-3 (local, not quota-bound).")
        elif lr.get("available"):
            if lr.get("rationale"):
                reasoning.append("Layer 4 rationale: " + lr["rationale"])
            if lr.get("recommendation"):
                reasoning.append("Recommendation: " + lr["recommendation"])
        else:
            reasoning.append("Layer 4: LLM returned no usable rationale.")
    else:
        reasoning.append("Layer 4: skipped (not high-risk — token-frugal gate).")

    out = schemas.AnalysisOut(
        id=aid, requester_id=requester_id,
        requester_role=requester_role,  # type: ignore[arg-type]
        submitted_at=now, completed_at=datetime.now(timezone.utc),
        mode=req.mode, input_excerpt=(norm.normalized or text)[:_EXCERPT],
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence, risk_score=round(final_risk, 4),
        needs_review=needs_review, quota_exhausted=llm_quota,
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
            "llm": llm_layer,
        },
        model_versions={
            "adversarial": "1.0", "heuristics": _L1_VERSION,
            "fake_news": settings.FN_MODEL_FAKE,
            "clickbait": settings.FN_MODEL_CLICKBAIT,
            "bias": settings.FN_MODEL_BIAS,
            "propaganda": settings.FN_MODEL_PROPAGANDA,
            "nli": settings.FN_MODEL_NLI, "claims": "spacy-en_core_web_sm",
            "sentiment": "vader-3", "llm": llm_rationale._FN_MODEL,
        },
        response_time_ms=int((time.perf_counter() - t0) * 1000),
    )
    repo.persist_analysis(out, h.hashes, url)
    return out


_SEV = {"REAL": 0, "LIKELY_REAL": 1, "UNCERTAIN": 2, "LIKELY_FAKE": 3, "FAKE": 4}


def analyze_media_content(
    content: bytes, filename: str = "", query: str = "",
    requester_id: str | None = None, requester_role: str = "citizen",
) -> schemas.AnalysisOut:
    """Image/video deepfake + AI-gen forensics; merges an optional caption
    through the text waterfall (worst-case of media vs text → catches
    out-of-context images with misleading captions)."""
    t0 = time.perf_counter()
    now = datetime.now(timezone.utc)
    aid = str(uuid.uuid4())
    mf = media_forensics.analyze_media(content, filename)
    reasoning: list[str] = []

    if not mf.get("available"):
        return schemas.AnalysisOut(
            id=aid, requester_id=requester_id,
            requester_role=requester_role,  # type: ignore[arg-type]
            submitted_at=now, completed_at=datetime.now(timezone.utc),
            mode="VIDEO" if mf.get("kind") == "video" else "IMAGE",
            input_excerpt=f"({mf.get('kind', 'media')} upload)",
            verdict="UNCERTAIN", confidence=0.0, risk_score=0.0,
            needs_review=True,
            reasoning=[f"Media forensics unavailable: {mf.get('reason')}"],
            layers={"forensics": mf}, model_versions={"pipeline": "fake-news"},
            response_time_ms=int((time.perf_counter() - t0) * 1000))

    kind = mf["kind"]
    mode = "VIDEO" if kind == "video" else "IMAGE"
    verdict, confidence = mf["verdict"], mf["confidence"]
    risk = float(mf["fabricated"])
    red_flags = list(mf.get("red_flags", []))
    reasoning.append(
        f"Media forensics ({kind}): fabricated probability {risk:.2f}"
        + (f" via {mf.get('forensics', {}).get('model')}"
           if mf.get("forensics") else "") + ".")
    for fl in mf.get("exif", {}).get("flags", []):
        reasoning.append("EXIF: " + fl)

    claims: list = []
    related: list = []
    cred = sentiment = manip = None
    if query and len(query.strip()) >= 20:
        try:
            txt = analyze(schemas.AnalyzeIn(mode="TEXT", text=query),
                          requester_id, requester_role)
            if _SEV.get(txt.verdict, 0) > _SEV.get(verdict, 0):
                verdict, confidence = txt.verdict, max(confidence, txt.confidence)
            risk = max(risk, txt.risk_score)
            red_flags += txt.red_flags
            claims, related = txt.claims, txt.related_fact_checks
            cred, sentiment, manip = (txt.source_credibility, txt.sentiment,
                                      txt.manipulation)
            reasoning.append("Caption text analyzed and merged "
                             "(worst-case of media vs text).")
        except Exception as e:  # noqa: BLE001
            reasoning.append(f"Caption text analysis skipped: {e}")

    needs_review = (verdict == "UNCERTAIN"
                    or confidence < settings.FN_AUTO_VERDICT_CONFIDENCE)
    out = schemas.AnalysisOut(
        id=aid, requester_id=requester_id,
        requester_role=requester_role,  # type: ignore[arg-type]
        submitted_at=now, completed_at=datetime.now(timezone.utc),
        mode=mode,
        input_excerpt=(query[:_EXCERPT] if query
                       else f"({kind} upload: {filename or 'media'})"),
        verdict=verdict, confidence=round(confidence, 4),
        risk_score=round(risk, 4), needs_review=needs_review,
        quota_exhausted=False, claims=claims, source_credibility=cred,
        bias_profile=None, sentiment=sentiment,
        red_flags=list(dict.fromkeys(red_flags)), manipulation=manip,
        related_fact_checks=related, reasoning=reasoning,
        layers={"forensics": mf},
        model_versions={"deepfake": settings.FN_MODEL_DEEPFAKE,
                        "deepfake_fallback": settings.FN_MODEL_DEEPFAKE_FALLBACK},
        response_time_ms=int((time.perf_counter() - t0) * 1000))
    repo.persist_analysis(
        out, {"sha256": hashlib.sha256(content).hexdigest(), "simhash": "0"},
        None)
    return out


# ==========================================================================
# Bulk analysis (<=50 items, async) — spec-06 /bulk
# ==========================================================================
_BULK: dict[str, dict] = {}
_BULK_LOCK = threading.Lock()
_BULK_VERDICT = {"REAL": "REAL", "LIKELY_REAL": "REAL", "FAKE": "FAKE",
                 "LIKELY_FAKE": "LIKELY_FAKE", "UNCERTAIN": "UNCERTAIN"}


def _is_url(s: str) -> bool:
    return s.lower().startswith(("http://", "https://"))


_BULK_WORKERS = 3
_BULK_MAX_KEEP = 50


def _bulk_one(bid: str, idx: int, it: str, rid: str | None, role: str) -> None:
    try:
        mode = "URL" if _is_url(it) else "TEXT"
        req = schemas.AnalyzeIn(
            mode=mode, **({"url": it} if mode == "URL" else {"text": it}))
        out = analyze(req, rid, role)
        with _BULK_LOCK:
            row = _BULK[bid]["items"][idx]
            row["verdict"] = _BULK_VERDICT.get(out.verdict, "UNCERTAIN")
            row["confidence"] = out.confidence
            row["analysis_id"] = out.id
    except Exception as e:  # noqa: BLE001
        with _BULK_LOCK:
            _BULK[bid]["items"][idx]["verdict"] = "ERROR"
            _BULK[bid]["items"][idx]["error"] = str(e)[:200]
    finally:
        with _BULK_LOCK:
            _BULK[bid]["completed"] += 1


def _bulk_worker(bid: str, items: list[str], rid: str | None,
                 role: str) -> None:
    from concurrent.futures import ThreadPoolExecutor

    try:
        with ThreadPoolExecutor(max_workers=_BULK_WORKERS,
                                thread_name_prefix=f"fn-bulk-{bid[:6]}") as ex:
            for idx, it in enumerate(items):
                ex.submit(_bulk_one, bid, idx, it, rid, role)
    finally:
        with _BULK_LOCK:
            _BULK[bid]["status"] = "done"


def bulk_submit(items: list[str], requester_id: str | None = None,
                requester_role: str = "citizen") -> dict:
    items = [s.strip() for s in items if s and s.strip()][:50]
    bid = str(uuid.uuid4())
    rec = {
        "id": bid, "submitted_at": datetime.now(timezone.utc).isoformat(),
        "total": len(items), "completed": 0,
        "status": "running" if items else "done",
        "items": [{"url": it, "verdict": "UNCERTAIN", "confidence": 0.0,
                   "analysis_id": None, "error": None} for it in items],
    }
    with _BULK_LOCK:
        _BULK[bid] = rec
        if len(_BULK) > _BULK_MAX_KEEP:        # evict oldest (no leak)
            for k in sorted(_BULK, key=lambda x: _BULK[x]["submitted_at"]
                            )[:len(_BULK) - _BULK_MAX_KEEP]:
                _BULK.pop(k, None)
    if items:
        threading.Thread(target=_bulk_worker,
                         args=(bid, items, requester_id, requester_role),
                         name=f"fn-bulk-{bid[:8]}", daemon=True).start()
    return {"id": bid, "submitted_at": rec["submitted_at"],
            "total": rec["total"],
            "status_url": f"/api/v1/fake-news/bulk/{bid}"}


def bulk_status(batch_id: str) -> dict | None:
    with _BULK_LOCK:
        rec = _BULK.get(batch_id)
        return json.loads(json.dumps(rec)) if rec else None


# ==========================================================================
# Exportable report + report-to-PIB + signed share link
# ==========================================================================
def _esc(s: object) -> str:
    import html as _html

    return _html.escape(str(s if s is not None else ""))


def report_html(analysis_id: str, requester_id: str | None = None) -> str | None:
    a = repo.get_analysis(analysis_id, requester_id)
    if not a:
        return None
    claims = a.get("claims") or []
    rf = a.get("red_flags") or []
    rs = a.get("reasoning") or []
    rows = "".join(
        f"<tr><td>{_esc(c.get('claim_text'))}</td>"
        f"<td><b>{_esc(c.get('verdict'))}</b></td>"
        f"<td>{_esc(round((c.get('confidence') or 0)*100))}%</td>"
        f"<td>{_esc(c.get('notes'))}</td></tr>" for c in claims)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>CITADEL Fake-News Report {_esc(analysis_id)}</title>
<style>body{{font-family:'JetBrains Mono',monospace;background:#F2F0EB;
color:#111;margin:0;padding:32px}}h1{{font-family:'Chakra Petch',sans-serif}}
.box{{border:3px solid #000;box-shadow:6px 6px 0 #E63946;background:#fff;
padding:20px;margin-bottom:20px}}.v{{font-size:28px;font-weight:700}}
table{{width:100%;border-collapse:collapse}}td,th{{border:2px solid #000;
padding:8px;text-align:left;font-size:13px}}th{{background:#111;color:#fff}}
li{{margin:4px 0}}</style></head><body>
<h1>FAKE NEWS ANALYSIS REPORT</h1>
<div class="box"><div class="v">{_esc(a.get('verdict'))} &mdash;
confidence {_esc(round((a.get('confidence') or 0)*100))}%</div>
<div>Risk score: {_esc(a.get('risk_score'))} &middot; Analysis
{_esc(analysis_id)} &middot; {_esc(a.get('submitted_at'))}</div></div>
<div class="box"><h3>Input excerpt</h3><p>{_esc(a.get('input_excerpt'))}</p></div>
<div class="box"><h3>Claim-by-claim ({len(claims)})</h3><table>
<tr><th>Claim</th><th>Verdict</th><th>Conf</th><th>Notes</th></tr>
{rows or '<tr><td colspan=4>No check-worthy claims extracted.</td></tr>'}
</table></div>
<div class="box"><h3>Red flags</h3><ul>
{''.join(f'<li>&#9888; {_esc(f)}</li>' for f in rf) or '<li>None</li>'}
</ul></div>
<div class="box"><h3>Reasoning trace</h3><ol>
{''.join(f'<li>{_esc(s)}</li>' for s in rs)}</ol></div>
<div class="box" style="box-shadow:6px 6px 0 #888;font-size:11px">
Generated by CITADEL Fake News Detector. Verdicts are decision-support,
not legal determinations. Route low-confidence items to human review.
</div></body></html>"""


def report_pdf(analysis_id: str, requester_id: str | None = None) -> bytes | None:
    a = repo.get_analysis(analysis_id, requester_id)
    if not a:
        return None
    try:
        from fpdf import FPDF
    except Exception:  # noqa: BLE001
        return None

    def _t(x: object) -> str:
        return str(x if x is not None else "").encode(
            "latin-1", "replace").decode("latin-1")

    pdf = FPDF()
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()

    def line(txt: str, size: int = 10, bold: bool = False, gap: int = 5) -> None:
        # multi_cell with explicit effective-page-width + reset X avoids the
        # fpdf2 "not enough horizontal space" cursor trap.
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.epw, gap, _t(txt),
                       new_x="LMARGIN", new_y="NEXT")

    line("CITADEL - Fake News Analysis Report", 16, True, 9)
    line(f"Verdict: {a.get('verdict')}  "
         f"(confidence {round((a.get('confidence') or 0) * 100)}%)", 13, True, 8)
    line(f"Risk score: {a.get('risk_score')}", 10)
    line(f"Analysis id: {analysis_id}", 10)
    line(f"Submitted: {a.get('submitted_at')}", 10)
    pdf.ln(2)
    line("Input excerpt", 11, True, 6)
    line(a.get("input_excerpt") or "(none)", 9)
    pdf.ln(1)
    line(f"Claims ({len(a.get('claims') or [])})", 11, True, 6)
    for c in (a.get("claims") or []):
        line(f"[{c.get('verdict')}] {c.get('claim_text')} - {c.get('notes')}", 9)
    if not (a.get("claims") or []):
        line("No check-worthy claims extracted.", 9)
    pdf.ln(1)
    line("Red flags", 11, True, 6)
    for f in (a.get("red_flags") or []):
        line(f"- {f}", 9)
    if not (a.get("red_flags") or []):
        line("None", 9)
    pdf.ln(1)
    line("Reasoning trace", 11, True, 6)
    for s in (a.get("reasoning") or []):
        line(f"- {s}", 8)
    return bytes(pdf.output())


def report_to_pib(analysis_id: str, requester_id: str | None = None) -> dict:
    a = repo.get_analysis(analysis_id, requester_id)
    if not a:
        return {"ok": False, "error": "analysis not found"}
    repo.mark_reported(analysis_id)
    tg = {"sent": False}
    token = settings.TELEGRAM_BOT_TOKEN
    chat = settings.TELEGRAM_DEFAULT_CHAT_ID
    if token and chat:
        try:
            msg = (f"PIB FACT-CHECK REFERRAL\nVerdict: {a.get('verdict')} "
                   f"({round((a.get('confidence') or 0)*100)}%)\n"
                   f"Excerpt: {str(a.get('input_excerpt'))[:300]}\n"
                   f"Analysis: {analysis_id}")
            with httpx.Client(timeout=10) as _c:
                r = _c.post(
                    f"{settings.TELEGRAM_API_BASE}/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": msg})
            tg = {"sent": r.status_code == 200}
        except Exception as e:  # noqa: BLE001
            tg = {"sent": False, "error": str(e)[:160]}
    return {"ok": True, "reported": True, "telegram": tg}


def _share_secret() -> bytes:
    """App-specific signing key, derived one-way from the server secret.

    No guessable constant fallback (forgeable tokens) and never the raw
    service-role JWT itself — fail closed if the server secret is missing.
    """
    import hashlib

    base = settings.SUPABASE_SERVICE_ROLE_KEY
    if not base:
        raise RuntimeError("share signing unavailable: server secret unset")
    return hashlib.sha256(b"citadel-fn-share-v1|" + base.encode()).digest()


def make_share_token(analysis_id: str, ttl_days: int = 7) -> str:
    import base64
    import hmac

    import time as _t

    exp = int(_t.time()) + ttl_days * 86400
    payload = f"{analysis_id}.{exp}"
    sig = hmac.new(_share_secret(), payload.encode(), "sha256").hexdigest()
    raw = f"{payload}.{sig}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def verify_share_token(token: str) -> str | None:
    import base64
    import hmac
    import time as _t

    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode()
        analysis_id, exp, sig = raw.rsplit(".", 2)
        good = hmac.new(_share_secret(), f"{analysis_id}.{exp}".encode(),
                        "sha256").hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        if int(exp) < int(_t.time()):
            return None
        return analysis_id
    except Exception:  # noqa: BLE001
        return None


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
        try:
            d = drift.compute_drift()
            if d.get("drifted"):
                log.warning("CONCEPT DRIFT detected: %s", d.get("per_feature"))
        except Exception as e:  # noqa: BLE001
            log.debug("drift compute skipped: %s", e)
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

