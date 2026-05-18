"""
Layer 3 — RAG fact verification.

Pipeline per check:
  1. extract check-worthy claims (spaCy en_core_web_sm — already installed)
  2. gather evidence per claim, strongest source first:
       Google Fact Check Tools API (human ClaimReviews)  ->
       stored fact_check_feed (PIB/Boom/AltNews/Factly)   ->
       keyless web (reuse citizen_assistant.web_search)    ->
       Wikipedia REST summary
  3. score evidence vs claim with the DeBERTa-v3 NLI head
     (entailment = supports, contradiction = refutes)
  4. fuse into a per-claim verdict + supporting/contradicting sources

Zero LLM tokens here (NLI is local; web/Wikipedia keyless; Google FC is a
free keyed quota). The LLM rationale layer is Phase 4, high-risk only.
Every external call is bounded and never raises.
"""
from __future__ import annotations

import html
import logging
import re
import uuid
from functools import lru_cache

import httpx

from app.config import settings
from app.modules.fake_news import pipeline as ml

log = logging.getLogger("citadel.fake_news.fact_check")

_GOOGLE_FC = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
_WIKI = "https://en.wikipedia.org/w/rest.php/v1/search/page"
_HTTP_TIMEOUT = 8.0
_MAX_CLAIMS = 4
_MAX_EVIDENCE = 5
_NLI_MIN = 0.60
_ASSERTIVE = {
    "say", "claim", "announce", "confirm", "report", "reveal", "find",
    "show", "prove", "cause", "kill", "ban", "launch", "approve", "warn",
    "die", "arrest", "win", "lose", "rise", "fall", "increase", "decrease",
}
_TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------
# Claim extraction
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _nlp():  # noqa: ANN202
    import spacy

    log.info("loading spaCy en_core_web_sm for claim extraction")
    return spacy.load("en_core_web_sm", disable=["lemmatizer"])


def extract_claims(text: str, max_claims: int = _MAX_CLAIMS) -> list[str]:
    """Pick the most check-worthy declarative sentences (entities/numbers)."""
    text = (text or "").strip()
    if not text:
        return []
    try:
        doc = _nlp()(text[:6000])
        sents = list(doc.sents)
    except Exception as e:  # noqa: BLE001
        log.warning("spaCy claim extraction failed (%s); sentence-split fallback", e)
        sents = []  # type: ignore[assignment]
    cands: list[tuple[int, str]] = []
    if sents:
        for sent in sents:
            s = sent.text.strip()
            wc = len(s.split())
            if wc < 5 or wc > 60 or s.endswith("?"):
                continue
            if not any(t.pos_ == "VERB" or t.pos_ == "AUX" for t in sent):
                continue
            ents = list(sent.ents)
            has_num = any(
                t.like_num or t.ent_type_ in
                ("PERCENT", "MONEY", "QUANTITY", "CARDINAL", "DATE", "TIME")
                for t in sent)
            assertive = any(t.pos_ == "VERB" and t.text.lower() in _ASSERTIVE
                            for t in sent)
            score = len(ents) * 2 + (2 if has_num else 0) + (1 if assertive else 0)
            if score <= 0 and not ents:
                continue
            cands.append((score, s))
    if not cands:  # crude fallback so we always check *something*
        parts = re.split(r"(?<=[.!?])\s+", text)
        cands = [(1, p.strip()) for p in parts if 5 <= len(p.split()) <= 60][:max_claims]
        if not cands:
            cands = [(1, text[:240])]
    cands.sort(key=lambda x: -x[0])
    out: list[str] = []
    for _, s in cands:
        if s not in out:
            out.append(s)
        if len(out) >= max_claims:
            break
    return out


# --------------------------------------------------------------------------
# Evidence sources
# --------------------------------------------------------------------------
def _rating_stance(rating: str) -> str:
    r = (rating or "").lower()
    if any(x in r for x in ("false", "pants on fire", "incorrect", "fake",
                            "hoax", "fabricat", "misleading", "no evidence",
                            "debunk", "not true", "distorted")):
        return "contradict"
    if any(x in r for x in ("true", "correct", "accurate", "verified", "legit")):
        return "support"
    return "neutral"


