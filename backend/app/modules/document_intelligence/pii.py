"""
PII detection — two layers:
  Layer 1: regex patterns for Indian PII (Aadhaar, PAN, phone, GST, email, bank-account).
  Layer 2: spaCy NER (PERSON / ORG / GPE) for general entities.

Returns a dict shaped to match the API response in the build prompt:
  {
    "<pii_type>": {"count": int, "status": "REDACTED"|"FLAGGED", "confidence": float, "positions": [...], "note": str?}
  }
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("citadel.pii")

# ----------------------------------------------------------------
# Regex patterns
# ----------------------------------------------------------------
PATTERNS: list[tuple[str, str, re.Pattern]] = [
    # (key, label, compiled regex)
    ("aadhaar_fragment", "Aadhaar Fragment", re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")),
    ("pan_number",       "PAN Number",       re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("phone_number",     "Phone Number",     re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{9}\b")),
    ("gst_number",       "GST Number",       re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b")),
    ("email_address",    "Email Address",    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]

# Bank account is contextual — only flag if near "account", "a/c", "bank"
BANK_NUM_RE = re.compile(r"\b\d{9,18}\b")
BANK_CONTEXT_RE = re.compile(r"\b(account|a/c|bank|ifsc)\b", re.IGNORECASE)
BANK_CONTEXT_WINDOW = 60  # chars on either side

LOW_CONFIDENCE_THRESHOLD = 70.0


@dataclass
class PIIFinding:
    type: str
    label: str
    matches: list[str] = field(default_factory=list)
    positions: list[tuple[int, int]] = field(default_factory=list)
    confidence: float = 100.0    # regex matches default to 100%
    note: Optional[str] = None


# ----------------------------------------------------------------
# spaCy lazy loader (loading is slow; cache the nlp object)
# ----------------------------------------------------------------
_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception as e:
            log.warning("spaCy unavailable (run: python -m spacy download en_core_web_sm). Error: %s", e)
            _nlp = False  # marker = tried and failed
    return _nlp if _nlp is not False else None


# ----------------------------------------------------------------
# Detection
# ----------------------------------------------------------------
def _detect_regex(text: str) -> dict[str, PIIFinding]:
    out: dict[str, PIIFinding] = {}
    for key, label, pat in PATTERNS:
        finds: list[re.Match] = list(pat.finditer(text))
        if not finds:
            continue
        f = PIIFinding(type=key, label=label)
        for m in finds:
            f.matches.append(m.group(0))
            f.positions.append((m.start(), m.end()))
        out[key] = f

    # bank account contextual
    bank_matches = []
    bank_positions = []
    for m in BANK_NUM_RE.finditer(text):
        s, e = m.span()
        ctx_lo, ctx_hi = max(0, s - BANK_CONTEXT_WINDOW), min(len(text), e + BANK_CONTEXT_WINDOW)
        if BANK_CONTEXT_RE.search(text[ctx_lo:ctx_hi]):
            bank_matches.append(m.group(0))
            bank_positions.append((s, e))
    if bank_matches:
        out["bank_account"] = PIIFinding(
            type="bank_account",
            label="Bank Account",
            matches=bank_matches,
            positions=bank_positions,
            confidence=85.0,    # contextual — not as certain as regex-only
        )
    return out


def _detect_spacy(text: str) -> dict[str, PIIFinding]:
    nlp = _get_nlp()
    if nlp is None:
        return {}
    out: dict[str, PIIFinding] = {}
    try:
        doc = nlp(text[:1_000_000])  # cap to 1MB of chars to be safe
    except Exception as e:
        log.warning("spaCy parse failed: %s", e)
        return {}

    for ent in doc.ents:
        if ent.label_ not in {"PERSON", "ORG", "GPE"}:
            continue
        key = f"ner_{ent.label_.lower()}"
        if key not in out:
            label_map = {"ner_person": "Person Name", "ner_org": "Organization", "ner_gpe": "Location"}
            out[key] = PIIFinding(
                type=key,
                label=label_map.get(key, ent.label_),
                confidence=80.0,    # spaCy small model is decent but not perfect
            )
        f = out[key]
        f.matches.append(ent.text)
        f.positions.append((ent.start_char, ent.end_char))
    return out


def detect_pii(text: str) -> dict[str, dict]:
    """
    Public entry point. Returns:
      {
        "aadhaar_fragment": {"count": 1, "status": "REDACTED", "confidence": 100.0, "positions": [...]},
        ...
      }
    """
    if not text:
        return {}

    findings: dict[str, PIIFinding] = {}
    findings.update(_detect_regex(text))
    findings.update(_detect_spacy(text))

    result: dict[str, dict] = {}
    for key, f in findings.items():
        status = "REDACTED" if f.confidence >= LOW_CONFIDENCE_THRESHOLD else "FLAGGED"
        entry = {
            "label": f.label,
            "count": len(f.positions),
            "status": status,
            "confidence": f.confidence,
            "positions": f.positions,
        }
        if f.confidence < LOW_CONFIDENCE_THRESHOLD:
            entry["note"] = f"Low confidence on {f.label} format — recommend manual verify"
        result[key] = entry
    return result


def redact_text(text: str, findings: dict[str, dict]) -> str:
    """
    Replace every detected PII span with '[REDACTED]'.
    Spans are merged + applied right-to-left so positions stay valid.
    """
    spans: list[tuple[int, int]] = []
    for f in findings.values():
        spans.extend((s, e) for s, e in f.get("positions", []))
    if not spans:
        return text

    # merge overlaps
    spans.sort()
    merged: list[list[int]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    # apply right-to-left
    out = list(text)
    for s, e in reversed(merged):
        out[s:e] = list("[REDACTED]")
    return "".join(out)


def total_pii_count(findings: dict[str, dict]) -> int:
    return sum(f.get("count", 0) for f in findings.values())
