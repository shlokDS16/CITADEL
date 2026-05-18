"""
Source-credibility knowledge base (spec-06 `source_credibility_db`).

A maintained reference table (allowlist / blocklist / score / bias lean),
seeded once with a curated, defensible list of Indian + global outlets and
fact-checkers. This is *reference data*, not a mock response — it is
officer-editable at runtime (`PUT /sources/{domain}`) exactly like the
Traffic module's `govt_fines_penalties`.

Everything degrades gracefully: no Supabase / missing table → lookups
return None and the waterfall falls back to the domain-age heuristic.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("citadel.fake_news.credibility")

_CACHE: dict[str, object] = {"ts": 0.0, "rows": None}
_TTL = 300.0          # credibility changes rarely; 5-min cache
_SEEDED = False

# Curated seed. trust_rating + score(0..100) + allow/block + optional lean.
# HIGH = wire/quality desk or official gov; fact-checkers flagged allowlist.
_SEED: list[dict] = [
    # Indian government / official
    {"domain": "pib.gov.in", "publisher_name": "Press Information Bureau", "trust_rating": "HIGH", "in_allowlist": True, "score": 95, "notes": "Official GoI"},
    {"domain": "factcheck.pib.gov.in", "publisher_name": "PIB Fact Check", "trust_rating": "HIGH", "in_allowlist": True, "score": 96, "notes": "Official GoI fact-check"},
    {"domain": "mygov.in", "publisher_name": "MyGov India", "trust_rating": "HIGH", "in_allowlist": True, "score": 92, "notes": "Official GoI"},
    {"domain": "rbi.org.in", "publisher_name": "Reserve Bank of India", "trust_rating": "HIGH", "in_allowlist": True, "score": 96, "notes": "Central bank"},
    # Indian independent fact-checkers
    {"domain": "boomlive.in", "publisher_name": "BOOM", "trust_rating": "HIGH", "in_allowlist": True, "score": 90, "notes": "IFCN-signatory fact-checker"},
    {"domain": "altnews.in", "publisher_name": "Alt News", "trust_rating": "HIGH", "in_allowlist": True, "score": 90, "notes": "IFCN-signatory fact-checker"},
    {"domain": "vishvasnews.com", "publisher_name": "Vishvas News", "trust_rating": "HIGH", "in_allowlist": True, "score": 88, "notes": "IFCN-signatory fact-checker"},
    {"domain": "factly.in", "publisher_name": "Factly", "trust_rating": "HIGH", "in_allowlist": True, "score": 88, "notes": "IFCN-signatory fact-checker"},
    {"domain": "newschecker.in", "publisher_name": "Newschecker", "trust_rating": "HIGH", "in_allowlist": True, "score": 87, "notes": "IFCN-signatory fact-checker"},
    {"domain": "thequint.com", "publisher_name": "The Quint (WebQoof)", "trust_rating": "MEDIUM", "in_allowlist": True, "score": 75, "bias_lean": "left", "notes": "Fact-check desk WebQoof"},
    # Global wire / quality
    {"domain": "reuters.com", "publisher_name": "Reuters", "trust_rating": "HIGH", "in_allowlist": True, "score": 95, "bias_lean": "center"},
    {"domain": "apnews.com", "publisher_name": "Associated Press", "trust_rating": "HIGH", "in_allowlist": True, "score": 95, "bias_lean": "center"},
    {"domain": "bbc.com", "publisher_name": "BBC News", "trust_rating": "HIGH", "in_allowlist": True, "score": 90, "bias_lean": "center"},
    {"domain": "bbc.co.uk", "publisher_name": "BBC News", "trust_rating": "HIGH", "in_allowlist": True, "score": 90, "bias_lean": "center"},
    {"domain": "afp.com", "publisher_name": "AFP", "trust_rating": "HIGH", "in_allowlist": True, "score": 93, "bias_lean": "center"},
    {"domain": "snopes.com", "publisher_name": "Snopes", "trust_rating": "HIGH", "in_allowlist": True, "score": 88},
    {"domain": "politifact.com", "publisher_name": "PolitiFact", "trust_rating": "HIGH", "in_allowlist": True, "score": 87},
    {"domain": "factcheck.org", "publisher_name": "FactCheck.org", "trust_rating": "HIGH", "in_allowlist": True, "score": 88},
    # Indian mainstream press (quality, varying lean)
    {"domain": "thehindu.com", "publisher_name": "The Hindu", "trust_rating": "HIGH", "in_allowlist": True, "score": 84, "bias_lean": "left"},
    {"domain": "indianexpress.com", "publisher_name": "The Indian Express", "trust_rating": "HIGH", "in_allowlist": True, "score": 83, "bias_lean": "center"},
    {"domain": "livemint.com", "publisher_name": "Mint", "trust_rating": "HIGH", "in_allowlist": True, "score": 82, "bias_lean": "center"},
    {"domain": "ndtv.com", "publisher_name": "NDTV", "trust_rating": "MEDIUM", "in_allowlist": True, "score": 76, "bias_lean": "left"},
    {"domain": "hindustantimes.com", "publisher_name": "Hindustan Times", "trust_rating": "MEDIUM", "in_allowlist": True, "score": 76, "bias_lean": "center"},
    {"domain": "timesofindia.indiatimes.com", "publisher_name": "Times of India", "trust_rating": "MEDIUM", "score": 70, "bias_lean": "center"},
    {"domain": "theprint.in", "publisher_name": "ThePrint", "trust_rating": "MEDIUM", "score": 74, "bias_lean": "center"},
    {"domain": "scroll.in", "publisher_name": "Scroll.in", "trust_rating": "MEDIUM", "score": 74, "bias_lean": "left"},
    # Known low-credibility / satire (treated as not-news; small illustrative set)
    {"domain": "theonion.com", "publisher_name": "The Onion (satire)", "trust_rating": "LOW", "in_blocklist": True, "score": 10, "notes": "Satire — not real news"},
    {"domain": "fakingnews.com", "publisher_name": "Faking News (satire)", "trust_rating": "LOW", "in_blocklist": True, "score": 10, "notes": "Satire"},
    {"domain": "postcard.news", "publisher_name": "Postcard News", "trust_rating": "LOW", "in_blocklist": True, "score": 12, "notes": "Repeatedly flagged for misinformation"},
]


def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable for credibility: %s", e)
        return None


def seed() -> dict:
    """Idempotent upsert of the curated seed (only inserts missing rows)."""
    global _SEEDED
    sb = _sb()
    if sb is None:
        return {"seeded": False, "reason": "no supabase"}
    inserted = 0
    try:
        existing = sb.table("source_credibility_db").select("domain").execute()
        have = {r["domain"] for r in (existing.data or [])}
        rows = [r for r in _SEED if r["domain"] not in have]
        if rows:
            sb.table("source_credibility_db").upsert(rows, on_conflict="domain").execute()
            inserted = len(rows)
        _SEEDED = True
        _CACHE["ts"] = 0.0
        return {"seeded": True, "inserted": inserted, "total_seed": len(_SEED)}
    except Exception as e:  # noqa: BLE001 — table may not exist yet
        log.warning("credibility seed skipped: %s", e)
        return {"seeded": False, "reason": str(e)}


def _rows() -> list[dict]:
    now = time.time()
    if _CACHE["rows"] is not None and now - float(_CACHE["ts"]) < _TTL:
        return _CACHE["rows"]  # type: ignore[return-value]
    sb = _sb()
    rows: list[dict] = []
    if sb is not None:
        try:
            rows = sb.table("source_credibility_db").select("*").execute().data or []
        except Exception as e:  # noqa: BLE001
            log.debug("credibility fetch failed: %s", e)
    _CACHE["rows"] = rows
    _CACHE["ts"] = now
    return rows


def _registrable(domain_or_url: str) -> str:
    try:
        import tldextract

        ext = tldextract.extract(domain_or_url)
        return ".".join(p for p in (ext.domain, ext.suffix) if p).lower()
    except Exception:  # noqa: BLE001
        return (domain_or_url or "").lower().strip()


def lookup(domain_or_url: str) -> dict | None:
    """Best-match KB row for a domain (exact registrable, else suffix match)."""
    if not domain_or_url:
        return None
    reg = _registrable(domain_or_url)
    rows = _rows()
    if not rows:
        return None
    by_domain = {r["domain"].lower(): r for r in rows}
    if reg in by_domain:
        return by_domain[reg]
    # subdomain / parent match (e.g. factcheck.pib.gov.in vs pib.gov.in)
    for d, r in by_domain.items():
        if reg.endswith("." + d) or d.endswith("." + reg):
            return r
    return None


def score_for(domain_or_url: str | None, domain_age_days: int | None) -> dict:
    """Authoritative credibility for a publisher: KB row first, else age heuristic."""
    reg = _registrable(domain_or_url) if domain_or_url else ""
    row = lookup(domain_or_url) if domain_or_url else None
    if row:
        score = int(row.get("score") or 50)
        rating = row.get("trust_rating") or ("HIGH" if score >= 70 else
                                             "MEDIUM" if score >= 40 else "LOW")
        return {
            "publisher": row.get("publisher_name") or reg or "unknown",
            "publisher_known": True,
            "domain_age_days": domain_age_days,
            "age_label": (f"Domain registered ~{domain_age_days // 365} year(s) ago"
                          if domain_age_days else ""),
            "score": score,
            "trust_rating": rating,
            "in_allowlist": bool(row.get("in_allowlist")),
            "in_blocklist": bool(row.get("in_blocklist")),
            "bias_lean": row.get("bias_lean"),
        }
    # not in KB → conservative age-based heuristic
    if domain_age_days is None:
        score, rating = 45, "MEDIUM"
        age_label = "Domain age unknown / publisher not in credibility list"
    elif domain_age_days < 30:
        score, rating = 18, "LOW"
        age_label = f"Domain registered {domain_age_days} days ago"
    elif domain_age_days < 365:
        score, rating = 40, "MEDIUM"
        age_label = f"Domain registered {domain_age_days} days ago"
    else:
        score, rating = 58, "MEDIUM"
        age_label = f"Domain registered ~{domain_age_days // 365} year(s) ago"
    return {
        "publisher": reg or "unknown", "publisher_known": False,
        "domain_age_days": domain_age_days, "age_label": age_label,
        "score": score, "trust_rating": rating,
        "in_allowlist": False, "in_blocklist": False, "bias_lean": None,
    }


def upsert(domain: str, fields: dict, reviewed_by: str | None = None) -> dict | None:
    """Officer edit of a credibility row (runtime-editable, like fines)."""
    sb = _sb()
    if sb is None:
        return None
    payload = {"domain": _registrable(domain), "reviewed_by": reviewed_by, **fields}
    sb.table("source_credibility_db").upsert(payload, on_conflict="domain").execute()
    _CACHE["ts"] = 0.0
    return lookup(domain)


def all_rows(limit: int = 500) -> list[dict]:
    return _rows()[:limit]
