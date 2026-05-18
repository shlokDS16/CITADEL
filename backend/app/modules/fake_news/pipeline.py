"""
Layer 2 — fast transformer classifiers (the production "fast path").

Models (all public HF repos, CPU inference, lazy + singleton-cached):
  - fake-news style ...... vikram71198/distilroberta-base-finetuned-fake-news
  - clickbait ............ valurank/distilroberta-clickbait
  - bias / loaded language d4data/bias-detection-model
  - propaganda technique . QCRI/PropagandaTechniquesAnalysis-en-BERT  (heavy)
  - sentiment ............ VADER lexicon (no model — spec-06 §262)

Design notes:
  * Label conventions differ per repo (LABEL_0/1 vs named). Instead of
    hard-coding, each binary head **self-calibrates at load**: it scores one
    canonical positive and one canonical negative example and records which
    output label is the "risk" class. Robust + self-verifying.
  * Everything degrades gracefully — a model that fails to load returns
    ``available=False`` and the waterfall continues without it.
  * Heavy models gated by ``settings.FN_ENABLE_HEAVY_MODELS`` so a
    constrained deployment can run a lean profile.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import lru_cache

from app.config import settings

log = logging.getLogger("citadel.fake_news.pipeline")

# Route HF cache into the (git-ignored) module models dir before transformers
# is imported. Symlink warning is noise on non-dev-mode Windows.
os.environ.setdefault("HF_HOME", settings.FN_MODELS_DIR)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_DEVICE = -1          # CPU
_MAX_LEN = 512
_MIN_CHARS = 25       # below this, transformer signal is unreliable
_LOAD_LOCK = threading.Lock()

# Canonical calibration pairs: (risk-positive example, neutral example).
_CAL = {
    "fake": (
        "SHOCKING: the government secretly replaced the president with a "
        "robot clone, anonymous insiders reveal!!!",
        "The central bank kept its benchmark interest rate unchanged at its "
        "scheduled review this week, in line with economist expectations.",
    ),
    "clickbait": (
        "You won't believe what happened next — number 7 will absolutely "
        "shock you!",
        "Quarterly gross domestic product grew 2 percent, official data "
        "released on Friday showed.",
    ),
    "bias": (
        "Those corrupt, evil politicians are obviously destroying everything "
        "good about this country.",
        "The agency published its quarterly report on its website on Monday "
        "morning.",
    ),
}


# --------------------------------------------------------------------------
# Lazy singletons
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _tc(model_id: str):  # noqa: ANN202
    """Load a text-classification pipeline (cached). Raises on failure."""
    from transformers import pipeline as hf_pipeline

    with _LOAD_LOCK:
        log.info("loading text-classification model: %s", model_id)
        return hf_pipeline(
            "text-classification", model=model_id, tokenizer=model_id,
            top_k=None, device=_DEVICE, truncation=True, max_length=_MAX_LEN,
        )


def _scores(pipe, text: str) -> dict[str, float]:  # noqa: ANN001
    raw = pipe(text)
    if raw and isinstance(raw[0], list):     # top_k=None → [[{...},{...}]]
        raw = raw[0]
    return {d["label"]: float(d["score"]) for d in raw}


# Minimum pos-vs-neg score separation for a head to be trusted. Some public
# "fake news" repos overfit their training set and collapse to one class on
# general text (verified: vikram71198 predicts the same label ~0.999 for both
# true and absurd sentences, gap ~0.0003). Such a head is non-discriminative
# noise and is excluded rather than silently dragging the verdict. 0.10 keeps
# weak-but-real heads (e.g. a clickbait head that only ever *raises* the score
# via max()) while still excluding the degenerate ones.
_CAL_MIN_GAP = 0.10
_STD_SEQ = "ForSequenceClassification"
_STD_TOK = "ForTokenClassification"


@lru_cache(maxsize=8)
def _calibrate(model_id: str, kind: str) -> tuple[str | None, float]:
    """Self-calibrate: (risk-positive label, discrimination gap)."""
    pos, neg = _CAL[kind]
    try:
        pipe = _tc(model_id)
        sp, sn = _scores(pipe, pos), _scores(pipe, neg)
        best, gap = None, -2.0
        for lbl in sp:
            g = sp.get(lbl, 0.0) - sn.get(lbl, 0.0)
            if g > gap:
                best, gap = lbl, g
        log.info("calibrated %s (%s) -> risk label %r (gap %.3f)",
                 kind, model_id, best, gap)
        return best, round(gap, 4)
    except Exception as e:  # noqa: BLE001
        log.warning("calibration failed for %s: %s", model_id, e)
        return None, 0.0


def _binary_risk(model_id: str, kind: str, text: str) -> dict:
    """Risk probability for a self-calibrated binary classifier.

    A head that fails the discrimination check returns ``available=False``
    with a reason — the waterfall then simply runs without it.
    """
    try:
        risk_lbl, gap = _calibrate(model_id, kind)
        if risk_lbl is None:
            return {"available": False, "score": 0.0, "discriminative": False,
                    "calibration_gap": gap,
                    "reason": f"{kind} model failed to load or calibrate "
                              f"(repo may lack PyTorch/safetensors weights) — "
                              f"excluded from scoring"}
        if abs(gap) < _CAL_MIN_GAP:
            return {"available": False, "score": 0.0, "discriminative": False,
                    "calibration_gap": gap,
                    "reason": f"{kind} model not discriminative on general text "
                              f"(calibration gap {gap:.3f}) — excluded from scoring"}
        pipe = _tc(model_id)
        sc = _scores(pipe, text)
        p = sc.get(risk_lbl, max(sc.values()) if sc else 0.0)
        return {"available": True, "score": round(p, 4), "risk_label": risk_lbl,
                "calibration_gap": gap,
                "raw": {k: round(v, 4) for k, v in sc.items()}}
    except Exception as e:  # noqa: BLE001
        log.warning("%s inference failed: %s", kind, e)
        return {"available": False, "error": str(e), "score": 0.0}


# --------------------------------------------------------------------------
# Public classifiers
# --------------------------------------------------------------------------
def classify_fake_news(text: str) -> dict:
    """Fabrication-style probability (NOT a truth oracle — a style signal)."""
    if len(text.strip()) < _MIN_CHARS:
        return {"available": True, "score": 0.0, "note": "text too short"}
    return _binary_risk(settings.FN_MODEL_FAKE, "fake", text)


def classify_clickbait(text: str) -> dict:
    if len(text.strip()) < _MIN_CHARS:
        return {"available": True, "score": 0.0, "note": "text too short"}
    return _binary_risk(settings.FN_MODEL_CLICKBAIT, "clickbait", text)


def classify_bias(text: str) -> dict:
    if len(text.strip()) < _MIN_CHARS:
        return {"available": True, "score": 0.0, "note": "text too short"}
    return _binary_risk(settings.FN_MODEL_BIAS, "bias", text)


@lru_cache(maxsize=1)
def _propaganda_pipe():  # noqa: ANN202
    """Propaganda model — architecture-aware (token vs sequence)."""
    from transformers import AutoConfig
    from transformers import pipeline as hf_pipeline

    mid = settings.FN_MODEL_PROPAGANDA
    cfg = AutoConfig.from_pretrained(mid)
    arch_list = list(getattr(cfg, "architectures", None) or [])
    is_tok = any(a.endswith(_STD_TOK) for a in arch_list)
    is_seq = any(a.endswith(_STD_SEQ) for a in arch_list)
    if not (is_tok or is_seq):
        # e.g. QCRI's BertForTokenAndSequenceJointClassification is a custom
        # joint head that needs trust_remote_code and is not pipeline-safe —
        # refuse rather than emit meaningless LABEL_0/1 noise.
        raise ValueError(
            f"unsupported propaganda model architecture {arch_list!r} "
            f"(not a standard sequence/token classifier) — excluded")
    with _LOAD_LOCK:
        if is_tok:
            log.info("loading propaganda (token-classification): %s", mid)
            return ("token", hf_pipeline(
                "token-classification", model=mid, tokenizer=mid,
                device=_DEVICE, aggregation_strategy="simple"))
        log.info("loading propaganda (text-classification): %s", mid)
        return ("seq", hf_pipeline(
            "text-classification", model=mid, tokenizer=mid, top_k=None,
            device=_DEVICE, truncation=True, max_length=_MAX_LEN))


def detect_propaganda(text: str) -> dict:
    """Propaganda technique tags + an overall propaganda score (heavy/gated)."""
    if not settings.FN_ENABLE_HEAVY_MODELS:
        return {"available": False, "reason": "heavy models disabled"}
    if len(text.strip()) < _MIN_CHARS:
        return {"available": True, "techniques": [], "score": 0.0}
    try:
        mode, pipe = _propaganda_pipe()
        techniques: list[str] = []
        if mode == "token":
            ents = pipe(text[:2000]) or []
            techniques = sorted({
                str(e.get("entity_group") or e.get("entity"))
                for e in ents
                if str(e.get("entity_group") or e.get("entity")).upper() not in ("O", "OTHER")
            })
            score = min(1.0, len(ents) / 6.0)
        else:
            out = pipe(text)
            if out and isinstance(out[0], list):
                out = out[0]
            ranked = sorted(out, key=lambda d: d["score"], reverse=True)
            top = ranked[0]
            neg = {"o", "other", "not_propaganda", "non-propaganda", "none", "no_technique"}
            if top["label"].strip().lower() in neg:
                score = round(1.0 - float(top["score"]), 4)
            else:
                score = round(float(top["score"]), 4)
                techniques = [d["label"] for d in ranked[:3] if d["score"] >= 0.30
                              and d["label"].strip().lower() not in neg]
        return {"available": True, "techniques": techniques, "score": float(score)}
    except Exception as e:  # noqa: BLE001
        log.warning("propaganda inference failed: %s", e)
        return {"available": False, "error": str(e), "techniques": [], "score": 0.0}


# --------------------------------------------------------------------------
# Sentiment — VADER lexicon (fast, no model)
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _vader():  # noqa: ANN202
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    return SentimentIntensityAnalyzer()


def sentiment(text: str) -> dict:
    """Return {positive, negative, neutral} percentages summing to ~100."""
    try:
        s = _vader().polarity_scores(text[:5000])
        pos = int(round(s["pos"] * 100))
        neg = int(round(s["neg"] * 100))
        neu = max(0, 100 - pos - neg)
        return {"available": True, "positive": pos, "negative": neg,
                "neutral": neu, "compound": round(s["compound"], 4)}
    except Exception as e:  # noqa: BLE001
        log.warning("sentiment failed: %s", e)
        return {"available": False, "positive": 0, "negative": 0, "neutral": 100,
                "compound": 0.0}


def warmup() -> dict:
    """Eagerly load + calibrate every L2 model. Used by the warmup endpoint
    and (optionally) the lifespan pre-warm so the first request is fast."""
    status: dict[str, object] = {}
    for name, fn in (
        ("fake_news", lambda: classify_fake_news("warmup probe sentence for the model loader.")),
        ("clickbait", lambda: classify_clickbait("warmup probe sentence for the model loader.")),
        ("bias", lambda: classify_bias("warmup probe sentence for the model loader.")),
        ("propaganda", lambda: detect_propaganda("warmup probe sentence for the model loader.")),
        ("sentiment", lambda: sentiment("warmup probe sentence.")),
    ):
        try:
            r = fn()
            status[name] = r.get("available", True)
        except Exception as e:  # noqa: BLE001
            status[name] = f"error: {e}"
    return status
