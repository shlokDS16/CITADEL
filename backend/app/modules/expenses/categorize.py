"""
Layered expense categorisation.

Order of consultation — cheapest, most-explainable layer first; each layer
only runs when every layer above it declined:

  0. citizen override        — the human said so; confidence 1.0
  1. merchant cache (DB)     — a previous LLM label or human correction
                               for this merchant_key; sub-ms, free
  2. curated lexicon         — exact/substring match (merchants.py)
  3. fuzzy lexicon           — rapidfuzz partial-ratio, strict cutoff
  4. TF-IDF + LinearSVC      — trained from the lexicon itself plus every
                               human-corrected row; covers phrasings the
                               patterns miss ("monthly metro pass renewal")
  5. Groq (once per merchant)— ONLY for a genuinely unseen merchant, and
                               the answer is written to the cache so the
                               same merchant never costs tokens again
  6. "Other", low confidence — honest fallback, flagged for review

Latency: layers 0-3 are sub-ms; layer 4 is ~1ms after first fit (model is
process-cached); layer 5 is the only network hop and is amortised to zero
by the cache. This meets the spec's <50ms budget for everything except a
brand-new merchant's first-ever transaction.

Why the model trains from the lexicon instead of a shipped corpus: the
spec imagines "~50k labeled Indian merchant entries" which do not exist in
this repo, and inventing them would be mock data. The lexicon IS the
labelled corpus we actually have (~400 real patterns); the SVC
generalises it (word order, extra tokens, inflections) and improves as
human corrections accumulate in expense_merchant_cache.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

from app.modules.expenses import merchants

log = logging.getLogger("citadel.expenses.categorize")

#: below this, the category is applied but flagged for review (spec-08 /
#: ml-conventions.md auto-apply default).
AUTO_APPLY_THRESHOLD = 0.75

#: below this, the SVC's answer is noise between neighbours — presenting
#: it as a category would be a guess wearing a label. Fall to "Other".
SVC_FLOOR = 0.30

#: in-process memo over expense_merchant_cache. The DB cache is ~50ms of
#: network away (Supabase ap-south-1); without this memo every repeat
#: merchant paid that latency and the spec's <50ms budget was blown by the
#: cache lookup itself. 60s TTL keeps human corrections near-live.
_MEMO_TTL_SECONDS = 60.0
_MEMO_MAX = 2048
_memo: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}


# --------------------------------------------------------------------------
# Layer 1 — merchant cache
# --------------------------------------------------------------------------
def _sb():  # noqa: ANN202
    try:
        from app.database import get_supabase

        return get_supabase()
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase unavailable: %s", e)
        return None


def cache_get(key: str) -> Optional[dict[str, Any]]:
    if not key or key == "unknown":
        return None
    # in-process memo first — negative results are memoised too, so a
    # lexicon-covered merchant doesn't pay the network hop on every call
    import time as _time

    now = _time.monotonic()
    hit = _memo.get(key)
    if hit and now - hit[0] < _MEMO_TTL_SECONDS:
        return hit[1]

    sb = _sb()
    if sb is None:
        return None
    try:
        rows = (
            sb.table("expense_merchant_cache").select("*")
            .eq("merchant_key", key).limit(1).execute()
        ).data or []
        row = rows[0] if rows else None
        if len(_memo) >= _MEMO_MAX:
            _memo.clear()
        _memo[key] = (now, row)
        if row is not None:
            try:  # best-effort hit counter; never blocks the answer
                sb.table("expense_merchant_cache").update(
                    {"hits": int(row.get("hits") or 0) + 1}
                ).eq("merchant_key", key).execute()
            except Exception:  # noqa: BLE001
                pass
        return row
    except Exception as e:  # noqa: BLE001
        log.debug("cache_get failed: %s", e)
        return None


def cache_put(key: str, category: str, confidence: float, source: str) -> None:
    """Write-through label memo. `source` is llm | human | model.

    A human correction always wins: it overwrites anything; an llm/model
    label never overwrites a human one.
    """
    sb = _sb()
    if sb is None or not key or key == "unknown":
        return
    if category not in merchants.CATEGORIES:
        return
    _memo.pop(key, None)   # a fresh label must be visible immediately
    try:
        existing = (
            sb.table("expense_merchant_cache").select("source")
            .eq("merchant_key", key).limit(1).execute()
        ).data or []
        if existing and existing[0].get("source") == "human" and source != "human":
            return
        row = {
            "merchant_key": key,
            "category": category,
            "confidence": round(float(confidence), 4),
            "source": source,
        }
        if existing:
            sb.table("expense_merchant_cache").update(row).eq("merchant_key", key).execute()
        else:
            sb.table("expense_merchant_cache").insert(row).execute()
    except Exception as e:  # noqa: BLE001
        log.debug("cache_put failed: %s", e)


# --------------------------------------------------------------------------
# Layer 4 — TF-IDF + LinearSVC, self-trained from the lexicon + corrections
# --------------------------------------------------------------------------
_MODEL_LOCK = threading.Lock()
_MODEL: Optional[tuple[Any, Any]] = None        # (vectorizer, classifier)
_MODEL_CORPUS_SIZE = 0


def _training_rows() -> list[tuple[str, str]]:
    """(text, category) pairs: every lexicon pattern + human-corrected
    cache rows. The lexicon is real curated data, not synthesised."""
    rows: list[tuple[str, str]] = []
    for cat, pats in merchants.LEXICON.items():
        for p in pats:
            rows.append((p, cat))
    sb = _sb()
    if sb is not None:
        try:
            extra = (
                sb.table("expense_merchant_cache")
                .select("merchant_key, category, source")
                .eq("source", "human").limit(2000).execute()
            ).data or []
            for r in extra:
                k, c = r.get("merchant_key"), r.get("category")
                if k and c in merchants.CATEGORIES:
                    rows.append((k, c))
        except Exception as e:  # noqa: BLE001
            log.debug("corrections fetch failed: %s", e)
    return rows


def _fit_model() -> Optional[tuple[Any, Any]]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.svm import LinearSVC
    except ImportError:
        log.warning("scikit-learn unavailable — SVC layer disabled")
        return None
    rows = _training_rows()
    if len(rows) < 50:
        return None
    texts = [t for t, _ in rows]
    labels = [c for _, c in rows]
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True, min_df=1)
    x = vec.fit_transform(texts)
    clf = LinearSVC(C=1.0)
    clf.fit(x, labels)
    global _MODEL_CORPUS_SIZE
    _MODEL_CORPUS_SIZE = len(rows)
    return vec, clf


def _model() -> Optional[tuple[Any, Any]]:
    global _MODEL
    if _MODEL is None:
        with _MODEL_LOCK:
            if _MODEL is None:
                _MODEL = _fit_model()
    return _MODEL


def refit_model() -> int:
    """Refit after human corrections accumulate. Returns corpus size."""
    global _MODEL
    with _MODEL_LOCK:
        _MODEL = _fit_model()
    return _MODEL_CORPUS_SIZE


def svc_predict(text: str) -> Optional[tuple[str, float, list[tuple[str, float]]]]:
    """(category, confidence, top-3 alternates) or None.

    LinearSVC has no predict_proba; decision_function margins are squashed
    into a softmax-ish confidence. Margins near zero mean the model is
    guessing between neighbours — that lands under AUTO_APPLY_THRESHOLD by
    construction, which is exactly the honest behaviour we want.
    """
    m = _model()
    if m is None:
        return None
    n = merchants.normalize(text)
    if not n:
        return None
    vec, clf = m
    import numpy as np

    scores = clf.decision_function(vec.transform([n]))[0]
    order = np.argsort(scores)[::-1]
    exp = np.exp(scores - scores.max())
    probs = exp / exp.sum()
    top = [(str(clf.classes_[i]), round(float(probs[i]), 4)) for i in order[:3]]
    cat, conf = top[0]
    return cat, conf, top


# --------------------------------------------------------------------------
# Layer 5 — Groq, once per merchant
# --------------------------------------------------------------------------
class QuotaExhausted(RuntimeError):
    pass


_SYSTEM_PROMPT = (
    "You classify a single Indian personal-finance transaction narration "
    "into a spending category. Reply ONLY with JSON: "
    '{"category": "<value>", "confidence": <0..1>}. '
    "Allowed values (exact): " + ", ".join(merchants.CATEGORIES) + "."
)


def groq_category(text: str, timeout: float = 8.0) -> tuple[str, float]:
    from app.config import settings

    if not getattr(settings, "GROQ_API_KEY", ""):
        raise RuntimeError("GROQ_API_KEY not configured")
    from app.shared import groq_failover

    payload = {
        "model": settings.GROQ_CLASSIFIER_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text[:300]},
        ],
        "temperature": 0,
        "max_tokens": 60,
        "response_format": {"type": "json_object"},
    }
    resp = groq_failover.post_chat(payload, timeout=timeout)
    if resp.status_code == 429:
        raise QuotaExhausted("Groq rate limited")
    if resp.status_code >= 400:
        raise RuntimeError(f"Groq HTTP {resp.status_code}")
    parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
    cat = str(parsed.get("category", "")).strip()
    if cat not in merchants.CATEGORIES:
        raise RuntimeError(f"Groq returned unknown category {cat!r}")
    try:
        conf = max(0.0, min(float(parsed.get("confidence", 0.8)), 1.0))
    except (TypeError, ValueError):
        conf = 0.8
    return cat, conf


# --------------------------------------------------------------------------
# Public entry
# --------------------------------------------------------------------------
def categorize(
    description: str,
    merchant: Optional[str] = None,
    category_override: Optional[str] = None,
    allow_llm: bool = True,
) -> dict[str, Any]:
    """Never raises. Returns:
    { category, confidence, source, alternates, merchant_key,
      needs_review, quota_exhausted }
    `source` names the layer that actually answered.
    """
    text = " ".join(t for t in (description or "", merchant or "") if t).strip()
    # Cache key comes from the MERCHANT field when given, not the joined
    # text: "Uber ride to office" + merchant "Uber India" must hit the
    # same cache row as every other Uber transaction. Free-text
    # descriptions without a merchant key per-phrase — bounded cost (one
    # LLM call per unique phrasing, still cached), and the deliberate
    # trade: aggressive single-token collapsing would merge hdfc-life
    # into hdfc-bank and reliance-fresh into reliance-digital.
    key = merchants.merchant_key(merchant if merchant else description)
    quota_exhausted = False

    if category_override and category_override in merchants.CATEGORIES:
        return {
            "category": category_override, "confidence": 1.0, "source": "citizen",
            "alternates": [], "merchant_key": key, "needs_review": False,
            "quota_exhausted": False,
        }

    # 1 — cache
    hit = cache_get(key)
    if hit:
        conf = float(hit.get("confidence") or 0.9)
        return {
            "category": hit["category"], "confidence": conf,
            "source": f"cache:{hit.get('source', 'llm')}", "alternates": [],
            "merchant_key": key, "needs_review": conf < AUTO_APPLY_THRESHOLD,
            "quota_exhausted": False,
        }

    # 2 — lexicon
    lex = merchants.lexicon_lookup(text)
    if lex:
        cat, conf = lex
        return {
            "category": cat, "confidence": conf, "source": "lexicon",
            "alternates": [], "merchant_key": key, "needs_review": False,
            "quota_exhausted": False,
        }

    # 3 — fuzzy
    fz = merchants.fuzzy_lookup(text)
    if fz:
        cat, conf = fz
        return {
            "category": cat, "confidence": conf, "source": "fuzzy",
            "alternates": [], "merchant_key": key,
            "needs_review": conf < AUTO_APPLY_THRESHOLD, "quota_exhausted": False,
        }

    # 4 — SVC
    sv = svc_predict(text)
    if sv and sv[1] >= AUTO_APPLY_THRESHOLD:
        cat, conf, alts = sv
        return {
            "category": cat, "confidence": conf, "source": "model",
            "alternates": alts, "merchant_key": key, "needs_review": False,
            "quota_exhausted": False,
        }

    # 5 — Groq, once per merchant key, only for a real merchant phrase
    if allow_llm and key != "unknown" and len(key) >= 3:
        try:
            cat, conf = groq_category(text)
            cache_put(key, cat, conf, "llm")
            return {
                "category": cat, "confidence": conf, "source": "llm",
                "alternates": sv[2] if sv else [], "merchant_key": key,
                "needs_review": conf < AUTO_APPLY_THRESHOLD,
                "quota_exhausted": False,
            }
        except QuotaExhausted:
            quota_exhausted = True
            log.warning("Groq quota drained — expense falls back to model/Other")
        except Exception as e:  # noqa: BLE001
            log.warning("Groq categorise failed: %s", e)

    # 6 — best remaining answer, honestly low-confidence. Below SVC_FLOOR
    # the model is choosing between neighbours at random — that is not a
    # prediction, so "Other" + review is the truthful output.
    if sv and sv[1] >= SVC_FLOOR:
        cat, conf, alts = sv
        return {
            "category": cat, "confidence": conf, "source": "model",
            "alternates": alts, "merchant_key": key, "needs_review": True,
            "quota_exhausted": quota_exhausted,
        }
    return {
        "category": "Other", "confidence": 0.3, "source": "fallback",
        "alternates": sv[2] if sv else [], "merchant_key": key,
        "needs_review": True, "quota_exhausted": quota_exhausted,
    }


def correct(description: str, merchant: Optional[str], category: str) -> str:
    """Record a human correction for this merchant — the strongest label.
    Returns the merchant_key written. Keying MUST mirror categorize()
    exactly, or the correction lands under a key lookups never use."""
    key = merchants.merchant_key(merchant if merchant else description)
    cache_put(key, category, 0.99, "human")
    return key


def model_status() -> dict[str, Any]:
    m = _model()
    return {
        "svc_loaded": m is not None,
        "corpus_size": _MODEL_CORPUS_SIZE,
        "auto_apply_threshold": AUTO_APPLY_THRESHOLD,
    }