def _google_factcheck(query: str) -> list[dict]:
    key = settings.GOOGLE_FACTCHECK_API_KEY
    if not key:
        return []
    try:
        r = httpx.get(_GOOGLE_FC, params={"query": query[:300],
                      "languageCode": "en", "key": key, "pageSize": 5},
                      timeout=_HTTP_TIMEOUT)
        if r.status_code != 200:
            return []
        out: list[dict] = []
        for c in r.json().get("claims", []):
            reviews = c.get("claimReview") or []
            if not reviews:
                continue
            rv = reviews[0]
            rating = rv.get("textualRating", "")
            out.append({
                "title": rv.get("title") or c.get("text", "")[:120],
                "url": rv.get("url", ""),
                "publisher": (rv.get("publisher") or {}).get("name", "fact-checker"),
                "snippet": f"Claim: {c.get('text', '')[:200]} — Rating: {rating}",
                "stance": _rating_stance(rating),
                "rating": rating,
                "source_type": "factcheck",
                "published_at": rv.get("reviewDate"),
            })
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("google factcheck failed: %s", e)
        return []


def _feed_matches(query: str) -> list[dict]:
    try:
        from app.database import get_supabase

        sb = get_supabase()
    except Exception:  # noqa: BLE001
        return []
    try:
        kws = [w for w in re.findall(r"[A-Za-z]{4,}", query.lower())][:4]
        if not kws:
            return []
        res = (sb.table("fact_check_feed")
               .select("title,url,publisher,body_excerpt,published_at")
               .ilike("title", f"%{kws[0]}%").limit(4).execute())
        out = []
        for row in (res.data or []):
            out.append({
                "title": row.get("title", ""), "url": row.get("url", ""),
                "publisher": row.get("publisher", "fact-check feed"),
                "snippet": (row.get("body_excerpt") or row.get("title") or "")[:300],
                "stance": "contradict",   # feed is a debunk corpus
                "source_type": "factcheck",
                "published_at": row.get("published_at"),
            })
        return out
    except Exception as e:  # noqa: BLE001 — table may be absent
        log.debug("feed match failed: %s", e)
        return []


def _wikipedia(query: str) -> list[dict]:
    try:
        r = httpx.get(_WIKI, params={"q": query[:280], "limit": 3},
                      timeout=_HTTP_TIMEOUT,
                      headers={"User-Agent": "CitadelFakeNews/1.0"})
        if r.status_code != 200:
            return []
        out = []
        for p in r.json().get("pages", []):
            excerpt = html.unescape(_TAG_RE.sub("", p.get("excerpt", "")))
            if not excerpt:
                continue
            out.append({
                "title": p.get("title", ""),
                "url": f"https://en.wikipedia.org/wiki/{p.get('key', '')}",
                "publisher": "Wikipedia",
                "snippet": (p.get("description") or "") + " " + excerpt,
                "stance": None, "source_type": "context",
            })
        return out
    except Exception as e:  # noqa: BLE001
        log.debug("wikipedia failed: %s", e)
        return []


def _web(query: str) -> list[dict]:
    try:
        from app.modules.citizen_assistant import web_search

        res = web_search.search(query, max_results=4) or []
        return [{
            "title": x.get("title", ""), "url": x.get("url", ""),
            "publisher": _domain(x.get("url", "")),
            "snippet": x.get("snippet", ""),
            "stance": None, "source_type": "web",
        } for x in res if x.get("snippet")]
    except Exception as e:  # noqa: BLE001
        log.debug("web search failed: %s", e)
        return []


def _domain(url: str) -> str:
    try:
        import tldextract

        e = tldextract.extract(url)
        return ".".join(p for p in (e.domain, e.suffix) if p)
    except Exception:  # noqa: BLE001
        return ""


def _dedupe(items: list[dict], limit: int) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = (it.get("url") or it.get("title") or it.get("snippet", ""))[:120]
        if key and key in seen:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= limit:
            break
    return out


def gather_evidence(claim: str) -> list[dict]:
    """Strongest source first; bounded."""
    ev = _google_factcheck(claim) + _feed_matches(claim)
    if len(ev) < _MAX_EVIDENCE:
        ev += _wikipedia(claim)
    if len(ev) < _MAX_EVIDENCE:
        ev += _web(claim)
    return _dedupe(ev, _MAX_EVIDENCE + 2)


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
def _src(e: dict, stance: str | None) -> dict:
    return {"title": e.get("title") or "", "url": e.get("url") or None,
            "publisher": e.get("publisher") or None,
            "snippet": (e.get("snippet") or "")[:300],
            "stance": stance or "neutral"}


