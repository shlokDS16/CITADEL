"""
Ticket classification: category → department → priority → SLA + sentiment.

Design (user decision, 2026-07-20): **Groq-first, rule-router fallback.**

  1. PII is stripped from the text *before* anything sees it.
     .claude/rules/ml-conventions.md: "Ticket priority must not learn from
     sender name". So names, phones, emails and ids are redacted first —
     for the LLM path this also means PII never leaves the process.
  2. Groq classifies the category with a constrained JSON response.
     Only the category comes from the LLM; department, priority and SLA
     come from the `routing_rules` table so a hallucinated department is
     structurally impossible.
  3. If Groq is unconfigured, errors, rate-limits, or returns a category
     outside the fixed set, the keyword rule router answers instead and
     the response says `source: "rules"`. It is never silently presented
     as an LLM result.

Sentiment is VADER (local, free, deterministic) and is used as an urgency
signal that can escalate priority — never de-escalate it.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from app.config import settings
from app.modules.tickets import repo, schemas

log = logging.getLogger("citadel.tickets.pipeline")

_PRIORITY_ORDER = ("LOW", "NORMAL", "HIGH", "CRITICAL")

# Hazard/urgency words that justify bumping priority one step.
# Deliberately excludes bare landmark nouns (school, hospital, child) —
# civic complaints mention those constantly as *locations*, and treating
# "garbage outside the school gate" as urgent made almost everything HIGH.
# Those live in _VULNERABLE_TERMS and only count alongside a real hazard.
_URGENCY_TERMS = {
    "emergency", "urgent", "immediately", "danger", "dangerous", "unsafe",
    "hazard", "flood", "accident", "injury", "injured", "sewage",
    "outbreak", "epidemic", "attack", "attacked", "bitten", "overflowing",
}

# Life-safety terms. These — and only these — can produce CRITICAL.
_CRITICAL_TERMS = {
    "fire", "collapse", "collapsed", "electrocut", "live wire", "gas leak",
    "death", "died", "drowning", "explosion", "gunshot",
}

# Presence of a vulnerable population escalates only when a hazard or
# urgency term is *also* present — a landmark alone is not an emergency.
_VULNERABLE_TERMS = {
    "child", "children", "school", "hospital", "elderly", "infant",
    "playground", "clinic",
}

# Civic complaints are negative by nature, so ordinary negativity carries
# no signal. Only an outlier ("terrible", "disgusting", repeated anger)
# clears this bar, and it can never push a ticket to CRITICAL — that is
# reserved for explicit life-safety cues.
_SENTIMENT_ESCALATION_THRESHOLD = -0.75

# --------------------------------------------------------------------------
# PII redaction — runs before classification, always.
# --------------------------------------------------------------------------
_RE_EMAIL = re.compile(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_RE_PHONE = re.compile(r"\b(?:\+?91[-\s]?)?[6-9]\d{9}\b")
_RE_AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
_RE_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_RE_MYNAME = re.compile(
    r"\b(?:my name is|i am|this is|name[:\-]\s*)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?",
    re.IGNORECASE,
)


def redact_pii(text: str) -> str:
    """Strip PII before the text reaches any classifier or the LLM.

    Deliberately aggressive: a false positive costs a little classification
    signal, a false negative leaks a citizen's identity to a third party.
    """
    if not text:
        return ""
    out = _RE_EMAIL.sub("[EMAIL]", text)
    out = _RE_AADHAAR.sub("[ID]", out)
    out = _RE_PAN.sub("[ID]", out)
    out = _RE_PHONE.sub("[PHONE]", out)
    out = _RE_MYNAME.sub("[NAME]", out)
    return out


# --------------------------------------------------------------------------
# Sentiment (VADER, local)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _vader():  # noqa: ANN202
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

        return SentimentIntensityAnalyzer()
    except Exception as e:  # noqa: BLE001
        log.warning("VADER unavailable: %s", e)
        return None


def vader_available() -> bool:
    return _vader() is not None


def sentiment_of(text: str) -> tuple[str, float]:
    """Return (label, compound). Neutral when VADER is unavailable."""
    an = _vader()
    if an is None or not text:
        return "neutral", 0.0
    compound = float(an.polarity_scores(text).get("compound", 0.0))
    if compound <= -0.35:
        return "negative", compound
    if compound >= 0.35:
        return "positive", compound
    return "neutral", compound


# --------------------------------------------------------------------------
# Rule router — the fallback, and the source of dept/priority/SLA always
# --------------------------------------------------------------------------
def _rules_by_category() -> dict[str, dict[str, Any]]:
    return {r["category"]: r for r in repo.routing_rules() if r.get("category")}


@lru_cache(maxsize=512)
def _kw_pattern(keyword: str) -> re.Pattern[str]:
    r"""Word-boundary-anchored matcher for a routing keyword.

    Plain substring matching was badly wrong: "tree" matched inside
    "s-tree-tlight" and "park" inside "sparking", so a streetlight fault on
    Park Lane scored two phantom Parks hits and out-voted the one real
    Electric hit.

    The boundary is on the *start* only, so a keyword still matches its
    inflections ("build" → "building", "park" → "parking") without
    matching mid-word noise. Multi-word keywords ("live wire") work too.
    """
    return re.compile(r"\b" + re.escape(keyword.lower()), re.IGNORECASE)


def rule_category(text: str, rules: dict[str, dict[str, Any]]) -> tuple[Optional[str], float, list[str]]:
    """Keyword-score the text against routing_rules.

    Returns (category | None, confidence 0..1, matched keywords).
    None means no keyword matched — the caller decides what to do rather
    than being handed a fabricated guess.

    Ties are broken by routing_rules order (category ascending), which is
    stable and deterministic rather than dict-insertion luck.
    """
    body = text or ""
    best: Optional[str] = None
    best_hits: list[str] = []
    for cat, rule in rules.items():
        kws = rule.get("keywords") or []
        if isinstance(kws, str):
            try:
                kws = json.loads(kws)
            except Exception:  # noqa: BLE001
                kws = []
        hits = [k for k in kws if k and _kw_pattern(k).search(body)]
        if len(hits) > len(best_hits):
            best, best_hits = cat, hits
    if not best:
        return None, 0.0, []
    # 1 hit ≈ 0.55, 2 ≈ 0.7, 3+ ≈ 0.85 — honest about being a keyword match
    conf = min(0.4 + 0.15 * len(best_hits), 0.85)
    return best, round(conf, 2), best_hits


# --------------------------------------------------------------------------
# Groq classification
# --------------------------------------------------------------------------
class QuotaExhausted(RuntimeError):
    """Groq returned 429. Distinct from a generic failure so the response
    can say so honestly instead of pretending the rules were the plan."""


_SYSTEM_PROMPT = (
    "You classify municipal civic complaints for an Indian city. "
    "Reply with ONLY a JSON object, no prose, no markdown fence.\n"
    'Format: {"category": "<one of the allowed values>", "confidence": <0..1>, '
    '"reason": "<max 12 words>"}\n'
    "Allowed category values (use exactly, including underscores): "
    + ", ".join(schemas.CATEGORIES)
    + ".\nPick 'Other' only when nothing else plausibly fits."
)


def _groq_configured() -> bool:
    return bool(getattr(settings, "GROQ_API_KEY", "") or "")


def groq_category(text: str, timeout: float = 8.0) -> tuple[str, float, str]:
    """Classify via Groq. Raises QuotaExhausted on 429, RuntimeError otherwise.

    Only the category is taken from the model; everything downstream comes
    from routing_rules, so a hallucinated department cannot reach the DB.
    """
    if not _groq_configured():
        raise RuntimeError("GROQ_API_KEY not configured")

    from app.shared import groq_failover

    payload = {
        "model": settings.GROQ_CLASSIFIER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text[:2000]},
        ],
        "temperature": 0,
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
    }
    resp = groq_failover.post_chat(payload, timeout=timeout)

    if resp.status_code == 429:
        raise QuotaExhausted("Groq rate limit / daily token cap reached")
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq HTTP {resp.status_code}: {resp.text[:200]}")

    content = resp.json()["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Groq returned non-JSON: {content[:120]}") from e

    cat = schemas.normalize_category(str(parsed.get("category", "")))
    if cat is None:
        raise RuntimeError(f"Groq returned unknown category: {parsed.get('category')!r}")
    try:
        conf = float(parsed.get("confidence", 0.7))
    except (TypeError, ValueError):
        conf = 0.7
    reason = str(parsed.get("reason", ""))[:120]
    return cat, max(0.0, min(conf, 1.0)), reason


# --------------------------------------------------------------------------
# Priority
# --------------------------------------------------------------------------
def _bump(priority: str, steps: int = 1) -> str:
    i = _PRIORITY_ORDER.index(priority) if priority in _PRIORITY_ORDER else 1
    return _PRIORITY_ORDER[min(i + steps, len(_PRIORITY_ORDER) - 1)]


def derive_priority(
    text: str,
    category_default: str,
    sentiment_label: str,
    compound: float,
) -> tuple[str, list[str]]:
    """Category default, escalated by urgency cues and sentiment intensity.

    Only ever escalates — a calmly-worded report of a fire is still a fire,
    so sentiment never lowers priority.

    CRITICAL is reachable *only* via an explicit life-safety term. Urgency
    cues and sentiment cap out at HIGH, so an angrily-worded pothole report
    cannot outrank a live wire over a playground.
    """
    low = (text or "").lower()
    reasons: list[str] = [f"{category_default} default for category"]
    priority = category_default

    crit = sorted(t for t in _CRITICAL_TERMS if t in low)
    if crit:
        reasons.append(f"life-safety cue: {crit[0]}")
        return "CRITICAL", reasons

    def _bump_capped(p: str) -> str:
        """Escalate one step, but never past HIGH."""
        nxt = _bump(p)
        return "HIGH" if _PRIORITY_ORDER.index(nxt) > _PRIORITY_ORDER.index("HIGH") else nxt

    urgent = sorted(t for t in _URGENCY_TERMS if t in low)
    if urgent:
        priority = _bump_capped(priority)
        reasons.append(f"urgency cue: {urgent[0]}")

        # A hazard near a vulnerable population is worth a second look, but
        # still not automatically life-safety.
        vulnerable = sorted(t for t in _VULNERABLE_TERMS if t in low)
        if vulnerable:
            priority = _bump_capped(priority)
            reasons.append(f"vulnerable population: {vulnerable[0]}")

    if sentiment_label == "negative" and compound <= _SENTIMENT_ESCALATION_THRESHOLD:
        before = priority
        priority = _bump_capped(priority)
        if priority != before:
            reasons.append(f"outlier negative sentiment ({compound:.2f})")

    return priority, reasons


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def classify(
    subject: str,
    description: str,
    category_override: Optional[str] = None,
    priority_override: Optional[str] = None,
) -> dict[str, Any]:
    """Full classification. Never raises — always returns a usable result.

    `source` reports which path actually answered, and `quota_exhausted`
    is set only when Groq was genuinely rate-limited.
    """
    raw = f"{subject}\n\n{description}".strip()
    text = redact_pii(raw)

    rules = _rules_by_category()
    sentiment_label, compound = sentiment_of(text)

    source = "rules"
    quota_exhausted = False
    reason_bits: list[str] = []
    category: Optional[str] = schemas.normalize_category(category_override)
    confidence = 1.0 if category else 0.0

    if category:
        reason_bits.append("category chosen by citizen")
    else:
        # 1) Groq
        if _groq_configured():
            try:
                category, confidence, why = groq_category(text)
                source = "groq"
                if why:
                    reason_bits.append(why)
            except QuotaExhausted:
                quota_exhausted = True
                log.warning("Groq quota exhausted — falling back to rule router")
            except Exception as e:  # noqa: BLE001
                log.warning("Groq classification failed (%s) — falling back to rules", e)

        # 2) Rule router
        if category is None:
            category, confidence, hits = rule_category(text, rules)
            source = "rules"
            if category:
                reason_bits.append("keyword match: " + ", ".join(hits[:3]))

        # 3) Nothing matched — say so rather than guess a wrong department
        if category is None:
            category = "Other"
            confidence = 0.25
            source = "rules"
            reason_bits.append("no category signal found")

    rule = rules.get(category) or rules.get("Other") or {}
    department = rule.get("department") or "PWD"
    sla_hours = int(rule.get("sla_hours") or 48)
    cat_default_priority = rule.get("default_priority") or "NORMAL"

    if priority_override and priority_override != "AUTO":
        priority = priority_override
        priority_was_auto = False
        reason_bits.append("priority set by citizen")
    else:
        priority, why = derive_priority(text, cat_default_priority, sentiment_label, compound)
        priority_was_auto = True
        reason_bits.extend(why)

    # A citizen-raised priority tightens the SLA; it must not loosen it.
    if priority == "CRITICAL":
        sla_hours = min(sla_hours, 4)
    elif priority == "HIGH":
        sla_hours = min(sla_hours, 12)

    due = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
    label = f"{sla_hours} hours" if sla_hours < 24 else f"{sla_hours // 24} days"

    summary = f"{schemas.DISPLAY_CATEGORY.get(category, category)} → {department} {priority}"
    if reason_bits:
        summary += " · " + "; ".join(reason_bits[:2])

    return {
        "predicted_category": category,
        "display_category": schemas.DISPLAY_CATEGORY.get(category, category),
        "predicted_priority": priority,
        "priority_was_auto": priority_was_auto,
        "predicted_department": department,
        "predicted_sla_label": label,
        "predicted_sla_due_at": due,
        "sla_hours": sla_hours,
        "sentiment": sentiment_label,
        "sentiment_compound": round(compound, 3),
        "confidence": round(float(confidence), 2),
        "reasoning_summary": summary[:300],
        "source": source,
        "quota_exhausted": quota_exhausted,
    }


def classifier_status() -> dict[str, Any]:
    """What the *next* classification will actually do. Used by /health."""
    rules = repo.routing_rules()
    configured = _groq_configured()
    if configured:
        mode = "groq"
    elif rules:
        mode = "rules"
    else:
        mode = "unavailable"
    return {
        "mode": mode,
        "groq_configured": configured,
        "groq_model": settings.GROQ_CLASSIFIER_MODEL if configured else None,
        "rules_loaded": len(rules),
        "vader_available": vader_available(),
    }
