"""
Layer 1 — lightweight heuristics, domain reputation, and hash matching.

Fast (sub-millisecond for the text part), pure-Python, zero ML. This is the
first stage of the production waterfall: it cheaply flags the obvious
(clickbait/urgency/emotional manipulation, suspicious domains, and exact or
near-duplicate matches against previously debunked content) so the expensive
transformer / LLM layers only run on what's actually ambiguous.

Nothing here raises — every failure degrades to a neutral signal.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

log = logging.getLogger("citadel.fake_news.heuristics")

# --------------------------------------------------------------------------
# Lexicons / patterns. Kept as module constants (no inline magic).
# --------------------------------------------------------------------------
_URGENCY = [
    "act now", "before it", "before its", "before it's", "share before",
    "forward this", "forward to", "share with everyone", "share immediately",
    "don't ignore", "do not ignore", "urgent", "breaking", "last chance",
    "limited time", "expires today", "only today", "hurry", "deadline",
    "share now", "spread the word", "must read", "delete soon",
]
_CLICKBAIT = [
    "you won't believe", "you wont believe", "what happened next",
    "doctors hate", "this one trick", "will shock you", "shocking",
    "gone wrong", "the truth about", "they don't want you to know",
    "they dont want you to know", "no one is talking about", "exposed",
    "secret", "miracle", "mind blowing", "jaw dropping", "this is why",
    "number will surprise", "changed forever", "instant",
]
_EMOTIONAL = [
    "outrage", "outrageous", "disgusting", "shameful", "terrifying",
    "horrific", "devastating", "catastrophe", "panic", "fear", "danger",
    "threat", "destroy", "destroyed", "betray", "betrayal", "scandal",
    "corrupt", "evil", "lie", "lies", "fraud", "hoax", "exposed", "slammed",
    "blasted", "furious", "chaos", "crisis", "alarming",
]
_AUTHORITY_VAGUE = [
    "experts say", "experts warn", "scientists say", "scientists confirm",
    "studies show", "research shows", "doctors say", "doctors warn",
    "sources say", "sources claim", "officials say", "officials confirm",
    "reports say", "it is said", "according to reports", "insiders say",
    "a study found", "analysts predict",
]
_CONSPIRACY = [
    "wake up", "mainstream media won't", "mainstream media wont",
    "msm won't", "they are hiding", "the truth is being", "cover up",
    "cover-up", "what they don't want", "do your own research",
    "open your eyes", "sheeple", "plandemic", "false flag",
]
_FINANCIAL_LURE = [
    "free", "giveaway", "lottery", "winner", "won", "prize", "cash reward",
    "claim now", "claim your", "register now to get", "100% free",
    "earn money", "double your", "guaranteed income", "work from home",
]
_PHISHING_ACTION = [
    "click here", "click the link", "click below", "register at",
    "verify your account", "update your details", "kyc update",
    "link in bio", "dm to claim", "whatsapp this number", "otp",
    "share your aadhaar", "share your pan", "bank details",
]
_SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd",
    "buff.ly", "rebrand.ly", "cutt.ly", "shorturl.at", "rb.gy",
}
# TLDs over-represented in spam / disinfo (weight = risk contribution).
_SUSPICIOUS_TLD = {
    "info": 0.15, "xyz": 0.25, "top": 0.25, "live": 0.15, "click": 0.35,
    "buzz": 0.3, "online": 0.15, "site": 0.15, "fun": 0.3, "icu": 0.35,
    "rest": 0.3, "cfd": 0.4, "sbs": 0.35, "monster": 0.4, "loan": 0.4,
}

# Unicode-aware: [^\W\d_] = any letter in any script (Latin, Devanagari, …)
# but not digits/underscore. Danda (U+0964) added via chr() so there are no
# non-ASCII glyphs in this source file.
_WORD_RE = re.compile(r"[^\W\d_]+")
_SENT_RE = re.compile("[.!?" + chr(0x0964) + r"]+\s+|\n+")
_URL_RE = re.compile(r"https?://[^\s]+", re.I)
_CAPS_RE = re.compile(r"\b[A-Z]{3,}\b")

# scoring weights / thresholds
_W_OBFUSCATION = 0.18
_W_MANIPULATION = 0.34
_W_DOMAIN = 0.22
_W_LURE = 0.14
_W_PHISH = 0.20
_DEBUNK_HAMMING = 6          # simhash distance for "near-duplicate"
_RDAP_TIMEOUT = 5.0
_YOUNG_DOMAIN_DAYS = 90


@dataclass
class HeuristicResult:
    red_flags: list[str] = field(default_factory=list)
    manipulation: dict[str, int] = field(default_factory=dict)   # 0..100 each
    metrics: dict[str, float] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    domain: dict | None = None
    hashes: dict[str, str] = field(default_factory=dict)
    debunked_match: dict | None = None
    l1_risk: float = 0.0          # 0..1 — L1's contribution to overall risk


# --------------------------------------------------------------------------
# Text metrics + manipulation profile
# --------------------------------------------------------------------------
def _count_phrases(haystack: str, phrases: list[str]) -> tuple[int, list[str]]:
    hits = [p for p in phrases if p in haystack]
    return len(hits), hits


def _text_metrics(text: str) -> dict[str, float]:
    words = _WORD_RE.findall(text)
    n_words = len(words)
    caps = _CAPS_RE.findall(text)
    sentences = [s for s in _SENT_RE.split(text) if s.strip()]
    excl = text.count("!")
    return {
        "word_count": float(n_words),
        "sentence_count": float(max(1, len(sentences))),
        "caps_word_ratio": round(len(caps) / n_words, 4) if n_words else 0.0,
        "exclamation_count": float(excl),
        "exclamation_density": round(excl / n_words, 4) if n_words else 0.0,
        "question_count": float(text.count("?")),
    }


def _scale(hits: int, per_hit: int, bonus: float = 0.0) -> int:
    return int(max(0.0, min(100.0, hits * per_hit + bonus)))


def _manipulation_profile(low: str, metrics: dict[str, float]) -> tuple[dict[str, int], list[str]]:
    flags: list[str] = []
    caps_ratio = metrics["caps_word_ratio"]
    excl = metrics["exclamation_count"]

    cb_n, cb_hits = _count_phrases(low, _CLICKBAIT)
    ur_n, ur_hits = _count_phrases(low, _URGENCY)
    au_n, au_hits = _count_phrases(low, _AUTHORITY_VAGUE)
    em_n, _ = _count_phrases(low, _EMOTIONAL)
    co_n, _ = _count_phrases(low, _CONSPIRACY)

    clickbait = _scale(cb_n, 26, bonus=caps_ratio * 60)
    urgency = _scale(ur_n, 24, bonus=min(30.0, excl * 6))
    authority = _scale(au_n, 30)
    emotional = _scale(em_n + co_n, 18, bonus=caps_ratio * 40)

    if caps_ratio > 0.18:
        flags.append("Excessive ALL-CAPS — common in sensational misinformation")
    if excl >= 3:
        flags.append(f"Excessive exclamation marks ({int(excl)})")
    if cb_hits:
        flags.append(f"Clickbait phrasing: \"{cb_hits[0]}\"")
    if ur_hits:
        flags.append(f"Urgency / call-to-share pressure: \"{ur_hits[0]}\"")
    if au_hits:
        flags.append(f"Vague authority with no named source: \"{au_hits[0]}\"")
    if co_n:
        flags.append("Conspiracy framing detected")
    if em_n >= 3:
        flags.append("Heavy emotional / fear language")

    return (
        {"clickbait": clickbait, "urgency": urgency,
         "authority_claim": authority, "emotional": emotional},
        flags,
    )


# --------------------------------------------------------------------------
# Domain reputation (keyless RDAP)
# --------------------------------------------------------------------------
@lru_cache(maxsize=512)
def _rdap_age_days(domain: str) -> int | None:
    """Registered-age in days via the free, keyless rdap.org. None on failure."""
    import datetime as _dt

    try:
        r = httpx.get(f"https://rdap.org/domain/{domain}",
                       timeout=_RDAP_TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            return None
        for ev in r.json().get("events", []):
            if ev.get("eventAction") == "registration":
                reg = _dt.datetime.fromisoformat(
                    ev["eventDate"].replace("Z", "+00:00"))
                now = _dt.datetime.now(_dt.timezone.utc)
                return max(0, (now - reg).days)
    except Exception as e:  # noqa: BLE001
        log.debug("RDAP lookup failed for %s: %s", domain, e)
    return None


def domain_signals(url: str | None, text: str) -> dict | None:
    """Reputation signals for the publishing domain (URL mode or in-text link)."""
    target = url
    if not target:
        m = _URL_RE.search(text)
        target = m.group(0) if m else None
    if not target:
        return None

    try:
        import tldextract

        ext = tldextract.extract(target)
        registrable = ".".join(p for p in (ext.domain, ext.suffix) if p)
        suffix = ext.suffix or ""
    except Exception:  # noqa: BLE001
        registrable, suffix = "", ""

    signals: list[str] = []
    risk = 0.0
    last_tld = suffix.split(".")[-1] if suffix else ""
    if last_tld in _SUSPICIOUS_TLD:
        risk += _SUSPICIOUS_TLD[last_tld]
        signals.append(f"suspicious_tld:.{last_tld}")
    if registrable in _SHORTENERS:
        risk += 0.25
        signals.append("url_shortener")

    age_days = _rdap_age_days(registrable) if registrable else None
    if age_days is None:
        age_label = "Domain age unknown (registry did not respond)"
    elif age_days < _YOUNG_DOMAIN_DAYS:
        age_label = f"Domain registered {age_days} days ago"
        risk += 0.3 if age_days < 30 else 0.18
        signals.append(f"young_domain:{age_days}d")
    else:
        years = age_days // 365
        age_label = (f"Domain registered ~{years} year(s) ago"
                     if years else f"Domain registered {age_days} days ago")

    is_gov = registrable.endswith(".gov.in") or registrable.endswith(".nic.in") \
        or suffix in ("gov.in", "nic.in", "gov")
    if is_gov:
        signals.append("official_gov_domain")

    return {
        "publisher": registrable or target,
        "tld": last_tld,
        "domain_age_days": age_days,
        "age_label": age_label,
        "official_gov": is_gov,
        "signals": signals,
        "risk": round(min(1.0, risk), 4),
    }


# --------------------------------------------------------------------------
# Hashing — exact (sha256) + near-duplicate (simhash)
# --------------------------------------------------------------------------
def content_sha256(match_variant: str) -> str:
    return hashlib.sha256(match_variant.strip().encode("utf-8")).hexdigest()


def simhash64(text: str) -> int:
    """64-bit SimHash over token bigrams — robust to small edits/reordering."""
    toks = _WORD_RE.findall(text.lower())
    if not toks:
        return 0
    shingles = toks if len(toks) < 2 else [
        f"{a}_{b}" for a, b in zip(toks, toks[1:])
    ]
    vec = [0] * 64
    for sh in shingles:
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            vec[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(64):
        if vec[i] > 0:
            out |= 1 << i
    return out


def hamming64(a: int, b: int) -> int:
    return bin((a ^ b) & ((1 << 64) - 1)).count("1")


# SimHash is an unsigned 64-bit value; Postgres `bigint` is signed 64-bit
# (max ~9.2e18) so storing the raw unsigned form overflows. Map via lossless
# two's-complement at the DB boundary, reinterpret on read.
def to_signed64(u: int) -> int:
    return u - (1 << 64) if u >= (1 << 63) else u


def to_unsigned64(s: int) -> int:
    return s + (1 << 64) if s < 0 else s


def match_debunked(sha: str, sim: int, supabase) -> dict | None:  # noqa: ANN001
    """Exact or near-duplicate match against the fn_debunked store.

    `supabase` is a service-role client or None. Missing table / no client
    → returns None (graceful degrade — Phase 4 hardens persistence).
    """
    if supabase is None:
        return None
    try:
        exact = (supabase.table("fn_debunked")
                 .select("*").eq("content_sha256", sha).limit(1).execute())
        if exact.data:
            row = exact.data[0]
            return {"kind": "exact", "claim_text": row.get("claim_text"),
                    "canonical_verdict": row.get("canonical_verdict", "FAKE"),
                    "source_url": row.get("source_url"), "distance": 0}
        rows = (supabase.table("fn_debunked")
                .select("simhash,claim_text,canonical_verdict,source_url")
                .not_.is_("simhash", "null").limit(2000).execute()).data or []
        best, best_d = None, _DEBUNK_HAMMING + 1
        for r in rows:
            sv = r.get("simhash")
            if sv is None:
                continue
            d = hamming64(sim, to_unsigned64(int(sv)))
            if d < best_d:
                best, best_d = r, d
        if best is not None and best_d <= _DEBUNK_HAMMING:
            return {"kind": "near_duplicate", "claim_text": best.get("claim_text"),
                    "canonical_verdict": best.get("canonical_verdict", "FAKE"),
                    "source_url": best.get("source_url"), "distance": best_d}
    except Exception as e:  # noqa: BLE001 — table absent / transient
        log.debug("debunked match unavailable: %s", e)
    return None


# --------------------------------------------------------------------------
# Aggregate
# --------------------------------------------------------------------------
def analyze(
    *,
    original: str,
    normalized: str,
    match_variant: str,
    obfuscation_score: float,
    obfuscation_signals: list[str],
    url: str | None,
    supabase=None,  # noqa: ANN001
) -> HeuristicResult:
    """Run the full L1 pass and produce its risk contribution + red flags."""
    low = (normalized or original).lower()
    metrics = _text_metrics(original)
    manipulation, mflags = _manipulation_profile(low, metrics)

    red_flags = list(mflags)
    signals: list[str] = list(obfuscation_signals)

    lure_n, lure_hits = _count_phrases(low, _FINANCIAL_LURE)
    phish_n, phish_hits = _count_phrases(low, _PHISHING_ACTION)
    if lure_n >= 2:
        red_flags.append("Financial lure pattern (free / prize / claim now)")
        signals.append(f"financial_lure:{lure_n}")
    if phish_hits:
        red_flags.append(f"Phishing-style call to action: \"{phish_hits[0]}\"")
        signals.append(f"phishing_action:{phish_n}")
    if obfuscation_signals:
        red_flags.append("Text deliberately obfuscated to evade filters")

    dom = domain_signals(url, original)
    if dom and dom["signals"]:
        for s in dom["signals"]:
            if s.startswith("young_domain"):
                red_flags.append(dom["age_label"])
            elif s.startswith("suspicious_tld"):
                red_flags.append(f"Low-reputation domain (.{dom['tld']})")
            elif s == "url_shortener":
                red_flags.append("Link hidden behind a URL shortener")

    sha = content_sha256(match_variant or normalized or original)
    sim = simhash64(match_variant or normalized or original)
    debunked = match_debunked(sha, sim, supabase)
    if debunked:
        red_flags.insert(0, (
            "Matches previously debunked content"
            + (" (exact)" if debunked["kind"] == "exact" else
               f" (near-duplicate, distance {debunked['distance']})")
        ))
        signals.append(f"debunked_{debunked['kind']}")

    # Peak-driven (not mean): one maxed manipulation dimension is a strong
    # signal that mean-averaging would wrongly dilute. Breadth adds a little
    # when several independent manipulation types co-occur.
    dom_risk = dom["risk"] if dom else 0.0
    manip_peak = max(manipulation.values()) / 100.0
    manip_breadth = sum(1 for v in manipulation.values() if v >= 40) / len(manipulation)
    lure_risk = min(1.0, lure_n / 3.0)
    phish_risk = min(1.0, phish_n / 2.0)

    l1_risk = (
        _W_OBFUSCATION * obfuscation_score
        + _W_MANIPULATION * (0.7 * manip_peak + 0.3 * manip_breadth)
        + _W_DOMAIN * dom_risk
        + _W_LURE * lure_risk
        + _W_PHISH * phish_risk
    )
    # Classic scam triad: urgency + financial lure + phishing CTA together is
    # a near-certain scam pattern (high precision) — boost so it routes right.
    if manipulation["urgency"] >= 60 and lure_n >= 2 and phish_n >= 1:
        l1_risk += 0.28
        signals.append("scam_triad")
        red_flags.append("Classic scam pattern: urgency + money lure + action link")
    if debunked:
        l1_risk = max(l1_risk, 0.97 if debunked["kind"] == "exact" else 0.9)
    l1_risk = round(min(1.0, l1_risk), 4)

    return HeuristicResult(
        red_flags=red_flags,
        manipulation=manipulation,
        metrics=metrics,
        signals=signals,
        domain=dom,
        hashes={"sha256": sha, "simhash": str(sim)},
        debunked_match=debunked,
        l1_risk=l1_risk,
    )