def verify_claim(claim: str) -> dict:
    """Return a ClaimAnalysis-shaped dict for one claim."""
    ev = gather_evidence(claim)
    supporting: list[dict] = []
    contradicting: list[dict] = []
    fc_false = fc_true = False
    nli_labels: list[str] = []

    for e in ev:
        if e.get("source_type") == "factcheck" and e.get("stance") in (
                "contradict", "support"):
            if e["stance"] == "contradict":
                contradicting.append(_src(e, "contradict"))
                fc_false = True
            else:
                supporting.append(_src(e, "support"))
                fc_true = True
            continue
        snip = (e.get("snippet") or e.get("title") or "").strip()
        if len(snip) < 15:
            continue
        r = ml.nli(snip, claim)
        if not r.get("available"):
            continue
        nli_labels.append(r["label"])
        if r["label"] == "entailment" and r["entailment"] >= _NLI_MIN:
            supporting.append(_src(e, "support"))
        elif r["label"] == "contradiction" and r["contradiction"] >= _NLI_MIN:
            contradicting.append(_src(e, "contradict"))

    ns, nc = len(supporting), len(contradicting)
    if fc_false:
        verdict, conf = "FALSE", 0.93
        notes = "A credible fact-checker has rated this claim false."
    elif fc_true and nc == 0:
        verdict, conf = "TRUE", 0.88
        notes = "Corroborated by a credible fact-checker."
    elif nc >= 2 and ns == 0:
        verdict, conf = "FALSE", 0.78
        notes = f"{nc} independent sources contradict this claim."
    elif ns >= 2 and nc == 0:
        verdict, conf = "TRUE", 0.82
        notes = f"{ns} independent sources support this claim."
    elif ns and nc:
        verdict, conf = "MISLEADING", 0.6
        notes = f"Disputed — {ns} support, {nc} contradict."
    elif nc and not ns:
        verdict, conf = "SUSPICIOUS", 0.58
        notes = "Some evidence contradicts; not conclusively debunked."
    elif not ev:
        verdict, conf = "UNVERIFIED", 0.5
        notes = "No corroborating or contradicting evidence found online."
    else:
        verdict, conf = "UNVERIFIED", 0.5
        notes = "Evidence found but it neither clearly supports nor refutes."

    dominant = max(set(nli_labels), key=nli_labels.count) if nli_labels else None
    return {
        "id": str(uuid.uuid4()), "text": claim, "verdict": verdict,
        "confidence": round(conf, 4), "notes": notes,
        "nli_label": dominant,
        "supporting_evidence": supporting[:4],
        "contradicting_evidence": contradicting[:4],
    }


def search(query: str) -> list[dict]:
    """RelatedFactCheck-shaped results for the /related-fact-checks endpoint."""
    out = [{
        "title": e.get("title") or e.get("publisher") or "fact-check",
        "publisher": e.get("publisher") or "fact-checker",
        "url": e.get("url") or "",
        "published_at": e.get("published_at"),
        "matched_claim_ids": [],
    } for e in (_google_factcheck(query) + _feed_matches(query))]
    return [r for r in _dedupe(out, 12) if r["url"]]


def analyze_claims(text: str, max_claims: int = _MAX_CLAIMS) -> dict:
    """Extract + verify claims; collect related fact-checks. Never raises."""
    try:
        claims = extract_claims(text, max_claims)
    except Exception as e:  # noqa: BLE001
        log.warning("claim extraction failed: %s", e)
        claims = []
    results = [verify_claim(c) for c in claims]

    related: list[dict] = []
    seen: set[str] = set()
    for res in results:
        for ev in res["supporting_evidence"] + res["contradicting_evidence"]:
            url = ev.get("url")
            if url and url not in seen and ev.get("publisher"):
                seen.add(url)
                related.append({
                    "title": ev.get("title") or ev.get("publisher"),
                    "publisher": ev.get("publisher"),
                    "url": url, "published_at": None,
                    "matched_claim_ids": [res["id"]],
                })
    return {"claims": results, "related_fact_checks": related[:8]}
